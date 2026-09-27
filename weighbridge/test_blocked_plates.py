from decimal import Decimal
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import UserProfile, RoleChoices
from weighbridge.models import BlockedPlate, WeighTicket, TicketStatus, WeightMode
from weighbridge.plate_policy import DailyPlatePolicy, can_manage_blocked_plates, normalize_plate
from weighbridge.forms import TicketCreateForm
from masterdata.models import Product, Party, Location, OperationType


class BlockedPlateTests(TestCase):
    def setUp(self):
        # Admin / Manager user
        self.manager_user = User.objects.create_user(
            username="manager1",
            password="password123",
            first_name="مدیر",
            last_name="باسکول"
        )
        self.manager_profile = self.manager_user.profile
        self.manager_profile.role = RoleChoices.WEIGHBRIDGE_MANAGER
        self.manager_profile.save()

        # Operator user (unauthorized to manage blocked plates)
        self.operator_user = User.objects.create_user(
            username="operator1",
            password="password123",
            first_name="اپراتور",
            last_name="تست"
        )
        self.operator_profile = self.operator_user.profile
        self.operator_profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        self.operator_profile.save()

        # Base MasterData
        self.product = Product.objects.create(name="آهن اسفنجی", code="P1", is_active=True)
        self.party = Party.objects.create(name="شرکت فولاد تست", code="C1", is_active=True)
        self.origin = Location.objects.create(name="تهران", is_active=True)
        self.op_type = OperationType.objects.create(name="ورودی خرید", is_active=True)

        self.client = Client()

    def test_permission_can_manage_blocked_plates(self):
        self.assertTrue(can_manage_blocked_plates(self.manager_user))
        self.assertFalse(can_manage_blocked_plates(self.operator_user))

    def test_view_access_restriction(self):
        url = reverse("weighbridge:blocked_plates")
        # Operator gets 403 Forbidden
        self.client.login(username="operator1", password="password123")
        res = self.client.get(url)
        self.assertEqual(res.status_code, 403)

        # Manager gets 200 OK
        self.client.login(username="manager1", password="password123")
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "لیست سیاه")

    def test_create_blocked_plate_via_post(self):
        self.client.login(username="manager1", password="password123")
        url = reverse("weighbridge:blocked_plates")
        payload = {
            "action": "save",
            "plate_part1": "12",
            "plate_letter": "ع",
            "plate_part2": "345",
            "plate_iran": "64",
            "license_plate_display": "12 ع 345 - ایران 64",
            "reason": "تخلف در تناژ بار و دستکاری بارنامه",
        }
        res = self.client.post(url, data=payload, follow=True)
        self.assertEqual(res.status_code, 200)

        # Verify DB entry
        norm = normalize_plate("12 ع 345 - ایران 64")
        bp = BlockedPlate.objects.filter(normalized_plate=norm).first()
        self.assertIsNotNone(bp)
        self.assertTrue(bp.is_active)
        self.assertEqual(bp.reason, "تخلف در تناژ بار و دستکاری بارنامه")
        self.assertEqual(bp.blocked_by, self.manager_user)

    def test_toggle_blocked_plate_status(self):
        self.client.login(username="manager1", password="password123")
        url = reverse("weighbridge:blocked_plates")
        bp = BlockedPlate.objects.create(
            license_plate_display="55 ب 888 - ایران 11",
            normalized_plate=normalize_plate("55 ب 888 - ایران 11"),
            reason="عدم تسویه بدهی مالی",
            blocked_by=self.manager_user,
            is_active=True
        )

        # Deactivate (Unblock)
        res = self.client.post(url, {"action": "deactivate", "item_id": str(bp.id)}, follow=True)
        self.assertEqual(res.status_code, 200)
        bp.refresh_from_db()
        self.assertFalse(bp.is_active)

        # Re-activate (Re-block)
        res = self.client.post(url, {"action": "activate", "item_id": str(bp.id)}, follow=True)
        self.assertEqual(res.status_code, 200)
        bp.refresh_from_db()
        self.assertTrue(bp.is_active)

    def test_daily_plate_policy_enforcement(self):
        # Create active blocked plate
        plate_str = "23 د 456 - ایران 78"
        BlockedPlate.objects.create(
            license_plate_display=plate_str,
            normalized_plate=normalize_plate(plate_str),
            reason="دستور حراست جهت توقیف",
            blocked_by=self.manager_user,
            is_active=True
        )

        ticket = WeighTicket(
            license_plate_display=plate_str,
            status=TicketStatus.WAITING_SECOND,
            product=self.product,
            party=self.party,
            origin=self.origin,
            operation_type=self.op_type,
            first_weight=Decimal("15000"),
            weight_mode=WeightMode.EMPTY_FIRST
        )

        # Policy check must fail
        with self.assertRaises(ValidationError) as ctx:
            DailyPlatePolicy.check(ticket)
        self.assertIn("لیست سیاه مسدود شده است", str(ctx.exception))
        self.assertIn("دستور حراست جهت توقیف", str(ctx.exception))

    def test_ajax_plate_lookup_returns_blocked_status(self):
        plate_str = "99 ج 777 - ایران 22"
        BlockedPlate.objects.create(
            license_plate_display=plate_str,
            normalized_plate=normalize_plate(plate_str),
            reason="تخلف باسکول و عدم تطابق وزن",
            blocked_by=self.manager_user,
            is_active=True
        )

        self.client.login(username="operator1", password="password123")
        lookup_url = reverse("weighbridge:ajax_plate_lookup") + f"?plate={plate_str}"
        res = self.client.get(lookup_url)
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertTrue(data.get("is_blocked"))
        self.assertEqual(data.get("block_reason"), "تخلف باسکول و عدم تطابق وزن")
        self.assertEqual(data.get("blocked_by"), "مدیر باسکول")

    def test_ticket_form_rejects_blocked_plate(self):
        plate_str = "44 ق 123 - ایران 33"
        BlockedPlate.objects.create(
            license_plate_display=plate_str,
            normalized_plate=normalize_plate(plate_str),
            reason="دستور قضایی توقیف خودرو",
            blocked_by=self.manager_user,
            is_active=True
        )

        form_data = {
            "license_plate_display": plate_str,
            "plate_part1": "44",
            "plate_letter": "ق",
            "plate_part2": "123",
            "plate_iran": "33",
            "first_weight": "12000",
            "product": str(self.product.id),
            "party": str(self.party.id),
            "origin": str(self.origin.id),
            "operation_type": str(self.op_type.id),
            "weight_mode": WeightMode.EMPTY_FIRST,
        }
        form = TicketCreateForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("license_plate_display", form.errors)
        self.assertTrue(any("لیست سیاه پلاک‌های مسدود" in err for err in form.errors["license_plate_display"]))

    def test_ticket_create_page_contains_blocked_plate_guards(self):
        self.client.login(username="operator1", password="password123")
        res = self.client.get(reverse("weighbridge:ticket_create"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'id="btn-open-confirm-modal"')
        self.assertContains(res, 'setPlateBlockedState')
