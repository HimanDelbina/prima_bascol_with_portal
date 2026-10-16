import logging
from decimal import Decimal
from typing import Dict, Any, Optional, Tuple, List
from django.db import transaction
from django.core.exceptions import ValidationError, PermissionDenied
from django.utils import timezone
from django.contrib.auth.models import User

from weighbridge.models import WeighTicket, TicketRevision, TicketStatus
from weighbridge.services import TicketCalculationService, VehicleDriverRegistrationService
from weighbridge.plate_policy import DailyPlatePolicy
from audit.models import AuditLog, AuditAction
from audit.services import log_audit

logger = logging.getLogger("weighbridge.revision")


class TicketRevisionService:
    """
    Centralized, concurrency-safe, auditable revision governance service
    for completed weighbridge tickets (Phase 3.2.3).

    Principles:
    1. Original weighing evidence and immutable fields are strictly preserved.
    2. Controlled business changes create an explicit, traceable TicketRevision record.
    3. Separation of duties: Requester cannot review/approve their own request.
    4. Row-level locks in consistent acquisition order prevent deadlocks and race conditions.
    5. The latest applied revision determines the effective business values on WeighTicket.
    6. Completed tickets are NEVER demoted into WAITING_SECOND.
    """

    IMMUTABLE_FIELDS = {
        "serial_number",
        "created_at",
        "first_weight_date",
        "first_weight_time",
        "first_weight_operator",
        "first_weight_operator_id",
        "second_weight_date",
        "second_weight_time",
        "second_weight_operator",
        "second_weight_operator_id",
    }

    CONTROLLED_FIELDS = {
        "first_weight",
        "second_weight",
        "gross_weight",
        "tare_weight",
        "net_weight",
        "sent_weight",
        "loss_percent",
        "loss_weight",
        "loss_type",
        "loss_type_id",
        "is_loss_overridden",
        "loss_override_reason",
        "product",
        "product_id",
        "party",
        "party_id",
        "vehicle",
        "vehicle_id",
        "vehicle_type",
        "vehicle_type_id",
        "vehicle_type_custom",
        "license_plate_display",
        "waybill_number",
        "freight_amount",
        "load_count",
        "ingot_count",
        "operation_type",
        "operation_type_id",
    }

    NON_MATERIAL_FIELDS = {
        "notes",
        "driver_mobile_custom",
        "driver_name_custom",
        "unload_location",
        "unload_location_id",
        "origin",
        "origin_id",
        "destination",
        "destination_id",
    }

    @staticmethod
    def _to_decimal_safe(val: Any) -> Any:
        """Converts Decimal objects into string representations for JSON serialization."""
        if isinstance(val, Decimal):
            return str(val)
        if isinstance(val, (dict,)):
            return {k: TicketRevisionService._to_decimal_safe(v) for k, v in val.items()}
        if isinstance(val, (list, tuple)):
            return [TicketRevisionService._to_decimal_safe(v) for v in val]
        return val

    @classmethod
    def serialize_ticket_state(cls, ticket: WeighTicket) -> Dict[str, Any]:
        """Creates a comprehensive, JSON-serializable snapshot of ticket state."""
        return {
            "serial_number": str(ticket.serial_number),
            "status": str(ticket.status),
            "first_weight": str(ticket.first_weight or Decimal("0.00")),
            "first_weight_date": str(ticket.first_weight_date) if ticket.first_weight_date else None,
            "first_weight_time": str(ticket.first_weight_time) if ticket.first_weight_time else None,
            "first_weight_operator_id": ticket.first_weight_operator_id,
            "first_weight_operator_name": ticket.first_weight_operator.get_full_name() or ticket.first_weight_operator.username if ticket.first_weight_operator else None,
            "second_weight": str(ticket.second_weight or Decimal("0.00")) if ticket.second_weight is not None else None,
            "second_weight_date": str(ticket.second_weight_date) if ticket.second_weight_date else None,
            "second_weight_time": str(ticket.second_weight_time) if ticket.second_weight_time else None,
            "second_weight_operator_id": ticket.second_weight_operator_id,
            "second_weight_operator_name": ticket.second_weight_operator.get_full_name() or ticket.second_weight_operator.username if ticket.second_weight_operator else None,
            "gross_weight": str(ticket.gross_weight or Decimal("0.00")),
            "tare_weight": str(ticket.tare_weight or Decimal("0.00")),
            "net_weight": str(ticket.net_weight or Decimal("0.00")),
            "sent_weight": str(ticket.sent_weight or Decimal("0.00")),
            "final_weight": str(ticket.final_weight or Decimal("0.00")),
            "loss_percent": str(ticket.loss_percent or Decimal("0.00")),
            "loss_weight": str(ticket.loss_weight or Decimal("0.00")),
            "loss_type_id": ticket.loss_type_id,
            "loss_type_name": ticket.loss_type.name if ticket.loss_type else None,
            "is_loss_overridden": bool(ticket.is_loss_overridden),
            "loss_override_reason": str(ticket.loss_override_reason or ""),
            "weight_difference": str(ticket.weight_difference or Decimal("0.00")),
            "weight_difference_percent": str(ticket.weight_difference_percent or Decimal("0.00")),
            "is_tolerance_exceeded": bool(ticket.is_tolerance_exceeded),
            "product_id": ticket.product_id,
            "product_name": ticket.product.name if ticket.product else None,
            "party_id": ticket.party_id,
            "party_name": ticket.party.name if ticket.party else None,
            "vehicle_id": ticket.vehicle_id,
            "license_plate_display": str(ticket.license_plate_display or ""),
            "vehicle_type_id": ticket.vehicle_type_id,
            "vehicle_type_name": ticket.vehicle_type.name if ticket.vehicle_type else (ticket.vehicle_type_custom or None),
            "driver_id": ticket.driver_id,
            "driver_name": ticket.driver_name_custom or (ticket.driver.full_name if ticket.driver else None),
            "driver_mobile": ticket.driver_mobile_custom or (ticket.driver.mobile if ticket.driver else None),
            "waybill_number": str(ticket.waybill_number or ""),
            "freight_amount": str(ticket.freight_amount) if ticket.freight_amount is not None else None,
            "load_count": int(ticket.load_count or 1),
            "ingot_count": int(ticket.ingot_count) if ticket.ingot_count is not None else None,
            "operation_type_id": ticket.operation_type_id,
            "operation_type_name": ticket.operation_type.name if ticket.operation_type else None,
            "unload_location_id": ticket.unload_location_id,
            "notes": str(ticket.notes or ""),
            "current_revision_number": int(ticket.current_revision_number or 0),
        }

    @classmethod
    def request_revision(
        cls,
        ticket: WeighTicket,
        requester: Optional[User] = None,
        proposed_data: Optional[Dict[str, Any]] = None,
        reason: str = "",
        client_ip: Optional[str] = None,
        requested_by: Optional[User] = None,
    ) -> TicketRevision:
        """
        Creates a formal revision request for a completed weighbridge ticket.
        Accepts either requester or requested_by.
        """
        actual_requester = requester or requested_by
        if not actual_requester:
            raise ValidationError({"requester": "کاربر متقاضی بازنگری الزامی است."})

        if proposed_data is None:
            proposed_data = {}

        if not reason or not str(reason).strip():
            raise ValidationError({"reason": "ثبت دلیل و ادله توجیهی برای درخواست بازنگری الزامی است."})

        with transaction.atomic():
            # Acquire row-level lock on ticket
            locked_ticket = WeighTicket.objects.select_for_update().get(pk=ticket.pk)

            if locked_ticket.status != TicketStatus.COMPLETED:
                raise ValidationError("درخواست بازنگری فقط مختص قبوض در وضعیت «تکمیل شده» است.")

            # Check if there is already an active pending revision for this ticket
            existing_pending = TicketRevision.objects.filter(
                ticket=locked_ticket,
                status=TicketRevision.RevisionStatus.PENDING
            ).first()
            if existing_pending:
                raise ValidationError("قبلاً یک درخواست بازنگری در انتظار بررسی برای این قبض ثبت گردیده است.")

            # Validate that immutable fields are not being altered
            for field in cls.IMMUTABLE_FIELDS:
                if field in proposed_data:
                    current_val = getattr(locked_ticket, field, None)
                    if hasattr(current_val, "pk"):
                        current_val = current_val.pk
                    prop_val = proposed_data[field]
                    if str(current_val) != str(prop_val):
                        raise ValidationError({field: "فیلدهای هویتی و ثبت فیزیکی توزین (سریال، زمان‌ها و اپراتورها) کاملاً غیرقابل‌تغییر هستند."})

            # Normalize FK references if given without _id
            if "product" in proposed_data:
                p = proposed_data["product"]
                proposed_data["product_id"] = p.id if hasattr(p, "id") else p
            if "party" in proposed_data:
                pty = proposed_data["party"]
                proposed_data["party_id"] = pty.id if hasattr(pty, "id") else pty
            if "vehicle" in proposed_data:
                v = proposed_data["vehicle"]
                proposed_data["vehicle_id"] = v.id if hasattr(v, "id") else v
            if "vehicle_type" in proposed_data:
                vt = proposed_data["vehicle_type"]
                proposed_data["vehicle_type_id"] = vt.id if hasattr(vt, "id") else vt
            if "driver" in proposed_data:
                d = proposed_data["driver"]
                proposed_data["driver_id"] = d.id if hasattr(d, "id") else d

            # Snapshot before
            before_snapshot = cls.serialize_ticket_state(locked_ticket)

            # Build proposed after state
            after_state = dict(before_snapshot)
            changed_fields_list: List[str] = []

            # If gross or tare are provided directly
            prop_gross = proposed_data.get("gross_weight")
            prop_tare = proposed_data.get("tare_weight")
            if prop_gross is not None and prop_tare is not None:
                if Decimal(str(prop_gross)) < Decimal(str(prop_tare)):
                    raise ValidationError("وزن ناخالص نمی‌تواند کمتر از وزن خالی باشد.")

            # Determine proposed values for weights calculation
            if locked_ticket.weight_mode == "full_first":
                default_first = prop_gross if prop_gross is not None else locked_ticket.first_weight
                default_second = prop_tare if prop_tare is not None else locked_ticket.second_weight
            else:
                default_first = prop_tare if prop_tare is not None else locked_ticket.first_weight
                default_second = prop_gross if prop_gross is not None else locked_ticket.second_weight

            first_w = Decimal(str(proposed_data.get("first_weight", default_first or 0)))
            second_w = Decimal(str(proposed_data.get("second_weight", default_second or 0)))
            sent_w = Decimal(str(proposed_data.get("sent_weight", locked_ticket.sent_weight or 0)))
            loss_pct = Decimal(str(proposed_data.get("loss_percent", locked_ticket.loss_percent or 0)))
            loss_w = Decimal(str(proposed_data.get("loss_weight", locked_ticket.loss_weight or 0)))
            is_loss_overridden = bool(proposed_data.get("is_loss_overridden", locked_ticket.is_loss_overridden))

            eval_product = locked_ticket.product
            if "product_id" in proposed_data:
                from masterdata.models import Product
                eval_product = Product.objects.filter(pk=proposed_data["product_id"]).first() or locked_ticket.product

            # Recalculate official weights with standard formulas
            calc_res = TicketCalculationService.calculate_ticket(
                first_weight=first_w,
                second_weight=second_w,
                sent_weight=sent_w,
                loss_percent=loss_pct,
                manual_loss_weight=loss_w if is_loss_overridden else None,
                product=eval_product,
                is_loss_overridden=is_loss_overridden
            )

            # Apply recalculated values into after state
            after_state["first_weight"] = str(first_w)
            after_state["second_weight"] = str(second_w) if second_w is not None else None
            after_state["gross_weight"] = str(calc_res["gross_weight"])
            after_state["tare_weight"] = str(calc_res["tare_weight"])
            after_state["net_weight"] = str(calc_res["net_weight"])
            after_state["sent_weight"] = str(calc_res["sent_weight"])
            after_state["loss_percent"] = str(calc_res["loss_percent"])
            after_state["loss_weight"] = str(calc_res["loss_weight"])
            after_state["final_weight"] = str(calc_res["final_weight"])
            after_state["weight_difference"] = str(calc_res["weight_difference"])
            after_state["weight_difference_percent"] = str(calc_res["weight_difference_percent"])
            after_state["is_tolerance_exceeded"] = bool(calc_res["is_tolerance_exceeded"])
            after_state["is_loss_overridden"] = is_loss_overridden

            # Apply other proposed fields
            for key, val in proposed_data.items():
                if key in cls.CONTROLLED_FIELDS or key in cls.NON_MATERIAL_FIELDS:
                    after_state[key] = cls._to_decimal_safe(val)

            if "product_id" in proposed_data:
                after_state["product_id"] = proposed_data["product_id"]
                if eval_product:
                    after_state["product_name"] = eval_product.name
            if "party_id" in proposed_data:
                from masterdata.models import Party
                after_state["party_id"] = proposed_data["party_id"]
                party_obj = Party.objects.filter(pk=proposed_data["party_id"]).first()
                if party_obj:
                    after_state["party_name"] = party_obj.name

            def _is_diff(val_a, val_b):
                if val_a is None and val_b is None:
                    return False
                if val_a is None or val_b is None:
                    return True
                try:
                    d_a = Decimal(str(val_a))
                    d_b = Decimal(str(val_b))
                    return d_a != d_b
                except Exception:
                    pass
                return str(val_a).strip() != str(val_b).strip()

            # Compare and identify changed fields
            for key in set(before_snapshot.keys()) | set(after_state.keys()):
                if key in [
                    "current_revision_number", "status", "product_name", "party_name",
                    "vehicle_type_name", "driver_name", "first_weight_operator_name",
                    "second_weight_operator_name"
                ]:
                    continue
                val_before = before_snapshot.get(key)
                val_after = after_state.get(key)
                if _is_diff(val_before, val_after):
                    changed_fields_list.append(key)

            if not changed_fields_list:
                raise ValidationError("هیچ تغییری در اطلاعات نسبت به مقادیر جاری قبض مشاهده نشد.")

            # Run discrepancy evaluation on trial weights
            from monitoring.services.discrepancy_service import DiscrepancyApprovalService
            discrepancy_eval = DiscrepancyApprovalService.evaluate_ticket_discrepancies(
                locked_ticket,
                trial_weights=calc_res
            )
            discrepancy_safe = cls._to_decimal_safe(discrepancy_eval)

            # Create revision record
            revision = TicketRevision.objects.create(
                ticket=locked_ticket,
                revision_number=None,  # Assigned only when applied!
                ticket_current_revision_at_request=locked_ticket.current_revision_number,
                status=TicketRevision.RevisionStatus.PENDING,
                reason=reason.strip(),
                before_snapshot=before_snapshot,
                after_snapshot=after_state,
                changed_fields=changed_fields_list,
                requested_by=actual_requester,
                discrepancy_details=discrepancy_safe,
            )

            # Audit log
            log_audit(
                action=AuditAction.REVISION_REQUEST,
                model_name="WeighTicket",
                record_id=str(locked_ticket.id),
                record_repr=f"قبض شماره {locked_ticket.serial_number}",
                user=actual_requester,
                old_values={"revision_id": str(revision.id), "fields": changed_fields_list},
                new_values={"status": revision.status, "reason": reason.strip()},
                reason=f"ثبت درخواست بازنگری: {reason.strip()}",
                ip_address=client_ip,
                source="TicketRevisionService"
            )

            logger.info("Revision %s requested for ticket #%s by user %s", revision.id, locked_ticket.serial_number, actual_requester)
            return revision

    @classmethod
    def approve_revision(
        cls,
        revision: Any,
        reviewer: User,
        review_reason: str = "",
        auto_apply: bool = True,
        client_ip: Optional[str] = None,
        decision_notes: Optional[str] = None,
    ) -> TicketRevision:
        """
        Approves a pending ticket revision.
        Enforces separation of duties (requester != reviewer) and detects stale requests.
        """
        rev_id = revision.id if hasattr(revision, "id") else revision
        actual_notes = review_reason or decision_notes or ""

        with transaction.atomic():
            # Strict lock order: WeighTicket first, then TicketRevision
            # First fetch ticket ID
            rev_obj = TicketRevision.objects.select_related("ticket").get(pk=rev_id)
            locked_ticket = WeighTicket.objects.select_for_update().get(pk=rev_obj.ticket_id)
            locked_revision = TicketRevision.objects.select_for_update().get(pk=rev_id)

            if locked_revision.status != TicketRevision.RevisionStatus.PENDING:
                raise ValidationError(f"درخواست بازنگری در وضعیت «{locked_revision.get_status_display()}» بوده و قابل تأیید نیست.")

            # Separation of duties check
            if locked_revision.requested_by_id == reviewer.id and not reviewer.is_superuser:
                raise PermissionDenied("اصل تفکیک وظایف: کاربر ثبت‌کننده درخواست نمی‌تواند رأساً آن را تأیید نماید.")

            # Stale revision conflict check
            if locked_revision.ticket_current_revision_at_request != locked_ticket.current_revision_number:
                raise ValidationError(
                    f"این درخواست بازنگری منسوخ شده است (Stale Conflict). "
                    f"نسخه قبض در زمان درخواست {locked_revision.ticket_current_revision_at_request} بوده ولی اکنون {locked_ticket.current_revision_number} است."
                )

            # Check blocking discrepancies authorization
            disc_details = locked_revision.discrepancy_details or {}
            if disc_details.get("has_blocking"):
                can_approve_disc = reviewer.is_superuser or getattr(reviewer.profile, "is_admin_or_manager", False)
                if not can_approve_disc:
                    raise PermissionDenied(
                        f"این بازنگری دارای مغایرت مسدودکننده است ({disc_details.get('blocking_reason')}) "
                        "و نیازمند مجوز سرپرست ارشد جهت تأیید می‌باشد."
                    )

            now = timezone.now()
            locked_revision.status = TicketRevision.RevisionStatus.APPROVED
            locked_revision.reviewed_by = reviewer
            locked_revision.reviewed_at = now
            locked_revision.review_notes = actual_notes.strip()
            locked_revision.save()

            if auto_apply:
                return cls.apply_revision(locked_revision, applied_by=reviewer, client_ip=client_ip)

            return locked_revision

    @classmethod
    def apply_revision(
        cls,
        revision: Any,
        applied_by: User,
        client_ip: Optional[str] = None
    ) -> TicketRevision:
        """
        Atomically applies an approved revision to WeighTicket.
        Increments current_revision_number, stores original_net_weight if first revision,
        and ensures ticket.status NEVER transitions to WAITING_SECOND.
        """
        rev_id = revision.id if hasattr(revision, "id") else revision

        with transaction.atomic():
            rev_obj = TicketRevision.objects.select_related("ticket").get(pk=rev_id)
            locked_ticket = WeighTicket.objects.select_for_update().get(pk=rev_obj.ticket_id)
            locked_revision = TicketRevision.objects.select_for_update().get(pk=rev_id)

            if locked_revision.status not in [TicketRevision.RevisionStatus.APPROVED, TicketRevision.RevisionStatus.PENDING]:
                raise ValidationError(f"درخواست بازنگری در وضعیت «{locked_revision.get_status_display()}» امکان اعمال شدن ندارد.")

            # If revision was pending and directly applied by an authorized manager (with separation of duties)
            if locked_revision.status == TicketRevision.RevisionStatus.PENDING:
                if locked_revision.requested_by_id == applied_by.id and not applied_by.is_superuser:
                    raise PermissionDenied("اصل تفکیک وظایف: کاربر ثبت‌کننده درخواست نمی‌تواند آن را اعمال کند.")
                locked_revision.reviewed_by = applied_by
                locked_revision.reviewed_at = timezone.now()

            # Atomically increment revision number
            new_rev_number = locked_ticket.current_revision_number + 1
            locked_revision.revision_number = new_rev_number

            # Preserve original net weight upon first applied revision
            if locked_ticket.current_revision_number == 0:
                locked_ticket.original_net_weight = locked_ticket.net_weight

            # Apply after snapshot values onto locked_ticket
            after = locked_revision.after_snapshot

            if "first_weight" in after:
                locked_ticket.first_weight = Decimal(str(after["first_weight"]))
            if "second_weight" in after and after["second_weight"] is not None:
                locked_ticket.second_weight = Decimal(str(after["second_weight"]))
            if "gross_weight" in after:
                locked_ticket.gross_weight = Decimal(str(after["gross_weight"]))
            if "tare_weight" in after:
                locked_ticket.tare_weight = Decimal(str(after["tare_weight"]))
            if "net_weight" in after:
                locked_ticket.net_weight = Decimal(str(after["net_weight"]))
            if "sent_weight" in after:
                locked_ticket.sent_weight = Decimal(str(after["sent_weight"]))
            if "final_weight" in after:
                locked_ticket.final_weight = Decimal(str(after["final_weight"]))
            if "loss_percent" in after:
                locked_ticket.loss_percent = Decimal(str(after["loss_percent"]))
            if "loss_weight" in after:
                locked_ticket.loss_weight = Decimal(str(after["loss_weight"]))
            if "loss_type_id" in after:
                locked_ticket.loss_type_id = after["loss_type_id"]
            if "is_loss_overridden" in after:
                locked_ticket.is_loss_overridden = bool(after["is_loss_overridden"])
            if "weight_difference" in after:
                locked_ticket.weight_difference = Decimal(str(after["weight_difference"]))
            if "weight_difference_percent" in after:
                locked_ticket.weight_difference_percent = Decimal(str(after["weight_difference_percent"]))
            if "is_tolerance_exceeded" in after:
                locked_ticket.is_tolerance_exceeded = bool(after["is_tolerance_exceeded"])

            if "product_id" in after or "product" in after:
                p_val = after.get("product_id") or after.get("product")
                locked_ticket.product_id = getattr(p_val, "id", p_val)
            if "party_id" in after or "party" in after:
                pty_val = after.get("party_id") or after.get("party")
                locked_ticket.party_id = getattr(pty_val, "id", pty_val)
            if "vehicle_id" in after or "vehicle" in after:
                veh_val = after.get("vehicle_id") or after.get("vehicle")
                locked_ticket.vehicle_id = getattr(veh_val, "id", veh_val)
            if "license_plate_display" in after:
                locked_ticket.license_plate_display = after["license_plate_display"]
            if "vehicle_type_id" in after or "vehicle_type" in after:
                vt_val = after.get("vehicle_type_id") or after.get("vehicle_type")
                locked_ticket.vehicle_type_id = getattr(vt_val, "id", vt_val)
            if "driver_id" in after or "driver" in after:
                drv_val = after.get("driver_id") or after.get("driver")
                locked_ticket.driver_id = getattr(drv_val, "id", drv_val)
            if "driver_mobile" in after:
                locked_ticket.driver_mobile_custom = after["driver_mobile"]
            if "waybill_number" in after:
                locked_ticket.waybill_number = after["waybill_number"]
            if "freight_amount" in after and after["freight_amount"] is not None:
                locked_ticket.freight_amount = Decimal(str(after["freight_amount"]))
            if "load_count" in after:
                locked_ticket.load_count = after["load_count"]
            if "ingot_count" in after and after["ingot_count"] is not None:
                locked_ticket.ingot_count = after["ingot_count"]
            if "notes" in after:
                locked_ticket.notes = after["notes"]

            # Set revision metadata on ticket
            locked_ticket.current_revision_number = new_rev_number
            locked_ticket.last_edited_by = applied_by
            locked_ticket.last_edit_reason = f"اعمال بازنگری ویرایش {new_rev_number}: {locked_revision.reason}"

            # CRITICAL: ticket.status MUST REMAIN COMPLETED! Never demote to WAITING_SECOND!
            locked_ticket.status = TicketStatus.COMPLETED

            # Save ticket safely with DailyPlatePolicy
            DailyPlatePolicy.save(locked_ticket, user=applied_by)

            # Finalize revision record
            now = timezone.now()
            locked_revision.status = TicketRevision.RevisionStatus.APPLIED
            locked_revision.applied_by = applied_by
            locked_revision.applied_at = now
            locked_revision.save()

            # Record audit log
            log_audit(
                action=AuditAction.REVISION_APPLY,
                model_name="WeighTicket",
                record_id=str(locked_ticket.id),
                record_repr=f"قبض شماره {locked_ticket.serial_number} (ویرایش {new_rev_number})",
                user=applied_by,
                old_values={"revision_number": new_rev_number - 1, "before": locked_revision.before_snapshot},
                new_values={"revision_number": new_rev_number, "after": locked_revision.after_snapshot},
                reason=f"اعمال قطعی بازنگری ویرایش {new_rev_number}",
                ip_address=client_ip,
                source="TicketRevisionService"
            )

            logger.info("Revision #%s (Rev.%d) successfully applied to ticket #%s by user %s",
                        locked_revision.id, new_rev_number, locked_ticket.serial_number, applied_by)
            return locked_revision

    @classmethod
    def reject_revision(
        cls,
        revision: Any,
        reviewer: User,
        review_reason: str = "",
        client_ip: Optional[str] = None,
        decision_notes: Optional[str] = None,
    ) -> TicketRevision:
        """
        Rejects a pending ticket revision.
        """
        actual_reason = review_reason or decision_notes or ""
        if not actual_reason or not str(actual_reason).strip():
            raise ValidationError({"review_notes": "ثبت دلیل رد درخواست بازنگری الزامی است."})

        rev_id = revision.id if hasattr(revision, "id") else revision

        with transaction.atomic():
            rev_obj = TicketRevision.objects.select_related("ticket").get(pk=rev_id)
            locked_ticket = WeighTicket.objects.select_for_update().get(pk=rev_obj.ticket_id)
            locked_revision = TicketRevision.objects.select_for_update().get(pk=rev_id)

            if locked_revision.status != TicketRevision.RevisionStatus.PENDING:
                raise ValidationError(f"درخواست بازنگری در وضعیت «{locked_revision.get_status_display()}» بوده و قابل رد کردن نیست.")

            if locked_revision.requested_by_id == reviewer.id and not reviewer.is_superuser:
                raise PermissionDenied("کاربر متقاضی نمی‌تواند درخواست خود را رد کند؛ لطفاً از گزینه انصراف (Withdraw) استفاده فرمایید.")

            now = timezone.now()
            locked_revision.status = TicketRevision.RevisionStatus.REJECTED
            locked_revision.reviewed_by = reviewer
            locked_revision.reviewed_at = now
            locked_revision.review_notes = actual_reason.strip()
            locked_revision.save()

            log_audit(
                action=AuditAction.REVISION_REJECT,
                model_name="WeighTicket",
                record_id=str(locked_ticket.id),
                record_repr=f"قبض شماره {locked_ticket.serial_number}",
                user=reviewer,
                old_values={"revision_id": str(locked_revision.id)},
                new_values={"status": locked_revision.status, "reason": actual_reason.strip()},
                reason=f"رد درخواست بازنگری: {actual_reason.strip()}",
                ip_address=client_ip,
                source="TicketRevisionService"
            )

            logger.info("Revision %s rejected by user %s", locked_revision.id, reviewer)
            return locked_revision

    @classmethod
    def withdraw_revision(
        cls,
        revision: Any,
        user: User,
        reason: str = "",
        client_ip: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> TicketRevision:
        """
        Withdraws a pending revision by the original requester.
        """
        actual_reason = reason or notes or ""
        rev_id = revision.id if hasattr(revision, "id") else revision

        with transaction.atomic():
            locked_revision = TicketRevision.objects.select_for_update().get(pk=rev_id)

            if locked_revision.status != TicketRevision.RevisionStatus.PENDING:
                raise ValidationError(f"درخواست بازنگری در وضعیت «{locked_revision.get_status_display()}» بوده و امکان انصراف وجود ندارد.")

            if locked_revision.requested_by_id != user.id and not user.is_superuser:
                raise PermissionDenied("فقط کاربر ثبت‌کننده درخواست یا مدیر ارشد مجاز به انصراف از بازنگری است.")

            now = timezone.now()
            locked_revision.status = TicketRevision.RevisionStatus.WITHDRAWN
            locked_revision.reviewed_at = now
            locked_revision.review_notes = f"انصراف توسط کاربر: {actual_reason.strip()}" if actual_reason else "انصراف توسط کاربر"
            locked_revision.save()

            log_audit(
                action=AuditAction.REVISION_WITHDRAW,
                model_name="WeighTicket",
                record_id=str(locked_revision.ticket_id),
                record_repr=f"قبض شماره {locked_revision.ticket.serial_number}",
                user=user,
                old_values={"revision_id": str(locked_revision.id)},
                new_values={"status": locked_revision.status},
                reason=f"انصراف از درخواست بازنگری: {reason.strip()}",
                ip_address=client_ip,
                source="TicketRevisionService"
            )

            logger.info("Revision %s withdrawn by user %s", locked_revision.id, user)
            return locked_revision

    @classmethod
    def get_effective_ticket_data(cls, ticket: WeighTicket) -> Dict[str, Any]:
        """Returns the currently effective business values for downstream reporting and display."""
        data = cls.serialize_ticket_state(ticket)
        data["is_revised"] = ticket.current_revision_number > 0
        data["current_revision_number"] = ticket.current_revision_number
        data["original_net_weight"] = str(ticket.original_net_weight) if ticket.original_net_weight is not None else data["net_weight"]
        return data

    @classmethod
    def get_original_ticket_data(cls, ticket: WeighTicket) -> Dict[str, Any]:
        """Returns the original, unrevised weighing evidence recorded when ticket was first completed."""
        if ticket.current_revision_number == 0:
            return cls.get_effective_ticket_data(ticket)

        first_rev = TicketRevision.objects.filter(
            ticket=ticket,
            revision_number=1,
            status=TicketRevision.RevisionStatus.APPLIED
        ).first()

        if first_rev and first_rev.before_snapshot:
            data = dict(first_rev.before_snapshot)
            data["is_original_snapshot"] = True
            return data

        # Fallback to current ticket with original_net_weight
        data = cls.get_effective_ticket_data(ticket)
        if ticket.original_net_weight is not None:
            data["net_weight"] = str(ticket.original_net_weight)
        return data

    @classmethod
    def get_revision_history(cls, ticket: WeighTicket):
        """Returns the complete historical audit sequence of revisions for a ticket."""
        return ticket.revisions.select_related(
            "requested_by", "reviewed_by", "applied_by"
        ).order_by("-requested_at")
