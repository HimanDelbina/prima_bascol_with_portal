"""
Official Excel & PDF Document Generation Engine for Prima Bascol Shift Management.
Phase 4.3.3: Official Excel/PDF Reporting, Handover Documents & Final Regression.

Authoritative Single Source of Truth:
- Reuses `ShiftKPIService` and `ShiftDashboardService` data models exclusively.
- Zero business formula duplication in export rendering.
- Formula injection protection for spreadsheets.
- Persian RTL shaping and local Vazirmatn font registration for ReportLab.
- Complete audit logging integration with IP tracking.
- Strict authorization and operator data segregation.
"""
import io
import os
from datetime import datetime, date, time, timedelta
from decimal import Decimal
from typing import Dict, Any, Optional, List, Tuple

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from django.utils.html import escape

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

import arabic_reshaper
from bidi.algorithm import get_display

from core.jalali import (
    format_jalali_date,
    format_jalali_datetime,
    get_today_jalali,
    get_today_gregorian,
)
from core.models import SystemSetting
from core.middleware import get_current_ip
from audit.services import log_audit
from audit.models import AuditAction
from shifts.models import (
    ShiftSession,
    ShiftHandover,
    ShiftHandoverStatus,
    ShiftHandoverItem,
    ShiftHandoverItemCategory,
)
from shifts.kpi_service import ShiftKPIService
from shifts.dashboard_service import ShiftDashboardService
from weighbridge.models import WeighTicket, TicketStatus


import unicodedata
from reportlab.pdfgen import canvas


# -----------------------------------------------------------------------------
# Security & Helper Utilities
# -----------------------------------------------------------------------------

def sanitize_formula_injection(val: Any) -> Any:
    """
    Prevents spreadsheet formula injection (CSV/Excel DDE attacks)
    by prepending a single quote to strings starting with '=', '+', '-', '@', '|', or '%'.
    Strips leading whitespace, tabs, newlines, carriage returns,
    and Unicode control/format characters (categories C* and Z*)
    before checking for formula trigger characters.
    Ensures untrusted values are stored explicitly as text while preserving legitimate numeric values.
    """
    if val is None:
        return ""
    if isinstance(val, (int, float, Decimal)):
        return val
    if isinstance(val, str):
        idx = 0
        while idx < len(val):
            ch = val[idx]
            if ch.isspace() or unicodedata.category(ch).startswith(('C', 'Z')):
                idx += 1
            else:
                break
        if idx < len(val) and val[idx] in ('=', '+', '-', '@', '|', '%'):
            return "'" + val
        return val
    return val


def shape_persian(text: Any) -> str:
    """
    Applies Arabic reshaping and bidi display algorithm for Persian text in ReportLab.
    """
    if text is None or text == "":
        return ""
    text_str = str(text)
    try:
        reshaped = arabic_reshaper.reshape(text_str)
        return get_display(reshaped)
    except Exception:
        return text_str


def get_or_register_vazirmatn_font() -> Tuple[str, str]:
    """
    Registers local Vazirmatn TrueType fonts (SIL OFL) for ReportLab.
    """
    font_name = "Vazirmatn"
    bold_font_name = "Vazirmatn-Bold"

    registered = pdfmetrics.getRegisteredFontNames()
    if font_name in registered and bold_font_name in registered:
        return font_name, bold_font_name

    reg_path = os.path.join(settings.BASE_DIR, "static", "fonts", "Vazirmatn-Regular.ttf")
    bold_path = os.path.join(settings.BASE_DIR, "static", "fonts", "Vazirmatn-Bold.ttf")

    if os.path.exists(reg_path) and os.path.exists(bold_path):
        if font_name not in registered:
            pdfmetrics.registerFont(TTFont(font_name, reg_path))
        if bold_font_name not in registered:
            pdfmetrics.registerFont(TTFont(bold_font_name, bold_path))
        return font_name, bold_font_name

    # System fallbacks if local files missing
    fallbacks = [
        ("C:/Windows/Fonts/tahoma.ttf", "C:/Windows/Fonts/tahomabd.ttf"),
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ]
    for r_p, b_p in fallbacks:
        if os.path.exists(r_p):
            try:
                b = b_p if os.path.exists(b_p) else r_p
                if font_name not in registered:
                    pdfmetrics.registerFont(TTFont(font_name, r_p))
                if bold_font_name not in registered:
                    pdfmetrics.registerFont(TTFont(bold_font_name, b))
                return font_name, bold_font_name
            except Exception:
                continue

    raise RuntimeError("فونت‌های محلی وزیرمتن یا فونت‌های فارسی سیستم‌عامل جهت تولید PDF یافت نشدند.")


class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas to dynamically compute total page count and draw
    consistent Persian RTL footers and page numbers on every PDF page.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_footer(num_pages)
            super().showPage()
        super().save()

    def draw_footer(self, page_count):
        self.saveState()
        font_name, _ = get_or_register_vazirmatn_font()
        self.setFont(font_name, 7)
        self.setFillColor(colors.HexColor('#64748B'))
        page_text = shape_persian(f"صفحه {self._pageNumber} از {page_count}")
        # Draw on the left in Persian RTL document convention
        self.drawString(25, 12, page_text)
        confidential_text = shape_persian("سامانه اتوماسیون صنعتی باسکول پریما — سند رسمی")
        self.drawRightString(self._pagesize[0] - 25, 12, confidential_text)
        self.restoreState()


# -----------------------------------------------------------------------------
# 1. Shift Performance Multi-Sheet Excel Export
# -----------------------------------------------------------------------------

class ShiftExportService:
    """
    Centralized generation service for official Excel workbooks and PDF documents.
    """

    @classmethod
    def export_shift_performance_excel(
        cls,
        user: User,
        params: Dict[str, Any],
        client_ip: Optional[str] = None
    ) -> HttpResponse:
        """
        Generates a professional 4-sheet Persian RTL Excel workbook:
        Sheet 1: Management Summary (خلاصه مدیریتی)
        Sheet 2: Shift Comparison (مقایسه شیفت‌ها)
        Sheet 3: Operator Performance (عملکرد اپراتورها)
        Sheet 4: Ticket Details (ریز قبوض شیفت)
        """
        data = ShiftDashboardService.get_dashboard_data(user, params)
        if data.get("error"):
            raise ValidationError(data["error"])

        filters = data["filters"]
        summary = data["summary"]
        sessions = data["sessions"]
        operators = data["operators"]
        handovers = data["handovers_list"]
        unattributed = data["unattributed_legacy"]
        is_supervisor = data["is_supervisor"]

        wb = Workbook()

        # Styles
        navy_header_fill = PatternFill("solid", fgColor="1E3A8A")
        sub_header_fill = PatternFill("solid", fgColor="3B82F6")
        gray_header_fill = PatternFill("solid", fgColor="475569")
        zebra_fill = PatternFill("solid", fgColor="F8FAFC")
        alert_fill = PatternFill("solid", fgColor="FEF3C7")

        font_title = Font(name="Tahoma", size=14, bold=True, color="0F172A")
        font_header = Font(name="Tahoma", size=10, bold=True, color="FFFFFF")
        font_cell = Font(name="Tahoma", size=9)
        font_cell_bold = Font(name="Tahoma", size=9, bold=True)
        font_note = Font(name="Tahoma", size=8, italic=True, color="64748B")

        thin_border_side = Side(border_style="thin", color="CBD5E1")
        cell_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)

        align_center = Alignment(horizontal="center", vertical="center")
        align_right = Alignment(horizontal="right", vertical="center")
        align_left = Alignment(horizontal="left", vertical="center")

        company_name = SystemSetting.get_settings().company_name or "شرکت فولاد پریما"

        # -------------------------------------------------------------
        # SHEET 1: Management Summary (خلاصه مدیریتی)
        # -------------------------------------------------------------
        ws1 = wb.active
        ws1.title = "خلاصه مدیریتی"
        ws1.sheet_view.rightToLeft = True

        ws1.merge_cells("A1:F1")
        if is_supervisor:
            ws1["A1"] = f"{company_name} — گزارش جامع عملکرد شیفت‌های کاری"
        else:
            ws1["A1"] = f"{company_name} — کارنامه اختصاصی عملکرد اپراتور"
        ws1["A1"].font = font_title
        ws1["A1"].alignment = align_center

        ws1.merge_cells("A2:F2")
        ws1["A2"] = (
            f"بازه عملیاتی: {filters['start_date_jalali']} الی {filters['end_date_jalali']} | "
            f"تاریخ تهیه: {get_today_jalali()} | کاربر: {user.get_full_name() or user.username}"
            + (" (کارنامه فردی اپراتور)" if not is_supervisor else " (مدیریت/سرپرست)")
        )
        ws1["A2"].font = font_note
        ws1["A2"].alignment = align_center

        # KPI Summary Table
        kpi_headers = ["ردیف", "شاخص کلیدی عملکرد (KPI)", "مقدار", "واحد اندازه‌گیری", "توضیحات و مبنای محاسبه"]
        ws1.append([])
        for col_idx, h in enumerate(kpi_headers, 1):
            cell = ws1.cell(4, col_idx, h)
            cell.fill = navy_header_fill
            cell.font = font_header
            cell.alignment = align_center
            cell.border = cell_border

        if is_supervisor:
            kpi_rows = [
                (1, "تعداد جلسات شیفت در بازه", data["total_sessions_count"], "جلسه", "جلسات شیفت فعال یا خاتمه‌یافته"),
                (2, "توزین مرحله اول", summary["first_weighings_count"], "قبض", "ورود و ثبت وزن اولیه ناوگان"),
                (3, "توزین مرحله دوم", summary["second_weighings_count"], "قبض", "خروج و ثبت وزن نهایی"),
                (4, "قبوض تکمیل‌شده و معتبر", summary["completed_tickets_count"], "قبض معتبر", "صرفاً قبوض نهایی (COMPLETED) بدون ابطالی"),
                (5, "توزین‌های مستقیم تک‌مرحله‌ای", summary["direct_weighings_count"], "قبض", "توزین‌های مستقیم و آزاد"),
                (6, "قبوض لغو شده پس از وزن دوم", summary["cancelled_after_second_weight_count"], "قبض ابطالی", "قبوض ابطال‌شده (کسر از تناژ نهایی)"),
                (7, "قبوض تک‌اپراتوری (Solo)", summary["solo_completed_count"], "قبض", "هر دو توزین توسط یک اپراتور انجام شده"),
                (8, "خالص تناژ جاری معتبر", float(summary["completed_net_ton"]), "تُن خالص", "مبنای تناژ: خالص جاری معتبر (Current Effective)"),
                (9, "تناژ ورودی (خرید و تامین)", float(summary["inbound_net_ton"]), "تُن خالص", "کالاهای ورودی کارخانه"),
                (10, "تناژ خروجی (فروش و محصول)", float(summary["outbound_net_ton"]), "تُن خالص", "کالاهای ارسالی و فروش"),
                (11, "میانگین زمان چرخه در محوطه", summary["turnaround"]["avg_minutes"], "دقیقه", "فاصله وزن اول تا وزن دوم"),
                (12, "میانه زمان چرخه (Median)", summary["turnaround"]["median_minutes"], "دقیقه", "شاخص بدون تاثیر داده‌های پرت (Outliers)"),
                (13, "خودروهای فیزیکی یکتا", summary["distinct_vehicles_completed"], "پلاک مستقل", "تفکیک تردد فیزیکی ناوگان از صدور قبوض"),
                (14, "رخدادهای خارج از شیفت", summary["out_of_shift_events_count"], "رخداد", "توزین خارج از شیفت و استثنا"),
                (15, "تحویل‌های شیفت دارای اختلاف تاریخی", data["handover_kpis"].get("historically_disputed_count", 0), "مورد", "تحویل‌های مورد اختلاف (حتی در صورت حل‌وفصل بعدی)"),
            ]
        else:
            kpi_rows = [
                (1, "تعداد جلسات شیفت منتسب به اپراتور", data["total_sessions_count"], "جلسه", "جلسات شیفت دارای تخصیص فعال"),
                (2, "توزین مرحله اول توسط اپراتور", summary["first_weighings_count"], "قبض", "ثبت وزن اولیه توسط این اپراتور"),
                (3, "توزین مرحله دوم توسط اپراتور", summary["second_weighings_count"], "قبض", "ثبت وزن نهایی توسط این اپراتور"),
                (4, "قبوض تکمیل‌شده توسط اپراتور", summary["completed_tickets_count"], "قبض معتبر", "قبوض تکمیل‌شده مرحله دوم"),
                (5, "توزین‌های مستقیم تک‌مرحله‌ای", summary["direct_weighings_count"], "قبض", "توزین مستقیم ثبت‌شده توسط اپراتور"),
                (6, "قبوض لغو شده توسط اپراتور", summary["cancelled_after_second_weight_count"], "قبض ابطالی", "قبوض لغو شده بعد از ثبت وزن دوم"),
                (7, "قبوض انفرادی (Solo) اپراتور", summary["solo_completed_count"], "قبض", "ثبت هر دو مرحله توزین توسط خود اپراتور"),
                (8, "خالص تناژ جاری تکمیل‌شده اپراتور", float(summary["completed_net_ton"]), "تُن خالص", "مجموع تناژ خالص نهایی‌شده توسط اپراتور"),
                (9, "تناژ ورودی تکمیل‌شده اپراتور", float(summary["inbound_net_ton"]), "تُن خالص", "کالاهای ورودی نهایی‌شده توسط اپراتور"),
                (10, "تناژ خروجی تکمیل‌شده اپراتور", float(summary["outbound_net_ton"]), "تُن خالص", "کالاهای ارسالی نهایی‌شده توسط اپراتور"),
                (11, "میانگین زمان چرخه در محوطه", summary["turnaround"]["avg_minutes"], "دقیقه", "میانگین زمان چرخه قبوض اپراتور"),
                (12, "میانه زمان چرخه (Median)", summary["turnaround"]["median_minutes"], "دقیقه", "میانه زمان چرخه قبوض اپراتور"),
                (13, "خودروهای فیزیکی یکتا", summary["distinct_vehicles_completed"], "پلاک مستقل", "پلاک‌های تردد ثبت‌شده توسط اپراتور"),
                (14, "رخدادهای خارج از شیفت اپراتور", summary["out_of_shift_events_count"], "رخداد", "توزین‌های خارج از شیفت منتسب به اپراتور"),
                (15, "تحویل‌های شیفت مرتبط با اپراتور", data["handover_kpis"].get("total_handovers", 0), "مورد", "تحویل‌های شیفت به عنوان تحویل‌دهنده یا گیرنده"),
            ]

        for r_idx, row in enumerate(kpi_rows, 5):
            for c_idx, val in enumerate(row, 1):
                cell = ws1.cell(r_idx, c_idx, sanitize_formula_injection(val))
                cell.font = font_cell
                cell.border = cell_border
                if c_idx in [1, 4]:
                    cell.alignment = align_center
                elif c_idx == 3:
                    cell.alignment = align_left
                    if isinstance(val, (int, float, Decimal)):
                        cell.number_format = "#,##0.00" if isinstance(val, float) else "#,##0"
                else:
                    cell.alignment = align_right
                if r_idx % 2 == 0:
                    cell.fill = zebra_fill

        ws1.column_dimensions["A"].width = 8
        ws1.column_dimensions["B"].width = 34
        ws1.column_dimensions["C"].width = 16
        ws1.column_dimensions["D"].width = 18
        ws1.column_dimensions["E"].width = 46

        # -------------------------------------------------------------
        # SHEET 2: Shift Comparison (مقایسه شیفت‌ها)
        # -------------------------------------------------------------
        ws2 = wb.create_sheet(title="مقایسه شیفت‌ها")
        ws2.sheet_view.rightToLeft = True

        shift_headers = [
            "ردیف", "نام شیفت", "کد شیفت", "شبانه", "تاریخ عملیاتی",
            "ساعت شروع مقرر", "ساعت پایان مقرر", "اپراتورهای حاضر",
            "وزن اول", "وزن دوم", "قبوض معتبر", "تناژ خالص (تُن)",
            "میانگین چرخه (دقیقه)", "میانه چرخه (دقیقه)", "وضعیت تحویل شیفت"
        ]

        ws2.append([])
        for col_idx, h in enumerate(shift_headers, 1):
            cell = ws2.cell(2, col_idx, h)
            cell.fill = navy_header_fill
            cell.font = font_header
            cell.alignment = align_center
            cell.border = cell_border

        for s_idx, s in enumerate(sessions, 1):
            if is_supervisor:
                op_names = ", ".join(op["full_name"] for op in s.get("operators", []))
            else:
                op_names = user.get_full_name() or user.username
            row_vals = [
                s_idx,
                s["shift_name"],
                s["shift_code"],
                "بله" if s["is_overnight"] else "خیر",
                s["operational_date_jalali"],
                s.get("actual_start").strftime("%H:%M") if s.get("actual_start") else "-",
                s.get("actual_end").strftime("%H:%M") if s.get("actual_end") else "در حال کار",
                op_names or "تعیین‌نشده",
                s["first_weighings_count"],
                s["second_weighings_count"],
                s["completed_tickets_count"],
                float(s["completed_net_ton"]),
                s["turnaround"]["avg_minutes"],
                s["turnaround"]["median_minutes"],
                s["outgoing_handover"]["status"] if s["outgoing_handover"]["exists"] else "بدون تحویل",
            ]
            row_num = s_idx + 2
            for c_idx, val in enumerate(row_vals, 1):
                cell = ws2.cell(row_num, c_idx, sanitize_formula_injection(val))
                cell.font = font_cell
                cell.border = cell_border
                if c_idx in [1, 3, 4, 5, 6, 7, 9, 10, 11, 13, 14, 15]:
                    cell.alignment = align_center
                elif c_idx == 12:
                    cell.alignment = align_left
                    cell.number_format = "#,##0.00"
                else:
                    cell.alignment = align_right

        ws2.freeze_panes = "A3"
        for col_letter, w in zip(["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O"],
                                 [8, 20, 12, 10, 16, 14, 14, 28, 12, 12, 14, 16, 18, 18, 18]):
            ws2.column_dimensions[col_letter].width = w

        # -------------------------------------------------------------
        # SHEET 3: Operator Performance (عملکرد اپراتورها)
        # -------------------------------------------------------------
        ws3 = wb.create_sheet(title="عملکرد اپراتورها")
        ws3.sheet_view.rightToLeft = True

        op_headers = [
            "ردیف", "نام و نام خانوادگی", "نام کاربری", "نقش سازمانی",
            "توزین اول", "توزین دوم", "قبوض Solo", "مجموع تسک‌ها",
            "ساعات حضور معتبر", "بهره‌وری (تسک/ساعت)", "تناژ خالص (تُن)", "استثنائات شیفت"
        ]

        ws3.append([])
        for col_idx, h in enumerate(op_headers, 1):
            cell = ws3.cell(2, col_idx, h)
            cell.fill = navy_header_fill
            cell.font = font_header
            cell.alignment = align_center
            cell.border = cell_border

        for op_idx, op in enumerate(operators, 1):
            row_vals = [
                op_idx,
                op["full_name"],
                op["username"],
                op["role"],
                op["first_weights"],
                op["second_weights"],
                op["solo_completed"],
                op["total_tasks"],
                float(op["attendance_hours"]),
                op["tasks_per_hour"],
                float(op["completed_net_ton"]),
                op["shift_exceptions_count"],
            ]
            row_num = op_idx + 2
            for c_idx, val in enumerate(row_vals, 1):
                cell = ws3.cell(row_num, c_idx, sanitize_formula_injection(val))
                cell.font = font_cell
                cell.border = cell_border
                if c_idx in [1, 3, 4, 5, 6, 7, 8, 10, 12]:
                    cell.alignment = align_center
                elif c_idx in [9, 11]:
                    cell.alignment = align_left
                    cell.number_format = "#,##0.00"
                else:
                    cell.alignment = align_right

        ws3.freeze_panes = "A3"
        for col_letter, w in zip(["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"],
                                 [8, 24, 16, 16, 12, 12, 12, 14, 18, 18, 16, 14]):
            ws3.column_dimensions[col_letter].width = w

        # -------------------------------------------------------------
        # SHEET 4: Ticket Details (ریز قبوض شیفت)
        # -------------------------------------------------------------
        ws4 = wb.create_sheet(title="ریز قبوض شیفت")
        ws4.sheet_view.rightToLeft = True

        ticket_headers = [
            "ردیف", "شماره قبض", "پلاک خودرو", "طرف حساب", "محصول", "نوع عملیات",
            "تاریخ وزن اول", "زمان وزن اول", "اپراتور وزن اول", "شیفت وزن اول",
            "تاریخ وزن دوم", "زمان وزن دوم", "اپراتور وزن دوم", "شیفت وزن دوم",
            "خالص معتبر (Kg)", "خالص معتبر (تُن)", "وضعیت", "تعداد بازنگری"
        ]

        ws4.append([])
        for col_idx, h in enumerate(ticket_headers, 1):
            cell = ws4.cell(2, col_idx, h)
            cell.fill = navy_header_fill
            cell.font = font_header
            cell.alignment = align_center
            cell.border = cell_border

        # Fetch tickets within the authorized scope of sessions
        session_ids = [s["session_id"] for s in sessions]
        tickets_qs = WeighTicket.objects.filter(
            Q(first_weight_shift_session_id__in=session_ids) |
            Q(second_weight_shift_session_id__in=session_ids)
        ).select_related(
            "first_weight_operator",
            "second_weight_operator",
            "first_weight_shift_session__shift",
            "second_weight_shift_session__shift",
            "party",
            "product",
            "operation_type",
        ).order_by("-id")

        # Operator self-service restriction
        if not is_supervisor:
            tickets_qs = tickets_qs.filter(
                Q(first_weight_operator=user) | Q(second_weight_operator=user)
            )

        for t_idx, t in enumerate(tickets_qs[:2000], 1):
            first_shift_str = t.first_weight_shift_session.shift.name if t.first_weight_shift_session else "-"
            second_shift_str = t.second_weight_shift_session.shift.name if t.second_weight_shift_session else "-"
            net_ton = float(ShiftKPIService.kg_to_ton(t.net_weight))

            row_vals = [
                t_idx,
                t.serial_number,
                t.license_plate_display,
                t.party.name if t.party else "-",
                t.product.name if t.product else "-",
                t.operation_type.name if t.operation_type else "-",
                format_jalali_date(t.first_weight_date) if t.first_weight_date else "-",
                t.first_weight_time.strftime("%H:%M") if t.first_weight_time else "-",
                t.first_weight_operator.get_full_name() or t.first_weight_operator.username if t.first_weight_operator else "-",
                first_shift_str,
                format_jalali_date(t.second_weight_date) if t.second_weight_date else "-",
                t.second_weight_time.strftime("%H:%M") if t.second_weight_time else "-",
                t.second_weight_operator.get_full_name() or t.second_weight_operator.username if t.second_weight_operator else "-",
                second_shift_str,
                float(t.net_weight or 0),
                net_ton,
                t.get_status_display(),
                t.current_revision_number,
            ]
            row_num = t_idx + 2
            for c_idx, val in enumerate(row_vals, 1):
                cell = ws4.cell(row_num, c_idx, sanitize_formula_injection(val))
                cell.font = font_cell
                cell.border = cell_border
                if c_idx in [1, 2, 3, 7, 8, 10, 11, 12, 14, 17, 18]:
                    cell.alignment = align_center
                elif c_idx in [15, 16]:
                    cell.alignment = align_left
                    cell.number_format = "#,##0.00" if c_idx == 16 else "#,##0"
                else:
                    cell.alignment = align_right

        ws4.freeze_panes = "A3"
        for col_letter, w in zip(
            ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R"],
            [8, 16, 16, 24, 20, 16, 14, 12, 18, 18, 14, 12, 18, 18, 16, 16, 16, 12]
        ):
            ws4.column_dimensions[col_letter].width = w

        # Audit Logging
        log_audit(
            action=AuditAction.PRINT,
            model_name="ShiftSession",
            record_id=f"PERIOD_{filters['start_date']}_{filters['end_date']}",
            record_repr=f"خروجی اکسل عملکرد شیفت ({filters['start_date_jalali']} الی {filters['end_date_jalali']})",
            new_values={
                "report_type": "EXCEL_SHIFT_PERFORMANCE",
                "start_date": str(filters["start_date"]),
                "end_date": str(filters["end_date"]),
                "sessions_count": len(sessions),
                "is_supervisor": is_supervisor,
            },
            user=user,
            ip_address=client_ip,
            source="WEB"
        )

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        filename = f"shift_performance_{filters['start_date_jalali'].replace('/', '')}_{filters['end_date_jalali'].replace('/', '')}.xlsx"
        response = HttpResponse(
            output.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    # -------------------------------------------------------------
    # 2. Formal Shift Handover Official PDF (A4 Portrait)
    # -------------------------------------------------------------
    @classmethod
    def export_formal_handover_pdf(
        cls,
        user: User,
        handover_id: int,
        client_ip: Optional[str] = None
    ) -> HttpResponse:
        """
        Generates an official, printable A4 Persian RTL Handover Document.
        Distinguishes frozen historical snapshot from live state.
        Includes equipment checklist, dispute resolution, and triple signature spaces.
        """
        handover = ShiftHandover.objects.select_related(
            "outgoing_session__shift",
            "incoming_session__shift",
            "outgoing_operator",
            "incoming_operator",
            "supervisor",
        ).filter(pk=handover_id).first()

        if not handover:
            raise ValidationError("تحویل شیفت مورد نظر یافت نشد.")

        # Security check:
        # Management or supervisor can view. Outgoing or incoming operator can view.
        has_access, is_supervisor = ShiftDashboardService.check_user_dashboard_access(user)
        if not has_access:
            raise PermissionDenied("شما مجوز دسترسی به این سند را ندارید.")

        is_participant = user in [handover.outgoing_operator, handover.incoming_operator]
        if not (is_supervisor or is_participant):
            raise PermissionDenied("اپراتورها تنها مجاز به مشاهده اسناد تحویل مربوط به خود می‌باشند.")

        font_regular, font_bold = get_or_register_vazirmatn_font()

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=25,
            leftMargin=25,
            topMargin=25,
            bottomMargin=25
        )

        elements = []
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            'HandoverTitle', fontName=font_bold, fontSize=13, leading=17,
            alignment=1, textColor=colors.HexColor('#0F172A')
        )
        sub_style = ParagraphStyle(
            'HandoverSub', fontName=font_regular, fontSize=8, leading=12,
            alignment=1, textColor=colors.HexColor('#475569')
        )
        header_cell_style = ParagraphStyle(
            'HandoverHeaderCell', fontName=font_bold, fontSize=7.5, leading=10,
            alignment=1, textColor=colors.whitesmoke
        )
        body_cell_style = ParagraphStyle(
            'HandoverBodyCell', fontName=font_regular, fontSize=7, leading=9,
            alignment=1, textColor=colors.HexColor('#0F172A')
        )
        notice_style = ParagraphStyle(
            'HandoverNotice', fontName=font_regular, fontSize=7, leading=9.5,
            alignment=2, textColor=colors.HexColor('#334155')
        )

        company_name = SystemSetting.get_settings().company_name or "شرکت فولاد پریما"

        # Document Header
        header_text = f"{company_name} — برگه رسمی تحویل و تحول شیفت کاری"
        elements.append(Paragraph(escape(shape_persian(header_text)), title_style))
        elements.append(Spacer(1, 3))

        meta_info = (
            f"شناسه تحویل: #{handover.pk} | تاریخ عملیاتی: {format_jalali_date(handover.outgoing_session.operational_date)} | "
            f"زمان تهیه سند: {get_today_jalali()} {datetime.now().strftime('%H:%M')}"
        )
        elements.append(Paragraph(escape(shape_persian(meta_info)), sub_style))
        elements.append(Spacer(1, 8))

        # Metadata Summary Table (Right to Left ordering)
        status_display = handover.get_status_display()
        if handover.status == ShiftHandoverStatus.DISPUTED or handover.disputed_at:
            status_display += " (دارای سابقه اختلاف)"

        outgoing_shift_name = handover.outgoing_session.shift.name
        incoming_shift_name = handover.incoming_session.shift.name if handover.incoming_session else "نامشخص / شیفت بعد"

        meta_rows = [
            [
                Paragraph(escape(shape_persian(f"شیفت تحویل‌گیرنده: {incoming_shift_name}")), body_cell_style),
                Paragraph(escape(shape_persian(f"شیفت تحویل‌دهنده: {outgoing_shift_name}")), body_cell_style),
                Paragraph(escape(shape_persian(f"وضعیت جاری سند: {status_display}")), body_cell_style),
            ],
            [
                Paragraph(escape(shape_persian(f"تحویل‌گیرنده: {handover.incoming_operator.get_full_name() or handover.incoming_operator.username if handover.incoming_operator else 'تعیین‌نشده'}")), body_cell_style),
                Paragraph(escape(shape_persian(f"تحویل‌دهنده: {handover.outgoing_operator.get_full_name() or handover.outgoing_operator.username}")), body_cell_style),
                Paragraph(escape(shape_persian(f"زمان ارسال: {format_jalali_datetime(handover.submitted_at) if handover.submitted_at else 'ارسال‌نشده'}")), body_cell_style),
            ]
        ]
        meta_table = Table(meta_rows, colWidths=[180, 180, 180])
        meta_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
            ('BORDER', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('PADDING', (0, 0), (-1, -1), 4),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))
        elements.append(meta_table)
        elements.append(Spacer(1, 8))

        # Equipment Checklist Table
        elements.append(Paragraph(escape(shape_persian("چک‌لیست تجهیزات، سخت‌افزار و ایستگاه کاری")), title_style))
        elements.append(Spacer(1, 4))

        checklist_headers = [
            Paragraph(escape(shape_persian("توضیحات")), header_cell_style),
            Paragraph(escape(shape_persian("وضعیت تایید")), header_cell_style),
            Paragraph(escape(shape_persian("مورد کنترلی")), header_cell_style),
            Paragraph(escape(shape_persian("ردیف")), header_cell_style),
        ]

        def bool_to_check(val):
            return "تایید و سالم" if val else "عدم تایید / دارای نقص"

        checklist_data = [
            checklist_headers,
            [
                Paragraph(escape(shape_persian("بررسی وزن صفر و عدم وجود بار بر روی پل")), body_cell_style),
                Paragraph(escape(shape_persian(bool_to_check(handover.scale_zero_confirmed))), body_cell_style),
                Paragraph(escape(shape_persian("صفر باسکول و پایدار بودن اندیکاتور")), body_cell_style),
                Paragraph(escape(shape_persian("۱")), body_cell_style),
            ],
            [
                Paragraph(escape(shape_persian("بررسی رول کاغذ پرینتر و چاپ خوانا")), body_cell_style),
                Paragraph(escape(shape_persian(bool_to_check(handover.printer_paper_confirmed))), body_cell_style),
                Paragraph(escape(shape_persian("کاغذ پرینتر و کارتریج چاپ قبوض")), body_cell_style),
                Paragraph(escape(shape_persian("۲")), body_cell_style),
            ],
            [
                Paragraph(escape(shape_persian("تحویل میز کار، کیوسک و نظافت عمومی")), body_cell_style),
                Paragraph(escape(shape_persian(bool_to_check(handover.workstation_clean_confirmed))), body_cell_style),
                Paragraph(escape(shape_persian("نظافت ایستگاه کاری و تجهیزات")), body_cell_style),
                Paragraph(escape(shape_persian("۳")), body_cell_style),
            ],
            [
                Paragraph(escape(shape_persian("بررسی بارنامه‌ها، مجوزها و لاگ‌بوک")), body_cell_style),
                Paragraph(escape(shape_persian(bool_to_check(handover.physical_documents_confirmed))), body_cell_style),
                Paragraph(escape(shape_persian("اسناد فیزیکی و دفاتر ثبت دستی")), body_cell_style),
                Paragraph(escape(shape_persian("۴")), body_cell_style),
            ],
        ]
        chk_table = Table(checklist_data, colWidths=[200, 130, 180, 30])
        chk_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
            ('BORDER', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('PADDING', (0, 0), (-1, -1), 3),
        ]))
        elements.append(chk_table)
        elements.append(Spacer(1, 8))

        # Operational Snapshot Summary (Frozen Snapshot)
        elements.append(Paragraph(escape(shape_persian("اسنپ‌شات عملیاتی منجمدشده در لحظه تحویل (Frozen Snapshot)")), title_style))
        elements.append(Spacer(1, 4))

        snapshot_summary_rows = [
            [
                Paragraph(escape(shape_persian(f"تعداد قبوض در انتظار توزین دوم: {handover.waiting_second_count}")), body_cell_style),
                Paragraph(escape(shape_persian(f"تعداد کل خودروهای حاضر در محوطه: {handover.yard_vehicles_count}")), body_cell_style),
            ]
        ]
        snap_table = Table(snapshot_summary_rows, colWidths=[270, 270])
        snap_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#EFF6FF')),
            ('BORDER', (0, 0), (-1, -1), 0.5, colors.HexColor('#93C5FD')),
            ('PADDING', (0, 0), (-1, -1), 5),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))
        elements.append(snap_table)
        elements.append(Spacer(1, 8))

        # Snapshot Items Table (up to 20 items)
        items_qs = handover.items.all().order_by("category", "id")
        if items_qs.exists():
            item_headers = [
                Paragraph(escape(shape_persian("توضیحات و شناسه")), header_cell_style),
                Paragraph(escape(shape_persian("وزن اول (Kg)")), header_cell_style),
                Paragraph(escape(shape_persian("پلاک خودرو")), header_cell_style),
                Paragraph(escape(shape_persian("دسته‌بندی رکورد")), header_cell_style),
                Paragraph(escape(shape_persian("ردیف")), header_cell_style),
            ]
            items_table_data = [item_headers]
            for it_idx, it in enumerate(items_qs[:25], 1):
                w_str = "-"
                plate_str = "-"
                desc_str = it.item_title or it.item_identifier
                if it.details and isinstance(it.details, dict):
                    if it.details.get("first_weight") is not None:
                        try:
                            w_str = str(int(float(it.details["first_weight"])))
                        except (ValueError, TypeError):
                            w_str = str(it.details["first_weight"])
                    plate_str = str(it.details.get("plate") or it.details.get("license_plate") or "-")
                    if it.details.get("serial_number"):
                        desc_str = f"قبض #{it.details['serial_number']} - {desc_str}"

                items_table_data.append([
                    Paragraph(escape(shape_persian(desc_str[:35])), body_cell_style),
                    Paragraph(escape(shape_persian(w_str)), body_cell_style),
                    Paragraph(escape(shape_persian(plate_str)), body_cell_style),
                    Paragraph(escape(shape_persian(it.get_category_display())), body_cell_style),
                    Paragraph(escape(shape_persian(str(it_idx))), body_cell_style),
                ])
            it_table = Table(items_table_data, colWidths=[180, 80, 110, 140, 30])
            it_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3B82F6')),
                ('BORDER', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('PADDING', (0, 0), (-1, -1), 2.5),
            ]))
            elements.append(it_table)
            elements.append(Spacer(1, 8))

        # Supervisor Intervention & Dispute Box (If applicable and authorized)
        if is_supervisor and (handover.dispute_reason or handover.supervisor_resolution_notes):
            elements.append(Paragraph(escape(shape_persian("سوابق اختلاف و تصمیم سرپرست")), title_style))
            elements.append(Spacer(1, 3))
            disp_rows = [
                [Paragraph(escape(shape_persian(f"علت اختلاف اپراتور: {handover.dispute_reason or 'ثبت نشده'}")), body_cell_style)],
                [Paragraph(escape(shape_persian(f"دستورات سرپرست ({handover.supervisor.username if handover.supervisor else '-'}): {handover.supervisor_resolution_notes or 'در انتظار تصمیم'}")), body_cell_style)],
            ]
            disp_table = Table(disp_rows, colWidths=[540])
            disp_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FEF3C7')),
                ('BORDER', (0, 0), (-1, -1), 0.5, colors.HexColor('#F59E0B')),
                ('PADDING', (0, 0), (-1, -1), 4),
            ]))
            elements.append(disp_table)
            elements.append(Spacer(1, 8))
        elif not is_supervisor and (handover.dispute_reason or handover.supervisor_resolution_notes):
            elements.append(Paragraph(escape(shape_persian("سوابق اختلاف و تصمیم سرپرست")), title_style))
            elements.append(Spacer(1, 3))
            disp_rows = [
                [Paragraph(escape(shape_persian(f"علت اختلاف اپراتور: {handover.dispute_reason or 'ثبت نشده'}")), body_cell_style)],
                [Paragraph(escape(shape_persian("دستورات و تصمیم سرپرست: [محرمانه - فقط سرپرست]")), body_cell_style)],
            ]
            disp_table = Table(disp_rows, colWidths=[540])
            disp_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FEF3C7')),
                ('BORDER', (0, 0), (-1, -1), 0.5, colors.HexColor('#F59E0B')),
                ('PADDING', (0, 0), (-1, -1), 4),
            ]))
            elements.append(disp_table)
            elements.append(Spacer(1, 8))

        # Official Legal Notice
        notice_box = [
            [
                Paragraph(
                    escape(shape_persian(
                        "تذکر ممیزی و قانونی: این سند نسخه چاپی سوابق رسمی ثبت‌شده در پایگاه داده سامانه است. "
                        "امضای فیزیکی مندرج در ذیل این برگه جنبه تأیید پرسنلی و عملیاتی داشته و به عنوان امضای دیجیتال رمزنگاری‌شده تلقی نمی‌گردد. "
                        "اصالت سند صرفاً با وضعیت رسمی ثبت‌شده در سیستم معتبر است."
                    )),
                    notice_style
                )
            ]
        ]
        nt_table = Table(notice_box, colWidths=[540])
        nt_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F1F5F9')),
            ('BORDER', (0, 0), (-1, -1), 0.5, colors.HexColor('#94A3B8')),
            ('PADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(nt_table)
        elements.append(Spacer(1, 14))

        # Triple Signature Spaces
        sig_headers = [
            Paragraph(escape(shape_persian("سرپرست شیفت / ناظر")), header_cell_style),
            Paragraph(escape(shape_persian("اپراتور تحویل‌گیرنده")), header_cell_style),
            Paragraph(escape(shape_persian("اپراتور تحویل‌دهنده")), header_cell_style),
        ]
        sig_body = [
            sig_headers,
            [
                Paragraph(escape(shape_persian("نام: .........................<br/><br/>تاریخ: .........................<br/><br/>امضا: .........................")), body_cell_style),
                Paragraph(escape(shape_persian(f"نام: {handover.incoming_operator.get_full_name() or handover.incoming_operator.username if handover.incoming_operator else '.....................'}<br/><br/>تاریخ: .........................<br/><br/>امضا: .........................")), body_cell_style),
                Paragraph(escape(shape_persian(f"نام: {handover.outgoing_operator.get_full_name() or handover.outgoing_operator.username}<br/><br/>تاریخ: .........................<br/><br/>امضا: .........................")), body_cell_style),
            ]
        ]
        sig_table = Table(sig_body, colWidths=[180, 180, 180])
        sig_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#475569')),
            ('BORDER', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('PADDING', (0, 0), (-1, -1), 6),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        elements.append(KeepTogether(sig_table))

        # Build Document
        doc.build(elements, canvasmaker=NumberedCanvas)
        buffer.seek(0)

        # Audit Logging
        log_audit(
            action=AuditAction.PRINT,
            model_name="ShiftHandover",
            record_id=str(handover.pk),
            record_repr=f"چاپ برگه تحویل شیفت #{handover.pk}",
            new_values={
                "report_type": "PDF_FORMAL_HANDOVER",
                "handover_id": handover.pk,
                "status": handover.status,
                "is_supervisor": is_supervisor,
            },
            user=user,
            ip_address=client_ip,
            source="WEB"
        )

        filename = f"shift_handover_{handover.pk}.pdf"
        response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    # -------------------------------------------------------------
    # 3. Management Summary PDF (A4 Landscape)
    # -------------------------------------------------------------
    @classmethod
    def export_management_summary_pdf(
        cls,
        user: User,
        params: Dict[str, Any],
        client_ip: Optional[str] = None
    ) -> HttpResponse:
        """
        Generates an executive management shift performance PDF report (A4 Landscape).
        Contains period overview, shift comparisons, operator activity, and attribution notes.
        """
        data = ShiftDashboardService.get_dashboard_data(user, params)
        if data.get("error"):
            raise ValidationError(data["error"])

        filters = data["filters"]
        summary = data["summary"]
        sessions = data["sessions"]
        operators = data["operators"]
        is_supervisor = data["is_supervisor"]

        font_regular, font_bold = get_or_register_vazirmatn_font()

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(A4),
            rightMargin=20,
            leftMargin=20,
            topMargin=20,
            bottomMargin=20
        )

        elements = []
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            'PdfTitle', fontName=font_bold, fontSize=13, leading=17,
            alignment=1, textColor=colors.HexColor('#0F172A')
        )
        sub_style = ParagraphStyle(
            'PdfSub', fontName=font_regular, fontSize=8, leading=11,
            alignment=1, textColor=colors.HexColor('#475569')
        )
        header_cell_style = ParagraphStyle(
            'PdfHeaderCell', fontName=font_bold, fontSize=7, leading=9,
            alignment=1, textColor=colors.whitesmoke
        )
        body_cell_style = ParagraphStyle(
            'PdfBodyCell', fontName=font_regular, fontSize=6.5, leading=8.5,
            alignment=1, textColor=colors.HexColor('#0F172A')
        )
        section_style = ParagraphStyle(
            'PdfSection', fontName=font_bold, fontSize=9.5, leading=13,
            alignment=2, textColor=colors.HexColor('#1E3A8A')
        )
        note_style = ParagraphStyle(
            'PdfNote', fontName=font_regular, fontSize=6.5, leading=8.5,
            alignment=2, textColor=colors.HexColor('#64748B')
        )

        company_name = SystemSetting.get_settings().company_name or "شرکت فولاد پریما"

        # Document Header
        if is_supervisor:
            title_text = f"{company_name} — گزارش مدیریتی و بیلان عملیاتی شیفت‌های کاری"
            sub_text = (
                f"بازه عملیاتی: {filters['start_date_jalali']} الی {filters['end_date_jalali']} | "
                f"تاریخ تهیه: {get_today_jalali()} | تهیه‌کننده: {user.get_full_name() or user.username} (مدیریت/سرپرست)"
            )
        else:
            title_text = f"{company_name} — کارنامه عملکرد و بیلان کاری اپراتور"
            sub_text = (
                f"بازه عملیاتی: {filters['start_date_jalali']} الی {filters['end_date_jalali']} | "
                f"تاریخ تهیه: {get_today_jalali()} | اپراتور: {user.get_full_name() or user.username} (گزارش فردی)"
            )
        elements.append(Paragraph(escape(shape_persian(title_text)), title_style))
        elements.append(Spacer(1, 3))
        elements.append(Paragraph(escape(shape_persian(sub_text)), sub_style))
        elements.append(Spacer(1, 8))

        # Summary Metrics Strip (RTL ordered: Col 3 to Col 0)
        summary_headers = [
            Paragraph(escape(shape_persian("شاخص‌های بهره‌وری")), header_cell_style),
            Paragraph(escape(shape_persian("زمان چرخه در محوطه")), header_cell_style),
            Paragraph(escape(shape_persian("خالص تناژ جاری معتبر")), header_cell_style),
            Paragraph(escape(shape_persian("حجم عملیات توزین")), header_cell_style),
        ]
        summary_content = [
            summary_headers,
            [
                Paragraph(escape(shape_persian(f"ناوگان فیزیکی یکتا: {summary['distinct_vehicles_completed']}<br/>رخدادهای خارج از شیفت: {summary['out_of_shift_events_count']}<br/>اختلافات تحویل: {data['handover_kpis'].get('historically_disputed_count', 0)}")), body_cell_style),
                Paragraph(escape(shape_persian(f"میانگین چرخه: {summary['turnaround']['avg_minutes']} دقیقه<br/>میانه (Median): {summary['turnaround']['median_minutes']} دقیقه<br/>دامنه: {summary['turnaround']['min_minutes']} تا {summary['turnaround']['max_minutes']} دقیقه")), body_cell_style),
                Paragraph(escape(shape_persian(f"مجموع خالص: {summary['completed_net_ton']} تُن<br/>ورودی: {summary['inbound_net_ton']} تُن<br/>خروجی: {summary['outbound_net_ton']} تُن")), body_cell_style),
                Paragraph(escape(shape_persian(f"توزین مرحله اول: {summary['first_weighings_count']}<br/>قبوض تکمیل‌شده: {summary['completed_tickets_count']}<br/>مستقیم: {summary['direct_weighings_count']} | ابطالی: {summary['cancelled_after_second_weight_count']}")), body_cell_style),
            ]
        ]
        sm_table = Table(summary_content, colWidths=[200, 200, 200, 200])
        sm_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
            ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#F8FAFC')),
            ('BORDER', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('PADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(sm_table)
        elements.append(Spacer(1, 10))

        # Shift Comparison Table (RTL ordered)
        elements.append(Paragraph(escape(shape_persian("جدول مقایسه‌ای جلسات شیفت در بازه")), section_style))
        elements.append(Spacer(1, 4))

        shift_headers = [
            Paragraph(escape(shape_persian("وضعیت تحویل")), header_cell_style),
            Paragraph(escape(shape_persian("میانه چرخه")), header_cell_style),
            Paragraph(escape(shape_persian("میانگین چرخه")), header_cell_style),
            Paragraph(escape(shape_persian("تناژ خالص (تُن)")), header_cell_style),
            Paragraph(escape(shape_persian("قبوض معتبر")), header_cell_style),
            Paragraph(escape(shape_persian("وزن دوم")), header_cell_style),
            Paragraph(escape(shape_persian("وزن اول")), header_cell_style),
            Paragraph(escape(shape_persian("اپراتورها")), header_cell_style),
            Paragraph(escape(shape_persian("ساعات واقعی")), header_cell_style),
            Paragraph(escape(shape_persian("تاریخ عملیاتی")), header_cell_style),
            Paragraph(escape(shape_persian("شیفت")), header_cell_style),
            Paragraph(escape(shape_persian("ردیف")), header_cell_style),
        ]
        shift_data = [shift_headers]
        for idx, s in enumerate(sessions[:30], 1):
            op_names = ", ".join(op["full_name"] for op in s.get("operators", []))
            shift_title = s["shift_name"]
            if s["is_overnight"]:
                shift_title += " (شبانه)"
            h_stat = s["outgoing_handover"]["status"] if s["outgoing_handover"]["exists"] else "-"
            shift_data.append([
                Paragraph(escape(shape_persian(h_stat)), body_cell_style),
                Paragraph(escape(shape_persian(str(s["turnaround"]["median_minutes"] or "-"))), body_cell_style),
                Paragraph(escape(shape_persian(str(s["turnaround"]["avg_minutes"] or "-"))), body_cell_style),
                Paragraph(escape(shape_persian(str(s["completed_net_ton"]))), body_cell_style),
                Paragraph(escape(shape_persian(str(s["completed_tickets_count"]))), body_cell_style),
                Paragraph(escape(shape_persian(str(s["second_weighings_count"]))), body_cell_style),
                Paragraph(escape(shape_persian(str(s["first_weighings_count"]))), body_cell_style),
                Paragraph(escape(shape_persian(op_names[:25])), body_cell_style),
                Paragraph(escape(shape_persian(s["actual_start"].strftime("%H:%M") if s["actual_start"] else "-")), body_cell_style),
                Paragraph(escape(shape_persian(s["operational_date_jalali"])), body_cell_style),
                Paragraph(escape(shape_persian(shift_title)), body_cell_style),
                Paragraph(escape(shape_persian(str(idx))), body_cell_style),
            ])
        sh_table = Table(shift_data, colWidths=[80, 55, 55, 65, 50, 45, 45, 145, 60, 75, 100, 25])
        sh_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3B82F6')),
            ('BORDER', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('PADDING', (0, 0), (-1, -1), 2.5),
        ]))
        elements.append(sh_table)
        elements.append(Spacer(1, 10))

        # Operator Performance Table
        elements.append(Paragraph(escape(shape_persian("جدول شاخص‌های فعالیت و بهره‌وری اپراتورها")), section_style))
        elements.append(Spacer(1, 4))

        op_headers = [
            Paragraph(escape(shape_persian("استثنائات")), header_cell_style),
            Paragraph(escape(shape_persian("تناژ خالص (تُن)")), header_cell_style),
            Paragraph(escape(shape_persian("بهره‌وری (تسک/ساعت)")), header_cell_style),
            Paragraph(escape(shape_persian("ساعات حضور")), header_cell_style),
            Paragraph(escape(shape_persian("مجموع تسک")), header_cell_style),
            Paragraph(escape(shape_persian("قبوض Solo")), header_cell_style),
            Paragraph(escape(shape_persian("وزن دوم")), header_cell_style),
            Paragraph(escape(shape_persian("وزن اول")), header_cell_style),
            Paragraph(escape(shape_persian("نقش")), header_cell_style),
            Paragraph(escape(shape_persian("نام و نام خانوادگی")), header_cell_style),
            Paragraph(escape(shape_persian("ردیف")), header_cell_style),
        ]
        op_data = [op_headers]
        for o_idx, op in enumerate(operators, 1):
            op_data.append([
                Paragraph(escape(shape_persian(str(op["shift_exceptions_count"]))), body_cell_style),
                Paragraph(escape(shape_persian(str(op["completed_net_ton"]))), body_cell_style),
                Paragraph(escape(shape_persian(str(op["tasks_per_hour"]))), body_cell_style),
                Paragraph(escape(shape_persian(str(op["attendance_hours"]))), body_cell_style),
                Paragraph(escape(shape_persian(str(op["total_tasks"]))), body_cell_style),
                Paragraph(escape(shape_persian(str(op["solo_completed"]))), body_cell_style),
                Paragraph(escape(shape_persian(str(op["second_weights"]))), body_cell_style),
                Paragraph(escape(shape_persian(str(op["first_weights"]))), body_cell_style),
                Paragraph(escape(shape_persian(op["role"])), body_cell_style),
                Paragraph(escape(shape_persian(op["full_name"])), body_cell_style),
                Paragraph(escape(shape_persian(str(o_idx))), body_cell_style),
            ])
        op_table = Table(op_data, colWidths=[65, 85, 100, 75, 65, 65, 60, 60, 75, 120, 25])
        op_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#475569')),
            ('BORDER', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('PADDING', (0, 0), (-1, -1), 3),
        ]))
        elements.append(op_table)
        elements.append(Spacer(1, 8))

        # Footnotes & Attribution
        elements.append(Paragraph(escape(shape_persian(
            "پی‌نوشت ممیزی: کلیه ارقام تناژ بر اساس خالص جاری معتبر قبوض محاسبه شده و قبوض ابطالی از تناژ نهایی مستثنی گردیده‌اند. "
            "ساعات حضور با برش به محدوده زمانی گزارش و ادغام بازه‌های همپوشان (Interval Union) محاسبه گردیده است."
        )), note_style))

        # Build Document
        doc.build(elements, canvasmaker=NumberedCanvas)
        buffer.seek(0)

        # Audit Logging
        log_audit(
            action=AuditAction.PRINT,
            model_name="ShiftSession",
            record_id=f"SUMMARY_PDF_{filters['start_date']}_{filters['end_date']}",
            record_repr=f"خروجی PDF خلاصه مدیریتی شیفت ({filters['start_date_jalali']} الی {filters['end_date_jalali']})",
            new_values={
                "report_type": "PDF_MANAGEMENT_SUMMARY",
                "start_date": str(filters["start_date"]),
                "end_date": str(filters["end_date"]),
                "sessions_count": len(sessions),
                "is_supervisor": is_supervisor,
            },
            user=user,
            ip_address=client_ip,
            source="WEB"
        )

        filename = f"shift_management_summary_{filters['start_date_jalali'].replace('/', '')}_{filters['end_date_jalali'].replace('/', '')}.pdf"
        response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
