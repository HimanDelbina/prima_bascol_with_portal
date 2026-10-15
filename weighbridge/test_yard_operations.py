import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile, RoleChoices
from masterdata.models import Product, Party, Driver, Vehicle, VehicleType, OperationType
from weighbridge.models import WeighTicket, TicketStatus, WeightMode


class YardOperationsTests(TestCase):
    """
    Comprehensive verification suite for Phase 2.3: Professional Yard Operations
    and Vehicle Queue Management (Prima Bascol).
    """

    def setUp(self):
        self.client = Client()

        # Users and Profiles
        self.operator_user = User.objects.create_user(
            username="yard_operator", password="password123", first_name="علی", last_name="صالحی"
        )
        self.operator_profile = self.operator_user.profile
        self.operator_profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        self.operator_profile.save()

        self.supervisor_user = User.objects.create_user(
            username="yard_supervisor", password="password123", first_name="مهدی", last_name="ناظمی"
        )
        self.supervisor_profile = self.supervisor_user.profile
        self.supervisor_profile.role = RoleChoices.WEIGHBRIDGE_MANAGER
        self.supervisor_profile.save()

        self.unprivileged_user = User.objects.create_user(
            username="viewer_user", password="password123", first_name="مشاهده", last_name="گر"
        )
        self.unprivileged_profile = self.unprivileged_user.profile
        self.unprivileged_profile.role = RoleChoices.VIEWER
        self.unprivileged_profile.save()

        # Master Data
        self.product_iron = Product.objects.create(name="میلگرد ۱۴ A3", code="P-101", is_active=True)
        self.product_scrap = Product.objects.create(name="قراضه سنگین ۱", code="P-102", is_active=True)
        self.party_foolad = Party.objects.create(name="فولاد مبارکه اصفهان", code="C-201", is_active=True)
        self.party_zobahan = Party.objects.create(name="ذوب آهن اصفهان", code="C-202", is_active=True)

        self.driver_ali = Driver.objects.create(full_name="علی رستمی", mobile="09121112233", is_active=True)
        self.driver_hasan = Driver.objects.create(full_name="حسن میرزایی", mobile="09123334455", is_active=True)

        self.op_buy = OperationType.objects.create(name="خرید مواد اولیه", direction="inbound", is_active=True)
        self.op_sale = OperationType.objects.create(name="فروش محصول", direction="outbound", is_active=True)

        now = timezone.now()

        # Ticket 1: Normal Dwell (20 minutes ago)
        self.t1 = WeighTicket.objects.create(
            serial_number="WB-3001",
            status=TicketStatus.WAITING_SECOND,
            weight_mode=WeightMode.EMPTY_FIRST,
            license_plate_display="12 ع 345 ایران 67",
            driver=self.driver_ali,
            party=self.party_foolad,
            product=self.product_iron,
            operation_type=self.op_sale,
            waybill_number="BL-9001",
            first_weight=Decimal("14500.00"),
            first_weight_date=now.date(),
            first_weight_time=(now - timedelta(minutes=20)).time(),
            first_weight_operator=self.operator_user,
        )
        WeighTicket.objects.filter(pk=self.t1.pk).update(created_at=now - timedelta(minutes=20))
        self.t1.refresh_from_db()

        # Ticket 2: Warning Dwell (90 minutes ago)
        self.t2 = WeighTicket.objects.create(
            serial_number="WB-3002",
            status=TicketStatus.FIRST_REGISTERED,
            weight_mode=WeightMode.FULL_FIRST,
            license_plate_display="44 ب 678 ایران 22",
            driver=self.driver_hasan,
            party=self.party_zobahan,
            product=self.product_scrap,
            operation_type=self.op_buy,
            waybill_number="BL-9002",
            first_weight=Decimal("38200.00"),
            first_weight_date=now.date(),
            first_weight_time=(now - timedelta(minutes=90)).time(),
            first_weight_operator=self.operator_user,
        )
        WeighTicket.objects.filter(pk=self.t2.pk).update(created_at=now - timedelta(minutes=90))
        self.t2.refresh_from_db()

        # Ticket 3: Overdue Dwell (240 minutes = 4 hours ago)
        self.t3 = WeighTicket.objects.create(
            serial_number="WB-3003",
            status=TicketStatus.WAITING_SECOND,
            weight_mode=WeightMode.EMPTY_FIRST,
            license_plate_display="77 ج 123 ایران 88",
            driver_name_custom="کامران ابراهیمی",
            driver_mobile_custom="09135556677",
            party=self.party_foolad,
            product=self.product_iron,
            operation_type=self.op_sale,
            waybill_number="BL-9003",
            first_weight=Decimal("15100.00"),
            first_weight_date=now.date(),
            first_weight_time=(now - timedelta(minutes=240)).time(),
            first_weight_operator=self.operator_user,
        )
        WeighTicket.objects.filter(pk=self.t3.pk).update(created_at=now - timedelta(minutes=240))
        self.t3.refresh_from_db()

        # Ticket 4: Completed (should NOT appear in yard board)
        self.t_completed = WeighTicket.objects.create(
            serial_number="WB-3004",
            status=TicketStatus.COMPLETED,
            weight_mode=WeightMode.EMPTY_FIRST,
            license_plate_display="99 د 999 ایران 11",
            driver=self.driver_ali,
            party=self.party_foolad,
            product=self.product_iron,
            first_weight=Decimal("14200.00"),
            second_weight=Decimal("39500.00"),
            gross_weight=Decimal("39500.00"),
            tare_weight=Decimal("14200.00"),
            net_weight=Decimal("25300.00"),
            final_weight=Decimal("25300.00"),
            first_weight_date=now.date(),
            first_weight_time=now.time(),
            second_weight_date=now.date(),
            second_weight_time=now.time(),
        )

        # Ticket 5: Cancelled (should NOT appear in yard board)
        self.t_cancelled = WeighTicket.objects.create(
            serial_number="WB-3005",
            status=TicketStatus.CANCELLED,
            weight_mode=WeightMode.EMPTY_FIRST,
            license_plate_display="33 ل 333 ایران 33",
            first_weight=Decimal("15000.00"),
        )

    def test_permission_enforcement(self):
        """Anonymous and unprivileged users must be denied access."""
        url = reverse("weighbridge:trucks_in_yard")

        # 1. Anonymous -> redirect to login
        res_anon = self.client.get(url)
        self.assertEqual(res_anon.status_code, 302)
        self.assertIn("/accounts/login/", res_anon.url)

        # 2. Unprivileged viewer -> redirect to dashboard with error
        self.client.force_login(self.unprivileged_user)
        res_viewer = self.client.get(url)
        self.assertEqual(res_viewer.status_code, 302)
        self.assertIn("/dashboard/", res_viewer.url)

        # 3. Weighbridge Operator -> 200 OK
        self.client.force_login(self.operator_user)
        res_op = self.client.get(url)
        self.assertEqual(res_op.status_code, 200)

        # 4. Supervisor -> 200 OK
        self.client.force_login(self.supervisor_user)
        res_sup = self.client.get(url)
        self.assertEqual(res_sup.status_code, 200)

    def test_yard_initial_counts_and_exclusion_of_completed(self):
        """Yard board must strictly include open tickets (3) and exclude completed/cancelled (2)."""
        self.client.force_login(self.operator_user)
        res = self.client.get(reverse("weighbridge:trucks_in_yard"))
        self.assertEqual(res.status_code, 200)

        self.assertEqual(res.context["total_yard_count"], 3)
        self.assertEqual(res.context["yard_normal_count"], 1)
        self.assertEqual(res.context["yard_warning_count"], 1)
        self.assertEqual(res.context["yard_overdue_count"], 1)

        # Verify completed and cancelled tickets are absent from HTML
        self.assertContains(res, "WB-3001")
        self.assertContains(res, "WB-3002")
        self.assertContains(res, "WB-3003")
        self.assertNotContains(res, "WB-3004")
        self.assertNotContains(res, "WB-3005")

    def test_search_by_license_plate_persian_and_english(self):
        """Search by Iranian plate must work with Persian digits, English digits, and normalized formats."""
        self.client.force_login(self.operator_user)
        url = reverse("weighbridge:trucks_in_yard")

        # Persian digits: "۱۲ ع ۳۴۵"
        res_fa = self.client.get(url, {"q": "۱۲ ع ۳۴۵"})
        self.assertEqual(res_fa.status_code, 200)
        self.assertEqual(res_fa.context["count"], 1)
        self.assertEqual(res_fa.context["items"][0]["ticket"].serial_number, "WB-3001")

        # English digits: "12ع345"
        res_en = self.client.get(url, {"q": "12ع345"})
        self.assertEqual(res_en.status_code, 200)
        self.assertEqual(res_en.context["count"], 1)
        self.assertEqual(res_en.context["items"][0]["ticket"].serial_number, "WB-3001")

        # Normalized full plate: "12ع34567"
        res_norm = self.client.get(url, {"q": "12ع34567"})
        self.assertEqual(res_norm.status_code, 200)
        self.assertEqual(res_norm.context["count"], 1)
        self.assertEqual(res_norm.context["items"][0]["ticket"].serial_number, "WB-3001")

    def test_search_by_driver_name_and_custom_name(self):
        """Search by driver name must resolve both FK Driver and custom driver name."""
        self.client.force_login(self.operator_user)
        url = reverse("weighbridge:trucks_in_yard")

        # Masterdata FK Driver
        res_fk = self.client.get(url, {"q": "علی رستمی"})
        self.assertEqual(res_fk.status_code, 200)
        self.assertEqual(res_fk.context["count"], 1)
        self.assertEqual(res_fk.context["items"][0]["ticket"].serial_number, "WB-3001")

        # Custom Driver Name
        res_custom = self.client.get(url, {"q": "کامران ابراهیمی"})
        self.assertEqual(res_custom.status_code, 200)
        self.assertEqual(res_custom.context["count"], 1)
        self.assertEqual(res_custom.context["items"][0]["ticket"].serial_number, "WB-3003")

    def test_search_by_serial_number_persian_and_english(self):
        """Search by serial number must resolve with prefix, English digits, and Persian digits."""
        self.client.force_login(self.operator_user)
        url = reverse("weighbridge:trucks_in_yard")

        # Full serial string
        res1 = self.client.get(url, {"q": "WB-3002"})
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.context["count"], 1)
        self.assertEqual(res1.context["items"][0]["ticket"].serial_number, "WB-3002")

        # English digits only
        res2 = self.client.get(url, {"q": "3002"})
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.context["count"], 1)
        self.assertEqual(res2.context["items"][0]["ticket"].serial_number, "WB-3002")

        # Persian digits
        res3 = self.client.get(url, {"q": "۳۰۰۲"})
        self.assertEqual(res3.status_code, 200)
        self.assertEqual(res3.context["count"], 1)
        self.assertEqual(res3.context["items"][0]["ticket"].serial_number, "WB-3002")

    def test_search_by_waybill_number(self):
        """Search by waybill number must resolve accurately."""
        self.client.force_login(self.operator_user)
        url = reverse("weighbridge:trucks_in_yard")

        res = self.client.get(url, {"q": "BL-9003"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["count"], 1)
        self.assertEqual(res.context["items"][0]["ticket"].serial_number, "WB-3003")

        # Partial digits in Persian
        res_fa = self.client.get(url, {"q": "۹۰۰۳"})
        self.assertEqual(res_fa.status_code, 200)
        self.assertEqual(res_fa.context["count"], 1)
        self.assertEqual(res_fa.context["items"][0]["ticket"].serial_number, "WB-3003")

    def test_dwell_status_filtering(self):
        """Filtering by dwell_status (normal, warning, overdue) must correctly isolate queue tiers."""
        self.client.force_login(self.operator_user)
        url = reverse("weighbridge:trucks_in_yard")

        # 1. Normal (< 60m) -> Ticket 1
        res_normal = self.client.get(url, {"dwell_status": "normal"})
        self.assertEqual(res_normal.status_code, 200)
        self.assertEqual(res_normal.context["count"], 1)
        self.assertEqual(res_normal.context["items"][0]["ticket"].serial_number, "WB-3001")
        self.assertEqual(res_normal.context["items"][0]["dwell_status"], "normal")

        # 2. Warning (60m - 180m) -> Ticket 2
        res_warning = self.client.get(url, {"dwell_status": "warning"})
        self.assertEqual(res_warning.status_code, 200)
        self.assertEqual(res_warning.context["count"], 1)
        self.assertEqual(res_warning.context["items"][0]["ticket"].serial_number, "WB-3002")
        self.assertEqual(res_warning.context["items"][0]["dwell_status"], "warning")

        # 3. Overdue (>= 180m) -> Ticket 3
        res_overdue = self.client.get(url, {"dwell_status": "overdue"})
        self.assertEqual(res_overdue.status_code, 200)
        self.assertEqual(res_overdue.context["count"], 1)
        self.assertEqual(res_overdue.context["items"][0]["ticket"].serial_number, "WB-3003")
        self.assertEqual(res_overdue.context["items"][0]["dwell_status"], "overdue")

        # 4. All -> All 3 tickets
        res_all = self.client.get(url, {"dwell_status": "all"})
        self.assertEqual(res_all.status_code, 200)
        self.assertEqual(res_all.context["count"], 3)

    def test_ajax_auto_refresh_endpoint(self):
        """AJAX requests must return structured JSON with live counters and partial HTML table."""
        self.client.force_login(self.operator_user)
        url = reverse("weighbridge:trucks_in_yard")

        response = self.client.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")

        data = json.loads(response.content.decode("utf-8"))
        self.assertTrue(data["success"])
        self.assertEqual(data["total_yard_count"], 3)
        self.assertEqual(data["yard_normal_count"], 1)
        self.assertEqual(data["yard_warning_count"], 1)
        self.assertEqual(data["yard_overdue_count"], 1)
        self.assertEqual(data["filtered_count"], 3)
        self.assertIn("html", data)
        self.assertIn("items", data)
        self.assertEqual(len(data["items"]), 3)

        # Verify item fields in JSON
        first_item = data["items"][0]
        self.assertIn("serial_number", first_item)
        self.assertIn("second_weight_url", first_item)
        self.assertIn("dwell_status", first_item)
        self.assertIn("duration_str", first_item)

    def test_concurrent_ticket_completion_updates_yard(self):
        """Completing a ticket removes it from the yard on the next AJAX refresh without full reload."""
        self.client.force_login(self.operator_user)
        url = reverse("weighbridge:trucks_in_yard")

        # Initial yard check
        res1 = self.client.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        data1 = json.loads(res1.content.decode("utf-8"))
        self.assertEqual(data1["total_yard_count"], 3)

        # Another station completes WB-3001
        self.t1.status = TicketStatus.COMPLETED
        self.t1.second_weight = Decimal("39000.00")
        self.t1.save(update_fields=["status", "second_weight"])

        # Next automatic polling response
        res2 = self.client.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        data2 = json.loads(res2.content.decode("utf-8"))
        self.assertEqual(data2["total_yard_count"], 2)
        self.assertEqual(data2["yard_normal_count"], 0)  # t1 was the normal one
        self.assertEqual(data2["yard_warning_count"], 1)
        self.assertEqual(data2["yard_overdue_count"], 1)

        serials = [it["serial_number"] for it in data2["items"]]
        self.assertNotIn("WB-3001", serials)
        self.assertIn("WB-3002", serials)
        self.assertIn("WB-3003", serials)

    def test_second_weighing_navigation_and_filter_preservation(self):
        """Action button to second weighing must link correctly and preserve query parameters."""
        self.client.force_login(self.operator_user)
        url = reverse("weighbridge:trucks_in_yard") + "?dwell_status=warning"

        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

        # The HTML should contain the second weighing link with encoded return url
        expected_second_url = reverse("weighbridge:ticket_second_weight", args=[self.t2.id])
        self.assertContains(res, expected_second_url)

        # Access second weight view with next parameter
        sec_weight_url = f"{expected_second_url}?next={url}"
        res_sec = self.client.get(sec_weight_url)
        self.assertEqual(res_sec.status_code, 200)
        # Verify return link on second weight page points back to filtered yard url
        self.assertContains(res_sec, url)

    def test_ordering_behavior(self):
        """Ordering by longest_wait (FIFO default) vs newest must sort correctly."""
        self.client.force_login(self.operator_user)
        url = reverse("weighbridge:trucks_in_yard")

        # 1. longest_wait (oldest first -> t3 arrived 4h ago, t2 arrived 90m ago, t1 arrived 20m ago)
        res_longest = self.client.get(url, {"order_by": "longest_wait"})
        serials_longest = [item["ticket"].serial_number for item in res_longest.context["items"]]
        self.assertEqual(serials_longest, ["WB-3003", "WB-3002", "WB-3001"])

        # 2. newest (newest first -> t1, t2, t3)
        res_newest = self.client.get(url, {"order_by": "newest"})
        serials_newest = [item["ticket"].serial_number for item in res_newest.context["items"]]
        self.assertEqual(serials_newest, ["WB-3001", "WB-3002", "WB-3003"])

        # 3. plate (alphabetical)
        res_plate = self.client.get(url, {"order_by": "plate"})
        self.assertEqual(res_plate.status_code, 200)

    def test_product_filter(self):
        """Filtering by product must return only matching vehicles."""
        self.client.force_login(self.operator_user)
        url = reverse("weighbridge:trucks_in_yard")

        res = self.client.get(url, {"product": self.product_scrap.id})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["count"], 1)
        self.assertEqual(res.context["items"][0]["ticket"].serial_number, "WB-3002")
