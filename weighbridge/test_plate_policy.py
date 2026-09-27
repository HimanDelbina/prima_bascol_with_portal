from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import connection, connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from audit.models import AuditLog
from core.jalali import format_jalali_date
from core.models import SystemSetting
from weighbridge.models import WeighTicket, TicketStatus, PlateRegistrationException
from weighbridge.plate_policy import DailyPlatePolicy, normalize_plate


class DailyPlatePolicyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.operator = User.objects.create_user("plate_operator")
        cls.supervisor = User.objects.create_user("plate_supervisor")
        cls.supervisor.profile.role = "weighbridge_manager"
        cls.supervisor.profile.save()
        cls.today = timezone.localdate()
        cls.plate = "12 ع 345 - ایران 67"
        cls.first = WeighTicket.objects.create(serial_number="PLATE-1", license_plate_display=cls.plate,
                                               first_weight_date=cls.today, first_weight=12000)
        SystemSetting.objects.create(require_driver=False)

    def setUp(self):
        self.client.force_login(self.operator)
        self.payload = {"license_plate_display": self.plate, "first_weight": "12000",
                        "weight_mode": "empty_first", "load_count": "1", "sent_weight": "0",
                        "loss_weight": "0", "loss_percent": "0"}

    def grant(self):
        self.client.force_login(self.supervisor)
        response = self.client.post(reverse("weighbridge:plate_exceptions"), {
            "license_plate_display": "۱۲ ع ۳۴۵ - ایران ۶۷", "reason": "حمل چند سرویس در روز",
        })
        self.assertEqual(response.status_code, 302)
        return PlateRegistrationException.objects.get()

    def test_same_day_duplicate_is_rejected_for_all_digit_formats(self):
        for plate in (self.plate, "۱۲ع۳۴۵ایران۶۷", "١٢ ع ٣٤٥ - ايران ٦٧"):
            with self.subTest(plate=plate):
                response = self.client.post(reverse("weighbridge:ticket_create"), {**self.payload, "license_plate_display": plate})
                self.assertEqual(response.status_code, 200)
                self.assertIn("license_plate_display", response.context["form"].errors)
                self.assertContains(response, "PLATE-1")
        self.assertEqual(WeighTicket.objects.count(), 1)

    def test_different_day_is_allowed_and_invalid_date_is_rejected(self):
        tomorrow = format_jalali_date(self.today + timedelta(days=1))
        response = self.client.post(reverse("weighbridge:ticket_create"), {**self.payload, "first_weight_date_jalali": tomorrow})
        self.assertEqual(response.status_code, 302)
        response = self.client.post(reverse("weighbridge:ticket_create"), {**self.payload, "first_weight_date_jalali": "wrong"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("first_weight_date_jalali", response.context["form"].errors)

    def test_supervisor_grant_allows_operator_and_is_audited(self):
        exception = self.grant()
        self.client.force_login(self.operator)
        response = self.client.post(reverse("weighbridge:ticket_create"), self.payload)
        self.assertEqual(response.status_code, 302)
        ticket = WeighTicket.objects.latest("id")
        self.assertEqual(ticket.duplicate_exception_id, exception.pk)
        self.assertEqual(exception.approved_by, self.supervisor)
        self.assertTrue(AuditLog.objects.filter(model_name="PlateRegistrationException", record_id=str(exception.pk), user=self.supervisor).exists())
        self.assertTrue(AuditLog.objects.filter(model_name="WeighTicket", record_id=str(ticket.pk),
                                               new_values__duplicate_exception_id=exception.pk).exists())

    def test_deactivation_blocks_future_duplicates_but_keeps_existing_second_weight(self):
        exception = self.grant()
        self.client.post(reverse("weighbridge:plate_exceptions"), {"action": "deactivate", "exception_id": exception.pk})
        response = self.client.post(reverse("weighbridge:ticket_create"), self.payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("license_plate_display", response.context["form"].errors)
        response = self.client.post(reverse("weighbridge:ticket_second_weight", args=[self.first.pk]), {
            "second_weight": "30000", "sent_weight": "18000", "loss_percent": "0",
        })
        self.assertEqual(response.status_code, 302)
        self.first.refresh_from_db()
        self.assertEqual(self.first.status, TicketStatus.COMPLETED)

    def test_operator_cannot_grant_or_toggle_exception(self):
        url = reverse("weighbridge:plate_exceptions")
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {"license_plate_display": self.plate, "reason": "مجوز غیرمجاز"}).status_code, 403)
        exception = self.grant()
        self.client.force_login(self.operator)
        self.assertEqual(self.client.post(url, {"action": "deactivate", "exception_id": exception.pk}).status_code, 403)
        exception.refresh_from_db()
        self.assertTrue(exception.is_active)

    def test_missing_reason_rejected_and_equivalent_plate_updates_one_grant(self):
        self.client.force_login(self.supervisor)
        url = reverse("weighbridge:plate_exceptions")
        response = self.client.post(url, {"license_plate_display": self.plate, "reason": ""})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PlateRegistrationException.objects.exists())
        self.grant()
        self.client.post(url, {"license_plate_display": self.plate, "reason": "اصلاح دلیل مجوز"})
        self.assertEqual(PlateRegistrationException.objects.count(), 1)

    def test_grant_exception_using_iran_plate_component_parts(self):
        self.client.force_login(self.supervisor)
        url = reverse("weighbridge:plate_exceptions")
        response = self.client.post(url, {
            "plate_part1": "34",
            "plate_letter": "ب",
            "plate_part2": "567",
            "plate_iran": "89",
            "reason": "تست ورود پلاک با اجزای کامپوننت ملی",
        })
        self.assertEqual(response.status_code, 302)
        exc = PlateRegistrationException.objects.filter(license_plate_display="34 ب 567 - ایران 89").first()
        self.assertIsNotNone(exc)
        self.assertTrue(exc.is_active)
        self.assertEqual(exc.approved_by, self.supervisor)


    def test_cancelled_ticket_does_not_prevent_replacement(self):
        WeighTicket.objects.filter(pk=self.first.pk).update(status=TicketStatus.CANCELLED)
        self.assertEqual(self.client.post(reverse("weighbridge:ticket_create"), self.payload).status_code, 302)

    def test_edit_to_conflicting_plate_is_rejected(self):
        self.client.force_login(self.supervisor)
        other = WeighTicket.objects.create(serial_number="OTHER", license_plate_display="99 ع 999 - ایران 99", first_weight=12000, first_weight_date=self.today)
        response = self.client.post(reverse("weighbridge:ticket_edit", args=[other.pk]), {
            **self.payload, "manager_reason": "اصلاح شماره پلاک",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("license_plate_display", response.context["form"].errors)
        other.refresh_from_db()
        self.assertNotEqual(other.license_plate_display, self.plate)

    def test_api_enforces_rule_and_cannot_forge_exception(self):
        api = APIClient()
        api.force_authenticate(self.operator)
        response = api.post("/api/v1/tickets/", {**self.payload, "duplicate_exception": 1})
        self.assertEqual(response.status_code, 400)
        self.assertIn("license_plate_display", response.data["error"]["fields"])
        self.grant()
        self.assertEqual(api.post("/api/v1/tickets/", self.payload).status_code, 201)

    def test_api_changing_date_cannot_bypass_rule(self):
        other = WeighTicket.objects.create(serial_number="OTHER-DAY", license_plate_display=self.plate,
            first_weight=12000, first_weight_date=self.today - timedelta(days=1))
        api = APIClient()
        api.force_authenticate(self.supervisor)
        response = api.post(f"/api/v1/tickets/{other.pk}/first-weight/", {"weight": 13000, "date": str(self.today)})
        self.assertEqual(response.status_code, 400)
        other.refresh_from_db()
        self.assertEqual(other.first_weight_date, self.today - timedelta(days=1))

    def test_model_form_validation_for_admin_blocks_duplicates(self):
        from django.forms import modelform_factory
        Form = modelform_factory(WeighTicket, fields=["serial_number", "license_plate_display", "first_weight_date"])
        form = Form({"serial_number": "ADMIN-NEW", "license_plate_display": self.plate, "first_weight_date": self.today})
        self.assertFalse(form.is_valid())
        self.assertIn("license_plate_display", form.errors)

    def test_historical_duplicates_can_complete_but_no_new_duplicate(self):
        historical = WeighTicket.objects.create(serial_number="HISTORICAL", license_plate_display=self.plate, first_weight=12000, first_weight_date=self.today)
        historical.second_weight = 30000
        DailyPlatePolicy.save(historical, user=self.supervisor)
        historical.refresh_from_db()
        self.assertEqual(historical.second_weight, 30000)
        with self.assertRaises(ValidationError):
            DailyPlatePolicy.save(WeighTicket(serial_number="NEW", license_plate_display=self.plate, first_weight_date=self.today))


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locks")
class ConcurrentDailyPlateTests(TransactionTestCase):
    def test_simultaneous_registration_only_creates_one_ticket(self):
        SystemSetting.objects.create()
        barrier = Barrier(2)

        def create(plate):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                ticket = WeighTicket(license_plate_display=plate, first_weight=12000, first_weight_date=timezone.localdate())
                try:
                    DailyPlatePolicy.save(ticket, assign_serial=True)
                    return "saved"
                except ValidationError:
                    return "duplicate"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(create, "12 ع 345 - ایران 67")
            second = pool.submit(create, "۱۲ع۳۴۵ایران۶۷")
            results = [first.result(timeout=20), second.result(timeout=20)]
        self.assertCountEqual(results, ["saved", "duplicate"])
        self.assertEqual(WeighTicket.objects.count(), 1)
