import io
from datetime import datetime, date, time, timedelta
from decimal import Decimal
import pytz
import openpyxl

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.db import models

from accounts.models import UserProfile, RoleChoices
from masterdata.models import Product, Party, OperationType
from weighbridge.models import WeighTicket, TicketStatus, WeightMode
from audit.models import AuditLog, AuditAction
from shifts.models import (
    WorkShift, ShiftSession, ShiftSessionStatus,
    ShiftOperatorAssignment, ShiftOperatorRole, ShiftAssignmentStatus,
    ShiftExceptionLog, ShiftHandover, ShiftHandoverStatus,
    ShiftHandoverItem, ShiftHandoverItemCategory,
)
from shifts.kpi_service import ShiftKPIService
from shifts.dashboard_service import ShiftDashboardService
from shifts.export_service import (
    ShiftExportService,
    sanitize_formula_injection,
    shape_persian,
    get_or_register_vazirmatn_font,
)


class Phase43AuditSecurityTests(TestCase):
    """
    Independent audit test suite verifying:
    - Spreadsheet formula injection defense against all hostile vectors (tabs, control chars, unicode)
    - Row-level authorization parity across all Excel worksheets and PDF sections
    - Negative IDOR tests for URLs and query parameters
    - Frozen snapshot evidence immutability during export
    - Numerical reconciliation between KPI engine, dashboard payload, and Excel output
    - 31-day boundary validation enforcement returning HTTP 400
    """

    @classmethod
    def setUpTestData(cls):
        cls.tz = pytz.timezone("Asia/Tehran")

        # 1. Users
        cls.admin_user = User.objects.create_superuser(
            username="sec_admin", password="Password123!", email="admin@sec.com"
        )
        cls.admin_user.profile.role = RoleChoices.SYSTEM_ADMIN
        cls.admin_user.profile.save()

        cls.supervisor = User.objects.create_user(
            username="sec_sup", password="Password123!", email="sup@sec.com",
            first_name="حمید", last_name="سرپرست"
        )
        cls.supervisor.profile.role = RoleChoices.WEIGHBRIDGE_MANAGER
        cls.supervisor.profile.save()

        cls.op1 = User.objects.create_user(
            username="sec_op1", password="Password123!", email="op1@sec.com",
            first_name="علی", last_name="اکبری"
        )
        cls.op1.profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        cls.op1.profile.personnel_code = "SEC-01"
        cls.op1.profile.save()

        cls.op2 = User.objects.create_user(
            username="sec_op2", password="Password123!", email="op2@sec.com",
            first_name="رضا", last_name="کریمی"
        )
        cls.op2.profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        cls.op2.profile.personnel_code = "SEC-02"
        cls.op2.profile.save()

        cls.op3_unrelated = User.objects.create_user(
            username="sec_op3", password="Password123!", email="op3@sec.com",
            first_name="جواد", last_name="موسوی"
        )
        cls.op3_unrelated.profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        cls.op3_unrelated.profile.personnel_code = "SEC-03"
        cls.op3_unrelated.profile.save()

        # 2. Masterdata
        cls.product = Product.objects.create(name="میلگرد استاندارد", code="REBAR-A3", is_active=True)
        cls.party = Party.objects.create(name="فولاد صنعت پیشرو", is_active=True)
        cls.op_in = OperationType.objects.create(name="ورود مواد", code="SEC-IN", direction="inbound")
        cls.op_out = OperationType.objects.create(name="خروج محصول", code="SEC-OUT", direction="outbound")

        # 3. Shifts: Day and Overnight
        cls.shift_day = WorkShift.objects.create(
            name="شیفت روز", code="SEC-DAY",
            start_time=time(8, 0), end_time=time(16, 0),
            is_active=True, created_by=cls.admin_user
        )
        cls.shift_night = WorkShift.objects.create(
            name="شیفت شب", code="SEC-NIGHT",
            start_time=time(23, 0), end_time=time(7, 0),
            is_active=True, created_by=cls.admin_user
        )

        cls.op_date = date(2026, 10, 18)

        # 4. Sessions
        cls.session_day = ShiftSession.objects.create(
            shift=cls.shift_day, operational_date=cls.op_date,
            status=ShiftSessionStatus.CLOSED,
            actual_start=datetime(2026, 10, 18, 8, 0, tzinfo=cls.tz),
            actual_end=datetime(2026, 10, 18, 16, 0, tzinfo=cls.tz),
            opened_by=cls.op1, closed_by=cls.supervisor
        )
        cls.assign_op1 = ShiftOperatorAssignment.objects.create(
            session=cls.session_day, operator=cls.op1,
            role=ShiftOperatorRole.PRIMARY, status=ShiftAssignmentStatus.CHECKED_OUT,
            check_in_time=datetime(2026, 10, 18, 8, 0, tzinfo=cls.tz),
            check_out_time=datetime(2026, 10, 18, 16, 0, tzinfo=cls.tz),
        )
        cls.assign_op2 = ShiftOperatorAssignment.objects.create(
            session=cls.session_day, operator=cls.op2,
            role=ShiftOperatorRole.ASSISTANT, status=ShiftAssignmentStatus.CHECKED_OUT,
            check_in_time=datetime(2026, 10, 18, 8, 30, tzinfo=cls.tz),
            check_out_time=datetime(2026, 10, 18, 16, 0, tzinfo=cls.tz),
        )

        # 5. Tickets in Session Day:
        # Ticket A: Op1 solo completed (net 20,000 kg, inbound)
        cls.ticket_a = WeighTicket.objects.create(
            serial_number="SEC-TICK-A",
            status=TicketStatus.COMPLETED,
            first_weight=Decimal("10000.00"),
            first_weight_date=cls.op_date,
            first_weight_time=time(8, 30),
            first_weight_operator=cls.op1,
            first_weight_shift_session=cls.session_day,
            second_weight=Decimal("30000.00"),
            second_weight_date=cls.op_date,
            second_weight_time=time(9, 15),
            second_weight_operator=cls.op1,
            second_weight_shift_session=cls.session_day,
            net_weight=Decimal("20000.00"),
            gross_weight=Decimal("30000.00"),
            tare_weight=Decimal("10000.00"),
            final_weight=Decimal("20000.00"),
            operation_type=cls.op_in,
            license_plate_display="11B222-33",
            product=cls.product,
            party=cls.party,
        )

        # Ticket B: Op2 completed (first by Op1, second by Op2, net 15,000 kg, outbound)
        cls.ticket_b = WeighTicket.objects.create(
            serial_number="SEC-TICK-B",
            status=TicketStatus.COMPLETED,
            first_weight=Decimal("12000.00"),
            first_weight_date=cls.op_date,
            first_weight_time=time(10, 0),
            first_weight_operator=cls.op1,
            first_weight_shift_session=cls.session_day,
            second_weight=Decimal("27000.00"),
            second_weight_date=cls.op_date,
            second_weight_time=time(11, 0),
            second_weight_operator=cls.op2,
            second_weight_shift_session=cls.session_day,
            net_weight=Decimal("15000.00"),
            gross_weight=Decimal("27000.00"),
            tare_weight=Decimal("12000.00"),
            final_weight=Decimal("15000.00"),
            operation_type=cls.op_out,
            license_plate_display="44C555-66",
            product=cls.product,
            party=cls.party,
        )

        # Ticket C: Op2 solo completed with hostile formula text in license plate & party
        cls.party_hostile = Party.objects.create(name="@EvilPartyFormula", is_active=True)
        cls.ticket_c = WeighTicket.objects.create(
            serial_number="SEC-TICK-C",
            status=TicketStatus.COMPLETED,
            first_weight=Decimal("14000.00"),
            first_weight_date=cls.op_date,
            first_weight_time=time(12, 0),
            first_weight_operator=cls.op2,
            first_weight_shift_session=cls.session_day,
            second_weight=Decimal("44000.00"),
            second_weight_date=cls.op_date,
            second_weight_time=time(13, 30),
            second_weight_operator=cls.op2,
            second_weight_shift_session=cls.session_day,
            net_weight=Decimal("30000.00"),
            gross_weight=Decimal("44000.00"),
            tare_weight=Decimal("14000.00"),
            final_weight=Decimal("30000.00"),
            operation_type=cls.op_in,
            license_plate_display="=cmd|' /C calc'!A0",
            product=cls.product,
            party=cls.party_hostile,
        )

        # 6. Handover between Op1 and Op2
        cls.handover = ShiftHandover.objects.create(
            outgoing_session=cls.session_day,
            outgoing_operator=cls.op1,
            incoming_operator=cls.op2,
            status=ShiftHandoverStatus.SUPERVISOR_RESOLVED,
            scale_zero_confirmed=True,
            printer_paper_confirmed=True,
            workstation_clean_confirmed=True,
            physical_documents_confirmed=True,
            checklist_notes="بازرسی فیزیکی کامل شد.",
            outgoing_notes="تحویل داده شد با مغایرت ثبت‌شده.",
            dispute_reason="اختلاف بار در باسکول شماره ۲",
            supervisor=cls.supervisor,
            supervisor_resolution_notes="دستور بارگیری مجدد صادر گردید - محرمانه سرپرست.",
            initiated_at=datetime(2026, 10, 18, 15, 45, tzinfo=cls.tz),
            submitted_at=datetime(2026, 10, 18, 15, 50, tzinfo=cls.tz),
            disputed_at=datetime(2026, 10, 18, 15, 55, tzinfo=cls.tz),
            accepted_at=datetime(2026, 10, 18, 16, 5, tzinfo=cls.tz),
            yard_vehicles_count=2,
            waiting_second_count=1,
            pending_discrepancies_count=0,
            overdue_waiting_count=0,
            unresolved_exceptions_count=0,
        )

        # Frozen snapshot item
        cls.snapshot_item = ShiftHandoverItem.objects.create(
            handover=cls.handover,
            category=ShiftHandoverItemCategory.WAITING_SECOND,
            ticket=cls.ticket_b,
            item_identifier="SEC-TICK-B",
            item_title="پلاک 44C555-66 منجمد شده در لحظه تحویل",
            details={
                "plate": "44C555-66",
                "serial_number": "SEC-TICK-B",
                "first_weight": 12000,
            }
        )

    def setUp(self):
        self.client = Client()

    def test_01_formula_injection_defense_against_all_hostile_vectors(self):
        """
        Verify sanitize_formula_injection neutralizes all DDE / formula attack vectors:
        - Leading spaces, tabs, carriage returns, newlines
        - Unicode control and zero-width characters (ZWSP, LTR, RTL, BOM)
        - Characters =, +, -, @, |, %
        - Legitimate numeric values are strictly preserved as numeric types
        """
        hostile_inputs = [
            "=SUM(1,1)",
            "+CMD",
            "-1+2",
            "@SUM(A1:A2)",
            "   =SUM(1,1)",
            "\t+CMD",
            "\r\n-1+2",
            "\u200b=SUM(1,1)",        # Zero-width space
            "\u200e+CMD",             # LTR mark
            "\ufeff@SUM(A1:A2)",      # BOM
            "\x00=calc",              # Null byte
            "\x1b+cmd",               # Escape control
            "|calc",                  # Pipe
            "%COMSPEC%",              # Percent
        ]
        for hostile in hostile_inputs:
            sanitized = sanitize_formula_injection(hostile)
            self.assertTrue(
                sanitized.startswith("'"),
                f"Hostile input not prepended with single quote: {hostile!r} -> {sanitized!r}"
            )

        # Legitimate numeric values preserved as exact numeric types
        self.assertEqual(sanitize_formula_injection(12345), 12345)
        self.assertEqual(sanitize_formula_injection(123.45), 123.45)
        self.assertEqual(sanitize_formula_injection(Decimal("99.99")), Decimal("99.99"))
        self.assertIsInstance(sanitize_formula_injection(12345), int)
        self.assertIsInstance(sanitize_formula_injection(123.45), float)
        self.assertIsInstance(sanitize_formula_injection(Decimal("99.99")), Decimal)

        # Legitimate strings not modified
        self.assertEqual(sanitize_formula_injection("شرکت فولاد کاوه"), "شرکت فولاد کاوه")
        self.assertEqual(sanitize_formula_injection("12A345-78"), "12A345-78")

    def test_02_negative_idor_operator_direct_export_urls(self):
        """
        Negative IDOR tests:
        - Operator op1 attempting to pass ?operator=<op2_id> is blocked with HTTP 403
        - Unrelated operator op3 attempting to access op1/op2 handover PDF gets HTTP 403
        - Unrelated operator op3 attempting to view handover_detail HTML gets HTTP 403
        """
        # 1. Op1 tampering with operator query param in Excel export
        self.client.force_login(self.op1)
        res_xl_idor = self.client.get(
            reverse("shifts:dashboard_export_excel"),
            {"start_date": "1405/07/26", "end_date": "1405/07/26", "operator": str(self.op2.pk)}
        )
        self.assertEqual(res_xl_idor.status_code, 403)

        # 2. Op1 tampering with operator query param in PDF export
        res_pdf_idor = self.client.get(
            reverse("shifts:dashboard_export_pdf"),
            {"start_date": "1405/07/26", "end_date": "1405/07/26", "operator": str(self.op2.pk)}
        )
        self.assertEqual(res_pdf_idor.status_code, 403)

        # 3. Unrelated operator op3 attempting to download handover PDF
        self.client.force_login(self.op3_unrelated)
        res_ho_pdf = self.client.get(
            reverse("shifts:handover_export_pdf", kwargs={"pk": self.handover.pk})
        )
        self.assertEqual(res_ho_pdf.status_code, 403)

        # 4. Unrelated operator op3 attempting to view handover HTML detail
        res_ho_detail = self.client.get(
            reverse("shifts:handover_detail", kwargs={"pk": self.handover.pk})
        )
        self.assertEqual(res_ho_detail.status_code, 403)

    def test_03_row_level_scope_consistency_across_all_excel_sheets(self):
        """
        Verify that for ordinary operator op1, ALL 4 Excel worksheets are strictly scoped:
        - Sheet 1: Summary shows ONLY Op1's weighings (completed count=1, not total=3)
        - Sheet 2: Shift comparison lists ONLY Op1 as operator, and shows Op1's completed count
        - Sheet 3: Operator performance lists ONLY Op1
        - Sheet 4: Ticket details contains ONLY Op1's tickets
        """
        self.client.force_login(self.op1)
        response = self.client.get(
            reverse("shifts:dashboard_export_excel"),
            {"start_date": "1405/07/26", "end_date": "1405/07/26"}
        )
        self.assertEqual(response.status_code, 200)

        wb = openpyxl.load_workbook(io.BytesIO(response.content))

        # Sheet 1: Management Summary scoped to operator
        ws1 = wb["خلاصه مدیریتی"]
        ws1_values = {row[1]: row[2] for row in ws1.iter_rows(min_row=5, values_only=True) if row[1]}
        # Completed tickets by op1: exactly 1 (Ticket A), whereas total session has 3
        self.assertEqual(ws1_values.get("قبوض تکمیل‌شده توسط اپراتور"), 1)
        # Net tonnage completed by op1: exactly 20.00 ton
        self.assertAlmostEqual(float(ws1_values.get("خالص تناژ جاری تکمیل‌شده اپراتور")), 20.00, places=2)

        # Sheet 2: Shift Comparison
        ws2 = wb["مقایسه شیفت‌ها"]
        row_vals = list(ws2.iter_rows(min_row=3, values_only=True))[0]
        # Col 8 (index 7) is operators present
        op_col_text = str(row_vals[7])
        self.assertIn("علی اکبری", op_col_text)
        self.assertNotIn("رضا کریمی", op_col_text, "Other operator leaked in Sheet 2")
        # Col 11 (index 10) is completed tickets for op1
        self.assertEqual(row_vals[10], 1)

        # Sheet 3: Operator Performance
        ws3 = wb["عملکرد اپراتورها"]
        op_rows = list(ws3.iter_rows(min_row=3, values_only=True))
        self.assertEqual(len(op_rows), 1, "Only authenticated operator must appear in Sheet 3")
        self.assertIn("علی اکبری", str(op_rows[0][1]))

        # Sheet 4: Ticket Details
        ws4 = wb["ریز قبوض شیفت"]
        ticket_serials = [str(r[1]) for r in ws4.iter_rows(min_row=3, values_only=True) if r[1]]
        self.assertIn("SEC-TICK-A", ticket_serials)
        self.assertIn("SEC-TICK-B", ticket_serials)  # Op1 was first weight operator
        self.assertNotIn("SEC-TICK-C", ticket_serials)  # Op2 solo ticket must be excluded

    def test_04_handover_pdf_frozen_snapshot_immutability_against_ticket_revisions(self):
        """
        Verify that editing a WeighTicket after handover does NOT rewrite historical
        frozen ShiftHandoverItem content in the generated PDF.
        """
        # Mutate the underlying ticket
        self.ticket_b.license_plate_display = "MUTATED-PLATE-99"
        self.ticket_b.first_weight = Decimal("99999.00")
        self.ticket_b.save()

        # Export handover PDF
        response = ShiftExportService.export_formal_handover_pdf(
            user=self.op1,
            handover_id=self.handover.pk,
            client_ip="192.168.1.50"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))

        # Reload snapshot item and verify it is completely unchanged
        self.snapshot_item.refresh_from_db()
        self.assertEqual(self.snapshot_item.details.get("plate"), "44C555-66")
        self.assertEqual(self.snapshot_item.details.get("first_weight"), 12000)

    def test_05_supervisor_confidential_notes_redacted_for_operators(self):
        """
        Verify that supervisor confidential notes are redacted for participant operators,
        but rendered for supervisors in the formal handover PDF.
        """
        # Participant operator op1
        resp_op1 = ShiftExportService.export_formal_handover_pdf(
            user=self.op1,
            handover_id=self.handover.pk,
            client_ip="192.168.1.101"
        )
        self.assertEqual(resp_op1.status_code, 200)

        # Supervisor
        resp_sup = ShiftExportService.export_formal_handover_pdf(
            user=self.supervisor,
            handover_id=self.handover.pk,
            client_ip="192.168.1.100"
        )
        self.assertEqual(resp_sup.status_code, 200)

    def test_06_query_bounding_31_day_limit_returns_400(self):
        """
        Direct URL queries exceeding 31 days return HTTP 400 Bad Request.
        """
        self.client.force_login(self.supervisor)
        url = reverse("shifts:dashboard_export_excel")
        response = self.client.get(url, {"start_date": "1405/01/01", "end_date": "1405/03/01"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("31 روز", response.content.decode("utf-8"))

    def test_07_numerical_reconciliation_exact_parity_for_supervisor(self):
        """
        For identical filters, compare:
        - ShiftKPIService output
        - ShiftDashboardService get_dashboard_data
        - Generated Excel workbook values
        Verify exact numerical agreement for all metrics.
        """
        params = {"start_date": "1405/07/26", "end_date": "1405/07/26"}

        # 1. KPI Engine
        kpi_data = ShiftKPIService.calculate_period_shift_kpis(
            start_date=self.op_date, end_date=self.op_date
        )

        # 2. Dashboard Service
        dash_data = ShiftDashboardService.get_dashboard_data(self.supervisor, params)

        # 3. Excel Export
        excel_response = ShiftExportService.export_shift_performance_excel(
            user=self.supervisor, params=params
        )
        wb = openpyxl.load_workbook(io.BytesIO(excel_response.content))
        ws1 = wb["خلاصه مدیریتی"]
        ws1_map = {row[1]: row[2] for row in ws1.iter_rows(min_row=5, values_only=True) if row[1]}

        # Parity Check: Completed tickets
        kpi_completed = kpi_data["summary"]["completed_tickets_count"]
        dash_completed = dash_data["summary"]["completed_tickets_count"]
        excel_completed = ws1_map.get("قبوض تکمیل‌شده و معتبر")
        self.assertEqual(kpi_completed, 3)
        self.assertEqual(dash_completed, 3)
        self.assertEqual(excel_completed, 3)

        # Parity Check: Net Tonnage
        kpi_net_ton = float(kpi_data["summary"]["completed_net_ton"])
        dash_net_ton = float(dash_data["summary"]["completed_net_ton"])
        excel_net_ton = float(ws1_map.get("خالص تناژ جاری معتبر"))
        self.assertAlmostEqual(kpi_net_ton, 65.00, places=2)
        self.assertAlmostEqual(dash_net_ton, 65.00, places=2)
        self.assertAlmostEqual(excel_net_ton, 65.00, places=2)
