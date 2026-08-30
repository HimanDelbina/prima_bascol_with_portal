import csv
from io import BytesIO
from django.http import HttpResponse
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from core.jalali import format_jalali_date, get_today_jalali
from core.models import SystemSetting
from weighbridge.models import WeighTicket, TicketStatus
from management.services import ManagementDashboardService, ManagementReportService

def export_management_excel(curr_qs, start_date_jalali, end_date_jalali, title="گزارش جامع مدیریتی باسکول"):
    wb = openpyxl.Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    header_font = Font(name="Tahoma", size=11, bold=True, color="FFFFFF")
    title_font = Font(name="Tahoma", size=14, bold=True, color="1E3A8A")
    kpi_title_font = Font(name="Tahoma", size=10, bold=True, color="475569")
    kpi_val_font = Font(name="Tahoma", size=12, bold=True, color="0F172A")
    data_font = Font(name="Tahoma", size=10)

    header_fill = PatternFill(start_color="1E40AF", end_color="1E40AF", fill_type="solid")
    sub_fill = PatternFill(start_color="3B82F6", end_color="3B82F6", fill_type="solid")
    kpi_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
    zebra_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

    thin_border = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )

    settings_obj = SystemSetting.get_settings()
    company_name = settings_obj.company_name or "مجتمع صنعتی و معدنی فولاد پریما"

    # -------------------------------------------------------------
    # Sheet 1: Summary KPI
    # -------------------------------------------------------------
    ws1 = wb.create_sheet(title="خلاصه مدیریتی")
    ws1.views.sheetView[0].rightToLeft = True

    ws1.cell(row=1, column=1, value=company_name).font = title_font
    ws1.cell(row=2, column=1, value=f"{title} (بازه: {start_date_jalali} تا {end_date_jalali})").font = Font(name="Tahoma", size=11, bold=True, color="334155")
    ws1.cell(row=3, column=1, value=f"تاریخ گزارش‌گیری: {get_today_jalali()}").font = Font(name="Tahoma", size=9, color="64748B")

    kpis, _, comparison = ManagementDashboardService.calculate_kpis_with_comparison(curr_qs, curr_qs.none())

    kpi_items = [
        ("تعداد کل سرویس‌ها", f"{kpis['trips']:,} بار", "تعداد قبوض تکمیل‌شده", f"{kpis['completed_trips']:,} بار"),
        ("مجموع وزن خالص (Kg)", f"{kpis['net_kg']:,.0f} کیلوگرم", "مجموع وزن خالص (Ton)", f"{kpis['net_ton']:,.2f} تن"),
        ("مجموع وزن نهایی (Kg)", f"{kpis['final_kg']:,.0f} کیلوگرم", "مجموع وزن نهایی (Ton)", f"{kpis['final_ton']:,.2f} تن"),
        ("ورودی / خرید (Ton)", f"{kpis['inbound_net_ton']:,.2f} تن", "خروجی / فروش (Ton)", f"{kpis['outbound_net_ton']:,.2f} تن"),
        ("مجموع افت کالا (Ton)", f"{kpis['loss_ton']:,.2f} تن", "میانگین درصد افت", f"{kpis['avg_loss_pct']:.2f} %"),
        ("تعداد کل خودروها", f"{kpis['trucks_count']:,} دستگاه", "تعداد کل رانندگان", f"{kpis['drivers_count']:,} نفر"),
        ("تعداد طرف‌های حساب", f"{kpis['parties_count']:,} شرکت/شخص", "تعداد محصولات", f"{kpis['products_count']:,} قلم کالا"),
        ("تعداد مغایرت‌های وزن", f"{kpis['discrepancies_count']:,} مورد", "تعداد قبوض لغو شده", f"{kpis['cancelled_count']:,} مورد"),
    ]

    r = 5
    for row_data in kpi_items:
        c1 = ws1.cell(row=r, column=1, value=row_data[0])
        c2 = ws1.cell(row=r, column=2, value=row_data[1])
        c3 = ws1.cell(row=r, column=3, value=row_data[2])
        c4 = ws1.cell(row=r, column=4, value=row_data[3])

        c1.font, c1.fill, c1.alignment = kpi_title_font, kpi_fill, Alignment(horizontal="right", vertical="center")
        c2.font, c2.fill, c2.alignment = kpi_val_font, kpi_fill, Alignment(horizontal="left", vertical="center")
        c3.font, c3.fill, c3.alignment = kpi_title_font, kpi_fill, Alignment(horizontal="right", vertical="center")
        c4.font, c4.fill, c4.alignment = kpi_val_font, kpi_fill, Alignment(horizontal="left", vertical="center")

        for c in [c1, c2, c3, c4]:
            c.border = thin_border
        r += 1

    # -------------------------------------------------------------
    # Sheet 2: All Tickets
    # -------------------------------------------------------------
    ws2 = wb.create_sheet(title="قبوض باسکول")
    ws2.views.sheetView[0].rightToLeft = True

    ticket_headers = [
        "ردیف", "شماره قبض", "تاریخ", "ساعت", "نوع عملیات", "طرف حساب", "محصول",
        "پلاک خودرو", "راننده", "وزن ناخالص / پر (Kg)", "وزن خالی / تار (Kg)",
        "وزن خالص (Kg)", "وزن ارسالی (Kg)", "اختلاف وزن (Kg)", "افت (Kg)", "وزن نهایی (Kg)", "وضعیت"
    ]
    for col_idx, h in enumerate(ticket_headers, 1):
        cell = ws2.cell(row=1, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    tickets = curr_qs.select_related('party', 'product', 'driver', 'operation_type').order_by('-id')
    for row_idx, t in enumerate(tickets, 2):
        status_display = dict(TicketStatus.choices).get(t.status, t.status)
        values = [
            row_idx - 1,
            t.serial_number,
            format_jalali_date(t.first_weight_date),
            t.first_time_str,
            str(t.operation_type or "-"),
            str(t.party or "-"),
            str(t.product or "-"),
            t.license_plate_display,
            t.driver_display,
            float(t.gross_weight or 0),
            float(t.tare_weight or 0),
            float(t.net_weight or 0),
            float(t.sent_weight or 0),
            float(t.weight_difference or 0),
            float(t.loss_weight or 0),
            float(t.final_weight or 0),
            status_display
        ]
        for col_idx, val in enumerate(values, 1):
            c = ws2.cell(row=row_idx, column=col_idx, value=val)
            c.font = data_font
            c.border = thin_border
            if row_idx % 2 == 1:
                c.fill = zebra_fill
            if isinstance(val, (int, float)) and col_idx >= 10 and col_idx <= 16:
                c.number_format = '#,##0'

    # -------------------------------------------------------------
    # Sheet 3: Products Summary
    # -------------------------------------------------------------
    ws3 = wb.create_sheet(title="گزارش محصولات")
    ws3.views.sheetView[0].rightToLeft = True
    prod_headers = ["ردیف", "نام محصول", "کد محصول", "تعداد بار", "وزن خالص (تن)", "وزن نهایی (تن)", "سهم از کل (%)", "میانگین هر بار (تن)", "وزن ارسالی (تن)", "اختلاف (کیلوگرم)", "افت (تن)", "مغایرت‌ها"]
    for col_idx, h in enumerate(prod_headers, 1):
        cell = ws3.cell(row=1, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = sub_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    prod_rows = ManagementReportService.get_product_analysis(curr_qs)
    for row_idx, p in enumerate(prod_rows, 2):
        vals = [
            row_idx - 1, p['name'], p['code'] or '-', p['trips'],
            p['net_ton'], p['final_ton'], p['share_pct'], p['avg_load_ton'],
            p['sent_ton'], p['diff_kg'], p['loss_ton'], p['discrepancies']
        ]
        for col_idx, val in enumerate(vals, 1):
            c = ws3.cell(row=row_idx, column=col_idx, value=val)
            c.font = data_font
            c.border = thin_border
            if row_idx % 2 == 1:
                c.fill = zebra_fill

    # -------------------------------------------------------------
    # Sheet 4: Parties Summary
    # -------------------------------------------------------------
    ws4 = wb.create_sheet(title="طرف‌های حساب")
    ws4.views.sheetView[0].rightToLeft = True
    party_headers = ["ردیف", "نام طرف حساب", "نوع", "تعداد بار", "وزن خالص (تن)", "وزن نهایی (تن)", "وزن ارسالی (تن)", "اختلاف (کیلوگرم)", "افت (تن)", "تعداد مغایرت", "اولین بار", "آخرین بار"]
    for col_idx, h in enumerate(party_headers, 1):
        cell = ws4.cell(row=1, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = sub_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    party_rows = ManagementReportService.get_party_analysis(curr_qs)
    for row_idx, pt in enumerate(party_rows, 2):
        vals = [
            row_idx - 1, pt['name'], pt['type'] or '-', pt['trips'],
            pt['net_ton'], pt['final_ton'], pt['sent_ton'], pt['diff_kg'],
            pt['loss_ton'], pt['discrepancies'], pt['first_date_jalali'], pt['last_date_jalali']
        ]
        for col_idx, val in enumerate(vals, 1):
            c = ws4.cell(row=row_idx, column=col_idx, value=val)
            c.font = data_font
            c.border = thin_border
            if row_idx % 2 == 1:
                c.fill = zebra_fill

    # -------------------------------------------------------------
    # Sheet 5: Discrepancies
    # -------------------------------------------------------------
    ws5 = wb.create_sheet(title="مغایرت‌های وزن")
    ws5.views.sheetView[0].rightToLeft = True
    disc_headers = ["ردیف", "شماره قبض", "تاریخ", "طرف حساب", "محصول", "پلاک", "وزن ارسالی (Kg)", "وزن باسکول (Kg)", "اختلاف وزن (Kg)", "درصد اختلاف (%)", "وضعیت مغایرت"]
    for col_idx, h in enumerate(disc_headers, 1):
        cell = ws5.cell(row=1, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = PatternFill(start_color="DC2626", end_color="DC2626", fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center")

    disc_tickets = curr_qs.filter(is_tolerance_exceeded=True).select_related('party', 'product').order_by('-created_at')
    for row_idx, d in enumerate(disc_tickets, 2):
        vals = [
            row_idx - 1, d.serial_number, format_jalali_date(d.first_weight_date),
            str(d.party or "-"), str(d.product or "-"), d.license_plate_display,
            float(d.sent_weight or 0), float(d.net_weight or 0), float(d.weight_difference or 0),
            float(d.weight_difference_percent or 0), "مغایرت فراتر از تلورانس"
        ]
        for col_idx, val in enumerate(vals, 1):
            c = ws5.cell(row=row_idx, column=col_idx, value=val)
            c.font = data_font
            c.border = thin_border

    # Adjust all column widths
    for sheet in wb.worksheets:
        for col in sheet.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = get_column_letter(col[0].column)
            sheet.column_dimensions[col_letter].width = max(max_len + 4, 12)

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="Executive_Management_Report_{get_today_jalali().replace("/", "-")}.xlsx"'
    return response

def export_management_csv(curr_qs, title="Management_Report"):
    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    response["Content-Disposition"] = f'attachment; filename="{title}_{get_today_jalali().replace("/", "-")}.csv"'
    response.write('\ufeff') # UTF-8 BOM

    writer = csv.writer(response)
    writer.writerow([
        "شماره قبض", "تاریخ", "ساعت", "نوع عملیات", "طرف حساب", "محصول",
        "پلاک", "راننده", "وزن پر (Kg)", "وزن خالی (Kg)", "وزن خالص (Kg)",
        "وزن ارسالی (Kg)", "اختلاف (Kg)", "افت (Kg)", "وزن نهایی (Kg)", "وضعیت"
    ])

    for t in curr_qs.select_related('party', 'product', 'driver', 'operation_type').order_by('-id'):
        writer.writerow([
            t.serial_number,
            format_jalali_date(t.first_weight_date),
            t.first_time_str,
            str(t.operation_type or "-"),
            str(t.party or "-"),
            str(t.product or "-"),
            t.license_plate_display,
            t.driver_display,
            t.gross_weight,
            t.tare_weight,
            t.net_weight,
            t.sent_weight,
            t.weight_difference,
            t.loss_weight,
            t.final_weight,
            dict(TicketStatus.choices).get(t.status, t.status)
        ])

    return response
