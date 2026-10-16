from decimal import Decimal
from datetime import datetime, date, time, timedelta
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.utils import timezone
from django.urls import reverse
from django.db import connection, reset_queries

from accounts.models import UserProfile
from masterdata.models import Product, Party, Vehicle, Driver, OperationType
from weighbridge.models import WeighTicket, TicketStatus
from monitoring.models import (
    DiscrepancyApproval, ApprovalStatus, AlertSeverity, AlertType, MonitoringRuleConfig
)
from management.services import ManagementDashboardService, ManagementReportService
from management.kpi_service import OperationalKPIService
from management.views import dashboard_view


class Phase322OperationalVisibilityTestCase(TestCase):
    def setUp(self):
        # Create users with specific roles
        self.admin_user = User.objects.create_superuser("admin_super", "admin@bascol.local", "pass123")
        self.admin_user.profile.role = "super_admin"
        self.admin_user.profile.save()

        self.ceo_user = User.objects.create_user("ceo_user", "ceo@bascol.local", "pass123")
        self.ceo_user.profile.role = "ceo"
        self.ceo_user.profile.save()

        self.report_manager = User.objects.create_user("rep_mgr", "rep@bascol.local", "pass123")
        self.report_manager.profile.role = "report_manager"
        self.report_manager.profile.save()

        self.op1 = User.objects.create_user("operator_ali", "ali@bascol.local", "pass123", first_name="Ali", last_name="Rad")
        self.op1.profile.role = "weighbridge_operator"
        self.op1.profile.save()

        self.op2 = User.objects.create_user("operator_reza", "reza@bascol.local", "pass123", first_name="Reza", last_name="Mirk")
        self.op2.profile.role = "weighbridge_operator"
        self.op2.profile.save()

        # Master Data
        self.product = Product.objects.create(name="آهن اسفنجی", code="FE-01", is_active=True)
        self.party = Party.objects.create(name="فولاد کاوه", code="KAV-01", is_active=True)
        self.driver = Driver.objects.create(full_name="حمید مرادی", national_code="0011223344", is_active=True)
        self.op_type = OperationType.objects.create(name="خرید", code="PUR", direction="inbound", is_active=True)

        self.today = timezone.localdate()

    def test_approval_count_accuracy_and_severity_breakdown(self):
        """
        Verify pending approval count, oldest request age calculation,
        and severity breakdown from DiscrepancyApproval.
        """
        t1 = WeighTicket.objects.create(
            serial_number=9001,
            status=TicketStatus.WAITING_SECOND,
            product=self.product,
            party=self.party,
            driver=self.driver,
            operation_type=self.op_type,
            license_plate_display="12B345-67",
            first_weight=Decimal("15000.00"),
            first_weight_date=self.today,
            first_weight_time=time(8, 0),
            first_weight_operator=self.op1,
        )
        t2 = WeighTicket.objects.create(
            serial_number=9002,
            status=TicketStatus.WAITING_SECOND,
            product=self.product,
            party=self.party,
            driver=self.driver,
            operation_type=self.op_type,
            license_plate_display="22B345-67",
            first_weight=Decimal("16000.00"),
            first_weight_date=self.today,
            first_weight_time=time(8, 30),
            first_weight_operator=self.op1,
        )

        # 1 Pending Critical approval created 45 mins ago
        app1 = DiscrepancyApproval.objects.create(
            ticket=t1,
            discrepancy_type=AlertType.WEIGHT_DISCREPANCY,
            severity=AlertSeverity.CRITICAL,
            status=ApprovalStatus.PENDING,
            requested_by=self.op1,
            request_reason="Critical discrepancy tolerance exceeded",
        )
        DiscrepancyApproval.objects.filter(id=app1.id).update(
            created_at=timezone.now() - timedelta(minutes=45)
        )

        # 1 Pending High approval created 10 mins ago
        app2 = DiscrepancyApproval.objects.create(
            ticket=t2,
            discrepancy_type=AlertType.WEIGHT_DISCREPANCY,
            severity=AlertSeverity.HIGH,
            status=ApprovalStatus.PENDING,
            requested_by=self.op1,
            request_reason="High discrepancy tolerance exceeded",
        )
        DiscrepancyApproval.objects.filter(id=app2.id).update(
            created_at=timezone.now() - timedelta(minutes=10)
        )

        # 1 Approved request (should NOT be counted in pending)
        t3 = WeighTicket.objects.create(
            serial_number=9003,
            status=TicketStatus.COMPLETED,
            product=self.product,
            party=self.party,
            driver=self.driver,
            operation_type=self.op_type,
            license_plate_display="33B345-67",
            first_weight=Decimal("17000.00"),
            first_weight_date=self.today,
            first_weight_time=time(9, 0),
            first_weight_operator=self.op1,
        )
        DiscrepancyApproval.objects.create(
            ticket=t3,
            discrepancy_type=AlertType.WEIGHT_DISCREPANCY,
            severity=AlertSeverity.HIGH,
            status=ApprovalStatus.APPROVED,
            requested_by=self.op1,
            request_reason="Already approved",
            reviewed_by=self.admin_user,
            reviewed_at=timezone.now(),
        )

        summary = ManagementDashboardService.get_pending_approvals_summary(self.ceo_user)
        self.assertTrue(summary["is_authorized"])
        self.assertEqual(summary["pending_count"], 2)
        self.assertIn("دقیقه", summary["oldest_age_str"])
        self.assertGreaterEqual(summary["oldest_age_minutes"], 44)

        severities = {s["severity"]: s["count"] for s in summary["severity_breakdown"]}
        self.assertEqual(severities.get(AlertSeverity.CRITICAL), 1)
        self.assertEqual(severities.get(AlertSeverity.HIGH), 1)
        self.assertEqual(summary["approval_url"], reverse("monitoring:approval_list"))

    def test_approval_permission_enforcement(self):
        """
        Verify that unauthorized roles (like report_manager or anonymous)
        do not receive approval counts or approval URLs.
        """
        summary_unauth = ManagementDashboardService.get_pending_approvals_summary(self.report_manager)
        self.assertFalse(summary_unauth["is_authorized"])
        self.assertEqual(summary_unauth["pending_count"], 0)
        self.assertIsNone(summary_unauth["oldest_age_str"])
        self.assertIsNone(summary_unauth["approval_url"])

        summary_auth = ManagementDashboardService.get_pending_approvals_summary(self.admin_user)
        self.assertTrue(summary_auth["is_authorized"])
        self.assertIsNotNone(summary_auth["approval_url"])

    def test_yard_kpi_consistency_and_configurable_thresholds(self):
        """
        Verify yard dwell metrics with configurable MonitoringRuleConfig thresholds,
        and ensure completed or cancelled tickets are strictly excluded.
        """
        # Configure thresholds: Warning at 40 min, Critical at 100 min
        rule, _ = MonitoringRuleConfig.objects.get_or_create(
            rule_type=AlertType.LONG_WAITING_TIME,
            defaults={"name_fa": "توقف طولانی", "enabled": True}
        )
        rule.warning_threshold = Decimal("40.00")
        rule.critical_threshold = Decimal("100.00")
        rule.save()

        now = timezone.now()

        # Ticket 1: In Yard, created 15 min ago (Normal)
        t1 = WeighTicket.objects.create(
            serial_number=9101,
            status=TicketStatus.WAITING_SECOND,
            product=self.product,
            license_plate_display="11A111-11",
            first_weight=Decimal("10000.00"),
            first_weight_date=self.today,
            first_weight_time=time(10, 0),
            first_weight_operator=self.op1,
        )
        WeighTicket.objects.filter(id=t1.id).update(created_at=now - timedelta(minutes=15))

        # Ticket 2: In Yard, created 50 min ago (Warning: between 40 and 100)
        t2 = WeighTicket.objects.create(
            serial_number=9102,
            status=TicketStatus.FIRST_REGISTERED,
            product=self.product,
            license_plate_display="22A222-22",
            first_weight=Decimal("12000.00"),
            first_weight_date=self.today,
            first_weight_time=time(9, 30),
            first_weight_operator=self.op1,
        )
        WeighTicket.objects.filter(id=t2.id).update(created_at=now - timedelta(minutes=50))

        # Ticket 3: In Yard, created 130 min ago (Overdue: > 100)
        t3 = WeighTicket.objects.create(
            serial_number=9103,
            status=TicketStatus.WAITING_SECOND,
            product=self.product,
            license_plate_display="33A333-33",
            first_weight=Decimal("14000.00"),
            first_weight_date=self.today,
            first_weight_time=time(8, 0),
            first_weight_operator=self.op1,
        )
        WeighTicket.objects.filter(id=t3.id).update(created_at=now - timedelta(minutes=130))

        # Ticket 4: Completed (MUST NOT be counted in yard)
        t4 = WeighTicket.objects.create(
            serial_number=9104,
            status=TicketStatus.COMPLETED,
            product=self.product,
            license_plate_display="44A444-44",
            first_weight=Decimal("15000.00"),
            second_weight=Decimal("5000.00"),
            net_weight=Decimal("10000.00"),
            final_weight=Decimal("10000.00"),
            first_weight_date=self.today,
            second_weight_date=self.today,
            first_weight_operator=self.op1,
            second_weight_operator=self.op1,
        )
        WeighTicket.objects.filter(id=t4.id).update(created_at=now - timedelta(minutes=180))

        # Ticket 5: Cancelled (MUST NOT be counted in yard)
        t5 = WeighTicket.objects.create(
            serial_number=9105,
            status=TicketStatus.CANCELLED,
            product=self.product,
            license_plate_display="55A555-55",
            first_weight=Decimal("10000.00"),
            first_weight_date=self.today,
            first_weight_operator=self.op1,
        )
        WeighTicket.objects.filter(id=t5.id).update(created_at=now - timedelta(minutes=200))

        yard = ManagementDashboardService.get_yard_operational_summary()

        self.assertEqual(yard["total_in_yard"], 3)
        self.assertEqual(yard["normal_count"], 1)
        self.assertEqual(yard["warning_count"], 1)
        self.assertEqual(yard["overdue_count"], 1)
        self.assertEqual(yard["warning_threshold_mins"], 40)
        self.assertEqual(yard["critical_threshold_mins"], 100)
        self.assertGreaterEqual(yard["longest_dwell_minutes"], 129)
        self.assertIn("ساعت", yard["longest_dwell_str"])
        self.assertEqual(yard["yard_url"], reverse("weighbridge:trucks_in_yard"))

    def test_turnaround_and_missing_timestamp_exclusions(self):
        """
        Verify average and median turnaround time calculations and ensure records
        with missing timestamps are cleanly excluded and counted.
        """
        base_date = self.today

        # Ticket 1: 30 minutes duration (08:00 to 08:30)
        WeighTicket.objects.create(
            serial_number=9201,
            status=TicketStatus.COMPLETED,
            product=self.product,
            license_plate_display="51A100-11",
            first_weight=Decimal("20000.00"),
            second_weight=Decimal("8000.00"),
            net_weight=Decimal("12000.00"),
            final_weight=Decimal("12000.00"),
            first_weight_date=base_date,
            first_weight_time=time(8, 0),
            second_weight_date=base_date,
            second_weight_time=time(8, 30),
            first_weight_operator=self.op1,
            second_weight_operator=self.op1,
        )

        # Ticket 2: 90 minutes duration (09:00 to 10:30)
        WeighTicket.objects.create(
            serial_number=9202,
            status=TicketStatus.COMPLETED,
            product=self.product,
            license_plate_display="52A100-11",
            first_weight=Decimal("22000.00"),
            second_weight=Decimal("7000.00"),
            net_weight=Decimal("15000.00"),
            final_weight=Decimal("15000.00"),
            first_weight_date=base_date,
            first_weight_time=time(9, 0),
            second_weight_date=base_date,
            second_weight_time=time(10, 30),
            first_weight_operator=self.op1,
            second_weight_operator=self.op2,
        )

        # Ticket 3: Missing second_weight_time (Incomplete)
        WeighTicket.objects.create(
            serial_number=9203,
            status=TicketStatus.COMPLETED,
            product=self.product,
            license_plate_display="53A100-11",
            first_weight=Decimal("18000.00"),
            second_weight=Decimal("6000.00"),
            net_weight=Decimal("12000.00"),
            final_weight=Decimal("12000.00"),
            first_weight_date=base_date,
            first_weight_time=time(11, 0),
            second_weight_date=base_date,
            second_weight_time=None,
            first_weight_operator=self.op1,
            second_weight_operator=self.op1,
        )

        qs = WeighTicket.objects.all()
        turnaround = ManagementDashboardService.get_turnaround_dwell_analytics(qs)

        self.assertEqual(turnaround["completed_trips_count"], 3)
        self.assertEqual(turnaround["valid_trips_count"], 2)
        self.assertEqual(turnaround["excluded_missing_timestamps_count"], 1)

        # Average = (30 + 90) / 2 = 60.0 mins
        self.assertEqual(turnaround["avg_turnaround_minutes"], 60.0)
        # Median = (30 + 90) / 2 = 60.0 mins
        self.assertEqual(turnaround["median_turnaround_minutes"], 60.0)
        self.assertEqual(turnaround["min_turnaround_minutes"], 30.0)
        self.assertEqual(turnaround["max_turnaround_minutes"], 90.0)

        # Hourly throughput: 1 at 08:30 (hour 8) and 1 at 10:30 (hour 10)
        self.assertEqual(turnaround["hourly_throughput"][8], 1)
        self.assertEqual(turnaround["hourly_throughput"][10], 1)

    def test_operator_attribution_accuracy(self):
        """
        Verify that first weights are attributed to first_weight_operator,
        second weights to second_weight_operator, and total tasks are distinguished
        from completed ticket counts.
        """
        base_date = self.today

        # Ticket 1: Ali does first weight, Ali does second weight (Solo Completed)
        WeighTicket.objects.create(
            serial_number=9301,
            status=TicketStatus.COMPLETED,
            product=self.product,
            license_plate_display="71A100-11",
            first_weight=Decimal("20000.00"),
            second_weight=Decimal("8000.00"),
            net_weight=Decimal("12000.00"),
            final_weight=Decimal("12000.00"),
            first_weight_date=base_date,
            first_weight_time=time(8, 0),
            second_weight_date=base_date,
            second_weight_time=time(8, 30),
            first_weight_operator=self.op1,
            second_weight_operator=self.op1,
        )

        # Ticket 2: Ali does first weight, Reza does second weight (Handover)
        WeighTicket.objects.create(
            serial_number=9302,
            status=TicketStatus.COMPLETED,
            product=self.product,
            license_plate_display="72A100-11",
            first_weight=Decimal("22000.00"),
            second_weight=Decimal("7000.00"),
            net_weight=Decimal("15000.00"),
            final_weight=Decimal("15000.00"),
            first_weight_date=base_date,
            first_weight_time=time(9, 0),
            second_weight_date=base_date,
            second_weight_time=time(10, 0),
            first_weight_operator=self.op1,
            second_weight_operator=self.op2,
        )

        # Ticket 3: Reza does first weight, still in yard (waiting second)
        WeighTicket.objects.create(
            serial_number=9303,
            status=TicketStatus.WAITING_SECOND,
            product=self.product,
            license_plate_display="73A100-11",
            first_weight=Decimal("18000.00"),
            first_weight_date=base_date,
            first_weight_time=time(11, 0),
            first_weight_operator=self.op2,
            second_weight_operator=None,
        )

        qs = WeighTicket.objects.all()
        ops_data = ManagementReportService.get_operations_performance(qs)
        ops_by_username = {op["username"]: op for op in ops_data["operators"]}

        ali_perf = ops_by_username[self.op1.username]
        reza_perf = ops_by_username[self.op2.username]

        # Ali: 2 first weights (Ticket 1 & 2), 1 second weight (Ticket 1) -> Total tasks = 3
        self.assertEqual(ali_perf["first_weights"], 2)
        self.assertEqual(ali_perf["second_weights"], 1)
        self.assertEqual(ali_perf["total_tasks"], 3)
        self.assertEqual(ali_perf["completed"], 1)
        self.assertEqual(ali_perf["solo_completed"], 1)

        # Reza: 1 first weight (Ticket 3), 1 second weight (Ticket 2) -> Total tasks = 2
        self.assertEqual(reza_perf["first_weights"], 1)
        self.assertEqual(reza_perf["second_weights"], 1)
        self.assertEqual(reza_perf["total_tasks"], 2)
        self.assertEqual(reza_perf["completed"], 1)
        self.assertEqual(reza_perf["solo_completed"], 0)

    def test_dashboard_view_integration_and_context(self):
        """
        Verify that dashboard_view renders with status 200 and provides all
        required operational visibility components in the context.
        """
        factory = RequestFactory()
        request = factory.get(reverse("management:dashboard") + "?quick_period=today")
        request.user = self.admin_user

        response = dashboard_view(request)
        self.assertEqual(response.status_code, 200)

        ctx = response.context_data if hasattr(response, "context_data") else response.content.decode("utf-8")
        # Check rendered HTML for key operational elements
        self.assertIn("کارتابل مجوزهای مغایرت سرپرست", ctx)
        self.assertIn("وضعیت عملیات و توقف محوطه (Yard)", ctx)
        self.assertIn("زمان چرخه توزین و توقف (Turnaround)", ctx)
        self.assertIn("کامیون حاضر در محوطه", ctx)

    def test_existing_kpi_consistency_unchanged(self):
        """
        Verify that OperationalKPIService calculations remain 100% authoritative
        and unaffected by operational dashboard visibility additions.
        """
        WeighTicket.objects.create(
            serial_number=9401,
            status=TicketStatus.COMPLETED,
            product=self.product,
            license_plate_display="81A100-11",
            first_weight=Decimal("25000.00"),
            second_weight=Decimal("10000.00"),
            net_weight=Decimal("15000.00"),
            final_weight=Decimal("15000.00"),
            first_weight_date=self.today,
            second_weight_date=self.today,
            first_weight_operator=self.op1,
            second_weight_operator=self.op1,
        )

        kpi = OperationalKPIService.calculate_period_kpis(start_date=self.today, end_date=self.today)
        self.assertEqual(kpi["completed_trips"], 1)
        self.assertEqual(kpi["net_ton"], 15.0)
        self.assertEqual(kpi["net_kg"], 15000.0)
        self.assertEqual(kpi["unit"], "ton")
