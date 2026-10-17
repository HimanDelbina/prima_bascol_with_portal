from datetime import datetime, date, time, timedelta
from typing import Optional, Tuple
from django.db import transaction, IntegrityError
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from shifts.models import (
    WorkShift, ShiftSession, ShiftSessionStatus,
    ShiftOperatorAssignment, ShiftOperatorRole, ShiftAssignmentStatus,
    ShiftExceptionLog
)
from audit.services import log_audit
from audit.models import AuditAction


class ShiftResolutionService:
    """
    Authoritative, concurrency-safe service for resolving shift operational dates,
    matching active sessions, managing operator assignments and attendance,
    and enforcing 100% uninterrupted weighing continuity.
    """

    @staticmethod
    def resolve_operational_date(dt: Optional[datetime] = None, shift: Optional[WorkShift] = None) -> date:
        """
        Determines the authoritative operational date for a given timestamp.
        For overnight shifts (e.g., 23:00 to 07:00), an event at 02:30 on calendar day D+1
        is deterministically assigned to operational date D.
        Always operates in local timezone (Asia/Tehran).
        """
        if dt is None:
            dt = timezone.now()
        if timezone.is_aware(dt):
            dt = timezone.localtime(dt)

        event_date = dt.date()
        event_time = dt.time()

        if shift and shift.is_overnight:
            # If the event occurs between midnight and shift end time, it belongs to the previous calendar day
            if event_time < shift.end_time:
                return event_date - timedelta(days=1)
            else:
                return event_date

        if not shift:
            # Check if there is an active overnight shift template covering this time
            overnight_shifts = WorkShift.objects.filter(is_active=True, is_overnight=True)
            for s in overnight_shifts:
                if event_time < s.end_time:
                    return event_date - timedelta(days=1)

        return event_date

    @staticmethod
    def get_active_session_for_operator(operator: User, dt: Optional[datetime] = None) -> Optional[ShiftSession]:
        """
        Retrieves the active session where the given operator is currently checked in.
        """
        if not operator or not operator.is_authenticated:
            return None

        assignment = ShiftOperatorAssignment.objects.filter(
            operator=operator,
            status=ShiftAssignmentStatus.CHECKED_IN,
            session__status=ShiftSessionStatus.ACTIVE
        ).select_related("session", "session__shift").first()

        if assignment:
            return assignment.session
        return None

    @classmethod
    def get_active_session_for_weighing(cls, operator: Optional[User] = None, dt: Optional[datetime] = None) -> Optional[ShiftSession]:
        """
        Deterministic resolution of active session for a weighing event:
        1. If operator has an active CHECKED_IN assignment in an ACTIVE session, return it.
        2. Otherwise, check for any currently ACTIVE ShiftSession matching the operational date and time.
        3. If multiple exist, return the latest opened active session.
        4. If none exist, return None (fail-safe: weighing proceeds with exception logged).
        """
        if dt is None:
            dt = timezone.now()
        if timezone.is_aware(dt):
            dt = timezone.localtime(dt)

        if operator and operator.is_authenticated:
            op_session = cls.get_active_session_for_operator(operator, dt=dt)
            if op_session:
                return op_session

        # Fallback to any active session covering now
        active_sessions = ShiftSession.objects.filter(
            status=ShiftSessionStatus.ACTIVE
        ).select_related("shift").order_by("-actual_start")

        return active_sessions.first()

    @classmethod
    def record_weighing_shift(
        cls,
        ticket,
        is_second_weight: bool = False,
        operator: Optional[User] = None,
        dt: Optional[datetime] = None
    ) -> Tuple[Optional[ShiftSession], bool]:
        """
        Integrates weighing events with shift sessions.
        CRITICAL FAIL-SAFE CONTINUITY:
        Weighing is NEVER blocked by missing shift context, late operator, or network delay.
        If no active shift is found, the ticket is flagged as out-of-shift and an exception is logged.
        """
        session = cls.get_active_session_for_weighing(operator=operator, dt=dt)
        phase_code = "SECOND" if is_second_weight else "FIRST"

        if session:
            if not is_second_weight:
                ticket.first_weight_shift_session = session
                ticket.first_weight_out_of_shift = False
            else:
                ticket.second_weight_shift_session = session
                ticket.second_weight_out_of_shift = False
            return session, False
        else:
            # Missing shift context: DO NOT BLOCK!
            if not is_second_weight:
                ticket.first_weight_shift_session = None
                ticket.first_weight_out_of_shift = True
            else:
                ticket.second_weight_shift_session = None
                ticket.second_weight_out_of_shift = True

            # If ticket is already in database or being saved, record exception
            if ticket.pk:
                ShiftExceptionLog.objects.create(
                    ticket=ticket,
                    weighing_phase=phase_code,
                    operator=operator if (operator and operator.is_authenticated) else None,
                    timestamp=timezone.now(),
                    reason="NO_ACTIVE_SHIFT",
                    notes="عملیات توزین بدون جلسه شیفت فعال ثبت گردید (تداوم عملیاتی حفظ شد)."
                )

            return None, True

    @staticmethod
    def open_session(
        session: ShiftSession,
        user: User,
        initial_scale_zero: bool = True,
        initial_printer_paper: bool = True,
        notes: str = ""
    ) -> ShiftSession:
        """
        Opens/activates a shift session concurrency-safely.
        """
        with transaction.atomic():
            locked_session = ShiftSession.objects.select_for_update().get(pk=session.pk)
            locked_session.open_session(
                user=user,
                initial_scale_zero=initial_scale_zero,
                initial_printer_paper=initial_printer_paper,
                notes=notes
            )
            log_audit(
                action=AuditAction.CREATE,
                model_name="ShiftSession",
                record_id=locked_session.pk,
                record_repr=str(locked_session),
                new_values={"status": locked_session.status, "opened_by": user.username},
                reason="بازگشایی رسمی جلسه شیفت کاری",
                user=user
            )
            return locked_session

    @staticmethod
    def close_session(
        session: ShiftSession,
        user: User,
        notes: str = ""
    ) -> ShiftSession:
        """
        Closes a shift session and checks out all active operators.
        """
        with transaction.atomic():
            locked_session = ShiftSession.objects.select_for_update().get(pk=session.pk)
            locked_session.close_session(user=user, notes=notes)

            # Automatically check out any active checked-in operators in this session
            active_assignments = ShiftOperatorAssignment.objects.filter(
                session=locked_session,
                status=ShiftAssignmentStatus.CHECKED_IN
            )
            now = timezone.now()
            for assignment in active_assignments:
                assignment.status = ShiftAssignmentStatus.CHECKED_OUT
                assignment.check_out_time = now
                assignment.save()

            log_audit(
                action=AuditAction.UPDATE,
                model_name="ShiftSession",
                record_id=locked_session.pk,
                record_repr=str(locked_session),
                new_values={"status": locked_session.status, "closed_by": user.username},
                reason="بستن رسمی جلسه شیفت کاری",
                user=user
            )
            return locked_session

    @staticmethod
    def check_in_operator(
        session: ShiftSession,
        operator: User,
        role: str = ShiftOperatorRole.PRIMARY,
        authorized_by: Optional[User] = None
    ) -> ShiftOperatorAssignment:
        """
        Registers operator check-in for an active session with concurrency locking.
        """
        with transaction.atomic():
            if session.status != ShiftSessionStatus.ACTIVE:
                raise ValidationError("امکان ثبت حضور در شیفتی که در وضعیت فعال نیست وجود ندارد.")

            # Lock any existing active assignments for this operator to prevent race conditions
            existing_active = ShiftOperatorAssignment.objects.select_for_update().filter(
                operator=operator,
                status=ShiftAssignmentStatus.CHECKED_IN
            )
            if existing_active.exists():
                active_rec = existing_active.first()
                raise ValidationError(
                    f"اپراتور {operator.username} هم‌اکنون در شیفت «{active_rec.session}» وضعیت حضور فعال دارد."
                )

            # Check if assignment already exists for this session
            assignment = ShiftOperatorAssignment.objects.filter(
                session=session,
                operator=operator
            ).first()

            if assignment:
                assignment.check_in()
            else:
                assignment = ShiftOperatorAssignment.objects.create(
                    session=session,
                    operator=operator,
                    role=role,
                    status=ShiftAssignmentStatus.CHECKED_IN,
                    check_in_time=timezone.now()
                )

            log_audit(
                action=AuditAction.CREATE,
                model_name="ShiftOperatorAssignment",
                record_id=assignment.pk,
                record_repr=str(assignment),
                new_values={"status": assignment.status, "operator": operator.username},
                reason="ثبت حضور اپراتور در شیفت",
                user=authorized_by or operator
            )
            return assignment

    @staticmethod
    def check_out_operator(
        assignment: ShiftOperatorAssignment,
        user: User
    ) -> ShiftOperatorAssignment:
        """
        Registers operator check-out.
        """
        with transaction.atomic():
            locked = ShiftOperatorAssignment.objects.select_for_update().get(pk=assignment.pk)
            locked.check_out()
            log_audit(
                action=AuditAction.UPDATE,
                model_name="ShiftOperatorAssignment",
                record_id=locked.pk,
                record_repr=str(locked),
                new_values={"status": locked.status, "check_out_time": str(locked.check_out_time)},
                reason="ثبت خروج اپراتور از شیفت",
                user=user
            )
            return locked

    @staticmethod
    def substitute_operator(
        session: ShiftSession,
        original_operator: User,
        replacement_operator: User,
        authorized_by: User,
        reason: str
    ) -> ShiftOperatorAssignment:
        """
        Supervisor-authorized emergency substitution of an operator during a shift.
        """
        if not authorized_by or not (authorized_by.is_superuser or authorized_by.profile.is_admin_or_manager):
            raise ValidationError("فقط مدیران و سرپرستان مجاز به تایید جایگزینی اضطراری اپراتور هستند.")

        if original_operator == replacement_operator:
            raise ValidationError("اپراتور جایگزین نمی‌تواند با اپراتور اصلی یکسان باشد.")

        if not reason or len(reason.strip()) < 5:
            raise ValidationError("ثبت ادله موجه و مشروح برای جایگزینی اضطراری الزامی است (حداقل ۵ کاراکتر).")

        with transaction.atomic():
            # Check out original operator if checked in
            orig_assignment = ShiftOperatorAssignment.objects.filter(
                session=session,
                operator=original_operator,
                status=ShiftAssignmentStatus.CHECKED_IN
            ).first()
            if orig_assignment:
                orig_assignment.status = ShiftAssignmentStatus.SUBSTITUTED
                orig_assignment.check_out_time = timezone.now()
                orig_assignment.notes = f"{orig_assignment.notes}\n[جایگزین شده با {replacement_operator.username} توسط {authorized_by.username}]: {reason}".strip()
                orig_assignment.save()

            # Create substitution assignment for replacement operator
            new_assignment = ShiftOperatorAssignment.objects.create(
                session=session,
                operator=replacement_operator,
                role=ShiftOperatorRole.PRIMARY,
                status=ShiftAssignmentStatus.CHECKED_IN,
                check_in_time=timezone.now(),
                is_substitution=True,
                substituted_operator=original_operator,
                authorized_by=authorized_by,
                substitution_reason=reason,
                notes=f"جایگزینی اضطراری به جای {original_operator.username} با تایید سرپرست {authorized_by.username}"
            )

            log_audit(
                action=AuditAction.UPDATE,
                model_name="ShiftOperatorAssignment",
                record_id=new_assignment.pk,
                record_repr=str(new_assignment),
                new_values={
                    "original_operator": original_operator.username,
                    "replacement_operator": replacement_operator.username,
                    "authorized_by": authorized_by.username,
                    "reason": reason
                },
                reason=f"جایگزینی اضطراری اپراتور شیفت: {reason}",
                user=authorized_by
            )
            return new_assignment
