import json
from decimal import Decimal
from datetime import timedelta
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Sum, Count, Q, Avg
from django.utils import timezone

from weighbridge.models import WeighTicket, TicketStatus
from masterdata.models import Product, Party, Driver, Vehicle, OperationType
from core.jalali import get_today_gregorian, get_today_jalali, format_jalali_date, get_jalali_range_gregorian

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

    # Recent 8 tickets
    recent_tickets = WeighTicket.objects.select_related(
        "product", "party", "driver"
    ).order_by("-id")[:8]

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
        "title": "داشبورد مدیریتی و کنترل توزین",
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
