from django.test import TestCase
from decimal import Decimal
from django.utils import timezone
from datetime import time

from weighbridge.models import WeighTicket, TicketStatus
from masterdata.models import Product, Party
from reports.services import ReportService
from reports.preset_reports import PRESET_REPORTS, get_preset_report_by_code
from django.contrib.auth.models import User
from django.urls import reverse
from core.jalali import jalali_to_gregorian
from openpyxl import load_workbook
import csv
import io


class FreightReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser("freight_report_admin", password="test-password")
        cls.party = Party.objects.create(name="طرف حساب کرایه")
        cls.other_party = Party.objects.create(name="طرف حساب دیگر")
        cls.date = jalali_to_gregorian("1405/06/24")
        for serial, amount, status, party in (
            ("F-1", "1000", TicketStatus.COMPLETED, cls.party),
            ("F-2", "2000", TicketStatus.WAITING_SECOND, cls.other_party),
            ("F-0", "0", TicketStatus.COMPLETED, cls.party),
            ("F-NONE", None, TicketStatus.COMPLETED, cls.party),
            ("F-CANCEL", "9000", TicketStatus.CANCELLED, cls.party),
        ):
            WeighTicket.objects.create(serial_number=serial, freight_amount=amount, status=status,
                                       party=party, first_weight_date=cls.date, license_plate_display="12 ج 345")

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("reports:freight_report")

    def test_summary_excludes_cancelled_and_distinguishes_missing_from_zero(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["summaries"], {
            "total_tickets": 4, "recorded_count": 3, "missing_count": 1, "total_amount": Decimal("3000"), "sum_sent": Decimal("0.00"),
        })
        self.assertContains(response, "3,000")
        self.assertContains(response, "ثبت نشده")
        self.assertNotContains(response, "F-CANCEL")
        response = self.client.get(self.url, {"status": "all"})
        self.assertEqual(response.context["summaries"]["total_amount"], Decimal("12000"))

    def test_filters_apply_to_summary_and_rows(self):
        response = self.client.get(self.url, {"party": self.party.pk, "amount_status": "recorded"})
        self.assertEqual(response.context["summaries"]["total_amount"], Decimal("1000"))
        self.assertEqual(response.context["summaries"]["total_tickets"], 2)
        self.assertNotContains(response, "F-2")
        response = self.client.get(self.url, {"amount_status": "missing"})
        self.assertEqual(response.context["summaries"]["missing_count"], 1)
        self.assertEqual(response.context["summaries"]["total_amount"], 0)

    def test_jalali_range_uses_first_weight_date_even_if_created_later(self):
        WeighTicket.objects.filter(serial_number="F-2").update(first_weight_date=jalali_to_gregorian("1405/06/23"))
        response = self.client.get(self.url, {"start_date": "۱۴۰۵/۰۶/۲۴", "end_date": "۱۴۰۵/۰۶/۲۴"})
        self.assertEqual(response.context["summaries"]["total_amount"], Decimal("1000"))
        self.assertNotContains(response, "F-2")

    def test_invalid_filters_show_errors_without_exporting(self):
        for params, field in (({"start_date": "invalid"}, "start_date"),
                              ({"start_date": "1405/06/25", "end_date": "1405/06/24"}, "end_date"),
                              ({"party": "invalid"}, "party")):
            with self.subTest(params=params):
                response = self.client.get(self.url, {**params, "export": "excel"})
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)
                self.assertNotIn("Content-Disposition", response)

    def test_exports_include_all_filtered_pages_and_numeric_amounts(self):
        for index in range(27):
            WeighTicket.objects.create(serial_number=f"EXTRA-{index}", freight_amount=100,
                                       party=self.party, first_weight_date=self.date, license_plate_display="test")
        params = {"party": self.party.pk, "page": 2}
        response = self.client.get(self.url, params)
        self.assertEqual(response.context["page_obj"].number, 2)
        self.assertEqual(response.context["summaries"]["total_amount"], 3700)
        csv_response = self.client.get(self.url, {**params, "export": "csv"})
        rows = list(csv.reader(io.StringIO(csv_response.content.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 32)  # Header, 30 tickets, total.
        self.assertEqual(rows[-1][-1], "3700")
        self.assertNotIn("F-2", [row[0] for row in rows])
        excel_response = self.client.get(self.url, {**params, "export": "excel"})
        workbook = load_workbook(io.BytesIO(excel_response.content))
        sheet = workbook.active
        self.assertTrue(sheet.sheet_view.rightToLeft)
        self.assertEqual(sheet.max_row, 35)
        self.assertEqual(sheet["L35"].value, 3700)
        self.assertEqual(sheet["L35"].data_type, "n")

    def test_empty_results_and_export(self):
        response = self.client.get(self.url, {"plate": "not-found"})
        self.assertContains(response, "قبضی با این فیلترها یافت نشد.")
        self.assertEqual(response.context["summaries"]["total_amount"], 0)
        response = self.client.get(self.url, {"plate": "not-found", "export": "excel"})
        sheet = load_workbook(io.BytesIO(response.content)).active
        self.assertEqual(sheet["L5"].value, 0)

    def test_exports_treat_ticket_text_as_text(self):
        WeighTicket.objects.filter(serial_number="F-1").update(waybill_number="=1+1")
        response = self.client.get(self.url, {"export": "excel"})
        sheet = load_workbook(io.BytesIO(response.content)).active
        cells = [row[8] for row in sheet.iter_rows(min_row=5) if row[0].value == "F-1"]
        self.assertEqual(cells[0].value, "=1+1")
        self.assertEqual(cells[0].data_type, "s")
        response = self.client.get(self.url, {"export": "csv"})
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
        self.assertEqual(next(row for row in rows if row[0] == "F-1")[8], "'=1+1")

    def test_login_required_for_page_and_exports(self):
        self.client.logout()
        for export in ("", "excel", "csv"):
            response = self.client.get(self.url, {"export": export})
            self.assertEqual(response.status_code, 302)
            self.assertIn("/accounts/login/", response.url)

class PresetReportNavigationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser("preset_admin", password="test-password")

    def setUp(self):
        self.client.force_login(self.user)

    def test_sidebar_reports_render_and_current_link_is_active(self):
        for code in ("daily", "monthly", "by_product", "by_party", "by_driver", "variance_analysis"):
            with self.subTest(code=code):
                url = reverse("reports:preset_report_view", args=[code])
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'href="{url}" class="nav-link active"')
                self.assertEqual(response.context["report_meta"]["code"], code)
                for legacy in ("product", "party", "driver", "discrepancy"):
                    self.assertNotContains(response, f'href="/reports/presets/{legacy}/"')

    def test_old_report_links_redirect_and_preserve_filters(self):
        for old, canonical in (("product", "by_product"), ("party", "by_party"),
                               ("driver", "by_driver"), ("discrepancy", "variance_analysis")):
            with self.subTest(code=old):
                url = reverse("reports:preset_report_view", args=[old])
                response = self.client.get(url, {"start_date": "1405/06/01", "product": ["1", "2"], "export": "csv"})
                expected = reverse("reports:preset_report_view", args=[canonical])
                self.assertRedirects(response, expected + "?start_date=1405%2F06%2F01&product=1&product=2&export=csv",
                                     fetch_redirect_response=False)
                response = self.client.get(url, follow=True)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["report_meta"]["code"], canonical)

    def test_unknown_report_still_returns_404(self):
        response = self.client.get(reverse("reports:preset_report_view", args=["unknown-report"]))
        self.assertEqual(response.status_code, 404)


class ReportServiceTests(TestCase):
    def setUp(self):
        self.p1 = Product.objects.create(name="آهن اسفنجی")
        self.p2 = Product.objects.create(name="گندله")
        self.party1 = Party.objects.create(name="فولاد خوزستان")
        self.party2 = Party.objects.create(name="فولاد مبارکه")

        today = timezone.localdate()

        WeighTicket.objects.create(
            serial_number="T-1",
            status=TicketStatus.COMPLETED,
            product=self.p1,
            party=self.party1,
            first_weight=Decimal("30000.00"),
            second_weight=Decimal("10000.00"),
            gross_weight=Decimal("30000.00"),
            tare_weight=Decimal("10000.00"),
            net_weight=Decimal("20000.00"),
            final_weight=Decimal("20000.00"),
            first_weight_date=today,
            first_weight_time=time(10, 0),
            license_plate_display="12 ج 345 - ایران 67"
        )

        WeighTicket.objects.create(
            serial_number="T-2",
            status=TicketStatus.COMPLETED,
            product=self.p2,
            party=self.party2,
            first_weight=Decimal("40000.00"),
            second_weight=Decimal("15000.00"),
            gross_weight=Decimal("40000.00"),
            tare_weight=Decimal("15000.00"),
            net_weight=Decimal("25000.00"),
            final_weight=Decimal("25000.00"),
            first_weight_date=today,
            first_weight_time=time(11, 0),
            license_plate_display="34 ج 567 - ایران 88"
        )

    def test_filter_and_summary_metrics(self):
        qs = ReportService.filter_tickets({"product": str(self.p1.id)})
        self.assertEqual(qs.count(), 1)
        
        summaries = ReportService.get_summary_metrics(qs)
        self.assertEqual(summaries["total_tickets"], 1)
        self.assertEqual(summaries["sum_net"], Decimal("20000.00"))

    def test_all_summary_metrics(self):
        qs = ReportService.filter_tickets({})
        self.assertEqual(qs.count(), 2)
        
        summaries = ReportService.get_summary_metrics(qs)
        self.assertEqual(summaries["total_tickets"], 2)
        self.assertEqual(summaries["sum_net"], Decimal("45000.00"))
        self.assertEqual(summaries["sum_gross"], Decimal("70000.00"))
        self.assertEqual(summaries["sum_tare"], Decimal("25000.00"))

    def test_group_by_product(self):
        qs = ReportService.filter_tickets({})
        group_data = ReportService.group_by_field(qs, "product")
        self.assertEqual(len(group_data), 2)

    def test_preset_reports_exist(self):
        self.assertEqual(len(PRESET_REPORTS), 30)
        daily_rep = get_preset_report_by_code("daily")
        self.assertIsNotNone(daily_rep)
        self.assertEqual(daily_rep["title"], "گزارش روزانه باسکول")

    def test_filter_by_ticket_number_and_digits(self):
        WeighTicket.objects.filter(serial_number="T-1").update(waybill_number="WB-1001")
        WeighTicket.objects.filter(serial_number="T-2").update(waybill_number="BL-2002")

        # English digits ticket_number
        qs1 = ReportService.filter_tickets({"ticket_number": "T-1"})
        self.assertEqual(qs1.count(), 1)
        self.assertEqual(qs1.first().serial_number, "T-1")

        # Persian digits ticket_number
        qs_fa = ReportService.filter_tickets({"ticket_number": "T-۱"})
        self.assertEqual(qs_fa.count(), 1)
        self.assertEqual(qs_fa.first().serial_number, "T-1")

        # Alias serial_number
        qs_alias = ReportService.filter_tickets({"serial_number": "T-2"})
        self.assertEqual(qs_alias.count(), 1)
        self.assertEqual(qs_alias.first().serial_number, "T-2")

    def test_filter_by_waybill_number_and_digits(self):
        WeighTicket.objects.filter(serial_number="T-1").update(waybill_number="WB-1001")
        WeighTicket.objects.filter(serial_number="T-2").update(waybill_number="BL-2002")

        # Search waybill
        qs_wb = ReportService.filter_tickets({"waybill_number": "1001"})
        self.assertEqual(qs_wb.count(), 1)
        self.assertEqual(qs_wb.first().serial_number, "T-1")

        # Search waybill with Persian digits
        qs_wb_fa = ReportService.filter_tickets({"waybill_number": "۲۰۰۲"})
        self.assertEqual(qs_wb_fa.count(), 1)
        self.assertEqual(qs_wb_fa.first().serial_number, "T-2")

    def test_filter_by_general_q_search(self):
        WeighTicket.objects.filter(serial_number="T-1").update(waybill_number="WB-9900")
        
        # Search by ticket serial in q
        qs_q_serial = ReportService.filter_tickets({"q": "T-1"})
        self.assertEqual(qs_q_serial.count(), 1)

        # Search by waybill in q
        qs_q_waybill = ReportService.filter_tickets({"q": "۹۹۰۰"})
        self.assertEqual(qs_q_waybill.count(), 1)
        self.assertEqual(qs_q_waybill.first().serial_number, "T-1")


class ReportBuilderViewFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser("report_view_admin", password="test-password")
        cls.t1 = WeighTicket.objects.create(
            serial_number="REP-101",
            waybill_number="BL-5555",
            status=TicketStatus.COMPLETED,
            gross_weight=Decimal("20000.00"),
            tare_weight=Decimal("8000.00"),
            net_weight=Decimal("12000.00"),
            final_weight=Decimal("12000.00"),
            license_plate_display="11 A 111",
        )
        cls.t2 = WeighTicket.objects.create(
            serial_number="REP-202",
            waybill_number="BL-8888",
            status=TicketStatus.COMPLETED,
            gross_weight=Decimal("25000.00"),
            tare_weight=Decimal("10000.00"),
            net_weight=Decimal("15000.00"),
            final_weight=Decimal("15000.00"),
            license_plate_display="22 B 222",
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("reports:report_builder")

    def test_filter_report_builder_by_ticket_number(self):
        response = self.client.get(self.url, {"ticket_number": "101"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "REP-101")
        self.assertNotContains(response, "REP-202")

    def test_filter_report_builder_by_waybill_number(self):
        response = self.client.get(self.url, {"waybill_number": "8888"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "REP-202")
        self.assertNotContains(response, "REP-101")

    def test_freight_report_ticket_and_waybill_filter(self):
        self.t1.freight_amount = Decimal("500000")
        self.t1.save()
        self.t2.freight_amount = Decimal("700000")
        self.t2.save()

        freight_url = reverse("reports:freight_report")
        response_ticket = self.client.get(freight_url, {"ticket_number": "101"})
        self.assertEqual(response_ticket.status_code, 200)
        self.assertContains(response_ticket, "REP-101")
        self.assertNotContains(response_ticket, "REP-202")

        response_waybill = self.client.get(freight_url, {"waybill_number": "8888"})
        self.assertEqual(response_waybill.status_code, 200)
        self.assertContains(response_waybill, "REP-202")
        self.assertNotContains(response_waybill, "REP-101")

    def test_report_builder_and_exports_contain_time_and_waybill_weight(self):
        self.t1.first_weight_time = time(9, 15)
        self.t1.second_weight_time = time(10, 45)
        self.t1.sent_weight = Decimal("19500.00")
        self.t1.save()

        # Web view
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ساعت ورود")
        self.assertContains(response, "ساعت خروج")
        self.assertContains(response, "وزن بارنامه (Kg)")
        self.assertContains(response, "09:15")
        self.assertContains(response, "10:45")

        # Excel export
        excel_resp = self.client.get(self.url, {"export": "excel"})
        self.assertEqual(excel_resp.status_code, 200)
        wb = load_workbook(io.BytesIO(excel_resp.content))
        ws = wb.active
        headers = [ws.cell(row=4, column=col).value for col in range(1, 19)]
        self.assertIn("ساعت ورود", headers)
        self.assertIn("ساعت خروج", headers)
        self.assertIn("وزن بارنامه (Kg)", headers)

        # CSV export
        csv_resp = self.client.get(self.url, {"export": "csv"})
        self.assertEqual(csv_resp.status_code, 200)
        csv_rows = list(csv.reader(io.StringIO(csv_resp.content.decode("utf-8-sig"))))
        self.assertIn("ساعت ورود", csv_rows[0])
        self.assertIn("ساعت خروج", csv_rows[0])
        self.assertIn("وزن بارنامه (Kg)", csv_rows[0])

        # Print preview
        print_resp = self.client.get(self.url, {"export": "print"})
        self.assertEqual(print_resp.status_code, 200)
        self.assertContains(print_resp, "ساعت ورود")
        self.assertContains(print_resp, "ساعت خروج")
        self.assertContains(print_resp, "وزن بارنامه (Kg)")


class ProductMultiSelectFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser("prod_filter_admin", password="test-password")
        cls.p_sponge = Product.objects.create(name="آهن اسفنجی", code="SP-01")
        cls.p_pellet = Product.objects.create(name="گندله", code="PL-02")
        cls.p_billet = Product.objects.create(name="شمش فولادی", code="BL-03")
        cls.party = Party.objects.create(name="مجتمع فولاد")

        today = timezone.localdate()
        cls.t_sponge = WeighTicket.objects.create(
            serial_number="TK-SPONGE",
            product=cls.p_sponge,
            party=cls.party,
            gross_weight=Decimal("30000"),
            tare_weight=Decimal("10000"),
            net_weight=Decimal("20000"),
            final_weight=Decimal("20000"),
            first_weight_date=today,
            status=TicketStatus.COMPLETED,
        )
        cls.t_pellet = WeighTicket.objects.create(
            serial_number="TK-PELLET",
            product=cls.p_pellet,
            party=cls.party,
            gross_weight=Decimal("35000"),
            tare_weight=Decimal("12000"),
            net_weight=Decimal("23000"),
            final_weight=Decimal("23000"),
            first_weight_date=today,
            status=TicketStatus.COMPLETED,
        )
        cls.t_billet = WeighTicket.objects.create(
            serial_number="TK-BILLET",
            product=cls.p_billet,
            party=cls.party,
            gross_weight=Decimal("40000"),
            tare_weight=Decimal("15000"),
            net_weight=Decimal("25000"),
            final_weight=Decimal("25000"),
            first_weight_date=today,
            status=TicketStatus.COMPLETED,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_service_filter_single_product(self):
        qs = ReportService.filter_tickets({"product": str(self.p_sponge.id)})
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().serial_number, "TK-SPONGE")

    def test_service_filter_multiple_products(self):
        from django.http import QueryDict
        qd = QueryDict(f"product={self.p_sponge.id}&product={self.p_billet.id}")
        qs = ReportService.filter_tickets(qd)
        self.assertEqual(qs.count(), 2)
        serials = set(qs.values_list("serial_number", flat=True))
        self.assertEqual(serials, {"TK-SPONGE", "TK-BILLET"})

    def test_report_builder_view_multiple_products(self):
        url = reverse("reports:report_builder")
        response = self.client.get(url, {"product": [str(self.p_sponge.id), str(self.p_pellet.id)]})
        self.assertEqual(response.status_code, 200)
        self.assertIn(str(self.p_sponge.id), response.context["selected_products"])
        self.assertIn(str(self.p_pellet.id), response.context["selected_products"])
        self.assertNotIn(str(self.p_billet.id), response.context["selected_products"])
        
        # Verify tickets in response
        self.assertContains(response, "TK-SPONGE")
        self.assertContains(response, "TK-PELLET")
        self.assertNotContains(response, "TK-BILLET")

    def test_preset_report_view_multiple_products(self):
        url = reverse("reports:preset_report_view", args=["daily"])
        response = self.client.get(url, {"product": [str(self.p_pellet.id), str(self.p_billet.id)]})
        self.assertEqual(response.status_code, 200)
        self.assertIn(str(self.p_pellet.id), response.context["selected_products"])
        self.assertIn(str(self.p_billet.id), response.context["selected_products"])
        
        # Verify tickets in response
        self.assertContains(response, "TK-PELLET")
        self.assertContains(response, "TK-BILLET")
        self.assertNotContains(response, "TK-SPONGE")

    def test_export_preserves_multiple_products_filter(self):
        url = reverse("reports:report_builder")
        response = self.client.get(url, {
            "product": [str(self.p_sponge.id)],
            "export": "csv"
        })
        self.assertEqual(response.status_code, 200)
        csv_text = response.content.decode("utf-8-sig")
        self.assertIn("TK-SPONGE", csv_text)
        self.assertNotIn("TK-PELLET", csv_text)
        self.assertNotIn("TK-BILLET", csv_text)


class FinancialExcelExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser("finance_admin", password="test-password")
        cls.product = Product.objects.create(name="آهن اسفنجی ویژه", code="SP-FIN")
        cls.party = Party.objects.create(name="فولاد مالی پریما")
        cls.date = timezone.localdate()
        cls.t1 = WeighTicket.objects.create(
            serial_number="FIN-100",
            waybill_number="WB-8899",
            product=cls.product,
            party=cls.party,
            gross_weight=Decimal("32000"),
            tare_weight=Decimal("12000"),
            net_weight=Decimal("20000"),
            final_weight=Decimal("20000"),
            freight_amount=Decimal("4500000"),
            notes="توضیحات مالی: پرداخت کرایه نقدی انجام شد",
            status=TicketStatus.COMPLETED,
            first_weight_date=cls.date,
        )
        cls.t2 = WeighTicket.objects.create(
            serial_number="FIN-200",
            product=cls.product,
            party=cls.party,
            gross_weight=Decimal("40000"),
            tare_weight=Decimal("15000"),
            net_weight=Decimal("25000"),
            final_weight=Decimal("25000"),
            freight_amount=Decimal("6000000"),
            notes="توضیحات حسابداری: نیازمند تأیید مدیر مالی",
            status=TicketStatus.COMPLETED,
            first_weight_date=cls.date,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_report_builder_financial_excel_export_contains_notes_and_freight(self):
        url = reverse("reports:report_builder")
        response = self.client.get(url, {"export": "excel_financial"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        wb = load_workbook(io.BytesIO(response.content))
        ws = wb.active
        self.assertTrue(ws.sheet_view.rightToLeft)
        
        # Verify Headers
        headers = [ws.cell(row=4, column=col).value for col in range(1, 22)]
        self.assertIn("توضیحات", headers)
        self.assertIn("مبلغ کرایه (تومان)", headers)
        self.assertIn("تعداد بار و شمش", headers)
        notes_col_idx = headers.index("توضیحات") + 1
        freight_col_idx = headers.index("مبلغ کرایه (تومان)") + 1

        # Check rows content
        all_notes = {ws.cell(row=r, column=notes_col_idx).value for r in range(5, 7)}
        self.assertIn("توضیحات مالی: پرداخت کرایه نقدی انجام شد", all_notes)
        self.assertIn("توضیحات حسابداری: نیازمند تأیید مدیر مالی", all_notes)

        all_freights = {ws.cell(row=r, column=freight_col_idx).value for r in range(5, 7)}
        self.assertIn(4500000, all_freights)
        self.assertIn(6000000, all_freights)

    def test_preset_report_financial_excel_export(self):
        url = reverse("reports:preset_report_view", args=["daily"])
        response = self.client.get(url, {"export": "excel_financial"})
        self.assertEqual(response.status_code, 200)
        wb = load_workbook(io.BytesIO(response.content))
        ws = wb.active
        headers = [ws.cell(row=4, column=col).value for col in range(1, 22)]
        self.assertIn("توضیحات", headers)
        notes_col_idx = headers.index("توضیحات") + 1
        all_notes = [ws.cell(row=r, column=notes_col_idx).value for r in range(5, ws.max_row)]
        self.assertTrue(any("پرداخت کرایه نقدی" in str(n) for n in all_notes))

    def test_freight_report_financial_excel_export(self):
        url = reverse("reports:freight_report")
        response = self.client.get(url, {"export": "excel_financial"})
        self.assertEqual(response.status_code, 200)
        wb = load_workbook(io.BytesIO(response.content))
        ws = wb.active
        headers = [ws.cell(row=4, column=col).value for col in range(1, 22)]
        self.assertIn("توضیحات", headers)


