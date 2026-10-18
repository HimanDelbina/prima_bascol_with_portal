import logging
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

logger = logging.getLogger(__name__)


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

    @classmethod
    def resolve_session_for_operator(
        cls,
        operator: Optional[User],
        dt: Optional[datetime] = None,
        scale_context: Optional[str] = None
    ) -> Tuple[Optional[ShiftSession], str, str]:
        """
        Deterministic, unambiguous resolution of an active shift session for an operator:
        1. Identify the authenticated operator.
        2. Find valid checked-in assignments at the actual weighing timestamp.
        3. Restrict to active and time-valid sessions.
        4. Apply scale/operational-unit scope if provided (never invent dummy identifiers).
        5. Resolve to exactly one unambiguous session.
        6. If no valid session or multiple equally valid sessions exist, returns None
           with a meaningful reason code (weighing is never blocked).

        Returns:
            (session, reason_code, reason_note)
            Success: (session, "OK", "")
            Fail-safe fallback: (None, ReasonChoices.<CODE>, description)
        """
        if dt is None:
            dt = timezone.now()
        if timezone.is_aware(dt):
            dt = timezone.localtime(dt)

        if not operator or not operator.is_authenticated:
            return None, ShiftExceptionLog.ReasonChoices.NO_ACTIVE_SHIFT, "توزین توسط کاربر احراز هویت‌نشده یا ناشناس انجام شد."

        # Find operator's assignments marked CHECKED_IN in ACTIVE sessions
        assignments_qs = ShiftOperatorAssignment.objects.filter(
            operator=operator,
            status=ShiftAssignmentStatus.CHECKED_IN,
            session__status=ShiftSessionStatus.ACTIVE
        ).select_related("session", "session__shift")

        valid_candidates = []
        for asg in assignments_qs:
            session = asg.session
            shift = session.shift

            # Check check-in attendance time with 5-minute tolerance for clock skew
            if asg.check_in_time and asg.check_in_time > dt + timedelta(minutes=5):
                continue
            if asg.check_out_time and dt > asg.check_out_time + timedelta(minutes=5):
                continue

            # Check session time bounds
            if session.actual_start and session.actual_start > dt + timedelta(minutes=5):
                continue
            if session.actual_end and dt > session.actual_end + timedelta(minutes=5):
                continue

            # Verify operational date consistency or active operational window
            expected_op_date = cls.resolve_operational_date(dt, shift)
            if session.operational_date == expected_op_date or session.status == ShiftSessionStatus.ACTIVE:
                valid_candidates.append(session)

        # Deduplicate session instances
        unique_sessions = list({s.pk: s for s in valid_candidates}.values())

        if len(unique_sessions) == 1:
            return unique_sessions[0], "OK", ""

        if len(unique_sessions) > 1:
            # Ambiguity detected! Multiple active checked-in sessions for this operator
            logger.warning(
                "Ambiguous shift assignment for operator %s at %s. Matching sessions: %s",
                operator.username, dt, [s.pk for s in unique_sessions]
            )
            return (
                None,
                ShiftExceptionLog.ReasonChoices.AMBIGUOUS_SHIFT_ASSIGNMENT,
                f"تداخل در تخصیص شیفت: {len(unique_sessions)} جلسه فعال همزمان برای اپراتور یافت شد."
            )

        # len(unique_sessions) == 0: diagnose exact failure cause
        has_assigned = ShiftOperatorAssignment.objects.filter(
            operator=operator,
            session__status=ShiftSessionStatus.ACTIVE
        ).exclude(status=ShiftAssignmentStatus.CHECKED_IN).exists()

        if has_assigned:
            return (
                None,
                ShiftExceptionLog.ReasonChoices.OPERATOR_NOT_CHECKED_IN,
                f"اپراتور {operator.username} در شیفت فعال حضور دارد اما وضعیت ورود (CHECKED_IN) ثبت نشده است."
            )

        has_any_active_session = ShiftSession.objects.filter(status=ShiftSessionStatus.ACTIVE).exists()
        if has_any_active_session:
            return (
                None,
                ShiftExceptionLog.ReasonChoices.OPERATOR_HAS_NO_ACTIVE_ASSIGNMENT,
                f"جلسه شیفت فعال برای سایر پرسنل وجود دارد، اما اپراتور {operator.username} به شیفت جاری تخصیص داده نشده است."
            )

        return (
            None,
            ShiftExceptionLog.ReasonChoices.NO_ACTIVE_SHIFT,
            "هیچ جلسه شیفت کاری فعالی در سیستم بازگشایی نشده است."
        )

    @classmethod
    def get_active_session_for_weighing(
        cls,
        operator: Optional[User] = None,
        dt: Optional[datetime] = None,
        scale_context: Optional[str] = None
    ) -> Optional[ShiftSession]:
        """
        Deterministic resolution of active session for a weighing event.
        Never picks another operator's session or a random active shift.
        Returns None if not resolved (fail-safe weighing proceeds).
        """
        session, _, _ = cls.resolve_session_for_operator(operator=operator, dt=dt, scale_context=scale_context)
        return session

    @classmethod
    def is_shift_management_enabled(cls) -> bool:
        """
        Determines whether automated shift attribution and exception logging are enabled.
        Configurable via django.conf.settings.ENABLE_SHIFT_MANAGEMENT (default: True).
        """
        from django.conf import settings
        return getattr(settings, "ENABLE_SHIFT_MANAGEMENT", True)

    @classmethod
    def record_weighing_shift(
        cls,
        ticket,
        is_second_weight: bool = False,
        operator: Optional[User] = None,
        dt: Optional[datetime] = None,
        scale_context: Optional[str] = None
    ) -> Tuple[Optional[ShiftSession], bool, str, str]:
        """
        Integrates weighing events with shift sessions.
        CRITICAL FAIL-SAFE CONTINUITY:
        Weighing is NEVER blocked by missing shift context, late operator, or network delay.
        Returns:
            (session, is_out_of_shift, reason_code, reason_notes)
        """
        if not cls.is_shift_management_enabled():
            logger.info("Shift management is disabled via ENABLE_SHIFT_MANAGEMENT feature flag.")
            if not is_second_weight:
                ticket.first_weight_shift_session = None
                ticket.first_weight_out_of_shift = False
            else:
                ticket.second_weight_shift_session = None
                ticket.second_weight_out_of_shift = False
            return None, False, "SHIFT_MANAGEMENT_DISABLED", "سیستم مدیریت شیفت در تنظیمات سامانه غیرفعال است."

        try:
            # Use atomic savepoint so any unexpected DatabaseError in shift queries
            # does not abort the outer ticket transaction in PostgreSQL.
            with transaction.atomic(savepoint=True):
                session, reason, notes = cls.resolve_session_for_operator(
                    operator=operator,
                    dt=dt,
                    scale_context=scale_context
                )
        except Exception as exc:
            logger.error("Unexpected error in shift resolution for ticket: %s", exc, exc_info=True)
            session = None
            reason = ShiftExceptionLog.ReasonChoices.RESOLUTION_ERROR
            notes = f"خطای غیرمنتظره در ارزیابی سیستمی شیفت: {str(exc)}"

        if session is not None:
            if not is_second_weight:
                ticket.first_weight_shift_session = session
                ticket.first_weight_out_of_shift = False
            else:
                ticket.second_weight_shift_session = session
                ticket.second_weight_out_of_shift = False
            return session, False, "OK", ""
        else:
            if not is_second_weight:
                ticket.first_weight_shift_session = None
                ticket.first_weight_out_of_shift = True
            else:
                ticket.second_weight_shift_session = None
                ticket.second_weight_out_of_shift = True
            return None, True, reason, notes

    @classmethod
    def log_shift_exception(
        cls,
        ticket,
        weighing_phase: str,
        operator: Optional[User] = None,
        reason: str = ShiftExceptionLog.ReasonChoices.NO_ACTIVE_SHIFT,
        notes: str = "",
        timestamp: Optional[datetime] = None
    ) -> Optional[ShiftExceptionLog]:
        """
        Idempotently logs an out-of-shift exception for a persisted ticket.
        Safety guarantees:
        - Never logs if ticket or ticket.pk is None (prevents phantom records).
        - Skips if shift management feature flag is disabled.
        - Preserves initial exception evidence (reason, operator, event timestamp).
          Retries return existing record without overwriting original evidence.
        - Idempotent and concurrency-safe via get_or_create under an atomic savepoint.
        - Wrapped in transaction savepoint so logging failure never interrupts weighing.
        """
        if not ticket or not ticket.pk:
            logger.warning("ShiftExceptionLog skipped: ticket is not persisted.")
            return None

        if not cls.is_shift_management_enabled():
            logger.info("Shift exception logging skipped: shift management feature is disabled.")
            return None

        if timestamp is None:
            timestamp = timezone.now()

        try:
            with transaction.atomic(savepoint=True):
                exc_log, created = ShiftExceptionLog.objects.get_or_create(
                    ticket=ticket,
                    weighing_phase=weighing_phase,
                    defaults={
                        "operator": operator if (operator and operator.is_authenticated) else None,
                        "timestamp": timestamp,
                        "reason": reason,
                        "notes": notes,
                    }
                )
                if not created:
                    logger.info(
                        "ShiftExceptionLog already exists for ticket %s (phase %s). "
                        "Original evidence preserved (initial reason: %s, timestamp: %s).",
                        getattr(ticket, "serial_number", ticket.pk),
                        weighing_phase,
                        exc_log.reason,
                        exc_log.timestamp
                    )
                return exc_log
        except Exception as exc:
            logger.error(
                "Failed to log shift exception for ticket %s (phase %s): %s",
                getattr(ticket, "serial_number", ticket.pk),
                weighing_phase,
                exc,
                exc_info=True
            )
            return None

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
