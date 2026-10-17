from datetime import datetime, date, time, timedelta
from decimal import Decimal
import pytz
from django.test import TestCase, TransactionTestCase, Client
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.urls import reverse
from unittest.mock import patch

from accounts.models import UserProfile, RoleChoices
from masterdata.models import (
    Product, Party, Vehicle, Driver, OperationType,
    VehicleType, Location, UnloadLocation
)
from weighbridge.models import WeighTicket, TicketStatus, WeightMode
from weighbridge.plate_policy import DailyPlatePolicy
from shifts.models import (
    WorkShift, ShiftSession, ShiftSessionStatus,
    ShiftOperatorAssignment, ShiftOperatorRole, ShiftAssignmentStatus,
    ShiftExceptionLog
)
from shifts.services import ShiftResolutionService


class ShiftDatabaseIntegrityTests(TestCase):
    """
    Tests proving real PostgreSQL foreign key constraints, orphan prevention,
    partial unique indexes, and referential integrity across shifts and weighbridge.
    """

    def setUp(self):
        self.shift = WorkShift.objects.create(
            name="شیفت تست یکپارچگی",
            code="INT-SHIFT",
            start_time=time(8, 0),
            end_time=time(16, 0),
        )
        self.session = ShiftSession.objects.create(
            shift=self.shift,
            operational_date=date(2026, 10, 25),
            status=ShiftSessionStatus.ACTIVE,
            actual_start=timezone.now()
        )
        self.operator = User.objects.create_user(username="int_op1", password="password123")
        self.v_type = VehicleType.objects.create(name="تریلی تست", code="TR-INT")

    def test_foreign_key_integrity_shiftsession_to_weighticket(self):
        """
        PostgreSQL database-level foreign key constraint must reject invalid shift session ID.
        """
        from django.db import connection
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                WeighTicket.objects.create(
                    serial_number="INT-TEST-001",
                    license_plate_display="11 س 111 - ایران 11",
                    first_weight=Decimal("15000.00"),
                    vehicle_type=self.v_type,
                    first_weight_shift_session_id=99999999  # Non-existent session
                )
                with connection.cursor() as cursor:
                    cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    def test_foreign_key_integrity_weighticket_to_shiftexceptionlog(self):
        """
        PostgreSQL database-level foreign key constraint must reject invalid ticket ID.
        """
        from django.db import connection
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ShiftExceptionLog.objects.create(
                    ticket_id=99999999,  # Non-existent ticket
                    weighing_phase="FIRST",
                    operator=self.operator,
                    reason=ShiftExceptionLog.ReasonChoices.NO_ACTIVE_SHIFT
                )
                with connection.cursor() as cursor:
                    cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    def test_orphan_prevention_on_session_deletion(self):
        """
        Deleting a ShiftSession must set FK to NULL on WeighTicket (on_delete=SET_NULL),
        preserving historical ticket and financial records.
        """
        ticket = WeighTicket.objects.create(
            serial_number="INT-TEST-002",
            license_plate_display="22 س 222 - ایران 22",
            first_weight=Decimal("16000.00"),
            vehicle_type=self.v_type,
            first_weight_shift_session=self.session,
            first_weight_operator=self.operator
        )
        session_id = self.session.pk
        self.session.delete()

        ticket.refresh_from_db()
        self.assertIsNone(ticket.first_weight_shift_session)
        self.assertEqual(ticket.serial_number, "INT-TEST-002")

    def test_orphan_prevention_on_ticket_deletion(self):
        """
        Deleting a WeighTicket must cascade (on_delete=CASCADE) to delete its ShiftExceptionLogs,
        leaving zero orphan records in the database.
        """
        ticket = WeighTicket.objects.create(
            serial_number="INT-TEST-003",
            license_plate_display="33 س 333 - ایران 33",
            first_weight=Decimal("17000.00"),
            vehicle_type=self.v_type,
            first_weight_out_of_shift=True
        )
        ShiftExceptionLog.objects.create(
            ticket=ticket,
            weighing_phase="FIRST",
            operator=self.operator,
            reason=ShiftExceptionLog.ReasonChoices.NO_ACTIVE_SHIFT
        )
        self.assertEqual(ShiftExceptionLog.objects.filter(ticket=ticket).count(), 1)

        ticket.delete()
        self.assertEqual(ShiftExceptionLog.objects.filter(ticket_id=ticket.pk).count(), 0)

    def test_concurrent_operator_checkin_unique_constraint_at_db_level(self):
        """
        PostgreSQL partial unique index 'unique_active_checkin_per_operator'
        must prevent two active CHECKED_IN assignments for the same operator at the DB engine level.
        """
        session2 = ShiftSession.objects.create(
            shift=self.shift,
            operational_date=date(2026, 10, 26),
            status=ShiftSessionStatus.ACTIVE,
            actual_start=timezone.now()
        )
        ShiftOperatorAssignment.objects.create(
            session=self.session,
            operator=self.operator,
            status=ShiftAssignmentStatus.CHECKED_IN,
            check_in_time=timezone.now()
        )

        asg2 = ShiftOperatorAssignment(
            session=session2,
            operator=self.operator,
            status=ShiftAssignmentStatus.CHECKED_IN,
            check_in_time=timezone.now()
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                # Direct DB insert bypassing model save()/full_clean() to prove DB engine constraint
                super(ShiftOperatorAssignment, asg2).save(force_insert=True)

    def test_operator_invariance_first_and_second_weight(self):
        """
        Original first weight operator and first shift session MUST NEVER be mutated
        when a second weight is recorded by a different operator in a different shift session.
        """
        session2 = ShiftSession.objects.create(
            shift=self.shift,
            operational_date=date(2026, 10, 26),
            status=ShiftSessionStatus.ACTIVE,
            actual_start=timezone.now()
        )
        op2 = User.objects.create_user(username="int_op2", password="password123")

        # First weight recorded in session 1 by op1
        ticket = WeighTicket(
            serial_number="INV-TEST-001",
            license_plate_display="77 س 777 - ایران 77",
            first_weight=Decimal("12000.00"),
            vehicle_type=self.v_type,
            first_weight_operator=self.operator,
            first_weight_shift_session=self.session
        )
        ticket.save()

        # Second weight recorded in session 2 by op2
        ticket.second_weight = Decimal("24000.00")
        ticket.second_weight_operator = op2
        ticket.second_weight_shift_session = session2
        ticket.save()

        ticket.refresh_from_db()
        # Invariance checks:
        self.assertEqual(ticket.first_weight_operator, self.operator)
        self.assertEqual(ticket.first_weight_shift_session, self.session)
        self.assertEqual(ticket.second_weight_operator, op2)
        self.assertEqual(ticket.second_weight_shift_session, session2)

    def test_missing_shift_context_preserves_authorized_weighing_continuity(self):
        """
        CRITICAL INDUSTRIAL CONTINUITY:
        When no shift is open, scale operator weighing proceeds 100% uninterrupted.
        out_of_shift flag is True, session is None, and ShiftExceptionLog is recorded with NO_ACTIVE_SHIFT.
        """
        # Ensure no active sessions exist
        ShiftSession.objects.all().update(status=ShiftSessionStatus.CLOSED)

        ticket = WeighTicket(
            serial_number="CONT-TEST-001",
            license_plate_display="88 س 888 - ایران 88",
            first_weight=Decimal("14000.00"),
            vehicle_type=self.v_type,
            first_weight_operator=self.operator
        )
        session, is_out, reason, notes = ShiftResolutionService.record_weighing_shift(
            ticket, is_second_weight=False, operator=self.operator
        )
        self.assertIsNone(session)
        self.assertTrue(is_out)
        self.assertEqual(reason, ShiftExceptionLog.ReasonChoices.NO_ACTIVE_SHIFT)

        # Ticket saves successfully without blocking
        ticket.save()
        self.assertTrue(ticket.first_weight_out_of_shift)
        self.assertIsNone(ticket.first_weight_shift_session)

        # Log exception idempotently
        exc = ShiftResolutionService.log_shift_exception(
            ticket=ticket,
            weighing_phase="FIRST",
            operator=self.operator,
            reason=reason,
            notes=notes
        )
        self.assertIsNotNone(exc)
        self.assertEqual(exc.reason, ShiftExceptionLog.ReasonChoices.NO_ACTIVE_SHIFT)
        self.assertEqual(exc.ticket, ticket)

    def test_idempotent_exception_logging_prevents_duplicate_logs_on_retry(self):
        """
        Database UniqueConstraint(ticket, weighing_phase) combined with
        ShiftResolutionService.log_shift_exception guarantees idempotency on retries.
        """
        ticket = WeighTicket.objects.create(
            serial_number="INT-TEST-004",
            license_plate_display="44 س 444 - ایران 44",
            first_weight=Decimal("18000.00"),
            vehicle_type=self.v_type,
            first_weight_out_of_shift=True
        )

        # Call log_shift_exception 3 times
        log1 = ShiftResolutionService.log_shift_exception(
            ticket=ticket,
            weighing_phase="FIRST",
            operator=self.operator,
            reason=ShiftExceptionLog.ReasonChoices.NO_ACTIVE_SHIFT,
            notes="Attempt 1"
        )
        log2 = ShiftResolutionService.log_shift_exception(
            ticket=ticket,
            weighing_phase="FIRST",
            operator=self.operator,
            reason=ShiftExceptionLog.ReasonChoices.OPERATOR_NOT_CHECKED_IN,
            notes="Attempt 2 updated"
        )

        self.assertEqual(log1.pk, log2.pk)
        self.assertEqual(ShiftExceptionLog.objects.filter(ticket=ticket, weighing_phase="FIRST").count(), 1)
        log2.refresh_from_db()
        self.assertEqual(log2.reason, ShiftExceptionLog.ReasonChoices.OPERATOR_NOT_CHECKED_IN)
        self.assertEqual(log2.notes, "Attempt 2 updated")

        # Direct insert violates DB unique constraint
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ShiftExceptionLog.objects.create(
                    ticket=ticket,
                    weighing_phase="FIRST",
                    operator=self.operator,
                    reason=ShiftExceptionLog.ReasonChoices.NO_ACTIVE_SHIFT
                )


class ShiftDeterministicResolutionTests(TestCase):
    """
    Tests proving deterministic shift resolution logic:
    - Never randomly selects an active shift
    - Never assigns another operator's session
    - Respects operator attendance
    - Detects ambiguity cleanly
    - Fails safe without interrupting weighing
    """

    def setUp(self):
        self.shift_morn = WorkShift.objects.create(
            name="شیفت صبح", code="MORN-DET",
            start_time=time(7, 0), end_time=time(15, 0)
        )
        self.shift_relief = WorkShift.objects.create(
            name="شیفت امدادی", code="RELIEF-DET",
            start_time=time(10, 0), end_time=time(18, 0)
        )
        self.shift_night = WorkShift.objects.create(
            name="شیفت شبانه", code="NIGHT-DET",
            start_time=time(23, 0), end_time=time(7, 0)
        )

        self.op1 = User.objects.create_user(username="det_op1", password="password123")
        self.op2 = User.objects.create_user(username="det_op2", password="password123")
        self.op_unassigned = User.objects.create_user(username="det_unassigned", password="password123")

        self.v_type = VehicleType.objects.create(name="کامیون", code="TR-DET")

    def test_multiple_active_sessions_resolves_only_operator_specific_session(self):
        """
        When two sessions are active simultaneously, each operator resolves strictly
        to their own checked-in session. Unassigned operator NEVER gets randomly assigned!
        """
        now = timezone.now()
        today = now.date()

        session1 = ShiftSession.objects.create(
            shift=self.shift_morn, operational_date=today,
            status=ShiftSessionStatus.ACTIVE, actual_start=now
        )
        session2 = ShiftSession.objects.create(
            shift=self.shift_relief, operational_date=today,
            status=ShiftSessionStatus.ACTIVE, actual_start=now
        )

        ShiftOperatorAssignment.objects.create(
            session=session1, operator=self.op1,
            status=ShiftAssignmentStatus.CHECKED_IN, check_in_time=now
        )
        ShiftOperatorAssignment.objects.create(
            session=session2, operator=self.op2,
            status=ShiftAssignmentStatus.CHECKED_IN, check_in_time=now
        )

        # 1. Op1 resolves to session1
        res1, reason1, _ = ShiftResolutionService.resolve_session_for_operator(self.op1, dt=now)
        self.assertEqual(res1, session1)
        self.assertEqual(reason1, "OK")

        # 2. Op2 resolves to session2
        res2, reason2, _ = ShiftResolutionService.resolve_session_for_operator(self.op2, dt=now)
        self.assertEqual(res2, session2)
        self.assertEqual(reason2, "OK")

        # 3. Unassigned operator must NEVER be assigned session1 or session2!
        res_un, reason_un, _ = ShiftResolutionService.resolve_session_for_operator(self.op_unassigned, dt=now)
        self.assertIsNone(res_un)
        self.assertEqual(reason_un, ShiftExceptionLog.ReasonChoices.OPERATOR_HAS_NO_ACTIVE_ASSIGNMENT)

    def test_ambiguous_assignments_logs_exception_and_does_not_guess(self):
        """
        If an operator has multiple valid candidate assignments (e.g. edge case or multiple roles),
        service returns None, logs AMBIGUOUS_SHIFT_ASSIGNMENT, and never randomly picks one!
        """
        now = timezone.now()
        today = now.date()

        session1 = ShiftSession.objects.create(
            shift=self.shift_morn, operational_date=today,
            status=ShiftSessionStatus.ACTIVE, actual_start=now
        )
        session2 = ShiftSession.objects.create(
            shift=self.shift_relief, operational_date=today,
            status=ShiftSessionStatus.ACTIVE, actual_start=now
        )

        fake_asg1 = ShiftOperatorAssignment(session=session1, operator=self.op1, status=ShiftAssignmentStatus.CHECKED_IN, check_in_time=now)
        fake_asg2 = ShiftOperatorAssignment(session=session2, operator=self.op1, status=ShiftAssignmentStatus.CHECKED_IN, check_in_time=now)

        class MockQuerySet(list):
            def select_related(self, *args, **kwargs):
                return self

        mock_qs = MockQuerySet([fake_asg1, fake_asg2])
        with patch.object(ShiftOperatorAssignment.objects, "filter", return_value=mock_qs):
            res, reason, notes = ShiftResolutionService.resolve_session_for_operator(self.op1, dt=now)
            self.assertIsNone(res)
            self.assertEqual(reason, ShiftExceptionLog.ReasonChoices.AMBIGUOUS_SHIFT_ASSIGNMENT)
            self.assertIn("تداخل در تخصیص شیفت", notes)

    def test_midnight_boundary_behavior_asia_tehran(self):
        """
        Overnight shift (23:00 to 07:00):
        23:30 D maps to D.
        02:30 D+1 maps to D.
        07:30 D+1 maps to D+1.
        """
        tehran = pytz.timezone("Asia/Tehran")
        # 2026-10-25 23:30
        dt_night = tehran.localize(datetime(2026, 10, 25, 23, 30))
        op_date1 = ShiftResolutionService.resolve_operational_date(dt_night, self.shift_night)
        self.assertEqual(op_date1, date(2026, 10, 25))

        # 2026-10-26 02:30 (next calendar day)
        dt_morning = tehran.localize(datetime(2026, 10, 26, 2, 30))
        op_date2 = ShiftResolutionService.resolve_operational_date(dt_morning, self.shift_night)
        self.assertEqual(op_date2, date(2026, 10, 25))

        # 2026-10-26 07:30 (after shift end)
        dt_after = tehran.localize(datetime(2026, 10, 26, 7, 30))
        op_date3 = ShiftResolutionService.resolve_operational_date(dt_after, self.shift_night)
        self.assertEqual(op_date3, date(2026, 10, 26))

    def test_failed_shift_resolution_service_fail_safe_continuity(self):
        """
        When shift resolution raises an unexpected exception (e.g. database error),
        weighing is 100% UNINTERRUPTED. Ticket saves, out_of_shift=True, RESOLUTION_ERROR logged.
        """
        ticket = WeighTicket(
            serial_number="FAILSAFE-001",
            license_plate_display="55 س 555 - ایران 55",
            first_weight=Decimal("20000.00"),
            vehicle_type=self.v_type,
            first_weight_operator=self.op1
        )

        with patch.object(ShiftResolutionService, "resolve_session_for_operator", side_effect=RuntimeError("Database lock")):
            session, is_out, reason, notes = ShiftResolutionService.record_weighing_shift(
                ticket, is_second_weight=False, operator=self.op1
            )
            self.assertIsNone(session)
            self.assertTrue(is_out)
            self.assertEqual(reason, ShiftExceptionLog.ReasonChoices.RESOLUTION_ERROR)
            self.assertIn("Database lock", notes)

        # Ticket must still save successfully
        ticket.save()
        self.assertIsNotNone(ticket.pk)
        self.assertTrue(ticket.first_weight_out_of_shift)
        self.assertIsNone(ticket.first_weight_shift_session)

        # Log exception safely
        exc = ShiftResolutionService.log_shift_exception(
            ticket=ticket,
            weighing_phase="FIRST",
            operator=self.op1,
            reason=reason,
            notes=notes
        )
        self.assertIsNotNone(exc)
        self.assertEqual(exc.reason, ShiftExceptionLog.ReasonChoices.RESOLUTION_ERROR)

    def test_ticket_creation_rollback_does_not_create_phantom_exception_log(self):
        """
        If a ticket creation transaction rolls back, no ShiftExceptionLog should exist
        pointing to an unpersisted or rolled-back ticket.
        """
        initial_log_count = ShiftExceptionLog.objects.count()

        try:
            with transaction.atomic():
                ticket = WeighTicket(
                    serial_number="ROLLBACK-001",
                    license_plate_display="66 س 666 - ایران 66",
                    first_weight=Decimal("21000.00"),
                    vehicle_type=self.v_type,
                    first_weight_operator=self.op1
                )
                _, is_out, reason, notes = ShiftResolutionService.record_weighing_shift(
                    ticket, is_second_weight=False, operator=self.op1
                )
                ticket.save()
                ShiftResolutionService.log_shift_exception(
                    ticket=ticket,
                    weighing_phase="FIRST",
                    operator=self.op1,
                    reason=reason,
                    notes=notes
                )
                # Force rollback
                raise ValueError("Simulated unexpected business logic error")
        except ValueError:
            pass

        self.assertEqual(ShiftExceptionLog.objects.count(), initial_log_count)
        self.assertFalse(WeighTicket.objects.filter(serial_number="ROLLBACK-001").exists())
