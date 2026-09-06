import math
import statistics
from decimal import Decimal
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional

from django.db.models import (
    Sum, Count, Avg, Min, Max, Q, F, StdDev, Case, When, Value, IntegerField, FloatField, DecimalField
)
from django.utils import timezone

from weighbridge.models import WeighTicket, TicketStatus
from masterdata.models import Party, Product, PartyType
from monitoring.models import MonitoringAlert, AlertSeverity, AlertType, AlertStatus
from audit.models import AuditLog, AuditAction
from core.jalali import (
    get_today_gregorian, get_today_jalali, format_jalali_date,
    format_jalali_datetime, jalali_to_gregorian, gregorian_to_jalali,
    get_jalali_range_gregorian, get_comparison_period_gregorian
)
from management.models import (
    PartyScoringConfig, PartyScoreSnapshot, ScoreLevel, ScoreConfidence, TrendDirection
)


class PartyAnalyticsService:
    """
    سرویس جامع تحلیل آماری، روندها، مقایسه گروهی و رتبه‌بندی طرف‌حساب‌ها (قاعده‌محور و فاقد جعبه‌سیاه).
    """

    @staticmethod
    def get_filtered_ticket_queryset(party, start_date=None, end_date=None, product=None, operation_type=None):
        """
        کوئری‌ست پایه قبوض طرف‌حساب با اعمال فیلترهای زمانی و کالایی.
        """
        qs = WeighTicket.objects.filter(party=party)
        if start_date and end_date:
            qs = qs.filter(
                Q(first_weight_date__range=[start_date, end_date]) |
                Q(first_weight_date__isnull=True, created_at__date__range=[start_date, end_date])
            )
        elif start_date:
            qs = qs.filter(
                Q(first_weight_date__gte=start_date) |
                Q(first_weight_date__isnull=True, created_at__date__gte=start_date)
            )
        elif end_date:
            qs = qs.filter(
                Q(first_weight_date__lte=end_date) |
                Q(first_weight_date__isnull=True, created_at__date__lte=end_date)
            )

        if product:
            qs = qs.filter(product=product)
        if operation_type:
            qs = qs.filter(operation_type=operation_type)

        return qs

    @classmethod
    def calculate_party_profile(cls, party, qs):
        """
        محاسبه شناسنامه آماری کلی و حجم بار طرف‌حساب.
        """
        total_tickets = qs.count()
        completed_qs = qs.filter(status=TicketStatus.COMPLETED)
        cancelled_tickets = qs.filter(status=TicketStatus.CANCELLED).count()
        completed_count = completed_qs.count()

        agg = completed_qs.aggregate(
            total_net=Sum('net_weight'),
            total_final=Sum('final_weight'),
            avg_net=Avg('net_weight'),
            avg_final=Avg('final_weight'),
            min_net=Min('net_weight'),
            max_net=Max('net_weight'),
            first_date=Min('first_weight_date'),
            last_date=Max('first_weight_date'),
            active_days=Count('first_weight_date', distinct=True),
        )

        return {
            'party_id': party.id,
            'party_name': party.name,
            'party_type': party.party_type,
            'party_type_display': party.get_party_type_display(),
            'total_tickets': total_tickets,
            'completed_tickets': completed_count,
            'cancelled_tickets': cancelled_tickets,
            'total_net_weight_kg': float(agg['total_net'] or 0),
            'total_net_weight_ton': round(float(agg['total_net'] or 0) / 1000.0, 2),
            'total_final_weight_kg': float(agg['total_final'] or 0),
            'total_final_weight_ton': round(float(agg['total_final'] or 0) / 1000.0, 2),
            'average_net_weight_kg': round(float(agg['avg_net'] or 0), 2),
            'average_final_weight_kg': round(float(agg['avg_final'] or 0), 2),
            'min_net_weight_kg': float(agg['min_net'] or 0),
            'max_net_weight_kg': float(agg['max_net'] or 0),
            'first_ticket_date': agg['first_date'].isoformat() if agg['first_date'] else None,
            'first_ticket_date_fa': format_jalali_date(agg['first_date']) if agg['first_date'] else '-',
            'last_ticket_date': agg['last_date'].isoformat() if agg['last_date'] else None,
            'last_ticket_date_fa': format_jalali_date(agg['last_date']) if agg['last_date'] else '-',
            'active_days': agg['active_days'] or 0,
        }

    @classmethod
    def calculate_discrepancy_metrics(cls, completed_qs):
        """
        محاسبه شاخص‌های مغایرت وزن ارسالی و باسکول (قبوض ابطالی لحاظ نمی‌شوند).
        """
        completed_count = completed_qs.count()
        if completed_count == 0:
            return {
                'total_discrepancy_kg': 0.0,
                'average_signed_discrepancy_kg': 0.0,
                'average_absolute_discrepancy_kg': 0.0,
                'median_absolute_discrepancy_kg': 0.0,
                'maximum_absolute_discrepancy_kg': 0.0,
                'average_discrepancy_percent': 0.0,
                'discrepancy_stddev': 0.0,
                'tickets_with_discrepancy': 0,
                'discrepancy_rate': 0.0,
                'tickets_with_sent_weight': 0,
                'missing_sent_weight_rate': 0.0,
            }

        sent_qs = completed_qs.filter(sent_weight__gt=0)
        sent_count = sent_qs.count()
        missing_sent_rate = round(((completed_count - sent_count) / completed_count) * 100.0, 1)

        if sent_count == 0:
            return {
                'total_discrepancy_kg': 0.0,
                'average_signed_discrepancy_kg': 0.0,
                'average_absolute_discrepancy_kg': 0.0,
                'median_absolute_discrepancy_kg': 0.0,
                'maximum_absolute_discrepancy_kg': 0.0,
                'average_discrepancy_percent': 0.0,
                'discrepancy_stddev': 0.0,
                'tickets_with_discrepancy': 0,
                'discrepancy_rate': 0.0,
                'tickets_with_sent_weight': 0,
                'missing_sent_weight_rate': missing_sent_rate,
            }

        diffs = list(sent_qs.values_list('weight_difference', 'weight_difference_percent', 'is_tolerance_exceeded'))
        signed_diffs = [float(d[0] or 0) for d in diffs]
        abs_diffs = [abs(val) for val in signed_diffs]
        pct_diffs = [abs(float(d[1] or 0)) for d in diffs]
        exceeded_count = sum(1 for d in diffs if d[2])

        total_discrepancy = sum(signed_diffs)
        avg_signed = total_discrepancy / len(signed_diffs)
        avg_abs = sum(abs_diffs) / len(abs_diffs)
        median_abs = statistics.median(abs_diffs) if abs_diffs else 0.0
        max_abs = max(abs_diffs) if abs_diffs else 0.0
        avg_pct = sum(pct_diffs) / len(pct_diffs) if pct_diffs else 0.0
        stddev_val = statistics.stdev(signed_diffs) if len(signed_diffs) > 1 else 0.0
        discrepancy_rate = round((exceeded_count / completed_count) * 100.0, 2)

        return {
            'total_discrepancy_kg': round(total_discrepancy, 2),
            'average_signed_discrepancy_kg': round(avg_signed, 2),
            'average_absolute_discrepancy_kg': round(avg_abs, 2),
            'median_absolute_discrepancy_kg': round(median_abs, 2),
            'maximum_absolute_discrepancy_kg': round(max_abs, 2),
            'average_discrepancy_percent': round(avg_pct, 2),
            'discrepancy_stddev': round(stddev_val, 2),
            'tickets_with_discrepancy': exceeded_count,
            'discrepancy_rate': discrepancy_rate,
            'tickets_with_sent_weight': sent_count,
            'missing_sent_weight_rate': missing_sent_rate,
        }

    @classmethod
    def calculate_loss_metrics(cls, completed_qs):
        """
        محاسبه شاخص‌های افت وزنی محموله‌ها.
        """
        completed_count = completed_qs.count()
        if completed_count == 0:
            return {
                'total_loss_weight': 0.0,
                'average_loss_weight': 0.0,
                'average_loss_percent': 0.0,
                'median_loss_percent': 0.0,
                'maximum_loss_percent': 0.0,
                'loss_stddev': 0.0,
                'tickets_with_loss': 0,
                'loss_rate': 0.0,
                'missing_loss_data_rate': 0.0,
            }

        loss_data = list(completed_qs.values_list('loss_weight', 'loss_percent'))
        weights = [float(d[0] or 0) for d in loss_data]
        percents = [float(d[1] or 0) for d in loss_data]

        tickets_with_loss = sum(1 for w in weights if w > 0)
        total_loss = sum(weights)
        avg_loss_weight = total_loss / len(weights)
        avg_loss_pct = sum(percents) / len(percents)
        median_loss_pct = statistics.median(percents) if percents else 0.0
        max_loss_pct = max(percents) if percents else 0.0
        loss_stddev = statistics.stdev(percents) if len(percents) > 1 else 0.0
        loss_rate = round((tickets_with_loss / completed_count) * 100.0, 2)

        return {
            'total_loss_weight': round(total_loss, 2),
            'average_loss_weight': round(avg_loss_weight, 2),
            'average_loss_percent': round(avg_loss_pct, 2),
            'median_loss_percent': round(median_loss_pct, 2),
            'maximum_loss_percent': round(max_loss_pct, 2),
            'loss_stddev': round(loss_stddev, 2),
            'tickets_with_loss': tickets_with_loss,
            'loss_rate': loss_rate,
            'missing_loss_data_rate': 0.0,
        }

    @classmethod
    def calculate_monitoring_metrics(cls, party, qs):
        """
        محاسبه هشدارهای پایش هوشمند فاز ۳ برای طرف‌حساب جاری.
        """
        ticket_ids = qs.values_list('id', flat=True)
        alerts_qs = MonitoringAlert.objects.filter(ticket_id__in=ticket_ids).distinct()

        total_alerts = alerts_qs.count()
        completed_count = qs.filter(status=TicketStatus.COMPLETED).count()

        status_counts = alerts_qs.values('status').annotate(c=Count('id'))
        status_map = {item['status']: item['c'] for item in status_counts}

        open_alerts = status_map.get(AlertStatus.OPEN, 0)
        reviewed_alerts = status_map.get(AlertStatus.REVIEWED, 0)
        resolved_alerts = status_map.get(AlertStatus.RESOLVED, 0)
        ignored_alerts = status_map.get(AlertStatus.IGNORED, 0)

        severity_counts = alerts_qs.values('severity').annotate(c=Count('id'))
        severity_map = {item['severity']: item['c'] for item in severity_counts}

        low_alerts = severity_map.get(AlertSeverity.LOW, 0)
        medium_alerts = severity_map.get(AlertSeverity.MEDIUM, 0)
        high_alerts = severity_map.get(AlertSeverity.HIGH, 0)
        critical_alerts = severity_map.get(AlertSeverity.CRITICAL, 0)

        type_counts = alerts_qs.values('alert_type').annotate(c=Count('id'))
        type_map = {item['alert_type']: item['c'] for item in type_counts}

        alerts_per_100 = round((total_alerts / completed_count * 100.0), 2) if completed_count > 0 else 0.0

        return {
            'total_alerts': total_alerts,
            'open_alerts': open_alerts,
            'reviewed_alerts': reviewed_alerts,
            'resolved_alerts': resolved_alerts,
            'ignored_alerts': ignored_alerts,
            'low_alerts': low_alerts,
            'medium_alerts': medium_alerts,
            'high_alerts': high_alerts,
            'critical_alerts': critical_alerts,
            'alerts_per_100_tickets': alerts_per_100,
            'breakdown_by_type': {
                'VEHICLE_TARE_ANOMALY': type_map.get(AlertType.VEHICLE_TARE_ANOMALY, 0),
                'WEIGHT_DISCREPANCY': type_map.get(AlertType.WEIGHT_DISCREPANCY, 0),
                'LOSS_ANOMALY': type_map.get(AlertType.LOSS_ANOMALY, 0),
                'NET_WEIGHT_ANOMALY': type_map.get(AlertType.NET_WEIGHT_ANOMALY, 0),
                'LONG_WAITING_TIME': type_map.get(AlertType.LONG_WAITING_TIME, 0),
                'WEIGHT_EDIT_ANOMALY': type_map.get(AlertType.WEIGHT_EDIT_ANOMALY, 0),
            }
        }

    @classmethod
    def calculate_turnaround_metrics(cls, completed_qs):
        """
        محاسبه شاخص‌های زمان معطلی خودروها از وزن اول تا وزن دوم.
        """
        two_weight_qs = completed_qs.filter(
            first_weight_date__isnull=False,
            first_weight_time__isnull=False,
            second_weight_date__isnull=False,
            second_weight_time__isnull=False
        )
        count = two_weight_qs.count()
        if count == 0:
            return {
                'average_turnaround_minutes': 0.0,
                'median_turnaround_minutes': 0.0,
                'max_turnaround_minutes': 0.0,
                'turnaround_stddev': 0.0,
                'long_waiting_ticket_count': 0,
                'long_waiting_rate': 0.0,
            }

        durations = []
        for t in two_weight_qs.only('first_weight_date', 'first_weight_time', 'second_weight_date', 'second_weight_time'):
            dt1 = datetime.combine(t.first_weight_date, t.first_weight_time)
            dt2 = datetime.combine(t.second_weight_date, t.second_weight_time)
            diff_mins = (dt2 - dt1).total_seconds() / 60.0
            if 0 <= diff_mins <= 2880:  # فیلتر مقادیر نامعتبر بیش از ۴۸ ساعت
                durations.append(diff_mins)

        if not durations:
            return {
                'average_turnaround_minutes': 0.0,
                'median_turnaround_minutes': 0.0,
                'max_turnaround_minutes': 0.0,
                'turnaround_stddev': 0.0,
                'long_waiting_ticket_count': 0,
                'long_waiting_rate': 0.0,
            }

        avg_m = sum(durations) / len(durations)
        med_m = statistics.median(durations)
        max_m = max(durations)
        std_m = statistics.stdev(durations) if len(durations) > 1 else 0.0
        long_wait = sum(1 for m in durations if m > 120.0)
        long_rate = round((long_wait / len(durations)) * 100.0, 2)

        return {
            'average_turnaround_minutes': round(avg_m, 1),
            'median_turnaround_minutes': round(med_m, 1),
            'max_turnaround_minutes': round(max_m, 1),
            'turnaround_stddev': round(std_m, 1),
            'long_waiting_ticket_count': long_wait,
            'long_waiting_rate': long_rate,
        }

    @classmethod
    def calculate_correction_metrics(cls, qs):
        """
        محاسبه موارد تغییر دستی اوزان و ابطال قبوض از روی لاگ ممیزی (AuditLog).
        """
        ticket_ids = [str(tid) for tid in qs.values_list('id', flat=True)]
        if not ticket_ids:
            return {
                'weight_correction_count': 0,
                'loss_override_count': 0,
                'cancel_count': 0,
                'tickets_with_correction': 0,
                'correction_rate': 0.0,
            }

        audit_qs = AuditLog.objects.filter(
            model_name='WeighTicket',
            record_id__in=ticket_ids
        )

        weight_corr = audit_qs.filter(action=AuditAction.OVERRIDE_WEIGHT).count()
        loss_corr = audit_qs.filter(action=AuditAction.OVERRIDE_LOSS).count()
        cancel_corr = audit_qs.filter(action=AuditAction.CANCEL).count()
        
        corr_ticket_ids = set(audit_qs.filter(
            action__in=[AuditAction.OVERRIDE_WEIGHT, AuditAction.OVERRIDE_LOSS, AuditAction.CANCEL]
        ).values_list('record_id', flat=True))

        total_completed = qs.filter(status=TicketStatus.COMPLETED).count()
        rate = round((len(corr_ticket_ids) / total_completed * 100.0), 2) if total_completed > 0 else 0.0

        return {
            'weight_correction_count': weight_corr,
            'loss_override_count': loss_corr,
            'cancel_count': cancel_corr,
            'tickets_with_correction': len(corr_ticket_ids),
            'correction_rate': rate,
        }

    @classmethod
    def calculate_consistency_metrics(cls, completed_qs):
        """
        محاسبه ثبات اوزان و ثبات درصد افت (ضریب تغییرات و انحراف معیار).
        """
        count = completed_qs.count()
        if count < 5:
            return {
                'is_sufficient_sample': False,
                'weight_stddev': None,
                'weight_variation_coef': None,
                'loss_stddev': None,
                'loss_variation_coef': None,
            }

        weights = list(completed_qs.values_list('net_weight', flat=True))
        weights_float = [float(w) for w in weights if w]

        losses = list(completed_qs.values_list('loss_percent', flat=True))
        losses_float = [float(l) for l in losses if l is not None]

        w_mean = statistics.mean(weights_float) if weights_float else 0.0
        w_std = statistics.stdev(weights_float) if len(weights_float) > 1 else 0.0
        w_cv = round((w_std / w_mean), 3) if w_mean > 0 else 0.0

        l_mean = statistics.mean(losses_float) if losses_float else 0.0
        l_std = statistics.stdev(losses_float) if len(losses_float) > 1 else 0.0
        l_cv = round((l_std / l_mean), 3) if l_mean > 0 else 0.0

        return {
            'is_sufficient_sample': True,
            'weight_stddev': round(w_std, 2),
            'weight_variation_coef': w_cv,
            'loss_stddev': round(l_std, 2),
            'loss_variation_coef': l_cv,
        }

    @classmethod
    def calculate_product_normalized_loss(cls, party, completed_qs):
        """
        محاسبه نرمال‌شده عملکرد افت بر مبنای بیس‌لاین تلرانس هر محصول.
        """
        if not completed_qs.exists():
            return 1.0

        # مقایسه میانگین افت محموله‌های هر محصول این طرف‌حساب با افت استاندارد همان محصول
        by_prod = completed_qs.values('product__name', 'product__default_loss_percent').annotate(
            avg_loss=Avg('loss_percent'),
            ticket_count=Count('id')
        )

        total_weight = 0
        score_accumulator = 0.0

        for row in by_prod:
            t_count = row['ticket_count']
            actual_loss = float(row['avg_loss'] or 0.0)
            baseline_loss = float(row['product__default_loss_percent'] or 0.5)
            if baseline_loss <= 0.0:
                baseline_loss = 0.5

            ratio = actual_loss / baseline_loss
            score_accumulator += ratio * t_count
            total_weight += t_count

        return round(score_accumulator / total_weight, 2) if total_weight > 0 else 1.0

    @classmethod
    def evaluate_score_and_dimensions(cls, party, profile, discrepancy, loss, monitoring, turnaround, corrections, consistency, prod_normalized_loss_ratio, config=None):
        """
        محاسبه امتیاز ابعاد ۶ گانه، امتیاز کل، سطح، اطمینان و دلایل تحلیلی (قاعده‌محور و شفاف).
        """
        if config is None:
            config = PartyScoringConfig.get_config()

        completed_count = profile['completed_tickets']
        conf_thresholds = config.confidence_thresholds or {}

        # ۱. ارزیابی سطح اطمینان آماری (Confidence)
        t_insufficient = conf_thresholds.get('insufficient', 10)
        t_low = conf_thresholds.get('low', 30)
        t_medium = conf_thresholds.get('medium', 100)
        t_high = conf_thresholds.get('high', 300)

        if completed_count < t_insufficient:
            confidence = ScoreConfidence.INSUFFICIENT
            confidence_fa = 'داده ناکافی'
        elif completed_count < t_low:
            confidence = ScoreConfidence.LOW
            confidence_fa = 'پایین'
        elif completed_count < t_medium:
            confidence = ScoreConfidence.MEDIUM
            confidence_fa = 'متوسط'
        elif completed_count < t_high:
            confidence = ScoreConfidence.HIGH
            confidence_fa = 'بالا'
        else:
            confidence = ScoreConfidence.VERY_HIGH
            confidence_fa = 'بسیار بالا'

        # ۲. محاسبه امتیازات ابعاد ۶ گانه (0 تا 100)
        # بعد ۱: دقت وزنی (Weight Accuracy)
        disc_rate = discrepancy['discrepancy_rate']
        avg_abs_disc = discrepancy['average_absolute_discrepancy_kg']
        crit_alerts = monitoring['critical_alerts']

        # امتیاز پایه دقت
        acc_score = 100.0 - (disc_rate * 0.8) - min(avg_abs_disc * 0.1, 20.0) - (crit_alerts * 5.0)
        acc_score = max(0.0, min(100.0, acc_score))

        # بعد ۲: عملکرد افت (Loss Performance - Product Normalized)
        # اگر نسبت افت کمتر یا مساوی ۱ باشد (یعنی بهتر از بیس‌لاین)، امتیاز ۹۰ تا ۱۰۰
        if prod_normalized_loss_ratio <= 1.0:
            loss_score = 90.0 + (1.0 - prod_normalized_loss_ratio) * 10.0
        else:
            loss_score = max(20.0, 90.0 - (prod_normalized_loss_ratio - 1.0) * 35.0)
        # جریمه هشدارهای افت
        loss_anom_alerts = monitoring['breakdown_by_type'].get('LOSS_ANOMALY', 0)
        loss_score = max(0.0, min(100.0, loss_score - (loss_anom_alerts * 4.0)))

        # بعد ۳: ثبات عملکرد (Consistency)
        if consistency['is_sufficient_sample'] and consistency['weight_variation_coef'] is not None:
            cv = consistency['weight_variation_coef']
            if cv < 0.15:
                cons_score = 95.0
            elif cv < 0.25:
                cons_score = 85.0
            elif cv < 0.40:
                cons_score = 70.0
            elif cv < 0.60:
                cons_score = 55.0
            else:
                cons_score = 40.0
        else:
            cons_score = 70.0  # مقدار خنثی در صورت نبود سابقه کافی

        # بعد ۴: کیفیت پایش و هشدارها (Monitoring Quality)
        alert_rate = monitoring['alerts_per_100_tickets']
        high_crit = monitoring['high_alerts'] * 8.0 + monitoring['critical_alerts'] * 15.0
        mon_score = 100.0 - (alert_rate * 3.0) - (high_crit) - (corrections['weight_correction_count'] * 5.0)
        mon_score = max(0.0, min(100.0, mon_score))

        # بعد ۵: بهره‌وری عملیاتی و معطلی (Operational Efficiency)
        avg_turnaround = turnaround['average_turnaround_minutes']
        long_wait_rate = turnaround['long_waiting_rate']
        if avg_turnaround <= 0:
            eff_score = 80.0
        elif avg_turnaround <= 45.0:
            eff_score = 95.0
        elif avg_turnaround <= 75.0:
            eff_score = 85.0
        elif avg_turnaround <= 120.0:
            eff_score = 70.0
        else:
            eff_score = 50.0
        eff_score = max(0.0, min(100.0, eff_score - (long_wait_rate * 0.5)))

        # بعد ۶: قابلیت اعتماد به داده (Data Reliability)
        if completed_count < 10:
            rel_score = 30.0
        elif completed_count < 30:
            rel_score = 60.0
        elif completed_count < 100:
            rel_score = 80.0
        elif completed_count < 300:
            rel_score = 95.0
        else:
            rel_score = 100.0
        # جریمه نقص داده مبدا
        rel_score = max(10.0, rel_score - (discrepancy['missing_sent_weight_rate'] * 0.3))

        dimension_scores = {
            'weight_accuracy': round(acc_score, 1),
            'loss_performance': round(loss_score, 1),
            'consistency': round(cons_score, 1),
            'monitoring_quality': round(mon_score, 1),
            'operational_efficiency': round(eff_score, 1),
            'data_reliability': round(rel_score, 1),
        }

        # ۳. فرمول وزنی امتیاز نهایی
        weights = config.dimension_weights or {}
        w_acc = float(weights.get('weight_accuracy', 30))
        w_loss = float(weights.get('loss_performance', 20))
        w_cons = float(weights.get('consistency', 15))
        w_mon = float(weights.get('monitoring_quality', 20))
        w_eff = float(weights.get('operational_efficiency', 10))
        w_rel = float(weights.get('data_reliability', 5))
        total_w = w_acc + w_loss + w_cons + w_mon + w_eff + w_rel
        if total_w <= 0:
            total_w = 100.0

        raw_score = (
            acc_score * w_acc +
            loss_score * w_loss +
            cons_score * w_cons +
            mon_score * w_mon +
            eff_score * w_eff +
            rel_score * w_rel
        ) / total_w
        raw_score = round(raw_score, 1)

        # ۴. سطوح کیفی
        thresholds = config.score_thresholds or {}
        t_exc = thresholds.get('excellent', 90)
        t_good = thresholds.get('good', 75)
        t_acc = thresholds.get('acceptable', 60)
        t_attn = thresholds.get('needs_attention', 40)

        if raw_score >= t_exc:
            level = ScoreLevel.EXCELLENT
            level_fa = 'عالی'
        elif raw_score >= t_good:
            level = ScoreLevel.GOOD
            level_fa = 'خوب'
        elif raw_score >= t_acc:
            level = ScoreLevel.ACCEPTABLE
            level_fa = 'قابل قبول'
        elif raw_score >= t_attn:
            level = ScoreLevel.NEEDS_ATTENTION
            level_fa = 'نیازمند بررسی'
        else:
            level = ScoreLevel.HIGH_RISK
            level_fa = 'پرریسک'

        # ۵. تولید دلایل تحلیلی شفاف (Explainability)
        positives = []
        attentions = []

        if discrepancy['average_absolute_discrepancy_kg'] < 30.0 and discrepancy['tickets_with_sent_weight'] > 0:
            positives.append(f"میانگین اختلاف با وزن ارسالی فقط {discrepancy['average_absolute_discrepancy_kg']} کیلوگرم است.")
        if discrepancy['discrepancy_rate'] < 3.0 and discrepancy['tickets_with_sent_weight'] > 0:
            positives.append(f"نرخ مغایرت وزنی فراتر از حد مجاز بسیار پایین ({discrepancy['discrepancy_rate']}٪) است.")
        if prod_normalized_loss_ratio <= 1.0 and loss['tickets_with_loss'] > 0:
            positives.append("میانگین درصد افت محموله‌ها در محدوده استاندارد کالا قرار دارد.")
        if monitoring['critical_alerts'] == 0:
            positives.append("فاقد هرگونه هشدار پایش بحرانی (Critical Alert) در این بازه.")
        if turnaround['average_turnaround_minutes'] > 0 and turnaround['average_turnaround_minutes'] <= 50.0:
            positives.append(f"سرعت مطلوب در تخلیه و بارگیری (متوسط زمان توقف {turnaround['average_turnaround_minutes']} دقیقه).")
        if consistency['is_sufficient_sample'] and consistency['weight_variation_coef'] and consistency['weight_variation_coef'] < 0.2:
            positives.append("ثبات وزنی بالا در محموله‌های ارسالی طرف‌حساب.")

        if discrepancy['discrepancy_rate'] >= 8.0:
            attentions.append(f"نرخ بالای مغایرت وزن ارسالی ({discrepancy['discrepancy_rate']}٪ قبوض دارای مغایرت).")
        if monitoring['critical_alerts'] > 0:
            attentions.append(f"ثبت {monitoring['critical_alerts']} مورد هشدار بحرانی پایش هوشمند در دوره بررسی.")
        if monitoring['high_alerts'] >= 3:
            attentions.append(f"ثبت {monitoring['high_alerts']} مورد هشدار با اولویت بالا (High) در دوره بررسی.")
        if prod_normalized_loss_ratio > 1.3:
            attentions.append(f"میانگین افت ثبت‌شده ۳۰٪ بالاتر از افت پیش‌فرض و استاندارد کالا است.")
        if turnaround['average_turnaround_minutes'] > 90.0:
            attentions.append(f"متوسط زمان توقف خودروها بالا ({turnaround['average_turnaround_minutes']} دقیقه) ارزیابی شده است.")
        if corrections['weight_correction_count'] > 0:
            attentions.append(f"ثبت {corrections['weight_correction_count']} مورد اصلاح دستی اوزان در قبوض متعلق به این طرف‌حساب.")

        if not positives:
            positives.append("عملکرد کلی در حدود معمول شاخص‌های صنعتی ثبت شده است.")
        if not attentions:
            attentions.append("هیچ انحراف بااهمیتی در شاخص‌های این طرف‌حساب مشاهده نشد.")

        explanation = {
            'positive_points': positives,
            'attention_points': attentions,
        }

        # در صورت نبود سابقه کافی (<10)، امتیاز گمراه‌کننده محاسبه نمی‌شود
        overall_score = raw_score if confidence != ScoreConfidence.INSUFFICIENT else None

        return {
            'overall_score': overall_score,
            'raw_score': raw_score,
            'level': level,
            'level_fa': level_fa,
            'confidence': confidence,
            'confidence_fa': confidence_fa,
            'is_score_reliable': confidence != ScoreConfidence.INSUFFICIENT,
            'dimension_scores': dimension_scores,
            'dimension_weights': weights,
            'calculation_version': config.calculation_version,
            'explanation': explanation,
        }

    @classmethod
    def analyze_party(cls, party, start_date=None, end_date=None, product=None, operation_type=None, config=None):
        """
        آنالیز کامل عملکرد یک طرف‌حساب به همراه ابعاد ۶ گانه و شاخص‌ها.
        """
        qs = cls.get_filtered_ticket_queryset(party, start_date, end_date, product, operation_type)
        completed_qs = qs.filter(status=TicketStatus.COMPLETED)

        profile = cls.calculate_party_profile(party, qs)
        discrepancy = cls.calculate_discrepancy_metrics(completed_qs)
        loss = cls.calculate_loss_metrics(completed_qs)
        monitoring = cls.calculate_monitoring_metrics(party, qs)
        turnaround = cls.calculate_turnaround_metrics(completed_qs)
        corrections = cls.calculate_correction_metrics(qs)
        consistency = cls.calculate_consistency_metrics(completed_qs)
        prod_norm_loss_ratio = cls.calculate_product_normalized_loss(party, completed_qs)

        score_res = cls.evaluate_score_and_dimensions(
            party=party,
            profile=profile,
            discrepancy=discrepancy,
            loss=loss,
            monitoring=monitoring,
            turnaround=turnaround,
            corrections=corrections,
            consistency=consistency,
            prod_normalized_loss_ratio=prod_norm_loss_ratio,
            config=config
        )

        return {
            'party': {
                'id': party.id,
                'name': party.name,
                'code': party.code,
                'party_type': party.party_type,
                'party_type_fa': party.get_party_type_display(),
            },
            'profile': profile,
            'discrepancy_metrics': discrepancy,
            'loss_metrics': loss,
            'monitoring_metrics': monitoring,
            'turnaround_metrics': turnaround,
            'correction_metrics': corrections,
            'consistency_metrics': consistency,
            'score': score_res,
        }

    @classmethod
    def calculate_trend_analysis(cls, party, quick_period='this_month', start_date=None, end_date=None, product=None):
        """
        مقایسه عملکرد دوره جاری با دوره متناظر قبلی و تعیین روند (IMPROVING / STABLE / WORSENING).
        """
        config = PartyScoringConfig.get_config()
        trend_thresh = float(config.trend_threshold)

        if quick_period and quick_period != 'custom':
            curr_start, curr_end = get_jalali_range_gregorian(quick_period)
            prev_start, prev_end = get_comparison_period_gregorian(curr_start, curr_end, quick_period)
        elif start_date and end_date:
            curr_start, curr_end = start_date, end_date
            prev_start, prev_end = get_comparison_period_gregorian(curr_start, curr_end, 'custom')
        else:
            curr_start, curr_end = get_jalali_range_gregorian('this_month')
            prev_start, prev_end = get_comparison_period_gregorian(curr_start, curr_end, 'this_month')

        curr_analysis = cls.analyze_party(party, curr_start, curr_end, product=product, config=config)
        prev_analysis = cls.analyze_party(party, prev_start, prev_end, product=product, config=config)

        def calc_delta(curr_val, prev_val, is_lower_better=False):
            if curr_val is None or prev_val is None:
                return {
                    'current': curr_val,
                    'previous': prev_val,
                    'delta_abs': None,
                    'delta_percent': None,
                    'direction': TrendDirection.INSUFFICIENT_DATA,
                }
            c = float(curr_val)
            p = float(prev_val)
            d_abs = round(c - p, 2)
            d_pct = round(((c - p) / p * 100.0), 1) if p != 0 else (100.0 if c > 0 else 0.0)

            if abs(d_pct) < trend_thresh:
                direction = TrendDirection.STABLE
            elif is_lower_better:
                direction = TrendDirection.IMPROVING if d_pct < 0 else TrendDirection.WORSENING
            else:
                direction = TrendDirection.IMPROVING if d_pct > 0 else TrendDirection.WORSENING

            return {
                'current': c,
                'previous': p,
                'delta_abs': d_abs,
                'delta_percent': d_pct,
                'direction': direction,
            }

        curr_score = curr_analysis['score']['overall_score']
        prev_score = prev_analysis['score']['overall_score']

        return {
            'period': {
                'current_start': curr_start.isoformat(),
                'current_end': curr_end.isoformat(),
                'current_start_fa': format_jalali_date(curr_start),
                'current_end_fa': format_jalali_date(curr_end),
                'previous_start': prev_start.isoformat(),
                'previous_end': prev_end.isoformat(),
                'previous_start_fa': format_jalali_date(prev_start),
                'previous_end_fa': format_jalali_date(prev_end),
            },
            'kpi_comparison': {
                'score': calc_delta(curr_score, prev_score, is_lower_better=False),
                'net_tonnage': calc_delta(
                    curr_analysis['profile']['total_net_weight_ton'],
                    prev_analysis['profile']['total_net_weight_ton'],
                    is_lower_better=False
                ),
                'average_discrepancy_kg': calc_delta(
                    curr_analysis['discrepancy_metrics']['average_absolute_discrepancy_kg'],
                    prev_analysis['discrepancy_metrics']['average_absolute_discrepancy_kg'],
                    is_lower_better=True
                ),
                'average_loss_percent': calc_delta(
                    curr_analysis['loss_metrics']['average_loss_percent'],
                    prev_analysis['loss_metrics']['average_loss_percent'],
                    is_lower_better=True
                ),
                'alert_rate': calc_delta(
                    curr_analysis['monitoring_metrics']['alerts_per_100_tickets'],
                    prev_analysis['monitoring_metrics']['alerts_per_100_tickets'],
                    is_lower_better=True
                ),
                'turnaround_minutes': calc_delta(
                    curr_analysis['turnaround_metrics']['average_turnaround_minutes'],
                    prev_analysis['turnaround_metrics']['average_turnaround_minutes'],
                    is_lower_better=True
                ),
            },
            'current_analysis': curr_analysis,
            'previous_analysis': prev_analysis,
        }

    @classmethod
    def get_party_ranking(cls, start_date=None, end_date=None, party_type=None, product=None, minimum_tickets=None, ordering='overall_score'):
        """
        تولید لیست رتبه‌بندی طرف‌حساب‌ها با اعمال حداقل سابقه آماری جهت برقراری عدالت در رتبه‌بندی.
        """
        config = PartyScoringConfig.get_config()
        min_tickets = minimum_tickets if minimum_tickets is not None else config.minimum_tickets_for_ranking

        parties_qs = Party.objects.filter(is_active=True)
        if party_type:
            parties_qs = parties_qs.filter(party_type=party_type)

        ranked_items = []

        for party in parties_qs:
            analysis = cls.analyze_party(party, start_date, end_date, product=product, config=config)
            completed_count = analysis['profile']['completed_tickets']
            
            # شرط حداقل قبوض برای ورود به جدول رتبه‌بندی
            if completed_count < min_tickets:
                continue

            score_data = analysis['score']
            dims = score_data['dimension_scores']

            ranked_items.append({
                'party_id': party.id,
                'party_name': party.name,
                'party_code': party.code,
                'party_type': party.party_type,
                'party_type_fa': party.get_party_type_display(),
                'overall_score': score_data['overall_score'] or 0.0,
                'score_level': score_data['level'],
                'score_level_fa': score_data['level_fa'],
                'confidence': score_data['confidence'],
                'confidence_fa': score_data['confidence_fa'],
                'completed_tickets': completed_count,
                'total_tonnage': analysis['profile']['total_net_weight_ton'],
                'avg_discrepancy_kg': analysis['discrepancy_metrics']['average_absolute_discrepancy_kg'],
                'avg_loss_percent': analysis['loss_metrics']['average_loss_percent'],
                'alert_rate': analysis['monitoring_metrics']['alerts_per_100_tickets'],
                'avg_turnaround_min': analysis['turnaround_metrics']['average_turnaround_minutes'],
                'weight_accuracy_score': dims['weight_accuracy'],
                'loss_performance_score': dims['loss_performance'],
                'consistency_score': dims['consistency'],
                'monitoring_quality_score': dims['monitoring_quality'],
                'operational_efficiency_score': dims['operational_efficiency'],
                'data_reliability_score': dims['data_reliability'],
                'explanation': score_data['explanation'],
            })

        # مرتب‌سازی
        reverse_sort = True
        sort_key = 'overall_score'
        
        if ordering == 'overall_score' or ordering == '-overall_score':
            sort_key = 'overall_score'
            reverse_sort = not ordering.startswith('-') if ordering == '-overall_score' else True
        elif ordering in ['weight_accuracy', '-weight_accuracy']:
            sort_key = 'weight_accuracy_score'
            reverse_sort = not ordering.startswith('-')
        elif ordering in ['loss_performance', '-loss_performance']:
            sort_key = 'loss_performance_score'
            reverse_sort = not ordering.startswith('-')
        elif ordering in ['total_net_weight', 'total_tonnage']:
            sort_key = 'total_tonnage'
            reverse_sort = True
        elif ordering in ['alert_rate', '-alert_rate']:
            sort_key = 'alert_rate'
            reverse_sort = ordering.startswith('-')  # پیش‌فرض alert_rate کمتر بهتر است
        elif ordering in ['average_discrepancy', 'avg_discrepancy_kg']:
            sort_key = 'avg_discrepancy_kg'
            reverse_sort = False
        elif ordering in ['average_turnaround', 'avg_turnaround_min']:
            sort_key = 'avg_turnaround_min'
            reverse_sort = False

        ranked_items.sort(key=lambda x: x.get(sort_key, 0.0), reverse=reverse_sort)

        # افزودن رتبه (Rank) و محاسبه صدک (Percentile)
        total_ranked = len(ranked_items)
        for idx, item in enumerate(ranked_items, 1):
            item['rank'] = idx
            if total_ranked > 1:
                item['percentile'] = round(((total_ranked - idx) / (total_ranked - 1)) * 100.0, 1)
            else:
                item['percentile'] = 100.0

        return ranked_items

    @classmethod
    def compare_parties(cls, party_ids: List[int], start_date=None, end_date=None, product=None):
        """
        مقایسه همزمان ۲ تا ۴ طرف‌حساب به تفکیک ابعاد و شاخص‌های کلیدی، همراه با فیلتر کالایی.
        """
        config = PartyScoringConfig.get_config()
        parties = Party.objects.filter(id__in=party_ids)
        comparison_results = []

        for p in parties:
            analysis = cls.analyze_party(p, start_date, end_date, product=product, config=config)
            comparison_results.append({
                'party_id': p.id,
                'party_name': p.name,
                'party_type': p.party_type,
                'party_type_fa': p.get_party_type_display(),
                'score': analysis['score'],
                'volume': {
                    'completed_tickets': analysis['profile']['completed_tickets'],
                    'net_tonnage': analysis['profile']['total_net_weight_ton'],
                    'active_days': analysis['profile']['active_days'],
                },
                'discrepancy': {
                    'avg_abs_discrepancy_kg': analysis['discrepancy_metrics']['average_absolute_discrepancy_kg'],
                    'discrepancy_rate': analysis['discrepancy_metrics']['discrepancy_rate'],
                },
                'loss': {
                    'avg_loss_percent': analysis['loss_metrics']['average_loss_percent'],
                    'tickets_with_loss': analysis['loss_metrics']['tickets_with_loss'],
                },
                'monitoring': {
                    'total_alerts': analysis['monitoring_metrics']['total_alerts'],
                    'critical_alerts': analysis['monitoring_metrics']['critical_alerts'],
                    'alerts_per_100': analysis['monitoring_metrics']['alerts_per_100_tickets'],
                },
                'turnaround': {
                    'avg_minutes': analysis['turnaround_metrics']['average_turnaround_minutes'],
                    'long_wait_rate': analysis['turnaround_metrics']['long_waiting_rate'],
                }
            })

        return {
            'parties_count': len(comparison_results),
            'product_context': product.name if product else 'همه کالاها',
            'comparison': comparison_results
        }
