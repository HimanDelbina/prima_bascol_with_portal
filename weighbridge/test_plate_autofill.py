from decimal import Decimal
from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import UserProfile
from masterdata.models import (
    Driver, Location, LossType, OperationType, Party, Product,
    UnloadLocation, Vehicle, VehicleType,
)
from weighbridge.models import (
    PlateAutoFill, WeighTicket, TicketStatus, WeightMode
)
from weighbridge.plate_policy import normalize_plate


class PlateAutoFillTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Operator user
        self.operator = User.objects.create_user(username="wb_op", password="password123")
        op_profile = self.operator.profile
        op_profile.role = "weighbridge_operator"
        op_profile.is_active = True
        op_profile.save()

        # Super Admin user
        self.super_admin = User.objects.create_user(username="wb_super", password="password123")
        admin_profile = self.super_admin.profile
        admin_profile.role = "super_admin"
        admin_profile.is_active = True
        admin_profile.save()

        # Default login as operator
        self.client.login(username="wb_op", password="password123")

        # Master Data
        self.vtype = VehicleType.objects.create(name="تریلی کفی")
        self.driver = Driver.objects.create(full_name="علی محمدی", mobile="09123456789")
        self.product = Product.objects.create(name="شمش فولادی 150")
        self.party = Party.objects.create(name="فولاد مبارکه اصفهان")
        self.op_type = OperationType.objects.create(name="خروج بار فروش")
        self.origin = Location.objects.create(name="کارخانه اصلی")
        self.destination = Location.objects.create(name="انبار مرکزی تهران")
        self.unload_loc = UnloadLocation.objects.create(name="سیلو شماره ۳")
        self.loss_type = LossType.objects.create(name="افت رطوبت")

        self.plate_display = "12 ع 345 - ایران 64"
        self.norm_plate = normalize_plate(self.plate_display)

        self.vehicle = Vehicle.objects.create(
            plate_display=self.plate_display,
            vehicle_type=self.vtype,
            default_driver=self.driver,
        )

        # Existing completed ticket for this vehicle
        self.ticket = WeighTicket.objects.create(
            serial_number="WB-TEST-999",
            status=TicketStatus.COMPLETED,
            weight_mode=WeightMode.EMPTY_FIRST,
            license_plate_display=self.plate_display,
            vehicle=self.vehicle,
            vehicle_type=self.vtype,
            driver=self.driver,
            driver_name_custom="علی محمدی",
            driver_mobile_custom="09123456789",
            party=self.party,
            product=self.product,
            operation_type=self.op_type,
            origin=self.origin,
            destination=self.destination,
            unload_location=self.unload_loc,
            freight_amount=Decimal("15000000"),
            load_count=2,
            ingot_count=45,
            loss_type=self.loss_type,
            loss_percent=Decimal("1.25"),
            first_weight=Decimal("14200"),
            second_weight=Decimal("38500"),
            gross_weight=Decimal("38500"),
            tare_weight=Decimal("14200"),
            net_weight=Decimal("24300"),
            final_weight=Decimal("23996"),
        )

    def test_plate_autofill_model_creation_and_normalization(self):
        obj = PlateAutoFill.objects.create(
            license_plate_display=" 12 ع 345 - ایران 64 ",
            notes="کامیون‌های ثابت فروش",
            created_by=self.operator,
        )
        self.assertEqual(obj.normalized_plate, self.norm_plate)
        self.assertTrue(obj.is_active)
        self.assertIn("12", str(obj))

    def test_operator_denied_access_to_plate_autofill_management(self):
        """Operators must receive 403 Forbidden when trying to access or manage autofill plates."""
        url = reverse("weighbridge:plate_autofill")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        post_data = {
            "action": "save",
            "plate_part1": "12",
            "plate_letter": "ع",
            "plate_part2": "345",
            "plate_iran": "64",
            "notes": "تست اپراتور",
        }
        post_resp = self.client.post(url, post_data)
        self.assertEqual(post_resp.status_code, 403)

    def test_super_admin_allowed_access_and_get_autofill_view(self):
        """Super Admin can access the autofill management page."""
        self.client.login(username="wb_super", password="password123")
        url = reverse("weighbridge:plate_autofill")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "پلاک‌های تکمیل خودکار")

    def test_super_admin_add_plate(self):
        """Super Admin can add new plates to autofill."""
        self.client.login(username="wb_super", password="password123")
        url = reverse("weighbridge:plate_autofill")
        post_data = {
            "action": "save",
            "plate_part1": "12",
            "plate_letter": "ع",
            "plate_part2": "345",
            "plate_iran": "64",
            "notes": "خودروی ثابت شمش",
        }
        response = self.client.post(url, post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(PlateAutoFill.objects.filter(normalized_plate=self.norm_plate).exists())

    def test_super_admin_toggle_status_and_delete(self):
        """Super Admin can activate, deactivate, and delete autofill entries."""
        obj = PlateAutoFill.objects.create(
            license_plate_display=self.plate_display,
            notes="تست",
            created_by=self.super_admin,
            is_active=True,
        )
        self.client.login(username="wb_super", password="password123")
        url = reverse("weighbridge:plate_autofill")

        # Deactivate
        self.client.post(url, {"action": "deactivate", "item_id": str(obj.pk)})
        obj.refresh_from_db()
        self.assertFalse(obj.is_active)

        # Activate
        self.client.post(url, {"action": "activate", "item_id": str(obj.pk)})
        obj.refresh_from_db()
        self.assertTrue(obj.is_active)

        # Delete
        self.client.post(url, {"action": "delete", "item_id": str(obj.pk)})
        self.assertFalse(PlateAutoFill.objects.filter(pk=obj.pk).exists())

    def test_ticket_create_view_hides_button_from_operator_and_shows_for_super_admin(self):
        """ticket_create UI shows management button only to super admin."""
        url = reverse("weighbridge:ticket_create")
        
        # As operator: button must NOT be present
        self.client.login(username="wb_op", password="password123")
        op_resp = self.client.get(url)
        self.assertEqual(op_resp.status_code, 200)
        self.assertFalse(op_resp.context.get("can_manage_plate_autofill"))
        self.assertNotContains(op_resp, "مدیریت پلاک‌های تکمیل خودکار")

        # As super admin: button MUST be present
        self.client.login(username="wb_super", password="password123")
        admin_resp = self.client.get(url)
        self.assertEqual(admin_resp.status_code, 200)
        self.assertTrue(admin_resp.context.get("can_manage_plate_autofill"))
        self.assertContains(admin_resp, "مدیریت پلاک‌های تکمیل خودکار")

    def test_ajax_plate_lookup_new_plate_without_history(self):
        # A completely new plate without ticket history or autofill rule
        url = reverse("weighbridge:ajax_plate_lookup")
        response = self.client.get(url, {"plate": "99 ب 999 - ایران 99"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data.get("is_autofill_enabled"))
        self.assertIsNone(data.get("autofill_data"))

    def test_ajax_plate_lookup_plate_with_history_autofills_everything(self):
        # Plate with previous tickets automatically populates all metadata
        url = reverse("weighbridge:ajax_plate_lookup")
        response = self.client.get(url, {"plate": self.plate_display})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("is_autofill_enabled"))
        af = data.get("autofill_data")
        self.assertIsNotNone(af)
        self.assertEqual(af["party_id"], self.party.id)
        self.assertEqual(af["product_id"], self.product.id)
        self.assertEqual(af["operation_type_id"], self.op_type.id)
        self.assertEqual(af["origin_id"], self.origin.id)
        self.assertEqual(af["destination_id"], self.destination.id)
        self.assertEqual(af["unload_location_id"], self.unload_loc.id)

    def test_ajax_plate_lookup_with_autofill_rule(self):
        # Register in PlateAutoFill
        PlateAutoFill.objects.create(
            license_plate_display=self.plate_display,
            notes="تکمیل خودکار شمش",
            created_by=self.super_admin,
            is_active=True,
        )

        url = reverse("weighbridge:ajax_plate_lookup")
        response = self.client.get(url, {"plate": self.plate_display})
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertTrue(data.get("is_autofill_enabled"))
        af = data.get("autofill_data")
        self.assertIsNotNone(af)

        # Verify all metadata fields match the last ticket
        self.assertEqual(af["last_ticket_serial"], "WB-TEST-999")
        self.assertEqual(af["party_id"], self.party.id)
        self.assertEqual(af["party_name"], self.party.name)
        self.assertEqual(af["product_id"], self.product.id)
        self.assertEqual(af["product_name"], self.product.name)
        self.assertEqual(af["operation_type_id"], self.op_type.id)
        self.assertEqual(af["origin_id"], self.origin.id)
        self.assertEqual(af["destination_id"], self.destination.id)
        self.assertEqual(af["unload_location_id"], self.unload_loc.id)
        self.assertEqual(af["freight_amount"], 15000000)
        self.assertEqual(af["load_count"], 2)
        self.assertEqual(af["ingot_count"], 45)
        self.assertEqual(af["loss_type_id"], self.loss_type.id)
        self.assertEqual(af["loss_percent"], 1.25)
        self.assertEqual(af["driver_name"], "علی محمدی")
        self.assertEqual(af["driver_mobile"], "09123456789")

        # STRICT ASSERTION: Verify weights are NEVER returned in autofill_data
        self.assertNotIn("first_weight", af)
        self.assertNotIn("second_weight", af)
        self.assertNotIn("gross_weight", af)
        self.assertNotIn("tare_weight", af)
        self.assertNotIn("net_weight", af)
        self.assertNotIn("final_weight", af)
        self.assertNotIn("sent_weight", af)
        self.assertNotIn("loss_weight", af)
