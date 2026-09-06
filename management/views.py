import json
from decimal import Decimal
from datetime import datetime, date, timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q

from accounts.decorators import management_role_required
from core.jalali import (
    get_today_jalali, get_today_gregorian, format_jalali_date, 
    gregorian_to_jalali, get_jalali_month_name, jalali_to_gregorian
)
from core.models import SystemSetting
from weighbridge.models import WeighTicket, TicketStatus
from masterdata.models import Product, Party, Driver, Vehicle, Location, OperationType, LossType
from management.models import SavedReport, ReportSnapshot
from management.services import ManagementDashboardService, ManagementReportService
from management.exports import export_management_excel, export_management_csv

def _get_filter_context(request, curr_qs, start_date, end_date, period_label):
    products = Product.objects.filter(is_active=True)
    parties = Party.objects.filter(is_active=True)
    operation_types = OperationType.objects.filter(is_active=True)
    drivers = Driver.objects.filter(is_active=True)
    vehicles = Vehicle.objects.filter(is_active=True)
    origins = Location.objects.filter(is_active=True)
    destinations = Location.objects.filter(is_active=True)

    saved_reports = SavedReport.objects.filter(created_by=request.user)

    return {
        'start_date_jalali': format_jalali_date(start_date),
        'end_date_jalali': format_jalali_date(end_date),
        'period_label': period_label,
        'products': products,
        'parties': parties,
        'operation_types': operation_types,
        'drivers': drivers,
        'vehicles': vehicles,
        'origins': origins,
        'destinations': destinations,
        'saved_reports': saved_reports,
        'params': request.GET,
    }

@login_required
@management_role_required
def dashboard_view(request):
    """
    Executive Management Analytical Dashboard.
    """
    if request.GET.get('export') == 'excel':
        curr_qs, _, start_date, end_date, _, _, _ = ManagementDashboardService.get_filtered_queryset(request.GET)
        return export_management_excel(curr_qs, format_jalali_date(start_date), format_jalali_date(end_date))
    elif request.GET.get('export') == 'csv':
        curr_qs, _, _, _, _, _, _ = ManagementDashboardService.get_filtered_queryset(request.GET)
        return export_management_csv(curr_qs, "Executive_Dashboard")

    curr_qs, prev_qs, start_date, end_date, prev_start, prev_end, period_label = ManagementDashboardService.get_filtered_queryset(request.GET)

    kpis, prev_kpis, comparison = ManagementDashboardService.calculate_kpis_with_comparison(curr_qs, prev_qs)
    top10 = ManagementDashboardService.get_top10_metrics(curr_qs)
    alerts = ManagementDashboardService.detect_management_alerts(curr_qs)

    top_prod_name = top10['top_products'][0]['name'] if top10['top_products'] else ""
    top_party_name = top10['top_parties'][0]['name'] if top10['top_parties'] else ""
    narrative_summary = ManagementDashboardService.generate_executive_narrative(
        kpis, comparison, top_prod_name, top_party_name
    )

    granularity = request.GET.get('granularity', 'daily')
    trends = ManagementDashboardService.get_tonnage_trend(start_date, end_date, granularity=granularity)
    heatmap_matrix = ManagementDashboardService.get_traffic_heatmap(curr_qs)

    from monitoring.models import MonitoringAlert, AlertStatus, AlertSeverity
    _alert_qs = MonitoringAlert.objects.filter(status__in=[AlertStatus.OPEN, AlertStatus.REVIEWED])
    if start_date:
        _alert_qs = _alert_qs.filter(created_at__date__gte=start_date)
    if end_date:
        _alert_qs = _alert_qs.filter(created_at__date__lte=end_date)
    monitoring_open_count = _alert_qs.count()
    monitoring_critical_count = _alert_qs.filter(
        severity__in=[AlertSeverity.CRITICAL, AlertSeverity.HIGH]
    ).count()

    ctx = _get_filter_context(request, curr_qs, start_date, end_date, period_label)
    ctx.update({
        'title': 'داشبورد جامع مدیریتی',
        'kpis': kpis,
        'prev_kpis': prev_kpis,
        'comparison': comparison,
        'top10': top10,
        'alerts': alerts,
        'monitoring_open_count': monitoring_open_count,
        'monitoring_critical_count': monitoring_critical_count,
        'narrative_summary': narrative_summary,
        'trends_json': json.dumps(trends),
        'heatmap_json': json.dumps(heatmap_matrix),
        'granularity': granularity,
        'today_jalali': get_today_jalali(),
    })
    return render(request, 'management/dashboard.html', ctx)

@login_required
@management_role_required
def api_dashboard_charts(request):
    """
    JSON API for dynamic chart updates without full page reloads.
    """
    curr_qs, _, start_date, end_date, _, _, _ = ManagementDashboardService.get_filtered_queryset(request.GET)
    granularity = request.GET.get('granularity', 'daily')
    trends = ManagementDashboardService.get_tonnage_trend(start_date, end_date, granularity=granularity)
    heatmap = ManagementDashboardService.get_traffic_heatmap(curr_qs)
    top10 = ManagementDashboardService.get_top10_metrics(curr_qs)

    return JsonResponse({
        'trends': trends,
        'heatmap': heatmap,
        'top_products': top10['top_products'],
        'top_parties': top10['top_parties'],
    })

@login_required
@management_role_required
def inbound_outbound_view(request):
    curr_qs, _, start_date, end_date, _, _, period_label = ManagementDashboardService.get_filtered_queryset(request.GET)
    if request.GET.get('export') == 'excel':
        return export_management_excel(curr_qs, format_jalali_date(start_date), format_jalali_date(end_date), "گزارش ورودی و خروجی")

    inout_data = ManagementReportService.get_inbound_outbound_data(curr_qs)
    ctx = _get_filter_context(request, curr_qs, start_date, end_date, period_label)
    ctx.update({
        'title': 'گزارش مدیریتی ورودی و خروجی کالا',
        'data': inout_data,
    })
    return render(request, 'management/inbound_outbound.html', ctx)

@login_required
@management_role_required
def purchase_view(request):
    curr_qs, _, start_date, end_date, _, _, period_label = ManagementDashboardService.get_filtered_queryset(request.GET)
    if request.GET.get('export') == 'excel':
        return export_management_excel(curr_qs, format_jalali_date(start_date), format_jalali_date(end_date), "گزارش مدیریتی خرید")

    purchase_data = ManagementReportService.get_purchase_data(curr_qs)
    ctx = _get_filter_context(request, curr_qs, start_date, end_date, period_label)
    ctx.update({
        'title': 'گزارش مدیریتی خرید و تامین‌کنندگان',
        'data': purchase_data,
    })
    return render(request, 'management/purchase_report.html', ctx)

@login_required
@management_role_required
def sales_view(request):
    curr_qs, _, start_date, end_date, _, _, period_label = ManagementDashboardService.get_filtered_queryset(request.GET)
    if request.GET.get('export') == 'excel':
        return export_management_excel(curr_qs, format_jalali_date(start_date), format_jalali_date(end_date), "گزارش مدیریتی فروش")

    sales_data = ManagementReportService.get_sales_data(curr_qs)
    ctx = _get_filter_context(request, curr_qs, start_date, end_date, period_label)
    ctx.update({
        'title': 'گزارش مدیریتی فروش و مشتریان',
        'data': sales_data,
    })
    return render(request, 'management/sales_report.html', ctx)

@login_required
@management_role_required
def products_view(request):
    curr_qs, _, start_date, end_date, _, _, period_label = ManagementDashboardService.get_filtered_queryset(request.GET)
    if request.GET.get('export') == 'excel':
        return export_management_excel(curr_qs, format_jalali_date(start_date), format_jalali_date(end_date), "گزارش مدیریتی محصولات")

    products_rows = ManagementReportService.get_product_analysis(curr_qs)
    ctx = _get_filter_context(request, curr_qs, start_date, end_date, period_label)
    ctx.update({
        'title': 'گزارش تحلیلی محصولات و تناژ',
        'products_rows': products_rows,
        'products_json': json.dumps([{'name': p['name'], 'net_ton': p['net_ton']} for p in products_rows[:8]]),
    })
    return render(request, 'management/products_report.html', ctx)

@login_required
@management_role_required
def parties_view(request):
    curr_qs, _, start_date, end_date, _, _, period_label = ManagementDashboardService.get_filtered_queryset(request.GET)
    if request.GET.get('export') == 'excel':
        return export_management_excel(curr_qs, format_jalali_date(start_date), format_jalali_date(end_date), "گزارش طرف‌های حساب")

    parties_rows = ManagementReportService.get_party_analysis(curr_qs)
    ctx = _get_filter_context(request, curr_qs, start_date, end_date, period_label)
    ctx.update({
        'title': 'گزارش تحلیلی طرف‌های حساب (مشتریان و تامین‌کنندگان)',
        'parties_rows': parties_rows,
        'parties_json': json.dumps([{'name': p['name'], 'net_ton': p['net_ton']} for p in parties_rows[:8]]),
    })
    return render(request, 'management/parties_report.html', ctx)

@login_required
@management_role_required
def discrepancies_view(request):
    try:
        threshold = int(request.GET.get('threshold_kg', 50))
    except (ValueError, TypeError):
        threshold = 50
    curr_qs, _, start_date, end_date, _, _, period_label = ManagementDashboardService.get_filtered_queryset(request.GET)
    if request.GET.get('export') == 'excel':
        return export_management_excel(curr_qs, format_jalali_date(start_date), format_jalali_date(end_date), "گزارش مغایرت‌های وزن")

    data = ManagementReportService.get_discrepancy_analysis(curr_qs, threshold_kg=threshold)
    ctx = _get_filter_context(request, curr_qs, start_date, end_date, period_label)
    ctx.update({
        'title': 'گزارش نظارتی مغایرت‌های وزن و تلورانس',
        'data': data,
        'threshold': threshold,
    })
    return render(request, 'management/discrepancies_report.html', ctx)

@login_required
@management_role_required
def loss_view(request):
    curr_qs, _, start_date, end_date, _, _, period_label = ManagementDashboardService.get_filtered_queryset(request.GET)
    if request.GET.get('export') == 'excel':
        return export_management_excel(curr_qs, format_jalali_date(start_date), format_jalali_date(end_date), "گزارش افت و کسورات")

    loss_data = ManagementReportService.get_loss_analysis(curr_qs)
    ctx = _get_filter_context(request, curr_qs, start_date, end_date, period_label)
    ctx.update({
        'title': 'گزارش مدیریتی افت و کسورات کالا',
        'data': loss_data,
    })
    return render(request, 'management/loss_report.html', ctx)

@login_required
@management_role_required
def drivers_vehicles_view(request):
    curr_qs, _, start_date, end_date, _, _, period_label = ManagementDashboardService.get_filtered_queryset(request.GET)
    if request.GET.get('export') == 'excel':
        return export_management_excel(curr_qs, format_jalali_date(start_date), format_jalali_date(end_date), "گزارش رانندگان و ناوگان")

    drivers_rows, vehicles_rows = ManagementReportService.get_fleet_performance(curr_qs)
    ctx = _get_filter_context(request, curr_qs, start_date, end_date, period_label)
    ctx.update({
        'title': 'گزارش عملکرد رانندگان و ناوگان خودرویی',
        'drivers_rows': drivers_rows,
        'vehicles_rows': vehicles_rows,
    })
    return render(request, 'management/drivers_vehicles_report.html', ctx)

@login_required
@management_role_required
def routes_view(request):
    curr_qs, _, start_date, end_date, _, _, period_label = ManagementDashboardService.get_filtered_queryset(request.GET)
    origins, destinations, routes = ManagementReportService.get_routes_analysis(curr_qs)
    ctx = _get_filter_context(request, curr_qs, start_date, end_date, period_label)
    ctx.update({
        'title': 'گزارش مبادی، مقاصد و مسیرهای حمل',
        'origins': origins,
        'destinations': destinations,
        'routes': routes,
    })
    return render(request, 'management/routes_report.html', ctx)

@login_required
@management_role_required
def operations_view(request):
    curr_qs, _, start_date, end_date, _, _, period_label = ManagementDashboardService.get_filtered_queryset(request.GET)
    ops_data = ManagementReportService.get_operations_performance(curr_qs)
    ctx = _get_filter_context(request, curr_qs, start_date, end_date, period_label)
    ctx.update({
        'title': 'گزارش عملکرد باسکول، زمان توقف و اپراتورها',
        'data': ops_data,
    })
    return render(request, 'management/operations_performance.html', ctx)

@login_required
@management_role_required
def monthly_report_view(request):
    j_today = gregorian_to_jalali(get_today_gregorian())
    year = int(request.GET.get('year', j_today.year))
    month = int(request.GET.get('month', j_today.month))

    monthly_data = ManagementReportService.get_monthly_executive_data(year, month)
    return render(request, 'management/monthly_report.html', {
        'title': f"گزارش مدیریتی ماهانه ({monthly_data['month_title']})",
        'data': monthly_data,
        'current_year': j_today.year,
        'current_month': j_today.month,
        'years_list': [j_today.year - i for i in range(4)],
        'months_list': [(m, get_jalali_month_name(m)) for m in range(1, 13)],
    })

@login_required
@management_role_required
def yearly_report_view(request):
    j_today = gregorian_to_jalali(get_today_gregorian())
    year = int(request.GET.get('year', j_today.year))

    yearly_data = ManagementReportService.get_yearly_executive_data(year)
    return render(request, 'management/yearly_report.html', {
        'title': f"گزارش مدیریتی سالانه ({yearly_data['year_title']})",
        'data': yearly_data,
        'year': year,
        'current_year': j_today.year,
        'years_list': [j_today.year - i for i in range(4)],
        'chart_json': json.dumps(yearly_data['chart_data']),
    })

@login_required
@management_role_required
def executive_print_view(request):
    """
    Formal Printable & PDF-ready Executive Briefing.
    """
    curr_qs, prev_qs, start_date, end_date, _, _, period_label = ManagementDashboardService.get_filtered_queryset(request.GET)
    kpis, _, comparison = ManagementDashboardService.calculate_kpis_with_comparison(curr_qs, prev_qs)
    top10 = ManagementDashboardService.get_top10_metrics(curr_qs)
    alerts = ManagementDashboardService.detect_management_alerts(curr_qs)
    top_prod = top10['top_products'][0]['name'] if top10['top_products'] else ""
    top_party = top10['top_parties'][0]['name'] if top10['top_parties'] else ""
    narrative = ManagementDashboardService.generate_executive_narrative(kpis, comparison, top_prod, top_party)
    products_rows = ManagementReportService.get_product_analysis(curr_qs)
    parties_rows = ManagementReportService.get_party_analysis(curr_qs)

    settings_obj = SystemSetting.get_settings()

    return render(request, 'management/executive_print.html', {
        'title': 'گزارش رسمی و تحلیلی مدیریت باسکول',
        'kpis': kpis,
        'comparison': comparison,
        'top10': top10,
        'alerts': alerts,
        'narrative': narrative,
        'products_rows': products_rows[:10],
        'parties_rows': parties_rows[:10],
        'start_date_jalali': format_jalali_date(start_date),
        'end_date_jalali': format_jalali_date(end_date),
        'today_jalali': get_today_jalali(),
        'settings': settings_obj,
        'user': request.user,
    })

@login_required
@management_role_required
def tv_monitor_view(request):
    """
    Full-Screen Industrial Dark Wallboard Monitor Mode for Management Office TV.
    """
    today_g = get_today_gregorian()
    today_qs = WeighTicket.objects.filter(
        Q(first_weight_date=today_g) | Q(created_at__date=today_g)
    )
    yesterday_g = today_g - timedelta(days=1)
    yest_qs = WeighTicket.objects.filter(
        Q(first_weight_date=yesterday_g) | Q(created_at__date=yesterday_g)
    )

    kpis, _, comparison = ManagementDashboardService.calculate_kpis_with_comparison(today_qs, yest_qs)
    seven_days_ago = today_g - timedelta(days=6)
    trends = ManagementDashboardService.get_tonnage_trend(seven_days_ago, today_g, granularity='daily')
    recent_activity = WeighTicket.objects.select_related('product', 'party', 'driver').order_by('-id')[:10]
    alerts = ManagementDashboardService.detect_management_alerts(today_qs)

    return render(request, 'management/tv_monitor.html', {
        'title': 'مانیتورینگ زنده مدیریت (Wallboard Mode)',
        'kpis': kpis,
        'comparison': comparison,
        'trends_json': json.dumps(trends),
        'recent_activity': recent_activity,
        'alerts': alerts,
        'today_jalali': get_today_jalali(),
        'settings': SystemSetting.get_settings(),
    })

@login_required
@management_role_required
@require_POST
def api_save_filter(request):
    title = request.POST.get('title', '').strip()
    if not title:
        return JsonResponse({'status': 'error', 'message': 'عنوان فیلتر الزامی است.'}, status=400)

    filters = {k: v for k, v in request.POST.items() if k not in ['csrfmiddlewaretoken', 'title']}
    saved = SavedReport.objects.create(
        title=title,
        report_type=request.POST.get('report_type', 'dashboard'),
        filters_json=filters,
        created_by=request.user
    )
    return JsonResponse({'status': 'ok', 'id': saved.id, 'title': saved.title})

@login_required
@management_role_required
def api_load_filters(request):
    reports = SavedReport.objects.filter(created_by=request.user).values('id', 'title', 'filters_json', 'created_at')
    return JsonResponse({'status': 'ok', 'reports': list(reports)})
