from decimal import Decimal
from audit.models import AuditLog, AuditAction
from monitoring.models import AlertType, AlertSeverity, AlertConfidence, MonitoringRuleConfig
from weighbridge.models import TicketStatus


class WeightEditAnalysisService:
    """
    Rule 6: Post-Registration Weight & Loss Edit Risk Analysis.
    Inspects AuditLog records for changes made to official weights or loss after initial creation.
    """
    @classmethod
    def analyze(cls, ticket, config: MonitoringRuleConfig | None = None) -> dict | None:
        if not config:
            config = MonitoringRuleConfig.get_rule_config(AlertType.WEIGHT_EDIT_ANOMALY)

        if not config.enabled:
            return None

        # Fetch audit logs for this ticket regarding weight changes
        audit_qs = AuditLog.objects.filter(
            model_name="WeighTicket",
            record_id=str(ticket.id),
            action__in=[
                AuditAction.OVERRIDE_WEIGHT,
                AuditAction.OVERRIDE_LOSS,
                AuditAction.UPDATE,
            ]
        ).order_by("timestamp")

        if not audit_qs.exists() and not ticket.last_edited_by:
            return None

        # Find significant weight changes
        weight_diffs = []
        edit_count = audit_qs.count()
        last_log = audit_qs.last()

        max_abs_diff = Decimal("0.00")
        changed_field_name = ""
        old_val_display = Decimal("0.00")
        new_val_display = Decimal("0.00")

        for log in audit_qs:
            old_v = log.old_values or {}
            new_v = log.new_values or {}

            # Check tare weight
            if "tare_weight" in old_v and "tare_weight" in new_v:
                try:
                    o = Decimal(str(old_v["tare_weight"]))
                    n = Decimal(str(new_v["tare_weight"]))
                    d = abs(n - o)
                    if d > max_abs_diff:
                        max_abs_diff = d
                        changed_field_name = "وزن خالی (Tare)"
                        old_val_display = o
                        new_val_display = n
                except Exception:
                    pass

            # Check gross weight
            if "gross_weight" in old_v and "gross_weight" in new_v:
                try:
                    o = Decimal(str(old_v["gross_weight"]))
                    n = Decimal(str(new_v["gross_weight"]))
                    d = abs(n - o)
                    if d > max_abs_diff:
                        max_abs_diff = d
                        changed_field_name = "وزن پر (Gross)"
                        old_val_display = o
                        new_val_display = n
                except Exception:
                    pass

            # Check net weight
            if "net_weight" in old_v and "net_weight" in new_v:
                try:
                    o = Decimal(str(old_v["net_weight"]))
                    n = Decimal(str(new_v["net_weight"]))
                    d = abs(n - o)
                    if d > max_abs_diff:
                        max_abs_diff = d
                        changed_field_name = "وزن خالص (Net)"
                        old_val_display = o
                        new_val_display = n
                except Exception:
                    pass

        # If audit logs exist but max_abs_diff is 0, check last_edit_reason
        if max_abs_diff == Decimal("0.00") and ticket.last_edited_by:
            max_abs_diff = Decimal("50.00")
            changed_field_name = "مشخصات/اوزان قبض"

        if max_abs_diff < config.warning_threshold and edit_count <= 1:
            return None

        # Severity assessment
        if max_abs_diff >= config.critical_threshold or edit_count >= 3:
            severity = AlertSeverity.CRITICAL
        elif max_abs_diff >= config.high_threshold or edit_count >= 2:
            severity = AlertSeverity.HIGH
        elif max_abs_diff >= config.warning_threshold:
            severity = AlertSeverity.MEDIUM
        else:
            severity = AlertSeverity.LOW

        editor_name = ticket.last_edited_by.get_full_name() or ticket.last_edited_by.username if ticket.last_edited_by else "کاربر سیستم"
        reason_text = ticket.last_edit_reason or (last_log.reason if last_log else "بدون ثبت دلیل")

        diff_percent = Decimal(str(round(float((max_abs_diff / (old_val_display or Decimal("1000"))) * Decimal("100")), 2)))

        reason = (
            f"اطلاعات {changed_field_name} این قبض پس از ثبت اولیه به میزان {max_abs_diff:,.0f} کیلوگرم تغییر کرده است "
            f"(از {old_val_display:,.0f} به {new_val_display:,.0f} Kg). "
            f"تعداد دفعات ویرایش: {edit_count} بار | توسط: {editor_name} | دلیل اعلام‌شده: {reason_text}."
        )

        title = f"اصلاح غیرعادی و دستی وزن قبض ({max_abs_diff:,.0f} کیلوگرم تغییر)"
        description = f"{changed_field_name} از {old_val_display:,.0f} به {new_val_display:,.0f} Kg تغییر یافت ({edit_count} بار ویرایش)"

        metadata = {
            "changed_field": changed_field_name,
            "old_value": float(old_val_display),
            "new_value": float(new_val_display),
            "difference_kg": float(max_abs_diff),
            "difference_percent": float(diff_percent),
            "edit_count": edit_count,
            "editor_name": editor_name,
            "edit_reason": reason_text,
        }

        return {
            "alert_type": AlertType.WEIGHT_EDIT_ANOMALY,
            "severity": severity,
            "title": title,
            "description": description,
            "reason": reason,
            "current_value": new_val_display,
            "baseline_value": old_val_display,
            "deviation_value": max_abs_diff,
            "deviation_percent": diff_percent,
            "sample_size": edit_count,
            "confidence": AlertConfidence.HIGH,
            "metadata": metadata,
        }
