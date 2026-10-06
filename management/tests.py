from decimal import Decimal
from datetime import date, time, timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User

from accounts.models import UserProfile, RoleChoices
from masterdata.models import Product, Party, Driver, Vehicle, OperationType, LossType
from weighbridge.models import WeighTicket, TicketStatus, WeightMode
from management.models import SavedReport

class ManagementSuiteTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Users
        self.admin = User.objects.create_superuser(username="admin_user", password="password123")
        self.manager = User.objects.create_user(username="mgr_user", password="password123")
        self.manager.profile.role = RoleChoices.WEIGHBRIDGE_MANAGER
        self.manager.profile.save()

        self.ceo = User.objects.create_user(username="ceo_user", password="password123")
        self.ceo.profile.role = RoleChoices.CEO
        self.ceo.profile.save()

        self.operator = User.objects.create_user(username="op_user", password="password123")
        self.operator.profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        self.operator.profile.save()

        # Masterdata
        self.product = Product.objects.create(name="شمش فولادی 150", code="BL-150")
        self.party_supplier = Party.objects.create(name="شرکت تامین فولاد خوزستان", party_type="supplier")
        self.party_customer = Party.objects.create(name="فولاد کاوه جنوب", party_type="customer")
        self.op_in = OperationType.objects.create(name="خرید مواد اولیه", direction="inbound")
        self.op_out = OperationType.objects.create(name="فروش شمش", direction="outbound")
        self.driver = Driver.objects.create(full_name="علی اکبری")
        self.vehicle = Vehicle.objects.create(
            plate_part1="12",
            plate_letter="الف",
            plate_part2="345",
            plate_iran="67",
            plate_display="12 الف 345 ایران 67"
        )

        # Tickets
        today = date.today()
        WeighTicket.objects.create(
            serial_number="10001",
            weight_mode=WeightMode.EMPTY_FIRST,
            product=self.product,
            party=self.party_supplier,
            operation_type=self.op_in,
            driver=self.driver,
            vehicle=self.vehicle,
            first_weight_date=today,
            first_weight_time=time(8, 0),
            second_weight_date=today,
            second_weight_time=time(8, 45),
            gross_weight=Decimal("35000"),
            tare_weight=Decimal("12000"),
            net_weight=Decimal("23000"),
            sent_weight=Decimal("23100"),
            weight_difference=Decimal("-100"),
            is_tolerance_exceeded=True,
            loss_weight=Decimal("200"),
            loss_percent=Decimal("0.87"),
            final_weight=Decimal("22800"),
            status=TicketStatus.COMPLETED,
        )

        WeighTicket.objects.create(
            serial_number="10002",
            weight_mode=WeightMode.EMPTY_FIRST,
            product=self.product,
            party=self.party_customer,
            operation_type=self.op_out,
            driver=self.driver,
            vehicle=self.vehicle,
            first_weight_date=today,
            first_weight_time=time(10, 0),
            second_weight_date=today,
            second_weight_time=time(10, 25),
            gross_weight=Decimal("40000"),
            tare_weight=Decimal("14000"),
            net_weight=Decimal("26000"),
            sent_weight=Decimal("26000"),
            weight_difference=Decimal("0"),
            is_tolerance_exceeded=False,
            final_weight=Decimal("26000"),
            status=TicketStatus.COMPLETED,
        )

    def test_permission_restrictions(self):
        # Unauthenticated
        response = self.client.get(reverse("management:dashboard"))
        self.assertEqual(response.status_code, 302)

        # Operator (unauthorized)
        self.client.login(username="op_user", password="password123")
        response = self.client.get(reverse("management:dashboard"))
        self.assertEqual(response.status_code, 302)

        # CEO (authorized)
        self.client.login(username="ceo_user", password="password123")
        response = self.client.get(reverse("management:dashboard"))
        self.assertEqual(response.status_code, 200)

        # Weighbridge Manager (unauthorized per latest policy)
        self.client.login(username="mgr_user", password="password123")
        response = self.client.get(reverse("management:dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_dashboard_metrics_and_context(self):
        self.client.login(username="ceo_user", password="password123")
        response = self.client.get(reverse("management:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("kpis", response.context)
        self.assertIn("comparison", response.context)
        self.assertIn("top10", response.context)
        self.assertIn("narrative_summary", response.context)
        self.assertIn("trends_json", response.context)

        kpis = response.context["kpis"]
        self.assertEqual(kpis["trips"], 2)
        self.assertEqual(kpis["completed_trips"], 2)
        self.assertEqual(kpis["net_ton"], 49.0) # 23 + 26 = 49 Ton
        self.assertEqual(kpis["inbound_net_ton"], 23.0)
        self.assertEqual(kpis["outbound_net_ton"], 26.0)
        self.assertEqual(kpis["discrepancies_count"], 1)

    def test_excel_and_csv_export(self):
        # Weighbridge Manager cannot export management reports
        self.client.login(username="mgr_user", password="password123")
        res_mgr = self.client.get(reverse("management:dashboard") + "?export=excel")
        self.assertEqual(res_mgr.status_code, 302)

        # CEO can export management reports
        self.client.login(username="ceo_user", password="password123")
        
        # Excel
        res_excel = self.client.get(reverse("management:dashboard") + "?export=excel")
        self.assertEqual(res_excel.status_code, 200)
        self.assertEqual(
            res_excel["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        # CSV
        res_csv = self.client.get(reverse("management:dashboard") + "?export=csv")
        self.assertEqual(res_csv.status_code, 200)
        self.assertEqual(res_csv["Content-Type"], "text/csv; charset=utf-8-sig")

    def test_all_management_report_views(self):
        self.client.login(username="ceo_user", password="password123")
        
        views_to_test = [
            "management:inbound_outbound",
            "management:purchases",
            "management:sales",
            "management:products",
            "management:parties",
            "management:discrepancies",
            "management:loss",
            "management:drivers_vehicles",
            "management:routes",
            "management:operations",
            "management:monthly",
            "management:yearly",
            "management:print",
            "management:tv_monitor",
        ]
        for v in views_to_test:
            res = self.client.get(reverse(v))
            self.assertEqual(res.status_code, 200, f"View {v} failed with status {res.status_code}")

    def test_charts_and_filters_api(self):
        # Weighbridge Manager cannot access charts API
        self.client.login(username="mgr_user", password="password123")
        res_mgr = self.client.get(reverse("management:api_charts"))
        self.assertEqual(res_mgr.status_code, 302)

        # CEO can access charts API
        self.client.login(username="ceo_user", password="password123")
        
        # Charts API
        res_charts = self.client.get(reverse("management:api_charts"))
        self.assertEqual(res_charts.status_code, 200)
        data = res_charts.json()
        self.assertIn("trends", data)
        self.assertIn("heatmap", data)
        self.assertIn("top_products", data)

        # Save filter API
        res_save = self.client.post(reverse("management:api_save_filter"), {
            "title": "فیلتر تست خرید شمش",
            "report_type": "dashboard",
            "direction": "inbound",
            "product": str(self.product.id),
        })
        self.assertEqual(res_save.status_code, 200)
        self.assertEqual(res_save.json()["status"], "ok")

        # Load filters API
        res_load = self.client.get(reverse("management:api_load_filters"))
        self.assertEqual(res_load.status_code, 200)
        saved = res_load.json()["reports"]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["title"], "فیلتر تست خرید شمش")
