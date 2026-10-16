from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from audit.models import AuditLog
from core.jalali import format_jalali_date
from core.models import SystemSetting
from masterdata.models import Product, Party, OperationType, Location, UnloadLocation, VehicleType
from reports.services import ReportService
from weighbridge.models import WeighTicket, TicketStatus


class SystemRegressionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("system_test_admin")
        cls.operator = User.objects.create_user("system_test_operator")
        cls.viewer = User.objects.create_user("system_test_viewer")
        cls.viewer.profile.role = "viewer"
        cls.viewer.profile.save()
        SystemSetting.objects.create(require_driver=False)
        cls.product = Product.objects.create(name="محصول تست")
        cls.party = Party.objects.create(name="طرف حساب تست")
        cls.op_type = OperationType.objects.create(name="ورود بار", direction="inbound")
        cls.origin = Location.objects.create(name="مبدأ تست")
        cls.destination = Location.objects.create(name="مقصد تست")
        cls.unload_loc = UnloadLocation.objects.create(name="جایگاه ۱")
        cls.vehicle_type = VehicleType.objects.create(name="تریلی")
        cls.ticket = WeighTicket.objects.create(serial_number="SYSTEM-1", license_plate_display="12 ع 345 - ایران 67",
            first_weight=12000, second_weight=30000, status=TicketStatus.COMPLETED, first_weight_date=timezone.localdate())

    def setUp(self):
        self.client.force_login(self.admin)
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def test_visible_registration_form_can_submit_with_blank_optional_weights(self):
        response = self.client.get(reverse("weighbridge:ticket_create"))
        self.assertContains(response, 'name="weight_mode"')
        response = self.client.post(reverse("weighbridge:ticket_create"), {
            "weight_mode": "empty_first", "first_weight": "12000", "second_weight": "",
            "load_count": "1", "sent_weight": "", "loss_weight": "", "loss_percent": "",
            "license_plate_display": "", "plate_part1": "98", "plate_letter": "ع", "plate_part2": "765", "plate_iran": "43",
            "freight_amount": "250000",
            "operation_type": self.op_type.pk,
            "party": self.party.pk,
            "product": self.product.pk,
            "origin": self.origin.pk,
            "destination": self.destination.pk,
            "unload_location": self.unload_loc.pk,
            "vehicle_type": self.vehicle_type.pk,
            "driver_name_custom": "راننده تست",
            "driver_mobile_custom": "09123456789",
        })
        self.assertEqual(response.status_code, 302)
        ticket = WeighTicket.objects.latest("id")
        self.assertEqual(ticket.license_plate_display, "98 ع 765 - ایران 43")
        self.assertEqual(ticket.sent_weight, 0)
        self.assertEqual(ticket.freight_amount, 250000)

    def test_form_error_and_copy_preserve_plate_fields(self):
        response = self.client.post(reverse("weighbridge:ticket_create"), {
            "plate_part1": "98", "plate_letter": "ج", "plate_part2": "765", "plate_iran": "43", "first_weight": "-1",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="765"')
        self.assertContains(response, 'value="43"')
        response = self.client.get(reverse("weighbridge:ticket_create"), {"duplicate_from": self.ticket.pk})
        self.assertContains(response, 'value="345"')

    def test_viewer_cannot_register_or_complete_tickets(self):
        self.client.force_login(self.viewer)
        self.api.force_authenticate(self.viewer)
        count = WeighTicket.objects.count()
        self.assertEqual(self.client.post(reverse("weighbridge:ticket_create"), {}).status_code, 302)
        self.assertEqual(self.client.post(reverse("weighbridge:ticket_second_weight", args=[self.ticket.pk]), {"second_weight": 40000}).status_code, 302)
        self.assertEqual(self.api.post("/api/v1/tickets/", {}).status_code, 403)
        self.assertEqual(self.api.post(f"/api/v1/tickets/{self.ticket.pk}/first-weight/", {"weight": 40000}).status_code, 403)
        self.assertEqual(WeighTicket.objects.count(), count)

    def test_cancelled_ticket_cannot_be_reactivated_by_weighing(self):
        WeighTicket.objects.filter(pk=self.ticket.pk).update(status=TicketStatus.CANCELLED)
        response = self.client.post(reverse("weighbridge:ticket_second_weight", args=[self.ticket.pk]), {"second_weight": 40000})
        self.assertEqual(response.status_code, 302)
        for action in ("first-weight", "second-weight", "complete"):
            with self.subTest(action=action):
                self.assertEqual(self.api.post(f"/api/v1/tickets/{self.ticket.pk}/{action}/", {"weight": 40000}).status_code, 400)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.CANCELLED)
        self.assertEqual(self.ticket.second_weight, 30000)

    def test_physical_ticket_deletion_is_disabled(self):
        response = self.api.delete(f"/api/v1/tickets/{self.ticket.pk}/")
        self.assertEqual(response.status_code, 405)
        self.assertTrue(WeighTicket.objects.filter(pk=self.ticket.pk).exists())

    def test_api_invalid_numbers_are_rejected_and_freight_is_saved(self):
        for field, value in (("first_weight", "-1"), ("second_weight", "-1"), ("loss_percent", "101"), ("sent_weight", "-10")):
            with self.subTest(field=field):
                response = self.api.post("/api/v1/tickets/", {"license_plate_display": "98 ع 765 - ایران 43", field: value})
                self.assertEqual(response.status_code, 400)
        response = self.api.post("/api/v1/tickets/", {"license_plate_display": "98 ع 765 - ایران 43", "first_weight": 12000, "freight_amount": "1250000"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Decimal(response.data["freight_amount"]), Decimal("1250000"))

    def test_api_correction_masterdata_and_invalid_values(self):
        in_flight_ticket = WeighTicket.objects.create(
            serial_number="SYSTEM-INFLIGHT-1",
            license_plate_display="12 ع 345 - ایران 67",
            first_weight=12000,
            status=TicketStatus.WAITING_SECOND,
            first_weight_date=timezone.localdate()
        )
        url = f"/api/v1/tickets/{in_flight_ticket.pk}/correct/"
        response = self.api.post(url, {"field": "product", "new_value": str(self.product.pk), "reason": "اصلاح کالا"})
        self.assertEqual(response.status_code, 200)
        in_flight_ticket.refresh_from_db()
        self.assertEqual(in_flight_ticket.product, self.product)
        for field, value in (("product", "abc"), ("first_weight", "NaN"), ("loss_percent", "-1")):
            with self.subTest(field=field):
                self.assertEqual(self.api.post(url, {"field": field, "new_value": value, "reason": "اصلاح آزمایشی"}).status_code, 400)
        self.assertEqual(self.api.post("/api/v1/tickets/999999/first-weight/", {"weight": 12000}).status_code, 404)

    def test_cancellation_audit_keeps_previous_status(self):
        self.assertEqual(self.api.post(f"/api/v1/tickets/{self.ticket.pk}/cancel/", {"reason": "ابطال آزمایشی"}).status_code, 200)
        audit = AuditLog.objects.get(model_name="WeighTicket", record_id=str(self.ticket.pk), action="cancel")
        self.assertEqual(audit.old_values["status"], TicketStatus.COMPLETED)

    def test_date_filter_uses_weighing_date_and_excludes_cancelled(self):
        old_day = timezone.localdate() - timedelta(days=10)
        WeighTicket.objects.filter(pk=self.ticket.pk).update(first_weight_date=old_day)
        qs = ReportService.filter_tickets({"start_date": format_jalali_date(timezone.localdate())})
        self.assertFalse(qs.exists())
        WeighTicket.objects.filter(pk=self.ticket.pk).update(status=TicketStatus.CANCELLED)
        self.assertFalse(ReportService.filter_tickets({}).exists())
        self.assertEqual(ReportService.filter_tickets({"status": "cancelled"}).count(), 1)

    def test_invalid_report_filters_do_not_crash_or_export(self):
        for path in (reverse("reports:report_builder"), reverse("reports:preset_report_view", args=["daily"])):
            for params in ({"per_page": "wrong"}, {"product": "abc"}, {"min_net": "NaN"}, {"start_date": "invalid"}, {"start_time": "25:99"}):
                with self.subTest(path=path, params=params):
                    response = self.client.get(path, {**params, "export": "excel"})
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, "خطا در فیلتر گزارش")
                    self.assertNotIn("Content-Disposition", response)

    def test_pagination_does_not_keep_stale_page_parameter(self):
        WeighTicket.objects.bulk_create([WeighTicket(serial_number=f"PAGE-{n}", license_plate_display=f"P{n}") for n in range(55)])
        for path in (reverse("reports:report_builder"), reverse("reports:preset_report_view", args=["sent_vs_net"])):
            response = self.client.get(path, {"page": "2"})
            self.assertEqual(response.context["page_obj"].number, 2)
            self.assertNotIn("page", response.context["params"])
            self.assertContains(response, "?page=3")

    def test_status_toggle_requires_post_and_csrf(self):
        url = reverse("masterdata:product_toggle", args=[self.product.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.product.refresh_from_db()
        self.assertTrue(self.product.is_active)
        strict_client = Client(enforce_csrf_checks=True)
        strict_client.force_login(self.admin)
        self.assertEqual(strict_client.post(url).status_code, 403)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.product.refresh_from_db()
        self.assertFalse(self.product.is_active)
        user_url = reverse("accounts:user_toggle_status", args=[self.operator.pk])
        self.assertEqual(self.client.get(user_url).status_code, 405)
        self.operator.refresh_from_db()
        self.assertTrue(self.operator.is_active)
