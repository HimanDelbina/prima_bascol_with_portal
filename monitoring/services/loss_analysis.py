from decimal import Decimal
from monitoring.models import AlertType, AlertSeverity, AlertConfidence, MonitoringRuleConfig
from monitoring.selectors.monitoring_queries import get_loss_stats


class LossAnomalyAnalysisService:
    """
    Rule 3: Cargo Loss & Waste Anomaly Analysis.
    Compares current loss percentage against historical baseline for Product / Party.
    """
    @classmethod
    def analyze(cls, ticket, config: MonitoringRuleConfig | None = None) -> dict | None:
        if not config:
            config = MonitoringRuleConfig.get_rule_config(AlertType.LOSS_ANOMALY)

        if not config.enabled:
            return None

        current_loss = ticket.loss_percent
        if current_loss is None:
            return None

        # Fetch stats for Product / Party
        stats = get_loss_stats(
            product_id=ticket.product_id,
            party_id=ticket.party_id,
            exclude_ticket_id=ticket.id
        )

        sample_size = stats["count"]
        min_history = config.minimum_history or 10

        if sample_size < min_history and not ticket.is_loss_overridden:
            return None

        avg_loss = stats["avg_loss_pct"]
        std_loss = stats["std_dev_loss"]

        diff = current_loss - avg_loss
        abs_diff = abs(diff)
        diff_percent = Decimal(str(round(float((abs_diff / avg_loss) * Decimal("100")), 2))) if avg_loss > Decimal("0") else Decimal("0.00")

        # Check conditions
        is_warning_pct = abs_diff >= config.warning_threshold
        is_std_exceeded = (float(abs_diff / std_loss) >= 2.0) if std_loss > Decimal("0") else False
        is_override_anomaly = ticket.is_loss_overridden and abs_diff >= Decimal("0.50")

        if not (is_warning_pct or is_std_exceeded or is_override_anomaly):
            return None

        # Severity
        if abs_diff >= config.critical_threshold or diff_percent >= config.percentage_critical:
            severity = AlertSeverity.CRITICAL
        elif abs_diff >= config.high_threshold or diff_percent >= config.percentage_high:
            severity = AlertSeverity.HIGH
        elif is_warning_pct or is_override_anomaly:
            severity = AlertSeverity.MEDIUM
        else:
            severity = AlertSeverity.LOW

        # Confidence rating
        if sample_size >= 50:
            confidence = AlertConfidence.HIGH
        elif sample_size >= 20:
            confidence = AlertConfidence.MEDIUM
        elif sample_size >= 10:
            confidence = AlertConfidence.LOW
        else:
            confidence = AlertConfidence.INSUFFICIENT

        prod_name = ticket.product.name if ticket.product else "محصول"
        level_fa = stats.get("level_fa", "محصول")

        reason = (
            f"افت فعلی این محموله {current_loss:.2f} درصد است، در حالی که میانگین افت {level_fa} ({prod_name}) "
            f"در {sample_size} محموله قبلی {avg_loss:.2f} درصد بوده است."
        )

        if ticket.is_loss_overridden:
            override_reason = f" (دلیل ثبت‌شده: {ticket.loss_override_reason})" if ticket.loss_override_reason else ""
            reason += f" همچنین افت به صورت دستی اورراید شده است{override_reason}."

        title = f"افت غیرعادی محموله ({current_loss:.2f}% در برابر میانگین {avg_loss:.2f}%)"
        description = f"انحراف افت: {diff:+.2f}% | میانگین مبنا: {avg_loss:.2f}% ({sample_size} سابقه)"

        metadata = {
            "current_loss_percent": float(current_loss),
            "historical_avg_loss_percent": float(avg_loss),
            "std_dev_loss": float(std_loss),
            "sample_size": sample_size,
            "baseline_level": stats.get("level"),
            "is_loss_overridden": ticket.is_loss_overridden,
            "loss_override_reason": ticket.loss_override_reason,
            "loss_weight_kg": float(ticket.loss_weight or 0),
        }

        return {
            "alert_type": AlertType.LOSS_ANOMALY,
            "severity": severity,
            "title": title,
            "description": description,
            "reason": reason,
            "current_value": current_loss,
            "baseline_value": avg_loss,
            "deviation_value": diff,
            "deviation_percent": diff_percent,
            "sample_size": sample_size,
            "confidence": confidence,
            "metadata": metadata,
        }
