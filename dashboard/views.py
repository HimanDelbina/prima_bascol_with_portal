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

@login_required
def dashboard_index(request):
    """
    Executive Management Dashboard for Prima Bascol Weighbridge.
    """
    today_g = get_today_gregorian()
    
    # Querysets
    today_tickets = WeighTicket.objects.filter(
        Q(first_weight_date=today_g) | Q(created_at__date=today_g)
    )

    # 1. KPI Cards Metrics
    today_count = today_tickets.count()
    today_completed_count = today_tickets.filter(status=TicketStatus.COMPLETED).count()
    
    today_aggregates = today_tickets.aggregate(
        sum_net=Sum("net_weight"),
        sum_gross=Sum("gross_weight"),
        sum_tare=Sum("tare_weight"),
        sum_loss=Sum("loss_weight"),
        sum_loads=Sum("load_count"),
    )
    
    today_net_kg = today_aggregates["sum_net"] or Decimal("0")
    today_tonnage = round(today_net_kg / Decimal("1000"), 2)
    today_loads = today_aggregates["sum_loads"] or 0
    today_loss_kg = today_aggregates["sum_loss"] or Decimal("0")

    # Inbound / Outbound breakdown
    today_inbound_net = today_tickets.filter(
        operation_type__direction="inbound"
    ).aggregate(s=Sum("net_weight"))["s"] or Decimal("0")
    today_inbound_ton = round(today_inbound_net / Decimal("1000"), 2)

    today_outbound_net = today_tickets.filter(
        operation_type__direction="outbound"
    ).aggregate(s=Sum("net_weight"))["s"] or Decimal("0")
    today_outbound_ton = round(today_outbound_net / Decimal("1000"), 2)

    # Discrepancies and waiting trucks
    today_discrepancies_count = today_tickets.filter(is_tolerance_exceeded=True).count()
    
    waiting_trucks_count = WeighTicket.objects.filter(
        status__in=[TicketStatus.WAITING_SECOND, TicketStatus.FIRST_REGISTERED]
    ).count()

    # Monitoring Alerts
    from monitoring.models import MonitoringAlert, AlertStatus, AlertSeverity
    open_alerts_count = MonitoringAlert.objects.filter(status__in=[AlertStatus.OPEN, AlertStatus.REVIEWED]).count()
    today_critical_alerts = MonitoringAlert.objects.filter(
        created_at__date=today_g,
        severity__in=[AlertSeverity.CRITICAL, AlertSeverity.HIGH],
        status__in=[AlertStatus.OPEN, AlertStatus.REVIEWED]
    ).count()

    # Date Filtering for Recent Tickets (Default: Today)
    period = request.GET.get("period", "today").strip().lower()
    custom_date_str = request.GET.get("date", "").strip()

    recent_tickets_qs = WeighTicket.objects.select_related(
        "product", "party", "driver"
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
                Q(first_weight_date=target_date) | Q(created_at__date=target_date)
            )
            period_label = f"تاریخ {custom_date_str}"
            active_date_val = custom_date_str
        else:
            # Fallback to today if invalid format
            start_date, end_date = get_jalali_range_gregorian("today")
            recent_tickets_qs = recent_tickets_qs.filter(
                Q(first_weight_date=start_date) | Q(created_at__date=start_date)
            )
            period_label = "امروز"
            period = "today"
    elif period == "yesterday":
        start_date, end_date = get_jalali_range_gregorian("yesterday")
        recent_tickets_qs = recent_tickets_qs.filter(
            Q(first_weight_date=start_date) | Q(created_at__date=start_date)
        )
        period_label = "دیروز"
    elif period == "week":
        start_date, end_date = get_jalali_range_gregorian("this_week")
        recent_tickets_qs = recent_tickets_qs.filter(
            Q(first_weight_date__range=[start_date, end_date]) | Q(created_at__date__range=[start_date, end_date])
        )
        period_label = "هفته جاری"
    elif period == "month":
        start_date, end_date = get_jalali_range_gregorian("this_month")
        recent_tickets_qs = recent_tickets_qs.filter(
            Q(first_weight_date__range=[start_date, end_date]) | Q(created_at__date__range=[start_date, end_date])
        )
        period_label = "ماه جاری"
    elif period == "year":
        start_date, end_date = get_jalali_range_gregorian("this_year")
        recent_tickets_qs = recent_tickets_qs.filter(
            Q(first_weight_date__range=[start_date, end_date]) | Q(created_at__date__range=[start_date, end_date])
        )
        period_label = "سال جاری"
    elif period == "all":
        period_label = "همه قبوض"
    else:  # Default: today
        period = "today"
        start_date, end_date = get_jalali_range_gregorian("today")
        recent_tickets_qs = recent_tickets_qs.filter(
            Q(first_weight_date=start_date) | Q(created_at__date=start_date)
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
    """
    today_g = get_today_gregorian()
    
    # 1. 30-Day Tonnage and Trips Trend
    dates_30 = []
    tonnage_30 = []
    trips_30 = []
    
    for i in range(29, -1, -1):
        target_day = today_g - timedelta(days=i)
        day_qs = WeighTicket.objects.filter(
            Q(first_weight_date=target_day) | Q(created_at__date=target_day)
        )
        day_net = day_qs.aggregate(s=Sum("net_weight"))["s"] or Decimal("0")
        day_trips = day_qs.count()
        
        dates_30.append(format_jalali_date(target_day, fmt="%m/%d"))
        tonnage_30.append(float(day_net))
        trips_30.append(day_trips)

    # 2. Product Share (Top 6 products by net weight)
    top_prods_qs = WeighTicket.objects.filter(
        status=TicketStatus.COMPLETED,
        product__isnull=False
    ).values("product__name").annotate(
        total_net=Sum("net_weight")
    ).order_by("-total_net")[:6]
    
    product_labels = [p["product__name"] or "نامشخص" for p in top_prods_qs]
    product_values = [float(round((p["total_net"] or Decimal("0")) / Decimal("1000"), 2)) for p in top_prods_qs]

    # 3. Inbound vs Outbound comparison (in kg)
    inbound_net = WeighTicket.objects.filter(
        status=TicketStatus.COMPLETED,
        operation_type__direction="inbound"
    ).aggregate(s=Sum("net_weight"))["s"] or Decimal("0")
    
    outbound_net = WeighTicket.objects.filter(
        status=TicketStatus.COMPLETED,
        operation_type__direction="outbound"
    ).aggregate(s=Sum("net_weight"))["s"] or Decimal("0")

    # 4. Top Parties (Top 6 parties by net weight in kg)
    top_parties_qs = WeighTicket.objects.filter(
        status=TicketStatus.COMPLETED,
        party__isnull=False
    ).values("party__name").annotate(
        total_net=Sum("net_weight")
    ).order_by("-total_net")[:6]
    
    party_labels = [p["party__name"] or "نامشخص" for p in top_parties_qs]
    party_values = [float(p["total_net"] or Decimal("0")) for p in top_parties_qs]

    return JsonResponse({
        "dates_30": dates_30,
        "tonnage_30": tonnage_30,
        "trips_30": trips_30,
        "product_labels": product_labels,
        "product_values": product_values,
        "inbound_tonnage": float(inbound_net),
        "outbound_tonnage": float(outbound_net),
        "party_labels": party_labels,
        "party_values": party_values,
    })
