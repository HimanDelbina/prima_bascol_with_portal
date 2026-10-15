import io
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from weighbridge.models import WeighTicket, TicketStatus, WeightMode
from masterdata.models import Product, Party, VehicleType, OperationType, Driver, Vehicle
from accounts.models import UserProfile, RoleChoices
from core.models import SystemSetting
from audit.models import AuditLog, AuditAction
from reports.exports import export_pdf, shape_persian, get_or_register_persian_font


class PrintingAndPdfOfflineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_superuser(
            username="print_admin",
            password="test-password"
        )
        
        # Regular user with weighbridge operator role
        cls.operator_user = User.objects.create_user(
            username="print_operator",
            password="test-password"
        )
        cls.operator_user.profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        cls.operator_user.profile.is_active = True
        cls.operator_user.profile.save()

        # Inactive / Deactivated user without print permission
        cls.unauthorized_user = User.objects.create_user(
            username="unauthorized_user",
            password="test-password"
        )
        cls.unauthorized_user.profile.is_active = False
        cls.unauthorized_user.profile.save()

        cls.settings = SystemSetting.get_settings()
        cls.settings.company_name = "شرکت تست باسکول پریما"
        cls.settings.receipt_header_title = "قبض رسمی توزین دیجیتال"
        cls.settings.receipt_footer_note = "هرگونه دستکاری پیگرد قانونی دارد"
        cls.settings.save()

        cls.op_type = OperationType.objects.create(name="فروش آزمایشی", code="OP-TEST")
        cls.party = Party.objects.create(name="شرکت فولاد البرز")
        cls.product = Product.objects.create(name="میلگرد آجدار ۱۶")
        cls.v_type = VehicleType.objects.create(name="تریلی کفی")
        cls.driver = Driver.objects.create(full_name="علی رستمی", mobile="09121112233")
        cls.vehicle = Vehicle.objects.create(
            plate_part1="12",
            plate_letter="ج",
            plate_part2="345",
            plate_iran="67",
            plate_display="12 ج 345 - ایران 67",
            normalized_plate="12ج345ایران67",
            vehicle_type=cls.v_type
        )

        cls.ticket = WeighTicket.objects.create(
            serial_number="WB-1405-00101",
            operation_type=cls.op_type,
            party=cls.party,
            product=cls.product,
            vehicle=cls.vehicle,
            vehicle_type=cls.v_type,
            driver=cls.driver,
            license_plate_display=cls.vehicle.plate_display,
            driver_name_custom=cls.driver.full_name,
            driver_mobile_custom=cls.driver.mobile,
            weight_mode=WeightMode.EMPTY_FIRST,
            first_weight=Decimal("14200"),
            second_weight=Decimal("38600"),
            gross_weight=Decimal("38600"),
            tare_weight=Decimal("14200"),
            net_weight=Decimal("24400"),
            sent_weight=Decimal("24500"),
            loss_percent=Decimal("0.5"),
            loss_weight=Decimal("122"),
            final_weight=Decimal("24278"),
            waybill_number="BL-998877",
            status=TicketStatus.COMPLETED,
            notes="بارگیری مطابق استاندارد کارخانه",
        )

    def test_unauthorized_user_cannot_access_ticket_print(self):
        self.client.force_login(self.unauthorized_user)
        url = reverse("weighbridge:ticket_print", args=[self.ticket.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("dashboard:index"))

    def test_print_views_render_with_zero_external_cdns(self):
        """
        Ensure A4, A5, and POS print templates load 100% offline assets with NO external CDN references.
        """
        self.client.force_login(self.operator_user)
        url = reverse("weighbridge:ticket_print", args=[self.ticket.pk])

        forbidden_cdn_domains = [
            "cdn.jsdelivr.net",
            "fonts.googleapis.com",
            "fonts.gstatic.com",
            "cdnjs.cloudflare.com",
            "unpkg.com",
            "http://",
            "https://",
        ]

        for template_format in ["a4", "a5", "pos"]:
            with self.subTest(template=template_format):
                resp = self.client.get(url, {"template": template_format})
                self.assertEqual(resp.status_code, 200)
                content = resp.content.decode("utf-8")

                # Verify local CSS is included
                self.assertIn("/static/css/ticket-print.css", content)

                # Verify no external CDN or remote URLs
                for cdn in forbidden_cdn_domains:
                    self.assertNotIn(cdn, content, f"Template {template_format} contains external reference: {cdn}")

                # Verify ticket serial number and details are present
                self.assertIn(self.ticket.serial_number, content)
                self.assertIn(self.ticket.license_plate_display, content)
                self.assertIn(self.ticket.driver_display, content)

    def test_pos_thermal_print_features_and_loop_prevention(self):
        """
        Verify POS print has 80mm default, 58mm toggle, and session storage auto-print guard.
        """
        self.client.force_login(self.operator_user)
        url = reverse("weighbridge:ticket_print", args=[self.ticket.pk])
        resp = self.client.get(url, {"template": "pos"})
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")

        # 80mm default style
        self.assertIn("80mm", content)
        # 58mm toggle support
        self.assertIn("togglePosWidth", content)
        self.assertIn("58mm", content)
        # Infinite print loop prevention via sessionStorage
        self.assertIn("sessionStorage.getItem", content)
        self.assertIn("sessionStorage.setItem", content)

    def test_a5_print_features_and_orientation_toggle(self):
        """
        Verify A5 print has orientation toggle and page styling.
        """
        self.client.force_login(self.operator_user)
        url = reverse("weighbridge:ticket_print", args=[self.ticket.pk])
        resp = self.client.get(url, {"template": "a5"})
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")

        self.assertIn("toggleOrientation", content)
        self.assertIn("A5 portrait", content)
        self.assertIn("A5 landscape", content)

    def test_offline_qr_code_embedded_in_print(self):
        """
        Ensure offline verification QR code is generated as embedded base64 PNG data URI.
        """
        self.client.force_login(self.operator_user)
        url = reverse("weighbridge:ticket_print", args=[self.ticket.pk])
        resp = self.client.get(url, {"template": "a4"})
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")

        self.assertIn("data:image/png;base64,", content)
        self.assertTrue(resp.context["qr_b64"])

    def test_reprint_immutability_and_audit_logging(self):
        """
        Verify that printing and reprinting:
        1. Never changes ticket serial numbers or weights.
        2. Accurately tracks initial print vs reprints in AuditLog.
        3. Sets is_reprint=True and increments print_number on reprints.
        """
        self.client.force_login(self.operator_user)
        url = reverse("weighbridge:ticket_print", args=[self.ticket.pk])

        # Capture state before print
        serial_before = self.ticket.serial_number
        gross_before = self.ticket.gross_weight
        net_before = self.ticket.net_weight
        final_before = self.ticket.final_weight

        # 1st Print (Initial)
        resp1 = self.client.get(url, {"template": "a4"})
        self.assertEqual(resp1.status_code, 200)
        self.assertFalse(resp1.context["is_reprint"])
        self.assertEqual(resp1.context["print_number"], 1)

        # 2nd Print (Reprint 1)
        resp2 = self.client.get(url, {"template": "a4"})
        self.assertEqual(resp2.status_code, 200)
        self.assertTrue(resp2.context["is_reprint"])
        self.assertEqual(resp2.context["print_number"], 2)
        self.assertIn("چاپ مجدد (نسخه 2)", resp2.content.decode("utf-8"))

        # 3rd Print (Reprint 2)
        resp3 = self.client.get(url, {"template": "pos"})
        self.assertEqual(resp3.status_code, 200)
        self.assertTrue(resp3.context["is_reprint"])
        self.assertEqual(resp3.context["print_number"], 3)
        self.assertIn("چاپ مجدد (نسخه 3)", resp3.content.decode("utf-8"))

        # Check AuditLog
        print_logs = AuditLog.objects.filter(
            model_name="WeighTicket",
            record_id=str(self.ticket.id),
            action=AuditAction.PRINT
        ).order_by("id")
        self.assertEqual(print_logs.count(), 3)
        self.assertIn("اولیه", print_logs[0].reason)
        self.assertIn("چاپ مجدد (نسخه 2)", print_logs[1].reason)
        self.assertIn("چاپ مجدد (نسخه 3)", print_logs[2].reason)

        # Verify Ticket Immutability
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.serial_number, serial_before)
        self.assertEqual(self.ticket.gross_weight, gross_before)
        self.assertEqual(self.ticket.net_weight, net_before)
        self.assertEqual(self.ticket.final_weight, final_before)

    def test_persian_font_registration_and_shaping(self):
        """
        Verify Persian TrueType font registration and arabic_reshaper / bidi display.
        """
        reg_font, bold_font = get_or_register_persian_font()
        self.assertIn("PersianTahoma", reg_font)
        self.assertIn("PersianTahoma", bold_font)

        # Test Persian text shaping
        persian_input = "باسکول دیجیتال پریما"
        shaped = shape_persian(persian_input)
        self.assertIsInstance(shaped, str)
        self.assertGreater(len(shaped), 0)
        self.assertNotEqual(shaped, "")

        # Empty / None string handling
        self.assertEqual(shape_persian(""), "")
        self.assertEqual(shape_persian(None), "")

    def test_export_pdf_generates_valid_persian_document(self):
        """
        Verify that export_pdf generates a valid binary PDF document with Persian RTL structure.
        """
        queryset = WeighTicket.objects.filter(id=self.ticket.id)
        summaries = {
            "total_tickets": 1,
            "sum_sent": Decimal("24500"),
            "sum_gross": Decimal("38600"),
            "sum_tare": Decimal("14200"),
            "sum_net": Decimal("24400"),
            "sum_loss": Decimal("122"),
            "sum_final": Decimal("24278"),
        }

        response = export_pdf(queryset, summaries=summaries, title="گزارش آزمایشی پرسنل")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment; filename=", response["Content-Disposition"])

        # Check PDF header magic bytes
        pdf_bytes = response.content
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"), "Generated file must start with PDF magic bytes %PDF-")
        self.assertGreater(len(pdf_bytes), 5000, "PDF content size should be non-trivial")

    def test_export_pdf_empty_queryset(self):
        """
        Verify that export_pdf executes cleanly with an empty queryset.
        """
        empty_qs = WeighTicket.objects.none()
        response = export_pdf(empty_qs, summaries=None, title="گزارش بدون داده")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_offline_static_assets_exist_on_disk(self):
        """
        Verify that local font and CSS files exist on the filesystem and are non-empty.
        """
        import os
        from django.conf import settings

        required_files = [
            os.path.join(settings.BASE_DIR, "static", "css", "ticket-print.css"),
            os.path.join(settings.BASE_DIR, "static", "fonts", "tahoma.ttf"),
            os.path.join(settings.BASE_DIR, "static", "fonts", "tahomabd.ttf"),
        ]
        for fpath in required_files:
            self.assertTrue(os.path.exists(fpath), f"File {fpath} does not exist on disk")
            self.assertGreater(os.path.getsize(fpath), 100, f"File {fpath} is unexpectedly small")

    def test_ticket_numeric_formatting_and_weights_rendered(self):
        """
        Verify weights are displayed accurately with proper formatting.
        """
        self.client.force_login(self.operator_user)
        url = reverse("weighbridge:ticket_print", args=[self.ticket.pk])
        resp = self.client.get(url, {"template": "a4"})
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")

        # 38,600, 14,200, 24,400, 24,278
        self.assertIn("38,600", content)
        self.assertIn("14,200", content)
        self.assertIn("24,400", content)
        self.assertIn("24,278", content)

    def test_report_builder_export_pdf_endpoint(self):
        """
        Verify that GET /reports/builder/?export=pdf returns a valid Persian PDF.
        """
        self.client.force_login(self.operator_user)
        url = reverse("reports:report_builder")
        response = self.client.get(url, {"export": "pdf"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_preset_report_export_pdf_endpoint(self):
        """
        Verify that GET /reports/preset/<code_or_id>/?export=pdf returns a valid Persian PDF.
        """
        self.client.force_login(self.operator_user)
        url = reverse("reports:preset_report_view", args=["daily"])
        response = self.client.get(url, {"export": "pdf"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF-"))

