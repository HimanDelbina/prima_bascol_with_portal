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
