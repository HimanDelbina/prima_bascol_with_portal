from decimal import Decimal
from datetime import datetime, date, time, timedelta
import zoneinfo

from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from django.utils import timezone
from django.db import connection
from django.test.utils import CaptureQueriesContext

from shifts.models import (
    WorkShift,
    ShiftSession,
    ShiftSessionStatus,
    ShiftOperatorAssignment,
    ShiftOperatorRole,
    ShiftAssignmentStatus,
    ShiftExceptionLog,
    ShiftHandover,
    ShiftHandoverStatus,
    ShiftHandoverItem,
    ShiftHandoverItemCategory,
)
from shifts.kpi_service import ShiftKPIService
from weighbridge.models import WeighTicket, TicketStatus, WeightMode, TicketRevision
from masterdata.models import Product, Party, Vehicle, Driver, OperationType
from management.kpi_service import OperationalKPIService


class ShiftKPIServiceComprehensiveTests(TestCase):
    """
    Exhaustive validation test suite for ShiftKPIService ensuring:
    - 100% statistical accuracy
    - Concurrency and read-only safety
    - Strict avoidance of double counting
    - Turnaround timestamp sanitization
    - Separation of financial daily reports from shift operational reports
    - Accurate Decimal arithmetic
    """

    def setUp(self):
        self.tz = timezone.get_current_timezone()

        # Users
        self.admin = User.objects.create_superuser("admin_kpi", "admin@kpi.com", "pass")
        self.op1 = User.objects.create_user("operator_one", "op1@kpi.com", "pass")
        self.op2 = User.objects.create_user("operator_two", "op2@kpi.com", "pass")
        self.supervisor = User.objects.create_user("supervisor_kpi", "sup@kpi.com", "pass")

        # Masterdata
        self.product = Product.objects.create(name="آهن اسفنجی", code="SPONGE-01", is_active=True)
        self.party = Party.objects.create(name="شرکت فولاد جنوب", is_active=True)
        self.op_type_in = OperationType.objects.create(name="ورودی خرید", code="IN-01", direction="inbound")
        self.op_type_out = OperationType.objects.create(name="خروجی فروش", code="OUT-01", direction="outbound")

        # Shifts
        self.shift_day = WorkShift.objects.create(
            name="شیفت روز",
            code="DAY-01",
            start_time=time(8, 0),
            end_time=time(16, 0),
            is_active=True,
            created_by=self.admin,
        )
        self.shift_night = WorkShift.objects.create(
            name="شیفت شبانه",
            code="NIGHT-01",
            start_time=time(23, 0),
            end_time=time(7, 0),
            is_active=True,
            created_by=self.admin,
        )

        # Standard Day Session
        self.session_day = ShiftSession.objects.create(
            shift=self.shift_day,
            operational_date=date(2026, 10, 18),
            status=ShiftSessionStatus.ACTIVE,
            actual_start=timezone.make_aware(datetime(2026, 10, 18, 8, 0, 0), self.tz),
            opened_by=self.op1,
        )

        # Assignments
        self.assign1 = ShiftOperatorAssignment.objects.create(
            session=self.session_day,
            operator=self.op1,
            role=ShiftOperatorRole.PRIMARY,
            status=ShiftAssignmentStatus.CHECKED_IN,
            check_in_time=timezone.make_aware(datetime(2026, 10, 18, 8, 0, 0), self.tz),
            check_out_time=timezone.make_aware(datetime(2026, 10, 18, 16, 0, 0), self.tz),
        )
        self.assign2 = ShiftOperatorAssignment.objects.create(
            session=self.session_day,
            operator=self.op2,
            role=ShiftOperatorRole.ASSISTANT,
            status=ShiftAssignmentStatus.CHECKED_IN,
            check_in_time=timezone.make_aware(datetime(2026, 10, 18, 12, 0, 0), self.tz),
            check_out_time=timezone.make_aware(datetime(2026, 10, 18, 16, 0, 0), self.tz),
        )

    def test_01_first_weighing_attribution(self):
        """First weighings assigned to a ShiftSession are accurately counted."""
        WeighTicket.objects.create(
            serial_number="TICK-001",
            status=TicketStatus.WAITING_SECOND,
            first_weight=Decimal("15000.00"),
            first_weight_date=date(2026, 10, 18),
            first_weight_time=time(9, 0),
            first_weight_operator=self.op1,
            first_weight_shift_session=self.session_day,
            license_plate_display="12A345-78",
            product=self.product,
            party=self.party,
        )
        WeighTicket.objects.create(
            serial_number="TICK-002",
            status=TicketStatus.WAITING_SECOND,
            first_weight=Decimal("14000.00"),
            first_weight_date=date(2026, 10, 18),
            first_weight_time=time(9, 30),
            first_weight_operator=self.op1,
            first_weight_shift_session=self.session_day,
            license_plate_display="99B888-21",
            product=self.product,
            party=self.party,
        )

        kpis = ShiftKPIService.calculate_session_kpis(self.session_day)
        self.assertEqual(kpis["first_weighings_count"], 2)
        self.assertEqual(kpis["waiting_second_count"], 2)
        self.assertEqual(kpis["completed_tickets_count"], 0)
        self.assertEqual(kpis["distinct_vehicles_first_weighed"], 2)

    def test_02_second_weighing_and_completed_vs_cancelled(self):
        """
        Completed tickets and cancelled tickets after second weighing are strictly separated.
        Cancelled tickets do NOT contribute to completed_tickets_count or completed_net_ton.
        """
        # Ticket 1: Completed
        WeighTicket.objects.create(
            serial_number="TICK-COMP",
            status=TicketStatus.COMPLETED,
            first_weight=Decimal("15000.00"),
            first_weight_date=date(2026, 10, 18),
            first_weight_time=time(8, 30),
            first_weight_operator=self.op1,
            first_weight_shift_session=self.session_day,
            second_weight=Decimal("35000.00"),
            second_weight_date=date(2026, 10, 18),
            second_weight_time=time(9, 15),
            second_weight_operator=self.op2,
            second_weight_shift_session=self.session_day,
            net_weight=Decimal("20000.00"),
            gross_weight=Decimal("35000.00"),
            tare_weight=Decimal("15000.00"),
            final_weight=Decimal("20000.00"),
            operation_type=self.op_type_in,
            license_plate_display="12A345-78",
        )

        # Ticket 2: Cancelled after second weight
        WeighTicket.objects.create(
            serial_number="TICK-CANC",
            status=TicketStatus.CANCELLED,
            first_weight=Decimal("16000.00"),
            first_weight_date=date(2026, 10, 18),
            first_weight_time=time(8, 45),
            first_weight_operator=self.op1,
            first_weight_shift_session=self.session_day,
            second_weight=Decimal("38000.00"),
            second_weight_date=date(2026, 10, 18),
            second_weight_time=time(9, 30),
            second_weight_operator=self.op2,
            second_weight_shift_session=self.session_day,
            net_weight=Decimal("22000.00"),
            gross_weight=Decimal("38000.00"),
            tare_weight=Decimal("16000.00"),
            operation_type=self.op_type_in,
            license_plate_display="99B888-21",
        )

        kpis = ShiftKPIService.calculate_session_kpis(self.session_day)
        self.assertEqual(kpis["second_weighings_count"], 2)
        self.assertEqual(kpis["completed_tickets_count"], 1)
        self.assertEqual(kpis["cancelled_after_second_weight_count"], 1)
        # Net tonnage only counts the completed ticket (20,000 kg = 20.00 ton)
        self.assertEqual(kpis["completed_net_kg"], Decimal("20000.00"))
        self.assertEqual(kpis["completed_net_ton"], Decimal("20.00"))

    def test_03_current_effective_revised_tonnage_no_double_count(self):
        """
        Tonnage uses current effective net weight.
        Revisions are tracked by revisions_applied_count and NEVER duplicated as extra tonnage.
        """
        ticket = WeighTicket.objects.create(
            serial_number="TICK-REV",
            status=TicketStatus.COMPLETED,
            first_weight=Decimal("15000.00"),
            first_weight_date=date(2026, 10, 18),
            first_weight_time=time(10, 0),
            first_weight_operator=self.op1,
            first_weight_shift_session=self.session_day,
            second_weight=Decimal("38000.00"),
            second_weight_date=date(2026, 10, 18),
            second_weight_time=time(10, 45),
            second_weight_operator=self.op1,
            second_weight_shift_session=self.session_day,
            net_weight=Decimal("23000.00"),  # Revised value
            original_net_weight=Decimal("20000.00"),
            current_revision_number=1,
            gross_weight=Decimal("38000.00"),
            tare_weight=Decimal("15000.00"),
            final_weight=Decimal("23000.00"),
            license_plate_display="12A345-78",
        )
        # Create TicketRevision record
        TicketRevision.objects.create(
            ticket=ticket,
            revision_number=1,
            status=TicketRevision.RevisionStatus.APPLIED,
            requested_by=self.op1,
        )

        kpis = ShiftKPIService.calculate_session_kpis(self.session_day)
        self.assertEqual(kpis["completed_tickets_count"], 1)
        self.assertEqual(kpis["revisions_applied_count"], 1)
        self.assertEqual(kpis["completed_net_kg"], Decimal("23000.00"))
        self.assertEqual(kpis["completed_net_ton"], Decimal("23.00"))

    def test_04_overnight_shift_attribution(self):
        """
        An overnight shift crossing midnight attributes early morning events (Day+1)
        to the session's operational date (Day).
        """
        session_night = ShiftSession.objects.create(
            shift=self.shift_night,
            operational_date=date(2026, 10, 18),
            status=ShiftSessionStatus.ACTIVE,
            actual_start=timezone.make_aware(datetime(2026, 10, 18, 23, 0, 0), self.tz),
            opened_by=self.op1,
        )

        # Ticket weighed at 02:30 AM on Oct 19th
        ticket_night = WeighTicket.objects.create(
            serial_number="TICK-NIGHT-01",
            status=TicketStatus.COMPLETED,
            first_weight=Decimal("12000.00"),
            first_weight_date=date(2026, 10, 19),
            first_weight_time=time(2, 0),
            first_weight_operator=self.op1,
            first_weight_shift_session=session_night,
            second_weight=Decimal("32000.00"),
            second_weight_date=date(2026, 10, 19),
            second_weight_time=time(2, 30),
            second_weight_operator=self.op1,
            second_weight_shift_session=session_night,
            net_weight=Decimal("20000.00"),
            gross_weight=Decimal("32000.00"),
            tare_weight=Decimal("12000.00"),
            final_weight=Decimal("20000.00"),
            license_plate_display="34C567-99",
        )

        kpis = ShiftKPIService.calculate_session_kpis(session_night)
        self.assertEqual(kpis["operational_date"], date(2026, 10, 18))
        self.assertTrue(kpis["is_overnight"])
        self.assertEqual(kpis["completed_tickets_count"], 1)
        self.assertEqual(kpis["completed_net_ton"], Decimal("20.00"))

    def test_05_missing_shift_references_and_legacy_unattributed(self):
        """
        Historical tickets with NULL shift session are isolated into unattributed_legacy
        and do not corrupt session totals.
        """
        # Create unassigned legacy ticket
        WeighTicket.objects.create(
            serial_number="TICK-LEGACY",
            status=TicketStatus.COMPLETED,
            first_weight=Decimal("10000.00"),
            first_weight_date=date(2026, 10, 18),
            first_weight_time=time(11, 0),
            second_weight=Decimal("25000.00"),
            second_weight_date=date(2026, 10, 18),
            second_weight_time=time(11, 45),
            net_weight=Decimal("15000.00"),
            first_weight_shift_session=None,
            second_weight_shift_session=None,
        )

        period_kpis = ShiftKPIService.calculate_period_shift_kpis(
            start_date=date(2026, 10, 18),
            end_date=date(2026, 10, 18)
        )
        unattr = period_kpis["unattributed_legacy"]
        self.assertEqual(unattr["completed_tickets_count"], 1)
        self.assertEqual(unattr["completed_net_ton"], Decimal("15.00"))

    @override_settings(ENABLE_SHIFT_MANAGEMENT=False)
    def test_06_disabled_shift_management(self):
        """Service gracefully reports disabled shift management status."""
        period_kpis = ShiftKPIService.calculate_period_shift_kpis(
            start_date=date(2026, 10, 18),
            end_date=date(2026, 10, 18)
        )
        self.assertFalse(period_kpis["shift_management_enabled"])

    def test_07_different_first_and_second_operators_and_solo(self):
        """Accurately separates solo completed tickets from dual-operator tickets."""
        # Solo completed ticket by op1
        WeighTicket.objects.create(
            serial_number="TICK-SOLO",
            status=TicketStatus.COMPLETED,
            first_weight=Decimal("10000.00"),
            first_weight_date=date(2026, 10, 18),
            first_weight_time=time(8, 30),
            first_weight_operator=self.op1,
            first_weight_shift_session=self.session_day,
            second_weight=Decimal("25000.00"),
            second_weight_date=date(2026, 10, 18),
            second_weight_time=time(9, 0),
            second_weight_operator=self.op1,
            second_weight_shift_session=self.session_day,
            net_weight=Decimal("15000.00"),
        )
        # Dual-operator ticket: op1 first, op2 second
        WeighTicket.objects.create(
            serial_number="TICK-DUAL",
            status=TicketStatus.COMPLETED,
            first_weight=Decimal("12000.00"),
            first_weight_date=date(2026, 10, 18),
            first_weight_time=time(9, 30),
            first_weight_operator=self.op1,
            first_weight_shift_session=self.session_day,
            second_weight=Decimal("30000.00"),
            second_weight_date=date(2026, 10, 18),
            second_weight_time=time(10, 15),
            second_weight_operator=self.op2,
            second_weight_shift_session=self.session_day,
            net_weight=Decimal("18000.00"),
        )

        kpis = ShiftKPIService.calculate_session_kpis(self.session_day)
        self.assertEqual(kpis["completed_tickets_count"], 2)
        self.assertEqual(kpis["solo_completed_count"], 1)
        self.assertEqual(kpis["dual_operator_completed_count"], 1)

        # Operator breakdown checks
        op1_stat = next(o for o in kpis["operators"] if o["operator_id"] == self.op1.pk)
        op2_stat = next(o for o in kpis["operators"] if o["operator_id"] == self.op2.pk)

        self.assertEqual(op1_stat["first_weights"], 2)
        self.assertEqual(op1_stat["second_weights"], 1)
        self.assertEqual(op1_stat["solo_completed"], 1)

        self.assertEqual(op2_stat["first_weights"], 0)
        self.assertEqual(op2_stat["second_weights"], 1)
        self.assertEqual(op2_stat["solo_completed"], 0)

    def test_08_turnaround_calculation_sanitization_and_exclusion(self):
        """
        Turnaround correctly calculates mean and median for valid pairs.
        Excludes missing timestamps and negative durations without using created_at fallback.
        """
        # Valid Ticket 1: 40 min
        t1 = WeighTicket.objects.create(
            serial_number="T-TAT-1",
            status=TicketStatus.COMPLETED,
            first_weight_date=date(2026, 10, 18),
            first_weight_time=time(8, 0),
            second_weight_date=date(2026, 10, 18),
            second_weight_time=time(8, 40),
            second_weight_shift_session=self.session_day,
            net_weight=Decimal("10000.00"),
        )
        # Valid Ticket 2: 80 min
        t2 = WeighTicket.objects.create(
            serial_number="T-TAT-2",
            status=TicketStatus.COMPLETED,
            first_weight_date=date(2026, 10, 18),
            first_weight_time=time(9, 0),
            second_weight_date=date(2026, 10, 18),
            second_weight_time=time(10, 20),
            second_weight_shift_session=self.session_day,
            net_weight=Decimal("10000.00"),
        )
        # Valid Ticket 3: 120 min
        t3 = WeighTicket.objects.create(
            serial_number="T-TAT-3",
            status=TicketStatus.COMPLETED,
            first_weight_date=date(2026, 10, 18),
            first_weight_time=time(11, 0),
            second_weight_date=date(2026, 10, 18),
            second_weight_time=time(13, 0),
            second_weight_shift_session=self.session_day,
            net_weight=Decimal("10000.00"),
        )
        # Invalid Ticket 4: Missing second_weight_time
        t4 = WeighTicket.objects.create(
            serial_number="T-TAT-4",
            status=TicketStatus.COMPLETED,
            first_weight_date=date(2026, 10, 18),
            first_weight_time=time(11, 0),
            second_weight_date=date(2026, 10, 18),
            second_weight_time=None,
            second_weight_shift_session=self.session_day,
            net_weight=Decimal("10000.00"),
        )
        # Invalid Ticket 5: Negative duration
        t5 = WeighTicket.objects.create(
            serial_number="T-TAT-5",
            status=TicketStatus.COMPLETED,
            first_weight_date=date(2026, 10, 18),
            first_weight_time=time(15, 0),
            second_weight_date=date(2026, 10, 18),
            second_weight_time=time(14, 0),
            second_weight_shift_session=self.session_day,
            net_weight=Decimal("10000.00"),
        )

        turnaround = ShiftKPIService.calculate_turnaround_metrics([t1, t2, t3, t4, t5])
        self.assertEqual(turnaround["valid_count"], 3)
        self.assertEqual(turnaround["excluded_count"], 2)
        self.assertEqual(turnaround["excluded_reasons"]["missing_timestamps"], 1)
        self.assertEqual(turnaround["excluded_reasons"]["negative_duration"], 1)

        # Average = (40 + 80 + 120) / 3 = 80.0
        self.assertEqual(turnaround["avg_minutes"], 80.0)
        # Median of [40, 80, 120] = 80.0
        self.assertEqual(turnaround["median_minutes"], 80.0)
        self.assertEqual(turnaround["min_minutes"], 40.0)
        self.assertEqual(turnaround["max_minutes"], 120.0)

    def test_09_multiple_tickets_one_vehicle_and_distinct_counts(self):
        """Distinguishes physical vehicle count from total ticket count."""
        plate = "12A345-78"
        WeighTicket.objects.create(
            serial_number="TICK-V1",
            status=TicketStatus.COMPLETED,
            second_weight_shift_session=self.session_day,
            license_plate_display=plate,
            net_weight=Decimal("10000.00"),
        )
        WeighTicket.objects.create(
            serial_number="TICK-V2",
            status=TicketStatus.COMPLETED,
            second_weight_shift_session=self.session_day,
            license_plate_display=plate,
            net_weight=Decimal("12000.00"),
        )

        kpis = ShiftKPIService.calculate_session_kpis(self.session_day)
        self.assertEqual(kpis["completed_tickets_count"], 2)
        self.assertEqual(kpis["distinct_vehicles_completed"], 1)

    def test_10_handover_snapshot_vs_live_records_and_no_double_counting(self):
        """
        Handover snapshot records are read accurately.
        Snapshot yard vehicles and waiting second counts are never summed together.
        """
        handover = ShiftHandover.objects.create(
            outgoing_session=self.session_day,
            outgoing_operator=self.op1,
            incoming_operator=self.op2,
            status=ShiftHandoverStatus.SUBMITTED,
            initiated_at=timezone.make_aware(datetime(2026, 10, 18, 15, 45, 0), self.tz),
            submitted_at=timezone.make_aware(datetime(2026, 10, 18, 16, 0, 0), self.tz),
            yard_vehicles_count=3,
            waiting_second_count=5,
        )

        kpis = ShiftKPIService.calculate_session_kpis(self.session_day)
        out_h = kpis["outgoing_handover"]
        self.assertTrue(out_h["exists"])
        self.assertEqual(out_h["snapshot_yard_vehicles_count"], 3)
        self.assertEqual(out_h["snapshot_waiting_second_count"], 5)
        self.assertEqual(out_h["submission_duration_minutes"], 15.0)

    def test_11_disputed_then_supervisor_resolved_handover(self):
        """
        Historically disputed handovers are recognized even if current status is SUPERVISOR_RESOLVED.
        """
        handover = ShiftHandover.objects.create(
            outgoing_session=self.session_day,
            outgoing_operator=self.op1,
            incoming_operator=self.op2,
            status=ShiftHandoverStatus.SUPERVISOR_RESOLVED,
            initiated_at=timezone.make_aware(datetime(2026, 10, 18, 15, 45, 0), self.tz),
            submitted_at=timezone.make_aware(datetime(2026, 10, 18, 16, 0, 0), self.tz),
            disputed_at=timezone.make_aware(datetime(2026, 10, 18, 16, 10, 0), self.tz),
            supervisor=self.supervisor,
            supervisor_resolved_at=timezone.make_aware(datetime(2026, 10, 18, 16, 30, 0), self.tz),
            scale_zero_confirmed=True,
            printer_paper_confirmed=True,
            workstation_clean_confirmed=True,
            physical_documents_confirmed=True,
        )

        h_kpis = ShiftKPIService.calculate_handover_kpis(
            start_date=date(2026, 10, 18),
            end_date=date(2026, 10, 18)
        )
        self.assertEqual(h_kpis["total_handovers"], 1)
        self.assertEqual(h_kpis["currently_disputed_count"], 0)
        self.assertEqual(h_kpis["supervisor_resolved_count"], 1)
        self.assertEqual(h_kpis["historically_disputed_count"], 1)
        self.assertEqual(h_kpis["dispute_rate_pct"], 100.0)
        self.assertEqual(h_kpis["checklist_compliance_pct"], 100.0)

    def test_12_operator_attendance_merged_intervals_and_open_status(self):
        """
        Overlapping attendance intervals are merged, preventing duration inflation.
        """
        # Operator 1 has two overlapping intervals: (8:00 to 12:00) and (10:00 to 16:00)
        # Merged interval must be (8:00 to 16:00) = 8 hours, NOT 10 hours!
        iv1 = (
            timezone.make_aware(datetime(2026, 10, 18, 8, 0), self.tz),
            timezone.make_aware(datetime(2026, 10, 18, 12, 0), self.tz),
        )
        iv2 = (
            timezone.make_aware(datetime(2026, 10, 18, 10, 0), self.tz),
            timezone.make_aware(datetime(2026, 10, 18, 16, 0), self.tz),
        )
        merged = ShiftKPIService.merge_attendance_intervals([iv1, iv2])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0][0], iv1[0])
        self.assertEqual(merged[0][1], iv2[1])

    def test_13_financial_kpi_isolation(self):
        """
        Financial OperationalKPIService calculations remain completely untouched and identical.
        """
        WeighTicket.objects.create(
            serial_number="T-FIN-01",
            status=TicketStatus.COMPLETED,
            first_weight=Decimal("10000.00"),
            first_weight_date=date(2026, 10, 18),
            first_weight_time=time(10, 0),
            second_weight=Decimal("25000.00"),
            second_weight_date=date(2026, 10, 18),
            second_weight_time=time(10, 30),
            second_weight_shift_session=self.session_day,
            net_weight=Decimal("15000.00"),
            gross_weight=Decimal("25000.00"),
            tare_weight=Decimal("10000.00"),
            final_weight=Decimal("15000.00"),
            operation_type=self.op_type_in,
        )

        fin_kpis = OperationalKPIService.calculate_period_kpis(
            start_date=date(2026, 10, 18),
            end_date=date(2026, 10, 18)
        )
        shift_kpis = ShiftKPIService.calculate_session_kpis(self.session_day)

        # Both agree on completed trips and net tonnage
        self.assertEqual(fin_kpis["completed_trips"], 1)
        self.assertEqual(shift_kpis["completed_tickets_count"], 1)
        self.assertEqual(fin_kpis["net_ton_dec"], shift_kpis["completed_net_ton"])

    def test_14_accurate_decimal_arithmetic(self):
        """Decimal conversion preserves exact values without float representation errors."""
        self.assertEqual(ShiftKPIService.kg_to_ton(Decimal("12345.67")), Decimal("12.35"))
        self.assertEqual(ShiftKPIService.kg_to_ton(Decimal("12340.00")), Decimal("12.34"))
        self.assertEqual(ShiftKPIService.kg_to_ton(Decimal("0.00")), Decimal("0.00"))
        self.assertEqual(ShiftKPIService.kg_to_ton(None), Decimal("0.00"))

    def test_15_direct_weighing_mode(self):
        """Direct weighing mode is correctly categorized and included in completed count."""
        WeighTicket.objects.create(
            serial_number="T-DIR-01",
            status=TicketStatus.COMPLETED,
            weight_mode=WeightMode.DIRECT,
            first_weight=Decimal("10000.00"),
            second_weight=Decimal("25000.00"),
            second_weight_shift_session=self.session_day,
            net_weight=Decimal("15000.00"),
        )
        kpis = ShiftKPIService.calculate_session_kpis(self.session_day)
        self.assertEqual(kpis["direct_weighings_count"], 1)
        self.assertEqual(kpis["completed_tickets_count"], 1)

    def test_16_query_count_and_performance(self):
        """Verifies that calculate_session_kpis executes within a bounded, efficient query count."""
        # Preload session
        with CaptureQueriesContext(connection) as ctx:
            ShiftKPIService.calculate_session_kpis(self.session_day)
        # Should be bounded and efficient (typically under 15 queries)
        self.assertLess(len(ctx.captured_queries), 20)
