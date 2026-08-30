from decimal import Decimal
from monitoring.models import AlertType, AlertSeverity, AlertConfidence, MonitoringRuleConfig
from monitoring.selectors.monitoring_queries import get_vehicle_tare_stats


class VehicleTareAnalysisService:
    """
    Rule 1: Vehicle Tare Weight Anomaly Analysis.
    Compares current tare weight against historical baseline and std dev for the vehicle.
    """
    @classmethod
    def analyze(cls, ticket, config: MonitoringRuleConfig | None = None) -> dict | None:
        if not config:
            config = MonitoringRuleConfig.get_rule_config(AlertType.VEHICLE_TARE_ANOMALY)
        
        if not config.enabled:
            return None

        current_tare = ticket.tare_weight
        if not current_tare or current_tare <= Decimal("0"):
            return None

        # Gather historical statistics
        stats = get_vehicle_tare_stats(
            vehicle_id=ticket.vehicle_id,
            plate=ticket.license_plate_display,
            exclude_ticket_id=ticket.id
        )

        sample_size = stats["count"]
        min_history = config.minimum_history or 10

        # Avoid false positives if insufficient history
        if sample_size < min_history:
            return None

        avg_tare = stats["avg"]
        if avg_tare <= Decimal("0"):
            return None

        diff = current_tare - avg_tare
        abs_diff = abs(diff)
        diff_percent = Decimal(str(round(float((abs_diff / avg_tare) * Decimal("100")), 2)))

        std_dev = stats["std_dev"]
        z_score = float(abs_diff / std_dev) if std_dev > Decimal("0") else 0.0

        # Evaluation against thresholds
        is_warning_kg = abs_diff >= config.warning_threshold
        is_warning_pct = diff_percent >= config.percentage_warning
        is_std_exceeded = z_score >= 2.0

        if not (is_warning_kg or is_warning_pct or is_std_exceeded):
            return None

        # Determine Severity
        if abs_diff >= config.critical_threshold or diff_percent >= config.percentage_critical:
            severity = AlertSeverity.CRITICAL
        elif abs_diff >= config.high_threshold or diff_percent >= config.percentage_high:
            severity = AlertSeverity.HIGH
        elif is_warning_kg or is_warning_pct:
            severity = AlertSeverity.MEDIUM
        else:
            severity = AlertSeverity.LOW

        # Confidence rating
        if sample_size >= 50:
            confidence = AlertConfidence.HIGH
        elif sample_size >= 20:
            confidence = AlertConfidence.MEDIUM
        else:
            confidence = AlertConfidence.LOW

        direction_word = "بیشتر" if diff > 0 else "کمتر"
        plate_str = ticket.license_plate_display or "خودرو"

        reason = (
            f"وزن خالی فعلی این خودرو ({plate_str}) {current_tare:,.0f} کیلوگرم است. "
            f"میانگین وزن خالی این خودرو در {sample_size} سرویس قبلی {avg_tare:,.0f} کیلوگرم بوده است. "
            f"وزن فعلی {abs_diff:,.0f} کیلوگرم معادل {diff_percent:.2f} درصد {direction_word} از میانگین تاریخی است."
        )

        title = f"وزن خالی غیرعادی خودرو ({abs_diff:,.0f} کیلوگرم انحراف)"
        description = f"انحراف {diff_percent}% نسبت به میانگین {sample_size} سرویس قبلی ({avg_tare:,.0f} Kg)"

        metadata = {
            "sample_size": sample_size,
            "historical_average": float(avg_tare),
            "median": float(stats["median"]),
            "std_dev": float(std_dev),
            "min": float(stats["min"]),
            "max": float(stats["max"]),
            "last_5_avg": float(stats["last_5_avg"]),
            "last_10_avg": float(stats["last_10_avg"]),
            "difference_kg": float(diff),
            "difference_percent": float(diff_percent),
            "z_score": round(z_score, 2),
            "recent_ticket_ids": [t.id for t in stats["recent_records"]],
        }

        return {
            "alert_type": AlertType.VEHICLE_TARE_ANOMALY,
            "severity": severity,
            "title": title,
            "description": description,
            "reason": reason,
            "current_value": current_tare,
            "baseline_value": avg_tare,
            "deviation_value": diff,
            "deviation_percent": diff_percent,
            "sample_size": sample_size,
            "confidence": confidence,
            "metadata": metadata,
        }
