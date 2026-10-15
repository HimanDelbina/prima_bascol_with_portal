from decimal import Decimal
from datetime import datetime, date, timedelta
import jdatetime
from django.db.models import Sum, Count, Avg, Min, Max, Q, F
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from weighbridge.models import WeighTicket, TicketStatus
from masterdata.models import Product, Party, Driver, Vehicle, Location, OperationType
from core.jalali import (
    get_today_gregorian, get_today_jalali, format_jalali_date,
    format_jalali_datetime, jalali_to_gregorian, gregorian_to_jalali,
    get_jalali_range_gregorian, get_comparison_period_gregorian,
    get_jalali_month_name, get_jalali_days_in_month
)


class OperationalKPIService:
    """
    Authoritative, concurrency-safe, single-source-of-truth KPI Calculation Service
    for Prima Bascol Industrial Weighbridge.

    Canonical Rules:
    1. Authoritative WeighTicket records only.
    2. Finalized Throughput & Completed Weights:
       - Strictly require status=TicketStatus.COMPLETED.
       - Cancelled, draft, and open in-yard tickets are strictly excluded from finalized tonnage.
       - Authoritative date is `completion_date`:
         Coalesce('second_weight_date', 'first_weight_date', TruncDate('created_at')).
    3. Gate Traffic & Vehicle Arrivals:
       - Authoritative date is `arrival_date`:
         Coalesce('first_weight_date', TruncDate('created_at')).
    4. Unit Standard:
       - Stored and aggregated in Kilograms (Decimal).
       - Metric tons = round(kg / 1000, 2).
       - All API endpoints explicitly identify "unit": "ton".
    5. Single-Pass Aggregation:
       - Eliminates N+1 query loops.
    """

    @staticmethod
    def get_canonical_date_annotations():
        """
        Returns Django ORM expressions for arrival and completion dates.
        """
        return {
            "arrival_date": Coalesce("first_weight_date", TruncDate("created_at")),
            "completion_date": Coalesce("second_weight_date", "first_weight_date", TruncDate("created_at")),
        }

    @staticmethod
    def get_annotated_queryset(qs=None):
        """
        Returns a WeighTicket queryset annotated with canonical dates.
        """
        if qs is None:
            qs = WeighTicket.objects.all()
        return qs.annotate(**OperationalKPIService.get_canonical_date_annotations())

    @staticmethod
    def kg_to_ton(kg_val, decimal_places=2) -> Decimal:
        """
        Safely convert a kilogram value to metric tons using exact Decimal arithmetic.
        """
        if kg_val is None:
            return Decimal("0.00")
        if not isinstance(kg_val, Decimal):
            kg_val = Decimal(str(kg_val))
        ton = kg_val / Decimal("1000")
        quantizer = Decimal("1." + "0" * decimal_places)
        return ton.quantize(quantizer)

    @classmethod
    def calculate_period_kpis(cls, start_date=None, end_date=None, base_qs=None, params=None):
        """
        Computes all authoritative operational KPIs for a specified period in a single SQL query.
        """
        params = params or {}
        if base_qs is None:
            base_qs = cls.get_annotated_queryset()
        else:
            base_qs = base_qs.annotate(**cls.get_canonical_date_annotations())

        # Apply dimensional filters if provided
        op_type_id = params.get("operation_type")
        if op_type_id:
            base_qs = base_qs.filter(operation_type_id=op_type_id)

        direction = params.get("direction")
        if direction in ["inbound", "outbound", "internal"]:
            base_qs = base_qs.filter(operation_type__direction=direction)

        product_id = params.get("product")
        if product_id:
            base_qs = base_qs.filter(product_id=product_id)

        party_id = params.get("party")
        if party_id:
            base_qs = base_qs.filter(party_id=party_id)

        driver_id = params.get("driver")
        if driver_id:
            base_qs = base_qs.filter(driver_id=driver_id)

        vehicle_id = params.get("vehicle")
        if vehicle_id:
            base_qs = base_qs.filter(vehicle_id=vehicle_id)

        origin_id = params.get("origin")
        if origin_id:
            base_qs = base_qs.filter(origin_id=origin_id)

        destination_id = params.get("destination")
        if destination_id:
            base_qs = base_qs.filter(destination_id=destination_id)

        if params.get("has_discrepancy") == "1":
            base_qs = base_qs.filter(is_tolerance_exceeded=True)

        if params.get("has_loss") == "1":
            base_qs = base_qs.filter(loss_weight__gt=0)

        # Build date filters
        if start_date and end_date:
            completion_date_q = Q(completion_date__range=[start_date, end_date])
            arrival_date_q = Q(arrival_date__range=[start_date, end_date])
            # Scope overall queryset to tickets that either arrived or completed in this period
            period_qs = base_qs.filter(arrival_date_q | (Q(status=TicketStatus.COMPLETED) & completion_date_q))
        elif start_date:
            completion_date_q = Q(completion_date__gte=start_date)
            arrival_date_q = Q(arrival_date__gte=start_date)
            period_qs = base_qs.filter(arrival_date_q | (Q(status=TicketStatus.COMPLETED) & completion_date_q))
        elif end_date:
            completion_date_q = Q(completion_date__lte=end_date)
            arrival_date_q = Q(arrival_date__lte=end_date)
            period_qs = base_qs.filter(arrival_date_q | (Q(status=TicketStatus.COMPLETED) & completion_date_q))
        else:
            completion_date_q = Q()
            arrival_date_q = Q()
            period_qs = base_qs

        # Strict completion condition: status must be COMPLETED and completed in the period
        comp_cond = Q(status=TicketStatus.COMPLETED) & completion_date_q
        arr_cond = arrival_date_q

        aggr = period_qs.aggregate(
            # Traffic and Operational counts
            trips=Count("id", filter=arr_cond),
            completed_trips=Count("id", filter=comp_cond),
            cancelled_count=Count("id", filter=arr_cond & Q(status=TicketStatus.CANCELLED)),
            waiting_count=Count("id", filter=Q(status__in=[TicketStatus.WAITING_SECOND, TicketStatus.FIRST_REGISTERED])),
            discrepancies_count=Count("id", filter=arr_cond & Q(is_tolerance_exceeded=True)),
            edited_count=Count("id", filter=arr_cond & Q(last_edited_by__isnull=False)),

            # Entity distinct counts in the period
            trucks_count=Count("license_plate_display", distinct=True, filter=arr_cond),
            drivers_count=Count("driver", distinct=True, filter=arr_cond),
            parties_count=Count("party", distinct=True, filter=arr_cond),
            products_count=Count("product", distinct=True, filter=arr_cond),

            # Finalized completed weights (strictly status=COMPLETED)
            net_kg=Sum("net_weight", filter=comp_cond),
            gross_kg=Sum("gross_weight", filter=comp_cond),
            tare_kg=Sum("tare_weight", filter=comp_cond),
            final_kg=Sum("final_weight", filter=comp_cond),
            loss_kg=Sum("loss_weight", filter=comp_cond),
            loads_count=Sum("load_count", filter=comp_cond),
            avg_loss_pct=Avg("loss_percent", filter=comp_cond),

            # Inbound / Outbound / Internal (strictly status=COMPLETED)
            inbound_net_kg=Sum("net_weight", filter=comp_cond & Q(operation_type__direction="inbound")),
            outbound_net_kg=Sum("net_weight", filter=comp_cond & Q(operation_type__direction="outbound")),
            internal_net_kg=Sum("net_weight", filter=comp_cond & Q(operation_type__direction="internal")),

            purchase_net_kg=Sum("net_weight", filter=comp_cond & (
                Q(operation_type__name__icontains="خرید") | Q(operation_type__direction="inbound")
            )),
            sales_net_kg=Sum("net_weight", filter=comp_cond & (
                Q(operation_type__name__icontains="فروش") | Q(operation_type__direction="outbound")
            )),
        )

        # Convert to Decimals
        net_kg_dec = aggr["net_kg"] or Decimal("0.00")
        gross_kg_dec = aggr["gross_kg"] or Decimal("0.00")
        tare_kg_dec = aggr["tare_kg"] or Decimal("0.00")
        final_kg_dec = aggr["final_kg"] or Decimal("0.00")
        loss_kg_dec = aggr["loss_kg"] or Decimal("0.00")
        inbound_kg_dec = aggr["inbound_net_kg"] or Decimal("0.00")
        outbound_kg_dec = aggr["outbound_net_kg"] or Decimal("0.00")
        internal_kg_dec = aggr["internal_net_kg"] or Decimal("0.00")
        purchase_kg_dec = aggr["purchase_net_kg"] or Decimal("0.00")
        sales_kg_dec = aggr["sales_net_kg"] or Decimal("0.00")
        avg_loss_pct_dec = aggr["avg_loss_pct"] or Decimal("0.00")

        # Ton calculations
        net_ton_dec = cls.kg_to_ton(net_kg_dec)
        gross_ton_dec = cls.kg_to_ton(gross_kg_dec)
        tare_ton_dec = cls.kg_to_ton(tare_kg_dec)
        final_ton_dec = cls.kg_to_ton(final_kg_dec)
        loss_ton_dec = cls.kg_to_ton(loss_kg_dec)
        inbound_ton_dec = cls.kg_to_ton(inbound_kg_dec)
        outbound_ton_dec = cls.kg_to_ton(outbound_kg_dec)
        internal_ton_dec = cls.kg_to_ton(internal_kg_dec)
        purchase_ton_dec = cls.kg_to_ton(purchase_kg_dec)
        sales_ton_dec = cls.kg_to_ton(sales_kg_dec)

        return {
            "unit": "ton",
            "weight_unit_authoritative": "kg",

            # Integer counts
            "trips": aggr["trips"] or 0,
            "completed_trips": aggr["completed_trips"] or 0,
            "cancelled_count": aggr["cancelled_count"] or 0,
            "waiting_count": aggr["waiting_count"] or 0,
            "discrepancies_count": aggr["discrepancies_count"] or 0,
            "edited_count": aggr["edited_count"] or 0,
            "loads_count": aggr["loads_count"] or 0,
            "trucks_count": aggr["trucks_count"] or 0,
            "drivers_count": aggr["drivers_count"] or 0,
            "parties_count": aggr["parties_count"] or 0,
            "products_count": aggr["products_count"] or 0,

            # Decimal values (exact)
            "net_kg_dec": net_kg_dec,
            "gross_kg_dec": gross_kg_dec,
            "tare_kg_dec": tare_kg_dec,
            "final_kg_dec": final_kg_dec,
            "loss_kg_dec": loss_kg_dec,
            "net_ton_dec": net_ton_dec,
            "gross_ton_dec": gross_ton_dec,
            "tare_ton_dec": tare_ton_dec,
            "final_ton_dec": final_ton_dec,
            "loss_ton_dec": loss_ton_dec,
            "inbound_net_kg_dec": inbound_kg_dec,
            "inbound_net_ton_dec": inbound_ton_dec,
            "outbound_net_kg_dec": outbound_kg_dec,
            "outbound_net_ton_dec": outbound_ton_dec,
            "purchase_net_ton_dec": purchase_ton_dec,
            "sales_net_ton_dec": sales_ton_dec,

            # Float values (for JSON / template compatibility)
            "net_kg": float(net_kg_dec),
            "net_ton": float(net_ton_dec),
            "gross_kg": float(gross_kg_dec),
            "gross_ton": float(gross_ton_dec),
            "tare_kg": float(tare_kg_dec),
            "tare_ton": float(tare_ton_dec),
            "final_kg": float(final_kg_dec),
            "final_ton": float(final_ton_dec),
            "loss_kg": float(loss_kg_dec),
            "loss_ton": float(loss_ton_dec),
            "inbound_net_kg": float(inbound_kg_dec),
            "inbound_net_ton": float(inbound_ton_dec),
            "outbound_net_kg": float(outbound_kg_dec),
            "outbound_net_ton": float(outbound_ton_dec),
            "purchase_net_ton": float(purchase_ton_dec),
            "sales_net_ton": float(sales_ton_dec),
            "avg_loss_pct": round(float(avg_loss_pct_dec), 2),
        }

    @classmethod
    def calculate_comparison(cls, curr_kpi, prev_kpi):
        """
        Compares current period KPIs against previous period KPIs with safe percentage calculations.
        """
        comparison = {}
        compare_keys = [
            "trips", "completed_trips", "net_kg", "net_ton", "final_kg", "final_ton",
            "gross_kg", "gross_ton", "tare_kg", "tare_ton", "inbound_net_kg", "inbound_net_ton",
            "outbound_net_kg", "outbound_net_ton", "purchase_net_ton", "sales_net_ton",
            "loss_kg", "loss_ton", "avg_loss_pct", "trucks_count", "drivers_count",
            "parties_count", "products_count", "discrepancies_count", "cancelled_count", "edited_count"
        ]

        for k in compare_keys:
            c_val = curr_kpi.get(k, 0)
            p_val = prev_kpi.get(k, 0)
            diff = round(c_val - p_val, 2)
            if p_val:
                pct = round(((c_val - p_val) / p_val * 100), 2)
            else:
                pct = 100.0 if c_val > 0 else 0.0

            comparison[k] = {
                "current": c_val,
                "previous": p_val,
                "diff": diff,
                "pct_change": pct,
                "is_positive": diff > 0,
                "is_neutral": diff == 0,
            }
        return comparison

    @classmethod
    def get_daily_operational_summary(cls, target_date=None):
        """
        Authoritative daily summary for operator and management dashboards.
        Synchronizes today's KPIs across all dashboards.
        """
        if target_date is None:
            target_date = get_today_gregorian()

        kpis = cls.calculate_period_kpis(start_date=target_date, end_date=target_date)

        # Active waiting trucks in yard (live snapshot)
        waiting_trucks_count = WeighTicket.objects.filter(
            status__in=[TicketStatus.WAITING_SECOND, TicketStatus.FIRST_REGISTERED]
        ).count()

        # Monitoring Alerts
        from monitoring.models import MonitoringAlert, AlertStatus, AlertSeverity
        open_alerts_count = MonitoringAlert.objects.filter(
            status__in=[AlertStatus.OPEN, AlertStatus.REVIEWED]
        ).count()
        today_critical_alerts = MonitoringAlert.objects.filter(
            created_at__date=target_date,
            severity__in=[AlertSeverity.CRITICAL, AlertSeverity.HIGH],
            status__in=[AlertStatus.OPEN, AlertStatus.REVIEWED]
        ).count()

        return {
            "target_date": target_date,
            "target_date_jalali": format_jalali_date(target_date),
            "today_count": kpis["trips"],
            "today_trips": kpis["trips"],
            "today_completed_count": kpis["completed_trips"],
            "today_net": kpis["net_kg_dec"],
            "today_net_kg": kpis["net_kg_dec"],
            "today_net_ton": kpis["net_ton_dec"],
            "today_tonnage": kpis["net_ton_dec"],
            "today_gross_kg": kpis["gross_kg_dec"],
            "today_gross_ton": kpis["gross_ton_dec"],
            "today_tare_kg": kpis["tare_kg_dec"],
            "today_tare_ton": kpis["tare_ton_dec"],
            "today_loads": kpis["loads_count"],
            "today_loss_kg": kpis["loss_kg_dec"],
            "today_loss_ton": kpis["loss_ton_dec"],
            "today_inbound": kpis["inbound_net_kg_dec"],
            "today_inbound_net": kpis["inbound_net_kg_dec"],
            "today_inbound_ton": kpis["inbound_net_ton_dec"],
            "today_outbound": kpis["outbound_net_kg_dec"],
            "today_outbound_net": kpis["outbound_net_kg_dec"],
            "today_outbound_ton": kpis["outbound_net_ton_dec"],
            "discrepancies_count": kpis["discrepancies_count"],
            "today_discrepancies_count": kpis["discrepancies_count"],
            "waiting_trucks_count": waiting_trucks_count,
            "open_alerts_count": open_alerts_count,
            "today_critical_alerts": today_critical_alerts,
        }

    @classmethod
    def get_tonnage_trend(cls, start_date, end_date, granularity="daily"):
        """
        Computes trend time series in 2 SQL queries instead of N loops.
        Authoritative completion dates for completed tonnage; arrival dates for trips.
        """
        labels = []
        inbound_series = []
        outbound_series = []
        net_series = []
        final_series = []
        trips_series = []

        annotated_qs = cls.get_annotated_queryset()

        total_days = (end_date - start_date).days + 1

        if granularity == "monthly" or total_days > 120:
            # Monthly aggregation
            buckets = []
            curr = start_date
            while curr <= end_date:
                j_dt = gregorian_to_jalali(curr)
                days_in_m = get_jalali_days_in_month(j_dt.year, j_dt.month)
                m_end_j = jdatetime.date(j_dt.year, j_dt.month, days_in_m)
                m_end_g = m_end_j.togregorian()
                actual_end = min(m_end_g, end_date)
                label = f"{get_jalali_month_name(j_dt.month)} {j_dt.year}"
                buckets.append((curr, actual_end, label))
                curr = actual_end + timedelta(days=1)

            # Query completed data
            comp_data = annotated_qs.filter(
                status=TicketStatus.COMPLETED,
                completion_date__range=[start_date, end_date]
            ).values("completion_date").annotate(
                net_kg=Sum("net_weight"),
                final_kg=Sum("final_weight"),
                inbound_kg=Sum("net_weight", filter=Q(operation_type__direction="inbound")),
                outbound_kg=Sum("net_weight", filter=Q(operation_type__direction="outbound")),
            )
            comp_map = {row["completion_date"]: row for row in comp_data}

            # Query trips data
            arr_data = annotated_qs.filter(
                arrival_date__range=[start_date, end_date]
            ).values("arrival_date").annotate(
                trips=Count("id")
            )
            arr_map = {row["arrival_date"]: row["trips"] for row in arr_data}

            for b_start, b_end, b_label in buckets:
                labels.append(b_label)
                b_net = Decimal("0.00")
                b_final = Decimal("0.00")
                b_inbound = Decimal("0.00")
                b_outbound = Decimal("0.00")
                b_trips = 0

                cur_day = b_start
                while cur_day <= b_end:
                    if cur_day in comp_map:
                        r = comp_map[cur_day]
                        b_net += r["net_kg"] or Decimal("0")
                        b_final += r["final_kg"] or Decimal("0")
                        b_inbound += r["inbound_kg"] or Decimal("0")
                        b_outbound += r["outbound_kg"] or Decimal("0")
                    if cur_day in arr_map:
                        b_trips += arr_map[cur_day]
                    cur_day += timedelta(days=1)

                net_series.append(float(cls.kg_to_ton(b_net)))
                final_series.append(float(cls.kg_to_ton(b_final)))
                inbound_series.append(float(cls.kg_to_ton(b_inbound)))
                outbound_series.append(float(cls.kg_to_ton(b_outbound)))
                trips_series.append(b_trips)

        elif granularity == "weekly" or total_days > 45:
            # Weekly aggregation
            buckets = []
            curr = start_date
            while curr <= end_date:
                w_end = min(curr + timedelta(days=6), end_date)
                label = f"{format_jalali_date(curr, fmt='%m/%d')} تا {format_jalali_date(w_end, fmt='%m/%d')}"
                buckets.append((curr, w_end, label))
                curr = w_end + timedelta(days=1)

            comp_data = annotated_qs.filter(
                status=TicketStatus.COMPLETED,
                completion_date__range=[start_date, end_date]
            ).values("completion_date").annotate(
                net_kg=Sum("net_weight"),
                final_kg=Sum("final_weight"),
                inbound_kg=Sum("net_weight", filter=Q(operation_type__direction="inbound")),
                outbound_kg=Sum("net_weight", filter=Q(operation_type__direction="outbound")),
            )
            comp_map = {row["completion_date"]: row for row in comp_data}

            arr_data = annotated_qs.filter(
                arrival_date__range=[start_date, end_date]
            ).values("arrival_date").annotate(
                trips=Count("id")
            )
            arr_map = {row["arrival_date"]: row["trips"] for row in arr_data}

            for b_start, b_end, b_label in buckets:
                labels.append(b_label)
                b_net = Decimal("0.00")
                b_final = Decimal("0.00")
                b_inbound = Decimal("0.00")
                b_outbound = Decimal("0.00")
                b_trips = 0

                cur_day = b_start
                while cur_day <= b_end:
                    if cur_day in comp_map:
                        r = comp_map[cur_day]
                        b_net += r["net_kg"] or Decimal("0")
                        b_final += r["final_kg"] or Decimal("0")
                        b_inbound += r["inbound_kg"] or Decimal("0")
                        b_outbound += r["outbound_kg"] or Decimal("0")
                    if cur_day in arr_map:
                        b_trips += arr_map[cur_day]
                    cur_day += timedelta(days=1)

                net_series.append(float(cls.kg_to_ton(b_net)))
                final_series.append(float(cls.kg_to_ton(b_final)))
                inbound_series.append(float(cls.kg_to_ton(b_inbound)))
                outbound_series.append(float(cls.kg_to_ton(b_outbound)))
                trips_series.append(b_trips)

        else:
            # Daily aggregation
            comp_data = annotated_qs.filter(
                status=TicketStatus.COMPLETED,
                completion_date__range=[start_date, end_date]
            ).values("completion_date").annotate(
                net_kg=Sum("net_weight"),
                final_kg=Sum("final_weight"),
                inbound_kg=Sum("net_weight", filter=Q(operation_type__direction="inbound")),
                outbound_kg=Sum("net_weight", filter=Q(operation_type__direction="outbound")),
            )
            comp_map = {row["completion_date"]: row for row in comp_data}

            arr_data = annotated_qs.filter(
                arrival_date__range=[start_date, end_date]
            ).values("arrival_date").annotate(
                trips=Count("id")
            )
            arr_map = {row["arrival_date"]: row["trips"] for row in arr_data}

            curr = start_date
            while curr <= end_date:
                labels.append(format_jalali_date(curr, fmt="%m/%d"))
                r = comp_map.get(curr, {})
                net_kg = r.get("net_kg") or Decimal("0.00")
                final_kg = r.get("final_kg") or Decimal("0.00")
                inbound_kg = r.get("inbound_kg") or Decimal("0.00")
                outbound_kg = r.get("outbound_kg") or Decimal("0.00")
                trips = arr_map.get(curr, 0)

                net_series.append(float(cls.kg_to_ton(net_kg)))
                final_series.append(float(cls.kg_to_ton(final_kg)))
                inbound_series.append(float(cls.kg_to_ton(inbound_kg)))
                outbound_series.append(float(cls.kg_to_ton(outbound_kg)))
                trips_series.append(trips)
                curr += timedelta(days=1)

        return {
            "unit": "ton",
            "labels": labels,
            "inbound": inbound_series,
            "outbound": outbound_series,
            "net": net_series,
            "final": final_series,
            "trips": trips_series,
        }

    @classmethod
    def get_product_share(cls, start_date=None, end_date=None, limit=6):
        """
        Top products by completed net weight. Standardized in metric tons.
        """
        annotated_qs = cls.get_annotated_queryset()
        qs = annotated_qs.filter(status=TicketStatus.COMPLETED, product__isnull=False)
        if start_date and end_date:
            qs = qs.filter(completion_date__range=[start_date, end_date])
        elif start_date:
            qs = qs.filter(completion_date__gte=start_date)
        elif end_date:
            qs = qs.filter(completion_date__lte=end_date)

        top_prods = qs.values("product__name").annotate(
            total_net_kg=Sum("net_weight")
        ).order_by("-total_net_kg")[:limit]

        labels = [p["product__name"] or "نامشخص" for p in top_prods]
        values_ton = [float(cls.kg_to_ton(p["total_net_kg"] or Decimal("0.00"))) for p in top_prods]

        return {
            "unit": "ton",
            "labels": labels,
            "values": values_ton,
        }

    @classmethod
    def get_party_share(cls, start_date=None, end_date=None, limit=6):
        """
        Top parties by completed net weight. Standardized in metric tons.
        """
        annotated_qs = cls.get_annotated_queryset()
        qs = annotated_qs.filter(status=TicketStatus.COMPLETED, party__isnull=False)
        if start_date and end_date:
            qs = qs.filter(completion_date__range=[start_date, end_date])
        elif start_date:
            qs = qs.filter(completion_date__gte=start_date)
        elif end_date:
            qs = qs.filter(completion_date__lte=end_date)

        top_parties = qs.values("party__name").annotate(
            total_net_kg=Sum("net_weight")
        ).order_by("-total_net_kg")[:limit]

        labels = [p["party__name"] or "نامشخص" for p in top_parties]
        values_ton = [float(cls.kg_to_ton(p["total_net_kg"] or Decimal("0.00"))) for p in top_parties]

        return {
            "unit": "ton",
            "labels": labels,
            "values": values_ton,
        }
