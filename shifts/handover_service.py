import logging
from typing import Optional, Dict, Any, List, Tuple
from django.db import transaction, IntegrityError
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError, PermissionDenied

from shifts.models import (
    ShiftSession, ShiftSessionStatus, ShiftOperatorAssignment, ShiftAssignmentStatus,
    ShiftExceptionLog, ShiftHandover, ShiftHandoverStatus,
    ShiftHandoverItem, ShiftHandoverItemCategory
)
from weighbridge.models import WeighTicket, TicketStatus
from monitoring.models import DiscrepancyApproval, ApprovalStatus, MonitoringAlert, AlertType, AlertStatus
from audit.services import log_audit
from audit.models import AuditAction

logger = logging.getLogger(__name__)


class ShiftHandoverService:
    """
    Core industrial domain service governing formal shift handover workflows,
    operational snapshot capture, separation of duties, and supervisor intervention (Phase 4.2).
    """

    ALLOWED_TRANSITIONS = {
        ShiftHandoverStatus.DRAFT: [ShiftHandoverStatus.SUBMITTED, ShiftHandoverStatus.CANCELLED],
        ShiftHandoverStatus.SUBMITTED: [ShiftHandoverStatus.ACCEPTED, ShiftHandoverStatus.DISPUTED, ShiftHandoverStatus.CANCELLED],
        ShiftHandoverStatus.DISPUTED: [ShiftHandoverStatus.SUPERVISOR_RESOLVED, ShiftHandoverStatus.ACCEPTED, ShiftHandoverStatus.CANCELLED],
        ShiftHandoverStatus.ACCEPTED: [],
        ShiftHandoverStatus.SUPERVISOR_RESOLVED: [],
        ShiftHandoverStatus.CANCELLED: [],
    }

    @classmethod
    def get_active_handover_for_session(cls, session: ShiftSession) -> Optional[ShiftHandover]:
        """Returns active/in-progress handover for an outgoing session, if any."""
        return ShiftHandover.objects.filter(
            outgoing_session=session,
            status__in=[
                ShiftHandoverStatus.DRAFT,
                ShiftHandoverStatus.SUBMITTED,
                ShiftHandoverStatus.DISPUTED
            ]
        ).first()

    @classmethod
    def initiate_handover(
        cls,
        outgoing_session: ShiftSession,
        operator: User,
        incoming_operator: Optional[User] = None,
        incoming_session: Optional[ShiftSession] = None,
        outgoing_notes: str = ""
    ) -> ShiftHandover:
        """
        Initiates a shift handover draft.
        - Ensures session is ACTIVE.
        - Ensures operator is authorized and checked into this session (or is supervisor).
        - Reuses existing DRAFT if present, or raises ValidationError if in-progress.
        """
        if not (operator.is_superuser or (hasattr(operator, "profile") and operator.profile.can_operate_shift)):
            raise PermissionDenied("کاربر مجوز انجام عملیات تحویل و تحول شیفت را ندارد.")

        if outgoing_session.status != ShiftSessionStatus.ACTIVE:
            raise ValidationError(f"تنها برای جلسات شیفت فعال (ACTIVE) امکان آغاز تحویل شیفت وجود دارد (وضعیت جاری: {outgoing_session.get_status_display()}).")

        # Verify operator is checked into this session, unless supervisor
        is_supervisor = operator.is_superuser or (hasattr(operator, "profile") and operator.profile.can_manage_shifts)
        if not is_supervisor:
            is_checked_in = outgoing_session.assignments.filter(
                operator=operator,
                status=ShiftAssignmentStatus.CHECKED_IN
            ).exists()
            if not is_checked_in:
                raise ValidationError(f"اپراتور {operator.username} در جلسه شیفت جاری در وضعیت حضور فعال (CHECKED_IN) قرار ندارد.")

        with transaction.atomic():
            # Check for existing active handover
            existing = cls.get_active_handover_for_session(outgoing_session)
            if existing:
                if existing.status == ShiftHandoverStatus.DRAFT:
                    if incoming_operator:
                        existing.incoming_operator = incoming_operator
                    if incoming_session:
                        existing.incoming_session = incoming_session
                    if outgoing_notes:
                        existing.outgoing_notes = outgoing_notes
                    existing.save()
                    return existing
                else:
                    raise ValidationError(
                        f"برای این جلسه شیفت، تحویل دیگری با شناسه #{existing.pk} در وضعیت «{existing.get_status_display()}» در جریان است."
                    )

            handover = ShiftHandover.objects.create(
                outgoing_session=outgoing_session,
                incoming_session=incoming_session,
                outgoing_operator=operator,
                incoming_operator=incoming_operator,
                status=ShiftHandoverStatus.DRAFT,
                initiated_at=timezone.now(),
                outgoing_notes=outgoing_notes
            )
            logger.info("Shift handover #%s initiated by %s for session %s", handover.pk, operator.username, outgoing_session)
            return handover

    @classmethod
    def capture_operational_snapshot(cls, handover: ShiftHandover, operator: User) -> ShiftHandover:
        """
        Takes an immutable snapshot of all yard vehicles, waiting tickets, pending approvals,
        overdue alerts, and unresolved shift exceptions at the exact moment of handover submission.
        """
        with transaction.atomic():
            locked_handover = ShiftHandover.objects.select_for_update().get(pk=handover.pk)

            # Clear previous draft items if re-capturing
            locked_handover.items.all().delete()

            # 1. Vehicles in yard & tickets awaiting second weight
            yard_tickets = list(
                WeighTicket.objects.filter(status=TicketStatus.WAITING_SECOND)
                .select_related("product", "party", "vehicle", "driver", "first_weight_operator")
                .order_by("created_at")
            )

            # 2. Pending discrepancy approvals
            pending_approvals = list(
                DiscrepancyApproval.objects.filter(status=ApprovalStatus.PENDING)
                .select_related("ticket", "alert", "requested_by")
                .order_by("created_at")
            )

            # 3. Open long waiting alerts in yard
            overdue_alerts = list(
                MonitoringAlert.objects.filter(alert_type=AlertType.LONG_WAITING_TIME, status=AlertStatus.OPEN)
                .select_related("ticket")
                .order_by("created_at")
            )

            # 4. Unresolved out-of-shift exceptions
            unresolved_exceptions = list(
                ShiftExceptionLog.objects.filter(acknowledged_by__isnull=True)
                .select_related("ticket", "operator")
                .order_by("timestamp")
            )

            items_to_create = []

            # Group yard tickets by physical vehicle
            unique_vehicles: Dict[str, List[WeighTicket]] = {}
            for t in yard_tickets:
                plate_key = (t.license_plate_display or t.serial_number).strip()
                if plate_key not in unique_vehicles:
                    unique_vehicles[plate_key] = []
                unique_vehicles[plate_key].append(t)

            # 1. Populate unique Yard Vehicle Items
            for plate_key, v_tickets in unique_vehicles.items():
                primary_ticket = v_tickets[0]
                ticket_serials = [t.serial_number for t in v_tickets]
                items_to_create.append(
                    ShiftHandoverItem(
                        handover=locked_handover,
                        category=ShiftHandoverItemCategory.YARD_VEHICLE,
                        ticket=primary_ticket,
                        item_identifier=plate_key,
                        item_title=f"خودرو {plate_key} ({len(v_tickets)} قبض)",
                        source_status=primary_ticket.status,
                        source_timestamp=primary_ticket.created_at,
                        details={
                            "plate": plate_key,
                            "serial_number": primary_ticket.serial_number,
                            "ticket_serials": ticket_serials,
                            "ticket_count": len(v_tickets),
                            "primary_serial": primary_ticket.serial_number,
                            "first_weight": float(primary_ticket.first_weight) if primary_ticket.first_weight else None,
                            "first_weight_time": str(primary_ticket.first_weight_time) if primary_ticket.first_weight_time else None,
                            "first_weight_date": str(primary_ticket.first_weight_date) if primary_ticket.first_weight_date else None,
                            "first_weight_operator": primary_ticket.first_weight_operator.username if primary_ticket.first_weight_operator else None,
                            "product_name": primary_ticket.product.name if primary_ticket.product else None,
                            "party_name": primary_ticket.party.name if primary_ticket.party else None,
                            "driver_name": primary_ticket.driver.full_name if primary_ticket.driver else None,
                            "created_at": primary_ticket.created_at.isoformat() if primary_ticket.created_at else None,
                        }
                    )
                )

            # 2. Populate Waiting Second Weight Items (one per operational ticket)
            for ticket in yard_tickets:
                items_to_create.append(
                    ShiftHandoverItem(
                        handover=locked_handover,
                        category=ShiftHandoverItemCategory.WAITING_SECOND,
                        ticket=ticket,
                        item_identifier=ticket.serial_number,
                        item_title=f"قبض {ticket.serial_number} - در انتظار توزین دوم",
                        source_status=ticket.status,
                        source_timestamp=ticket.created_at,
                        details={
                            "serial_number": ticket.serial_number,
                            "plate": ticket.license_plate_display,
                            "first_weight": float(ticket.first_weight) if ticket.first_weight else None,
                            "product": ticket.product.name if ticket.product else None,
                        }
                    )
                )

            # Populate Pending Discrepancy Approval Items
            for approval in pending_approvals:
                items_to_create.append(
                    ShiftHandoverItem(
                        handover=locked_handover,
                        category=ShiftHandoverItemCategory.PENDING_APPROVAL,
                        ticket=approval.ticket,
                        discrepancy_approval=approval,
                        item_identifier=str(approval.pk),
                        item_title=f"مجوز مغایرت #{approval.pk} ({approval.get_discrepancy_type_display()}) - قبض {approval.ticket.serial_number}",
                        source_status=approval.status,
                        source_timestamp=approval.created_at,
                        details={
                            "approval_id": approval.pk,
                            "ticket_serial": approval.ticket.serial_number,
                            "discrepancy_type": approval.discrepancy_type,
                            "severity": approval.severity,
                            "reason": getattr(approval, "request_reason", ""),
                            "requested_by": approval.requested_by.username if approval.requested_by else None,
                            "created_at": approval.created_at.isoformat() if approval.created_at else None,
                        }
                    )
                )

            # Populate Overdue Alert Items
            for alert in overdue_alerts:
                items_to_create.append(
                    ShiftHandoverItem(
                        handover=locked_handover,
                        category=ShiftHandoverItemCategory.OVERDUE_ALERT,
                        ticket=alert.ticket,
                        monitoring_alert=alert,
                        item_identifier=str(alert.pk),
                        item_title=f"هشدار توقف طولانی #{alert.pk} - قبض {alert.ticket.serial_number if alert.ticket else 'نامشخص'}",
                        source_status=alert.status,
                        source_timestamp=alert.created_at,
                        details={
                            "alert_id": alert.pk,
                            "message": getattr(alert, "title", "") or getattr(alert, "reason", ""),
                            "severity": alert.severity,
                            "created_at": alert.created_at.isoformat() if alert.created_at else None,
                        }
                    )
                )

            # Populate Shift Exception Items
            for exc in unresolved_exceptions:
                items_to_create.append(
                    ShiftHandoverItem(
                        handover=locked_handover,
                        category=ShiftHandoverItemCategory.SHIFT_EXCEPTION,
                        ticket=exc.ticket,
                        shift_exception=exc,
                        item_identifier=str(exc.pk),
                        item_title=f"استثنای شیفت #{exc.pk} ({exc.get_weighing_phase_display()}) - قبض {exc.ticket.serial_number}",
                        source_status="UNACKNOWLEDGED",
                        source_timestamp=exc.timestamp,
                        details={
                            "exception_id": exc.pk,
                            "ticket_serial": exc.ticket.serial_number,
                            "weighing_phase": exc.weighing_phase,
                            "reason": exc.reason,
                            "operator": exc.operator.username if exc.operator else None,
                            "timestamp": exc.timestamp.isoformat() if exc.timestamp else None,
                            "notes": exc.notes,
                        }
                    )
                )

            # Bulk create items
            ShiftHandoverItem.objects.bulk_create(items_to_create)

            # Update handover metrics
            locked_handover.yard_vehicles_count = len(unique_vehicles)
            locked_handover.waiting_second_count = len(yard_tickets)
            locked_handover.pending_discrepancies_count = len(pending_approvals)
            locked_handover.overdue_waiting_count = len(overdue_alerts)
            locked_handover.unresolved_exceptions_count = len(unresolved_exceptions)
            locked_handover.save()

            if handover is not locked_handover:
                handover.yard_vehicles_count = locked_handover.yard_vehicles_count
                handover.waiting_second_count = locked_handover.waiting_second_count
                handover.pending_discrepancies_count = locked_handover.pending_discrepancies_count
                handover.overdue_waiting_count = locked_handover.overdue_waiting_count
                handover.unresolved_exceptions_count = locked_handover.unresolved_exceptions_count

            return locked_handover

    @classmethod
    def submit_handover(
        cls,
        handover: ShiftHandover,
        operator: User,
        checklist_data: Optional[Dict[str, Any]] = None,
        notes: str = ""
    ) -> ShiftHandover:
        """
        Outgoing operator finalizes and submits their handover declaration.
        Freezes the operational snapshot.
        Transitions DRAFT -> SUBMITTED.
        """
        with transaction.atomic():
            locked = ShiftHandover.objects.select_for_update().get(pk=handover.pk)

            # Validate transition
            if locked.status != ShiftHandoverStatus.DRAFT:
                raise ValidationError(f"فقط تحویل شیفت در وضعیت پیش‌نویس قابل ارسال است (وضعیت فعلی: {locked.get_status_display()}).")

            # Outgoing operator must submit their own handover (or supervisor)
            is_supervisor = operator.is_superuser or (hasattr(operator, "profile") and operator.profile.can_manage_shifts)
            if not is_supervisor and operator != locked.outgoing_operator:
                raise PermissionDenied("تنها اپراتور تحویل‌دهنده یا سرپرست مجاز به ارسال این تحویل شیفت می‌باشد.")

            # Update checklist declarations
            if checklist_data:
                locked.scale_zero_confirmed = bool(checklist_data.get("scale_zero_confirmed", False))
                locked.printer_paper_confirmed = bool(checklist_data.get("printer_paper_confirmed", False))
                locked.workstation_clean_confirmed = bool(checklist_data.get("workstation_clean_confirmed", False))
                locked.physical_documents_confirmed = bool(checklist_data.get("physical_documents_confirmed", False))
                locked.checklist_notes = str(checklist_data.get("checklist_notes", "")).strip()

            if notes:
                locked.outgoing_notes = notes.strip()

            # Persist checklist and notes before snapshot capture
            locked.save()

            # Capture snapshot and update metrics
            locked = cls.capture_operational_snapshot(locked, operator)

            # Transition state
            locked.status = ShiftHandoverStatus.SUBMITTED
            locked.submitted_at = timezone.now()
            locked.save()

            if handover is not locked:
                handover.status = locked.status
                handover.submitted_at = locked.submitted_at
                handover.yard_vehicles_count = locked.yard_vehicles_count
                handover.waiting_second_count = locked.waiting_second_count
                handover.pending_discrepancies_count = locked.pending_discrepancies_count
                handover.overdue_waiting_count = locked.overdue_waiting_count
                handover.unresolved_exceptions_count = locked.unresolved_exceptions_count

            # Formal audit log
            log_audit(
                action=AuditAction.SHIFT_HANDOVER_SUBMIT,
                model_name="ShiftHandover",
                record_id=locked.pk,
                record_repr=f"تحویل شیفت #{locked.pk} ({locked.outgoing_session})",
                user=operator,
                reason=locked.outgoing_notes or "ارسال تحویل شیفت توسط اپراتور تحویل‌دهنده",
                new_values={
                    "status": locked.status,
                    "yard_vehicles_count": locked.yard_vehicles_count,
                    "waiting_second_count": locked.waiting_second_count,
                    "pending_discrepancies_count": locked.pending_discrepancies_count,
                    "unresolved_exceptions_count": locked.unresolved_exceptions_count,
                    "scale_zero_confirmed": locked.scale_zero_confirmed,
                    "printer_paper_confirmed": locked.printer_paper_confirmed,
                },
                source="Web"
            )

            logger.info("Shift handover #%s successfully submitted by %s", locked.pk, operator.username)
            return locked

    @classmethod
    def accept_handover(
        cls,
        handover: ShiftHandover,
        operator: User,
        incoming_session: Optional[ShiftSession] = None,
        notes: str = ""
    ) -> ShiftHandover:
        """
        Incoming operator formally accepts operational responsibility.
        CRITICAL SEPARATION OF DUTIES:
        - Outgoing operator CANNOT accept their own handover (No self-approval).
        - User must be authenticated and have shift operation role.
        - Superusers cannot impersonate the incoming operator through ordinary acceptance.
        - Actor must be the designated incoming operator if one was specified.
        - Actor must be authorized/assigned to the incoming session if specified.
        Transitions SUBMITTED/DISPUTED -> ACCEPTED.
        """
        if not operator or not operator.is_authenticated:
            raise PermissionDenied("کاربر احراز هویت نشده است.")

        with transaction.atomic():
            locked = ShiftHandover.objects.select_for_update().get(pk=handover.pk)

            # Valid transitions
            if locked.status not in [ShiftHandoverStatus.SUBMITTED, ShiftHandoverStatus.DISPUTED]:
                raise ValidationError(f"تحویل شیفت در وضعیت فعلی «{locked.get_status_display()}» قابل پذیرش نیست.")

            # SEPARATION OF DUTIES ENFORCEMENT
            if operator == locked.outgoing_operator:
                raise ValidationError("اپراتور تحویل‌دهنده نمی‌تواند تحویل شیفت خود را تأیید و پذیرش نماید (اصل تفکیک وظایف).")

            # Check incoming operator role (superuser cannot bypass operator capability)
            if not (hasattr(operator, "profile") and operator.profile.can_operate_shift):
                raise PermissionDenied("کاربر مجوز اپراتوری برای پذیرش تحویل شیفت را ندارد.")

            # Designated operator check: An unrelated operator cannot accept someone else's handover
            if locked.incoming_operator and operator != locked.incoming_operator:
                raise PermissionDenied(
                    f"تنها اپراتور تحویل‌گیرنده تعیین‌شده ({locked.incoming_operator.get_full_name() or locked.incoming_operator.username}) مجاز به پذیرش این تحویل شیفت می‌باشد."
                )

            # Incoming session assignment check
            target_session = incoming_session or locked.incoming_session
            if target_session and target_session.assignments.exists():
                is_assigned = target_session.assignments.filter(
                    operator=operator,
                    status__in=[ShiftAssignmentStatus.ASSIGNED, ShiftAssignmentStatus.CHECKED_IN]
                ).exists()
                if not is_assigned:
                    raise ValidationError(
                        f"اپراتور {operator.username} به جلسه شیفت تحویل‌گیرنده «{target_session}» تخصیص داده نشده است."
                    )

            old_status = locked.status
            locked.status = ShiftHandoverStatus.ACCEPTED
            locked.incoming_operator = operator
            locked.accepted_at = timezone.now()
            if incoming_session:
                locked.incoming_session = incoming_session
            if notes:
                locked.incoming_notes = notes.strip()

            locked.full_clean()
            locked.save()

            # Audit log
            log_audit(
                action=AuditAction.SHIFT_HANDOVER_ACCEPT,
                model_name="ShiftHandover",
                record_id=locked.pk,
                record_repr=f"تحویل شیفت #{locked.pk} ({locked.outgoing_session})",
                user=operator,
                reason=notes or "پذیرش رسمی مسئولیت شیفت توسط اپراتور تحویل‌گیرنده",
                old_values={"status": old_status},
                new_values={
                    "status": locked.status,
                    "incoming_operator": operator.username,
                    "accepted_at": locked.accepted_at.isoformat(),
                    "incoming_session_id": locked.incoming_session.pk if locked.incoming_session else None,
                },
                source="Web"
            )

            logger.info("Shift handover #%s accepted by %s", locked.pk, operator.username)
            return locked

    @classmethod
    def dispute_handover(
        cls,
        handover: ShiftHandover,
        operator: User,
        dispute_reason: str,
        incoming_session: Optional[ShiftSession] = None,
        notes: str = ""
    ) -> ShiftHandover:
        """
        Incoming operator records an operational discrepancy/dispute.
        CRITICAL SEPARATION OF DUTIES:
        Outgoing operator CANNOT dispute their own handover.
        Transitions SUBMITTED -> DISPUTED.
        """
        if not operator or not operator.is_authenticated:
            raise PermissionDenied("کاربر احراز هویت نشده است.")

        dispute_reason = str(dispute_reason).strip()
        if len(dispute_reason) < 5:
            raise ValidationError("ثبت علت دقیق مغایرت یا اختلاف الزامی است (حداقل ۵ کاراکتر).")

        with transaction.atomic():
            locked = ShiftHandover.objects.select_for_update().get(pk=handover.pk)

            if locked.status != ShiftHandoverStatus.SUBMITTED:
                raise ValidationError(f"تنها تحویل شیفت ارسال‌شده قابل ثبت مغایرت است (وضعیت فعلی: {locked.get_status_display()}).")

            if operator == locked.outgoing_operator:
                raise ValidationError("اپراتور تحویل‌دهنده نمی‌تواند تحویل شیفت خود را رد یا مغایرت‌دار کند.")

            if not (hasattr(operator, "profile") and operator.profile.can_operate_shift):
                raise PermissionDenied("کاربر مجوز اپراتوری برای ثبت مغایرت تحویل شیفت را ندارد.")

            # Designated operator check
            if locked.incoming_operator and operator != locked.incoming_operator:
                raise PermissionDenied(
                    f"تنها اپراتور تحویل‌گیرنده تعیین‌شده ({locked.incoming_operator.get_full_name() or locked.incoming_operator.username}) مجاز به ثبت مغایرت در این تحویل شیفت می‌باشد."
                )

            # Incoming session assignment check
            target_session = incoming_session or locked.incoming_session
            if target_session and target_session.assignments.exists():
                is_assigned = target_session.assignments.filter(
                    operator=operator,
                    status__in=[ShiftAssignmentStatus.ASSIGNED, ShiftAssignmentStatus.CHECKED_IN]
                ).exists()
                if not is_assigned:
                    raise ValidationError(
                        f"اپراتور {operator.username} به جلسه شیفت تحویل‌گیرنده «{target_session}» تخصیص داده نشده است."
                    )

            old_status = locked.status
            locked.status = ShiftHandoverStatus.DISPUTED
            locked.incoming_operator = operator
            locked.disputed_at = timezone.now()
            locked.dispute_reason = dispute_reason
            if incoming_session:
                locked.incoming_session = incoming_session
            if notes:
                locked.incoming_notes = notes.strip()

            locked.full_clean()
            locked.save()

            log_audit(
                action=AuditAction.SHIFT_HANDOVER_DISPUTE,
                model_name="ShiftHandover",
                record_id=locked.pk,
                record_repr=f"تحویل شیفت #{locked.pk} ({locked.outgoing_session})",
                user=operator,
                reason=dispute_reason,
                old_values={"status": old_status},
                new_values={
                    "status": locked.status,
                    "incoming_operator": operator.username,
                    "dispute_reason": dispute_reason,
                    "disputed_at": locked.disputed_at.isoformat(),
                },
                source="Web"
            )

            logger.warning("Shift handover #%s disputed by %s: %s", locked.pk, operator.username, dispute_reason)
            return locked

    @classmethod
    def resolve_dispute(
        cls,
        handover: ShiftHandover,
        supervisor: User,
        resolution_notes: str,
        action: str = "RESOLVE",
        responsible_operator: Optional[User] = None
    ) -> ShiftHandover:
        """
        Supervisor intervenes to resolve a disputed handover (or in emergency operator absence).
        Requires can_manage_shifts role.
        Action:
            "RESOLVE" -> SUPERVISOR_RESOLVED
            "CANCEL"  -> CANCELLED
        Preserves original incoming operator dispute reason and timestamp.
        """
        if not supervisor or not supervisor.is_authenticated:
            raise PermissionDenied("کاربر احراز هویت نشده است.")

        if not (supervisor.is_superuser or (hasattr(supervisor, "profile") and supervisor.profile.can_manage_shifts)):
            raise PermissionDenied("تنها سرپرست یا مدیر سیستم مجاز به حل‌وفصل و تصمیم‌گیری در خصوص اختلافات تحویل شیفت است.")

        resolution_notes = str(resolution_notes).strip()
        if len(resolution_notes) < 5:
            raise ValidationError("ثبت شرح و دستورات سرپرست جهت تصمیم‌گیری الزامی است (حداقل ۵ کاراکتر).")

        with transaction.atomic():
            locked = ShiftHandover.objects.select_for_update().get(pk=handover.pk)

            if locked.status not in [ShiftHandoverStatus.DISPUTED, ShiftHandoverStatus.SUBMITTED]:
                raise ValidationError(f"تحویل شیفت در وضعیت «{locked.get_status_display()}» قابل مداخله سرپرست نیست.")

            # CRITICAL SEPARATION OF DUTIES: Supervisor cannot be the outgoing operator
            if supervisor == locked.outgoing_operator:
                raise ValidationError("سرپرستی که خود اپراتور تحویل‌دهنده این شیفت بوده است، مجاز به حل‌وفصل و تایید اختلاف پرونده خود نمی‌باشد (اصل تفکیک وظایف).")

            old_status = locked.status
            if action.upper() == "RESOLVE":
                locked.status = ShiftHandoverStatus.SUPERVISOR_RESOLVED
                audit_action = AuditAction.SHIFT_HANDOVER_RESOLVE

                # Responsible operator verification
                if responsible_operator:
                    if responsible_operator == locked.outgoing_operator:
                        raise ValidationError("اپراتور تحویل‌دهنده نمی‌تواند به عنوان اپراتور مسئول نهایی تعیین شود.")
                    if not (hasattr(responsible_operator, "profile") and responsible_operator.profile.can_operate_shift):
                        raise ValidationError(f"کاربر {responsible_operator.username} فاقد مجوز اپراتوری شیفت است.")
                    locked.incoming_operator = responsible_operator
                elif not locked.incoming_operator:
                    raise ValidationError("تعیین اپراتور مسئول نهایی شیفت جهت حل‌وفصل و تایید الزامی است.")

            elif action.upper() == "CANCEL":
                locked.status = ShiftHandoverStatus.CANCELLED
                audit_action = AuditAction.CANCEL
            else:
                raise ValidationError(f"اقدام انتخابی «{action}» نامعتبر است.")

            locked.supervisor = supervisor
            locked.supervisor_resolved_at = timezone.now()
            locked.supervisor_resolution_notes = resolution_notes
            locked.full_clean()
            locked.save()

            log_audit(
                action=audit_action,
                model_name="ShiftHandover",
                record_id=locked.pk,
                record_repr=f"تحویل شیفت #{locked.pk} ({locked.outgoing_session})",
                user=supervisor,
                reason=resolution_notes,
                old_values={"status": old_status},
                new_values={
                    "status": locked.status,
                    "supervisor": supervisor.username,
                    "incoming_operator": locked.incoming_operator.username if locked.incoming_operator else None,
                    "resolved_at": locked.supervisor_resolved_at.isoformat(),
                    "notes": resolution_notes
                },
                source="Web"
            )

            logger.info("Shift handover #%s resolved by supervisor %s (status: %s)", locked.pk, supervisor.username, locked.status)
            return locked

    @classmethod
    def substitute_incoming_operator(
        cls,
        handover: ShiftHandover,
        supervisor: User,
        new_incoming_operator: User,
        reason: str
    ) -> ShiftHandover:
        """
        Documented exceptional workflow for supervisor substitution of the incoming operator
        (e.g., when the originally designated operator is absent or replaced).
        """
        if not supervisor or not supervisor.is_authenticated:
            raise PermissionDenied("کاربر احراز هویت نشده است.")

        if not (supervisor.is_superuser or (hasattr(supervisor, "profile") and supervisor.profile.can_manage_shifts)):
            raise PermissionDenied("تنها سرپرست یا مدیر سیستم مجاز به تغییر یا تعویض اضطراری اپراتور تحویل‌گیرنده است.")

        reason = str(reason).strip()
        if len(reason) < 5:
            raise ValidationError("ثبت علت تعویض اپراتور تحویل‌گیرنده الزامی است (حداقل ۵ کاراکتر).")

        with transaction.atomic():
            locked = ShiftHandover.objects.select_for_update().get(pk=handover.pk)

            if locked.is_finalized:
                raise ValidationError(f"امکان تغییر اپراتور برای تحویل نهایی‌شده (وضعیت: {locked.get_status_display()}) وجود ندارد.")

            if supervisor == locked.outgoing_operator:
                raise ValidationError("اپراتور تحویل‌دهنده مجاز به مداخله سرپرستی در تعویض تحویل‌گیرنده نمی‌باشد.")

            if new_incoming_operator == locked.outgoing_operator:
                raise ValidationError("اپراتور جدید تحویل‌گیرنده نمی‌تواند با اپراتور تحویل‌دهنده یکسان باشد (اصل تفکیک وظایف).")

            if not (hasattr(new_incoming_operator, "profile") and new_incoming_operator.profile.can_operate_shift):
                raise ValidationError(f"کاربر {new_incoming_operator.username} مجوز اپراتوری شیفت را ندارد.")

            old_operator_name = locked.incoming_operator.username if locked.incoming_operator else "تعیین‌نشده"
            locked.incoming_operator = new_incoming_operator
            locked.save()

            log_audit(
                action=AuditAction.SHIFT_SUBSTITUTION,
                model_name="ShiftHandover",
                record_id=locked.pk,
                record_repr=f"تعویض اپراتور تحویل‌گیرنده در تحویل شیفت #{locked.pk}",
                user=supervisor,
                reason=reason,
                old_values={"incoming_operator": old_operator_name},
                new_values={
                    "incoming_operator": new_incoming_operator.username,
                    "substituted_by": supervisor.username
                },
                source="Web"
            )

            logger.info(
                "Shift handover #%s incoming operator substituted by supervisor %s from %s to %s",
                locked.pk, supervisor.username, old_operator_name, new_incoming_operator.username
            )
            return locked

    @classmethod
    def cancel_handover(
        cls,
        handover: ShiftHandover,
        user: User,
        reason: str = ""
    ) -> ShiftHandover:
        """
        Cancels a draft or submitted handover.
        If DISPUTED, only a supervisor can cancel or resolve it.
        """
        if not user or not user.is_authenticated:
            raise PermissionDenied("کاربر احراز هویت نشده است.")

        with transaction.atomic():
            locked = ShiftHandover.objects.select_for_update().get(pk=handover.pk)

            if locked.is_finalized:
                raise ValidationError(f"امکان لغو تحویل شیفت نهایی‌شده (وضعیت: {locked.get_status_display()}) وجود ندارد.")

            is_supervisor = user.is_superuser or (hasattr(user, "profile") and user.profile.can_manage_shifts)

            if locked.status == ShiftHandoverStatus.DISPUTED:
                if not is_supervisor:
                    raise PermissionDenied("تحویل شیفت دارای اختلاف تنها توسط سرپرست قابل لغو یا تعیین‌تکلیف می‌باشد.")
                if user == locked.outgoing_operator:
                    raise ValidationError("اپراتور تحویل‌دهنده مجاز به لغو پرونده اختلافی خود نیست.")
            else:
                if not is_supervisor and user != locked.outgoing_operator:
                    raise PermissionDenied("تنها اپراتور تحویل‌دهنده یا سرپرست مجاز به لغو فرآیند تحویل می‌باشند.")

            old_status = locked.status
            locked.status = ShiftHandoverStatus.CANCELLED
            if reason:
                locked.outgoing_notes = f"{locked.outgoing_notes}\n[لغو توسط {user.username}]: {reason}".strip()
            locked.save()

            log_audit(
                action=AuditAction.CANCEL,
                model_name="ShiftHandover",
                record_id=locked.pk,
                record_repr=f"تحویل شیفت #{locked.pk} ({locked.outgoing_session})",
                user=user,
                reason=reason or "لغو فرآیند تحویل شیفت",
                old_values={"status": old_status},
                new_values={"status": locked.status},
                source="Web"
            )

            logger.info("Shift handover #%s cancelled by %s", locked.pk, user.username)
            return locked

    @classmethod
    def get_live_operational_delta(cls, handover: ShiftHandover) -> Dict[str, Any]:
        """
        Calculates the differences between the snapshot captured at handover submission
        and the current live operational state of the weighbridge.
        Crucially:
        - NEVER mutates or overwrites the frozen snapshot records.
        - Classifies completed tickets as routine operational progression, NOT fraud.
        - Detects newly arrived vehicles in the yard after submission.
        - Detects resolved or newly requested discrepancy approvals.
        """
        if handover.status == ShiftHandoverStatus.DRAFT:
            return {"has_changes": False}

        snapshot_ticket_ids = set(
            handover.items.filter(
                category=ShiftHandoverItemCategory.WAITING_SECOND,
                ticket__isnull=False
            ).values_list("ticket_id", flat=True)
        )

        # 1. Snapshot tickets that completed second weighing since submission
        completed_since_submission = list(
            WeighTicket.objects.filter(
                id__in=snapshot_ticket_ids,
                status=TicketStatus.COMPLETED
            ).select_related("product", "party").order_by("-updated_at")
        )

        # 2. Snapshot tickets still waiting in yard
        still_waiting_tickets = list(
            WeighTicket.objects.filter(
                id__in=snapshot_ticket_ids,
                status=TicketStatus.WAITING_SECOND
            ).select_related("product", "party").order_by("created_at")
        )

        # 3. Newly arrived vehicles in yard since handover submission
        new_yard_arrivals = list(
            WeighTicket.objects.filter(
                status=TicketStatus.WAITING_SECOND
            ).exclude(
                id__in=snapshot_ticket_ids
            ).select_related("product", "party").order_by("created_at")
        )

        # 4. Approvals delta
        snapshot_approval_ids = set(
            handover.items.filter(
                category=ShiftHandoverItemCategory.PENDING_APPROVAL,
                discrepancy_approval__isnull=False
            ).values_list("discrepancy_approval_id", flat=True)
        )

        resolved_approvals = list(
            DiscrepancyApproval.objects.filter(
                id__in=snapshot_approval_ids
            ).exclude(
                status=ApprovalStatus.PENDING
            ).select_related("ticket", "reviewed_by").order_by("-reviewed_at")
        )

        new_pending_approvals = list(
            DiscrepancyApproval.objects.filter(
                status=ApprovalStatus.PENDING
            ).exclude(
                id__in=snapshot_approval_ids
            ).select_related("ticket", "requested_by").order_by("created_at")
        )

        has_changes = bool(
            completed_since_submission or new_yard_arrivals or
            resolved_approvals or new_pending_approvals
        )

        return {
            "has_changes": has_changes,
            "completed_since_submission": completed_since_submission,
            "completed_tickets": completed_since_submission,
            "completed_count": len(completed_since_submission),
            "completed_since_snapshot_count": len(completed_since_submission),
            "still_waiting_tickets": still_waiting_tickets,
            "still_waiting_count": len(still_waiting_tickets),
            "new_yard_arrivals": new_yard_arrivals,
            "new_yard_tickets": new_yard_arrivals,
            "new_arrivals_count": len(new_yard_arrivals),
            "new_yard_arrivals_count": len(new_yard_arrivals),
            "resolved_approvals": resolved_approvals,
            "resolved_approvals_count": len(resolved_approvals),
            "new_pending_approvals": new_pending_approvals,
            "new_pending_count": len(new_pending_approvals),
        }
