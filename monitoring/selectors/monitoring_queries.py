from datetime import datetime, timedelta
from decimal import Decimal
import numpy as np
from django.db.models import Avg, StdDev, Min, Max, Count, Sum, Q, F
from django.utils import timezone

from weighbridge.models import WeighTicket, TicketStatus
from audit.models import AuditLog, AuditAction
from monitoring.models import MonitoringAlert, AlertStatus, AlertSeverity, AlertType


def compute_median_from_values(values_list):
    """Compute median from a list of numbers/Decimals."""
    if not values_list:
        return Decimal("0.00")
    floats = [float(v) for v in values_list if v is not None]
    if not floats:
        return Decimal("0.00")
    med = float(np.median(floats))
    return Decimal(str(round(med, 2)))


def get_vehicle_tare_stats(vehicle_id=None, plate=None, exclude_ticket_id=None) -> dict:
    """
    PostgreSQL-optimized historical statistics for a vehicle's tare weight.
    Only completed tickets with tare_weight > 0 are considered.
    """
    qs = WeighTicket.objects.filter(
        status=TicketStatus.COMPLETED,
        tare_weight__gt=0
    )
    
    if vehicle_id:
        qs = qs.filter(vehicle_id=vehicle_id)
    elif plate:
        qs = qs.filter(license_plate_display=plate)
    else:
        return {"count": 0, "avg": Decimal("0"), "std_dev": Decimal("0"), "min": Decimal("0"), "max": Decimal("0"), "median": Decimal("0"), "last_5_avg": Decimal("0"), "last_10_avg": Decimal("0"), "recent_records": []}

    if exclude_ticket_id:
        qs = qs.exclude(pk=exclude_ticket_id)

    agg = qs.aggregate(
        cnt=Count("id"),
        avg_tare=Avg("tare_weight"),
        std_tare=StdDev("tare_weight"),
        min_tare=Min("tare_weight"),
        max_tare=Max("tare_weight"),
    )

    count = agg["cnt"] or 0
    if count == 0:
        return {
            "count": 0,
            "avg": Decimal("0.00"),
            "std_dev": Decimal("0.00"),
            "min": Decimal("0.00"),
            "max": Decimal("0.00"),
            "median": Decimal("0.00"),
            "last_5_avg": Decimal("0.00"),
            "last_10_avg": Decimal("0.00"),
            "recent_records": [],
        }

    # Fetch recent records for last 5/10 averages & median & historical comparison table
    recent_qs = qs.order_by("-id")[:10]
    recent_records = list(recent_qs)
    
    last_10_values = [t.tare_weight for t in recent_records]
    last_5_values = last_10_values[:5]

    last_5_avg = Decimal(str(round(float(np.mean([float(x) for x in last_5_values])), 2))) if last_5_values else Decimal("0.00")
    last_10_avg = Decimal(str(round(float(np.mean([float(x) for x in last_10_values])), 2))) if last_10_values else Decimal("0.00")
    
    # All values for median if count < 500, else approximate from recent/all
    all_values = list(qs.values_list("tare_weight", flat=True)[:500])
    median_val = compute_median_from_values(all_values)

    return {
        "count": count,
        "avg": Decimal(str(round(float(agg["avg_tare"] or 0), 2))),
        "std_dev": Decimal(str(round(float(agg["std_tare"] or 0), 2))),
        "min": Decimal(str(agg["min_tare"] or 0)),
        "max": Decimal(str(agg["max_tare"] or 0)),
        "median": median_val,
        "last_5_avg": last_5_avg,
        "last_10_avg": last_10_avg,
        "recent_records": recent_records,
    }


def get_party_discrepancy_stats(party_id, exclude_ticket_id=None) -> dict:
    """
    Historical discrepancy statistics for a specific Party.
    """
    if not party_id:
        return {"count": 0, "avg_diff": Decimal("0"), "std_dev_diff": Decimal("0"), "avg_diff_percent": Decimal("0"), "last_10_avg": Decimal("0"), "recent_records": []}

    qs = WeighTicket.objects.filter(
        party_id=party_id,
        status=TicketStatus.COMPLETED,
        sent_weight__gt=0,
        net_weight__gt=0
    )
    if exclude_ticket_id:
        qs = qs.exclude(pk=exclude_ticket_id)

    agg = qs.aggregate(
        cnt=Count("id"),
        avg_diff=Avg("weight_difference"),
        std_diff=StdDev("weight_difference"),
        avg_pct=Avg("weight_difference_percent"),
    )

    count = agg["cnt"] or 0
    if count == 0:
        return {
            "count": 0,
            "avg_diff": Decimal("0.00"),
            "std_dev_diff": Decimal("0.00"),
            "avg_diff_percent": Decimal("0.00"),
            "last_10_avg": Decimal("0.00"),
            "recent_records": [],
        }

    recent_qs = qs.order_by("-id")[:10]
    recent_records = list(recent_qs)
    last_10_diffs = [float(t.weight_difference) for t in recent_records]
    last_10_avg = Decimal(str(round(float(np.mean(last_10_diffs)), 2))) if last_10_diffs else Decimal("0.00")

    return {
        "count": count,
        "avg_diff": Decimal(str(round(float(agg["avg_diff"] or 0), 2))),
        "std_dev_diff": Decimal(str(round(float(agg["std_diff"] or 0), 2))),
        "avg_diff_percent": Decimal(str(round(float(agg["avg_pct"] or 0), 2))),
        "last_10_avg": last_10_avg,
        "recent_records": recent_records,
    }


def get_loss_stats(product_id=None, party_id=None, exclude_ticket_id=None) -> dict:
    """
    Historical Loss percentage statistics for Product, Party, or Product+Party.
    """
    base_qs = WeighTicket.objects.filter(
        status=TicketStatus.COMPLETED,
        net_weight__gt=0
    )
    if exclude_ticket_id:
        base_qs = base_qs.exclude(pk=exclude_ticket_id)

    # 1. Try Product + Party
    selected_level = "product_party"
    selected_level_fa = "ترکیب محصول و طرف حساب"
    qs = base_qs
    if product_id and party_id:
        qs = base_qs.filter(product_id=product_id, party_id=party_id)
    
    cnt = qs.count() if (product_id and party_id) else 0

    # 2. Fallback to Product if sample size < 10
    if (cnt < 10 or not (product_id and party_id)) and product_id:
        qs = base_qs.filter(product_id=product_id)
        selected_level = "product"
        selected_level_fa = "محصول"
        cnt = qs.count()

    # 3. Fallback to Party if product has < 10 and party exists
    if cnt < 10 and party_id:
        party_qs = base_qs.filter(party_id=party_id)
        if party_qs.count() >= 10:
            qs = party_qs
            selected_level = "party"
            selected_level_fa = "طرف حساب"
            cnt = qs.count()

    if cnt == 0:
        return {
            "count": 0,
            "level": selected_level,
            "level_fa": selected_level_fa,
            "avg_loss_pct": Decimal("0.00"),
            "std_dev_loss": Decimal("0.00"),
            "min_loss_pct": Decimal("0.00"),
            "max_loss_pct": Decimal("0.00"),
            "median_loss_pct": Decimal("0.00"),
            "last_10_avg": Decimal("0.00"),
            "recent_records": [],
        }

    agg = qs.aggregate(
        cnt=Count("id"),
        avg_loss=Avg("loss_percent"),
        std_loss=StdDev("loss_percent"),
        min_loss=Min("loss_percent"),
        max_loss=Max("loss_percent"),
    )

    recent_records = list(qs.order_by("-id")[:10])
    last_10_vals = [float(t.loss_percent) for t in recent_records]
    last_10_avg = Decimal(str(round(float(np.mean(last_10_vals)), 2))) if last_10_vals else Decimal("0.00")
    
    all_vals = list(qs.values_list("loss_percent", flat=True)[:500])
    median_val = compute_median_from_values(all_vals)

    return {
        "count": agg["cnt"] or 0,
        "level": selected_level,
        "level_fa": selected_level_fa,
        "avg_loss_pct": Decimal(str(round(float(agg["avg_loss"] or 0), 2))),
        "std_dev_loss": Decimal(str(round(float(agg["std_loss"] or 0), 2))),
        "min_loss_pct": Decimal(str(agg["min_loss"] or 0)),
        "max_loss_pct": Decimal(str(agg["max_loss"] or 0)),
        "median_loss_pct": median_val,
        "last_10_avg": last_10_avg,
        "recent_records": recent_records,
    }


def get_net_weight_stats(vehicle_id=None, plate=None, product_id=None, exclude_ticket_id=None, min_history=10) -> dict:
    """
    Hierarchical Net Weight Baseline:
    1. Vehicle + Product (if count >= min_history)
    2. Vehicle (if count >= min_history)
    3. Product (if count >= min_history)
    4. Global (if count >= min_history)
    """
    base_qs = WeighTicket.objects.filter(
        status=TicketStatus.COMPLETED,
        net_weight__gt=0
    )
    if exclude_ticket_id:
        base_qs = base_qs.exclude(pk=exclude_ticket_id)

    levels = []
    # Level 1: Vehicle + Product
    if (vehicle_id or plate) and product_id:
        vp_q = Q(vehicle_id=vehicle_id) if vehicle_id else Q(license_plate_display=plate)
        levels.append(("vehicle_product", "خودرو + محصول", base_qs.filter(vp_q, product_id=product_id)))

    # Level 2: Vehicle
    if vehicle_id or plate:
        v_q = Q(vehicle_id=vehicle_id) if vehicle_id else Q(license_plate_display=plate)
        levels.append(("vehicle", "خودرو (تمام محصولات)", base_qs.filter(v_q)))

    # Level 3: Product
    if product_id:
        levels.append(("product", "محصول (تمام ناوگان)", base_qs.filter(product_id=product_id)))

    # Level 4: Global
    levels.append(("global", "کل قبوض سیستم", base_qs))

    selected_level = "insufficient"
    selected_level_fa = "داده ناکافی"
    selected_qs = base_qs.none()
    count = 0

    for code, label_fa, qs in levels:
        c = qs.count()
        if c >= min_history:
            selected_level = code
            selected_level_fa = label_fa
            selected_qs = qs
            count = c
            break

    # If none met min_history, pick highest available or return empty
    if count == 0 and levels:
        best_code, best_fa, best_qs = levels[0]
        c = best_qs.count()
        selected_level = best_code
        selected_level_fa = best_fa
        selected_qs = best_qs
        count = c

    if count == 0:
        return {
            "count": 0,
            "level": selected_level,
            "level_fa": selected_level_fa,
            "avg_net": Decimal("0.00"),
            "std_dev_net": Decimal("0.00"),
            "min_net": Decimal("0.00"),
            "max_net": Decimal("0.00"),
            "median_net": Decimal("0.00"),
            "recent_records": [],
        }

    agg = selected_qs.aggregate(
        cnt=Count("id"),
        avg_net=Avg("net_weight"),
        std_net=StdDev("net_weight"),
        min_net=Min("net_weight"),
        max_net=Max("net_weight"),
    )

    recent_records = list(selected_qs.order_by("-id")[:10])
    all_vals = list(selected_qs.values_list("net_weight", flat=True)[:500])
    median_val = compute_median_from_values(all_vals)

    return {
        "count": agg["cnt"] or 0,
        "level": selected_level,
        "level_fa": selected_level_fa,
        "avg_net": Decimal(str(round(float(agg["avg_net"] or 0), 2))),
        "std_dev_net": Decimal(str(round(float(agg["std_net"] or 0), 2))),
        "min_net": Decimal(str(agg["min_net"] or 0)),
        "max_net": Decimal(str(agg["max_net"] or 0)),
        "median_net": median_val,
        "recent_records": recent_records,
    }


def get_ticket_turnaround_minutes(ticket) -> float | None:
    """Calculate actual elapsed turnaround time in minutes for a ticket."""
    if not ticket.first_weight_date or not ticket.first_weight_time:
        if ticket.created_at:
            t1 = ticket.created_at
        else:
            return None
    else:
        t1 = datetime.combine(ticket.first_weight_date, ticket.first_weight_time)
        if timezone.is_naive(t1):
            t1 = timezone.make_aware(t1)

    if ticket.status == TicketStatus.COMPLETED and ticket.second_weight_date and ticket.second_weight_time:
        t2 = datetime.combine(ticket.second_weight_date, ticket.second_weight_time)
        if timezone.is_naive(t2):
            t2 = timezone.make_aware(t2)
    else:
        t2 = timezone.now()

    diff_seconds = (t2 - t1).total_seconds()
    return round(diff_seconds / 60.0, 1)


def get_waiting_time_stats(product_id=None, unload_location_id=None, party_id=None, exclude_ticket_id=None) -> dict:
    """
    Historical turnaround time baseline (in minutes) for operations of similar type.
    """
    base_qs = WeighTicket.objects.filter(
        status=TicketStatus.COMPLETED,
        first_weight_date__isnull=False,
        first_weight_time__isnull=False,
        second_weight_date__isnull=False,
        second_weight_time__isnull=False,
    )
    if exclude_ticket_id:
        base_qs = base_qs.exclude(pk=exclude_ticket_id)

    levels = []
    if product_id and unload_location_id:
        levels.append(("prod_unload", "محصول + جایگاه تخلیه", base_qs.filter(product_id=product_id, unload_location_id=unload_location_id)))
    if product_id:
        levels.append(("prod", "محصول", base_qs.filter(product_id=product_id)))
    if unload_location_id:
        levels.append(("unload", "جایگاه تخلیه", base_qs.filter(unload_location_id=unload_location_id)))
    if party_id:
        levels.append(("party", "طرف حساب", base_qs.filter(party_id=party_id)))
    levels.append(("global", "کل عملیات", base_qs))

    selected_level = "global"
    selected_level_fa = "کل عملیات"
    selected_qs = base_qs

    for code, fa, qs in levels:
        if qs.count() >= 5:
            selected_level = code
            selected_level_fa = fa
            selected_qs = qs
            break

    tickets_sample = list(selected_qs.order_by("-id")[:100])
    durations = []
    for t in tickets_sample:
        mins = get_ticket_turnaround_minutes(t)
        if mins is not None and 0 <= mins <= 1440:  # within 24 hours
            durations.append(mins)

    if not durations:
        return {
            "count": 0,
            "level": selected_level,
            "level_fa": selected_level_fa,
            "avg_minutes": Decimal("45.00"),  # Standard fallback
            "std_dev_minutes": Decimal("15.00"),
            "min_minutes": Decimal("10.00"),
            "max_minutes": Decimal("120.00"),
            "median_minutes": Decimal("40.00"),
        }

    avg_m = float(np.mean(durations))
    std_m = float(np.std(durations)) if len(durations) > 1 else 0.0
    med_m = float(np.median(durations))

    return {
        "count": len(durations),
        "level": selected_level,
        "level_fa": selected_level_fa,
        "avg_minutes": Decimal(str(round(avg_m, 1))),
        "std_dev_minutes": Decimal(str(round(std_m, 1))),
        "min_minutes": Decimal(str(round(min(durations), 1))),
        "max_minutes": Decimal(str(round(max(durations), 1))),
        "median_minutes": Decimal(str(round(med_m, 1))),
    }


def get_ticket_risk_score(ticket_id) -> tuple[int, str]:
    """
    Compute ticket risk score (0 to 100) and risk level text from active open/reviewed alerts.
    """
    alerts = MonitoringAlert.objects.filter(
        ticket_id=ticket_id,
        status__in=[AlertStatus.OPEN, AlertStatus.REVIEWED]
    )
    total_score = sum(alert.severity_weight for alert in alerts)
    risk_score = min(100, total_score)

    if risk_score >= 80:
        level = "بحرانی (Critical)"
    elif risk_score >= 60:
        level = "پرخطر (High Risk)"
    elif risk_score >= 40:
        level = "نیازمند بررسی (Needs Review)"
    elif risk_score >= 20:
        level = "کم‌خطر (Low Risk)"
    else:
        level = "عادی (Normal)"

    return risk_score, level
