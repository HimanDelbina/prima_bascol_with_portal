from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from decimal import Decimal

from masterdata.models import Product, Party, Driver, Vehicle, VehicleType
from accounts.models import RoleChoices


class MasterDataAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(username="admin", password="password")
        self.operator = User.objects.create_user(username="operator", password="password")
        self.operator.profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        self.operator.profile.save()

        self.product = Product.objects.create(name="کنسانتره آهن", code="FE-02")
        self.v_type = VehicleType.objects.create(name="ده چرخ")
        self.vehicle = Vehicle.objects.create(plate_display="21 د 888 - ایران 33", vehicle_type=self.v_type)

    def test_read_masterdata_authenticated(self):
        self.client.force_authenticate(user=self.operator)
        res = self.client.get("/api/v1/products/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(res.data["count"], 1)

    def test_create_product_by_operator_forbidden(self):
        self.client.force_authenticate(user=self.operator)
        res = self.client.post("/api/v1/products/", {
            "name": "محصول غیرمجاز",
            "code": "BAD-01"
        })
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_product_by_admin_success(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.post("/api/v1/products/", {
            "name": "گندله سنگ آهن",
            "code": "PEL-01",
            "standard_tolerance_kg": 60
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["name"], "گندله سنگ آهن")

    def test_vehicle_history_action(self):
        self.client.force_authenticate(user=self.operator)
        res = self.client.get(f"/api/v1/vehicles/{self.vehicle.id}/history/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
