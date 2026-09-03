from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from decimal import Decimal

from weighbridge.models import WeighTicket, TicketStatus
from masterdata.models import Product, Party, OperationType
from accounts.models import RoleChoices


class ReportAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="reporter", password="password")
        self.user.profile.role = RoleChoices.REPORT_MANAGER
        self.user.profile.save()

        self.product = Product.objects.create(name="آهک کلسینه", code="AH-01")
        self.party = Party.objects.create(name="مجتمع فولاد خوزستان")
        self.op_type = OperationType.objects.create(name="فروش صادراتی", direction="outbound")

        self.t1 = WeighTicket.objects.create(
            serial_number="REP-001",
            license_plate_display="12 ع 345 - ایران 68",
            product=self.product,
            party=self.party,
            operation_type=self.op_type,
            gross_weight=Decimal("35000.00"),
            tare_weight=Decimal("15000.00"),
            net_weight=Decimal("20000.00"),
            final_weight=Decimal("20000.00"),
            status=TicketStatus.COMPLETED
        )

    def test_report_tickets_list(self):
        self.client.force_authenticate(user=self.user)
        res = self.client.get("/api/v1/reports/tickets/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["count"], 1)

    def test_report_summary(self):
        self.client.force_authenticate(user=self.user)
        res = self.client.get("/api/v1/reports/tickets/summary/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["total_tickets"], 1)
        self.assertEqual(float(res.data["sum_net"]), 20000.0)

    def test_report_grouped(self):
        self.client.force_authenticate(user=self.user)
        res = self.client.get("/api/v1/reports/tickets/grouped/?group_by=product")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["count"], 1)
        self.assertEqual(res.data["results"][0]["group_title"], "آهک کلسینه")

    def test_export_excel(self):
        self.client.force_authenticate(user=self.user)
        res = self.client.get("/api/v1/reports/tickets/export/xlsx/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    def test_export_csv(self):
        self.client.force_authenticate(user=self.user)
        res = self.client.get("/api/v1/reports/tickets/export/csv/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("text/csv", res['Content-Type'])
