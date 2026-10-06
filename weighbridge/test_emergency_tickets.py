from django.test import TestCase, Client
from django.contrib.auth.models import User
from decimal import Decimal
from django.urls import reverse
from weighbridge.models import EmergencyWeighTicket, EmergencyTicketStatus, WeighTicket
from accounts.models import UserProfile, RoleChoices


class EmergencyWeighTicketTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username="operator_user", password="test-password")
        self.client = Client()
        self.client.force_login(self.user)

    def test_create_emergency_ticket_both_weights(self):
        """Test creating an emergency ticket directly with both gross and tare."""
        url = reverse("weighbridge:emergency_ticket_create")
        data = {
            "company_name": "شرکت پتروشیمی زاگرس",
            "driver_name": "علی محمدی",
            "driver_mobile": "09123456789",
            "license_plate": "12 ج 345 - ایران 67",
            "gross_weight": "38500",
            "tare_weight": "14200",
            "weight_date_jalali": "1405/07/15",
            "weight_time_str": "14:30",
            "notes": "توزین اضطراری به علت خرابی باسکول شرکت مجاور",
            "save_only": "1",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)

        ticket = EmergencyWeighTicket.objects.latest("id")
        self.assertEqual(ticket.driver_name, "علی محمدی")
        self.assertEqual(ticket.company_name, "شرکت پتروشیمی زاگرس")
        self.assertEqual(ticket.gross_weight, Decimal("38500"))
        self.assertEqual(ticket.tare_weight, Decimal("14200"))
        self.assertEqual(ticket.net_weight, Decimal("24300"))
        self.assertEqual(ticket.status, EmergencyTicketStatus.COMPLETED)
        self.assertTrue(ticket.serial_number.startswith("EXT-"))

        # Verify it DOES NOT pollute the factory's regular tickets
        self.assertEqual(WeighTicket.objects.count(), 0)

    def test_create_emergency_ticket_with_iran_plate_component(self):
        """Test submitting emergency ticket with standard 4-part Iran plate widget."""
        url = reverse("weighbridge:emergency_ticket_create")
        data = {
            "company_name": "شرکت معدنی البرز",
            "driver_name": "سهراب کریمی",
            "driver_mobile": "09121234567",
            "plate_part1": "12",
            "plate_letter": "ج",
            "plate_part2": "345",
            "plate_iran": "67",
            "license_plate_display": "12 ج 345 - ایران 67",
            "gross_weight": "40000",
            "tare_weight": "16000",
            "weight_date_jalali": "1405/07/15",
            "weight_time_str": "15:00",
            "save_only": "1",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)

        ticket = EmergencyWeighTicket.objects.latest("id")
        self.assertEqual(ticket.license_plate, "12 ج 345 - ایران 67")
        self.assertEqual(ticket.net_weight, Decimal("24000"))
        self.assertEqual(ticket.status, EmergencyTicketStatus.COMPLETED)


    def test_create_emergency_ticket_first_weight_then_second_weight(self):
        """Test two-step workflow: first gross weight, then complete second weight."""
        url = reverse("weighbridge:emergency_ticket_create")
        data = {
            "company_name": "شرکت حمل و نقل آسیا",
            "driver_name": "رضا مرادی",
            "driver_mobile": "09181112233",
            "license_plate": "55 ب 789 - ایران 21",
            "gross_weight": "42000",
            "tare_weight": "0",
            "weight_date_jalali": "1405/07/15",
            "weight_time_str": "10:15",
            "save_only": "1",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)

        ticket = EmergencyWeighTicket.objects.latest("id")
        self.assertEqual(ticket.status, EmergencyTicketStatus.WAITING_SECOND)
        self.assertEqual(ticket.gross_weight, Decimal("42000"))

        # Complete second weight
        second_url = reverse("weighbridge:emergency_ticket_second_weight", args=[ticket.pk])
        sec_data = {
            "second_weight": "15000",
            "second_weight_date_jalali": "1405/07/15",
            "second_weight_time_str": "12:45",
            "notes": "وزن خالی پس از تخلیه ثبت شد",
            "save_only": "1",
        }
        res_sec = self.client.post(second_url, sec_data)
        self.assertEqual(res_sec.status_code, 302)

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, EmergencyTicketStatus.COMPLETED)
        self.assertEqual(ticket.tare_weight, Decimal("15000"))
        self.assertEqual(ticket.net_weight, Decimal("27000"))

    def test_emergency_ticket_list_and_search(self):
        """Test searching and filtering in emergency tickets list."""
        ticket1 = EmergencyWeighTicket.objects.create(
            serial_number="EXT-1001",
            company_name="فولاد کویر",
            driver_name="محسن حسینی",
            driver_mobile="09350001122",
            license_plate="77 ع 111 - ایران 44",
            gross_weight=Decimal("30000"),
            tare_weight=Decimal("10000"),
            weight_date="2026-10-06",
            status=EmergencyTicketStatus.COMPLETED,
        )
        ticket2 = EmergencyWeighTicket.objects.create(
            serial_number="EXT-1002",
            company_name="سیمان تهران",
            driver_name="قاسم کریمی",
            driver_mobile="09129998877",
            license_plate="88 د 222 - ایران 55",
            gross_weight=Decimal("25000"),
            tare_weight=Decimal("0"),
            weight_date="2026-10-06",
            status=EmergencyTicketStatus.WAITING_SECOND,
        )

        list_url = reverse("weighbridge:emergency_ticket_list")
        response = self.client.get(list_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "محسن حسینی")
        self.assertContains(response, "قاسم کریمی")

        # Search by driver
        res_search = self.client.get(list_url, {"q": "محسن"})
        self.assertContains(res_search, "محسن حسینی")
        self.assertNotContains(res_search, "قاسم کریمی")

        # Filter by status
        res_status = self.client.get(list_url, {"status": "waiting_second"})
        self.assertContains(res_status, "قاسم کریمی")
        self.assertNotContains(res_status, "محسن حسینی")

    def test_emergency_ticket_print_view(self):
        """Test print view rendering A5, A4, and POS."""
        ticket = EmergencyWeighTicket.objects.create(
            serial_number="EXT-1001",
            company_name="آریا شیمی",
            driver_name="حسین اکبری",
            driver_mobile="09121113344",
            license_plate="23 ج 456 - ایران 11",
            gross_weight=Decimal("35000"),
            tare_weight=Decimal("12000"),
            weight_date="2026-10-06",
            status=EmergencyTicketStatus.COMPLETED,
        )
        print_url = reverse("weighbridge:emergency_ticket_print", args=[ticket.pk])

        for template in ("a5", "a4", "pos"):
            res = self.client.get(print_url, {"template": template})
            self.assertEqual(res.status_code, 200)
            self.assertContains(res, "EXT-1001")
            self.assertContains(res, "حسین اکبری")
            self.assertContains(res, "35000")
            self.assertContains(res, "12000")
            self.assertContains(res, "23000")

    def test_emergency_ticket_cancellation(self):
        """Test canceling an emergency ticket with a reason."""
        ticket = EmergencyWeighTicket.objects.create(
            serial_number="EXT-1001",
            company_name="شرکت کاوه",
            driver_name="سعید نجفی",
            gross_weight=Decimal("20000"),
            tare_weight=Decimal("8000"),
            weight_date="2026-10-06",
            status=EmergencyTicketStatus.COMPLETED,
        )
        cancel_url = reverse("weighbridge:emergency_ticket_cancel", args=[ticket.pk])
        res = self.client.post(cancel_url, {"cancellation_reason": "خطا در ورود مشخصات توسط راننده"})
        self.assertEqual(res.status_code, 302)

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, EmergencyTicketStatus.CANCELLED)
        self.assertEqual(ticket.cancellation_reason, "خطا در ورود مشخصات توسط راننده")
        self.assertEqual(ticket.cancelled_by, self.user)
