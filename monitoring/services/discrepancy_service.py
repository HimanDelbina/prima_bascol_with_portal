import logging
from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError, PermissionDenied
from django.utils import timezone
from django.contrib.auth.models import User

from weighbridge.models import WeighTicket, TicketStatus
from weighbridge.services import TicketCalculationService
from monitoring.models import (
    MonitoringAlert, MonitoringRuleConfig, AlertType, AlertSeverity,
    AlertStatus, ApprovalStatus, DiscrepancyApproval
)
from audit.services import log_audit
from audit.models import AuditAction

logger = logging.getLogger(__name__)


class DiscrepancyApprovalService:
    """
    Intelligent Discrepancy Evaluation and Supervisor Approval Service (Phase 3.1).
    Provides atomic concurrency-safe approval lifecycle management, separation of duties,
    weight discrepancy checks, and automatic invalidation of stale approvals.
    """

    @classmethod
    def compute_rule_fingerprint(cls, rule_type: str) -> str:
        """Computes a deterministic fingerprint of a rule's active thresholds and settings."""
        rule_config = MonitoringRuleConfig.get_rule_config(rule_type)
        if not rule_config:
            return ""
        return (
            f"{rule_type}:w={rule_config.warning_threshold}:c={rule_config.critical_threshold}:"
            f"pw={rule_config.percentage_warning}:pc={rule_config.percentage_critical}:req={rule_config.requires_approval}"
        )

    @classmethod
    def evaluate_ticket_discrepancies(
        cls,
        ticket: WeighTicket,
        trial_weights: dict | None = None
    ) -> dict:
        """
        Evaluates a ticket for discrepancies and determines if supervisor approval is required.
        Accepts optional trial_weights dictionary (from TicketCalculationService.calculate_ticket)
        when evaluating during second weighing before ticket persistence.
        """
        # Determine effective weights and parameters
        if trial_weights:
            gross = Decimal(str(trial_weights.get("gross_weight") or 0))
            tare = Decimal(str(trial_weights.get("tare_weight") or 0))
            net = Decimal(str(trial_weights.get("net_weight") or 0))
            sent = Decimal(str(trial_weights.get("sent_weight") or ticket.sent_weight or 0))
            diff = Decimal(str(trial_weights.get("weight_difference") or 0))
            diff_pct = Decimal(str(trial_weights.get("weight_difference_percent") or 0))
            is_tol_exceeded = bool(trial_weights.get("is_tolerance_exceeded"))
            loss_pct = Decimal(str(trial_weights.get("loss_percent") or ticket.loss_percent or 0))
            is_loss_overridden = bool(trial_weights.get("is_loss_overridden", ticket.is_loss_overridden))
            current_prod = trial_weights.get("product") if "product" in trial_weights else ticket.product
        else:
            gross = ticket.gross_weight
            tare = ticket.tare_weight
            net = ticket.net_weight
            sent = ticket.sent_weight
            diff = ticket.weight_difference
            diff_pct = ticket.weight_difference_percent
            is_tol_exceeded = ticket.is_tolerance_exceeded
            loss_pct = ticket.loss_percent
            is_loss_overridden = ticket.is_loss_overridden
            current_prod = ticket.product

        # Check existing approvals for this ticket
        active_approval = None
        if getattr(ticket, "pk", None):
            active_approval = DiscrepancyApproval.objects.filter(
                ticket=ticket
            ).exclude(status=ApprovalStatus.CANCELLED).order_by("-id").first()

        is_approved = False
        is_pending = False
        is_rejected = False
        is_weights_changed = False

        if active_approval:
            rfp = cls.compute_rule_fingerprint(active_approval.discrepancy_type)
            is_matching = active_approval.are_parameters_matching(
                gross=gross,
                tare=tare,
                net=net,
                product=current_prod,
                sent_weight=sent,
                rule_fingerprint=rfp,
            )
            if active_approval.status == ApprovalStatus.APPROVED:
                if is_matching:
                    is_approved = True
                else:
                    is_weights_changed = True
            elif active_approval.status == ApprovalStatus.PENDING:
                if is_matching:
                    is_pending = True
                else:
                    is_weights_changed = True
            elif active_approval.status == ApprovalStatus.REJECTED:
                if is_matching:
                    is_rejected = True
                else:
                    is_weights_changed = True

        # Check blocking rules
        blocking_alerts = []
        warning_alerts = []
        requires_approval = False

        # 1. Weight Discrepancy Rule
        rule_weight = MonitoringRuleConfig.get_rule_config(AlertType.WEIGHT_DISCREPANCY)
        if rule_weight.enabled and sent > 0 and net > 0:
            abs_diff = abs(diff)
            abs_pct = abs(diff_pct)
            is_warn = abs_diff >= rule_weight.warning_threshold or abs_pct >= rule_weight.percentage_warning or is_tol_exceeded
            is_crit = abs_diff >= rule_weight.critical_threshold or abs_pct >= rule_weight.percentage_critical

            if is_warn:
                item = {
                    "rule_type": AlertType.WEIGHT_DISCREPANCY,
                    "title": rule_weight.name_fa,
                    "severity": AlertSeverity.CRITICAL if is_crit else AlertSeverity.HIGH,
                    "deviation_value": diff,
                    "deviation_percent": diff_pct,
                    "threshold_applied": rule_weight.critical_threshold if is_crit else rule_weight.warning_threshold,
                    "description": f"مغایرت وزن خالص با بارنامه ({abs_diff:,.0f} Kg / {abs_pct:.2f}%)",
                    "requires_approval": rule_weight.requires_approval,
                }
                if rule_weight.requires_approval:
                    blocking_alerts.append(item)
                    requires_approval = True
                else:
                    warning_alerts.append(item)

        # 2. Loss Anomaly Rule
        rule_loss = MonitoringRuleConfig.get_rule_config(AlertType.LOSS_ANOMALY)
        if rule_loss.enabled and (loss_pct > 0 or is_loss_overridden):
            if loss_pct >= rule_loss.warning_threshold or is_loss_overridden:
                is_crit = loss_pct >= rule_loss.critical_threshold
                item = {
                    "rule_type": AlertType.LOSS_ANOMALY,
                    "title": rule_loss.name_fa,
                    "severity": AlertSeverity.CRITICAL if is_crit else AlertSeverity.HIGH,
                    "deviation_value": loss_pct,
                    "deviation_percent": Decimal("0.00"),
                    "threshold_applied": rule_loss.warning_threshold,
                    "description": f"افت محموله ({loss_pct:.2f}%)" + (" [تنظیم دستی]" if is_loss_overridden else ""),
                    "requires_approval": rule_loss.requires_approval,
                }
                if rule_loss.requires_approval:
                    blocking_alerts.append(item)
                    requires_approval = True
                else:
                    warning_alerts.append(item)

        # 3. Vehicle Tare Anomaly Rule
        rule_tare = MonitoringRuleConfig.get_rule_config(AlertType.VEHICLE_TARE_ANOMALY)
        if rule_tare.enabled and ticket.vehicle and ticket.vehicle.empty_weight and tare > 0:
            baseline_tare = ticket.vehicle.empty_weight
            tare_diff = abs(tare - baseline_tare)
            if tare_diff >= rule_tare.warning_threshold:
                is_crit = tare_diff >= rule_tare.critical_threshold
                item = {
                    "rule_type": AlertType.VEHICLE_TARE_ANOMALY,
                    "title": rule_tare.name_fa,
                    "severity": AlertSeverity.CRITICAL if is_crit else AlertSeverity.HIGH,
                    "deviation_value": tare_diff,
                    "deviation_percent": Decimal("0.00"),
                    "threshold_applied": rule_tare.warning_threshold,
                    "description": f"انحراف وزن خالی خودرو ({tare_diff:,.0f} Kg نسبت به مبنا {baseline_tare:,.0f} Kg)",
                    "requires_approval": rule_tare.requires_approval,
                }
                if rule_tare.requires_approval:
                    blocking_alerts.append(item)
                    requires_approval = True
                else:
                    warning_alerts.append(item)

        # Determine if ticket can be finalized
        can_finalize = True
        blocking_reason = None

        if requires_approval:
            if is_approved:
                can_finalize = True
            elif is_pending:
                can_finalize = False
                blocking_reason = "این قبض به دلیل مغایرت وزنی در انتظار تأیید سرپرست می‌باشد."
            elif is_rejected:
                can_finalize = False
                blocking_reason = "درخواست مجوز این قبض توسط سرپرست رد شده است و امکان تکمیل آن وجود ندارد."
            elif is_weights_changed:
                can_finalize = False
                blocking_reason = "اوزان قبض پس از ثبت درخواست تغییر کرده است؛ نیاز به بررسی یا ثبت مجدد درخواست تأیید است."
            else:
                can_finalize = False
                blocking_reason = "به دلیل وجود مغایرت خارج از حد مجاز، تکمیل قبض نیازمند تأیید سرپرست است."

        has_discrepancies = bool(blocking_alerts or warning_alerts)

        return {
            "has_discrepancies": has_discrepancies,
            "requires_approval": requires_approval,
            "is_approved": is_approved,
            "is_pending": is_pending,
            "is_rejected": is_rejected,
            "is_weights_changed": is_weights_changed,
            "active_approval": active_approval,
            "blocking_alerts": blocking_alerts,
            "warning_alerts": warning_alerts,
            "can_finalize": can_finalize,
            "blocking_reason": blocking_reason,
            "effective_weights": {
                "gross": gross,
                "tare": tare,
                "net": net,
                "sent": sent,
                "diff": diff,
                "diff_pct": diff_pct,
            }
        }

    @classmethod
    def validate_ticket_finalization(
        cls,
        ticket: WeighTicket,
        trial_weights: dict | None = None,
    ) -> dict:
        """
        Shared domain-level validation that all write paths (Web views, REST API, Django Admin)
        must enforce prior to completing or finalizing any weigh ticket.
        """
        eval_res = cls.evaluate_ticket_discrepancies(ticket, trial_weights=trial_weights)
        if not eval_res["can_finalize"]:
            return {
                "valid": False,
                "error_code": "DISCREPANCY_APPROVAL_REQUIRED",
                "message": eval_res["blocking_reason"] or "تکمیل قبض نیازمند تأیید سرپرست است.",
                "blocking_alerts": eval_res["blocking_alerts"],
                "eval_res": eval_res,
            }
        return {
            "valid": True,
            "error_code": None,
            "message": "",
            "blocking_alerts": [],
            "eval_res": eval_res,
        }

    @classmethod
    def request_approval(
        cls,
        ticket: WeighTicket,
        user: User,
        reason: str,
        discrepancy_type: str = AlertType.WEIGHT_DISCREPANCY,
        gross: Decimal | None = None,
        tare: Decimal | None = None,
        net: Decimal | None = None,
        product=None,
        sent_weight: Decimal | None = None,
        alert: MonitoringAlert | None = None,
        metadata: dict | None = None,
    ) -> DiscrepancyApproval:
        """
        Submits a new supervisor approval request atomically.
        Guarantees that duplicate PENDING requests cannot be created concurrently
        and prevents creating approval requests for closed (COMPLETED/CANCELLED) tickets.
        """
        if ticket.status in [TicketStatus.COMPLETED, TicketStatus.CANCELLED]:
            raise ValidationError(
                f"امکان ثبت درخواست تأیید مغایرت برای قبض در وضعیت «{ticket.get_status_display()}» وجود ندارد."
            )

        clean_reason = (reason or "").strip()
        if not clean_reason or len(clean_reason) < 5:
            raise ValidationError("وارد کردن دلیل موجه برای درخواست تأیید سرپرست (حداقل ۵ کاراکتر) الزامی است.")

        with transaction.atomic():
            # Check for existing PENDING request with row lock
            existing_pending = DiscrepancyApproval.objects.select_for_update().filter(
                ticket=ticket,
                status=ApprovalStatus.PENDING
            ).first()

            if existing_pending:
                raise ValidationError("یک درخواست تأیید باز (در انتظار بررسی) از قبل برای این قبض وجود دارد.")

            g = Decimal(str(gross if gross is not None else ticket.gross_weight or 0))
            t = Decimal(str(tare if tare is not None else ticket.tare_weight or 0))
            n = Decimal(str(net if net is not None else ticket.net_weight or 0))
            prod = product or ticket.product
            sent = Decimal(str(sent_weight if sent_weight is not None else ticket.sent_weight or 0))

            rule_config = MonitoringRuleConfig.get_rule_config(discrepancy_type)
            rule_name = rule_config.name_fa if rule_config else "مغایرت توزین"
            rfp = cls.compute_rule_fingerprint(discrepancy_type)

            approval = DiscrepancyApproval.objects.create(
                ticket=ticket,
                alert=alert,
                discrepancy_type=discrepancy_type,
                severity=alert.severity if alert else AlertSeverity.HIGH,
                status=ApprovalStatus.PENDING,
                rule_name=rule_name,
                current_value=n,
                baseline_value=sent,
                deviation_value=ticket.weight_difference,
                deviation_percent=ticket.weight_difference_percent,
                threshold_applied=rule_config.critical_threshold if rule_config else Decimal("0"),
                gross_weight_snapshot=g,
                tare_weight_snapshot=t,
                net_weight_snapshot=n,
                product_snapshot=prod,
                sent_weight_snapshot=sent,
                rule_fingerprint=rfp,
                requested_by=user,
                request_reason=clean_reason,
                metadata=metadata or {},
            )

            log_audit(
                action=AuditAction.DISCREPANCY_APPROVAL,
                model_name="DiscrepancyApproval",
                record_id=approval.id,
                record_repr=f"درخواست تأیید مغایرت قبض {ticket.serial_number}",
                new_values={
                    "ticket_id": ticket.id,
                    "serial": ticket.serial_number,
                    "status": ApprovalStatus.PENDING,
                    "discrepancy_type": approval.discrepancy_type,
                    "requested_by": user.username,
                    "request_reason": clean_reason,
                    "gross": float(g),
                    "tare": float(t),
                    "net": float(n),
                    "product": str(prod) if prod else "-",
                    "sent_weight": float(sent),
                },
                reason="ثبت درخواست تأیید مغایرت توسط اپراتور"
            )

            return approval

    @classmethod
    def decide_approval(
        cls,
        approval_id: int,
        supervisor_user: User,
        decision: str,
        decision_reason: str,
    ) -> DiscrepancyApproval:
        """
        Executes a supervisor decision (approve or reject) with strict separation of duties,
        transactional atomicity, and row-level locking (SELECT FOR UPDATE).
        """
        clean_reason = (decision_reason or "").strip()
        if not clean_reason or len(clean_reason) < 5:
            raise ValidationError("وارد کردن دلیل مستند برای تصمیم سرپرست (حداقل ۵ کاراکتر) الزامی است.")

        with transaction.atomic():
            try:
                approval = DiscrepancyApproval.objects.select_for_update().get(id=approval_id)
            except DiscrepancyApproval.DoesNotExist:
                raise ValidationError("درخواست تأیید مورد نظر یافت نشد.")

            # Concurrency & Idempotency check: Already decided
            if approval.status != ApprovalStatus.PENDING:
                raise ValidationError(
                    f"این درخواست قبلاً تعیین تکلیف شده است (وضعیت: {approval.get_status_display()}). "
                    "امکان تغییر مجدد تصمیم وجود ندارد."
                )

            # Strict Separation of Duties Check: Requester cannot approve their own request under any circumstance
            if approval.requested_by_id == supervisor_user.id:
                raise ValidationError("بر اساس اصل تفکیک وظایف، اپراتور ثبت‌کننده درخواست نمی‌تواند آن را تأیید کند.")

            # Permission Check
            is_authorized = supervisor_user.is_superuser or (
                hasattr(supervisor_user, "profile") and supervisor_user.profile.can_approve_discrepancy
            )
            if not is_authorized:
                raise PermissionDenied("شما مجوز لازم برای تصمیم‌گیری روی درخواست‌های مغایرت را ندارید.")

            old_status = approval.status
            if decision == "approve":
                approval.status = ApprovalStatus.APPROVED
            elif decision == "reject":
                approval.status = ApprovalStatus.REJECTED
            else:
                raise ValidationError(f"تصمیم نامعتبر: {decision}")

            approval.reviewed_by = supervisor_user
            approval.reviewed_at = timezone.now()
            approval.decision_reason = clean_reason
            approval.save(update_fields=["status", "reviewed_by", "reviewed_at", "decision_reason"])

            # Synchronize linked MonitoringAlert if present
            if approval.alert:
                alert = approval.alert
                if decision == "approve":
                    alert.status = AlertStatus.RESOLVED
                    alert.resolved_by = supervisor_user
                    alert.resolved_at = timezone.now()
                    alert.resolution_note = f"تأیید سرپرست: {clean_reason}"
                    alert.save(update_fields=["status", "resolved_by", "resolved_at", "resolution_note"])
                else:
                    alert.status = AlertStatus.REVIEWED
                    alert.reviewed_by = supervisor_user
                    alert.reviewed_at = timezone.now()
                    alert.resolution_note = f"عدم تأیید (رد) توسط سرپرست: {clean_reason}"
                    alert.save(update_fields=["status", "reviewed_by", "reviewed_at", "resolution_note"])

            log_audit(
                action=AuditAction.DISCREPANCY_APPROVAL,
                model_name="DiscrepancyApproval",
                record_id=approval.id,
                record_repr=f"تصمیم سرپرست در خصوص مغایرت قبض {approval.ticket.serial_number}",
                old_values={"status": old_status},
                new_values={
                    "status": approval.status,
                    "reviewed_by": supervisor_user.username,
                    "decision_reason": clean_reason,
                    "reviewed_at": str(approval.reviewed_at),
                },
                reason=f"ثبت تصمیم سرپرست: {approval.get_status_display()}"
            )

            return approval

    @classmethod
    def check_and_invalidate_stale_approvals(
        cls,
        ticket: WeighTicket,
        current_gross: Decimal,
        current_tare: Decimal,
        current_net: Decimal,
        current_product=None,
        current_sent_weight: Decimal | None = None,
        current_rule_fingerprint: str | None = None,
    ) -> bool:
        """
        If ticket parameters (weights, product, waybill weight, rule config) were modified
        after approval was granted, invalidates (cancels) the approval atomically.
        """
        if not getattr(ticket, "pk", None):
            return False

        with transaction.atomic():
            approved = DiscrepancyApproval.objects.select_for_update().filter(
                ticket=ticket,
                status=ApprovalStatus.APPROVED
            ).first()

            if approved:
                prod = current_product if current_product is not None else ticket.product
                sent = Decimal(str(current_sent_weight if current_sent_weight is not None else ticket.sent_weight or 0))
                rfp = current_rule_fingerprint or cls.compute_rule_fingerprint(approved.discrepancy_type)

                if not approved.are_parameters_matching(
                    gross=current_gross,
                    tare=current_tare,
                    net=current_net,
                    product=prod,
                    sent_weight=sent,
                    rule_fingerprint=rfp,
                ):
                    approved.status = ApprovalStatus.CANCELLED
                    approved.decision_reason = (
                        (approved.decision_reason or "") +
                        f" | [ابطال خودکار به دلیل تغییر مقادیر مصوب پس از تأیید: ناخالص={current_gross}, تارا={current_tare}, خالص={current_net}, کالا={prod}, بارنامه={sent}]"
                    ).strip()
                    approved.save(update_fields=["status", "decision_reason"])

                    log_audit(
                        action=AuditAction.STATUS_CHANGE,
                        model_name="DiscrepancyApproval",
                        record_id=approved.id,
                        record_repr=f"ابطال مجوز قبض {ticket.serial_number}",
                        old_values={"status": ApprovalStatus.APPROVED},
                        new_values={"status": ApprovalStatus.CANCELLED},
                        reason="ابطال خودکار مجوز به علت تغییر مقادیر مصوب پس از تأیید"
                    )
                    return True

        return False

    @classmethod
    def cancel_approval_request(
        cls,
        approval_id: int,
        user: User,
        reason: str,
    ) -> DiscrepancyApproval:
        """
        Cancels an existing pending approval request.
        """
        with transaction.atomic():
            approval = DiscrepancyApproval.objects.select_for_update().get(id=approval_id)
            if approval.status != ApprovalStatus.PENDING:
                raise ValidationError("تنها درخواست‌های در انتظار بررسی قابل لغو هستند.")

            approval.status = ApprovalStatus.CANCELLED
            approval.decision_reason = f"لغو توسط {user.get_full_name() or user.username}: {reason}"
            approval.save(update_fields=["status", "decision_reason"])

            log_audit(
                action=AuditAction.STATUS_CHANGE,
                model_name="DiscrepancyApproval",
                record_id=approval.id,
                record_repr=f"لغو درخواست تأیید قبض {approval.ticket.serial_number}",
                old_values={"status": ApprovalStatus.PENDING},
                new_values={"status": ApprovalStatus.CANCELLED},
                reason=reason or "لغو درخواست توسط کاربر"
            )
            return approval
