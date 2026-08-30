from decimal import Decimal
from django.db.models import (
    Q, Sum, Avg, Count, Min, Max, F, ExpressionWrapper, DecimalField
)
from core.jalali import jalali_to_gregorian, gregorian_to_jalali, format_jalali_date
from weighbridge.models import WeighTicket, TicketStatus

class ReportService:
    """
    High-performance server-side query and aggregation service for Weighbridge reports.
    """
    @staticmethod
    def filter_tickets(params: dict):
        """
        Filter tickets based on dictionary of filter criteria.
        """
        qs = WeighTicket.objects.select_related(
            "operation_type", "party", "product", "vehicle", "driver", 
            "origin", "destination", "unload_location", "loss_type",
            "first_weight_operator", "second_weight_operator", "cancelled_by"
        ).all()

        # Date range filtering (supports both Jalali string inputs and Gregorian dates)
        start_date_j = params.get("start_date")
        end_date_j = params.get("end_date")
        if start_date_j:
            g_start = jalali_to_gregorian(start_date_j)
            if g_start:
                qs = qs.filter(Q(first_weight_date__gte=g_start) | Q(created_at__date__gte=g_start))
        
        if end_date_j:
            g_end = jalali_to_gregorian(end_date_j)
            if g_end:
                qs = qs.filter(Q(first_weight_date__lte=g_end) | Q(created_at__date__lte=g_end))

        # Time range
        start_time = params.get("start_time")
        end_time = params.get("end_time")
        if start_time:
            qs = qs.filter(first_weight_time__gte=start_time)
        if end_time:
            qs = qs.filter(first_weight_time__lte=end_time)

        # Serial numbers
        serial_from = params.get("serial_from")
        serial_to = params.get("serial_to")
        if serial_from:
            qs = qs.filter(serial_number__gte=serial_from)
        if serial_to:
            qs = qs.filter(serial_number__lte=serial_to)

        # Status
        status = params.get("status")
        if status and status != "all":
            qs = qs.filter(status=status)
        elif not params.get("include_cancelled"):
            # By default include only active/completed unless cancelled explicitly requested or filtered
            if status != "cancelled":
                pass

        # Specific status quick filters
        record_type = params.get("record_type")
        if record_type == "completed":
            qs = qs.filter(status=TicketStatus.COMPLETED)
        elif record_type == "waiting":
            qs = qs.filter(status=TicketStatus.WAITING_SECOND)
        elif record_type == "cancelled":
            qs = qs.filter(status=TicketStatus.CANCELLED)

        # Operation type & direction
        operation_type_id = params.get("operation_type")
        if operation_type_id:
            qs = qs.filter(operation_type_id=operation_type_id)
        
        operation_direction = params.get("operation_direction")
        if operation_direction:
            qs = qs.filter(operation_type__direction=operation_direction)

        # Products (single or multiple)
        product_ids = params.getlist("product") if hasattr(params, "getlist") else params.get("product")
        if product_ids:
            if isinstance(product_ids, list):
                product_ids = [p for p in product_ids if p]
                if product_ids:
                    qs = qs.filter(product_id__in=product_ids)
            else:
                qs = qs.filter(product_id=product_ids)

        # Parties (single or multiple)
        party_ids = params.getlist("party") if hasattr(params, "getlist") else params.get("party")
        if party_ids:
            if isinstance(party_ids, list):
                party_ids = [p for p in party_ids if p]
                if party_ids:
                    qs = qs.filter(party_id__in=party_ids)
            else:
                qs = qs.filter(party_id=party_ids)

        # Driver
        driver_id = params.get("driver")
        if driver_id:
            qs = qs.filter(driver_id=driver_id)
        
        driver_search = params.get("driver_search")
        if driver_search:
            qs = qs.filter(
                Q(driver__full_name__icontains=driver_search) | 
                Q(driver_name_custom__icontains=driver_search)
            )

        # Vehicle / Plate
        vehicle_id = params.get("vehicle")
        if vehicle_id:
            qs = qs.filter(vehicle_id=vehicle_id)
        
        plate = params.get("plate")
        if plate:
            qs = qs.filter(license_plate_display__icontains=plate)

        # Waybill
        waybill = params.get("waybill_number")
        if waybill:
            qs = qs.filter(waybill_number__icontains=waybill)

        # Locations
        origin_id = params.get("origin")
        if origin_id:
            qs = qs.filter(origin_id=origin_id)

        destination_id = params.get("destination")
        if destination_id:
            qs = qs.filter(destination_id=destination_id)

        unload_loc_id = params.get("unload_location")
        if unload_loc_id:
            qs = qs.filter(unload_location_id=unload_loc_id)

        # Operators
        operator_id = params.get("operator")
        if operator_id:
            qs = qs.filter(Q(first_weight_operator_id=operator_id) | Q(second_weight_operator_id=operator_id))

        first_operator_id = params.get("first_weight_operator")
        if first_operator_id:
            qs = qs.filter(first_weight_operator_id=first_operator_id)

        second_operator_id = params.get("second_weight_operator")
        if second_operator_id:
            qs = qs.filter(second_weight_operator_id=second_operator_id)

        # Loss criteria
        loss_type_id = params.get("loss_type")
        if loss_type_id:
            qs = qs.filter(loss_type_id=loss_type_id)

        has_loss = params.get("has_loss")
        if has_loss == "yes":
            qs = qs.filter(loss_weight__gt=0)
        elif has_loss == "no":
            qs = qs.filter(loss_weight=0)

        min_loss_pct = params.get("min_loss_pct")
        if min_loss_pct:
            qs = qs.filter(loss_percent__gte=Decimal(min_loss_pct))

        max_loss_pct = params.get("max_loss_pct")
        if max_loss_pct:
            qs = qs.filter(loss_percent__lte=Decimal(max_loss_pct))

        # Weight ranges
        min_gross = params.get("min_gross")
        if min_gross:
            qs = qs.filter(gross_weight__gte=Decimal(min_gross))
        max_gross = params.get("max_gross")
        if max_gross:
            qs = qs.filter(gross_weight__lte=Decimal(max_gross))

        min_tare = params.get("min_tare")
        if min_tare:
            qs = qs.filter(tare_weight__gte=Decimal(min_tare))
        max_tare = params.get("max_tare")
        if max_tare:
            qs = qs.filter(tare_weight__lte=Decimal(max_tare))

        min_net = params.get("min_net")
        if min_net:
            qs = qs.filter(net_weight__gte=Decimal(min_net))
        max_net = params.get("max_net")
        if max_net:
            qs = qs.filter(net_weight__lte=Decimal(max_net))

        min_final = params.get("min_final")
        if min_final:
            qs = qs.filter(final_weight__gte=Decimal(min_final))
        max_final = params.get("max_final")
        if max_final:
            qs = qs.filter(final_weight__lte=Decimal(max_final))

        # Tolerance & Variance
        tolerance_exceeded = params.get("tolerance_exceeded")
        if tolerance_exceeded == "yes":
            qs = qs.filter(is_tolerance_exceeded=True)
        elif tolerance_exceeded == "no":
            qs = qs.filter(is_tolerance_exceeded=False)

        min_diff = params.get("min_diff")
        if min_diff:
            qs = qs.filter(weight_difference__gte=Decimal(min_diff))
        max_diff = params.get("max_diff")
        if max_diff:
            qs = qs.filter(weight_difference__lte=Decimal(max_diff))

        # Manual Overrides
        is_overridden = params.get("is_overridden")
        if is_overridden == "yes":
            qs = qs.filter(is_loss_overridden=True)

        return qs

    @staticmethod
    def get_summary_metrics(qs):
        """
        Calculate summary aggregations on the filtered QuerySet.
        """
        metrics = qs.aggregate(
            total_tickets=Count("id"),
            total_loads=Sum("load_count"),
            sum_gross=Sum("gross_weight"),
            sum_tare=Sum("tare_weight"),
            sum_net=Sum("net_weight"),
            sum_sent=Sum("sent_weight"),
            sum_loss=Sum("loss_weight"),
            sum_final=Sum("final_weight"),
            avg_net=Avg("net_weight"),
            avg_loss_percent=Avg("loss_percent"),
            min_net=Min("net_weight"),
            max_net=Max("net_weight"),
        )
        return {
            "total_tickets": metrics["total_tickets"] or 0,
            "total_loads": metrics["total_loads"] or 0,
            "sum_gross": metrics["sum_gross"] or Decimal("0.00"),
            "sum_tare": metrics["sum_tare"] or Decimal("0.00"),
            "sum_net": metrics["sum_net"] or Decimal("0.00"),
            "sum_sent": metrics["sum_sent"] or Decimal("0.00"),
            "sum_loss": metrics["sum_loss"] or Decimal("0.00"),
            "sum_final": metrics["sum_final"] or Decimal("0.00"),
            "avg_net": round(metrics["avg_net"] or Decimal("0.00"), 2),
            "avg_loss_percent": round(metrics["avg_loss_percent"] or Decimal("0.00"), 2),
            "min_net": metrics["min_net"] or Decimal("0.00"),
            "max_net": metrics["max_net"] or Decimal("0.00"),
        }

    @staticmethod
    def group_by_field(qs, group_field: str):
        """
        Group QuerySet by a specified field and aggregate metrics.
        Supported group_fields:
        'day', 'product', 'party', 'driver', 'plate', 'origin', 'destination', 'unload_location', 'operation_type', 'operator', 'status'
        """
        results = []
        if not group_field or group_field == "none":
            return results

        if group_field == "day":
            grouped = qs.values("first_weight_date").annotate(
                count=Count("id"),
                total_loads=Sum("load_count"),
                sum_gross=Sum("gross_weight"),
                sum_tare=Sum("tare_weight"),
                sum_net=Sum("net_weight"),
                sum_loss=Sum("loss_weight"),
                sum_final=Sum("final_weight"),
                avg_net=Avg("net_weight"),
                min_net=Min("net_weight"),
                max_net=Max("net_weight"),
            ).order_by("-first_weight_date")
            for item in grouped:
                d = item["first_weight_date"]
                j_date = format_jalali_date(d) if d else "نامشخص"
                results.append({
                    "group_title": j_date,
                    "item": item
                })

        elif group_field == "product":
            grouped = qs.values("product__id", "product__name").annotate(
                count=Count("id"),
                total_loads=Sum("load_count"),
                sum_gross=Sum("gross_weight"),
                sum_tare=Sum("tare_weight"),
                sum_net=Sum("net_weight"),
                sum_loss=Sum("loss_weight"),
                sum_final=Sum("final_weight"),
                avg_net=Avg("net_weight"),
                min_net=Min("net_weight"),
                max_net=Max("net_weight"),
            ).order_by("-sum_net")
            for item in grouped:
                results.append({
                    "group_title": item["product__name"] or "بدون محصول",
                    "item": item
                })

        elif group_field == "party":
            grouped = qs.values("party__id", "party__name").annotate(
                count=Count("id"),
                total_loads=Sum("load_count"),
                sum_gross=Sum("gross_weight"),
                sum_tare=Sum("tare_weight"),
                sum_net=Sum("net_weight"),
                sum_loss=Sum("loss_weight"),
                sum_final=Sum("final_weight"),
                avg_net=Avg("net_weight"),
                min_net=Min("net_weight"),
                max_net=Max("net_weight"),
            ).order_by("-sum_net")
            for item in grouped:
                results.append({
                    "group_title": item["party__name"] or "بدون طرف حساب",
                    "item": item
                })

        elif group_field == "driver":
            grouped = qs.values("driver__id", "driver__full_name", "driver_name_custom").annotate(
                count=Count("id"),
                total_loads=Sum("load_count"),
                sum_gross=Sum("gross_weight"),
                sum_tare=Sum("tare_weight"),
                sum_net=Sum("net_weight"),
                sum_loss=Sum("loss_weight"),
                sum_final=Sum("final_weight"),
                avg_net=Avg("net_weight"),
                min_net=Min("net_weight"),
                max_net=Max("net_weight"),
            ).order_by("-count")
            for item in grouped:
                title = item["driver__full_name"] or item["driver_name_custom"] or "راننده نامشخص"
                results.append({
                    "group_title": title,
                    "item": item
                })

        elif group_field == "plate":
            grouped = qs.values("license_plate_display").annotate(
                count=Count("id"),
                total_loads=Sum("load_count"),
                sum_gross=Sum("gross_weight"),
                sum_tare=Sum("tare_weight"),
                sum_net=Sum("net_weight"),
                sum_loss=Sum("loss_weight"),
                sum_final=Sum("final_weight"),
                avg_net=Avg("net_weight"),
                min_net=Min("net_weight"),
                max_net=Max("net_weight"),
            ).order_by("-count")
            for item in grouped:
                results.append({
                    "group_title": item["license_plate_display"] or "بدون پلاک",
                    "item": item
                })

        elif group_field == "origin":
            grouped = qs.values("origin__id", "origin__name").annotate(
                count=Count("id"),
                total_loads=Sum("load_count"),
                sum_net=Sum("net_weight"),
                sum_loss=Sum("loss_weight"),
                sum_final=Sum("final_weight"),
                avg_net=Avg("net_weight"),
                min_net=Min("net_weight"),
                max_net=Max("net_weight"),
            ).order_by("-count")
            for item in grouped:
                results.append({
                    "group_title": item["origin__name"] or "نامشخص",
                    "item": item
                })

        elif group_field == "destination":
            grouped = qs.values("destination__id", "destination__name").annotate(
                count=Count("id"),
                total_loads=Sum("load_count"),
                sum_net=Sum("net_weight"),
                sum_loss=Sum("loss_weight"),
                sum_final=Sum("final_weight"),
                avg_net=Avg("net_weight"),
                min_net=Min("net_weight"),
                max_net=Max("net_weight"),
            ).order_by("-count")
            for item in grouped:
                results.append({
                    "group_title": item["destination__name"] or "نامشخص",
                    "item": item
                })

        elif group_field == "operation_type":
            grouped = qs.values("operation_type__id", "operation_type__name").annotate(
                count=Count("id"),
                total_loads=Sum("load_count"),
                sum_net=Sum("net_weight"),
                sum_loss=Sum("loss_weight"),
                sum_final=Sum("final_weight"),
                avg_net=Avg("net_weight"),
                min_net=Min("net_weight"),
                max_net=Max("net_weight"),
            ).order_by("-count")
            for item in grouped:
                results.append({
                    "group_title": item["operation_type__name"] or "بدون نوع عملیات",
                    "item": item
                })

        elif group_field == "operator":
            grouped = qs.values("first_weight_operator__id", "first_weight_operator__first_name", "first_weight_operator__last_name", "first_weight_operator__username").annotate(
                count=Count("id"),
                total_loads=Sum("load_count"),
                sum_net=Sum("net_weight"),
                sum_loss=Sum("loss_weight"),
                sum_final=Sum("final_weight"),
                avg_net=Avg("net_weight"),
                min_net=Min("net_weight"),
                max_net=Max("net_weight"),
            ).order_by("-count")
            for item in grouped:
                fn = item["first_weight_operator__first_name"] or ""
                ln = item["first_weight_operator__last_name"] or ""
                op_name = f"{fn} {ln}".strip() or item["first_weight_operator__username"] or "اپراتور نامشخص"
                results.append({
                    "group_title": op_name,
                    "item": item
                })

        return results
