from decimal import Decimal
from monitoring.models import AlertType, AlertSeverity, AlertConfidence, MonitoringRuleConfig
from monitoring.selectors.monitoring_queries import get_ticket_turnaround_minutes, get_waiting_time_stats
from weighbridge.models import TicketStatus


class WaitingTimeAnalysisService:
    """
    Rule 5: Turnaround & Waiting Time Anomaly Analysis.
    Analyzes duration between first and second weights, or elapsed time in yard for open tickets.
    """
    @classmethod
    def analyze(cls, ticket, config: MonitoringRuleConfig | None = None) -> dict | None:
        if not config:
            config = MonitoringRuleConfig.get_rule_config(AlertType.LONG_WAITING_TIME)

        if not config.enabled:
            return None

        if ticket.status == TicketStatus.CANCELLED:
            return None

        duration_mins = get_ticket_turnaround_minutes(ticket)
        if duration_mins is None or duration_mins <= 0:
            return None

        duration_dec = Decimal(str(duration_mins))

        # Baseline statistics
        stats = get_waiting_time_stats(
            product_id=ticket.product_id,
            unload_location_id=ticket.unload_location_id,
            party_id=ticket.party_id,
            exclude_ticket_id=ticket.id
        )

        avg_mins = stats["avg_minutes"]
        diff_mins = duration_dec - avg_mins
        abs_diff_mins = abs(diff_mins)
        diff_percent = Decimal(str(round(float((abs_diff_mins / avg_mins) * Decimal("100")), 2))) if avg_mins > Decimal("0") else Decimal("0.00")

        # Thresholds in minutes
        is_warning = duration_dec >= config.warning_threshold
        is_pct_exceeded = diff_percent >= config.percentage_warning and duration_dec >= Decimal("60.00")

        if not (is_warning or is_pct_exceeded):
            return None

        # Severity
        if duration_dec >= config.critical_threshold or diff_percent >= config.percentage_critical:
            severity = AlertSeverity.CRITICAL
        elif duration_dec >= config.high_threshold or diff_percent >= config.percentage_high:
            severity = AlertSeverity.HIGH
        elif is_warning or is_pct_exceeded:
            severity = AlertSeverity.MEDIUM
        else:
            severity = AlertSeverity.LOW

        sample_size = stats["count"]
        if sample_size >= 30:
            confidence = AlertConfidence.HIGH
        elif sample_size >= 10:
            confidence = AlertConfidence.MEDIUM
        elif sample_size >= 5:
            confidence = AlertConfidence.LOW
        else:
            confidence = AlertConfidence.INSUFFICIENT

        level_fa = stats.get("level_fa", "عملیات مشابه")
        is_in_yard = ticket.status in [TicketStatus.WAITING_SECOND, TicketStatus.FIRST_REGISTERED, TicketStatus.WAITING_FIRST]
        status_text = "در مجموعه متوقف بوده و هنوز خارج نشده است" if is_in_yard else "در مجموعه متوقف بوده است"

        hours = int(duration_mins // 60)
        rem_mins = int(duration_mins % 60)
        time_str = f"{hours} ساعت و {rem_mins} دقیقه" if hours > 0 else f"{int(duration_mins)} دقیقه"

        reason = (
            f"این خودرو {time_str} ({int(duration_mins)} دقیقه) {status_text}، "
            f"در حالی که میانگین زمان توقف برای {level_fa} {avg_mins:,.0f} دقیقه "
            f"(بر اساس {sample_size} سابقه قبلی) می‌باشد."
        )

        title = f"توقف و معطلی طولانی خودرو ({time_str})"
        description = f"مدت توقف: {int(duration_mins)} دقیقه | میانگین مبنا: {avg_mins:,.0f} دقیقه ({level_fa})"

        metadata = {
            "duration_minutes": float(duration_mins),
            "historical_avg_minutes": float(avg_mins),
            "difference_minutes": float(diff_mins),
            "difference_percent": float(diff_percent),
            "sample_size": sample_size,
            "baseline_level": stats.get("level"),
            "is_in_yard": is_in_yard,
        }

        return {
            "alert_type": AlertType.LONG_WAITING_TIME,
            "severity": severity,
            "title": title,
            "description": description,
            "reason": reason,
            "current_value": duration_dec,
            "baseline_value": avg_mins,
            "deviation_value": diff_mins,
            "deviation_percent": diff_percent,
            "sample_size": sample_size,
            "confidence": confidence,
            "metadata": metadata,
        }
