from decimal import Decimal
from monitoring.models import AlertType, AlertSeverity, AlertConfidence, MonitoringRuleConfig
from monitoring.selectors.monitoring_queries import get_party_discrepancy_stats


class WeightDiscrepancyAnalysisService:
    """
    Rule 2: Weight Discrepancy & Historical Party Discrepancy Analysis.
    Compares scale net weight with waybill sent weight and checks supplier/customer historical pattern.
    """
    @classmethod
    def analyze(cls, ticket, config: MonitoringRuleConfig | None = None) -> dict | None:
        if not config:
            config = MonitoringRuleConfig.get_rule_config(AlertType.WEIGHT_DISCREPANCY)

        if not config.enabled:
            return None

        sent_weight = ticket.sent_weight
        net_weight = ticket.net_weight

        if not sent_weight or sent_weight <= Decimal("0") or not net_weight or net_weight <= Decimal("0"):
            return None

        diff = net_weight - sent_weight
        abs_diff = abs(diff)
        diff_percent = Decimal(str(round(float((abs_diff / sent_weight) * Decimal("100")), 2)))

        # Fixed thresholds check
        is_warning_kg = abs_diff >= config.warning_threshold
        is_warning_pct = diff_percent >= config.percentage_warning

        # Historical Party analysis
        party_stats = get_party_discrepancy_stats(
            party_id=ticket.party_id,
            exclude_ticket_id=ticket.id
        )
        party_sample = party_stats["count"]
        party_avg_diff = party_stats["avg_diff"]
        party_std_diff = party_stats["std_dev_diff"]

        is_party_anomaly = False
        if party_sample >= config.minimum_history:
            if party_std_diff > 0:
                z = float(abs(abs_diff - abs(party_avg_diff)) / party_std_diff)
                if z >= 2.0:
                    is_party_anomaly = True
            elif abs_diff > abs(party_avg_diff) * Decimal("2.0") and abs_diff > config.warning_threshold:
                is_party_anomaly = True

        if not (is_warning_kg or is_warning_pct or is_party_anomaly):
            return None

        # Determine Severity
        if abs_diff >= config.critical_threshold or diff_percent >= config.percentage_critical:
            severity = AlertSeverity.CRITICAL
        elif abs_diff >= config.high_threshold or diff_percent >= config.percentage_high:
            severity = AlertSeverity.HIGH
        elif is_warning_kg or is_warning_pct or is_party_anomaly:
            severity = AlertSeverity.MEDIUM
        else:
            severity = AlertSeverity.LOW

        # Confidence rating
        if party_sample >= 50:
            confidence = AlertConfidence.HIGH
        elif party_sample >= 20:
            confidence = AlertConfidence.MEDIUM
        elif party_sample >= 5:
            confidence = AlertConfidence.LOW
        else:
            confidence = AlertConfidence.INSUFFICIENT

        party_name = ticket.party.name if ticket.party else "طرف حساب"
        direction_word = "اضافه وزن" if diff > 0 else "کسری وزن"

        reason = (
            f"مغایرت {direction_word} به میزان {abs_diff:,.0f} کیلوگرم ({diff_percent:.2f}%) "
            f"بین وزن خالص باسکول ({net_weight:,.0f} Kg) و وزن ارسالی بارنامه ({sent_weight:,.0f} Kg) شناسایی شد."
        )

        if party_sample >= 5:
            reason += (
                f" میانگین اختلاف وزن این طرف حساب ({party_name}) در {party_sample} محموله قبلی "
                f"{abs(party_avg_diff):,.0f} کیلوگرم بوده است، در حالی که اختلاف فعلی {abs_diff:,.0f} کیلوگرم می‌باشد."
            )

        title = f"مغایرت وزن با بارنامه ({abs_diff:,.0f} کیلوگرم {direction_word})"
        description = f"وزن باسکول: {net_weight:,.0f} Kg | وزن مبدأ: {sent_weight:,.0f} Kg | اختلاف: {diff:,.0f} Kg"

        metadata = {
            "sent_weight": float(sent_weight),
            "net_weight": float(net_weight),
            "difference_kg": float(diff),
            "difference_percent": float(diff_percent),
            "party_sample_size": party_sample,
            "party_historical_avg_diff": float(party_avg_diff),
            "party_std_dev": float(party_std_diff),
            "party_last_10_avg": float(party_stats["last_10_avg"]),
        }

        return {
            "alert_type": AlertType.WEIGHT_DISCREPANCY,
            "severity": severity,
            "title": title,
            "description": description,
            "reason": reason,
            "current_value": net_weight,
            "baseline_value": sent_weight,
            "deviation_value": diff,
            "deviation_percent": diff_percent,
            "sample_size": party_sample,
            "confidence": confidence,
            "metadata": metadata,
        }
