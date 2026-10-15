from decimal import Decimal
from datetime import date, time, timedelta, datetime
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils import timezone
from django.test.utils import CaptureQueriesContext
from django.db import connection

from accounts.models import UserProfile, RoleChoices
from masterdata.models import Product, Party, Driver, Vehicle, OperationType, Location
from weighbridge.models import WeighTicket, TicketStatus, WeightMode
from management.kpi_service import OperationalKPIService
from core.jalali import get_today_gregorian, format_jalali_date


class KPIConsistencyAndAccuracyTests(TestCase):
    """
    Comprehensive verification suite for Phase 3.2.1:
    - Authoritative WeighTicket KPI accuracy
    - Strict exclusion of cancelled and incomplete tickets from finalized tonnage
    - Correct reporting date semantics (cross-midnight transactions, arrival vs completion)
    - Fallback for legacy missing completion dates without inventing timestamps
    - Standardized units (Decimal kg authoritative, metric tons presentation)
    - Complete synchronization across Operator Dashboard, Management Dashboard, and APIs
    - Zero N+1 queries during 30-day trend generation
    """

    def setUp(self):
        self.client = Client()

        # Users
        self.admin = User.objects.create_superuser(username="admin_kpi", password="password123")
        self.manager = User.objects.create_user(username="mgr_kpi", password="password123")
        self.manager.profile.role = RoleChoices.FACTORY_MANAGER
        self.manager.profile.save()

        self.operator = User.objects.create_user(username="op_kpi", password="password123")
        self.operator.profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        self.operator.profile.save()

        # Masterdata
        self.product_ingot = Product.objects.create(name="شمش فولادی 150", code="ING-150")
        self.product_sponge = Product.objects.create(name="آهن اسفنجی", code="SPN-01")
        self.party_supplier = Party.objects.create(name="تامین فولاد خوزستان", party_type="supplier")
        self.party_customer = Party.objects.create(name="صنایع مفتول کاوه", party_type="customer")
        self.op_inbound = OperationType.objects.create(name="خرید مواد اولیه", direction="inbound")
        self.op_outbound = OperationType.objects.create(name="فروش شمش صادراتی", direction="outbound")
        self.loc_origin = Location.objects.create(name="انبار مرکزی")
        self.loc_dest = Location.objects.create(name="کارخانه شماره ۲")
        self.driver = Driver.objects.create(full_name="رضا مرادی", mobile="09121112233")
        self.vehicle = Vehicle.objects.create(
            plate_part1="55", plate_letter="ب", plate_part2="888", plate_iran="77",
            plate_display="55 ب 888 ایران 77"
        )

        self.today = get_today_gregorian()
        self.yesterday = self.today - timedelta(days=1)

    def test_completed_vs_cancelled_and_incomplete_tickets(self):
        """
        Finalized tonnage must strictly include COMPLETED tickets only.
        Cancelled and open tickets must be excluded from tonnage but visible in operational counts.
        """
        # Ticket 1: Completed Inbound Ticket (25,000 kg net)
        WeighTicket.objects.create(
            serial_number="T-COMPLETED-1",
            status=TicketStatus.COMPLETED,
            weight_mode=WeightMode.EMPTY_FIRST,
            product=self.product_sponge,
            party=self.party_supplier,
            operation_type=self.op_inbound,
            driver=self.driver,
            vehicle=self.vehicle,
            first_weight_date=self.today,
            first_weight_time=time(8, 0),
            second_weight_date=self.today,
            second_weight_time=time(8, 30),
            gross_weight=Decimal("38000.00"),
            tare_weight=Decimal("13000.00"),
            net_weight=Decimal("25000.00"),
            final_weight=Decimal("24800.00"),
            loss_weight=Decimal("200.00"),
            loss_percent=Decimal("0.80"),
        )

        # Ticket 2: Cancelled Ticket with old weights recorded (18,000 kg net)
        WeighTicket.objects.create(
            serial_number="T-CANCELLED-1",
            status=TicketStatus.CANCELLED,
            weight_mode=WeightMode.EMPTY_FIRST,
            product=self.product_sponge,
            party=self.party_supplier,
            operation_type=self.op_inbound,
            driver=self.driver,
            vehicle=self.vehicle,
            first_weight_date=self.today,
            first_weight_time=time(9, 0),
            second_weight_date=self.today,
            second_weight_time=time(9, 15),
            gross_weight=Decimal("31000.00"),
            tare_weight=Decimal("13000.00"),
            net_weight=Decimal("18000.00"),
            final_weight=Decimal("18000.00"),
            cancellation_reason="خطای راننده در ورود به باسکول اشتباه",
        )

        # Ticket 3: Waiting in yard (First weight registered only)
        WeighTicket.objects.create(
            serial_number="T-WAITING-1",
            status=TicketStatus.WAITING_SECOND,
            weight_mode=WeightMode.EMPTY_FIRST,
            product=self.product_ingot,
            party=self.party_customer,
            operation_type=self.op_outbound,
            driver=self.driver,
            vehicle=self.vehicle,
            first_weight_date=self.today,
            first_weight_time=time(10, 0),
            first_weight=Decimal("14000.00"),
            second_weight=None,
            gross_weight=Decimal("0.00"),
            tare_weight=Decimal("14000.00"),
            net_weight=Decimal("0.00"),
            final_weight=Decimal("0.00"),
        )

        kpis = OperationalKPIService.calculate_period_kpis(start_date=self.today, end_date=self.today)

        # Finalized completed tonnage must be exactly 25.00 tons (NOT 25 + 18 = 43 tons!)
        self.assertEqual(kpis["completed_trips"], 1)
        self.assertEqual(kpis["net_kg_dec"], Decimal("25000.00"))
        self.assertEqual(kpis["net_ton_dec"], Decimal("25.00"))
        self.assertEqual(kpis["loss_kg_dec"], Decimal("200.00"))
        self.assertEqual(kpis["final_ton_dec"], Decimal("24.80"))

        # Operational visibility must reflect all three tickets
        self.assertEqual(kpis["trips"], 3)  # 3 total arrivals today
        self.assertEqual(kpis["cancelled_count"], 1)  # 1 cancelled
        self.assertEqual(kpis["waiting_count"], 1)  # 1 waiting in yard

    def test_midnight_spanning_transaction_semantics(self):
        """
        Cross-midnight test:
        Truck arrives on Day 1 (23:30, first_weight_date=yesterday).
        Truck completes second weighing on Day 2 (01:15, second_weight_date=today).

        Authoritative Semantics:
        - Day 1: Arrivals +1, Completed Tonnage = 0.
        - Day 2: Arrivals = 0, Completed Tonnage = +30.00 tons.
        - Period [Day 1, Day 2]: Arrivals = 1, Completed Tonnage = +30.00 tons.
        """
        WeighTicket.objects.create(
            serial_number="T-MIDNIGHT-1",
            status=TicketStatus.COMPLETED,
            weight_mode=WeightMode.EMPTY_FIRST,
            product=self.product_ingot,
            party=self.party_customer,
            operation_type=self.op_outbound,
            driver=self.driver,
            vehicle=self.vehicle,
            first_weight_date=self.yesterday,
            first_weight_time=time(23, 30),
            second_weight_date=self.today,
            second_weight_time=time(1, 15),
            gross_weight=Decimal("44000.00"),
            tare_weight=Decimal("14000.00"),
            net_weight=Decimal("30000.00"),
            final_weight=Decimal("30000.00"),
        )

        # 1. Day 1 (Yesterday) KPIs
        kpi_day1 = OperationalKPIService.calculate_period_kpis(start_date=self.yesterday, end_date=self.yesterday)
        self.assertEqual(kpi_day1["trips"], 1, "Truck must be counted as arrival on Day 1")
        self.assertEqual(kpi_day1["completed_trips"], 0, "Truck was not completed on Day 1")
        self.assertEqual(kpi_day1["net_kg_dec"], Decimal("0.00"), "Tonnage on Day 1 must be 0")
        self.assertEqual(kpi_day1["net_ton_dec"], Decimal("0.00"), "Tonnage on Day 1 must be 0")

        # 2. Day 2 (Today) KPIs
        kpi_day2 = OperationalKPIService.calculate_period_kpis(start_date=self.today, end_date=self.today)
        self.assertEqual(kpi_day2["trips"], 0, "Truck arrived yesterday, so 0 arrivals today")
        self.assertEqual(kpi_day2["completed_trips"], 1, "Truck finalized on Day 2")
        self.assertEqual(kpi_day2["net_kg_dec"], Decimal("30000.00"), "Day 2 throughput must include 30,000 kg")
        self.assertEqual(kpi_day2["net_ton_dec"], Decimal("30.00"), "Day 2 throughput must be 30.00 tons")

        # 3. Two-day Combined Period
        kpi_combined = OperationalKPIService.calculate_period_kpis(start_date=self.yesterday, end_date=self.today)
        self.assertEqual(kpi_combined["trips"], 1)
        self.assertEqual(kpi_combined["completed_trips"], 1)
        self.assertEqual(kpi_combined["net_ton_dec"], Decimal("30.00"))

    def test_direct_weighing_mode(self):
        """
        Direct weighing scenario (both weights registered simultaneously).
        """
        WeighTicket.objects.create(
            serial_number="T-DIRECT-1",
            status=TicketStatus.COMPLETED,
            weight_mode=WeightMode.DIRECT,
            product=self.product_ingot,
            party=self.party_customer,
            operation_type=self.op_outbound,
            driver=self.driver,
            vehicle=self.vehicle,
            first_weight_date=self.today,
            first_weight_time=time(11, 0),
            second_weight_date=self.today,
            second_weight_time=time(11, 0),
            gross_weight=Decimal("38000.00"),
            tare_weight=Decimal("12000.00"),
            net_weight=Decimal("26000.00"),
            final_weight=Decimal("26000.00"),
        )

        kpis = OperationalKPIService.calculate_period_kpis(start_date=self.today, end_date=self.today)
        self.assertEqual(kpis["trips"], 1)
        self.assertEqual(kpis["completed_trips"], 1)
        self.assertEqual(kpis["net_ton_dec"], Decimal("26.00"))

    def test_missing_second_weight_date_fallback(self):
        """
        If a historical completed ticket has second_weight_date as NULL,
        completion_date must safely fall back to first_weight_date without error or timestamp invention.
        """
        past_date = self.today - timedelta(days=5)
        WeighTicket.objects.create(
            serial_number="T-LEGACY-1",
            status=TicketStatus.COMPLETED,
            weight_mode=WeightMode.EMPTY_FIRST,
            product=self.product_sponge,
            party=self.party_supplier,
            operation_type=self.op_inbound,
            driver=self.driver,
            vehicle=self.vehicle,
            first_weight_date=past_date,
            first_weight_time=time(14, 0),
            second_weight_date=None,  # Missing second date in legacy record
            second_weight_time=None,
            gross_weight=Decimal("35000.00"),
            tare_weight=Decimal("15000.00"),
            net_weight=Decimal("20000.00"),
            final_weight=Decimal("20000.00"),
        )

        kpis = OperationalKPIService.calculate_period_kpis(start_date=past_date, end_date=past_date)
        self.assertEqual(kpis["completed_trips"], 1)
        self.assertEqual(kpis["net_ton_dec"], Decimal("20.00"))

    def test_unit_conversion_and_decimal_precision(self):
        """
        Verifies exact Decimal kilogram-to-ton conversion and prevents floating point drift.
        """
        # Exact kilogram values
        self.assertEqual(OperationalKPIService.kg_to_ton(Decimal("1000")), Decimal("1.00"))
        self.assertEqual(OperationalKPIService.kg_to_ton(Decimal("25500")), Decimal("25.50"))
        self.assertEqual(OperationalKPIService.kg_to_ton(Decimal("12345.67")), Decimal("12.35"))
        self.assertEqual(OperationalKPIService.kg_to_ton(Decimal("12345.675")), Decimal("12.35"))
        self.assertEqual(OperationalKPIService.kg_to_ton(None), Decimal("0.00"))

    def test_dashboard_and_api_synchronization(self):
        """
        Under identical filters (e.g. today), Operator Dashboard, Management Dashboard,
        and REST APIs must report identical net tonnage and completed trip counts.
        """
        # Create 1 Completed and 1 Incomplete ticket for today
        WeighTicket.objects.create(
            serial_number="T-SYNC-1",
            status=TicketStatus.COMPLETED,
            weight_mode=WeightMode.EMPTY_FIRST,
            product=self.product_sponge,
            party=self.party_supplier,
            operation_type=self.op_inbound,
            driver=self.driver,
            vehicle=self.vehicle,
            first_weight_date=self.today,
            first_weight_time=time(8, 0),
            second_weight_date=self.today,
            second_weight_time=time(8, 30),
            gross_weight=Decimal("37000.00"),
            tare_weight=Decimal("12000.00"),
            net_weight=Decimal("25000.00"),
            final_weight=Decimal("25000.00"),
        )
        WeighTicket.objects.create(
            serial_number="T-SYNC-2",
            status=TicketStatus.WAITING_SECOND,
            weight_mode=WeightMode.EMPTY_FIRST,
            product=self.product_ingot,
            party=self.party_customer,
            operation_type=self.op_outbound,
            driver=self.driver,
            vehicle=self.vehicle,
            first_weight_date=self.today,
            first_weight_time=time(9, 0),
            first_weight=Decimal("13000.00"),
            net_weight=Decimal("0.00"),
        )

        # 1. Authoritative Service
        daily_summary = OperationalKPIService.get_daily_operational_summary(self.today)
        authoritative_net_ton = daily_summary["today_net_ton"]  # Decimal("25.00")
        authoritative_completed = daily_summary["today_completed_count"]  # 1

        # 2. Operator Dashboard View
        self.client.login(username="op_kpi", password="password123")
        res_op = self.client.get(reverse("dashboard:index"))
        self.assertEqual(res_op.status_code, 200)
        self.assertEqual(res_op.context["today_net_ton"], authoritative_net_ton)
        self.assertEqual(res_op.context["today_completed_count"], authoritative_completed)

        # 3. Management Dashboard View
        self.client.login(username="mgr_kpi", password="password123")
        res_mgr = self.client.get(reverse("management:dashboard") + "?quick_period=today")
        self.assertEqual(res_mgr.status_code, 200)
        mgr_kpis = res_mgr.context["kpis"]
        self.assertEqual(Decimal(str(mgr_kpis["net_ton"])), authoritative_net_ton)
        self.assertEqual(mgr_kpis["completed_trips"], authoritative_completed)

        # 4. REST API Summary View
        self.client.login(username="admin_kpi", password="password123")
        res_api = self.client.get(reverse("api_v1:dashboard_summary"))
        self.assertEqual(res_api.status_code, 200)
        api_data = res_api.json()
        self.assertEqual(Decimal(str(api_data["today_tonnage"])), authoritative_net_ton)
        self.assertEqual(api_data["today_completed_count"], authoritative_completed)

    def test_charts_data_standardization_and_performance(self):
        """
        Verifies that charts_data:
        - Explicitly returns 'unit': 'ton'
        - Returns values in metric tons
        - Executes in a minimal number of queries (strictly avoids 30-query loops)
        """
        # Create sample tickets across past few days
        for i in range(5):
            t_date = self.today - timedelta(days=i)
            WeighTicket.objects.create(
                serial_number=f"T-CHART-{i}",
                status=TicketStatus.COMPLETED,
                weight_mode=WeightMode.EMPTY_FIRST,
                product=self.product_sponge,
                party=self.party_supplier,
                operation_type=self.op_inbound,
                driver=self.driver,
                vehicle=self.vehicle,
                first_weight_date=t_date,
                first_weight_time=time(8, 0),
                second_weight_date=t_date,
                second_weight_time=time(8, 30),
                gross_weight=Decimal("32000.00"),
                tare_weight=Decimal("12000.00"),
                net_weight=Decimal("20000.00"),
                final_weight=Decimal("20000.00"),
            )

        self.client.login(username="admin_kpi", password="password123")

        with CaptureQueriesContext(connection) as queries_ctx:
            response = self.client.get(reverse("dashboard:charts_data"))

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Check explicit unit
        self.assertEqual(data["unit"], "ton")
        self.assertEqual(data["unit_display"], "تن (Ton)")

        # Check that 30 days of data are returned
        self.assertEqual(len(data["dates_30"]), 30)
        self.assertEqual(len(data["tonnage_30"]), 30)
        self.assertEqual(len(data["trips_30"]), 30)

        # Verify today's tonnage is 20.0 (in tons, not 20000 kg!)
        self.assertEqual(data["tonnage_30"][-1], 20.0)

        # Performance assertion: Query count must be <= 12 (far below the previous 60 queries!)
        self.assertLessEqual(len(queries_ctx.captured_queries), 12)

    def test_inbound_outbound_and_loss_aggregations(self):
        """
        Verifies correct breakdown between inbound (purchase) and outbound (sales) tonnage and losses.
        """
        # Inbound ticket: 22,000 kg net, 200 kg loss
        WeighTicket.objects.create(
            serial_number="T-IN-1",
            status=TicketStatus.COMPLETED,
            weight_mode=WeightMode.EMPTY_FIRST,
            product=self.product_sponge,
            party=self.party_supplier,
            operation_type=self.op_inbound,
            driver=self.driver,
            vehicle=self.vehicle,
            first_weight_date=self.today,
            second_weight_date=self.today,
            net_weight=Decimal("22000.00"),
            loss_weight=Decimal("200.00"),
            final_weight=Decimal("21800.00"),
            loss_percent=Decimal("0.91"),
        )

        # Outbound ticket: 28,000 kg net, 0 loss
        WeighTicket.objects.create(
            serial_number="T-OUT-1",
            status=TicketStatus.COMPLETED,
            weight_mode=WeightMode.EMPTY_FIRST,
            product=self.product_ingot,
            party=self.party_customer,
            operation_type=self.op_outbound,
            driver=self.driver,
            vehicle=self.vehicle,
            first_weight_date=self.today,
            second_weight_date=self.today,
            net_weight=Decimal("28000.00"),
            loss_weight=Decimal("0.00"),
            final_weight=Decimal("28000.00"),
        )

        kpis = OperationalKPIService.calculate_period_kpis(start_date=self.today, end_date=self.today)
        self.assertEqual(kpis["inbound_net_ton_dec"], Decimal("22.00"))
        self.assertEqual(kpis["outbound_net_ton_dec"], Decimal("28.00"))
        self.assertEqual(kpis["net_ton_dec"], Decimal("50.00"))
        self.assertEqual(kpis["loss_ton_dec"], Decimal("0.20"))
        self.assertEqual(kpis["final_ton_dec"], Decimal("49.80"))
