import json
from decimal import Decimal
from datetime import datetime, date, timedelta
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Sum, Count, Q, Avg
from django.utils import timezone

from weighbridge.models import WeighTicket, TicketStatus
from masterdata.models import Product, Party, Driver, Vehicle, OperationType
from core.jalali import (
    get_today_gregorian, get_today_jalali, format_jalali_date,
    get_jalali_range_gregorian, jalali_to_gregorian
)

from management.kpi_service import OperationalKPIService

@login_required
def dashboard_index(request):
    """
    Executive Management Dashboard for Prima Bascol Weighbridge.
    Synchronized with OperationalKPIService.
    """
    today_g = get_today_gregorian()
    
    # 1. Authoritative Daily Operational Summary from OperationalKPIService
    summary = OperationalKPIService.get_daily_operational_summary(today_g)
    
    today_count = summary["today_count"]
    today_completed_count = summary["today_completed_count"]
    today_net_kg = summary["today_net_kg"]
    today_tonnage = summary["today_tonnage"]
    today_loads = summary["today_loads"]
    today_loss_kg = summary["today_loss_kg"]
    today_inbound_net = summary["today_inbound_net"]
    today_inbound_ton = summary["today_inbound_ton"]
    today_outbound_net = summary["today_outbound_net"]
    today_outbound_ton = summary["today_outbound_ton"]
    today_discrepancies_count = summary["today_discrepancies_count"]
    waiting_trucks_count = summary["waiting_trucks_count"]
    open_alerts_count = summary["open_alerts_count"]
    today_critical_alerts = summary["today_critical_alerts"]

    # Date Filtering for Recent Tickets (Default: Today)
    period = request.GET.get("period", "today").strip().lower()
    custom_date_str = request.GET.get("date", "").strip()

    recent_tickets_qs = OperationalKPIService.get_annotated_queryset(
        WeighTicket.objects.select_related("product", "party", "driver")
    )

    period_label = "امروز"
    active_date_val = ""

    if custom_date_str:
        period = "custom"
        target_date = jalali_to_gregorian(custom_date_str)
        if not target_date:
            try:
                target_date = datetime.strptime(custom_date_str, "%Y-%m-%d").date()
            except Exception:
                target_date = None
        if target_date:
            recent_tickets_qs = recent_tickets_qs.filter(
                Q(arrival_date=target_date) |
                (Q(status=TicketStatus.COMPLETED) & Q(completion_date=target_date))
            )
            period_label = f"تاریخ {custom_date_str}"
            active_date_val = custom_date_str
        else:
            # Fallback to today if invalid format
            start_date, end_date = get_jalali_range_gregorian("today")
            recent_tickets_qs = recent_tickets_qs.filter(
                Q(arrival_date=start_date) |
                (Q(status=TicketStatus.COMPLETED) & Q(completion_date=start_date))
            )
            period_label = "امروز"
            period = "today"
    elif period == "yesterday":
        start_date, end_date = get_jalali_range_gregorian("yesterday")
        recent_tickets_qs = recent_tickets_qs.filter(
            Q(arrival_date=start_date) |
            (Q(status=TicketStatus.COMPLETED) & Q(completion_date=start_date))
        )
        period_label = "دیروز"
    elif period == "week":
        start_date, end_date = get_jalali_range_gregorian("this_week")
        recent_tickets_qs = recent_tickets_qs.filter(
            Q(arrival_date__range=[start_date, end_date]) |
            (Q(status=TicketStatus.COMPLETED) & Q(completion_date__range=[start_date, end_date]))
        )
        period_label = "هفته جاری"
    elif period == "month":
        start_date, end_date = get_jalali_range_gregorian("this_month")
        recent_tickets_qs = recent_tickets_qs.filter(
            Q(arrival_date__range=[start_date, end_date]) |
            (Q(status=TicketStatus.COMPLETED) & Q(completion_date__range=[start_date, end_date]))
        )
        period_label = "ماه جاری"
    elif period == "year":
        start_date, end_date = get_jalali_range_gregorian("this_year")
        recent_tickets_qs = recent_tickets_qs.filter(
            Q(arrival_date__range=[start_date, end_date]) |
            (Q(status=TicketStatus.COMPLETED) & Q(completion_date__range=[start_date, end_date]))
        )
        period_label = "سال جاری"
    elif period == "all":
        period_label = "همه قبوض"
    else:  # Default: today
        period = "today"
        start_date, end_date = get_jalali_range_gregorian("today")
        recent_tickets_qs = recent_tickets_qs.filter(
            Q(arrival_date=start_date) |
            (Q(status=TicketStatus.COMPLETED) & Q(completion_date=start_date))
        )
        period_label = "امروز"

    recent_tickets = recent_tickets_qs.order_by("-id")[:50]

    is_operator = (
        not request.user.is_superuser and
        hasattr(request.user, "profile") and
        request.user.profile.role == "weighbridge_operator"
    )

    return render(request, "dashboard/index.html", {
        "open_alerts_count": open_alerts_count,
        "today_critical_alerts": today_critical_alerts,
        "today_trips": today_count,
        "today_count": today_count,
        "today_completed_count": today_completed_count,
        "today_net": today_net_kg,
        "today_net_kg": today_net_kg,
        "today_net_ton": today_tonnage,
        "today_tonnage": today_tonnage,
        "today_loads": today_loads,
        "today_loss_kg": today_loss_kg,
        "today_inbound": today_inbound_net,
        "today_inbound_net": today_inbound_net,
        "today_inbound_ton": today_inbound_ton,
        "today_outbound": today_outbound_net,
        "today_outbound_net": today_outbound_net,
        "today_outbound_ton": today_outbound_ton,
        "discrepancies_count": today_discrepancies_count,
        "today_discrepancies_count": today_discrepancies_count,
        "waiting_trucks_count": waiting_trucks_count,
        "recent_tickets": recent_tickets,
        "selected_period": period,
        "period_label": period_label,
        "custom_date_val": active_date_val,
        "is_operator": is_operator,
        "title": "داشبورد عملیات باسکول" if is_operator else "داشبورد مدیریتی و کنترل توزین",
    })

@login_required
def charts_data(request):
    """
    JSON API endpoint providing datasets for dashboard Chart.js widgets.
    Uses OperationalKPIService with single-query aggregation and explicit unit definitions.
    """
    today_g = get_today_gregorian()
    start_date_30 = today_g - timedelta(days=29)

    # 1. 30-Day Trend (in metric tons) via single-pass aggregation
    trends_30 = OperationalKPIService.get_tonnage_trend(start_date_30, today_g, granularity="daily")

    # 2. Product Share (Top 6 products by completed net weight in metric tons)
    prod_share = OperationalKPIService.get_product_share(limit=6)

    # 3. 30-Day Inbound vs Outbound comparison (in metric tons)
    kpis_30 = OperationalKPIService.calculate_period_kpis(start_date=start_date_30, end_date=today_g)
    inbound_ton = kpis_30["inbound_net_ton"]
    outbound_ton = kpis_30["outbound_net_ton"]

    # 4. Top Parties (Top 6 parties by completed net weight in metric tons)
    party_share = OperationalKPIService.get_party_share(limit=6)

    return JsonResponse({
        "unit": "ton",
        "unit_display": "تن (Ton)",
        "dates_30": trends_30["labels"],
        "tonnage_30": trends_30["net"],
        "trips_30": trends_30["trips"],
        "product_labels": prod_share["labels"],
        "product_values": prod_share["values"],
        "inbound_tonnage": inbound_ton,
        "outbound_tonnage": outbound_ton,
        "party_labels": party_share["labels"],
        "party_values": party_share["values"],
    })
