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


def export_party_ranking_excel(ranked_items, title="رتبه‌بندی طرف‌های حساب و تأمین‌کنندگان"):
    """
    خروجی فایل اکسل جدول رتبه‌بندی طرف‌حساب‌ها همراه با رتبه، امتیاز، اطمینان و شاخص‌ها.
    """
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    ws = wb.create_sheet(title="رتبه‌بندی")
    ws.views.sheetView[0].rightToLeft = True

    header_font = Font(name="Tahoma", size=11, bold=True, color="FFFFFF")
    title_font = Font(name="Tahoma", size=14, bold=True, color="1E3A8A")
    data_font = Font(name="Tahoma", size=10)
    bold_data_font = Font(name="Tahoma", size=10, bold=True)

    header_fill = PatternFill(start_color="1E40AF", end_color="1E40AF", fill_type="solid")
    zebra_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

    thin_border = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )

    settings_obj = SystemSetting.get_settings()
    company_name = settings_obj.company_name or "مجتمع صنعتی و معدنی فولاد پریما"

    ws.cell(row=1, column=1, value=company_name).font = title_font
    ws.cell(row=2, column=1, value=f"{title} - تاریخ گزارش: {get_today_jalali()}").font = Font(name="Tahoma", size=10, italic=True, color="475569")

    headers = [
        "رتبه", "صدک", "نام طرف حساب", "کد", "نوع", "امتیاز کل (۰-۱۰۰)", "سطح کیفی",
        "سطح اطمینان", "تعداد بار", "مجموع تناژ", "میانگین مغایرت (Kg)", "میانگین افت (%)",
        "نرخ هشدار (در ۱۰۰)", "میانگین توقف (دقیقه)", "دقت وزن", "عملکرد افت", "ثبات", "پایش", "بهره‌وری"
    ]

    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    ws.row_dimensions[4].height = 28

    for r_idx, item in enumerate(ranked_items, 5):
        row_vals = [
            item.get('rank', '-'),
            item.get('percentile', '-'),
            item.get('party_name', '-'),
            item.get('party_code', '') or '-',
            item.get('party_type_fa', '-'),
            item.get('overall_score', '-'),
            item.get('score_level_fa', '-'),
            item.get('confidence_fa', '-'),
            item.get('completed_tickets', 0),
            item.get('total_tonnage', 0.0),
            item.get('avg_discrepancy_kg', 0.0),
            item.get('avg_loss_percent', 0.0),
            item.get('alert_rate', 0.0),
            item.get('avg_turnaround_min', 0.0),
            item.get('weight_accuracy_score', 0.0),
            item.get('loss_performance_score', 0.0),
            item.get('consistency_score', 0.0),
            item.get('monitoring_quality_score', 0.0),
            item.get('operational_efficiency_score', 0.0),
        ]
        is_even = (r_idx % 2 == 0)
        for c_idx, val in enumerate(row_vals, 1):
            c = ws.cell(row=r_idx, column=c_idx, value=val)
            c.font = bold_data_font if c_idx in [1, 6] else data_font
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = thin_border
            if is_even:
                c.fill = zebra_fill

    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    response = HttpResponse(
        output.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    filename = f"party_ranking_{get_today_jalali().replace('/', '-')}.xlsx"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def export_party_analytics_excel(party, analysis, trend_data=None):
    """
    خروجی جامع اکسل چندبرگه (Multi-Sheet) برای تحلیل یک طرف‌حساب خاص شامل:
    Sheet 1: Summary & Score
    Sheet 2: Tickets
    Sheet 3: Discrepancies
    Sheet 4: Losses
    Sheet 5: Alerts
    Sheet 6: Trend
    """
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    header_font = Font(name="Tahoma", size=11, bold=True, color="FFFFFF")
    title_font = Font(name="Tahoma", size=14, bold=True, color="1E3A8A")
    kpi_title_font = Font(name="Tahoma", size=10, bold=True, color="475569")
    kpi_val_font = Font(name="Tahoma", size=12, bold=True, color="0F172A")
    data_font = Font(name="Tahoma", size=10)
    bold_font = Font(name="Tahoma", size=10, bold=True)

    header_fill = PatternFill(start_color="1E40AF", end_color="1E40AF", fill_type="solid")
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

    # --- Sheet 1: خلاصه امتیاز و عملکرد ---
    ws1 = wb.create_sheet(title="خلاصه ارزیابی و امتیاز")
    ws1.views.sheetView[0].rightToLeft = True

    ws1.cell(row=1, column=1, value=company_name).font = title_font
    ws1.cell(row=2, column=1, value=f"شناسنامه و تحلیل عملکرد: {party.name} ({party.get_party_type_display()})").font = Font(name="Tahoma", size=12, bold=True, color="1E293B")
    ws1.cell(row=3, column=1, value=f"تاریخ گزارش: {get_today_jalali()} | نسخه الگوریتم: {analysis['score']['calculation_version']}").font = Font(name="Tahoma", size=9, italic=True, color="64748B")

    score_info = analysis['score']
    prof = analysis['profile']

    ws1.cell(row=5, column=1, value="امتیاز کل عملکرد").font = kpi_title_font
    ws1.cell(row=5, column=2, value=score_info['overall_score'] if score_info['overall_score'] is not None else "داده ناکافی").font = kpi_val_font
    ws1.cell(row=6, column=1, value="سطح کیفی").font = kpi_title_font
    ws1.cell(row=6, column=2, value=score_info['level_fa']).font = bold_font
    ws1.cell(row=7, column=1, value="سطح اطمینان آماری").font = kpi_title_font
    ws1.cell(row=7, column=2, value=score_info['confidence_fa']).font = bold_font

    ws1.cell(row=9, column=1, value="ابعاد ۶ گانه ارزیابی").font = Font(name="Tahoma", size=11, bold=True, color="1E40AF")
    ws1.cell(row=10, column=1, value="بُعد ارزیابی").font = header_font
    ws1.cell(row=10, column=1).fill = header_fill
    ws1.cell(row=10, column=2, value="وزن فرمول (%)").font = header_font
    ws1.cell(row=10, column=2).fill = header_fill
    ws1.cell(row=10, column=3, value="امتیاز کسب‌شده (۰-۱۰۰)").font = header_font
    ws1.cell(row=10, column=3).fill = header_fill

    dim_names_fa = {
        'weight_accuracy': 'دقت اوزان و مغایرت',
        'loss_performance': 'عملکرد افت محموله (نرمال‌شده)',
        'consistency': 'ثبات و یکنواختی عملکرد',
        'monitoring_quality': 'کیفیت پایش و عدم هشدار',
        'operational_efficiency': 'بهره‌وری عملیاتی و معطلی',
        'data_reliability': 'اعتبار و کفایت نمونه آماری',
    }

    cur_row = 11
    dims = score_info['dimension_scores']
    weights = score_info['dimension_weights']
    for d_key, d_label in dim_names_fa.items():
        ws1.cell(row=cur_row, column=1, value=d_label).font = data_font
        ws1.cell(row=cur_row, column=1).border = thin_border
        ws1.cell(row=cur_row, column=2, value=weights.get(d_key, 0)).font = data_font
        ws1.cell(row=cur_row, column=2).border = thin_border
        ws1.cell(row=cur_row, column=3, value=dims.get(d_key, 0.0)).font = bold_font
        ws1.cell(row=cur_row, column=3).border = thin_border
        cur_row += 1

    cur_row += 2
    ws1.cell(row=cur_row, column=1, value="توضیحات و دلایل تحلیلی (نقاط مثبت)").font = Font(name="Tahoma", size=11, bold=True, color="166534")
    cur_row += 1
    for p in score_info['explanation']['positive_points']:
        ws1.cell(row=cur_row, column=1, value=f"• {p}").font = data_font
        cur_row += 1

    cur_row += 1
    ws1.cell(row=cur_row, column=1, value="موارد نیازمند توجه و بهبود").font = Font(name="Tahoma", size=11, bold=True, color="991B1B")
    cur_row += 1
    for a in score_info['explanation']['attention_points']:
        ws1.cell(row=cur_row, column=1, value=f"• {a}").font = data_font
        cur_row += 1

    for col in ws1.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws1.column_dimensions[col_letter].width = max(max_len + 4, 16)

    # --- Sheet 2: قبوض محموله‌ها ---
    ws2 = wb.create_sheet(title="قبوض محموله‌ها")
    ws2.views.sheetView[0].rightToLeft = True

    t_headers = [
        "ردیف", "شماره قبض", "تاریخ", "کالا", "پلاک خودرو", "وزن ارسالی (Kg)",
        "وزن پر (Kg)", "وزن خالی (Kg)", "وزن خالص (Kg)", "اختلاف وزن (Kg)", "درصد افت (%)",
        "وزن نهایی (Kg)", "مغایرت غیرمجاز", "وضعیت"
    ]
    for col_idx, h in enumerate(t_headers, 1):
        cell = ws2.cell(row=1, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border
        cell.alignment = Alignment(horizontal="center", vertical="center")

    tickets = WeighTicket.objects.filter(party=party).order_by('-first_weight_date', '-id')[:300]
    for r_idx, t in enumerate(tickets, 2):
        is_even = (r_idx % 2 == 0)
        row_data = [
            r_idx - 1,
            t.serial_number,
            format_jalali_date(t.first_weight_date) if t.first_weight_date else '-',
            t.product.name if t.product else '-',
            t.license_plate_display,
            float(t.sent_weight or 0),
            float(t.gross_weight or 0),
            float(t.tare_weight or 0),
            float(t.net_weight or 0),
            float(t.weight_difference or 0),
            float(t.loss_percent or 0),
            float(t.final_weight or 0),
            "بله" if t.is_tolerance_exceeded else "خیر",
            t.get_status_display()
        ]
        for c_idx, val in enumerate(row_data, 1):
            c = ws2.cell(row=r_idx, column=c_idx, value=val)
            c.font = data_font
            c.border = thin_border
            c.alignment = Alignment(horizontal="center", vertical="center")
            if is_even:
                c.fill = zebra_fill

    for col in ws2.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws2.column_dimensions[col_letter].width = max(max_len + 4, 12)

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    response = HttpResponse(
        output.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    safe_name = "".join(c for c in party.name if c.isalnum() or c in (' ', '_', '-')).strip()
    filename = f"party_{safe_name}_{get_today_jalali().replace('/', '-')}.xlsx"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def export_party_ranking_csv(ranked_items):
    """
    خروجی فایل CSV استاندارد با UTF-8 BOM جهت رتبه‌بندی طرف‌حساب‌ها.
    """
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    filename = f"party_ranking_{get_today_jalali().replace('/', '-')}.csv"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write('\ufeff')  # BOM

    writer = csv.writer(response)
    writer.writerow([
        "Rank", "Percentile", "Party Name", "Code", "Type", "Overall Score",
        "Level", "Confidence", "Trips", "Tonnage", "Avg Discrepancy Kg",
        "Avg Loss Pct", "Alert Rate", "Avg Turnaround Min"
    ])

    for item in ranked_items:
        writer.writerow([
            item.get('rank', ''),
            item.get('percentile', ''),
            item.get('party_name', ''),
            item.get('party_code', ''),
            item.get('party_type_fa', ''),
            item.get('overall_score', ''),
            item.get('score_level_fa', ''),
            item.get('confidence_fa', ''),
            item.get('completed_tickets', 0),
            item.get('total_tonnage', 0.0),
            item.get('avg_discrepancy_kg', 0.0),
            item.get('avg_loss_percent', 0.0),
            item.get('alert_rate', 0.0),
            item.get('avg_turnaround_min', 0.0),
        ])

    return response


def export_party_analytics_pdf(party, analysis, trend_data=None):
    """
    تولید گزارش رسمی مدیریتی PDF طرف‌حساب با ReportLab.
    """
    from reportlab.lib.pagesizes import letter, landscape, A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors

    buffer = BytesIO()
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

    settings_obj = SystemSetting.get_settings()
    company_name = settings_obj.company_name or "مجتمع صنعتی و معدنی فولاد پریما"

    title_text = f"{company_name} - کارنامه عملکرد طرف‌حساب"
    elements.append(Paragraph(title_text, styles['Title']))
    elements.append(Paragraph(f"Party: {party.name} ({party.get_party_type_display()}) | Code: {party.code or '-'} | Date: {get_today_jalali()}", styles['Normal']))
    elements.append(Spacer(1, 15))

    score_info = analysis['score']
    prof = analysis['profile']

    sc_str = str(score_info['overall_score']) if score_info['overall_score'] is not None else "Insufficient Data"

    summary_table_data = [
        ["Overall Score", sc_str, "Quality Level", score_info['level_fa']],
        ["Confidence", score_info['confidence_fa'], "Algorithm Version", score_info['calculation_version']],
        ["Total Trips", str(prof['completed_tickets']), "Total Tonnage (Ton)", str(prof['total_net_weight_ton'])],
        ["Avg Discrepancy (Kg)", str(analysis['discrepancy_metrics']['average_absolute_discrepancy_kg']), "Avg Loss (%)", str(analysis['loss_metrics']['average_loss_percent'])],
        ["Alerts Per 100", str(analysis['monitoring_metrics']['alerts_per_100_tickets']), "Critical Alerts", str(analysis['monitoring_metrics']['critical_alerts'])],
        ["Avg Turnaround (Min)", str(analysis['turnaround_metrics']['average_turnaround_minutes']), "Weight Overrides", str(analysis['correction_metrics']['weight_correction_count'])],
    ]

    t = Table(summary_table_data, colWidths=[140, 130, 140, 130])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 15))

    elements.append(Paragraph("<b>Score Dimensions Breakdown (0 - 100):</b>", styles['Heading3']))
    dims = score_info['dimension_scores']
    dim_rows = [
        ["Dimension", "Score", "Formula Weight"],
        ["Weight Accuracy", str(dims['weight_accuracy']), "30%"],
        ["Loss Performance (Normalized)", str(dims['loss_performance']), "20%"],
        ["Consistency", str(dims['consistency']), "15%"],
        ["Monitoring Quality", str(dims['monitoring_quality']), "20%"],
        ["Operational Efficiency", str(dims['operational_efficiency']), "10%"],
        ["Data Reliability", str(dims['data_reliability']), "5%"],
    ]
    t_dims = Table(dim_rows, colWidths=[240, 150, 150])
    t_dims.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    elements.append(t_dims)
    elements.append(Spacer(1, 15))

    elements.append(Paragraph("<b>Analytical Evaluation & Observations:</b>", styles['Heading3']))
    for p in score_info['explanation']['positive_points']:
        elements.append(Paragraph(f"[+] {p}", styles['Normal']))
    for a in score_info['explanation']['attention_points']:
        elements.append(Paragraph(f"[-] {a}", styles['Normal']))

    doc.build(elements)
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    safe_name = "".join(c for c in party.name if c.isalnum() or c in (' ', '_', '-')).strip()
    response['Content-Disposition'] = f'attachment; filename="party_analytics_{safe_name}.pdf"'
    return response
