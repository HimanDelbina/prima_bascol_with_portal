import json
import statistics
from decimal import Decimal
from datetime import datetime, date, time, timedelta
import jdatetime
from django.db.models import Sum, Count, Avg, Min, Max, Q, F
from django.utils import timezone

from weighbridge.models import WeighTicket, TicketStatus
from masterdata.models import Product, Party, Driver, Vehicle, Location, OperationType, LossType
from core.jalali import (
    get_today_gregorian, get_today_jalali, format_jalali_date, 
    format_jalali_datetime, jalali_to_gregorian, gregorian_to_jalali,
    get_jalali_range_gregorian, get_comparison_period_gregorian,
    get_jalali_month_name, get_jalali_days_in_month
)
from core.models import SystemSetting
from management.kpi_service import OperationalKPIService

class ManagementDashboardService:
    @staticmethod
    def get_filtered_queryset(params):
        quick_period = params.get('quick_period', '').strip()
        start_jalali = params.get('start_date_jalali', '').strip()
        end_jalali = params.get('end_date_jalali', '').strip()
        
        if quick_period and quick_period != 'custom':
            start_date, end_date = get_jalali_range_gregorian(quick_period)
            prev_start, prev_end = get_comparison_period_gregorian(start_date, end_date, quick_period)
            period_label = quick_period
        elif start_jalali and end_jalali:
            start_date = jalali_to_gregorian(start_jalali) or get_today_gregorian()
            end_date = jalali_to_gregorian(end_jalali) or get_today_gregorian()
            prev_start, prev_end = get_comparison_period_gregorian(start_date, end_date, 'custom')
            period_label = 'custom'
        else:
            quick_period = 'this_month'
            start_date, end_date = get_jalali_range_gregorian(quick_period)
            prev_start, prev_end = get_comparison_period_gregorian(start_date, end_date, quick_period)
            period_label = quick_period

        qs = OperationalKPIService.get_annotated_queryset().filter(
            Q(arrival_date__range=[start_date, end_date]) |
            (Q(status=TicketStatus.COMPLETED) & Q(completion_date__range=[start_date, end_date]))
        )

        op_type_id = params.get('operation_type')
        if op_type_id:
            qs = qs.filter(operation_type_id=op_type_id)

        direction = params.get('direction')
        if direction in ['inbound', 'outbound', 'internal']:
            qs = qs.filter(operation_type__direction=direction)

        product_id = params.get('product')
        if product_id:
            qs = qs.filter(product_id=product_id)

        party_id = params.get('party')
        if party_id:
            qs = qs.filter(party_id=party_id)

        driver_id = params.get('driver')
        if driver_id:
            qs = qs.filter(driver_id=driver_id)

        vehicle_id = params.get('vehicle')
        if vehicle_id:
            qs = qs.filter(vehicle_id=vehicle_id)

        origin_id = params.get('origin')
        if origin_id:
            qs = qs.filter(origin_id=origin_id)

        destination_id = params.get('destination')
        if destination_id:
            qs = qs.filter(destination_id=destination_id)

        if params.get('has_discrepancy') == '1':
            qs = qs.filter(is_tolerance_exceeded=True)

        if params.get('has_loss') == '1':
            qs = qs.filter(loss_weight__gt=0)

        # Previous period query
        prev_qs = OperationalKPIService.get_annotated_queryset().filter(
            Q(arrival_date__range=[prev_start, prev_end]) |
            (Q(status=TicketStatus.COMPLETED) & Q(completion_date__range=[prev_start, prev_end]))
        )
        if op_type_id:
            prev_qs = prev_qs.filter(operation_type_id=op_type_id)
        if direction in ['inbound', 'outbound', 'internal']:
            prev_qs = prev_qs.filter(operation_type__direction=direction)
        if product_id:
            prev_qs = prev_qs.filter(product_id=product_id)
        if party_id:
            prev_qs = prev_qs.filter(party_id=party_id)

        # Attach date ranges to queryset objects for downstream service access
        qs.start_date = start_date
        qs.end_date = end_date
        prev_qs.start_date = prev_start
        prev_qs.end_date = prev_end

        return qs, prev_qs, start_date, end_date, prev_start, prev_end, period_label

    @staticmethod
    def calculate_kpis_with_comparison(curr_qs, prev_qs):
        curr_start = getattr(curr_qs, 'start_date', None)
        curr_end = getattr(curr_qs, 'end_date', None)
        prev_start = getattr(prev_qs, 'start_date', None)
        prev_end = getattr(prev_qs, 'end_date', None)

        curr = OperationalKPIService.calculate_period_kpis(
            start_date=curr_start, end_date=curr_end, base_qs=curr_qs
        )
        prev = OperationalKPIService.calculate_period_kpis(
            start_date=prev_start, end_date=prev_end, base_qs=prev_qs
        )
        comparison = OperationalKPIService.calculate_comparison(curr, prev)

        return curr, prev, comparison

    @staticmethod
    def generate_executive_narrative(curr_kpi, comparison, top_product_name, top_party_name):
        trips = curr_kpi['trips']
        tonnage = curr_kpi['net_ton']
        pct_change = comparison['net_ton']['pct_change']
        discrepancies = curr_kpi['discrepancies_count']
        loss_ton = curr_kpi['loss_ton']

        change_text = 'افزایش' if pct_change > 0 else ('کاهش' if pct_change < 0 else 'بدون تغییر')
        pct_abs = abs(pct_change)

        text = (
            f'در بازه زمانی انتخابی، مجموعاً {trips:,} سرویس توزین با تناژ خالص کل {tonnage:,.2f} تن به ثبت رسیده است. '
            f'حجم عملیات نسبت به دوره مشابه قبل {pct_abs:.1f} درصد {change_text} داشته است. '
        )
        if top_product_name:
            text += f'محصول «{top_product_name}» رتبه نخست تناژ حمل‌شده را به خود اختصاص داده '
        if top_party_name:
            text += f'و بیشترین تبادلات وزنی با طرف حساب «{top_party_name}» صورت گرفته است. '
        if loss_ton > 0:
            text += f'مجموع افت اعمال‌شده در این دوره {loss_ton:,.2f} تن ثبت گردیده است. '
        if discrepancies > 0:
            text += f'همچنین تعداد {discrepancies} مورد مغایرت وزنی فراتر از حد مجاز استاندارد شناسایی شده که نیازمند نظارت مدیریتی است.'
        else:
            text += 'هیچ مغایرت وزنی بحرانی در این دوره ثبت نشده و عملیات در شرایط پایدار قرار دارد.'

        return text

    @staticmethod
    def get_pending_approvals_summary(user):
        """
        Phase 3.2.2: Pending supervisor approvals summary.
        Respects supervisor approval permissions and avoids leaking details to unauthorized users.
        """
        is_authorized = False
        if user and user.is_authenticated:
            if user.is_superuser:
                is_authorized = True
            else:
                profile = getattr(user, "profile", None)
                if profile and profile.is_active and profile.role in [
                    "super_admin", "system_admin", "ceo", "factory_manager",
                    "commercial_manager", "financial_manager", "weighbridge_manager"
                ]:
                    is_authorized = True

        if not is_authorized:
            return {
                "is_authorized": False,
                "pending_count": 0,
                "oldest_age_str": None,
                "oldest_age_minutes": 0,
                "severity_breakdown": [],
                "approval_url": None,
            }

        from monitoring.models import DiscrepancyApproval, ApprovalStatus, AlertSeverity
        from django.urls import reverse

        pending_qs = DiscrepancyApproval.objects.filter(status=ApprovalStatus.PENDING)
        sev_aggr = list(pending_qs.values("severity").annotate(cnt=Count("id")).order_by("-cnt"))
        pending_count = sum(s["cnt"] for s in sev_aggr)

        oldest = pending_qs.order_by("created_at").first() if pending_count > 0 else None
        oldest_age_str = None
        oldest_age_minutes = 0
        if oldest and oldest.created_at:
            diff_sec = max(0.0, (timezone.now() - oldest.created_at).total_seconds())
            oldest_age_minutes = int(diff_sec / 60)
            hours = oldest_age_minutes // 60
            mins = oldest_age_minutes % 60
            days = hours // 24
            rem_hours = hours % 24
            if days > 0:
                oldest_age_str = f"{days} روز و {rem_hours} ساعت"
            elif hours > 0:
                oldest_age_str = f"{hours} ساعت و {mins} دقیقه"
            else:
                oldest_age_str = f"{max(1, mins)} دقیقه"

        sev_labels = dict(AlertSeverity.choices)
        sev_classes = {
            AlertSeverity.CRITICAL: "danger",
            AlertSeverity.HIGH: "warning text-dark",
            AlertSeverity.MEDIUM: "info text-dark",
            AlertSeverity.LOW: "secondary",
            AlertSeverity.INFO: "light text-dark border",
        }
        severity_breakdown = []
        for s in sev_aggr:
            code = s["severity"]
            severity_breakdown.append({
                "severity": code,
                "label": sev_labels.get(code, code),
                "count": s["cnt"],
                "badge_class": sev_classes.get(code, "secondary"),
            })

        return {
            "is_authorized": True,
            "pending_count": pending_count,
            "oldest_age_str": oldest_age_str,
            "oldest_age_minutes": oldest_age_minutes,
            "severity_breakdown": severity_breakdown,
            "approval_url": reverse("monitoring:approval_list"),
        }

    @staticmethod
    def get_yard_operational_summary():
        """
        Phase 3.2.2: Live yard operational queue and dwell summary.
        Uses exact same rules and thresholds as trucks_in_yard and MonitoringRuleConfig.
        """
        from django.urls import reverse
        try:
            from monitoring.models import MonitoringRuleConfig, AlertType
            rule_config = MonitoringRuleConfig.get_rule_config(AlertType.LONG_WAITING_TIME)
            warning_threshold = float(rule_config.warning_threshold)
            critical_threshold = float(rule_config.critical_threshold)
        except Exception:
            warning_threshold = 60.0
            critical_threshold = 180.0

        now = timezone.now()
        cutoff_warning = now - timedelta(minutes=warning_threshold)
        cutoff_critical = now - timedelta(minutes=critical_threshold)

        base_yard_qs = WeighTicket.objects.filter(
            status__in=[TicketStatus.WAITING_SECOND, TicketStatus.FIRST_REGISTERED]
        )

        yard_stats = base_yard_qs.aggregate(
            total=Count("id"),
            overdue=Count("id", filter=Q(created_at__lte=cutoff_critical)),
            warning=Count("id", filter=Q(created_at__gt=cutoff_critical, created_at__lte=cutoff_warning)),
            normal=Count("id", filter=Q(created_at__gt=cutoff_warning)),
            oldest_created=Min("created_at"),
        )

        total_count = yard_stats["total"] or 0
        oldest_created = yard_stats["oldest_created"]
        longest_dwell_str = "—"
        longest_dwell_minutes = 0
        if oldest_created:
            diff_sec = max(0.0, (now - oldest_created).total_seconds())
            longest_dwell_minutes = int(diff_sec / 60)
            hours = longest_dwell_minutes // 60
            mins = longest_dwell_minutes % 60
            if hours > 0 and mins > 0:
                longest_dwell_str = f"{hours} ساعت و {mins} دقیقه"
            elif hours > 0:
                longest_dwell_str = f"{hours} ساعت"
            elif mins > 0:
                longest_dwell_str = f"{mins} دقیقه"
            else:
                longest_dwell_str = "کمتر از ۱ دقیقه"

        return {
            "total_in_yard": total_count,
            "normal_count": yard_stats["normal"] or 0,
            "warning_count": yard_stats["warning"] or 0,
            "overdue_count": yard_stats["overdue"] or 0,
            "longest_dwell_str": longest_dwell_str,
            "longest_dwell_minutes": longest_dwell_minutes,
            "warning_threshold_mins": int(warning_threshold),
            "critical_threshold_mins": int(critical_threshold),
            "yard_url": reverse("weighbridge:trucks_in_yard"),
        }

    @staticmethod
    def get_turnaround_dwell_analytics(curr_qs):
        """
        Phase 3.2.2: Turnaround and dwell analytics for completed tickets.
        Computes average, median, completed trips count, excluded incomplete records count,
        and hourly throughput trend. Keeps metrics strictly separate from finalized net tonnage.
        """
        completed_qs = curr_qs.filter(status=TicketStatus.COMPLETED)
        completed_count = completed_qs.count()

        valid_qs = completed_qs.filter(
            first_weight_date__isnull=False,
            first_weight_time__isnull=False,
            second_weight_date__isnull=False,
            second_weight_time__isnull=False
        )

        timestamp_rows = list(valid_qs.values_list(
            "first_weight_date", "first_weight_time", "second_weight_date", "second_weight_time"
        ))

        excluded_count = max(0, completed_count - len(timestamp_rows))

        durations_minutes = []
        hourly_throughput = [0] * 24

        for d1, t1, d2, t2 in timestamp_rows:
            dt1 = datetime.combine(d1, t1)
            dt2 = datetime.combine(d2, t2)
            diff_sec = (dt2 - dt1).total_seconds()
            if diff_sec >= 0:
                mins = round(diff_sec / 60.0, 1)
                durations_minutes.append(mins)
            if 0 <= t2.hour < 24:
                hourly_throughput[t2.hour] += 1

        avg_turnaround = round(statistics.mean(durations_minutes), 1) if durations_minutes else 0.0
        median_turnaround = round(statistics.median(durations_minutes), 1) if durations_minutes else 0.0
        min_turnaround = min(durations_minutes) if durations_minutes else 0.0
        max_turnaround = max(durations_minutes) if durations_minutes else 0.0

        def _format_mins(m):
            if not m or m <= 0:
                return "—"
            hrs = int(m // 60)
            mins = int(m % 60)
            if hrs > 0 and mins > 0:
                return f"{hrs} ساعت و {mins} دقیقه"
            elif hrs > 0:
                return f"{hrs} ساعت"
            return f"{mins} دقیقه"

        return {
            "completed_trips_count": completed_count,
            "valid_trips_count": len(durations_minutes),
            "excluded_missing_timestamps_count": excluded_count,
            "avg_turnaround_minutes": avg_turnaround,
            "avg_turnaround_str": _format_mins(avg_turnaround),
            "median_turnaround_minutes": median_turnaround,
            "median_turnaround_str": _format_mins(median_turnaround),
            "min_turnaround_minutes": min_turnaround,
            "max_turnaround_minutes": max_turnaround,
            "hourly_throughput": hourly_throughput,
        }

    @staticmethod
    def detect_management_alerts(curr_qs, yard_overdue_count=None):
        alerts = []
        aggr = curr_qs.aggregate(
            crit_discrepancies=Count('id', filter=Q(weight_difference__gte=100) | Q(weight_difference__lte=-100) | Q(is_tolerance_exceeded=True)),
            high_loss=Count('id', filter=Q(loss_percent__gte=3.0)),
        )
        crit_count = aggr['crit_discrepancies'] or 0
        if crit_count > 0:
            alerts.append({
                'level': 'danger',
                'icon': 'bi-exclamation-octagon-fill',
                'title': f'{crit_count} مورد مغایرت وزن بحرانی',
                'message': f'تعداد {crit_count} قبض دارای اختلاف وزنی شدید با بارنامه (بیش از حد مجاز / ۱۰۰ کیلوگرم) ثبت شده است.',
                'link_param': 'has_discrepancy=1'
            })

        high_loss_count = aggr['high_loss'] or 0
        if high_loss_count > 0:
            alerts.append({
                'level': 'warning',
                'icon': 'bi-percent',
                'title': f'{high_loss_count} مورد کسر افت بالای ۳ درصد',
                'message': 'ثبت موارد افت بیش از ۳٪ نشان‌دهنده ناخالصی یا رطوبت بالای محموله‌های ورودی/خروجی است.',
                'link_param': 'has_loss=1'
            })

        if yard_overdue_count is None:
            stalled_trucks = WeighTicket.objects.filter(
                status__in=[TicketStatus.WAITING_SECOND, TicketStatus.FIRST_REGISTERED],
                created_at__lte=timezone.now() - timedelta(hours=3)
            ).count()
        else:
            stalled_trucks = yard_overdue_count

        if stalled_trucks > 0:
            alerts.append({
                'level': 'info',
                'icon': 'bi-hourglass-bottom',
                'title': f'{stalled_trucks} خودرو با زمان توقف بیش از حد مجاز',
                'message': 'کامیون‌هایی بیش از حد استاندارد داخل محوطه منتظر ثبت وزن دوم یا تخلیه/بارگیری هستند.',
                'link_param': 'status=waiting_second'
            })

        return alerts

    @staticmethod
    def get_tonnage_trend(start_date, end_date, granularity='daily'):
        return OperationalKPIService.get_tonnage_trend(start_date, end_date, granularity=granularity)

    @staticmethod
    def get_top10_metrics(curr_qs):
        completed = curr_qs.filter(status=TicketStatus.COMPLETED)
        total_net = completed.aggregate(s=Sum('net_weight'))['s'] or Decimal('1')

        # 1. Top 10 Products
        top_prods = completed.filter(product__isnull=False).values('product__name', 'product__id').annotate(
            total_net=Sum('net_weight'),
            trips=Count('id'),
            total_loss=Sum('loss_weight')
        ).order_by('-total_net')[:10]

        top_products_list = []
        for p in top_prods:
            net_ton = round(float(p['total_net'] or 0) / 1000.0, 2)
            share_pct = round((float(p['total_net'] or 0) / float(total_net)) * 100, 1)
            top_products_list.append({
                'id': p['product__id'],
                'name': p['product__name'] or 'نامشخص',
                'net_ton': net_ton,
                'trips': p['trips'],
                'share_pct': share_pct,
                'loss_ton': round(float(p['total_loss'] or 0) / 1000.0, 2),
            })

        # 2. Top 10 Parties
        top_parties = completed.filter(party__isnull=False).values('party__name', 'party__id').annotate(
            total_net=Sum('net_weight'),
            trips=Count('id'),
            total_loss=Sum('loss_weight'),
            discrepancies=Count('id', filter=Q(is_tolerance_exceeded=True))
        ).order_by('-total_net')[:10]

        top_parties_list = [{
            'id': pt['party__id'],
            'name': pt['party__name'] or 'نامشخص',
            'net_ton': round(float(pt['total_net'] or 0) / 1000.0, 2),
            'trips': pt['trips'],
            'loss_ton': round(float(pt['total_loss'] or 0) / 1000.0, 2),
            'discrepancies': pt['discrepancies'],
        } for pt in top_parties]

        # 3. Top 10 Drivers
        top_drivers = curr_qs.values('driver__full_name', 'driver_name_custom', 'driver__id').annotate(
            trips=Count('id'),
            total_net=Sum('net_weight', filter=Q(status=TicketStatus.COMPLETED))
        ).order_by('-trips')[:10]
        top_drivers_list = [{
            'id': d['driver__id'],
            'name': d['driver__full_name'] or d['driver_name_custom'] or 'نامشخص',
            'trips': d['trips'],
            'net_ton': round(float(d['total_net'] or 0) / 1000.0, 2),
        } for d in top_drivers]

        # 4. Top 10 Vehicles
        top_vehicles = curr_qs.values('license_plate_display').annotate(
            trips=Count('id'),
            total_net=Sum('net_weight', filter=Q(status=TicketStatus.COMPLETED))
        ).order_by('-trips')[:10]
        top_vehicles_list = [{
            'plate': v['license_plate_display'] or 'نامشخص',
            'trips': v['trips'],
            'net_ton': round(float(v['total_net'] or 0) / 1000.0, 2),
        } for v in top_vehicles]

        # 5. Top 10 Origins & Destinations
        top_origins = curr_qs.filter(origin__isnull=False).values('origin__name').annotate(
            trips=Count('id'),
            total_net=Sum('net_weight', filter=Q(status=TicketStatus.COMPLETED))
        ).order_by('-trips')[:10]

        top_destinations = curr_qs.filter(destination__isnull=False).values('destination__name').annotate(
            trips=Count('id'),
            total_net=Sum('net_weight', filter=Q(status=TicketStatus.COMPLETED))
        ).order_by('-trips')[:10]

        # 6. Top 10 Weight Discrepancies
        top_discrepancies = curr_qs.filter(
            Q(is_tolerance_exceeded=True) | Q(weight_difference__gt=0) | Q(weight_difference__lt=0)
        ).select_related('party', 'product', 'driver').order_by('-weight_difference')[:10]

        # 7. Top 10 Losses
        top_losses = curr_qs.filter(loss_weight__gt=0).select_related('party', 'product', 'loss_type', 'driver').order_by('-loss_weight')[:10]

        return {
            'top_products': top_products_list,
            'top_parties': top_parties_list,
            'top_drivers': top_drivers_list,
            'top_vehicles': top_vehicles_list,
            'top_origins': top_origins,
            'top_destinations': top_destinations,
            'top_discrepancies': top_discrepancies,
            'top_losses': top_losses,
        }

    @staticmethod
    def get_traffic_heatmap(curr_qs):
        matrix = [[0 for _ in range(24)] for _ in range(7)]
        # Performance optimization: lightweight values_list and direct weekday arithmetic
        tickets = curr_qs.values_list('first_weight_date', 'first_weight_time', 'created_at')
        for f_date, f_time, created_at in tickets:
            d = f_date or (created_at.date() if created_at else None)
            tm = f_time or (created_at.time() if created_at else None)
            if d and tm:
                # In Jalali calendar, Saturday is index 0.
                # In Python Gregorian date.weekday(), Monday=0, Saturday=5.
                # Direct arithmetic (d.weekday() + 2) % 7 is mathematically identical to
                # jdatetime.date.fromgregorian(date=d).weekday() while being ~195x faster.
                day_idx = (d.weekday() + 2) % 7
                hour_idx = tm.hour
                if 0 <= day_idx < 7 and 0 <= hour_idx < 24:
                    matrix[day_idx][hour_idx] += 1
        return matrix


class ManagementReportService:
    @staticmethod
    def get_inbound_outbound_data(curr_qs):
        completed = curr_qs.filter(status=TicketStatus.COMPLETED)
        in_qs = completed.filter(operation_type__direction='inbound')
        out_qs = completed.filter(operation_type__direction='outbound')

        in_net = in_qs.aggregate(s=Sum('net_weight'))['s'] or Decimal('0')
        out_net = out_qs.aggregate(s=Sum('net_weight'))['s'] or Decimal('0')
        diff_net = in_net - out_net

        in_trips = in_qs.count()
        out_trips = out_qs.count()

        prods_in = in_qs.values('product__name').annotate(net=Sum('net_weight'), trips=Count('id')).order_by('-net')
        prods_out = out_qs.values('product__name').annotate(net=Sum('net_weight'), trips=Count('id')).order_by('-net')

        parties_in = in_qs.values('party__name').annotate(net=Sum('net_weight'), trips=Count('id')).order_by('-net')
        parties_out = out_qs.values('party__name').annotate(net=Sum('net_weight'), trips=Count('id')).order_by('-net')

        return {
            'in_trips': in_trips,
            'in_net_ton': round(float(in_net) / 1000.0, 2),
            'out_trips': out_trips,
            'out_net_ton': round(float(out_net) / 1000.0, 2),
            'diff_net_ton': round(float(diff_net) / 1000.0, 2),
            'diff_is_positive': diff_net >= 0,
            'prods_in': prods_in,
            'prods_out': prods_out,
            'parties_in': parties_in,
            'parties_out': parties_out,
        }

    @staticmethod
    def get_purchase_data(curr_qs):
        purchase_qs = curr_qs.filter(
            Q(operation_type__name__icontains='خرید') | Q(operation_type__direction='inbound')
        ).filter(status=TicketStatus.COMPLETED)

        aggr = purchase_qs.aggregate(
            trips=Count('id'),
            net=Sum('net_weight'),
            final=Sum('final_weight'),
            sent=Sum('sent_weight'),
            loss=Sum('loss_weight'),
            diff=Sum('weight_difference'),
            loss_pct=Avg('loss_percent'),
        )
        total_net = aggr['net'] or Decimal('0')
        trips = aggr['trips'] or 0
        avg_load = round(float(total_net) / trips / 1000.0, 2) if trips else 0.0

        suppliers_table = purchase_qs.values('party__name', 'party__id').annotate(
            trips=Count('id'),
            sent_kg=Sum('sent_weight'),
            net_kg=Sum('net_weight'),
            final_kg=Sum('final_weight'),
            diff_kg=Sum('weight_difference'),
            loss_kg=Sum('loss_weight'),
            avg_loss=Avg('loss_percent'),
            discrepancies=Count('id', filter=Q(is_tolerance_exceeded=True))
        ).order_by('-net_kg')

        return {
            'trips': trips,
            'net_ton': round(float(total_net) / 1000.0, 2),
            'final_ton': round(float(aggr['final'] or 0) / 1000.0, 2),
            'sent_ton': round(float(aggr['sent'] or 0) / 1000.0, 2),
            'loss_ton': round(float(aggr['loss'] or 0) / 1000.0, 2),
            'diff_kg': float(aggr['diff'] or 0),
            'avg_loss_pct': round(float(aggr['loss_pct'] or 0), 2),
            'avg_load_ton': avg_load,
            'suppliers_table': suppliers_table,
        }

    @staticmethod
    def get_sales_data(curr_qs):
        sales_qs = curr_qs.filter(
            Q(operation_type__name__icontains='فروش') | Q(operation_type__direction='outbound')
        ).filter(status=TicketStatus.COMPLETED)

        aggr = sales_qs.aggregate(
            trips=Count('id'),
            net=Sum('net_weight'),
            final=Sum('final_weight'),
            loss=Sum('loss_weight'),
            diff=Sum('weight_difference'),
        )
        total_net = aggr['net'] or Decimal('0')
        trips = aggr['trips'] or 0
        avg_load = round(float(total_net) / trips / 1000.0, 2) if trips else 0.0

        customers_table = sales_qs.values('party__name', 'party__id').annotate(
            trips=Count('id'),
            net_kg=Sum('net_weight'),
            final_kg=Sum('final_weight'),
            diff_kg=Sum('weight_difference'),
            discrepancies=Count('id', filter=Q(is_tolerance_exceeded=True))
        ).order_by('-net_kg')

        products_table = sales_qs.values('product__name', 'product__id').annotate(
            trips=Count('id'),
            net_kg=Sum('net_weight'),
            final_kg=Sum('final_weight'),
        ).order_by('-net_kg')

        return {
            'trips': trips,
            'net_ton': round(float(total_net) / 1000.0, 2),
            'final_ton': round(float(aggr['final'] or 0) / 1000.0, 2),
            'avg_load_ton': avg_load,
            'customers_count': sales_qs.values('party').distinct().count(),
            'vehicles_count': sales_qs.values('license_plate_display').distinct().count(),
            'customers_table': customers_table,
            'products_table': products_table,
        }

    @staticmethod
    def get_product_analysis(curr_qs):
        completed = curr_qs.filter(status=TicketStatus.COMPLETED)
        total_net = completed.aggregate(s=Sum('net_weight'))['s'] or Decimal('1')

        prods = completed.filter(product__isnull=False).values('product__name', 'product__code', 'product__id').annotate(
            trips=Count('id'),
            net_kg=Sum('net_weight'),
            final_kg=Sum('final_weight'),
            sent_kg=Sum('sent_weight'),
            diff_kg=Sum('weight_difference'),
            loss_kg=Sum('loss_weight'),
            avg_loss=Avg('loss_percent'),
            discrepancies=Count('id', filter=Q(is_tolerance_exceeded=True))
        ).order_by('-net_kg')

        rows = []
        for p in prods:
            n_kg = float(p['net_kg'] or 0)
            t = p['trips'] or 1
            rows.append({
                'id': p['product__id'],
                'name': p['product__name'],
                'code': p['product__code'],
                'trips': p['trips'],
                'net_ton': round(n_kg / 1000.0, 2),
                'final_ton': round(float(p['final_kg'] or 0) / 1000.0, 2),
                'share_pct': round((n_kg / float(total_net)) * 100, 1),
                'avg_load_ton': round((n_kg / t) / 1000.0, 2),
                'sent_ton': round(float(p['sent_kg'] or 0) / 1000.0, 2),
                'diff_kg': float(p['diff_kg'] or 0),
                'loss_ton': round(float(p['loss_kg'] or 0) / 1000.0, 2),
                'avg_loss_pct': round(float(p['avg_loss'] or 0), 2),
                'discrepancies': p['discrepancies'],
            })
        return rows

    @staticmethod
    def get_party_analysis(curr_qs):
        completed = curr_qs.filter(status=TicketStatus.COMPLETED)
        parties = completed.filter(party__isnull=False).values('party__name', 'party__party_type', 'party__id').annotate(
            trips=Count('id'),
            net_kg=Sum('net_weight'),
            final_kg=Sum('final_weight'),
            sent_kg=Sum('sent_weight'),
            diff_kg=Sum('weight_difference'),
            loss_kg=Sum('loss_weight'),
            avg_loss=Avg('loss_percent'),
            discrepancies=Count('id', filter=Q(is_tolerance_exceeded=True)),
            first_date=Min('first_weight_date'),
            last_date=Max('first_weight_date'),
        ).order_by('-net_kg')

        rows = []
        for pt in parties:
            rows.append({
                'id': pt['party__id'],
                'name': pt['party__name'],
                'type': pt['party__party_type'],
                'trips': pt['trips'],
                'net_ton': round(float(pt['net_kg'] or 0) / 1000.0, 2),
                'final_ton': round(float(pt['final_kg'] or 0) / 1000.0, 2),
                'sent_ton': round(float(pt['sent_kg'] or 0) / 1000.0, 2),
                'diff_kg': float(pt['diff_kg'] or 0),
                'loss_ton': round(float(pt['loss_kg'] or 0) / 1000.0, 2),
                'avg_loss_pct': round(float(pt['avg_loss'] or 0), 2),
                'discrepancies': pt['discrepancies'],
                'first_date_jalali': format_jalali_date(pt['first_date']),
                'last_date_jalali': format_jalali_date(pt['last_date']),
            })
        return rows

    @staticmethod
    def get_discrepancy_analysis(curr_qs, threshold_kg=50):
        tickets = curr_qs.filter(
            Q(is_tolerance_exceeded=True) | Q(weight_difference__gte=threshold_kg) | Q(weight_difference__lte=-threshold_kg)
        ).select_related('party', 'product', 'driver').order_by('-created_at')

        party_aggr = curr_qs.filter(party__isnull=False).values('party__name', 'party__id').annotate(
            trips=Count('id'),
            sent_kg=Sum('sent_weight'),
            net_kg=Sum('net_weight'),
            diff_kg=Sum('weight_difference'),
            avg_diff=Avg('weight_difference'),
            max_diff=Max('weight_difference'),
            discrepancies=Count('id', filter=Q(is_tolerance_exceeded=True))
        ).filter(discrepancies__gt=0).order_by('-discrepancies')

        prod_aggr = curr_qs.filter(product__isnull=False).values('product__name', 'product__id').annotate(
            trips=Count('id'),
            net_kg=Sum('net_weight'),
            diff_kg=Sum('weight_difference'),
            avg_diff=Avg('weight_difference'),
            discrepancies=Count('id', filter=Q(is_tolerance_exceeded=True))
        ).filter(discrepancies__gt=0).order_by('-discrepancies')

        return {
            'tickets': tickets,
            'count': tickets.count(),
            'party_aggr': party_aggr,
            'prod_aggr': prod_aggr,
        }

    @staticmethod
    def get_loss_analysis(curr_qs):
        completed = curr_qs.filter(status=TicketStatus.COMPLETED)
        aggr = completed.aggregate(
            net=Sum('net_weight'),
            loss=Sum('loss_weight'),
            final=Sum('final_weight'),
            avg_loss=Avg('loss_percent'),
            max_loss=Max('loss_weight'),
        )
        total_loads = completed.count()
        loss_loads = completed.filter(loss_weight__gt=0).count()
        no_loss_loads = total_loads - loss_loads

        by_type = completed.filter(loss_type__isnull=False).values('loss_type__name').annotate(
            trips=Count('id'),
            total_loss=Sum('loss_weight')
        ).order_by('-total_loss')

        by_product = completed.filter(product__isnull=False, loss_weight__gt=0).values('product__name').annotate(
            trips=Count('id'),
            total_loss=Sum('loss_weight'),
            avg_loss=Avg('loss_percent')
        ).order_by('-total_loss')

        by_party = completed.filter(party__isnull=False, loss_weight__gt=0).values('party__name').annotate(
            trips=Count('id'),
            total_loss=Sum('loss_weight'),
            avg_loss=Avg('loss_percent')
        ).order_by('-total_loss')

        top_loss_tickets = completed.filter(loss_weight__gt=0).select_related(
            'party', 'product', 'loss_type', 'driver'
        ).order_by('-loss_weight')[:25]

        return {
            'net_ton': round(float(aggr['net'] or 0) / 1000.0, 2),
            'loss_ton': round(float(aggr['loss'] or 0) / 1000.0, 2),
            'final_ton': round(float(aggr['final'] or 0) / 1000.0, 2),
            'avg_loss_pct': round(float(aggr['avg_loss'] or 0), 2),
            'max_loss_kg': float(aggr['max_loss'] or 0),
            'total_loads': total_loads,
            'loss_loads': loss_loads,
            'no_loss_loads': no_loss_loads,
            'by_type': by_type,
            'by_product': by_product,
            'by_party': by_party,
            'top_loss_tickets': top_loss_tickets,
        }

    @staticmethod
    def get_fleet_performance(curr_qs):
        drivers = curr_qs.values('driver__full_name', 'driver_name_custom', 'driver__id').annotate(
            trips=Count('id'),
            net_kg=Sum('net_weight'),
            vehicles_count=Count('license_plate_display', distinct=True),
            discrepancies=Count('id', filter=Q(is_tolerance_exceeded=True)),
            first_date=Min('first_weight_date'),
            last_date=Max('first_weight_date')
        ).order_by('-trips')

        driver_rows = []
        for d in drivers:
            t = d['trips'] or 1
            n_kg = float(d['net_kg'] or 0)
            driver_rows.append({
                'name': d['driver__full_name'] or d['driver_name_custom'] or 'نامشخص',
                'trips': d['trips'],
                'net_ton': round(n_kg / 1000.0, 2),
                'avg_load_ton': round((n_kg / t) / 1000.0, 2),
                'vehicles_count': d['vehicles_count'],
                'discrepancies': d['discrepancies'],
                'first_date': format_jalali_date(d['first_date']),
                'last_date': format_jalali_date(d['last_date']),
            })

        vehicles = curr_qs.values('license_plate_display').annotate(
            trips=Count('id'),
            net_kg=Sum('net_weight'),
            drivers_count=Count('driver', distinct=True),
            parties_count=Count('party', distinct=True),
            discrepancies=Count('id', filter=Q(is_tolerance_exceeded=True)),
            last_date=Max('first_weight_date')
        ).order_by('-trips')

        vehicle_rows = []
        for v in vehicles:
            t = v['trips'] or 1
            n_kg = float(v['net_kg'] or 0)
            vehicle_rows.append({
                'plate': v['license_plate_display'] or 'نامشخص',
                'trips': v['trips'],
                'net_ton': round(n_kg / 1000.0, 2),
                'avg_load_ton': round((n_kg / t) / 1000.0, 2),
                'drivers_count': v['drivers_count'],
                'parties_count': v['parties_count'],
                'discrepancies': v['discrepancies'],
                'last_date': format_jalali_date(v['last_date']),
            })

        return driver_rows, vehicle_rows

    @staticmethod
    def get_routes_analysis(curr_qs):
        origins = curr_qs.filter(origin__isnull=False).values('origin__name', 'origin__id').annotate(
            trips=Count('id'),
            net_kg=Sum('net_weight')
        ).order_by('-net_kg')

        destinations = curr_qs.filter(destination__isnull=False).values('destination__name', 'destination__id').annotate(
            trips=Count('id'),
            net_kg=Sum('net_weight')
        ).order_by('-net_kg')

        routes = curr_qs.filter(origin__isnull=False, destination__isnull=False).values(
            'origin__name', 'destination__name'
        ).annotate(
            trips=Count('id'),
            net_kg=Sum('net_weight'),
            trucks_count=Count('license_plate_display', distinct=True)
        ).order_by('-net_kg')[:20]

        return origins, destinations, routes

    @staticmethod
    def get_operations_performance(curr_qs):
        total_tickets = curr_qs.count()
        completed_tickets = curr_qs.filter(status=TicketStatus.COMPLETED).count()
        in_yard = curr_qs.filter(status__in=[TicketStatus.WAITING_SECOND, TicketStatus.FIRST_REGISTERED]).count()
        cancelled = curr_qs.filter(status=TicketStatus.CANCELLED).count()
        edited = curr_qs.filter(last_edited_by__isnull=False).count()

        turnaround_minutes = []
        # Performance optimization: fetch lightweight tuples instead of all model instances and relations
        valid_completed_tuples = list(curr_qs.filter(
            status=TicketStatus.COMPLETED,
            first_weight_time__isnull=False,
            second_weight_time__isnull=False,
            first_weight_date__isnull=False,
            second_weight_date__isnull=False
        ).values_list('id', 'first_weight_date', 'first_weight_time', 'second_weight_date', 'second_weight_time'))

        excluded_count = max(0, completed_tickets - len(valid_completed_tuples))

        under_30 = 0
        between_30_60 = 0
        between_1_2h = 0
        between_2_3h = 0
        over_3h = 0
        slow_ticket_ids = []

        for tid, d1, t1, d2, t2 in valid_completed_tuples:
            dt1 = datetime.combine(d1, t1)
            dt2 = datetime.combine(d2, t2)
            diff_sec = (dt2 - dt1).total_seconds()
            if diff_sec > 0:
                mins = round(diff_sec / 60.0, 1)
                turnaround_minutes.append(mins)

                if mins < 30:
                    under_30 += 1
                elif mins <= 60:
                    between_30_60 += 1
                elif mins <= 120:
                    between_1_2h += 1
                elif mins <= 180:
                    between_2_3h += 1
                else:
                    over_3h += 1

                if mins >= 60:
                    slow_ticket_ids.append((tid, mins))

        slow_ticket_ids.sort(key=lambda x: x[1], reverse=True)
        top_slow_slice = slow_ticket_ids[:20]

        # Only instantiate model objects for the top 20 slow operations
        slow_ops = []
        if top_slow_slice:
            slow_ids = [item[0] for item in top_slow_slice]
            ticket_objs = {t.id: t for t in WeighTicket.objects.filter(id__in=slow_ids).select_related('product', 'party', 'driver')}
            for tid, mins in top_slow_slice:
                if tid in ticket_objs:
                    slow_ops.append({
                        'ticket': ticket_objs[tid],
                        'minutes': mins,
                        'duration_str': f"{int(mins // 60)} ساعت و {int(mins % 60)} دقیقه",
                    })

        avg_turnaround = round(statistics.mean(turnaround_minutes), 1) if turnaround_minutes else 0
        median_turnaround = round(statistics.median(turnaround_minutes), 1) if turnaround_minutes else 0
        min_turnaround = min(turnaround_minutes) if turnaround_minutes else 0
        max_turnaround = max(turnaround_minutes) if turnaround_minutes else 0

        # --- Phase 3.2.2 Accurate Dual-Operator Attribution ---
        # 1. Operators involved in first weighing
        first_ops = curr_qs.filter(first_weight_operator__isnull=False).values(
            'first_weight_operator__id',
            'first_weight_operator__username',
            'first_weight_operator__first_name',
            'first_weight_operator__last_name'
        ).annotate(
            first_weights=Count('id'),
            first_discrepancies=Count('id', filter=Q(is_tolerance_exceeded=True)),
            first_cancelled=Count('id', filter=Q(status=TicketStatus.CANCELLED))
        )

        # 2. Operators involved in second weighing (completed tickets)
        second_ops = curr_qs.filter(
            second_weight_operator__isnull=False,
            status=TicketStatus.COMPLETED
        ).values(
            'second_weight_operator__id',
            'second_weight_operator__username',
            'second_weight_operator__first_name',
            'second_weight_operator__last_name'
        ).annotate(
            second_weights=Count('id'),
            second_discrepancies=Count('id', filter=Q(is_tolerance_exceeded=True))
        )

        # 3. Solo completed tickets (first_weight_operator == second_weight_operator)
        solo_ops = curr_qs.filter(
            status=TicketStatus.COMPLETED,
            first_weight_operator=F('second_weight_operator'),
            first_weight_operator__isnull=False
        ).values('first_weight_operator__id').annotate(solo_completed=Count('id'))
        solo_map = {row['first_weight_operator__id']: row['solo_completed'] for row in solo_ops}

        # 4. Edits by user
        edits_ops = curr_qs.filter(last_edited_by__isnull=False).values('last_edited_by__id').annotate(edits=Count('id'))
        edits_map = {row['last_edited_by__id']: row['edits'] for row in edits_ops}

        # Combine into unified operator dictionary
        operators_dict = {}

        for op in first_ops:
            uid = op['first_weight_operator__id']
            operators_dict[uid] = {
                'id': uid,
                'username': op['first_weight_operator__username'] or 'سیستم',
                'first_name': op['first_weight_operator__first_name'] or '',
                'last_name': op['first_weight_operator__last_name'] or '',
                'first_weight_operator__username': op['first_weight_operator__username'] or 'سیستم',
                'first_weight_operator__first_name': op['first_weight_operator__first_name'] or '',
                'first_weight_operator__last_name': op['first_weight_operator__last_name'] or '',
                'first_weights': op['first_weights'],
                'second_weights': 0,
                'total_tasks': op['first_weights'],
                'completed': 0,
                'solo_completed': solo_map.get(uid, 0),
                'edited': edits_map.get(uid, 0),
                'cancelled': op['first_cancelled'],
                'discrepancies': op['first_discrepancies'],
            }

        for op in second_ops:
            uid = op['second_weight_operator__id']
            if uid not in operators_dict:
                operators_dict[uid] = {
                    'id': uid,
                    'username': op['second_weight_operator__username'] or 'سیستم',
                    'first_name': op['second_weight_operator__first_name'] or '',
                    'last_name': op['second_weight_operator__last_name'] or '',
                    'first_weight_operator__username': op['second_weight_operator__username'] or 'سیستم',
                    'first_weight_operator__first_name': op['second_weight_operator__first_name'] or '',
                    'first_weight_operator__last_name': op['second_weight_operator__last_name'] or '',
                    'first_weights': 0,
                    'second_weights': op['second_weights'],
                    'total_tasks': op['second_weights'],
                    'completed': op['second_weights'],
                    'solo_completed': solo_map.get(uid, 0),
                    'edited': edits_map.get(uid, 0),
                    'cancelled': 0,
                    'discrepancies': op['second_discrepancies'],
                }
            else:
                operators_dict[uid]['second_weights'] = op['second_weights']
                operators_dict[uid]['total_tasks'] += op['second_weights']
                operators_dict[uid]['completed'] = op['second_weights']
                operators_dict[uid]['discrepancies'] = max(
                    operators_dict[uid]['discrepancies'], op['second_discrepancies']
                )

        operators_list = list(operators_dict.values())
        operators_list.sort(key=lambda x: (x['total_tasks'], x['completed']), reverse=True)

        return {
            'total_tickets': total_tickets,
            'completed_tickets': completed_tickets,
            'excluded_missing_timestamps': excluded_count,
            'in_yard': in_yard,
            'cancelled': cancelled,
            'edited': edited,
            'avg_turnaround': avg_turnaround,
            'median_turnaround': median_turnaround,
            'min_turnaround': min_turnaround,
            'max_turnaround': max_turnaround,
            'under_30': under_30,
            'between_30_60': between_30_60,
            'between_1_2h': between_1_2h,
            'between_2_3h': between_2_3h,
            'over_3h': over_3h,
            'slow_operations': slow_ops,
            'operators': operators_list,
        }

    @staticmethod
    def get_monthly_executive_data(year: int, month: int):
        days_in_m = get_jalali_days_in_month(year, month)
        start_j = jdatetime.date(year, month, 1)
        end_j = jdatetime.date(year, month, days_in_m)
        start_g = start_j.togregorian()
        end_g = end_j.togregorian()

        if month == 1:
            prev_year = year - 1
            prev_month = 12
        else:
            prev_year = year
            prev_month = month - 1
        prev_days = get_jalali_days_in_month(prev_year, prev_month)
        prev_start_g = jdatetime.date(prev_year, prev_month, 1).togregorian()
        prev_end_g = jdatetime.date(prev_year, prev_month, prev_days).togregorian()

        curr_qs = WeighTicket.objects.filter(
            Q(first_weight_date__range=[start_g, end_g]) | Q(created_at__date__range=[start_g, end_g])
        )
        prev_qs = WeighTicket.objects.filter(
            Q(first_weight_date__range=[prev_start_g, prev_end_g]) | Q(created_at__date__range=[prev_start_g, prev_end_g])
        )

        kpis, prev_kpis, comparison = ManagementDashboardService.calculate_kpis_with_comparison(curr_qs, prev_qs)
        top10 = ManagementDashboardService.get_top10_metrics(curr_qs)
        trends = ManagementDashboardService.get_tonnage_trend(start_g, end_g, granularity='daily')

        month_title = f"{get_jalali_month_name(month)} {year}"
        prev_month_title = f"{get_jalali_month_name(prev_month)} {prev_year}"

        return {
            'month_title': month_title,
            'prev_month_title': prev_month_title,
            'year': year,
            'month': month,
            'start_date_jalali': format_jalali_date(start_g),
            'end_date_jalali': format_jalali_date(end_g),
            'kpis': kpis,
            'comparison': comparison,
            'top10': top10,
            'trends': trends,
        }

    @staticmethod
    def get_yearly_executive_data(year: int):
        months_data = []
        labels = []
        net_series = []
        inbound_series = []
        outbound_series = []
        loss_series = []
        discrepancy_series = []
        trips_series = []

        total_net_all = Decimal('0')
        total_trips_all = 0
        total_loss_all = Decimal('0')
        total_discrepancies_all = 0

        for m in range(1, 13):
            days_in_m = get_jalali_days_in_month(year, m)
            start_j = jdatetime.date(year, m, 1)
            end_j = jdatetime.date(year, m, days_in_m)
            start_g = start_j.togregorian()
            end_g = end_j.togregorian()

            m_qs = WeighTicket.objects.filter(
                Q(first_weight_date__range=[start_g, end_g]) | Q(created_at__date__range=[start_g, end_g])
            )
            m_comp = m_qs.filter(status=TicketStatus.COMPLETED)
            aggr = m_comp.aggregate(
                net=Sum('net_weight'),
                final=Sum('final_weight'),
                loss=Sum('loss_weight'),
                inbound=Sum('net_weight', filter=Q(operation_type__direction='inbound')),
                outbound=Sum('net_weight', filter=Q(operation_type__direction='outbound')),
            )
            trips = m_qs.count()
            net_kg = aggr['net'] or Decimal('0')
            in_kg = aggr['inbound'] or Decimal('0')
            out_kg = aggr['outbound'] or Decimal('0')
            loss_kg = aggr['loss'] or Decimal('0')
            discs = m_qs.filter(is_tolerance_exceeded=True).count()

            m_name = get_jalali_month_name(m)
            labels.append(m_name)
            net_ton = round(float(net_kg) / 1000.0, 2)
            in_ton = round(float(in_kg) / 1000.0, 2)
            out_ton = round(float(out_kg) / 1000.0, 2)
            loss_ton = round(float(loss_kg) / 1000.0, 2)

            net_series.append(net_ton)
            inbound_series.append(in_ton)
            outbound_series.append(out_ton)
            loss_series.append(loss_ton)
            discrepancy_series.append(discs)
            trips_series.append(trips)

            total_net_all += net_kg
            total_trips_all += trips
            total_loss_all += loss_kg
            total_discrepancies_all += discs

            months_data.append({
                'month_num': m,
                'month_name': m_name,
                'trips': trips,
                'net_ton': net_ton,
                'inbound_ton': in_ton,
                'outbound_ton': out_ton,
                'loss_ton': loss_ton,
                'discrepancies': discs,
            })

        return {
            'year': year,
            'year_title': f'سال {year}',
            'months_data': months_data,
            'total_trips': total_trips_all,
            'total_net_ton': round(float(total_net_all) / 1000.0, 2),
            'total_loss_ton': round(float(total_loss_all) / 1000.0, 2),
            'total_discrepancies': total_discrepancies_all,
            'chart_data': {
                'labels': labels,
                'net': net_series,
                'inbound': inbound_series,
                'outbound': outbound_series,
                'loss': loss_series,
                'discrepancies': discrepancy_series,
                'trips': trips_series,
            }
        }
