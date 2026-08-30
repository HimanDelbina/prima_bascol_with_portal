from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from decimal import Decimal
from datetime import timedelta
from core.jalali import get_today_gregorian
from weighbridge.models import WeighTicket, TicketStatus
from masterdata.models import Product, Party, OperationType

class DashboardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="test_dashboard_user", password="password123")
        self.client = Client()
        
        self.product = Product.objects.create(name="شمش فولادی")
        self.party = Party.objects.create(name="فولاد مبارکه")
        self.op_type = OperationType.objects.create(name="فروش مستقیم", direction="outbound")
        
        today_g = get_today_gregorian()
        self.ticket = WeighTicket.objects.create(
            serial_number="WB-DASH-1",
            status=TicketStatus.COMPLETED,
            product=self.product,
            party=self.party,
            operation_type=self.op_type,
            first_weight=Decimal("35000.00"),
            second_weight=Decimal("15000.00"),
            gross_weight=Decimal("35000.00"),
            tare_weight=Decimal("15000.00"),
            net_weight=Decimal("20000.00"),
            first_weight_date=today_g,
            license_plate_display="12 ج 345 - ایران 67"
        )

    def test_url_reversal(self):
        """Test URL reverse for dashboard views."""
        self.assertEqual(reverse("dashboard:index"), "/dashboard/")
        self.assertEqual(reverse("dashboard:charts_data"), "/dashboard/charts-data/")

    def test_dashboard_index_anonymous_redirect(self):
        """Anonymous access to dashboard should redirect to login."""
        response = self.client.get(reverse("dashboard:index"))
        self.assertEqual(response.status_code, 302)

    def test_dashboard_index_render(self):
        """Authenticated user should receive 200 OK and template rendered without error."""
        self.client.login(username="test_dashboard_user", password="password123")
        response = self.client.get(reverse("dashboard:index"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/index.html")
        self.assertIn("today_trips", response.context)
        self.assertIn("today_net", response.context)

    def test_charts_data_api(self):
        """Test JSON output of charts_data endpoint."""
        self.client.login(username="test_dashboard_user", password="password123")
        response = self.client.get(reverse("dashboard:charts_data"))
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertIn("dates_30", data)
        self.assertIn("tonnage_30", data)
        self.assertIn("trips_30", data)
        self.assertIn("product_labels", data)
        self.assertIn("product_values", data)
        self.assertIn("inbound_tonnage", data)
        self.assertIn("outbound_tonnage", data)
        self.assertIn("party_labels", data)
        self.assertIn("party_values", data)
        
        self.assertEqual(len(data["dates_30"]), 30)
        self.assertEqual(len(data["tonnage_30"]), 30)
        self.assertEqual(len(data["trips_30"]), 30)
        self.assertIn("شمش فولادی", data["product_labels"])
        self.assertIn("فولاد مبارکه", data["party_labels"])
