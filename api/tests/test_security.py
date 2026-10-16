from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status

from accounts.models import RoleChoices


class SecurityAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.operator = User.objects.create_user(username="operator_sec", password="password")
        self.operator.profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        self.operator.profile.save()

    def test_unauthenticated_access_returns_401_with_envelope(self):
        res = self.client.get("/api/v1/tickets/")
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(res.data["success"])
        self.assertEqual(res.data["error"]["code"], "AUTHENTICATION_REQUIRED")

    def test_operator_cannot_access_admin_settings(self):
        self.client.force_authenticate(user=self.operator)
        res = self.client.get("/api/v1/admin/settings/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(res.data["success"])
        self.assertEqual(res.data["error"]["code"], "PERMISSION_DENIED")

    def test_public_meta_and_health_accessible(self):
        meta_res = self.client.get("/api/v1/meta/")
        self.assertEqual(meta_res.status_code, status.HTTP_200_OK)
        self.assertEqual(meta_res.data["api_version"], "v1.0.0")

        health_res = self.client.get("/api/v1/health/")
        self.assertEqual(health_res.status_code, status.HTTP_200_OK)
        self.assertEqual(health_res.data["status"], "ok")

    def test_readonly_serial_number_cannot_be_forged(self):
        self.client.force_authenticate(user=self.operator)
        res = self.client.post("/api/v1/tickets/", {
            "serial_number": "FORGED-9999",
            "license_plate_display": "11 ج 222 - ایران 33",
            "first_weight": 12000
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        # Verify backend ignored the forged serial and generated genuine serial
        self.assertNotEqual(res.data["serial_number"], "FORGED-9999")


from audit.models import AuditLog, AuditAction
from weighbridge.models import WeighTicket, TicketStatus
from masterdata.models import Product
from decimal import Decimal
from api.v1.throttling import PasswordReauthThrottle


class HardenedSecurityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="test_auth_user", password="CorrectPassword123!")
        self.user.profile.role = RoleChoices.WEIGHBRIDGE_MANAGER
        self.user.profile.save()

        self.operator = User.objects.create_user(username="operator_sec2", password="password")
        self.operator.profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        self.operator.profile.save()

        self.product = Product.objects.create(name="سنگ آهن", code="FE-01", standard_tolerance_kg=Decimal("100.00"))

    def test_verify_password_requires_authentication(self):
        res = self.client.post("/api/v1/auth/verify-password/", {"password": "CorrectPassword123!"})
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_verify_password_success(self):
        self.client.force_authenticate(user=self.user)
        res = self.client.post("/api/v1/auth/verify-password/", {"password": "CorrectPassword123!"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["success"])
        self.assertTrue(res.data["valid"])

    def test_verify_password_failure_audits_without_leaking_credentials(self):
        self.client.force_authenticate(user=self.user)
        res = self.client.post("/api/v1/auth/verify-password/", {"password": "WrongPasswordAttempt"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["success"])
        self.assertFalse(res.data["valid"])

        audit = AuditLog.objects.filter(model_name="UserSecurity", record_id=str(self.user.id)).latest("timestamp")
        self.assertEqual(audit.user, self.user)
        self.assertEqual(audit.source, "API")
        self.assertNotIn("WrongPasswordAttempt", str(audit.old_values))
        self.assertNotIn("WrongPasswordAttempt", str(audit.new_values))
        self.assertNotIn("WrongPasswordAttempt", audit.reason)
        self.assertNotIn("token", str(audit.new_values))
        self.assertNotIn("Bearer", str(audit.new_values))

    def test_verify_password_has_dedicated_throttle_scope(self):
        from api.v1.views.auth_views import VerifyPasswordView
        self.assertEqual(VerifyPasswordView.throttle_scope, "password_reauth")
        self.assertIn(PasswordReauthThrottle, VerifyPasswordView.throttle_classes)

    def test_ticket_cancel_audits_source_and_old_values(self):
        ticket = WeighTicket.objects.create(
            serial_number="SEC-CANCEL-1",
            license_plate_display="12 ع 345 - ایران 68",
            product=self.product,
            first_weight=Decimal("15000.00"),
            second_weight=Decimal("35000.00"),
            gross_weight=Decimal("35000.00"),
            tare_weight=Decimal("15000.00"),
            net_weight=Decimal("20000.00"),
            final_weight=Decimal("20000.00"),
            status=TicketStatus.COMPLETED
        )
        self.client.force_authenticate(user=self.user)
        res = self.client.post(f"/api/v1/tickets/{ticket.id}/cancel/", {"reason": "ابطال به علت اشتباه راننده"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        audit = AuditLog.objects.filter(model_name="WeighTicket", record_id=str(ticket.id), action=AuditAction.CANCEL).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.source, "API")
        self.assertEqual(audit.user, self.user)
        self.assertEqual(audit.reason, "ابطال به علت اشتباه راننده")
        self.assertEqual(audit.new_values["status"], TicketStatus.CANCELLED)

    def test_ticket_correction_weight_vs_loss_audit_actions(self):
        ticket = WeighTicket.objects.create(
            serial_number="SEC-CORRECT-1",
            license_plate_display="12 ع 345 - ایران 68",
            product=self.product,
            first_weight=Decimal("15000.00"),
            second_weight=Decimal("35000.00"),
            gross_weight=Decimal("35000.00"),
            tare_weight=Decimal("15000.00"),
            net_weight=Decimal("20000.00"),
            final_weight=Decimal("20000.00"),
            status=TicketStatus.WAITING_SECOND
        )
        self.client.force_authenticate(user=self.user)

        # 1. Weight override
        res_weight = self.client.post(f"/api/v1/tickets/{ticket.id}/correct/", {
            "field": "first_weight",
            "new_value": 15200,
            "reason": "خطای قرائت باسکول"
        })
        self.assertEqual(res_weight.status_code, status.HTTP_200_OK)
        audit_w = AuditLog.objects.filter(
            model_name="WeighTicket",
            record_id=str(ticket.id),
            action=AuditAction.OVERRIDE_WEIGHT
        ).first()
        self.assertIsNotNone(audit_w)
        self.assertEqual(audit_w.source, "API")

        # 2. Loss override
        res_loss = self.client.post(f"/api/v1/tickets/{ticket.id}/correct/", {
            "field": "loss_weight",
            "new_value": 300,
            "reason": "افت دستی تاییدشده مدیر"
        })
        self.assertEqual(res_loss.status_code, status.HTTP_200_OK)
        audit_l = AuditLog.objects.filter(
            model_name="WeighTicket",
            record_id=str(ticket.id),
            action=AuditAction.OVERRIDE_LOSS
        ).first()
        self.assertIsNotNone(audit_l)
        self.assertEqual(audit_l.source, "API")
        self.assertEqual(audit_l.reason, "افت دستی تاییدشده مدیر")
