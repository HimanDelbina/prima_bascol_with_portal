import csv
import io
from decimal import Decimal
from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from core.jalali import format_jalali_date, get_today_jalali
from core.models import SystemSetting


def export_freight_report(queryset, summaries, export_format):
    headers = ["شماره قبض", "تاریخ", "ساعت ورود", "ساعت خروج", "طرف حساب", "محصول", "پلاک", "راننده",
               "شماره بارنامه", "وزن بارنامه (Kg)", "وضعیت", "مبلغ کرایه (ریال)"]

    def rows():
        for ticket in queryset.iterator():
            yield [
                ticket.serial_number,
                format_jalali_date(ticket.report_date),
                ticket.first_time_str or "-",
                ticket.second_time_str or "-",
                ticket.party.name if ticket.party else "-",
                ticket.product.name if ticket.product else "-",
                ticket.license_plate_display,
                ticket.driver_display,
                ticket.waybill_number or "-",
                float(ticket.sent_weight or 0),
                ticket.get_status_display(),
                int(ticket.freight_amount) if ticket.freight_amount is not None else "ثبت نشده"
            ]
        yield [
            "مجموع کرایه", "", "", "", "", "", "", "", "",
            float(summaries.get("sum_sent", 0) or 0),
            "",
            int(summaries["total_amount"])
        ]

    if export_format == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="freight-report.csv"'
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow(headers)
        for row in rows():
            writer.writerow([
                "'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value
                for value in row
            ])
        return response

    wb = Workbook()
    ws = wb.active
    ws.title = "مبالغ کرایه"
    ws.sheet_view.rightToLeft = True
    ws.merge_cells("A1:L1")
    ws["A1"] = "گزارش مبالغ کرایه (ریال)"
    ws["A1"].font = Font(name="Tahoma", size=15, bold=True)
    ws["A1"].alignment = Alignment(horizontal="center")
    ws.merge_cells("A2:L2")
    ws["A2"] = (f"تعداد قبوض: {summaries['total_tickets']} | مبلغ ثبت‌شده: {summaries['recorded_count']}"
                f" | بدون مبلغ: {summaries['missing_count']}")
    ws["A2"].alignment = Alignment(horizontal="center")
    for col, header in enumerate(headers, 1):
        cell = ws.cell(4, col, header)
        cell.fill = PatternFill("solid", fgColor="1E3A8A")
        cell.font = Font(name="Tahoma", bold=True, color="FFFFFF")
    for row_index, row in enumerate(rows(), 5):
        for col, value in enumerate(row, 1):
            cell = ws.cell(row_index, col, value)
            if isinstance(value, str):
                cell.data_type = "s"
            cell.font = Font(name="Tahoma", size=10)
            if col in [1, 2, 3, 4, 7, 9, 11]:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col in [10, 12]:
                cell.alignment = Alignment(horizontal="left", vertical="center")
                if isinstance(value, (int, float, Decimal)):
                    cell.number_format = "#,##0"
            else:
                cell.alignment = Alignment(horizontal="right", vertical="center")
    for cell in ws[ws.max_row]:
        cell.font = Font(name="Tahoma", bold=True)
        cell.fill = PatternFill("solid", fgColor="E2E8F0")
    ws.freeze_panes = "A5"
    ws.auto_filter.ref = f"A4:L{max(4, ws.max_row - 1)}"
    for col, width in enumerate([18, 14, 12, 12, 26, 24, 22, 20, 18, 16, 16, 22], 1):
        ws.column_dimensions[get_column_letter(col)].width = width
    output = io.BytesIO()
    wb.save(output)
    response = HttpResponse(output.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="freight-report.xlsx"'
    return response

def export_excel(queryset, summaries=None, title="گزارش باسکول"):
    """
    Generate a beautifully formatted Excel (.xlsx) file in Persian RTL with styling.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "گزارش باسکول"
    ws.sheet_view.rightToLeft = True

    # Styling definitions
    font_family = "Tahoma"
    title_font = Font(name=font_family, size=14, bold=True, color="1E293B")
    subtitle_font = Font(name=font_family, size=10, italic=True, color="64748B")
    header_font = Font(name=font_family, size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    
    data_font = Font(name=font_family, size=10)
    summary_font = Font(name=font_family, size=11, bold=True, color="0F172A")
    summary_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
    
    thin_border = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1")
    )
    align_center = Alignment(horizontal="center", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")

    # Header title
    settings_obj = SystemSetting.get_settings()
    ws.merge_cells("A1:R1")
    ws["A1"] = f"{settings_obj.company_name} - {title}"
    ws["A1"].font = title_font
    ws["A1"].alignment = align_center

    ws.merge_cells("A2:R2")
    ws["A2"] = f"تاریخ تهیه گزارش: {get_today_jalali()} | تعداد رکورد: {queryset.count()}"
    ws["A2"].font = subtitle_font
    ws["A2"].alignment = align_center

    # Column Headers
    headers = [
        "ردیف",
        "شماره قبض",
        "شماره بارنامه",
        "تاریخ",
        "ساعت ورود",
        "ساعت خروج",
        "نوع عملیات",
        "طرف حساب",
        "نام محصول",
        "شماره پلاک",
        "نام راننده",
        "وزن بارنامه (Kg)",
        "وزن پر (Kg)",
        "وزن خالی (Kg)",
        "وزن خالص (Kg)",
        "افت (Kg)",
        "وزن نهایی (Kg)",
        "وضعیت",
    ]

    header_row_idx = 4
    for col_idx, header_text in enumerate(headers, 1):
        cell = ws.cell(row=header_row_idx, column=col_idx, value=header_text)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = align_center
        cell.border = thin_border
    
    ws.freeze_panes = "A5"

    # Data Rows
    current_row = header_row_idx + 1
    num_fmt = "#,##0"

    for idx, ticket in enumerate(queryset, 1):
        date_str = format_jalali_date(ticket.first_weight_date or ticket.created_at.date())
        op_name = ticket.operation_type.name if ticket.operation_type else "-"
        party_name = ticket.party.name if ticket.party else "-"
        prod_name = ticket.product.name if ticket.product else "-"
        driver_name = ticket.driver_display
        status_name = ticket.get_status_display()

        row_values = [
            idx,
            ticket.serial_number,
            ticket.waybill_number or "-",
            date_str,
            ticket.first_time_str or "-",
            ticket.second_time_str or "-",
            op_name,
            party_name,
            prod_name,
            ticket.license_plate_display,
            driver_name,
            float(ticket.sent_weight or 0),
            float(ticket.gross_weight or 0),
            float(ticket.tare_weight or 0),
            float(ticket.net_weight or 0),
            float(ticket.loss_weight or 0),
            float(ticket.final_weight or 0),
            status_name,
        ]

        for col_idx, val in enumerate(row_values, 1):
            cell = ws.cell(row=current_row, column=col_idx, value=val)
            cell.font = data_font
            cell.border = thin_border

            # Alignments and number formats
            if col_idx in [1, 2, 3, 4, 5, 6, 10, 18]:
                cell.alignment = align_center
            elif col_idx in [12, 13, 14, 15, 16, 17]:
                cell.alignment = align_left
                cell.number_format = num_fmt
            else:
                cell.alignment = align_right

        current_row += 1

    # Summary Row
    if summaries:
        summary_row_values = [
            "مجموع کل",
            f"{summaries['total_tickets']} قبض",
            "-",
            "-",
            "-",
            "-",
            "-",
            "-",
            "-",
            "-",
            f"{summaries['total_loads']} بار",
            float(summaries["sum_sent"] or 0),
            float(summaries["sum_gross"] or 0),
            float(summaries["sum_tare"] or 0),
            float(summaries["sum_net"] or 0),
            float(summaries["sum_loss"] or 0),
            float(summaries["sum_final"] or 0),
            "-",
        ]
        for col_idx, val in enumerate(summary_row_values, 1):
            cell = ws.cell(row=current_row, column=col_idx, value=val)
            cell.font = summary_font
            cell.fill = summary_fill
            cell.border = thin_border
            if col_idx in [12, 13, 14, 15, 16, 17]:
                cell.number_format = num_fmt
                cell.alignment = align_left
            else:
                cell.alignment = align_center

    # Auto Column Width
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            if cell.row in [1, 2]:
                continue
            if cell.value:
                val_str = str(cell.value)
                max_len = max(max_len, len(val_str))
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="weighbridge_report.xlsx"'
    return response

def export_financial_excel(queryset, summaries=None, title="گزارش مالی باسکول"):
    """
    Generate a dedicated, beautifully formatted Financial Excel (.xlsx) file
    specifically for the Accounting and Financial department.
    Includes all core ticket fields PLUS notes (توضیحات), freight amount (مبلغ کرایه),
    and load/ingot counts with Persian RTL styling.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "گزارش مالی باسکول"
    ws.sheet_view.rightToLeft = True

    font_family = "Tahoma"
    title_font = Font(name=font_family, size=14, bold=True, color="0F766E")
    subtitle_font = Font(name=font_family, size=10, italic=True, color="475569")
    header_font = Font(name=font_family, size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="0F766E", end_color="0F766E", fill_type="solid")
    
    data_font = Font(name=font_family, size=10)
    summary_font = Font(name=font_family, size=11, bold=True, color="0F172A")
    summary_fill = PatternFill(start_color="CCFBF1", end_color="CCFBF1", fill_type="solid")
    
    thin_border = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1")
    )
    align_center = Alignment(horizontal="center", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")
    align_notes = Alignment(horizontal="right", vertical="center", wrap_text=True)

    # 21 columns from A to U
    last_col_letter = "U"
    settings_obj = SystemSetting.get_settings()
    ws.merge_cells(f"A1:{last_col_letter}1")
    ws["A1"] = f"{settings_obj.company_name} - {title}"
    ws["A1"].font = title_font
    ws["A1"].alignment = align_center

    ws.merge_cells(f"A2:{last_col_letter}2")
    ws["A2"] = f"تاریخ تهیه گزارش: {get_today_jalali()} | تعداد رکورد: {queryset.count()} | گزارش اختصاصی واحد مالی و حسابداری (شامل توضیحات و مبالغ)"
    ws["A2"].font = subtitle_font
    ws["A2"].alignment = align_center

    headers = [
        "ردیف",
        "شماره قبض",
        "شماره بارنامه",
        "تاریخ",
        "ساعت ورود",
        "ساعت خروج",
        "نوع عملیات",
        "طرف حساب",
        "نام محصول",
        "تعداد بار و شمش",
        "شماره پلاک",
        "نام راننده",
        "مبلغ کرایه (ریال)",
        "وزن بارنامه (Kg)",
        "وزن پر (Kg)",
        "وزن خالی (Kg)",
        "وزن خالص (Kg)",
        "افت (Kg)",
        "وزن نهایی (Kg)",
        "وضعیت",
        "توضیحات",
    ]

    header_row_idx = 4
    for col_idx, header_text in enumerate(headers, 1):
        cell = ws.cell(row=header_row_idx, column=col_idx, value=header_text)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = align_center
        cell.border = thin_border
    
    ws.freeze_panes = "A5"

    current_row = header_row_idx + 1
    num_fmt = "#,##0"

    total_freight = Decimal("0")

    for idx, ticket in enumerate(queryset, 1):
        date_str = format_jalali_date(ticket.first_weight_date or ticket.created_at.date())
        op_name = ticket.operation_type.name if ticket.operation_type else "-"
        party_name = ticket.party.name if ticket.party else "-"
        prod_name = ticket.product.name if ticket.product else "-"
        driver_name = ticket.driver_display
        status_name = ticket.get_status_display()
        load_ingot_str = ticket.load_and_ingot_display
        freight_val = int(ticket.freight_amount) if ticket.freight_amount is not None else 0
        if ticket.freight_amount is not None:
            total_freight += ticket.freight_amount
        notes_val = ticket.notes.strip() if ticket.notes else "-"

        row_values = [
            idx,
            ticket.serial_number,
            ticket.waybill_number or "-",
            date_str,
            ticket.first_time_str or "-",
            ticket.second_time_str or "-",
            op_name,
            party_name,
            prod_name,
            load_ingot_str,
            ticket.license_plate_display,
            driver_name,
            freight_val,
            float(ticket.sent_weight or 0),
            float(ticket.gross_weight or 0),
            float(ticket.tare_weight or 0),
            float(ticket.net_weight or 0),
            float(ticket.loss_weight or 0),
            float(ticket.final_weight or 0),
            status_name,
            notes_val,
        ]

        for col_idx, val in enumerate(row_values, 1):
            cell = ws.cell(row=current_row, column=col_idx, value=val)
            cell.font = data_font
            cell.border = thin_border

            # Alignments and number formats
            if col_idx in [1, 2, 3, 4, 5, 6, 10, 11, 20]:
                cell.alignment = align_center
            elif col_idx in [13, 14, 15, 16, 17, 18, 19]:
                cell.alignment = align_left
                cell.number_format = num_fmt
            elif col_idx == 21:
                cell.alignment = align_notes
            else:
                cell.alignment = align_right

        current_row += 1

    # Summary Row
    if summaries:
        sum_freight_val = float(summaries.get("sum_freight") or summaries.get("total_amount") or total_freight or 0)
        tickets_cnt = summaries.get("total_tickets", len(queryset))
        loads_str = f"{summaries['total_loads']} بار" if "total_loads" in summaries else "-"
        summary_row_values = [
            "مجموع کل",
            f"{tickets_cnt} قبض",
            "-",
            "-",
            "-",
            "-",
            "-",
            "-",
            "-",
            loads_str,
            "-",
            "-",
            sum_freight_val,
            float(summaries.get("sum_sent", 0) or 0),
            float(summaries.get("sum_gross", 0) or 0),
            float(summaries.get("sum_tare", 0) or 0),
            float(summaries.get("sum_net", 0) or 0),
            float(summaries.get("sum_loss", 0) or 0),
            float(summaries.get("sum_final", 0) or 0),
            "-",
            "-",
        ]
        for col_idx, val in enumerate(summary_row_values, 1):
            cell = ws.cell(row=current_row, column=col_idx, value=val)
            cell.font = summary_font
            cell.fill = summary_fill
            cell.border = thin_border
            if col_idx in [13, 14, 15, 16, 17, 18, 19]:
                cell.number_format = num_fmt
                cell.alignment = align_left
            else:
                cell.alignment = align_center

    # Column widths
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        if col[0].column == 21:  # توضیحات
            ws.column_dimensions[col_letter].width = 38
        else:
            max_len = 0
            for cell in col:
                if cell.row in [1, 2]:
                    continue
                if cell.value:
                    val_str = str(cell.value)
                    max_len = max(max_len, len(val_str))
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="financial_weighbridge_report.xlsx"'
    return response

def export_csv(queryset, title="گزارش باسکول"):
    """
    Generate CSV file with UTF-8 BOM encoding for perfect Excel Persian support.
    """
    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    response["Content-Disposition"] = 'attachment; filename="weighbridge_report.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        "ردیف", "شماره قبض", "شماره بارنامه", "تاریخ", "ساعت ورود", "ساعت خروج",
        "نوع عملیات", "طرف حساب", "محصول", "پلاک", "راننده",
        "وزن بارنامه (Kg)", "وزن پر (Kg)", "وزن خالی (Kg)", "وزن خالص (Kg)",
        "افت (Kg)", "وزن نهایی (Kg)", "وضعیت"
    ])

    for idx, ticket in enumerate(queryset, 1):
        date_str = format_jalali_date(ticket.first_weight_date or ticket.created_at.date())
        writer.writerow([
            idx,
            ticket.serial_number,
            ticket.waybill_number or "-",
            date_str,
            ticket.first_time_str or "-",
            ticket.second_time_str or "-",
            ticket.operation_type.name if ticket.operation_type else "-",
            ticket.party.name if ticket.party else "-",
            ticket.product.name if ticket.product else "-",
            ticket.license_plate_display,
            ticket.driver_display,
            ticket.sent_weight or 0,
            ticket.gross_weight or 0,
            ticket.tare_weight or 0,
            ticket.net_weight or 0,
            ticket.loss_weight or 0,
            ticket.final_weight or 0,
            ticket.get_status_display()
        ])

    return response


def get_or_register_persian_font():
    """
    Locates and registers a local TrueType font supporting Persian characters in ReportLab.
    Prioritizes official Vazirmatn (SIL Open Font License) from static/fonts/.
    """
    import os
    from django.conf import settings
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    font_name = "Vazirmatn"
    bold_font_name = "Vazirmatn-Bold"

    registered = pdfmetrics.getRegisteredFontNames()
    if font_name in registered and bold_font_name in registered:
        return font_name, bold_font_name

    candidates = [
        # 1. Project local open-source Vazirmatn (SIL OFL)
        (
            os.path.join(settings.BASE_DIR, "static", "fonts", "Vazirmatn-Regular.ttf"),
            os.path.join(settings.BASE_DIR, "static", "fonts", "Vazirmatn-Bold.ttf")
        ),
        # 2. Local fallback if tahoma exists
        (
            os.path.join(settings.BASE_DIR, "static", "fonts", "tahoma.ttf"),
            os.path.join(settings.BASE_DIR, "static", "fonts", "tahomabd.ttf")
        ),
        # 3. Windows system fonts fallback
        ("C:/Windows/Fonts/tahoma.ttf", "C:/Windows/Fonts/tahomabd.ttf"),
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
        # 4. Linux system fonts fallback
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        ),
    ]

    for reg_path, bold_path in candidates:
        if os.path.exists(reg_path):
            try:
                b_path = bold_path if os.path.exists(bold_path) else reg_path
                if font_name not in registered:
                    pdfmetrics.registerFont(TTFont(font_name, reg_path))
                if bold_font_name not in registered:
                    pdfmetrics.registerFont(TTFont(bold_font_name, b_path))
                return font_name, bold_font_name
            except Exception:
                continue

    return "Helvetica", "Helvetica-Bold"


def shape_persian(text) -> str:
    """
    Reshapes and applies the bidirectional (bidi) algorithm for Persian/Arabic strings,
    ensuring glyphs are connected properly and rendered Right-to-Left in ReportLab.
    """
    if text is None or text == "":
        return ""
    text_str = str(text)
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        reshaped = arabic_reshaper.reshape(text_str)
        return get_display(reshaped)
    except Exception:
        return text_str


def wrap_persian_cell(text, font_name, font_size, max_width_pt):
    """
    Safely wraps Persian text for ReportLab Table Paragraphs without text clipping or column bleeding.
    Calculates line breaks on logical words first, then applies bidi shaping to each individual line,
    and returns an escaped HTML snippet with <br/> tags.
    """
    if text is None or str(text).strip() in ("", "-"):
        return "-"

    from django.utils.html import escape
    from reportlab.pdfbase.pdfmetrics import stringWidth

    words = str(text).split()
    if not words:
        return "-"

    lines = []
    current_line = []
    # Leave 3 pt margin for cell borders/padding
    safe_width = max(10, max_width_pt - 3)

    for word in words:
        trial_line = " ".join(current_line + [word])
        trial_shaped = shape_persian(trial_line)
        w = stringWidth(trial_shaped, font_name, font_size)
        if w <= safe_width or not current_line:
            current_line.append(word)
        else:
            lines.append(" ".join(current_line))
            current_line = [word]

    if current_line:
        lines.append(" ".join(current_line))

    shaped_lines = [escape(shape_persian(line)) for line in lines]
    return "<br/>".join(shaped_lines)


def export_pdf(queryset, summaries=None, title="گزارش باسکول"):
    """
    Generate an offline-capable, beautifully shaped Persian RTL PDF report.
    Uses local Persian TrueType fonts, Paragraph cell wrapping for zero overflow,
    correct bidirectional layout, and summary aggregates.
    """
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from django.utils.html import escape

    font_regular, font_bold = get_or_register_persian_font()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=15,
        leftMargin=15,
        topMargin=20,
        bottomMargin=20
    )
    elements = []

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'PersianReportTitle',
        fontName=font_bold,
        fontSize=13,
        leading=17,
        alignment=1,  # Center
        textColor=colors.HexColor('#0F172A')
    )
    sub_style = ParagraphStyle(
        'PersianReportSub',
        fontName=font_regular,
        fontSize=8.5,
        leading=12,
        alignment=1,  # Center
        textColor=colors.HexColor('#475569')
    )

    cell_style = ParagraphStyle(
        'PersianTableCell',
        fontName=font_regular,
        fontSize=6.2,
        leading=7.8,
        alignment=1,  # Center
        textColor=colors.HexColor('#0F172A'),
    )
    header_style = ParagraphStyle(
        'PersianTableHeader',
        fontName=font_bold,
        fontSize=6.5,
        leading=8.2,
        alignment=1,  # Center
        textColor=colors.whitesmoke,
    )

    settings_obj = SystemSetting.get_settings()
    full_title = f"{settings_obj.company_name} - {title}"
    elements.append(Paragraph(escape(shape_persian(full_title)), title_style))
    elements.append(Spacer(1, 4))

    record_count = queryset.count() if hasattr(queryset, 'count') else len(queryset)
    date_info = f"تاریخ تهیه گزارش: {get_today_jalali()} | تعداد رکوردهای گزارش: {record_count}"
    elements.append(Paragraph(escape(shape_persian(date_info)), sub_style))
    elements.append(Spacer(1, 10))

    # RTL Table Headers (ordered Right-to-Left so column 0 appears on the far right)
    raw_headers = [
        "ردیف", "شماره قبض", "شماره بارنامه", "تاریخ", "ورود", "خروج",
        "نوع عملیات", "طرف حساب", "محصول", "پلاک خودرو", "نام راننده",
        "وزن بارنامه", "وزن پر", "وزن خالی", "وزن خالص", "افت", "وزن نهایی", "وضعیت"
    ]
    # Reverse order for RTL display in ReportLab
    rtl_headers = [Paragraph(escape(shape_persian(h)), header_style) for h in reversed(raw_headers)]
    table_data = [rtl_headers]

    for idx, t in enumerate(queryset[:500], 1):
        d_str = format_jalali_date(t.first_weight_date or (t.created_at.date() if t.created_at else None))
        status_display = t.get_status_display() if hasattr(t, 'get_status_display') else str(t.status)
        op_name = t.operation_type.name if t.operation_type else "-"
        party_name = t.party.name if t.party else "-"
        prod_name = t.product.name if t.product else "-"
        driver_name = t.driver_display if hasattr(t, 'driver_display') else "-"

        raw_row = [
            str(idx),
            str(t.serial_number),
            str(t.waybill_number or "-"),
            str(d_str or "-"),
            str(t.first_time_str or "-"),
            str(t.second_time_str or "-"),
            Paragraph(wrap_persian_cell(op_name, font_regular, 6.2, 50), cell_style),
            Paragraph(wrap_persian_cell(party_name, font_regular, 6.2, 55), cell_style),
            Paragraph(wrap_persian_cell(prod_name, font_regular, 6.2, 55), cell_style),
            Paragraph(wrap_persian_cell(t.license_plate_display or "-", font_regular, 6.2, 55), cell_style),
            Paragraph(wrap_persian_cell(driver_name, font_regular, 6.2, 50), cell_style),
            f"{int(t.sent_weight or 0):,}",
            f"{int(t.gross_weight or 0):,}",
            f"{int(t.tare_weight or 0):,}",
            f"{int(t.net_weight or 0):,}",
            f"{int(t.loss_weight or 0):,}",
            f"{int(t.final_weight or 0):,}",
            Paragraph(wrap_persian_cell(status_display, font_regular, 6.2, 40), cell_style)
        ]
        # Reverse row for RTL
        table_data.append(list(reversed(raw_row)))

    # Summary Row if available
    if summaries:
        sum_style = ParagraphStyle(
            'PersianTableSummary',
            fontName=font_bold,
            fontSize=6.8,
            leading=8.5,
            alignment=1,  # Center
            textColor=colors.HexColor('#0F172A'),
        )
        sum_row = [
            Paragraph(escape(shape_persian("مجموع")), sum_style),
            f"{summaries.get('total_tickets', record_count)}",
            "-", "-", "-", "-", "-", "-", "-", "-", "-",
            f"{int(summaries.get('sum_sent', 0) or 0):,}",
            f"{int(summaries.get('sum_gross', 0) or 0):,}",
            f"{int(summaries.get('sum_tare', 0) or 0):,}",
            f"{int(summaries.get('sum_net', 0) or 0):,}",
            f"{int(summaries.get('sum_loss', 0) or 0):,}",
            f"{int(summaries.get('sum_final', 0) or 0):,}",
            "-"
        ]
        table_data.append(list(reversed(sum_row)))

    # Define Column Widths across Landscape A4 (usable width approx 810 pt)
    col_widths = [
        40,  # وضعیت (leftmost)
        45,  # وزن نهایی
        35,  # افت
        45,  # وزن خالص
        45,  # وزن خالی
        45,  # وزن پر
        45,  # وزن بارنامه
        50,  # نام راننده
        55,  # پلاک خودرو
        55,  # محصول
        55,  # طرف حساب
        50,  # نوع عملیات
        30,  # خروج
        30,  # ورود
        45,  # تاریخ
        45,  # شماره بارنامه
        55,  # شماره قبض
        25,  # ردیف (rightmost)
    ]

    t_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table_styles = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, -1), font_regular),
        ('FONTNAME', (0, 0), (-1, 0), font_bold),
        ('FONTSIZE', (0, 0), (-1, -1), 6.2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING', (0, 0), (-1, -1), 1),
        ('RIGHTPADDING', (0, 0), (-1, -1), 1),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
    ]

    # Alternating row colors
    for r in range(1, len(table_data)):
        if r % 2 == 0:
            table_styles.append(('BACKGROUND', (0, r), (-1, r), colors.HexColor('#F8FAFC')))

    # Style summary row if present
    if summaries:
        last_idx = len(table_data) - 1
        table_styles.extend([
            ('BACKGROUND', (0, last_idx), (-1, last_idx), colors.HexColor('#E2E8F0')),
            ('FONTNAME', (0, last_idx), (-1, last_idx), font_bold),
            ('FONTSIZE', (0, last_idx), (-1, last_idx), 7.0),
        ])

    t_table.setStyle(TableStyle(table_styles))
    elements.append(t_table)

    doc.build(elements)
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="weighbridge_report.pdf"'
    return response


def export_revision_reconciliation_excel(queryset=None, title="گزارش تطبیق و تعدیلات بازنگری قبوض"):
    """
    Dedicated reconciliation audit export for Accounting and Financial auditors (Phase 3.2.3).
    Compares original recorded values against currently effective corrected values
    for all tickets that underwent formal revision, detailing variances, reasons,
    requesters, and supervisor approvals.
    """
    from weighbridge.models import TicketRevision, WeighTicket
    wb = Workbook()
    ws = wb.active
    ws.title = "تطبیق بازنگری قبوض"
    ws.sheet_view.rightToLeft = True

    font_family = "Tahoma"
    title_font = Font(name=font_family, size=14, bold=True, color="1E3A8A")
    subtitle_font = Font(name=font_family, size=10, italic=True, color="475569")
    header_font = Font(name=font_family, size=10, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    data_font = Font(name=font_family, size=9.5)
    summary_font = Font(name=font_family, size=10, bold=True, color="0F172A")
    summary_fill = PatternFill(start_color="DBEAFE", end_color="DBEAFE", fill_type="solid")

    thin_border = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1")
    )
    align_center = Alignment(horizontal="center", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")
    align_notes = Alignment(horizontal="right", vertical="center", wrap_text=True)

    settings_obj = SystemSetting.get_settings()
    last_col_letter = "N"

    ws.merge_cells(f"A1:{last_col_letter}1")
    ws["A1"] = f"{settings_obj.company_name} - {title}"
    ws["A1"].font = title_font
    ws["A1"].alignment = align_center

    if queryset is None:
        revisions = TicketRevision.objects.filter(
            status=TicketRevision.RevisionStatus.APPLIED
        ).select_related("ticket", "requested_by", "reviewed_by").order_by("-applied_at")
    elif getattr(queryset, "model", None) == TicketRevision:
        revisions = queryset.filter(
            status=TicketRevision.RevisionStatus.APPLIED
        ).select_related("ticket", "requested_by", "reviewed_by").order_by("-applied_at")
    else:
        ticket_ids = queryset.values_list("id", flat=True)
        revisions = TicketRevision.objects.filter(
            ticket_id__in=ticket_ids,
            status=TicketRevision.RevisionStatus.APPLIED
        ).select_related("ticket", "requested_by", "reviewed_by").order_by("-applied_at")

    ws.merge_cells(f"A2:{last_col_letter}2")
    ws["A2"] = f"تاریخ گزارش: {get_today_jalali()} | تعداد رکوردهای اصلاحی اعمال‌شده: {revisions.count()} | مختص ممیزی مالی و انبار"
    ws["A2"].font = subtitle_font
    ws["A2"].alignment = align_center

    headers = [
        "ردیف",
        "شماره قبض",
        "نسخه ویرایش",
        "تاریخ توزین اولیه",
        "فیلدهای اصلاح‌شده",
        "وزن خالص اولیه (Kg)",
        "وزن خالص اصلاح‌شده (Kg)",
        "اختلاف تناژ ناشی از اصلاح (Kg)",
        "درصد تغییر (%)",
        "دلیل و توجیه بازنگری",
        "متقاضی بازنگری",
        "زمان ثبت درخواست",
        "سرپرست تأییدکننده",
        "زمان تأیید و اعمال",
    ]

    header_row_idx = 4
    for col_idx, header_text in enumerate(headers, 1):
        cell = ws.cell(row=header_row_idx, column=col_idx, value=header_text)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = align_center
        cell.border = thin_border

    ws.freeze_panes = "A5"

    current_row = header_row_idx + 1
    num_fmt = "#,##0"

    total_orig_net = Decimal("0")
    total_effective_net = Decimal("0")
    total_variance_net = Decimal("0")

    for idx, rev in enumerate(revisions, 1):
        ticket = rev.ticket
        before = rev.before_snapshot or {}
        after = rev.after_snapshot or {}

        orig_w = Decimal(str(before.get("net_weight") or ticket.original_net_weight or 0))
        eff_w = Decimal(str(after.get("net_weight") or ticket.net_weight or 0))
        diff_w = eff_w - orig_w
        pct_change = ((diff_w / orig_w) * 100).quantize(Decimal("0.01")) if orig_w > 0 else Decimal("0.00")

        total_orig_net += orig_w
        total_effective_net += eff_w
        total_variance_net += diff_w

        changed_str = ", ".join(rev.changed_fields) if rev.changed_fields else "-"
        requester_name = rev.requested_by.get_full_name() or rev.requested_by.username if rev.requested_by else "-"
        reviewer_name = rev.reviewed_by.get_full_name() or rev.reviewed_by.username if rev.reviewed_by else "-"

        row_values = [
            idx,
            ticket.serial_number,
            f"Rev. {rev.revision_number}",
            format_jalali_date(ticket.first_weight_date or ticket.created_at.date()),
            changed_str,
            float(orig_w),
            float(eff_w),
            float(diff_w),
            float(pct_change),
            rev.reason,
            requester_name,
            rev.jalali_requested_at,
            reviewer_name,
            rev.jalali_applied_at,
        ]

        for col_idx, val in enumerate(row_values, 1):
            cell = ws.cell(row=current_row, column=col_idx, value=val)
            cell.font = data_font
            cell.border = thin_border

            if col_idx in [1, 2, 3, 4, 12, 14]:
                cell.alignment = align_center
            elif col_idx in [6, 7, 8, 9]:
                cell.alignment = align_left
                cell.number_format = num_fmt if col_idx != 9 else "0.00"
            elif col_idx in [5, 10]:
                cell.alignment = align_notes
            else:
                cell.alignment = align_right

        current_row += 1

    # Summary Row
    summary_row = current_row
    ws.merge_cells(f"A{summary_row}:E{summary_row}")
    sum_label_cell = ws.cell(row=summary_row, column=1, value="مجموع تعدیلات و مغایرت‌های بازنگری")
    sum_label_cell.font = summary_font
    sum_label_cell.alignment = align_center
    sum_label_cell.fill = summary_fill

    cell_orig = ws.cell(row=summary_row, column=6, value=float(total_orig_net))
    cell_orig.font = summary_font
    cell_orig.number_format = num_fmt
    cell_orig.alignment = align_left
    cell_orig.fill = summary_fill

    cell_eff = ws.cell(row=summary_row, column=7, value=float(total_effective_net))
    cell_eff.font = summary_font
    cell_eff.number_format = num_fmt
    cell_eff.alignment = align_left
    cell_eff.fill = summary_fill

    cell_diff = ws.cell(row=summary_row, column=8, value=float(total_variance_net))
    cell_diff.font = summary_font
    cell_diff.number_format = num_fmt
    cell_diff.alignment = align_left
    cell_diff.fill = summary_fill

    for c in range(1, 15):
        ws.cell(row=summary_row, column=c).border = thin_border
        if c > 8:
            ws.cell(row=summary_row, column=c).fill = summary_fill

    # Auto column width
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            if cell.row in [1, 2]:
                continue
            if cell.value:
                max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[col_letter].width = max(max_len + 3, 11)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="ticket_revision_reconciliation.xlsx"'
    return response
