from decimal import Decimal
from datetime import time
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.contrib.messages import get_messages

from weighbridge.models import WeighTicket, TicketStatus, WeightMode
from masterdata.models import Product, Party, Driver, VehicleType, Vehicle, OperationType, Location, UnloadLocation
from accounts.models import UserProfile, RoleChoices
from core.models import SystemSetting
from core.jalali import get_today_jalali, get_today_gregorian


class Phase1OperationalWorkflowTests(TestCase):
    """
    Automated test suite for Phase 1 Operational Workflow Improvements (UX-01 & UX-02).
    """

    def setUp(self):
        self.operator_user = User.objects.create_user(username="weigh_op", password="password123")
        p_op = self.operator_user.profile
        p_op.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        p_op.save()

        self.manager_user = User.objects.create_user(username="weigh_mgr", password="password123")
        p_mgr = self.manager_user.profile
        p_mgr.role = RoleChoices.WEIGHBRIDGE_MANAGER
        p_mgr.save()

        self.unauthorized_user = User.objects.create_user(username="viewer_user", password="password123")
        p_view = self.unauthorized_user.profile
        p_view.role = RoleChoices.VIEWER
        p_view.save()

        self.client = Client()
        self.client.force_login(self.operator_user)

        # 2. Master Data Setup
        self.op_type = OperationType.objects.create(name="ورود مواد اولیه", code="IN-01", direction="inbound")
        self.party = Party.objects.create(name="شرکت تامین فولاد آریا", code="P-01")
        self.product = Product.objects.create(name="شمش فولادی 150", code="PR-150")
        self.vehicle_type = VehicleType.objects.create(name="تریلی کفی", code="TR-FLAT")
        self.origin = Location.objects.create(name="اصفهان")
        self.dest = Location.objects.create(name="کارخانه پریما باسکول")
        self.unload_loc = UnloadLocation.objects.create(name="انبار روباز شماره ۱")

        SystemSetting.objects.update_or_create(
            id=1,
            defaults={
                "company_name": "شرکت فولاد پریما",
                "require_driver": False,
                "require_waybill": False,
            }
        )

        self.base_payload = {
            "weight_mode": WeightMode.EMPTY_FIRST,
            "operation_type": self.op_type.id,
            "party": self.party.id,
            "product": self.product.id,
            "vehicle_type": self.vehicle_type.id,
            "driver_name_custom": "حسین اکبری",
            "driver_mobile_custom": "09121234567",
            "origin": self.origin.id,
            "destination": self.dest.id,
            "unload_location": self.unload_loc.id,
            "plate_part1": "12",
            "plate_letter": "ع",
            "plate_part2": "345",
            "plate_iran": "64",
            "license_plate_display": "12 ع 345 - ایران 64",
            "first_weight": "14250",
            "load_count": "1",
            "sent_weight": "0",
            "loss_percent": "0",
            "loss_weight": "0",
        }

    # -------------------------------------------------------------------------
    # 1. UX-01: First Weighing Options (Save & New, Save & View Yard, Save & Print)
    # -------------------------------------------------------------------------

    def test_first_weighing_save_and_new_default(self):
        """
        Default action when registering first weight should be Save & New:
        - Saves ticket with WAITING_SECOND status
        - Redirects to ticket_create
        - Displays success notification with ticket serial number
        """
        payload = {**self.base_payload, "submit_action": "save_and_new"}
        response = self.client.post(reverse("weighbridge:ticket_create"), payload)

        # Authoritative POST-Redirect-GET to clean ticket_create form
        self.assertRedirects(response, reverse("weighbridge:ticket_create"))

        ticket = WeighTicket.objects.latest("id")
        self.assertEqual(ticket.status, TicketStatus.WAITING_SECOND)
        self.assertEqual(ticket.first_weight, Decimal("14250"))
        self.assertEqual(ticket.first_weight_operator, self.operator_user)

        # Success message with serial number
        messages = list(get_messages(response.wsgi_request))
        self.assertTrue(any(ticket.serial_number in str(m) and "ثبت شد" in str(m) for m in messages))

        # Check that subsequent GET loads a clean form
        get_response = self.client.get(reverse("weighbridge:ticket_create"))
        self.assertEqual(get_response.status_code, 200)
        form = get_response.context["form"]
        self.assertFalse(form.initial.get("first_weight"))
        self.assertFalse(form.initial.get("license_plate_display"))

    def test_first_weighing_save_and_view_yard(self):
        """
        Selecting 'Save & View Yard' after first weighing saves the ticket
        and redirects to the trucks-in-yard board.
        """
        payload = {
            **self.base_payload,
            "plate_part2": "888",
            "license_plate_display": "12 ع 888 - ایران 64",
            "submit_action": "save_and_yard"
        }
        response = self.client.post(reverse("weighbridge:ticket_create"), payload)

        self.assertRedirects(response, reverse("weighbridge:trucks_in_yard"))

        ticket = WeighTicket.objects.latest("id")
        self.assertEqual(ticket.status, TicketStatus.WAITING_SECOND)

        # Verify ticket is displayed on trucks_in_yard page
        yard_response = self.client.get(reverse("weighbridge:trucks_in_yard"))
        self.assertEqual(yard_response.status_code, 200)
        self.assertContains(yard_response, ticket.serial_number)
        self.assertContains(yard_response, "12 ع 888 - ایران 64")

    def test_first_weighing_save_and_print(self):
        """
        Selecting 'Save & Print' after first weighing saves the ticket
        and redirects immediately to ticket_print.
        """
        payload = {
            **self.base_payload,
            "plate_part2": "777",
            "license_plate_display": "12 ع 777 - ایران 64",
            "submit_action": "save_and_print"
        }
        response = self.client.post(reverse("weighbridge:ticket_create"), payload)

        ticket = WeighTicket.objects.latest("id")
        expected_print_url = f"/weighbridge/tickets/{ticket.id}/print/"
        self.assertRedirects(response, expected_print_url)

    # -------------------------------------------------------------------------
    # 2. UX-02: Second Weighing Navigation & Open Ticket Detection
    # -------------------------------------------------------------------------

    def test_existing_open_ticket_identification_via_ajax(self):
        """
        When operator types a plate belonging to a vehicle with an open ticket,
        ajax_plate_lookup returns has_open_ticket=True with serial number,
        first weight, registration date, time, product, and party.
        """
        plate_str = "45 ب 678 - ایران 22"
        open_ticket = WeighTicket.objects.create(
            serial_number="T-OPEN-101",
            status=TicketStatus.WAITING_SECOND,
            license_plate_display=plate_str,
            first_weight=Decimal("18500.00"),
            first_weight_date=get_today_gregorian(),
            first_weight_time=time(10, 45),
            product=self.product,
            party=self.party,
            operation_type=self.op_type,
            first_weight_operator=self.operator_user,
        )

        lookup_url = reverse("weighbridge:ajax_plate_lookup")
        response = self.client.get(lookup_url, {"plate": plate_str})
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertTrue(data.get("has_open_ticket"))
        ot_data = data.get("open_ticket")
        self.assertIsNotNone(ot_data)
        self.assertEqual(ot_data["id"], open_ticket.id)
        self.assertEqual(ot_data["serial_number"], "T-OPEN-101")
        self.assertEqual(ot_data["first_weight"], 18500.0)
        self.assertEqual(ot_data["product"], self.product.name)
        self.assertEqual(ot_data["party"], self.party.name)
        self.assertEqual(ot_data["time"], "10:45")

    def test_navigation_to_second_weighing_and_completion(self):
        """
        Operator can navigate to second weighing for the active open ticket
        and successfully record the second weight, calculating net weight.
        """
        open_ticket = WeighTicket.objects.create(
            serial_number="T-OPEN-102",
            status=TicketStatus.WAITING_SECOND,
            license_plate_display="55 ج 999 - ایران 33",
            first_weight=Decimal("32000.00"),
            product=self.product,
            party=self.party,
            first_weight_operator=self.operator_user,
        )

        sec_url = reverse("weighbridge:ticket_second_weight", args=[open_ticket.id])
        get_res = self.client.get(sec_url)
        self.assertEqual(get_res.status_code, 200)
        self.assertContains(get_res, open_ticket.serial_number)

        post_res = self.client.post(sec_url, {
            "second_weight": "12000",
            "second_weight_date_jalali": get_today_jalali(),
            "second_weight_time_str": "12:15",
            "sent_weight": "20000",
            "loss_percent": "0",
            "submit_action": "save"
        })
        self.assertEqual(post_res.status_code, 302)

        open_ticket.refresh_from_db()
        self.assertEqual(open_ticket.status, TicketStatus.COMPLETED)
        self.assertEqual(open_ticket.gross_weight, Decimal("32000.00"))
        self.assertEqual(open_ticket.tare_weight, Decimal("12000.00"))
        self.assertEqual(open_ticket.net_weight, Decimal("20000.00"))

    def test_duplicate_submission_prevention_on_server(self):
        """
        Authoritative server-side validation:
        If a vehicle already has an active open ticket in the yard (WAITING_SECOND),
        submitting a new first-weighing ticket for the same vehicle MUST be rejected.
        """
        plate_str = "66 د 111 - ایران 55"
        WeighTicket.objects.create(
            serial_number="T-OPEN-EXISTING",
            status=TicketStatus.WAITING_SECOND,
            license_plate_display=plate_str,
            first_weight=Decimal("25000.00"),
            first_weight_operator=self.operator_user,
        )

        # Attempt to create duplicate first weight for same vehicle
        payload = {
            **self.base_payload,
            "plate_part1": "66",
            "plate_letter": "د",
            "plate_part2": "111",
            "plate_iran": "55",
            "license_plate_display": plate_str,
            "first_weight": "26000",
        }
        response = self.client.post(reverse("weighbridge:ticket_create"), payload)

        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertTrue(form.errors)
        error_text = str(form.errors)
        self.assertIn("T-OPEN-EXISTING", error_text)
        self.assertIn("قبض باز", error_text)

        # Ensure no second ticket was created
        self.assertEqual(WeighTicket.objects.filter(license_plate_display=plate_str).count(), 1)

    # -------------------------------------------------------------------------
    # 3. Usability, Validation & Permissions
    # -------------------------------------------------------------------------

    def test_invalid_form_submission(self):
        """
        Submitting form with missing mandatory fields or invalid data returns 200
        with clear form errors and does not create a ticket.
        """
        payload = {**self.base_payload, "operation_type": "", "party": ""}
        response = self.client.post(reverse("weighbridge:ticket_create"), payload)
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertIn("operation_type", form.errors)
        self.assertIn("party", form.errors)

    def test_access_permissions(self):
        """
        Access to weighbridge operational views requires authentication
        and appropriate role.
        """
        anon_client = Client()

        # Anonymous access redirects to login
        res_create = anon_client.get(reverse("weighbridge:ticket_create"))
        self.assertEqual(res_create.status_code, 302)
        self.assertIn("/accounts/login/", res_create.url)

        res_yard = anon_client.get(reverse("weighbridge:trucks_in_yard"))
        self.assertEqual(res_yard.status_code, 302)

        # User without weighbridge operational role
        unauth_client = Client()
        unauth_client.force_login(self.unauthorized_user)

        res_unauth = unauth_client.get(reverse("weighbridge:ticket_create"))
        self.assertEqual(res_unauth.status_code, 302)

    def test_compatibility_with_ticket_printing(self):
        """
        An open ticket (WAITING_SECOND) is fully compatible with ticket_print
        in A4, A5, and POS layouts without rendering errors.
        """
        ticket = WeighTicket.objects.create(
            serial_number="T-PRINT-TEST-1",
            status=TicketStatus.WAITING_SECOND,
            license_plate_display="33 س 777 - ایران 99",
            first_weight=Decimal("19400.00"),
            product=self.product,
            party=self.party,
            operation_type=self.op_type,
            first_weight_operator=self.operator_user,
        )

        for template in ("a4", "a5", "pos"):
            with self.subTest(template=template):
                print_url = f"{reverse('weighbridge:ticket_print', args=[ticket.id])}?template={template}"
                response = self.client.get(print_url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, ticket.serial_number)
                self.assertContains(response, "33 س 777 - ایران 99")
