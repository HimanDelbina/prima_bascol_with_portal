from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from masterdata.models import (
    Party, Product, OperationType, VehicleType, Location, UnloadLocation, LossType
)
from accounts.models import UserProfile

class MasterDataQuickAddTests(TestCase):
    def setUp(self):
        self.operator = User.objects.create_user(username="operator1", password="password123")
        self.operator_profile, _ = UserProfile.objects.get_or_create(user=self.operator, defaults={"role": "weighbridge_operator"})
        self.operator_profile.role = "weighbridge_operator"
        self.operator_profile.save()
        self.client.force_login(self.operator)

    def test_quick_add_party_creates_new(self):
        url = reverse("masterdata:api_quick_add", args=["party"])
        response = self.client.post(url, {
            "name": "شرکت معدنی کاوشگران",
            "party_type": "supplier",
            "phone": "09123456789",
            "code": "ACC-99"
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "created")
        self.assertIn("معدنی کاوشگران", data["name"])
        party = Party.objects.get(id=data["id"])
        self.assertEqual(party.name, "شرکت معدنی کاوشگران")
        self.assertEqual(party.party_type, "supplier")
        self.assertTrue(party.is_active)

    def test_quick_add_party_detects_duplicate_and_returns_existing(self):
        existing = Party.objects.create(name="شرکت فولاد مبارکه", party_type="customer", is_active=True)
        url = reverse("masterdata:api_quick_add", args=["party"])
        # Same name with Arabic yeh or extra spaces
        response = self.client.post(url, {
            "name": "  شرکت فولاد مباركه  ",
            "party_type": "supplier"
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "duplicate")
        self.assertEqual(data["id"], existing.id)
        self.assertIn("از قبل در سیستم وجود دارد", data["message"])
        # Should not create duplicate
        self.assertEqual(Party.objects.filter(name__icontains="فولاد مبارکه").count(), 1)

    def test_quick_add_product_created_and_duplicate(self):
        url = reverse("masterdata:api_quick_add", args=["product"])
        response = self.client.post(url, {
            "name": "سنگ آهن دانه بندی",
            "code": "FE-01",
            "default_loss_percent": "1.50",
            "standard_tolerance_kg": "60"
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "created")
        prod = Product.objects.get(id=data["id"])
        self.assertEqual(prod.name, "سنگ آهن دانه بندی")
        self.assertEqual(float(prod.default_loss_percent), 1.5)

        # Duplicate check
        dup_res = self.client.post(url, {"name": "سنگ آهن دانه بندی"})
        self.assertEqual(dup_res.status_code, 200)
        dup_data = dup_res.json()
        self.assertEqual(dup_data["status"], "duplicate")
        self.assertEqual(dup_data["id"], prod.id)

    def test_quick_add_location_origin_destination(self):
        url = reverse("masterdata:api_quick_add", args=["origin"])
        response = self.client.post(url, {"name": "بندر انزلی", "description": "اسکله غربی"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "created")
        loc = Location.objects.get(id=data["id"])
        self.assertEqual(loc.name, "بندر انزلی")

        # Adding as destination detects duplicate and keeps it usable
        dest_url = reverse("masterdata:api_quick_add", args=["destination"])
        dest_res = self.client.post(dest_url, {"name": "بندر انزلی"})
        self.assertEqual(dest_res.status_code, 200)
        self.assertEqual(dest_res.json()["status"], "duplicate")
        self.assertEqual(dest_res.json()["id"], loc.id)

    def test_quick_add_operation_and_vehicle_type(self):
        # Operation Type
        url = reverse("masterdata:api_quick_add", args=["operation_type"])
        res = self.client.post(url, {"name": "تخلیه آزمایشی", "direction": "inbound"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "created")
        op_id = res.json()["id"]

        # Duplicate operation type
        dup_op = self.client.post(url, {"name": "تخلیه آزمایشی"})
        self.assertEqual(dup_op.json()["status"], "duplicate")
        self.assertEqual(dup_op.json()["id"], op_id)

        # Vehicle Type
        vt_url = reverse("masterdata:api_quick_add", args=["vehicle_type"])
        vt_res = self.client.post(vt_url, {"name": "کمپرسی جفت", "standard_tare_weight": "15000"})
        self.assertEqual(vt_res.status_code, 200)
        self.assertEqual(vt_res.json()["status"], "created")
