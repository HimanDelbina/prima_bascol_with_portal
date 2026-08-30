import csv
import io
from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from core.jalali import format_jalali_date, get_today_jalali
from core.models import SystemSetting


def export_monitoring_excel(queryset, title="گزارش هشدارهای پایش هوشمند"):
    """
    Generate styled Persian RTL Excel (.xlsx) file for Monitoring Alerts.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "هشدارهای پایش"
    ws.sheet_view.rightToLeft = True

    font_family = "Tahoma"
    title_font = Font(name=font_family, size=14, bold=True, color="1E293B")
    subtitle_font = Font(name=font_family, size=10, italic=True, color="64748B")
    header_font = Font(name=font_family, size=10, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    
    data_font = Font(name=font_family, size=9)
    thin_border = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1")
    )
    align_center = Alignment(horizontal="center", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")

    settings_obj = SystemSetting.get_settings()
    ws.merge_cells("A1:K1")
    ws["A1"] = f"{settings_obj.company_name} - {title}"
    ws["A1"].font = title_font
    ws["A1"].alignment = align_center

    ws.merge_cells("A2:K2")
    ws["A2"] = f"تاریخ گزارش: {get_today_jalali()} | تعداد هشدارها: {queryset.count()}"
    ws["A2"].font = subtitle_font
    ws["A2"].alignment = align_center

    headers = [
        "ردیف",
        "سطح اهمیت",
        "نوع هشدار",
        "شماره قبض",
        "پلاک خودرو",
        "طرف حساب",
        "محصول",
        "مقدار فعلی",
        "مقدار مبنا",
        "میزان انحراف",
        "وضعیت",
        "شرح و دلیل هشدار",
    ]

    ws.row_dimensions[4].height = 26
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = align_center
        cell.border = thin_border

    current_row = 5
    for idx, alert in enumerate(queryset, 1):
        t = alert.ticket
        ws.row_dimensions[current_row].height = 22
        
        row_values = [
            idx,
            alert.get_severity_display(),
            alert.get_alert_type_display(),
            t.serial_number if t else "-",
            t.license_plate_display if t else "-",
            t.party.name if (t and t.party) else "-",
            t.product.name if (t and t.product) else "-",
            f"{alert.current_value:,.2f}" if alert.current_value is not None else "-",
            f"{alert.baseline_value:,.2f}" if alert.baseline_value is not None else "-",
            f"{alert.deviation_value:,.2f}" if alert.deviation_value is not None else "-",
            alert.get_status_display(),
            alert.reason,
        ]

        for col_idx, val in enumerate(row_values, 1):
            cell = ws.cell(row=current_row, column=col_idx, value=val)
            cell.font = data_font
            cell.border = thin_border
            cell.alignment = align_right if col_idx in [6, 7, 12] else align_center

        current_row += 1

    # Auto-adjust column widths
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = 0
        for cell in col:
            val_str = str(cell.value or "")
            if len(val_str) > max_len and cell.row > 3:
                max_len = len(val_str)
        ws.column_dimensions[col_letter].width = min(max(max_len + 4, 12), 45)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="monitoring_alerts_report.xlsx"'
    return response


def export_monitoring_csv(queryset, filename="monitoring_alerts"):
    """
    Generate UTF-8 CSV with BOM for Persian Excel compatibility.
    """
    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        "ردیف",
        "سطح اهمیت",
        "نوع هشدار",
        "شماره قبض",
        "پلاک خودرو",
        "طرف حساب",
        "محصول",
        "مقدار فعلی",
        "مقدار مبنا",
        "میزان انحراف",
        "درصد انحراف",
        "وضعیت",
        "تاریخ ایجاد",
        "شرح و دلیل",
    ])

    for idx, alert in enumerate(queryset, 1):
        t = alert.ticket
        writer.writerow([
            idx,
            alert.get_severity_display(),
            alert.get_alert_type_display(),
            t.serial_number if t else "",
            t.license_plate_display if t else "",
            t.party.name if (t and t.party) else "",
            t.product.name if (t and t.product) else "",
            alert.current_value or "",
            alert.baseline_value or "",
            alert.deviation_value or "",
            f"{alert.deviation_percent}%" if alert.deviation_percent is not None else "",
            alert.get_status_display(),
            alert.jalali_created_at,
            alert.reason.replace("\n", " "),
        ])

    return response
