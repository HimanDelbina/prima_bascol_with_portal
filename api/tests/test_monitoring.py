from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from decimal import Decimal

from weighbridge.models import WeighTicket, TicketStatus
from monitoring.models import MonitoringAlert, AlertStatus, AlertSeverity, AlertType
from accounts.models import RoleChoices


class MonitoringAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.manager = User.objects.create_user(username="manager_mon", password="password")
        self.manager.profile.role = RoleChoices.WEIGHBRIDGE_MANAGER
        self.manager.profile.save()

        self.operator = User.objects.create_user(username="operator_mon", password="password")
        self.operator.profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        self.operator.profile.save()

        self.ticket = WeighTicket.objects.create(
            serial_number="MON-100",
            license_plate_display="11 ج 222 - ایران 44",
            status=TicketStatus.COMPLETED
        )
        self.alert = MonitoringAlert.objects.create(
            ticket=self.ticket,
            alert_type=AlertType.WEIGHT_DISCREPANCY,
            severity=AlertSeverity.HIGH,
            title="مغایرت بارنامه و باسکول",
            description="اختلاف وزن بیش از حد مجاز",
            reason="اختلاف ۱۵۰ کیلوگرمی",
            current_value=Decimal("150.00"),
            status=AlertStatus.OPEN
        )

    def test_list_alerts(self):
        self.client.force_authenticate(user=self.operator)
        res = self.client.get("/api/v1/monitoring/alerts/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["count"], 1)
        self.assertEqual(res.data["results"][0]["severity"]["code"], AlertSeverity.HIGH)

    def test_resolve_alert_by_manager(self):
        self.client.force_authenticate(user=self.manager)
        res = self.client.post(f"/api/v1/monitoring/alerts/{self.alert.id}/resolve/", {
            "resolution_note": "بارنامه با مبدأ کنترل شد و مغایرت موجه تشخیص داده شد."
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, AlertStatus.RESOLVED)
        self.assertEqual(self.alert.resolved_by, self.manager)

    def test_operator_cannot_resolve_alert(self):
        self.client.force_authenticate(user=self.operator)
        res = self.client.post(f"/api/v1/monitoring/alerts/{self.alert.id}/resolve/", {
            "resolution_note": "اقدام غیرمجاز"
        })
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_monitoring_summary(self):
        self.client.force_authenticate(user=self.operator)
        res = self.client.get("/api/v1/monitoring/summary/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("open", res.data)
        self.assertIn("high", res.data)
        self.assertIn("critical", res.data)
