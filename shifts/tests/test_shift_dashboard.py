from datetime import datetime, date, time, timedelta
from decimal import Decimal
import pytz

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.test.utils import CaptureQueriesContext
from django.db import connection

from accounts.models import UserProfile, RoleChoices
from masterdata.models import Product, Party, OperationType
from weighbridge.models import WeighTicket, TicketStatus, WeightMode
from shifts.models import (
    WorkShift, ShiftSession, ShiftSessionStatus,
    ShiftOperatorAssignment, ShiftOperatorRole, ShiftAssignmentStatus,
    ShiftExceptionLog, ShiftHandover, ShiftHandoverStatus,
)
from shifts.kpi_service import ShiftKPIService
from shifts.dashboard_service import ShiftDashboardService, MAX_DASHBOARD_DATE_RANGE_DAYS
from management.kpi_service import OperationalKPIService


class ShiftDashboardComprehensiveTests(TestCase):
    """
    Comprehensive test suite for Phase 4.3.2 Shift Management Dashboard UI & Service.
    Verifies:
    - Authoritative KPI matching ShiftKPIService
    - Strict operator self-service privacy and anti-tampering
    - Supervisor and manager full access
    - Jalali date filtering and range bounding (max 31 days)
    - Overnight shift attribution
    - Empty states and legacy records isolation
    - Handover historical dispute tracking & confidential notes masking
    - Performance and query bounding
    - Financial report decoupling
    """

    @classmethod
    def setUpTestData(cls):
        cls.tz = pytz.timezone("Asia/Tehran")

        # 1. Users & Roles
        cls.admin_user = User.objects.create_superuser(
            username="admin_dash", password="Password123!", email="admin@dash.com"
        )
        cls.admin_user.profile.role = RoleChoices.SYSTEM_ADMIN
        cls.admin_user.profile.save()

        cls.supervisor_user = User.objects.create_user(
            username="sup_dash", password="Password123!", email="sup@dash.com",
            first_name="سرپرست", last_name="باسکول"
        )
        cls.supervisor_user.profile.role = RoleChoices.WEIGHBRIDGE_MANAGER
        cls.supervisor_user.profile.save()

        cls.op1 = User.objects.create_user(
            username="op_dash1", password="Password123!", email="op1@dash.com",
            first_name="احمد", last_name="رضایی"
        )
        cls.op1.profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        cls.op1.profile.personnel_code = "OP-01"
        cls.op1.profile.save()

        cls.op2 = User.objects.create_user(
            username="op_dash2", password="Password123!", email="op2@dash.com",
            first_name="محسن", last_name="کریمی"
        )
        cls.op2.profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        cls.op2.profile.personnel_code = "OP-02"
        cls.op2.profile.save()

        cls.unauth_user = User.objects.create_user(
            username="unauth_dash", password="Password123!", email="unauth@dash.com"
        )
        cls.unauth_user.profile.role = RoleChoices.WAREHOUSE
        cls.unauth_user.profile.save()

        # 2. Masterdata
        cls.product = Product.objects.create(name="شمش فولادی", code="STEEL-INGOT", is_active=True)
        cls.party = Party.objects.create(name="شرکت نورد آریا", is_active=True)
        cls.op_type_in = OperationType.objects.create(name="ورودی خرید", code="IN-01", direction="inbound")
        cls.op_type_out = OperationType.objects.create(name="خروجی فروش", code="OUT-01", direction="outbound")

        # 3. WorkShifts
        cls.shift_day = WorkShift.objects.create(
            name="شیفت صبح",
            code="MORNING",
            start_time=time(7, 0),
            end_time=time(15, 0),
            is_active=True,
            created_by=cls.admin_user,
        )
        cls.shift_night = WorkShift.objects.create(
            name="شیفت شبانه",
            code="NIGHT",
            start_time=time(23, 0),
            end_time=time(7, 0),
            is_active=True,
            created_by=cls.admin_user,
        )

        # 4. Day Session on 2026-10-18 (1405/07/26)
        cls.op_date = date(2026, 10, 18)
        cls.session_day = ShiftSession.objects.create(
            shift=cls.shift_day,
            operational_date=cls.op_date,
            status=ShiftSessionStatus.ACTIVE,
            actual_start=datetime(2026, 10, 18, 7, 0, 0, tzinfo=cls.tz),
            opened_by=cls.op1,
        )

        # Assignments
        ShiftOperatorAssignment.objects.create(
            session=cls.session_day,
            operator=cls.op1,
            role=ShiftOperatorRole.PRIMARY,
            status=ShiftAssignmentStatus.CHECKED_IN,
            check_in_time=datetime(2026, 10, 18, 7, 0, 0, tzinfo=cls.tz),
        )
        ShiftOperatorAssignment.objects.create(
            session=cls.session_day,
            operator=cls.op2,
            role=ShiftOperatorRole.ASSISTANT,
            is_substitution=True,
            substituted_operator=cls.op1,
            authorized_by=cls.supervisor_user,
            substitution_reason="مرخصی ساعتی اپراتور اول",
            status=ShiftAssignmentStatus.CHECKED_IN,
            check_in_time=datetime(2026, 10, 18, 8, 0, 0, tzinfo=cls.tz),
        )

        # Completed ticket by op1
        cls.ticket_completed = WeighTicket.objects.create(
            serial_number="TICK-DASH-01",
            status=TicketStatus.COMPLETED,
            first_weight=Decimal("15000.00"),
            first_weight_date=cls.op_date,
            first_weight_time=time(7, 30),
            first_weight_operator=cls.op1,
            first_weight_shift_session=cls.session_day,
            second_weight=Decimal("35000.00"),
            second_weight_date=cls.op_date,
            second_weight_time=time(8, 15),
            second_weight_operator=cls.op1,
            second_weight_shift_session=cls.session_day,
            net_weight=Decimal("20000.00"),
            gross_weight=Decimal("35000.00"),
            tare_weight=Decimal("15000.00"),
            final_weight=Decimal("20000.00"),
            operation_type=cls.op_type_in,
            license_plate_display="12A345-78",
            product=cls.product,
            party=cls.party,
        )

        # Open ticket (waiting second) in yard
        cls.ticket_open = WeighTicket.objects.create(
            serial_number="TICK-DASH-02",
            status=TicketStatus.WAITING_SECOND,
            first_weight=Decimal("12000.00"),
            first_weight_date=cls.op_date,
            first_weight_time=time(8, 30),
            first_weight_operator=cls.op2,
            first_weight_shift_session=cls.session_day,
            license_plate_display="34B678-99",
            product=cls.product,
            party=cls.party,
        )

        # Handover from session
        cls.handover = ShiftHandover.objects.create(
            outgoing_session=cls.session_day,
            outgoing_operator=cls.op1,
            incoming_operator=cls.op2,
            status=ShiftHandoverStatus.DISPUTED,
            initiated_at=datetime(2026, 10, 18, 14, 50, tzinfo=cls.tz),
            submitted_at=datetime(2026, 10, 18, 14, 55, tzinfo=cls.tz),
            disputed_at=datetime(2026, 10, 18, 15, 0, tzinfo=cls.tz),
            dispute_reason="مغایرت در نظافت کیوسک و اختلاف وزن باسکول ۲",
            yard_vehicles_count=1,
            waiting_second_count=1,
        )

    def setUp(self):
        self.client = Client()

    def test_01_dashboard_access_superuser_and_manager(self):
        """Superusers and Weighbridge Managers access the dashboard successfully."""
        self.client.force_login(self.admin_user)
        res_admin = self.client.get(reverse("shifts:dashboard"))
        self.assertEqual(res_admin.status_code, 200)
        self.assertContains(res_admin, "داشبورد عملکرد شیفت و اپراتورها")

        self.client.force_login(self.supervisor_user)
        res_sup = self.client.get(reverse("shifts:dashboard"))
        self.assertEqual(res_sup.status_code, 200)
        self.assertContains(res_sup, "داشبورد عملکرد شیفت و اپراتورها")

    def test_02_dashboard_access_operator_allowed(self):
        """Weighbridge Operators can access the dashboard."""
        self.client.force_login(self.op1)
        res_op = self.client.get(reverse("shifts:dashboard"))
        self.assertEqual(res_op.status_code, 200)
        self.assertContains(res_op, "داشبورد عملکرد شیفت و اپراتورها")

    def test_03_dashboard_access_unauthorized_user_redirected(self):
        """Users without shift permissions are redirected away from dashboard."""
        self.client.force_login(self.unauth_user)
        res = self.client.get(reverse("shifts:dashboard"))
        self.assertEqual(res.status_code, 302)

    def test_04_operator_tampering_operator_parameter_denied(self):
        """
        An ordinary operator tampering with ?operator=<other_id> is blocked with PermissionDenied (HTTP 403).
        """
        self.client.force_login(self.op1)
        # Attempt to access op2's performance statistics
        res = self.client.get(reverse("shifts:dashboard"), {"operator": str(self.op2.id)})
        self.assertEqual(res.status_code, 403)

    def test_05_operator_self_service_only_sees_own_performance(self):
        """
        An ordinary operator viewing the dashboard sees only their own metrics in the operator table.
        """
        self.client.force_login(self.op1)
        res = self.client.get(reverse("shifts:dashboard"), {
            "start_date": "1405/07/26",
            "end_date": "1405/07/26"
        })
        self.assertEqual(res.status_code, 200)
        operators = res.context["operators"]
        self.assertEqual(len(operators), 1)
        self.assertEqual(operators[0]["operator_id"], self.op1.id)
        self.assertEqual(operators[0]["username"], self.op1.username)

    def test_06_supervisor_can_view_all_operators(self):
        """
        Supervisors and managers can view all active operators in the operator activity table.
        """
        self.client.force_login(self.supervisor_user)
        res = self.client.get(reverse("shifts:dashboard"), {
            "start_date": "1405/07/26",
            "end_date": "1405/07/26"
        })
        self.assertEqual(res.status_code, 200)
        operators = res.context["operators"]
        # Both op1 and op2 worked in the session
        self.assertGreaterEqual(len(operators), 2)
        op_ids = [o["operator_id"] for o in operators]
        self.assertIn(self.op1.id, op_ids)
        self.assertIn(self.op2.id, op_ids)

    def test_07_kpi_values_match_shift_kpi_service_exactly(self):
        """
        Dashboard summary cards match ShiftKPIService calculation engine exactly.
        """
        expected_kpis = ShiftKPIService.calculate_period_shift_kpis(
            start_date=self.op_date, end_date=self.op_date
        )

        self.client.force_login(self.supervisor_user)
        res = self.client.get(reverse("shifts:dashboard"), {
            "start_date": "1405/07/26",
            "end_date": "1405/07/26"
        })
        summary = res.context["summary"]

        self.assertEqual(summary["first_weighings_count"], expected_kpis["summary"]["first_weighings_count"])
        self.assertEqual(summary["second_weighings_count"], expected_kpis["summary"]["second_weighings_count"])
        self.assertEqual(summary["completed_tickets_count"], expected_kpis["summary"]["completed_tickets_count"])
        self.assertEqual(summary["completed_net_kg"], expected_kpis["summary"]["completed_net_kg"])
        self.assertEqual(summary["completed_net_ton"], expected_kpis["summary"]["completed_net_ton"])
        self.assertEqual(summary["completed_gross_ton"], expected_kpis["summary"]["completed_gross_ton"])

    def test_08_jalali_filter_parsing(self):
        """Jalali date filters are properly parsed into local Gregorian operational dates."""
        self.client.force_login(self.supervisor_user)
        # 1405/07/26 -> 2026-10-18
        res = self.client.get(reverse("shifts:dashboard"), {
            "start_date": "1405/07/26",
            "end_date": "1405/07/26"
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["filters"]["start_date"], self.op_date)
        self.assertEqual(res.context["filters"]["end_date"], self.op_date)
        self.assertEqual(len(res.context["sessions"]), 1)

    def test_09_overnight_shift_attribution(self):
        """Overnight shift crossing midnight is attributed to session's operational date."""
        session_night = ShiftSession.objects.create(
            shift=self.shift_night,
            operational_date=self.op_date,
            status=ShiftSessionStatus.ACTIVE,
            actual_start=datetime(2026, 10, 18, 23, 0, 0, tzinfo=self.tz),
            opened_by=self.op1,
        )
        # Weighing event in early morning of 2026-10-19
        WeighTicket.objects.create(
            serial_number="TICK-NIGHT-01",
            status=TicketStatus.COMPLETED,
            first_weight=Decimal("14000.00"),
            first_weight_date=date(2026, 10, 19),
            first_weight_time=time(1, 30),
            first_weight_operator=self.op1,
            first_weight_shift_session=session_night,
            second_weight=Decimal("34000.00"),
            second_weight_date=date(2026, 10, 19),
            second_weight_time=time(2, 15),
            second_weight_operator=self.op1,
            second_weight_shift_session=session_night,
            net_weight=Decimal("20000.00"),
            operation_type=self.op_type_in,
            license_plate_display="55C123-44",
        )

        self.client.force_login(self.supervisor_user)
        res = self.client.get(reverse("shifts:dashboard"), {
            "start_date": "1405/07/26",
            "end_date": "1405/07/26"
        })
        sessions = res.context["sessions"]
        session_ids = [s["session_id"] for s in sessions]
        self.assertIn(session_night.pk, session_ids)

    def test_10_large_date_range_validation(self):
        """Date range exceeding 31 days is rejected with a clear validation error."""
        self.client.force_login(self.supervisor_user)
        # Range of 60 days
        res = self.client.get(reverse("shifts:dashboard"), {
            "start_date": "2026-09-01",
            "end_date": "2026-11-01"
        })
        self.assertEqual(res.status_code, 200)
        self.assertIsNotNone(res.context.get("error"))
        self.assertIn("حداکثر بازه زمانی", res.context["error"])

    def test_11_inverted_date_range_handling(self):
        """Inverted date range (start > end) is safely swapped without crashing."""
        self.client.force_login(self.supervisor_user)
        res = self.client.get(reverse("shifts:dashboard"), {
            "start_date": "2026-10-20",
            "end_date": "2026-10-18"
        })
        self.assertEqual(res.status_code, 200)
        self.assertLessEqual(res.context["filters"]["start_date"], res.context["filters"]["end_date"])

    def test_12_no_data_empty_state(self):
        """Querying a date without shifts displays empty state gracefully."""
        self.client.force_login(self.supervisor_user)
        res = self.client.get(reverse("shifts:dashboard"), {
            "start_date": "2026-01-01",
            "end_date": "2026-01-01"
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["total_sessions_count"], 0)
        self.assertContains(res, "هیچ جلسه شیفتی در این بازه زمانی یافت نشد")

    def test_13_unattributed_legacy_records_isolated(self):
        """Legacy tickets without shift sessions are cleanly displayed in unattributed section."""
        WeighTicket.objects.create(
            serial_number="TICK-LEGACY-DASH",
            status=TicketStatus.COMPLETED,
            first_weight=Decimal("10000.00"),
            first_weight_date=self.op_date,
            first_weight_time=time(11, 0),
            second_weight=Decimal("30000.00"),
            second_weight_date=self.op_date,
            second_weight_time=time(11, 45),
            net_weight=Decimal("20000.00"),
            first_weight_shift_session=None,
            second_weight_shift_session=None,
        )

        self.client.force_login(self.supervisor_user)
        res = self.client.get(reverse("shifts:dashboard"), {
            "start_date": "1405/07/26",
            "end_date": "1405/07/26"
        })
        unattr = res.context["unattributed_legacy"]
        self.assertGreaterEqual(unattr["completed_tickets_count"], 1)
        self.assertGreaterEqual(unattr["completed_net_ton"], Decimal("20.00"))

    def test_14_handover_historical_dispute_indicator(self):
        """Historically disputed handovers are accurately marked in handover overview."""
        self.client.force_login(self.supervisor_user)
        res = self.client.get(reverse("shifts:dashboard"), {
            "start_date": "1405/07/26",
            "end_date": "1405/07/26"
        })
        handovers = res.context["handovers_list"]
        self.assertTrue(any(h["is_historically_disputed"] for h in handovers))

    def test_15_confidential_supervisor_notes_hidden_from_operator(self):
        """Confidential supervisor notes and dispute details are masked for regular operators."""
        # Check supervisor sees dispute reason
        self.client.force_login(self.supervisor_user)
        res_sup = self.client.get(reverse("shifts:dashboard"), {
            "start_date": "1405/07/26",
            "end_date": "1405/07/26"
        })
        sup_handovers = res_sup.context["handovers_list"]
        self.assertTrue(any(h["dispute_reason"] for h in sup_handovers))

        # Check operator does not see dispute reason
        self.client.force_login(self.op1)
        res_op = self.client.get(reverse("shifts:dashboard"), {
            "start_date": "1405/07/26",
            "end_date": "1405/07/26"
        })
        op_handovers = res_op.context["handovers_list"]
        for h in op_handovers:
            self.assertEqual(h["dispute_reason"], "")
            self.assertEqual(h["supervisor_notes"], "")

    def test_16_query_count_and_performance(self):
        """Dashboard renders efficiently within a bounded query count without N+1 loops."""
        self.client.force_login(self.supervisor_user)
        with CaptureQueriesContext(connection) as ctx:
            res = self.client.get(reverse("shifts:dashboard"), {
                "start_date": "1405/07/26",
                "end_date": "1405/07/26"
            })
            self.assertEqual(res.status_code, 200)

        # Ensure queries are bounded (less than 50 queries total for complete multi-table dashboard render)
        self.assertLessEqual(len(ctx), 50)

    def test_17_no_changes_to_financial_reports(self):
        """Financial OperationalKPIService calculations remain completely untouched."""
        fin_kpis = OperationalKPIService.calculate_period_kpis(
            start_date=self.op_date,
            end_date=self.op_date,
        )
        self.assertIsNotNone(fin_kpis)
        self.assertEqual(fin_kpis["completed_trips"], 1)
        self.assertEqual(fin_kpis["net_ton_dec"], Decimal("20.00"))
