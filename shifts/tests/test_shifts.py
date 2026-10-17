from datetime import datetime, date, time, timedelta
from decimal import Decimal
import pytz
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.urls import reverse

from accounts.models import UserProfile, RoleChoices
from masterdata.models import (
    Product, Party, Vehicle, Driver, OperationType,
    VehicleType, Location, UnloadLocation
)
from weighbridge.models import WeighTicket, TicketStatus, WeightMode
from shifts.models import (
    WorkShift, ShiftSession, ShiftSessionStatus,
    ShiftOperatorAssignment, ShiftOperatorRole, ShiftAssignmentStatus,
    ShiftExceptionLog
)
from shifts.services import ShiftResolutionService


class ShiftManagementPhase41Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Timezone for test consistency
        cls.tz = pytz.timezone("Asia/Tehran")

        # Users
        cls.admin_user = User.objects.create_superuser(
            username="admin_user", password="Password123!", email="admin@example.com"
        )
        cls.admin_profile = cls.admin_user.profile
        cls.admin_profile.role = RoleChoices.SYSTEM_ADMIN
        cls.admin_profile.save()

        cls.manager_user = User.objects.create_user(
            username="manager_user", password="Password123!", email="manager@example.com"
        )
        cls.manager_profile = cls.manager_user.profile
        cls.manager_profile.role = RoleChoices.WEIGHBRIDGE_MANAGER
        cls.manager_profile.save()

        cls.operator1 = User.objects.create_user(
            username="op_reza", password="Password123!", email="reza@example.com",
            first_name="رضا", last_name="رضایی"
        )
        cls.op1_profile = cls.operator1.profile
        cls.op1_profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        cls.op1_profile.personnel_code = "EMP-101"
        cls.op1_profile.save()

        cls.operator2 = User.objects.create_user(
            username="op_ali", password="Password123!", email="ali@example.com",
            first_name="علی", last_name="علوی"
        )
        cls.op2_profile = cls.operator2.profile
        cls.op2_profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        cls.op2_profile.personnel_code = "EMP-102"
        cls.op2_profile.save()

        cls.viewer_user = User.objects.create_user(
            username="viewer_user", password="Password123!", email="viewer@example.com"
        )
        cls.viewer_profile = cls.viewer_user.profile
        cls.viewer_profile.role = RoleChoices.VIEWER
        cls.viewer_profile.save()

        # Masterdata
        cls.product = Product.objects.create(name="میلگرد ۱۴", standard_tolerance_kg=Decimal("100.00"))
        cls.party = Party.objects.create(name="شرکت فولاد جنوب")
        cls.op_type = OperationType.objects.create(name="فروش داخلی", direction="outbound")
        cls.v_type = VehicleType.objects.create(name="کامیون جفت")
        cls.origin = Location.objects.create(name="مبدأ اصفهان")
        cls.dest = Location.objects.create(name="مقصد کارخانه")
        cls.unload_loc = UnloadLocation.objects.create(name="انبار مرکزی")

        # Shifts
        cls.morning_shift = WorkShift.objects.create(
            name="شیفت صبح", code="SHIFT-MORN",
            start_time=time(7, 0), end_time=time(15, 0),
            is_active=True, allowed_grace_minutes=15
        )
        cls.night_shift = WorkShift.objects.create(
            name="شیفت شب", code="SHIFT-NIGHT",
            start_time=time(23, 0), end_time=time(7, 0),
            is_active=True, allowed_grace_minutes=20
        )

    def setUp(self):
        self.client = Client()

    # -------------------------------------------------------------
    # 1. WorkShift Model & Validation Tests
    # -------------------------------------------------------------
    def test_workshift_zero_duration_rejected(self):
        """Zero duration schedule (start == end) must raise ValidationError."""
        shift = WorkShift(
            name="شیفت نامعتبر", code="SHIFT-ZERO",
            start_time=time(8, 0), end_time=time(8, 0)
        )
        with self.assertRaises(ValidationError):
            shift.save()

    def test_workshift_overnight_auto_detection_and_duration(self):
        """Overnight shift is automatically detected and duration correctly computed."""
        self.assertTrue(self.night_shift.is_overnight)
        self.assertEqual(self.night_shift.duration_hours, 8.0)

        self.assertFalse(self.morning_shift.is_overnight)
        self.assertEqual(self.morning_shift.duration_hours, 8.0)

    def test_workshift_invalid_date_range_rejected(self):
        """valid_until cannot be earlier than valid_from."""
        shift = WorkShift(
            name="شیفت تاریخ نامعتبر", code="SHIFT-DATERANGE",
            start_time=time(8, 0), end_time=time(16, 0),
            valid_from=date(2026, 10, 20), valid_until=date(2026, 10, 10)
        )
        with self.assertRaises(ValidationError):
            shift.save()

    def test_overlapping_shift_schedules_with_distinct_codes_allowed(self):
        """Multiple scales/relief teams can have overlapping schedules under distinct codes."""
        relief_shift = WorkShift.objects.create(
            name="شیفت کمکی خط ۲", code="SHIFT-RELIEF-MORN",
            start_time=time(10, 0), end_time=time(18, 0),
            is_active=True
        )
        self.assertIsNotNone(relief_shift.pk)

    # -------------------------------------------------------------
    # 2. ShiftSession Concurrency & Lifecycle Transitions
    # -------------------------------------------------------------
    def test_duplicate_session_for_same_shift_and_date_rejected_by_db(self):
        """Database constraint prevents duplicate sessions for the same shift and operational date."""
        op_date = date(2026, 10, 20)
        session1 = ShiftSession.objects.create(
            shift=self.morning_shift,
            operational_date=op_date,
            status=ShiftSessionStatus.SCHEDULED
        )
        self.assertIsNotNone(session1.pk)

        # Attempt duplicate insert
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ShiftSession.objects.create(
                    shift=self.morning_shift,
                    operational_date=op_date,
                    status=ShiftSessionStatus.SCHEDULED
                )

    def test_shift_session_allowed_status_transitions(self):
        """Only valid state machine transitions are permitted."""
        session = ShiftSession.objects.create(
            shift=self.morning_shift,
            operational_date=date(2026, 10, 21),
            status=ShiftSessionStatus.SCHEDULED
        )
        # SCHEDULED -> CLOSED is invalid
        with self.assertRaises(ValidationError):
            session.validate_transition(ShiftSessionStatus.CLOSED)

        # SCHEDULED -> ACTIVE is valid
        session.open_session(user=self.operator1, initial_scale_zero=True, initial_printer_paper=True)
        self.assertEqual(session.status, ShiftSessionStatus.ACTIVE)
        self.assertIsNotNone(session.actual_start)
        self.assertEqual(session.opened_by, self.operator1)

        # ACTIVE -> CLOSED is valid
        session.close_session(user=self.operator1, notes="شیفت بدون حادثه پایان یافت.")
        self.assertEqual(session.status, ShiftSessionStatus.CLOSED)
        self.assertIsNotNone(session.actual_end)

        # CLOSED -> ACTIVE is terminal / invalid
        with self.assertRaises(ValidationError):
            session.validate_transition(ShiftSessionStatus.ACTIVE)

    # -------------------------------------------------------------
    # 3. Overnight Midnight Crossing & Operational Date Resolution
    # -------------------------------------------------------------
    def test_midnight_crossing_operational_date_resolution(self):
        """
        Overnight shift 23:00 to 07:00:
        Events occurring after midnight (e.g. 02:30 on day D+1) retain operational_date D.
        """
        # Event at 23:30 on Oct 27
        dt_pre_midnight = self.tz.localize(datetime(2026, 10, 27, 23, 30))
        op_date1 = ShiftResolutionService.resolve_operational_date(dt_pre_midnight, shift=self.night_shift)
        self.assertEqual(op_date1, date(2026, 10, 27))

        # Event at 02:30 on Oct 28 (next calendar day, but same overnight shift!)
        dt_post_midnight = self.tz.localize(datetime(2026, 10, 28, 2, 30))
        op_date2 = ShiftResolutionService.resolve_operational_date(dt_post_midnight, shift=self.night_shift)
        self.assertEqual(op_date2, date(2026, 10, 27))

        # Event after shift end at 08:30 on Oct 28
        dt_after_shift = self.tz.localize(datetime(2026, 10, 28, 8, 30))
        op_date3 = ShiftResolutionService.resolve_operational_date(dt_after_shift, shift=self.morning_shift)
        self.assertEqual(op_date3, date(2026, 10, 28))

    # -------------------------------------------------------------
    # 4. Multi-Operator Attendance & Check-in / Check-out
    # -------------------------------------------------------------
    def test_multi_operator_attendance_and_session_auto_checkout(self):
        """Multiple operators can check in, and closing session automatically checks out all operators."""
        session = ShiftSession.objects.create(
            shift=self.morning_shift,
            operational_date=date(2026, 10, 22),
            status=ShiftSessionStatus.ACTIVE,
            actual_start=timezone.now()
        )

        asg1 = ShiftResolutionService.check_in_operator(session, self.operator1, role=ShiftOperatorRole.PRIMARY)
        asg2 = ShiftResolutionService.check_in_operator(session, self.operator2, role=ShiftOperatorRole.ASSISTANT)

        self.assertEqual(asg1.status, ShiftAssignmentStatus.CHECKED_IN)
        self.assertEqual(asg2.status, ShiftAssignmentStatus.CHECKED_IN)
        self.assertEqual(session.assignments.filter(status=ShiftAssignmentStatus.CHECKED_IN).count(), 2)

        # Closing session automatically checks out both operators
        ShiftResolutionService.close_session(session, user=self.operator1)
        asg1.refresh_from_db()
        asg2.refresh_from_db()

        self.assertEqual(asg1.status, ShiftAssignmentStatus.CHECKED_OUT)
        self.assertIsNotNone(asg1.check_out_time)
        self.assertEqual(asg2.status, ShiftAssignmentStatus.CHECKED_OUT)
        self.assertIsNotNone(asg2.check_out_time)

    # -------------------------------------------------------------
    # 5. Single Active Check-in Policy (Overlap Prevention)
    # -------------------------------------------------------------
    def test_operator_cannot_check_in_to_two_sessions_simultaneously(self):
        """An operator cannot be CHECKED_IN in two different sessions concurrently."""
        session1 = ShiftSession.objects.create(
            shift=self.morning_shift,
            operational_date=date(2026, 10, 23),
            status=ShiftSessionStatus.ACTIVE
        )
        session2 = ShiftSession.objects.create(
            shift=self.night_shift,
            operational_date=date(2026, 10, 23),
            status=ShiftSessionStatus.ACTIVE
        )

        ShiftResolutionService.check_in_operator(session1, self.operator1)

        # Attempt to check in operator1 to session2 concurrently
        with self.assertRaises(ValidationError):
            ShiftResolutionService.check_in_operator(session2, self.operator1)

    # -------------------------------------------------------------
    # 6. Supervisor Substitution Workflow
    # -------------------------------------------------------------
    def test_supervisor_substitution_workflow_and_validation(self):
        """Supervisor substitution marks original operator as SUBSTITUTED and activates replacement."""
        session = ShiftSession.objects.create(
            shift=self.morning_shift,
            operational_date=date(2026, 10, 24),
            status=ShiftSessionStatus.ACTIVE
        )
        orig_asg = ShiftResolutionService.check_in_operator(session, self.operator1)

        # Non-supervisor cannot authorize substitution
        with self.assertRaises(ValidationError):
            ShiftResolutionService.substitute_operator(
                session=session,
                original_operator=self.operator1,
                replacement_operator=self.operator2,
                authorized_by=self.operator1,  # Not a supervisor!
                reason="بیماری ناگهانی اپراتور"
            )

        # Short reason (< 5 chars) rejected
        with self.assertRaises(ValidationError):
            ShiftResolutionService.substitute_operator(
                session=session,
                original_operator=self.operator1,
                replacement_operator=self.operator2,
                authorized_by=self.manager_user,
                reason="test"
            )

        # Successful substitution by supervisor
        new_asg = ShiftResolutionService.substitute_operator(
            session=session,
            original_operator=self.operator1,
            replacement_operator=self.operator2,
            authorized_by=self.manager_user,
            reason="مرخصی استعلاجی فوری اپراتور اصلی با تایید مدیر باسکول"
        )

        orig_asg.refresh_from_db()
        self.assertEqual(orig_asg.status, ShiftAssignmentStatus.SUBSTITUTED)
        self.assertEqual(new_asg.status, ShiftAssignmentStatus.CHECKED_IN)
        self.assertTrue(new_asg.is_substitution)
        self.assertEqual(new_asg.substituted_operator, self.operator1)
        self.assertEqual(new_asg.authorized_by, self.manager_user)

    # -------------------------------------------------------------
    # 7. Fail-Safe Continuity: Weighing Without Shift Session
    # -------------------------------------------------------------
    def test_weighing_without_active_shift_succeeds_unblocked(self):
        """
        CRITICAL FAIL-SAFE REQUIREMENT:
        When no shift session exists, weighing proceeds 100% UNINTERRUPTED.
        Ticket has first_weight_shift_session = None and first_weight_out_of_shift = True.
        ShiftExceptionLog is recorded for supervisor visibility.
        """
        # Ensure no active sessions
        ShiftSession.objects.all().update(status=ShiftSessionStatus.CLOSED)

        self.client.force_login(self.operator1)
        post_data = {
            "weight_mode": WeightMode.EMPTY_FIRST,
            "first_weight": "15200.00",
            "first_weight_date_jalali": "1405/07/28",
            "first_weight_time_str": "10:30",
            "party": self.party.pk,
            "product": self.product.pk,
            "operation_type": self.op_type.pk,
            "vehicle_type": self.v_type.pk,
            "origin": self.origin.pk,
            "destination": self.dest.pk,
            "unload_location": self.unload_loc.pk,
            "license_plate_display": "12 ج 345 - ایران 78",
            "driver_name_custom": "حسین اکبری",
            "driver_mobile_custom": "09121111111",
            "load_count": 1,
            "submit_action": "save_and_new"
        }

        resp = self.client.post(reverse("weighbridge:ticket_create"), post_data)
        self.assertEqual(resp.status_code, 302)

        ticket = WeighTicket.objects.filter(license_plate_display__contains="345").first()
        self.assertIsNotNone(ticket)
        self.assertEqual(ticket.first_weight, Decimal("15200.00"))
        self.assertIsNone(ticket.first_weight_shift_session)
        self.assertTrue(ticket.first_weight_out_of_shift)

        # Exception log must exist for supervisor
        exc = ShiftExceptionLog.objects.filter(ticket=ticket).first()
        self.assertIsNotNone(exc)
        self.assertEqual(exc.weighing_phase, "FIRST")
        self.assertEqual(exc.operator, self.operator1)
        self.assertIsNone(exc.acknowledged_by)

        # Supervisor acknowledges exception
        self.client.force_login(self.manager_user)
        ack_resp = self.client.post(
            reverse("shifts:exception_acknowledge", kwargs={"pk": exc.pk}),
            {"acknowledgement_note": "بررسی شد: تاخیر بازگشایی شیفت به دلیل قطعی برق بود."}
        )
        self.assertEqual(ack_resp.status_code, 302)
        exc.refresh_from_db()
        self.assertEqual(exc.acknowledged_by, self.manager_user)

    # -------------------------------------------------------------
    # 8. Weighing Integration With Active Shift & Invariance
    # -------------------------------------------------------------
    def test_weighing_associates_active_shift_and_preserves_first_operator(self):
        """
        Weighing in active shift associates session.
        Second weight in another shift preserves first_weight_operator and first session invariant!
        """
        session_morn = ShiftSession.objects.create(
            shift=self.morning_shift,
            operational_date=date(2026, 10, 25),
            status=ShiftSessionStatus.ACTIVE,
            actual_start=timezone.now()
        )
        ShiftResolutionService.check_in_operator(session_morn, self.operator1)

        # 1. First weighing by operator 1
        self.client.force_login(self.operator1)
        post_data_1 = {
            "weight_mode": WeightMode.EMPTY_FIRST,
            "first_weight": "12000.00",
            "first_weight_date_jalali": "1405/07/28",
            "first_weight_time_str": "09:00",
            "party": self.party.pk,
            "product": self.product.pk,
            "operation_type": self.op_type.pk,
            "vehicle_type": self.v_type.pk,
            "origin": self.origin.pk,
            "destination": self.dest.pk,
            "unload_location": self.unload_loc.pk,
            "license_plate_display": "25 ج 678 - ایران 11",
            "driver_name_custom": "رضا مرادی",
            "driver_mobile_custom": "09122222222",
            "load_count": 1,
            "submit_action": "save_and_yard"
        }
        resp1 = self.client.post(reverse("weighbridge:ticket_create"), post_data_1)
        self.assertEqual(resp1.status_code, 302)

        ticket = WeighTicket.objects.get(license_plate_display__contains="678")
        self.assertEqual(ticket.first_weight_operator, self.operator1)
        self.assertEqual(ticket.first_weight_shift_session, session_morn)
        self.assertFalse(ticket.first_weight_out_of_shift)

        # 2. Close morning shift and open night shift with operator 2
        ShiftResolutionService.close_session(session_morn, user=self.operator1)

        session_night = ShiftSession.objects.create(
            shift=self.night_shift,
            operational_date=date(2026, 10, 25),
            status=ShiftSessionStatus.ACTIVE,
            actual_start=timezone.now()
        )
        ShiftResolutionService.check_in_operator(session_night, self.operator2)

        # 3. Second weighing by operator 2 in night shift
        self.client.force_login(self.operator2)
        post_data_2 = {
            "second_weight": "24500.00",
            "second_weight_date_jalali": "1405/07/28",
            "second_weight_time_str": "23:45",
            "loss_percent": "0.00",
            "submit_action": "save_and_complete"
        }
        resp2 = self.client.post(reverse("weighbridge:ticket_second_weight", kwargs={"pk": ticket.pk}), post_data_2)
        self.assertEqual(resp2.status_code, 302)

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.COMPLETED)
        # CRITICAL INVARIANCE CHECKS:
        # First weight operator and shift session MUST REMAIN UNTOUCHED
        self.assertEqual(ticket.first_weight_operator, self.operator1)
        self.assertEqual(ticket.first_weight_shift_session, session_morn)
        # Second weight operator and shift session belong to Operator 2 and Night Session
        self.assertEqual(ticket.second_weight_operator, self.operator2)
        self.assertEqual(ticket.second_weight_shift_session, session_night)

    # -------------------------------------------------------------
    # 9. UI Permissions & Access Control
    # -------------------------------------------------------------
    def test_shift_ui_permission_boundaries(self):
        """Unauthorized viewers cannot manage shift templates or open/close sessions."""
        self.client.force_login(self.viewer_user)

        # Viewer cannot access shift templates
        resp = self.client.get(reverse("shifts:shift_list"))
        self.assertEqual(resp.status_code, 302)  # Redirects with permission error

        # Viewer cannot open session
        resp_open = self.client.get(reverse("shifts:session_open"))
        self.assertEqual(resp_open.status_code, 302)

        # Manager can access shift templates
        self.client.force_login(self.manager_user)
        resp_mgr = self.client.get(reverse("shifts:shift_list"))
        self.assertEqual(resp_mgr.status_code, 200)

        # Operator can access sessions list
        self.client.force_login(self.operator1)
        resp_op = self.client.get(reverse("shifts:session_list"))
        self.assertEqual(resp_op.status_code, 200)

    # -------------------------------------------------------------
    # 10. Historical Data Preservation
    # -------------------------------------------------------------
    def test_historical_tickets_remain_valid_with_null_shift(self):
        """Historical tickets before Phase 4.1 have null shift sessions and remain completely intact."""
        hist_ticket = WeighTicket.objects.create(
            serial_number="PB-HIST-9999",
            status=TicketStatus.COMPLETED,
            first_weight=Decimal("14000.00"),
            second_weight=Decimal("25000.00"),
            net_weight=Decimal("11000.00"),
            first_weight_date=date(2026, 8, 1),
            second_weight_date=date(2026, 8, 1),
            first_weight_operator=self.operator1,
            second_weight_operator=self.operator1
        )
        hist_ticket.refresh_from_db()
        self.assertIsNone(hist_ticket.first_weight_shift_session)
        self.assertIsNone(hist_ticket.second_weight_shift_session)
        self.assertFalse(hist_ticket.first_weight_out_of_shift)
        self.assertEqual(hist_ticket.status, TicketStatus.COMPLETED)
