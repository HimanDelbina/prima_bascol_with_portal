from decimal import Decimal
from monitoring.models import AlertType, AlertSeverity, AlertConfidence, MonitoringRuleConfig
from monitoring.selectors.monitoring_queries import get_net_weight_stats


class NetWeightAnalysisService:
    """
    Rule 4: Net Weight Hierarchical Anomaly Analysis.
    Compares scale net weight against hierarchical baseline:
    1. Vehicle + Product
    2. Vehicle
    3. Product
    4. Global
    """
    @classmethod
    def analyze(cls, ticket, config: MonitoringRuleConfig | None = None) -> dict | None:
        if not config:
            config = MonitoringRuleConfig.get_rule_config(AlertType.NET_WEIGHT_ANOMALY)

        if not config.enabled:
            return None

        current_net = ticket.net_weight
        if not current_net or current_net <= Decimal("0"):
            return None

        min_history = config.minimum_history or 10

        stats = get_net_weight_stats(
            vehicle_id=ticket.vehicle_id,
            plate=ticket.license_plate_display,
            product_id=ticket.product_id,
            exclude_ticket_id=ticket.id,
            min_history=min_history
        )

        sample_size = stats["count"]
        if sample_size < min_history:
            return None

        avg_net = stats["avg_net"]
        if avg_net <= Decimal("0"):
            return None

        diff = current_net - avg_net
        abs_diff = abs(diff)
        diff_percent = Decimal(str(round(float((abs_diff / avg_net) * Decimal("100")), 2)))

        std_net = stats["std_dev_net"]
        z_score = float(abs_diff / std_net) if std_net > Decimal("0") else 0.0

        # Check conditions
        is_warning_kg = abs_diff >= config.warning_threshold
        is_warning_pct = diff_percent >= config.percentage_warning
        is_std_exceeded = z_score >= 2.5

        if not (is_warning_kg or is_warning_pct or is_std_exceeded):
            return None

        # Severity
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

        level_fa = stats["level_fa"]
        direction_word = "بیشتر" if diff > 0 else "کمتر"

        reason = (
            f"وزن خالص این قبض ({current_net:,.0f} کیلوگرم) با میانگین تاریخی بر مبنای «{level_fa}» "
            f"({avg_net:,.0f} کیلوگرم بر اساس {sample_size} سرویس قبلی) "
            f"به میزان {abs_diff:,.0f} کیلوگرم معادل {diff_percent:.2f} درصد {direction_word} است."
        )

        title = f"وزن خالص غیرعادی محموله ({abs_diff:,.0f} کیلوگرم انحراف)"
        description = f"وزن خالص فعلی: {current_net:,.0f} Kg | میانگین {level_fa}: {avg_net:,.0f} Kg ({sample_size} سابقه)"

        metadata = {
            "current_net_weight": float(current_net),
            "historical_avg_net_weight": float(avg_net),
            "std_dev_net": float(std_net),
            "sample_size": sample_size,
            "baseline_level": stats["level"],
            "difference_kg": float(diff),
            "difference_percent": float(diff_percent),
            "z_score": round(z_score, 2),
        }

        return {
            "alert_type": AlertType.NET_WEIGHT_ANOMALY,
            "severity": severity,
            "title": title,
            "description": description,
            "reason": reason,
            "current_value": current_net,
            "baseline_value": avg_net,
            "deviation_value": diff,
            "deviation_percent": diff_percent,
            "sample_size": sample_size,
            "confidence": confidence,
            "metadata": metadata,
        }
