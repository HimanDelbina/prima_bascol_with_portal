from datetime import datetime, date, time, timedelta
from decimal import Decimal
import pytz
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import IntegrityError, transaction, models
from django.utils import timezone
from django.urls import reverse

from accounts.models import UserProfile, RoleChoices
from masterdata.models import (
    Product, Party, Vehicle, Driver, OperationType,
    VehicleType, Location, UnloadLocation
)
from weighbridge.models import WeighTicket, TicketStatus, WeightMode
from monitoring.models import DiscrepancyApproval, ApprovalStatus, MonitoringAlert, AlertType, AlertStatus
from audit.models import AuditLog, AuditAction
from shifts.models import (
    WorkShift, ShiftSession, ShiftSessionStatus,
    ShiftOperatorAssignment, ShiftOperatorRole, ShiftAssignmentStatus,
    ShiftExceptionLog, ShiftHandover, ShiftHandoverStatus,
    ShiftHandoverItem, ShiftHandoverItemCategory
)
from shifts.services import ShiftResolutionService
from shifts.handover_service import ShiftHandoverService
from django.contrib.admin.sites import AdminSite
from shifts.admin import ShiftHandoverAdmin, ShiftHandoverItemInline


class ShiftHandoverServiceTests(TestCase):
    """
    Comprehensive domain tests for Phase 4.2 Shift Handover & Accountability.
    Verifies operational snapshot capture, immutability, separation of duties,
    supervisor intervention, and protected audit deletion.
    """

    @classmethod
    def setUpTestData(cls):
        cls.tz = pytz.timezone("Asia/Tehran")

        # Users
        cls.admin_user = User.objects.create_superuser(
            username="admin_ho", password="Password123!", email="admin@test.com"
        )
        cls.admin_profile = cls.admin_user.profile
        cls.admin_profile.role = RoleChoices.SYSTEM_ADMIN
        cls.admin_profile.save()

        cls.supervisor_user = User.objects.create_user(
            username="sup_ho", password="Password123!", email="sup@test.com",
            first_name="سرپرست", last_name="شیفت"
        )
        cls.sup_profile = cls.supervisor_user.profile
        cls.sup_profile.role = RoleChoices.WEIGHBRIDGE_MANAGER
        cls.sup_profile.save()

        cls.op_outgoing = User.objects.create_user(
            username="op_out", password="Password123!", email="out@test.com",
            first_name="اپراتور", last_name="تحویل‌دهنده"
        )
        cls.op_out_profile = cls.op_outgoing.profile
        cls.op_out_profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        cls.op_out_profile.personnel_code = "OP-OUT"
        cls.op_out_profile.save()

        cls.op_incoming = User.objects.create_user(
            username="op_in", password="Password123!", email="in@test.com",
            first_name="اپراتور", last_name="تحویل‌گیرنده"
        )
        cls.op_in_profile = cls.op_incoming.profile
        cls.op_in_profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        cls.op_in_profile.personnel_code = "OP-IN"
        cls.op_in_profile.save()

        cls.viewer_user = User.objects.create_user(
            username="viewer_ho", password="Password123!", email="view@test.com"
        )
        cls.viewer_profile = cls.viewer_user.profile
        cls.viewer_profile.role = RoleChoices.VIEWER
        cls.viewer_profile.save()

        cls.op_other = User.objects.create_user(
            username="op_other_ho", password="Password123!", email="other@test.com",
            first_name="اپراتور", last_name="متفرقه"
        )
        cls.op_other.profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        cls.op_other.profile.save()

        cls.sup_outgoing = User.objects.create_user(
            username="sup_out_ho", password="Password123!", email="supout@test.com",
            first_name="سرپرست", last_name="تحویل‌دهنده"
        )
        cls.sup_outgoing.profile.role = RoleChoices.WEIGHBRIDGE_MANAGER
        cls.sup_outgoing.profile.save()

        # Masterdata
        cls.product = Product.objects.create(name="شمش فولادی 150", standard_tolerance_kg=Decimal("150.00"))
        cls.party = Party.objects.create(name="شرکت ذوب‌آهن اصفهان")
        cls.op_type = OperationType.objects.create(name="ورود مواد اولیه", direction="inbound")
        cls.v_type = VehicleType.objects.create(name="تریلی لبه‌دار")

        # Shifts
        cls.morning_shift = WorkShift.objects.create(
            name="شیفت صبحگاهی", code="HO-MORN",
            start_time=time(7, 0), end_time=time(15, 0),
            is_active=True
        )
        cls.evening_shift = WorkShift.objects.create(
            name="شیفت عصرگاهی", code="HO-EVE",
            start_time=time(15, 0), end_time=time(23, 0),
            is_active=True
        )

        cls.session_out = ShiftSession.objects.create(
            shift=cls.morning_shift,
            operational_date=date(2026, 10, 25),
            status=ShiftSessionStatus.ACTIVE,
            actual_start=timezone.now(),
            opened_by=cls.op_outgoing
        )
        ShiftResolutionService.check_in_operator(cls.session_out, cls.op_outgoing, ShiftOperatorRole.PRIMARY)

        cls.session_in = ShiftSession.objects.create(
            shift=cls.evening_shift,
            operational_date=date(2026, 10, 25),
            status=ShiftSessionStatus.ACTIVE,
            actual_start=timezone.now(),
            opened_by=cls.op_incoming
        )
        ShiftResolutionService.check_in_operator(cls.session_in, cls.op_incoming, ShiftOperatorRole.PRIMARY)

        # Operational Tickets in Yard (Waiting second weight)
        cls.ticket_yard1 = WeighTicket.objects.create(
            serial_number="HO-TKT-001",
            license_plate_display="12 الف 345 - ایران 11",
            product=cls.product,
            party=cls.party,
            operation_type=cls.op_type,
            vehicle_type=cls.v_type,
            weight_mode=WeightMode.FULL_FIRST,
            status=TicketStatus.WAITING_SECOND,
            first_weight=Decimal("18500.00"),
            first_weight_date=date(2026, 10, 25),
            first_weight_time=time(10, 30),
            first_weight_operator=cls.op_outgoing,
            first_weight_shift_session=cls.session_out
        )

        cls.ticket_yard2 = WeighTicket.objects.create(
            serial_number="HO-TKT-002",
            license_plate_display="34 ب 789 - ایران 22",
            product=cls.product,
            party=cls.party,
            operation_type=cls.op_type,
            vehicle_type=cls.v_type,
            weight_mode=WeightMode.FULL_FIRST,
            status=TicketStatus.WAITING_SECOND,
            first_weight=Decimal("24300.00"),
            first_weight_date=date(2026, 10, 25),
            first_weight_time=time(11, 15),
            first_weight_operator=cls.op_outgoing,
            first_weight_shift_session=cls.session_out
        )

        # Pending Discrepancy Approval
        cls.approval_pending = DiscrepancyApproval.objects.create(
            ticket=cls.ticket_yard1,
            discrepancy_type="STANDARD_TOLERANCE_EXCEEDED",
            severity="WARNING",
            status=ApprovalStatus.PENDING,
            request_reason="مغایرت بیش از حد مجاز اولیه",
            requested_by=cls.op_outgoing
        )

        # Open Long-Wait Alert
        cls.alert_overdue = MonitoringAlert.objects.create(
            ticket=cls.ticket_yard1,
            alert_type=AlertType.LONG_WAITING_TIME,
            title="هشدار توقف طولانی",
            reason="توقف بیش از ۱۲۰ دقیقه در محوطه کارخانه"
        )

        # Unresolved Shift Exception
        cls.shift_exception = ShiftExceptionLog.objects.create(
            ticket=cls.ticket_yard2,
            weighing_phase="FIRST",
            operator=cls.op_outgoing,
            reason=ShiftExceptionLog.ReasonChoices.SESSION_TIME_INVALID,
            notes="توزین در زمان حاشیه شیفت ثبت شد"
        )

    def test_01_initiate_handover_success_and_draft_reuse(self):
        """Outgoing operator initiates draft handover; repeated call reuses existing draft."""
        handover1 = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session_out,
            operator=self.op_outgoing,
            incoming_operator=self.op_incoming,
            incoming_session=self.session_in,
            outgoing_notes="یادداشت اولیه شیفت"
        )
        self.assertIsNotNone(handover1.pk)
        self.assertEqual(handover1.status, ShiftHandoverStatus.DRAFT)
        self.assertEqual(handover1.outgoing_operator, self.op_outgoing)
        self.assertEqual(handover1.incoming_operator, self.op_incoming)

        # Re-initiating reuses the draft
        handover2 = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session_out,
            operator=self.op_outgoing,
            outgoing_notes="یادداشت بروزرسانی‌شده"
        )
        self.assertEqual(handover1.pk, handover2.pk)
        self.assertEqual(handover2.outgoing_notes, "یادداشت بروزرسانی‌شده")

    def test_02_initiate_handover_operator_not_checked_in_rejected(self):
        """Operator who is not checked into the session cannot initiate handover (unless supervisor)."""
        other_operator = User.objects.create_user(username="other_op", password="Password123!")
        UserProfile.objects.filter(user=other_operator).update(role=RoleChoices.WEIGHBRIDGE_OPERATOR)

        with self.assertRaises(ValidationError):
            ShiftHandoverService.initiate_handover(
                outgoing_session=self.session_out,
                operator=other_operator
            )

    def test_03_capture_operational_snapshot_metrics_and_items(self):
        """Snapshot correctly captures yard vehicles, waiting tickets, approvals, alerts, and exceptions."""
        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session_out,
            operator=self.op_outgoing,
            incoming_operator=self.op_incoming
        )
        frozen = ShiftHandoverService.capture_operational_snapshot(handover, self.op_outgoing)

        # Counts
        self.assertEqual(frozen.yard_vehicles_count, 2)
        self.assertEqual(frozen.waiting_second_count, 2)
        self.assertEqual(frozen.pending_discrepancies_count, 1)
        self.assertEqual(frozen.overdue_waiting_count, 1)
        self.assertEqual(frozen.unresolved_exceptions_count, 1)

        # Item records
        items = frozen.items.all()
        categories = set(items.values_list("category", flat=True))
        self.assertIn(ShiftHandoverItemCategory.YARD_VEHICLE, categories)
        self.assertIn(ShiftHandoverItemCategory.WAITING_SECOND, categories)
        self.assertIn(ShiftHandoverItemCategory.PENDING_APPROVAL, categories)
        self.assertIn(ShiftHandoverItemCategory.OVERDUE_ALERT, categories)
        self.assertIn(ShiftHandoverItemCategory.SHIFT_EXCEPTION, categories)

        # Check details json payload
        yard_item = frozen.items.filter(ticket=self.ticket_yard1, category=ShiftHandoverItemCategory.YARD_VEHICLE).first()
        self.assertIsNotNone(yard_item)
        self.assertEqual(yard_item.details["serial_number"], "HO-TKT-001")
        self.assertEqual(yard_item.details["first_weight"], 18500.0)

    def test_04_snapshot_immutability_after_ticket_completed(self):
        """
        CRITICAL DOMAIN INTEGRITY:
        When a ticket completes or changes status/weights AFTER handover submission,
        the ShiftHandoverItem snapshot details and metrics remain 100% frozen and unaltered.
        """
        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session_out,
            operator=self.op_outgoing,
            incoming_operator=self.op_incoming
        )
        submitted = ShiftHandoverService.submit_handover(
            handover=handover,
            operator=self.op_outgoing,
            checklist_data={"scale_zero_confirmed": True, "printer_paper_confirmed": True}
        )

        # Later in time, ticket_yard1 completes second weighing
        self.ticket_yard1.second_weight = Decimal("32500.00")
        self.ticket_yard1.net_weight = Decimal("14000.00")
        self.ticket_yard1.status = TicketStatus.COMPLETED
        self.ticket_yard1.save()

        # Reload snapshot item
        frozen_item = ShiftHandoverItem.objects.get(
            handover=submitted,
            ticket=self.ticket_yard1,
            category=ShiftHandoverItemCategory.YARD_VEHICLE
        )
        # Snapshot state MUST reflect status at handover time
        self.assertEqual(frozen_item.source_status, TicketStatus.WAITING_SECOND)
        self.assertEqual(frozen_item.details["first_weight"], 18500.0)
        self.assertNotIn("second_weight", frozen_item.details)
        # Handover yard count remains 2
        submitted.refresh_from_db()
        self.assertEqual(submitted.yard_vehicles_count, 2)

    def test_05_submit_handover_transitions_and_audit(self):
        """Submit transitions DRAFT -> SUBMITTED and registers SHIFT_HANDOVER_SUBMIT audit record."""
        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session_out,
            operator=self.op_outgoing,
            incoming_operator=self.op_incoming
        )
        checklist = {
            "scale_zero_confirmed": True,
            "printer_paper_confirmed": True,
            "workstation_clean_confirmed": True,
            "physical_documents_confirmed": True,
            "checklist_notes": "تمام تجهیزات سالم تحویل شد"
        }
        submitted = ShiftHandoverService.submit_handover(
            handover=handover,
            operator=self.op_outgoing,
            checklist_data=checklist,
            notes="یادداشت تسلیم شیفت"
        )
        self.assertEqual(submitted.status, ShiftHandoverStatus.SUBMITTED)
        self.assertIsNotNone(submitted.submitted_at)
        self.assertTrue(submitted.scale_zero_confirmed)

        # Verify Audit Log
        audit = AuditLog.objects.filter(
            action=AuditAction.SHIFT_HANDOVER_SUBMIT,
            record_id=str(submitted.pk)
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.user, self.op_outgoing)

    def test_06_separation_of_duties_self_acceptance_strictly_rejected(self):
        """
        SEPARATION OF DUTIES ENFORCEMENT:
        Outgoing operator CANNOT accept their own handover (No self-approval).
        """
        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session_out,
            operator=self.op_outgoing,
            incoming_operator=self.op_incoming
        )
        submitted = ShiftHandoverService.submit_handover(handover, self.op_outgoing)

        # Outgoing operator attempts self-acceptance
        with self.assertRaises(ValidationError) as ctx:
            ShiftHandoverService.accept_handover(
                handover=submitted,
                operator=self.op_outgoing
            )
        self.assertIn("تفکیک وظایف", str(ctx.exception))
        submitted.refresh_from_db()
        self.assertEqual(submitted.status, ShiftHandoverStatus.SUBMITTED)

    def test_07_separation_of_duties_self_dispute_strictly_rejected(self):
        """Outgoing operator cannot dispute their own handover."""
        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session_out,
            operator=self.op_outgoing,
            incoming_operator=self.op_incoming
        )
        submitted = ShiftHandoverService.submit_handover(handover, self.op_outgoing)

        with self.assertRaises(ValidationError):
            ShiftHandoverService.dispute_handover(
                handover=submitted,
                operator=self.op_outgoing,
                dispute_reason="مغایرت ساختگی توسط خودم"
            )

    def test_08_incoming_operator_accept_handover_success(self):
        """Incoming operator accepts handover; transitions to ACCEPTED and logs audit."""
        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session_out,
            operator=self.op_outgoing,
            incoming_operator=self.op_incoming
        )
        submitted = ShiftHandoverService.submit_handover(handover, self.op_outgoing)

        accepted = ShiftHandoverService.accept_handover(
            handover=submitted,
            operator=self.op_incoming,
            incoming_session=self.session_in,
            notes="مسئولیت شیفت بدون مغایرت تحویل گرفته شد."
        )
        self.assertEqual(accepted.status, ShiftHandoverStatus.ACCEPTED)
        self.assertEqual(accepted.incoming_operator, self.op_incoming)
        self.assertIsNotNone(accepted.accepted_at)
        self.assertTrue(accepted.is_finalized)

        # Audit Log
        audit = AuditLog.objects.filter(
            action=AuditAction.SHIFT_HANDOVER_ACCEPT,
            record_id=str(accepted.pk)
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.user, self.op_incoming)

    def test_09_incoming_operator_dispute_handover_and_reason_validation(self):
        """Incoming operator records dispute; requires >= 5 chars; transitions to DISPUTED."""
        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session_out,
            operator=self.op_outgoing,
            incoming_operator=self.op_incoming
        )
        submitted = ShiftHandoverService.submit_handover(handover, self.op_outgoing)

        # Too short reason rejected
        with self.assertRaises(ValidationError):
            ShiftHandoverService.dispute_handover(submitted, self.op_incoming, dispute_reason="کم")

        # Valid dispute
        disputed = ShiftHandoverService.dispute_handover(
            handover=submitted,
            operator=self.op_incoming,
            dispute_reason="عدم تطابق پلاک یک دستگاه کامیون در محوطه",
            notes="راننده مدارک را ارائه نکرده است."
        )
        self.assertEqual(disputed.status, ShiftHandoverStatus.DISPUTED)
        self.assertIsNotNone(disputed.disputed_at)
        self.assertFalse(disputed.is_finalized)

        # Audit Log
        audit = AuditLog.objects.filter(
            action=AuditAction.SHIFT_HANDOVER_DISPUTE,
            record_id=str(disputed.pk)
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.user, self.op_incoming)

    def test_10_supervisor_resolve_dispute_success(self):
        """Supervisor resolves a disputed handover with managerial note."""
        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session_out,
            operator=self.op_outgoing,
            incoming_operator=self.op_incoming
        )
        submitted = ShiftHandoverService.submit_handover(handover, self.op_outgoing)
        disputed = ShiftHandoverService.dispute_handover(
            submitted, self.op_incoming, dispute_reason="اختلاف در شمارش ژتون‌های فیزیکی"
        )

        resolved = ShiftHandoverService.resolve_dispute(
            handover=disputed,
            supervisor=self.supervisor_user,
            resolution_notes="بررسی میدانی انجام و ژتون گمشده پیدا شد. تحویل تایید گردید.",
            action="RESOLVE"
        )
        self.assertEqual(resolved.status, ShiftHandoverStatus.SUPERVISOR_RESOLVED)
        self.assertEqual(resolved.supervisor, self.supervisor_user)
        self.assertIsNotNone(resolved.supervisor_resolved_at)
        self.assertTrue(resolved.is_finalized)

        # Audit Log
        audit = AuditLog.objects.filter(
            action=AuditAction.SHIFT_HANDOVER_RESOLVE,
            record_id=str(resolved.pk)
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.user, self.supervisor_user)

    def test_11_supervisor_cancel_dispute_success(self):
        """Supervisor cancels a disputed handover."""
        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session_out,
            operator=self.op_outgoing,
            incoming_operator=self.op_incoming
        )
        submitted = ShiftHandoverService.submit_handover(handover, self.op_outgoing)
        disputed = ShiftHandoverService.dispute_handover(
            submitted, self.op_incoming, dispute_reason="عدم امکان تحویل به علت خرابی رایانه"
        )

        cancelled = ShiftHandoverService.resolve_dispute(
            handover=disputed,
            supervisor=self.supervisor_user,
            resolution_notes="فرآیند تحویل به دلیل خرابی تجهیزات لغو و شیفت تمدید شد.",
            action="CANCEL"
        )
        self.assertEqual(cancelled.status, ShiftHandoverStatus.CANCELLED)
        self.assertTrue(cancelled.is_finalized)

    def test_12_non_supervisor_cannot_resolve_dispute(self):
        """Regular operator cannot resolve a disputed handover."""
        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session_out,
            operator=self.op_outgoing,
            incoming_operator=self.op_incoming
        )
        submitted = ShiftHandoverService.submit_handover(handover, self.op_outgoing)
        disputed = ShiftHandoverService.dispute_handover(
            submitted, self.op_incoming, dispute_reason="مغایرت موجودی اسناد"
        )

        with self.assertRaises(PermissionDenied):
            ShiftHandoverService.resolve_dispute(
                handover=disputed,
                supervisor=self.op_incoming,
                resolution_notes="تلاش غیرمجاز جهت حل مغایرت"
            )

    def test_13_protected_deletion_on_referenced_ticket(self):
        """
        AUDIT SAFETY:
        Deleting a WeighTicket referenced by ShiftHandoverItem raises ProtectedError.
        Historical operational snapshot evidence can never be lost by cascading delete.
        """
        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session_out,
            operator=self.op_outgoing
        )
        ShiftHandoverService.capture_operational_snapshot(handover, self.op_outgoing)

        # Deleting ticket_yard1 must fail with ProtectedError
        with self.assertRaises(models.ProtectedError):
            self.ticket_yard1.delete()

    def test_14_database_partial_unique_constraint_rejects_duplicate_active_handover(self):
        """
        DATABASE CONSTRAINT:
        unique_active_handover_per_outgoing_session prevents multiple active handovers
        for the same outgoing session at PostgreSQL database level.
        """
        ShiftHandover.objects.create(
            outgoing_session=self.session_out,
            outgoing_operator=self.op_outgoing,
            status=ShiftHandoverStatus.DRAFT
        )

        # Creating a second DRAFT for the same session must raise IntegrityError
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ShiftHandover.objects.create(
                    outgoing_session=self.session_out,
                    outgoing_operator=self.op_outgoing,
                    status=ShiftHandoverStatus.SUBMITTED
                )

    def test_15_weighing_continuity_unblocked_during_pending_handover(self):
        """
        INDUSTRIAL CONTINUITY:
        A pending or disputed handover MUST NOT block scale weighing or ticket processing.
        """
        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session_out,
            operator=self.op_outgoing,
            incoming_operator=self.op_incoming
        )
        ShiftHandoverService.submit_handover(handover, self.op_outgoing)
        ShiftHandoverService.dispute_handover(handover, self.op_incoming, dispute_reason="مغایرت اداری")

        # New weighing on scale must succeed unimpeded
        new_ticket = WeighTicket.objects.create(
            serial_number="HO-CONT-999",
            license_plate_display="99 ی 999 - ایران 99",
            product=self.product,
            party=self.party,
            operation_type=self.op_type,
            vehicle_type=self.v_type,
            weight_mode=WeightMode.FULL_FIRST,
            status=TicketStatus.WAITING_SECOND,
            first_weight=Decimal("21000.00"),
            first_weight_date=date(2026, 10, 25),
            first_weight_time=time(14, 0),
            first_weight_operator=self.op_incoming
        )
        self.assertIsNotNone(new_ticket.pk)
        self.assertEqual(new_ticket.first_weight, Decimal("21000.00"))

    def test_16_submitted_and_finalized_handover_deletion_blocked_at_orm_level(self):
        """
        AUDIT SAFETY:
        Direct call to ShiftHandover.delete() raises ValidationError for SUBMITTED,
        ACCEPTED, SUPERVISOR_RESOLVED, and CANCELLED states.
        Only DRAFT can be deleted.
        """
        draft = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session_out,
            operator=self.op_outgoing
        )
        draft_pk = draft.pk
        draft.delete()
        self.assertFalse(ShiftHandover.objects.filter(pk=draft_pk).exists())

        submitted = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session_out,
            operator=self.op_outgoing,
            incoming_operator=self.op_incoming
        )
        ShiftHandoverService.submit_handover(submitted, self.op_outgoing)
        with self.assertRaises(ValidationError) as ctx:
            submitted.delete()
        self.assertIn("مسدود است", str(ctx.exception))

        accepted = ShiftHandoverService.accept_handover(submitted, self.op_incoming)
        with self.assertRaises(ValidationError) as ctx:
            accepted.delete()
        self.assertIn("مسدود است", str(ctx.exception))

    def test_17_snapshot_item_deletion_blocked_for_non_draft_handover(self):
        """
        AUDIT INTEGRITY:
        Direct deletion of ShiftHandoverItem raises ValidationError if parent handover
        status is not DRAFT.
        """
        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session_out,
            operator=self.op_outgoing,
            incoming_operator=self.op_incoming
        )
        ShiftHandoverService.submit_handover(handover, self.op_outgoing)
        item = handover.items.first()
        self.assertIsNotNone(item)
        with self.assertRaises(ValidationError) as ctx:
            item.delete()
        self.assertIn("تغییرناپذیر", str(ctx.exception))

    def test_18_finalized_handover_mutation_blocked_by_clean(self):
        """
        IMMUTABILITY:
        Modifying an already finalized handover (ACCEPTED, CANCELLED, SUPERVISOR_RESOLVED)
        triggers ValidationError during clean()/save().
        """
        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session_out,
            operator=self.op_outgoing,
            incoming_operator=self.op_incoming
        )
        ShiftHandoverService.submit_handover(handover, self.op_outgoing)
        accepted = ShiftHandoverService.accept_handover(handover, self.op_incoming)

        accepted.outgoing_notes = "دستکاری پس از پذیرش نهایی"
        with self.assertRaises(ValidationError) as ctx:
            accepted.save()
        self.assertIn("غیرقابل ویرایش", str(ctx.exception))

    def test_19_designated_incoming_operator_enforcement(self):
        """
        AUTHORIZATION INTEGRITY:
        When handover designates an incoming operator (op_in), an unrelated operator (op_other)
        cannot accept or dispute the handover.
        """
        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session_out,
            operator=self.op_outgoing,
            incoming_operator=self.op_incoming
        )
        ShiftHandoverService.submit_handover(handover, self.op_outgoing)

        with self.assertRaises(PermissionDenied) as ctx:
            ShiftHandoverService.accept_handover(handover, self.op_other)
        self.assertIn("تنها اپراتور تحویل‌گیرنده تعیین‌شده", str(ctx.exception))

        with self.assertRaises(PermissionDenied) as ctx:
            ShiftHandoverService.dispute_handover(handover, self.op_other, dispute_reason="عدم تطابق اداری")
        self.assertIn("تنها اپراتور تحویل‌گیرنده تعیین‌شده", str(ctx.exception))

    def test_20_incoming_session_assignment_enforcement(self):
        """
        SESSION ASSIGNMENT INTEGRITY:
        When incoming_session is set and has active operator assignments,
        an unassigned operator cannot accept the handover.
        """
        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session_out,
            operator=self.op_outgoing,
            incoming_session=self.session_in
        )
        ShiftHandoverService.submit_handover(handover, self.op_outgoing)

        with self.assertRaises(ValidationError) as ctx:
            ShiftHandoverService.accept_handover(handover, self.op_other)
        self.assertIn("تخصیص داده نشده است", str(ctx.exception))

    def test_21_superuser_cannot_bypass_designated_operator(self):
        """
        SEPARATION OF DUTIES:
        Superuser cannot silently accept a handover designated for another operator
        through ordinary acceptance without supervisor resolution workflow.
        """
        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session_out,
            operator=self.op_outgoing,
            incoming_operator=self.op_incoming
        )
        ShiftHandoverService.submit_handover(handover, self.op_outgoing)

        with self.assertRaises(PermissionDenied):
            ShiftHandoverService.accept_handover(handover, self.admin_user)

    def test_22_outgoing_supervisor_self_resolution_blocked(self):
        """
        SEPARATION OF DUTIES:
        A supervisor who opened/operated the outgoing shift session CANNOT resolve
        or approve their own handover dispute.
        """
        session_sup = ShiftSession.objects.create(
            shift=self.morning_shift,
            operational_date=date(2026, 10, 26),
            status=ShiftSessionStatus.ACTIVE,
            actual_start=timezone.now(),
            opened_by=self.sup_outgoing
        )
        ShiftResolutionService.check_in_operator(session_sup, self.sup_outgoing, ShiftOperatorRole.PRIMARY)

        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=session_sup,
            operator=self.sup_outgoing,
            incoming_operator=self.op_incoming
        )
        ShiftHandoverService.submit_handover(handover, self.sup_outgoing)
        ShiftHandoverService.dispute_handover(handover, self.op_incoming, dispute_reason="اختلاف ثبتی")

        with self.assertRaises(ValidationError) as ctx:
            ShiftHandoverService.resolve_dispute(
                handover=handover,
                supervisor=self.sup_outgoing,
                resolution_notes="خودتاییدی سرپرست"
            )
        self.assertIn("اصل تفکیک وظایف", str(ctx.exception))

        resolved = ShiftHandoverService.resolve_dispute(
            handover=handover,
            supervisor=self.supervisor_user,
            resolution_notes="بررسی شد و تایید گردید.",
            action="RESOLVE",
            responsible_operator=self.op_incoming
        )
        self.assertEqual(resolved.status, ShiftHandoverStatus.SUPERVISOR_RESOLVED)

    def test_23_supervisor_substitution_workflow(self):
        """
        SUPERVISOR EMERGENCY SUBSTITUTION:
        Supervisor can replace the designated incoming operator with audit tracking.
        Outgoing operator cannot perform substitution.
        """
        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session_out,
            operator=self.op_outgoing,
            incoming_operator=self.op_incoming
        )
        ShiftHandoverService.submit_handover(handover, self.op_outgoing)

        with self.assertRaises(PermissionDenied):
            ShiftHandoverService.substitute_incoming_operator(
                handover=handover,
                supervisor=self.op_outgoing,
                new_incoming_operator=self.op_other,
                reason="تلاش غیرمجاز تحویل‌دهنده"
            )

        with self.assertRaises(ValidationError):
            ShiftHandoverService.substitute_incoming_operator(
                handover=handover,
                supervisor=self.supervisor_user,
                new_incoming_operator=self.op_outgoing,
                reason="تعویض نامعتبر"
            )

        subbed = ShiftHandoverService.substitute_incoming_operator(
            handover=handover,
            supervisor=self.supervisor_user,
            new_incoming_operator=self.op_other,
            reason="جایگزینی اضطراری به دلیل مرخصی استعلاجی اپراتور اول"
        )
        self.assertEqual(subbed.incoming_operator, self.op_other)

        accepted = ShiftHandoverService.accept_handover(subbed, self.op_other)
        self.assertEqual(accepted.status, ShiftHandoverStatus.ACCEPTED)

        audit = AuditLog.objects.filter(
            action=AuditAction.SHIFT_SUBSTITUTION,
            record_id=handover.pk
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.user, self.supervisor_user)

    def test_24_multi_ticket_yard_truck_aggregation_no_duplicate_collision(self):
        """
        AGGREGATION & COLLISION RESILIENCE:
        Multiple open tickets for the same physical vehicle in yard do not collide
        on unique constraint (handover, category, item_identifier).
        yard_vehicles_count counts unique vehicles (2); waiting_second_count counts tickets (3).
        """
        ticket_dup = WeighTicket.objects.create(
            serial_number="HO-TKT-DUP-001",
            license_plate_display=self.ticket_yard1.license_plate_display,
            product=self.product,
            party=self.party,
            operation_type=self.op_type,
            vehicle_type=self.v_type,
            weight_mode=WeightMode.FULL_FIRST,
            status=TicketStatus.WAITING_SECOND,
            first_weight=Decimal("19000.00"),
            first_weight_date=date(2026, 10, 25),
            first_weight_time=time(11, 45),
            first_weight_operator=self.op_outgoing,
            first_weight_shift_session=self.session_out
        )

        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session_out,
            operator=self.op_outgoing
        )
        ShiftHandoverService.capture_operational_snapshot(handover, self.op_outgoing)
        handover.refresh_from_db()

        self.assertEqual(handover.yard_vehicles_count, 2)
        self.assertEqual(handover.waiting_second_count, 3)

        yard_item = handover.items.filter(
            category=ShiftHandoverItemCategory.YARD_VEHICLE,
            item_identifier=self.ticket_yard1.license_plate_display
        ).first()
        self.assertIsNotNone(yard_item)
        self.assertEqual(yard_item.details["ticket_count"], 2)
        self.assertIn("HO-TKT-001", yard_item.details["ticket_serials"])
        self.assertIn("HO-TKT-DUP-001", yard_item.details["ticket_serials"])

        # Delete draft handover first (clears protected ShiftHandoverItem foreign keys)
        handover.delete()
        ticket_dup.delete()

    def test_25_live_operational_delta_non_destructive(self):
        """
        SNAPSHOT STABILITY & LIVE PROGRESSION:
        Live delta reflects current state changes without altering frozen snapshot records.
        """
        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session_out,
            operator=self.op_outgoing,
            incoming_operator=self.op_incoming
        )
        ShiftHandoverService.submit_handover(handover, self.op_outgoing)
        handover.refresh_from_db()
        orig_yard_count = handover.yard_vehicles_count
        orig_waiting_count = handover.waiting_second_count

        self.ticket_yard1.status = TicketStatus.COMPLETED
        self.ticket_yard1.second_weight = Decimal("8500.00")
        self.ticket_yard1.net_weight = Decimal("10000.00")
        self.ticket_yard1.save()

        new_ticket = WeighTicket.objects.create(
            serial_number="HO-TKT-NEW-01",
            license_plate_display="55 س 555 - ایران 55",
            product=self.product,
            party=self.party,
            operation_type=self.op_type,
            vehicle_type=self.v_type,
            weight_mode=WeightMode.FULL_FIRST,
            status=TicketStatus.WAITING_SECOND,
            first_weight=Decimal("20000.00"),
            first_weight_date=date(2026, 10, 25),
            first_weight_time=time(12, 0),
            first_weight_operator=self.op_incoming
        )

        delta = ShiftHandoverService.get_live_operational_delta(handover)
        self.assertTrue(delta["has_changes"])
        self.assertEqual(delta["completed_since_snapshot_count"], 1)
        self.assertIn(self.ticket_yard1, delta["completed_tickets"])
        self.assertEqual(delta["new_yard_arrivals_count"], 1)
        self.assertIn(new_ticket, delta["new_yard_tickets"])

        handover.refresh_from_db()
        self.assertEqual(handover.yard_vehicles_count, orig_yard_count)
        self.assertEqual(handover.waiting_second_count, orig_waiting_count)

        self.ticket_yard1.status = TicketStatus.WAITING_SECOND
        self.ticket_yard1.second_weight = None
        self.ticket_yard1.net_weight = Decimal("0.00")
        self.ticket_yard1.save()
        new_ticket.delete()

    def test_26_cancel_handover_dispute_restriction(self):
        """
        WORKFLOW GOVERNANCE:
        An outgoing operator CANNOT cancel a DISPUTED handover (cannot bury discrepancy).
        Only a supervisor can cancel or resolve a disputed handover.
        """
        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session_out,
            operator=self.op_outgoing,
            incoming_operator=self.op_incoming
        )
        ShiftHandoverService.submit_handover(handover, self.op_outgoing)
        ShiftHandoverService.dispute_handover(handover, self.op_incoming, dispute_reason="اختلاف جدی")

        with self.assertRaises(PermissionDenied):
            ShiftHandoverService.cancel_handover(handover, self.op_outgoing, reason="لغو خودسرانه")

        cancelled = ShiftHandoverService.cancel_handover(handover, self.supervisor_user, reason="لغو رسمی توسط سرپرست")
        self.assertEqual(cancelled.status, ShiftHandoverStatus.CANCELLED)



class ShiftHandoverViewsTests(TestCase):
    """
    MVC views tests for Phase 4.2 Shift Handover workflows.
    """

    @classmethod
    def setUpTestData(cls):
        cls.tz = pytz.timezone("Asia/Tehran")

        cls.admin_user = User.objects.create_superuser(
            username="admin_vw", password="Password123!", email="adminvw@test.com"
        )
        cls.admin_user.profile.role = RoleChoices.SYSTEM_ADMIN
        cls.admin_user.profile.save()

        cls.supervisor = User.objects.create_user(
            username="sup_vw", password="Password123!", email="supvw@test.com"
        )
        cls.supervisor.profile.role = RoleChoices.WEIGHBRIDGE_MANAGER
        cls.supervisor.profile.save()

        cls.op_out = User.objects.create_user(
            username="op_out_vw", password="Password123!", email="outvw@test.com"
        )
        cls.op_out.profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        cls.op_out.profile.save()

        cls.op_in = User.objects.create_user(
            username="op_in_vw", password="Password123!", email="invw@test.com"
        )
        cls.op_in.profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        cls.op_in.profile.save()

        cls.shift = WorkShift.objects.create(
            name="شیفت تست ویو", code="VW-SHIFT",
            start_time=time(8, 0), end_time=time(16, 0),
            is_active=True
        )
        cls.session = ShiftSession.objects.create(
            shift=cls.shift,
            operational_date=date(2026, 10, 25),
            status=ShiftSessionStatus.ACTIVE,
            actual_start=timezone.now(),
            opened_by=cls.op_out
        )
        ShiftResolutionService.check_in_operator(cls.session, cls.op_out, ShiftOperatorRole.PRIMARY)

    def setUp(self):
        self.client = Client()

    def test_handover_list_view_authorized(self):
        """Operators and supervisors can access handover registry list."""
        self.client.force_login(self.op_out)
        response = self.client.get(reverse("shifts:handover_list"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "shifts/handover_list.html")

    def test_handover_initiate_view_get_and_post(self):
        """GET renders initiate form; POST save_draft creates draft."""
        self.client.force_login(self.op_out)
        url = reverse("shifts:handover_initiate", kwargs={"session_pk": self.session.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "shifts/handover_form.html")

        # POST save draft
        post_data = {
            "save_draft": "1",
            "incoming_operator": self.op_in.pk,
            "scale_zero_confirmed": "on",
            "printer_paper_confirmed": "on",
            "outgoing_notes": "یادداشت تست فرم",
        }
        post_resp = self.client.post(url, data=post_data)
        handover = ShiftHandover.objects.filter(outgoing_session=self.session).first()
        self.assertIsNotNone(handover)
        self.assertEqual(handover.status, ShiftHandoverStatus.DRAFT)
        self.assertRedirects(post_resp, reverse("shifts:handover_detail", kwargs={"pk": handover.pk}))

    def test_handover_detail_view(self):
        """Detail view renders successfully with snapshot tabs and metadata."""
        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session,
            operator=self.op_out,
            incoming_operator=self.op_in
        )
        self.client.force_login(self.op_in)
        url = reverse("shifts:handover_detail", kwargs={"pk": handover.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "shifts/handover_detail.html")

    def test_handover_accept_view_separation_of_duties(self):
        """Outgoing operator cannot accept via POST; incoming operator can."""
        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session,
            operator=self.op_out,
            incoming_operator=self.op_in
        )
        ShiftHandoverService.submit_handover(handover, self.op_out)

        # Outgoing operator POST to accept must fail
        self.client.force_login(self.op_out)
        accept_url = reverse("shifts:handover_accept", kwargs={"pk": handover.pk})
        resp = self.client.post(accept_url, data={"incoming_notes": "تلاش خودتاییدی"})
        handover.refresh_from_db()
        self.assertEqual(handover.status, ShiftHandoverStatus.SUBMITTED)

        # Incoming operator POST to accept succeeds
        self.client.force_login(self.op_in)
        resp2 = self.client.post(accept_url, data={"incoming_notes": "پذیرش توسط تحویل‌گیرنده"})
        handover.refresh_from_db()
        self.assertEqual(handover.status, ShiftHandoverStatus.ACCEPTED)

    def test_handover_dispute_and_supervisor_resolve_views(self):
        """Incoming operator disputes via view; supervisor resolves via view."""
        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session,
            operator=self.op_out,
            incoming_operator=self.op_in
        )
        ShiftHandoverService.submit_handover(handover, self.op_out)

        # Dispute POST
        self.client.force_login(self.op_in)
        dispute_url = reverse("shifts:handover_dispute", kwargs={"pk": handover.pk})
        resp = self.client.post(dispute_url, data={
            "dispute_reason": "اختلاف در تعداد خودروهای منتظر وزن دوم",
            "incoming_notes": "بررسی شود"
        })
        handover.refresh_from_db()
        self.assertEqual(handover.status, ShiftHandoverStatus.DISPUTED)

        # Supervisor Resolve GET & POST
        self.client.force_login(self.supervisor)
        resolve_url = reverse("shifts:handover_resolve", kwargs={"pk": handover.pk})
        get_resp = self.client.get(resolve_url)
        self.assertEqual(get_resp.status_code, 200)

        post_resp = self.client.post(resolve_url, data={
            "action": "RESOLVE",
            "resolution_notes": "شمارش محوطه مجددا انجام و تایید شد."
        })
        handover.refresh_from_db()
        self.assertEqual(handover.status, ShiftHandoverStatus.SUPERVISOR_RESOLVED)
        self.assertEqual(handover.supervisor, self.supervisor)

    def test_supervisor_substitute_operator_view(self):
        """Supervisor can substitute incoming operator via view; non-supervisor cannot."""
        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session,
            operator=self.op_out,
            incoming_operator=self.op_in
        )
        ShiftHandoverService.submit_handover(handover, self.op_out)

        sub_url = reverse("shifts:handover_substitute_operator", kwargs={"pk": handover.pk})

        # Outgoing operator cannot substitute
        self.client.force_login(self.op_out)
        resp = self.client.post(sub_url, data={
            "new_incoming_operator": self.admin_user.pk,
            "substitution_reason": "تلاش غیرمجاز اپراتور"
        })
        handover.refresh_from_db()
        self.assertEqual(handover.incoming_operator, self.op_in)

        # Supervisor can substitute
        self.client.force_login(self.supervisor)
        resp = self.client.post(sub_url, data={
            "new_incoming_operator": self.admin_user.pk,
            "substitution_reason": "جایگزینی رسمی به دستور سرپرست"
        })
        handover.refresh_from_db()
        self.assertEqual(handover.incoming_operator, self.admin_user)

    def test_outgoing_supervisor_cannot_resolve_via_view(self):
        """Supervisor who is also outgoing operator cannot resolve dispute via view."""
        sup_session = ShiftSession.objects.create(
            shift=self.shift,
            operational_date=date(2026, 10, 26),
            status=ShiftSessionStatus.ACTIVE,
            actual_start=timezone.now(),
            opened_by=self.supervisor
        )
        ShiftResolutionService.check_in_operator(sup_session, self.supervisor, ShiftOperatorRole.PRIMARY)

        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=sup_session,
            operator=self.supervisor,
            incoming_operator=self.op_in
        )
        ShiftHandoverService.submit_handover(handover, self.supervisor)
        ShiftHandoverService.dispute_handover(handover, self.op_in, dispute_reason="عدم تطابق")

        self.client.force_login(self.supervisor)
        resolve_url = reverse("shifts:handover_resolve", kwargs={"pk": handover.pk})
        resp = self.client.post(resolve_url, data={
            "action": "RESOLVE",
            "resolution_notes": "تایید پرونده خودم"
        })
        handover.refresh_from_db()
        self.assertEqual(handover.status, ShiftHandoverStatus.DISPUTED)

    def test_live_delta_rendered_in_detail_view(self):
        """View renders live progression delta section and respects incoming operator."""
        handover = ShiftHandoverService.initiate_handover(
            outgoing_session=self.session,
            operator=self.op_out,
            incoming_operator=self.op_in
        )
        ShiftHandoverService.submit_handover(handover, self.op_out)

        self.client.force_login(self.op_in)
        url = reverse("shifts:handover_detail", kwargs={"pk": handover.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["can_accept_or_dispute"])
        self.assertFalse(resp.context["is_outgoing"])
        self.assertIn("delta", resp.context)


class MockAdminRequest:
    def __init__(self, user):
        self.user = user


class ShiftHandoverAdminSecurityTests(TestCase):
    """
    Verifies Django admin protections for ShiftHandover immutability.
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_superuser(
            username="admin_sec", password="Password123!", email="sec@test.com"
        )
        cls.shift = WorkShift.objects.create(
            name="شیفت ادمین", code="ADM-SHF",
            start_time=time(8, 0), end_time=time(16, 0), is_active=True
        )
        cls.session = ShiftSession.objects.create(
            shift=cls.shift, operational_date=date(2026, 10, 25),
            status=ShiftSessionStatus.ACTIVE, actual_start=timezone.now(),
            opened_by=cls.admin_user
        )
        cls.handover = ShiftHandover.objects.create(
            outgoing_session=cls.session,
            outgoing_operator=cls.admin_user,
            status=ShiftHandoverStatus.SUBMITTED
        )

    def test_admin_has_no_delete_permission(self):
        site = AdminSite()
        admin = ShiftHandoverAdmin(ShiftHandover, site)
        req = MockAdminRequest(self.admin_user)
        self.assertFalse(admin.has_delete_permission(req, self.handover))
        self.assertFalse(admin.has_delete_permission(req, None))

    def test_admin_makes_all_fields_readonly_when_submitted(self):
        site = AdminSite()
        admin = ShiftHandoverAdmin(ShiftHandover, site)
        req = MockAdminRequest(self.admin_user)
        readonly = admin.get_readonly_fields(req, self.handover)
        self.assertIn("outgoing_session", readonly)
        self.assertIn("status", readonly)
        self.assertIn("yard_vehicles_count", readonly)

    def test_inline_item_permissions_disabled(self):
        site = AdminSite()
        inline = ShiftHandoverItemInline(ShiftHandoverItem, site)
        req = MockAdminRequest(self.admin_user)
        self.assertFalse(inline.has_add_permission(req, self.handover))
        self.assertFalse(inline.has_change_permission(req, self.handover))
        self.assertFalse(inline.has_delete_permission(req, self.handover))

