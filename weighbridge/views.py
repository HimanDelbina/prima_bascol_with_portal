from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse, Http404
from django.contrib import messages
from django.db.models import Q, Sum
from django.core.paginator import Paginator
from django.utils import timezone
from datetime import datetime, time
from decimal import Decimal
import re

from weighbridge.models import WeighTicket, TicketStatus, WeightMode, EmergencyWeighTicket, EmergencyTicketStatus, TicketRevision
from weighbridge.forms import TicketCreateForm, SecondWeightForm, TicketEditManagerForm
from weighbridge.services import TicketCalculationService, VehicleDriverRegistrationService
from core.weight_provider import get_active_weight_provider
from core.jalali import (
    jalali_to_gregorian, get_today_jalali, format_jalali_date,
    get_today_gregorian, get_jalali_range_gregorian
)
from core.models import SystemSetting
from masterdata.models import Product, Party, Driver, Vehicle, OperationType
from accounts.decorators import role_required, manager_or_admin_required, weighbridge_role_required
from audit.services import log_audit
from audit.models import AuditAction, AuditLog
from monitoring.services.anomaly_engine import AnomalyDetectionEngine
from monitoring.services.discrepancy_service import DiscrepancyApprovalService
from monitoring.models import AlertType, ApprovalStatus, DiscrepancyApproval
from django.core.exceptions import ValidationError, PermissionDenied
from weighbridge.plate_policy import DailyPlatePolicy, can_manage_plate_exceptions, can_manage_plate_autofill, normalize_plate
from shifts.services import ShiftResolutionService
from shifts.models import ShiftExceptionLog

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager", "weighbridge_operator")
def ticket_create(request):
    """
    Main high-speed weighbridge registration view.
    Registers 1st weight (open ticket) or both weights directly.
    """
    provider = get_active_weight_provider()

    if request.method == "POST":
        form = TicketCreateForm(request.POST)
        if form.is_valid():
            ticket = form.save(commit=False)
            
            # Dates and Times
            first_date_j = form.cleaned_data.get("first_weight_date_jalali")
            g_first_date = jalali_to_gregorian(first_date_j) if first_date_j else get_today_gregorian()
            ticket.first_weight_date = g_first_date
            
            first_time_str = form.cleaned_data.get("first_weight_time_str")
            if first_time_str and ":" in first_time_str:
                try:
                    h, m = first_time_str.split(":")[:2]
                    ticket.first_weight_time = time(int(h), int(m))
                except Exception:
                    ticket.first_weight_time = timezone.localtime().time()
            else:
                ticket.first_weight_time = timezone.localtime().time()

            ticket.first_weight_operator = request.user
            _, is_w1_out, w1_reason, w1_notes = ShiftResolutionService.record_weighing_shift(
                ticket, is_second_weight=False, operator=request.user
            )

            # Check if second weight is also provided (direct complete mode)
            w2_raw = form.cleaned_data.get("second_weight")
            has_w2 = w2_raw is not None and str(w2_raw).strip() != "" and Decimal(str(w2_raw)) > 0
            w2_reason = ""
            w2_notes = ""
            
            if has_w2:
                ticket.second_weight = Decimal(str(w2_raw))
                second_date_j = form.cleaned_data.get("second_weight_date_jalali")
                ticket.second_weight_date = jalali_to_gregorian(second_date_j) if second_date_j else get_today_gregorian()
                
                second_time_str = form.cleaned_data.get("second_weight_time_str")
                if second_time_str and ":" in second_time_str:
                    try:
                        h, m = second_time_str.split(":")[:2]
                        ticket.second_weight_time = time(int(h), int(m))
                    except Exception:
                        ticket.second_weight_time = timezone.localtime().time()
                else:
                    ticket.second_weight_time = timezone.localtime().time()
                
                ticket.second_weight_operator = request.user
                _, is_w2_out, w2_reason, w2_notes = ShiftResolutionService.record_weighing_shift(
                    ticket, is_second_weight=True, operator=request.user
                )
                ticket.status = TicketStatus.COMPLETED
            else:
                ticket.second_weight = None
                ticket.second_weight_date = None
                ticket.second_weight_time = None
                ticket.second_weight_operator = None
                ticket.status = TicketStatus.WAITING_SECOND

            # Perform calculations via TicketCalculationService
            calc_results = TicketCalculationService.calculate_ticket(
                first_weight=ticket.first_weight,
                second_weight=ticket.second_weight,
                sent_weight=ticket.sent_weight,
                loss_percent=ticket.loss_percent,
                manual_loss_weight=ticket.loss_weight if ticket.is_loss_overridden else None,
                product=ticket.product,
                is_loss_overridden=ticket.is_loss_overridden
            )

            ticket.gross_weight = calc_results["gross_weight"]
            ticket.tare_weight = calc_results["tare_weight"]
            ticket.net_weight = calc_results["net_weight"]
            ticket.loss_percent = calc_results["loss_percent"]
            ticket.loss_weight = calc_results["loss_weight"]
            ticket.final_weight = calc_results["final_weight"]
            ticket.weight_difference = calc_results["weight_difference"]
            ticket.weight_difference_percent = calc_results["weight_difference_percent"]
            ticket.is_tolerance_exceeded = calc_results["is_tolerance_exceeded"]

            if has_w2:
                eval_res = DiscrepancyApprovalService.evaluate_ticket_discrepancies(ticket, trial_weights=calc_results)
                if not eval_res["can_finalize"]:
                    ticket.status = TicketStatus.WAITING_SECOND
                    messages.warning(
                        request,
                        f"هشدار پایش هوشمند: {eval_res['blocking_reason']} "
                        "قبض صادر شد اما تکمیل نهایی آن در وضعیت «در انتظار وزن دوم / مجوز سرپرست» باقی ماند."
                    )

            # Auto-register or link Vehicle and Driver into system MasterData
            VehicleDriverRegistrationService.resolve_or_create(ticket, form.cleaned_data)

            # Prevent duplicate first-weighing transaction if vehicle already has an open ticket in yard
            if not has_w2:
                norm_p = normalize_plate(ticket.license_plate_display)
                if norm_p:
                    from django.db.models.functions import Coalesce, TruncDate
                    from weighbridge.models import PlateRegistrationException
                    has_supervisor_exception = PlateRegistrationException.objects.filter(normalized_plate=norm_p, is_active=True).exists()
                    if not has_supervisor_exception:
                        reg_day_target = ticket.first_weight_date or timezone.localdate()
                        open_conflict = WeighTicket.objects.filter(
                            normalized_plate=norm_p,
                            status__in=[TicketStatus.WAITING_SECOND, TicketStatus.WAITING_FIRST, TicketStatus.FIRST_REGISTERED]
                        ).annotate(
                            reg_day=Coalesce("first_weight_date", TruncDate("created_at"))
                        ).filter(reg_day=reg_day_target).exclude(pk=ticket.pk if ticket.pk else None).first()
                        if open_conflict:
                            form.add_error("license_plate_display", f"خودرو با پلاک «{ticket.license_plate_display}» در حال حاضر دارای قبض باز شماره {open_conflict.serial_number} (در انتظار وزن دوم) در محوطه است. ثبت مجدد وزن اول مجاز نیست.")
                            sales_op_ids = list(OperationType.objects.filter(Q(direction='outbound') | Q(name__icontains='فروش')).values_list('id', flat=True))
                            return render(request, "weighbridge/ticket_create.html", {
                                "form": form, "title": "ثبت باسکول و توزین جدید", "settings": SystemSetting.get_settings(),
                                "can_manage_plate_exceptions": can_manage_plate_exceptions(request.user),
                                "can_manage_plate_autofill": can_manage_plate_autofill(request.user),
                                "sales_op_ids": sales_op_ids,
                            })

            try:
                DailyPlatePolicy.save(ticket, user=request.user, assign_serial=True)
            except ValidationError as exc:
                form.add_error(None, exc)
                sales_op_ids = list(OperationType.objects.filter(Q(direction='outbound') | Q(name__icontains='فروش')).values_list('id', flat=True))
                return render(request, "weighbridge/ticket_create.html", {
                    "form": form, "title": "ثبت باسکول و توزین جدید", "settings": SystemSetting.get_settings(),
                    "can_manage_plate_exceptions": can_manage_plate_exceptions(request.user),
                    "can_manage_plate_autofill": can_manage_plate_autofill(request.user),
                    "sales_op_ids": sales_op_ids,
                })

            # Record shift exception idempotently if out of shift
            if ticket.first_weight_out_of_shift:
                ShiftResolutionService.log_shift_exception(
                    ticket=ticket,
                    weighing_phase="FIRST",
                    operator=request.user,
                    reason=w1_reason,
                    notes=w1_notes or "توزین اول بدون شیفت فعال ثبت شد (تداوم عملیاتی حفظ گردید)."
                )
            if has_w2 and ticket.second_weight_out_of_shift:
                ShiftResolutionService.log_shift_exception(
                    ticket=ticket,
                    weighing_phase="SECOND",
                    operator=request.user,
                    reason=w2_reason,
                    notes=w2_notes or "توزین مستقیم دوم بدون شیفت فعال ثبت شد (تداوم عملیاتی حفظ گردید)."
                )

            # Audit Log
            log_audit(
                action=AuditAction.CREATE,
                model_name="WeighTicket",
                record_id=ticket.id,
                record_repr=f"قبض شماره {ticket.serial_number}",
                new_values={
                    "serial": ticket.serial_number,
                    "freight_amount": str(ticket.freight_amount) if ticket.freight_amount is not None else None,
                    "plate": ticket.license_plate_display,
                    "first_weight": float(ticket.first_weight),
                    "status": ticket.status
                },
                reason="ثبت اولیه قبض باسکول"
            )

            # Smart Monitoring Anomaly Detection
            alerts = AnomalyDetectionEngine.run_for_ticket(ticket)
            if alerts:
                messages.warning(request, f"پایش هوشمند: {len(alerts)} هشدار برای این قبض شناسایی شد.")

            action_btn = request.POST.get("submit_action", "save_and_new")
            if ticket.status == TicketStatus.COMPLETED:
                messages.success(request, f"قبض شماره {ticket.serial_number} با موفقیت تکمیل و ثبت نهایی شد.")
                if action_btn == "save_and_print":
                    return redirect(f"/weighbridge/tickets/{ticket.id}/print/")
                elif action_btn == "save_and_new":
                    return redirect("weighbridge:ticket_create")
                elif action_btn in ("save_and_yard", "save_yard"):
                    return redirect("weighbridge:trucks_in_yard")
                return redirect("weighbridge:ticket_detail", pk=ticket.id)
            else:
                messages.success(request, f"قبض شماره {ticket.serial_number} با موفقیت ثبت شد (خودرو در انتظار وزن دوم).")
                if action_btn == "save_and_print":
                    return redirect(f"/weighbridge/tickets/{ticket.id}/print/")
                elif action_btn in ("save_and_yard", "save_yard"):
                    return redirect("weighbridge:trucks_in_yard")
                else:
                    # Default action: Save & New (immediately open clean form for next vehicle)
                    return redirect("weighbridge:ticket_create")
    else:
        # Prepopulate with duplicate params if any
        initial_data = {}
        dup_id = request.GET.get("duplicate_from")
        if dup_id:
            try:
                orig = WeighTicket.objects.get(pk=dup_id)
                initial_data = {
                    "operation_type": orig.operation_type,
                    "party": orig.party,
                    "product": orig.product,
                    "vehicle": orig.vehicle,
                    "driver": orig.driver,
                    "driver_name_custom": orig.driver_name_custom,
                    "driver_mobile_custom": orig.driver_mobile_custom,
                    "license_plate_display": orig.license_plate_display,
                    "origin": orig.origin,
                    "destination": orig.destination,
                    "unload_location": orig.unload_location,
                }
                parts = re.fullmatch(r"(\d{2})(.+?)(\d{3})(\d{2})", normalize_plate(orig.license_plate_display))
                if parts:
                    initial_data.update(dict(zip(("plate_part1", "plate_letter", "plate_part2", "plate_iran"), parts.groups())))
            except WeighTicket.DoesNotExist:
                pass

        form = TicketCreateForm(initial=initial_data)

    settings_obj = SystemSetting.get_settings()
    sales_op_ids = list(OperationType.objects.filter(Q(direction='outbound') | Q(name__icontains='فروش')).values_list('id', flat=True))
    return render(request, "weighbridge/ticket_create.html", {
        "form": form,
        "title": "ثبت باسکول و توزین جدید",
        "settings": settings_obj,
        "can_manage_plate_exceptions": can_manage_plate_exceptions(request.user),
        "can_manage_plate_autofill": can_manage_plate_autofill(request.user),
        "sales_op_ids": sales_op_ids,
    })


@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager", "weighbridge_operator")
def ticket_second_weight(request, pk):
    """
    Second weight registration view for completing an open weigh ticket.
    """
    ticket = get_object_or_404(WeighTicket, pk=pk)

    if ticket.status == TicketStatus.CANCELLED:
        messages.error(request, "امکان ثبت وزن برای قبض ابطال‌شده وجود ندارد.")
        return redirect("weighbridge:ticket_detail", pk=ticket.pk)
    if ticket.status == TicketStatus.COMPLETED and not (request.user.is_superuser or request.user.profile.can_edit_completed_ticket):
        messages.error(request, "این قبض قبلاً تکمیل شده است و فقط مدیر باسکول مجاز به ویرایش آن می‌باشد.")
        return redirect("weighbridge:ticket_detail", pk=ticket.id)

    action_btn = request.POST.get("submit_action") if request.method == "POST" else None

    # 1. Handle explicit Request Approval from second weighing screen
    if request.method == "POST" and action_btn == "request_approval":
        form = SecondWeightForm(request.POST, instance=ticket)
        if form.is_valid():
            req_reason = request.POST.get("request_reason", "").strip()
            if not req_reason or len(req_reason) < 5:
                messages.error(request, "ثبت دلیل موجه جهت ارسال درخواست تأیید سرپرست (حداقل ۵ کاراکتر) الزامی است.")
            else:
                ticket = form.save(commit=False)
                sec_date_j = form.cleaned_data.get("second_weight_date_jalali")
                ticket.second_weight_date = jalali_to_gregorian(sec_date_j) if sec_date_j else get_today_gregorian()
                sec_time_str = form.cleaned_data.get("second_weight_time_str")
                if sec_time_str and ":" in sec_time_str:
                    try:
                        h, m = sec_time_str.split(":")[:2]
                        ticket.second_weight_time = time(int(h), int(m))
                    except Exception:
                        ticket.second_weight_time = timezone.localtime().time()
                else:
                    ticket.second_weight_time = timezone.localtime().time()

                calc_results = TicketCalculationService.calculate_ticket(
                    first_weight=ticket.first_weight,
                    second_weight=ticket.second_weight,
                    sent_weight=ticket.sent_weight,
                    loss_percent=ticket.loss_percent,
                    manual_loss_weight=ticket.loss_weight if ticket.is_loss_overridden else None,
                    product=ticket.product,
                    is_loss_overridden=ticket.is_loss_overridden
                )
                ticket.gross_weight = calc_results["gross_weight"]
                ticket.tare_weight = calc_results["tare_weight"]
                ticket.net_weight = calc_results["net_weight"]
                ticket.loss_percent = calc_results["loss_percent"]
                ticket.loss_weight = calc_results["loss_weight"]
                ticket.final_weight = calc_results["final_weight"]
                ticket.weight_difference = calc_results["weight_difference"]
                ticket.weight_difference_percent = calc_results["weight_difference_percent"]
                ticket.is_tolerance_exceeded = calc_results["is_tolerance_exceeded"]
                ticket.status = TicketStatus.WAITING_SECOND
                ticket.second_weight_operator = request.user
                ticket.save()

                try:
                    approval = DiscrepancyApprovalService.request_approval(
                        ticket=ticket,
                        user=request.user,
                        reason=req_reason,
                        discrepancy_type=AlertType.WEIGHT_DISCREPANCY,
                        gross=calc_results["gross_weight"],
                        tare=calc_results["tare_weight"],
                        net=calc_results["net_weight"],
                        product=ticket.product,
                        sent_weight=ticket.sent_weight,
                    )
                    AnomalyDetectionEngine.run_for_ticket(ticket)
                    messages.success(request, f"درخواست تأیید مغایرت برای قبض {ticket.serial_number} با موفقیت ثبت شد و به کارتابل سرپرست ارسال گردید.")
                    return redirect("weighbridge:trucks_in_yard")
                except ValidationError as exc:
                    messages.error(request, f"خطا در ثبت درخواست: {exc}")

    elif request.method == "POST":
        form = SecondWeightForm(request.POST, instance=ticket)
        if form.is_valid():
            ticket = form.save(commit=False)
            
            # Second weight date & time
            sec_date_j = form.cleaned_data.get("second_weight_date_jalali")
            ticket.second_weight_date = jalali_to_gregorian(sec_date_j) if sec_date_j else get_today_gregorian()
            
            sec_time_str = form.cleaned_data.get("second_weight_time_str")
            if sec_time_str and ":" in sec_time_str:
                try:
                    h, m = sec_time_str.split(":")[:2]
                    ticket.second_weight_time = time(int(h), int(m))
                except Exception:
                    ticket.second_weight_time = timezone.localtime().time()
            else:
                ticket.second_weight_time = timezone.localtime().time()

            ticket.second_weight_operator = request.user
            _, is_w2_out, w2_reason, w2_notes = ShiftResolutionService.record_weighing_shift(
                ticket, is_second_weight=True, operator=request.user
            )

            # Calculate Gross, Tare, Net, Loss, Final
            calc_results = TicketCalculationService.calculate_ticket(
                first_weight=ticket.first_weight,
                second_weight=ticket.second_weight,
                sent_weight=ticket.sent_weight,
                loss_percent=ticket.loss_percent,
                manual_loss_weight=ticket.loss_weight if ticket.is_loss_overridden else None,
                product=ticket.product,
                is_loss_overridden=ticket.is_loss_overridden
            )

            ticket.gross_weight = calc_results["gross_weight"]
            ticket.tare_weight = calc_results["tare_weight"]
            ticket.net_weight = calc_results["net_weight"]
            ticket.loss_percent = calc_results["loss_percent"]
            ticket.loss_weight = calc_results["loss_weight"]
            ticket.final_weight = calc_results["final_weight"]
            ticket.weight_difference = calc_results["weight_difference"]
            ticket.weight_difference_percent = calc_results["weight_difference_percent"]
            ticket.is_tolerance_exceeded = calc_results["is_tolerance_exceeded"]

            # Phase 3.1: Invalidate any stale approval if weights or parameters changed from approved snapshot
            DiscrepancyApprovalService.check_and_invalidate_stale_approvals(
                ticket,
                calc_results["gross_weight"],
                calc_results["tare_weight"],
                calc_results["net_weight"],
                current_product=ticket.product,
                current_sent_weight=ticket.sent_weight,
            )

            # Evaluate discrepancies and blocking rules
            eval_res = DiscrepancyApprovalService.evaluate_ticket_discrepancies(
                ticket,
                trial_weights=calc_results
            )

            if not eval_res["can_finalize"]:
                # Blocking discrepancy without approval -> preserve entered weights, keep WAITING_SECOND
                ticket.status = TicketStatus.WAITING_SECOND
                ticket.save()
                if ticket.second_weight_out_of_shift:
                    ShiftResolutionService.log_shift_exception(
                        ticket=ticket,
                        weighing_phase="SECOND",
                        operator=request.user,
                        reason=w2_reason,
                        notes=w2_notes or "توزین دوم بدون شیفت فعال ثبت شد (تداوم عملیاتی حفظ گردید)."
                    )
                AnomalyDetectionEngine.run_for_ticket(ticket)

                messages.error(
                    request,
                    f"⛔ عدم امکان تکمیل خودکار قبض: {eval_res['blocking_reason']}"
                )
                today_jalali = get_today_jalali()
                today_time = timezone.localtime().strftime("%H:%M")
                return render(request, "weighbridge/ticket_second_weight.html", {
                    "form": form,
                    "ticket": ticket,
                    "title": f"ثبت وزن دوم - قبض شماره {ticket.serial_number}",
                    "today_jalali": today_jalali,
                    "today_time": today_time,
                    "discrepancy_eval": eval_res,
                    "active_approval": eval_res["active_approval"],
                })

            # Normal or approved ticket -> Complete
            ticket.status = TicketStatus.COMPLETED
            ticket.save()
            if ticket.second_weight_out_of_shift:
                ShiftResolutionService.log_shift_exception(
                    ticket=ticket,
                    weighing_phase="SECOND",
                    operator=request.user,
                    reason=w2_reason,
                    notes=w2_notes or "توزین دوم بدون شیفت فعال ثبت شد (تداوم عملیاتی حفظ گردید)."
                )

            # Update vehicle empty weight in masterdata if not previously set
            if ticket.vehicle and (not ticket.vehicle.empty_weight or ticket.vehicle.empty_weight == 0) and ticket.tare_weight and ticket.tare_weight > 0:
                ticket.vehicle.empty_weight = ticket.tare_weight
                ticket.vehicle.save(update_fields=["empty_weight"])

            log_audit(
                action=AuditAction.STATUS_CHANGE,
                model_name="WeighTicket",
                record_id=ticket.id,
                record_repr=f"قبض شماره {ticket.serial_number}",
                new_values={
                    "second_weight": float(ticket.second_weight),
                    "gross_weight": float(ticket.gross_weight),
                    "tare_weight": float(ticket.tare_weight),
                    "net_weight": float(ticket.net_weight),
                    "status": ticket.status
                },
                reason="ثبت وزن دوم و تکمیل فرایند توزین"
            )

            # Smart Monitoring Anomaly Detection
            alerts = AnomalyDetectionEngine.run_for_ticket(ticket)
            if alerts:
                messages.warning(request, f"پایش هوشمند: {len(alerts)} هشدار برای این قبض شناسایی شد.")

            messages.success(request, f"وزن دوم قبض {ticket.serial_number} با موفقیت ثبت و قبض تکمیل گردید.")
            action_btn = request.POST.get("submit_action")
            if action_btn == "save_and_print":
                return redirect(f"/weighbridge/tickets/{ticket.id}/print/")
            return redirect("weighbridge:ticket_detail", pk=ticket.id)
    else:
        form = SecondWeightForm(instance=ticket)

    today_jalali = get_today_jalali()
    today_time = timezone.localtime().strftime("%H:%M")
    eval_res = DiscrepancyApprovalService.evaluate_ticket_discrepancies(ticket)

    return render(request, "weighbridge/ticket_second_weight.html", {
        "form": form,
        "ticket": ticket,
        "title": f"ثبت وزن دوم - قبض شماره {ticket.serial_number}",
        "today_jalali": today_jalali,
        "today_time": today_time,
        "discrepancy_eval": eval_res,
        "active_approval": eval_res["active_approval"],
    })


@login_required
@weighbridge_role_required
def trucks_in_yard(request):
    """
    Dedicated operational queue board for vehicles waiting for 2nd weight inside the yard.
    Supports fast multi-field search (normalized plate, driver, serial, waybill),
    dwell-time thresholds (normal, warning, overdue), configurable auto-refresh polling (AJAX),
    accessible keyboard shortcuts, and responsive pagination.
    """
    from datetime import timedelta
    from django.db.models import Count
    from django.template.loader import render_to_string
    from django.http import JsonResponse
    from django.urls import reverse
    from core.jalali import to_english_digits

    # Authoritative dwell time thresholds from monitoring configuration
    try:
        from monitoring.models import MonitoringRuleConfig, AlertType
        rule_config = MonitoringRuleConfig.get_rule_config(AlertType.LONG_WAITING_TIME)
        warning_threshold = float(rule_config.warning_threshold)  # Default: 60.0 mins
        critical_threshold = float(rule_config.critical_threshold)  # Default: 180.0 mins
    except Exception:
        warning_threshold = 60.0
        critical_threshold = 180.0

    now = timezone.now()
    cutoff_warning = now - timedelta(minutes=warning_threshold)
    cutoff_critical = now - timedelta(minutes=critical_threshold)

    # Base QuerySet: All active vehicles currently in yard waiting for 2nd weight
    base_yard_qs = WeighTicket.objects.filter(
        status__in=[TicketStatus.WAITING_SECOND, TicketStatus.FIRST_REGISTERED]
    )

    # Compute overall yard KPI statistics in a single fast SQL aggregate
    yard_stats = base_yard_qs.aggregate(
        total=Count("id"),
        overdue=Count("id", filter=Q(created_at__lte=cutoff_critical)),
        warning=Count("id", filter=Q(created_at__gt=cutoff_critical, created_at__lte=cutoff_warning)),
        normal=Count("id", filter=Q(created_at__gt=cutoff_warning)),
    )
    total_yard_count = yard_stats["total"] or 0
    yard_overdue_count = yard_stats["overdue"] or 0
    yard_warning_count = yard_stats["warning"] or 0
    yard_normal_count = yard_stats["normal"] or 0

    # Build filtered query (prefetch discrepancy_approvals to prevent N+1 queries)
    qs = base_yard_qs.select_related(
        "product", "party", "driver", "vehicle", "first_weight_operator", "operation_type", "unload_location"
    ).prefetch_related("discrepancy_approvals")

    # 1. Search Query: Normalized Plate, Driver, Serial, Waybill, Party, Product
    q = request.GET.get("q", "").strip()
    if q:
        en_q = to_english_digits(q).strip()
        norm_q = normalize_plate(q)

        q_filter = Q()
        if norm_q:
            q_filter |= Q(normalized_plate__icontains=norm_q)
        q_filter |= Q(license_plate_display__icontains=q)
        if en_q and en_q != q:
            q_filter |= Q(license_plate_display__icontains=en_q)

        # Serial number and waybill search (both English and Persian digits)
        target_digits = en_q if en_q else q
        q_filter |= Q(serial_number__icontains=target_digits)
        q_filter |= Q(waybill_number__icontains=target_digits)

        # Driver search
        q_filter |= Q(driver__full_name__icontains=q)
        q_filter |= Q(driver_name_custom__icontains=q)
        if en_q:
            q_filter |= Q(driver_mobile_custom__icontains=en_q)
            q_filter |= Q(driver__mobile__icontains=en_q)

        # Cargo & Logistics
        q_filter |= Q(party__name__icontains=q)
        q_filter |= Q(product__name__icontains=q)

        qs = qs.filter(q_filter)

    # 2. Dwell Status Filter
    dwell_filter = request.GET.get("dwell_status", "all").strip().lower()
    if dwell_filter == "overdue":
        qs = qs.filter(created_at__lte=cutoff_critical)
    elif dwell_filter == "warning":
        qs = qs.filter(created_at__gt=cutoff_critical, created_at__lte=cutoff_warning)
    elif dwell_filter == "normal":
        qs = qs.filter(created_at__gt=cutoff_warning)
    else:
        dwell_filter = "all"

    # 3. Product Filter
    product_id = request.GET.get("product", "").strip()
    if product_id and product_id.isdigit():
        qs = qs.filter(product_id=int(product_id))

    # 4. Operation Type Filter
    op_id = request.GET.get("operation_type", "").strip()
    if op_id and op_id.isdigit():
        qs = qs.filter(operation_type_id=int(op_id))

    # 5. Ordering (Default: longest_wait FIFO priority)
    order_by = request.GET.get("order_by", "longest_wait").strip()
    if order_by == "newest":
        qs = qs.order_by("-created_at")
    elif order_by == "serial":
        qs = qs.order_by("-serial_number")
    elif order_by == "plate":
        qs = qs.order_by("license_plate_display")
    else:
        order_by = "longest_wait"
        qs = qs.order_by("created_at")

    # 6. Pagination
    try:
        per_page = int(request.GET.get("per_page", 50))
    except (ValueError, TypeError):
        per_page = 50
    if per_page not in [25, 50, 100, 200]:
        per_page = 50

    paginator = Paginator(qs, per_page)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    # Format items for template/JSON serialization
    tickets_with_duration = []
    start_index = page_obj.start_index() if paginator.count > 0 else 1
    for idx, t in enumerate(page_obj, start=start_index):
        start_dt = t.created_at or now
        diff_seconds = max(0.0, (now - start_dt).total_seconds())
        diff_mins = int(diff_seconds / 60)
        hours = diff_mins // 60
        mins = diff_mins % 60

        if hours > 0 and mins > 0:
            duration_str = f"{hours} ساعت و {mins} دقیقه"
        elif hours > 0:
            duration_str = f"{hours} ساعت"
        elif mins > 0:
            duration_str = f"{mins} دقیقه"
        else:
            duration_str = "کمتر از ۱ دقیقه"

        if diff_mins >= critical_threshold:
            item_dwell_status = "overdue"
            dwell_label = "معطلی بیش از حد"
            dwell_badge_class = "danger"
        elif diff_mins >= warning_threshold:
            item_dwell_status = "warning"
            dwell_label = "هشدار معطلی"
            dwell_badge_class = "warning"
        else:
            item_dwell_status = "normal"
            dwell_label = "عادی"
            dwell_badge_class = "success"

        tickets_with_duration.append({
            "row_number": idx,
            "ticket": t,
            "duration_str": duration_str,
            "duration_minutes": diff_mins,
            "dwell_status": item_dwell_status,
            "dwell_label": dwell_label,
            "dwell_badge_class": dwell_badge_class,
            "is_long_wait": diff_mins >= critical_threshold,
        })

    # Handle AJAX / JSON auto-refresh requests
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest" or request.GET.get("format") == "json"
    if is_ajax:
        html_table = render_to_string("weighbridge/partials/trucks_in_yard_rows.html", {
            "items": tickets_with_duration,
            "page_obj": page_obj,
            "q": q,
            "dwell_status": dwell_filter,
            "selected_product": product_id,
            "selected_op": op_id,
            "request": request,
        }, request=request)

        json_items = [
            {
                "id": item["ticket"].id,
                "serial_number": item["ticket"].serial_number,
                "license_plate_display": item["ticket"].license_plate_display,
                "driver_display": item["ticket"].driver_display,
                "driver_mobile": item["ticket"].driver_mobile_display,
                "party_name": str(item["ticket"].party) if item["ticket"].party else "-",
                "product_name": str(item["ticket"].product) if item["ticket"].product else "-",
                "first_weight": float(item["ticket"].first_weight),
                "duration_str": item["duration_str"],
                "duration_minutes": item["duration_minutes"],
                "dwell_status": item["dwell_status"],
                "dwell_label": item["dwell_label"],
                "dwell_badge_class": item["dwell_badge_class"],
                "second_weight_url": reverse("weighbridge:ticket_second_weight", args=[item["ticket"].id]),
                "detail_url": reverse("weighbridge:ticket_detail", args=[item["ticket"].id]),
            }
            for item in tickets_with_duration
        ]

        return JsonResponse({
            "success": True,
            "total_yard_count": total_yard_count,
            "yard_normal_count": yard_normal_count,
            "yard_warning_count": yard_warning_count,
            "yard_overdue_count": yard_overdue_count,
            "filtered_count": paginator.count,
            "page": page_obj.number,
            "total_pages": paginator.num_pages,
            "timestamp": timezone.localtime().strftime("%H:%M:%S"),
            "items": json_items,
            "html": html_table,
        })

    # Standard full-page render
    products = Product.objects.filter(is_active=True).order_by("name")
    operation_types = OperationType.objects.filter(is_active=True).order_by("name")

    return render(request, "weighbridge/trucks_in_yard.html", {
        "items": tickets_with_duration,
        "page_obj": page_obj,
        "count": paginator.count,
        "total_yard_count": total_yard_count,
        "yard_normal_count": yard_normal_count,
        "yard_warning_count": yard_warning_count,
        "yard_overdue_count": yard_overdue_count,
        "warning_threshold": int(warning_threshold),
        "critical_threshold": int(critical_threshold),
        "q": q,
        "dwell_status": dwell_filter,
        "selected_product": product_id,
        "selected_op": op_id,
        "order_by": order_by,
        "per_page": per_page,
        "products": products,
        "operation_types": operation_types,
        "title": "برد عملیاتی خودروهای داخل مجموعه (در انتظار وزن دوم)",
    })


@login_required
@weighbridge_role_required
def ticket_list(request):
    """
    Comprehensive ticket list view with advanced multi-field filtering and pagination.
    """
    qs = WeighTicket.objects.select_related(
        "operation_type", "party", "product", "driver", "vehicle", "first_weight_operator"
    ).all().order_by("-id")

    # Filters
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(serial_number__icontains=q) |
            Q(license_plate_display__icontains=q) |
            Q(driver__full_name__icontains=q) |
            Q(driver_name_custom__icontains=q) |
            Q(party__name__icontains=q) |
            Q(product__name__icontains=q) |
            Q(waybill_number__icontains=q) |
            Q(notes__icontains=q)
        )

    status_filter = request.GET.get("status")
    if status_filter and status_filter != "all":
        qs = qs.filter(status=status_filter)

    product_filter = request.GET.get("product")
    if product_filter:
        qs = qs.filter(product_id=product_filter)

    party_filter = request.GET.get("party")
    if party_filter:
        qs = qs.filter(party_id=party_filter)

    op_filter = request.GET.get("operation_type")
    if op_filter:
        qs = qs.filter(operation_type_id=op_filter)

    start_date_j = request.GET.get("start_date")
    if start_date_j:
        g_start = jalali_to_gregorian(start_date_j)
        if g_start:
            qs = qs.filter(first_weight_date__gte=g_start)

    end_date_j = request.GET.get("end_date")
    if end_date_j:
        g_end = jalali_to_gregorian(end_date_j)
        if g_end:
            qs = qs.filter(first_weight_date__lte=g_end)

    tolerance_exceeded = request.GET.get("tolerance_exceeded")
    if tolerance_exceeded == "1":
        qs = qs.filter(is_tolerance_exceeded=True)

    settings_obj = SystemSetting.get_settings()
    per_page = int(request.GET.get("per_page", settings_obj.items_per_page or 20))
    paginator = Paginator(qs, per_page)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Masterdata for filter dropdowns
    products = Product.objects.filter(is_active=True)
    parties = Party.objects.filter(is_active=True)
    op_types = OperationType.objects.filter(is_active=True)

    return render(request, "weighbridge/ticket_list.html", {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "products": products,
        "parties": parties,
        "op_types": op_types,
        "title": "لیست جامع قبوض باسکول",
    })


@login_required
def ticket_detail(request, pk):
    ticket = get_object_or_404(
        WeighTicket.objects.select_related(
            "operation_type", "party", "product", "driver", "vehicle", "vehicle_type",
            "origin", "destination", "unload_location", "loss_type",
            "first_weight_operator", "second_weight_operator", "cancelled_by", "last_edited_by"
        ), 
        pk=pk
    )
    
    # Fetch audit logs for this specific ticket
    audit_logs = AuditLog.objects.filter(model_name="WeighTicket", record_id=str(ticket.id)).order_by("-timestamp")
    
    # Smart Monitoring Analysis Summary
    monitoring_summary = AnomalyDetectionEngine.get_ticket_analysis_summary(ticket)

    # Historical and Pending Revisions
    revisions = ticket.revisions.select_related("requested_by", "reviewed_by", "applied_by").order_by("-requested_at")
    pending_revision = ticket.revisions.filter(status=TicketRevision.RevisionStatus.PENDING).first()

    return render(request, "weighbridge/ticket_detail.html", {
        "ticket": ticket,
        "audit_logs": audit_logs,
        "monitoring_summary": monitoring_summary,
        "revisions": revisions,
        "pending_revision": pending_revision,
        "title": f"جزئیات قبض شماره {ticket.serial_number}",
    })


@login_required
@manager_or_admin_required
def ticket_edit(request, pk):
    """
    Manager edit view for tickets with mandatory reason and audit logging.
    """
    ticket = get_object_or_404(WeighTicket, pk=pk)

    if request.method == "POST":
        old_values = {
            "freight_amount": str(ticket.freight_amount) if ticket.freight_amount is not None else None,
            "first_weight": float(ticket.first_weight),
            "second_weight": float(ticket.second_weight or 0),
            "gross_weight": float(ticket.gross_weight),
            "tare_weight": float(ticket.tare_weight),
            "net_weight": float(ticket.net_weight),
            "sent_weight": float(ticket.sent_weight),
            "loss_percent": float(ticket.loss_percent),
            "loss_weight": float(ticket.loss_weight),
            "final_weight": float(ticket.final_weight),
            "product": str(ticket.product) if ticket.product else "-",
            "party": str(ticket.party) if ticket.party else "-",
            "plate": ticket.license_plate_display,
            "vehicle_type": str(ticket.vehicle_type_display),
        }

        form = TicketEditManagerForm(request.POST, instance=ticket)
        if form.is_valid():
            reason = form.cleaned_data.get("manager_reason")

            if ticket.status == TicketStatus.COMPLETED:
                from weighbridge.revision_service import TicketRevisionService
                proposed_data = {
                    "first_weight": form.cleaned_data.get("first_weight"),
                    "second_weight": form.cleaned_data.get("second_weight"),
                    "sent_weight": form.cleaned_data.get("sent_weight"),
                    "loss_percent": form.cleaned_data.get("loss_percent"),
                    "loss_weight": form.cleaned_data.get("loss_weight"),
                    "loss_type_id": form.cleaned_data.get("loss_type").id if form.cleaned_data.get("loss_type") else None,
                    "product_id": form.cleaned_data.get("product").id if form.cleaned_data.get("product") else None,
                    "party_id": form.cleaned_data.get("party").id if form.cleaned_data.get("party") else None,
                    "license_plate_display": form.cleaned_data.get("license_plate_display"),
                    "waybill_number": form.cleaned_data.get("waybill_number"),
                    "freight_amount": form.cleaned_data.get("freight_amount"),
                    "notes": form.cleaned_data.get("notes"),
                    "driver_mobile": form.cleaned_data.get("driver_mobile_custom"),
                }
                try:
                    rev = TicketRevisionService.request_revision(
                        ticket=ticket,
                        requester=request.user,
                        proposed_data=proposed_data,
                        reason=reason,
                        client_ip=request.META.get("REMOTE_ADDR")
                    )
                    messages.success(
                        request,
                        f"درخواست بازنگری برای قبض نهایی‌شده {ticket.serial_number} با موفقیت ثبت شد و در انتظار بررسی سرپرست قرار گرفت."
                    )
                    return redirect("weighbridge:ticket_detail", pk=ticket.id)
                except ValidationError as exc:
                    err_msg = exc.messages[0] if hasattr(exc, "messages") else str(exc)
                    messages.error(request, f"خطا در ثبت درخواست بازنگری: {err_msg}")
                    sales_op_ids = list(OperationType.objects.filter(Q(direction='outbound') | Q(name__icontains='فروش')).values_list('id', flat=True))
                    return render(request, "weighbridge/ticket_edit.html", {
                        "form": form, "ticket": ticket, "title": f"اصلاح و ویرایش مدیریتی قبض {ticket.serial_number}",
                        "sales_op_ids": sales_op_ids,
                    })

            ticket = form.save(commit=False)
            ticket.last_edited_by = request.user
            ticket.last_edit_reason = reason

            # Auto-register or link Vehicle and Driver into system MasterData
            VehicleDriverRegistrationService.resolve_or_create(ticket, form.cleaned_data)
            if form.cleaned_data.get("vehicle_type"):
                ticket.vehicle_type = form.cleaned_data["vehicle_type"]
                if ticket.vehicle and ticket.vehicle.vehicle_type != ticket.vehicle_type:
                    ticket.vehicle.vehicle_type = ticket.vehicle_type
                    ticket.vehicle.save(update_fields=["vehicle_type"])

            if ticket.loss_weight and ticket.loss_weight > 0:
                ticket.is_loss_overridden = True
                if not ticket.loss_override_reason:
                    ticket.loss_override_reason = reason

            # Recalculate weights
            calc_results = TicketCalculationService.calculate_ticket(
                first_weight=ticket.first_weight,
                second_weight=ticket.second_weight,
                sent_weight=ticket.sent_weight,
                loss_percent=ticket.loss_percent,
                manual_loss_weight=ticket.loss_weight if ticket.is_loss_overridden else None,
                product=ticket.product,
                is_loss_overridden=ticket.is_loss_overridden
            )

            ticket.gross_weight = calc_results["gross_weight"]
            ticket.tare_weight = calc_results["tare_weight"]
            ticket.net_weight = calc_results["net_weight"]
            ticket.loss_percent = calc_results["loss_percent"]
            ticket.loss_weight = calc_results["loss_weight"]
            ticket.final_weight = calc_results["final_weight"]
            ticket.weight_difference = calc_results["weight_difference"]
            ticket.weight_difference_percent = calc_results["weight_difference_percent"]
            ticket.is_tolerance_exceeded = calc_results["is_tolerance_exceeded"]

            # Phase 3.1 Hotfix: Invalidate stale approval if weights, product, or sent_weight were modified
            DiscrepancyApprovalService.check_and_invalidate_stale_approvals(
                ticket,
                calc_results["gross_weight"],
                calc_results["tare_weight"],
                calc_results["net_weight"],
                current_product=ticket.product,
                current_sent_weight=ticket.sent_weight,
            )

            # Re-evaluate discrepancies after material edit (for in-flight tickets)
            eval_res = DiscrepancyApprovalService.evaluate_ticket_discrepancies(ticket, trial_weights=calc_results)
            if not eval_res["can_finalize"]:
                ticket.status = TicketStatus.WAITING_SECOND
                messages.warning(
                    request,
                    f"توجه: تغییرات اعمال‌شده در قبض موجب بروز مغایرت مسدودکننده گردید ({eval_res['blocking_reason']}). "
                    "وضعیت قبض به «در انتظار وزن دوم / مجوز سرپرست» تنظیم شد."
                )

            try:
                DailyPlatePolicy.save(ticket, user=request.user)
            except ValidationError as exc:
                form.add_error(None, exc)
                sales_op_ids = list(OperationType.objects.filter(Q(direction='outbound') | Q(name__icontains='فروش')).values_list('id', flat=True))
                return render(request, "weighbridge/ticket_edit.html", {
                    "form": form, "ticket": ticket, "title": "اصلاح و ویرایش مدیریتی قبض",
                    "sales_op_ids": sales_op_ids,
                })

            new_values = {
                "freight_amount": str(ticket.freight_amount) if ticket.freight_amount is not None else None,
                "first_weight": float(ticket.first_weight),
                "second_weight": float(ticket.second_weight or 0),
                "gross_weight": float(ticket.gross_weight),
                "tare_weight": float(ticket.tare_weight),
                "net_weight": float(ticket.net_weight),
                "sent_weight": float(ticket.sent_weight),
                "loss_percent": float(ticket.loss_percent),
                "loss_weight": float(ticket.loss_weight),
                "final_weight": float(ticket.final_weight),
                "product": str(ticket.product) if ticket.product else "-",
                "party": str(ticket.party) if ticket.party else "-",
                "plate": ticket.license_plate_display,
                "vehicle_type": str(ticket.vehicle_type_display),
            }

            log_audit(
                action=AuditAction.OVERRIDE_WEIGHT,
                model_name="WeighTicket",
                record_id=ticket.id,
                record_repr=f"قبض شماره {ticket.serial_number}",
                old_values=old_values,
                new_values=new_values,
                reason=reason
            )

            # Smart Monitoring Anomaly Detection on edit
            alerts = AnomalyDetectionEngine.run_for_ticket(ticket)
            if alerts:
                messages.warning(request, f"پایش هوشمند: {len(alerts)} هشدار پس از ویرایش برای این قبض شناسایی/بروزرسانی شد.")

            messages.success(request, f"قبض {ticket.serial_number} با موفقیت توسط مدیر ویرایش و اصلاح شد.")
            return redirect("weighbridge:ticket_detail", pk=ticket.id)
    else:
        form = TicketEditManagerForm(instance=ticket)

    sales_op_ids = list(OperationType.objects.filter(Q(direction='outbound') | Q(name__icontains='فروش')).values_list('id', flat=True))
    return render(request, "weighbridge/ticket_edit.html", {
        "form": form,
        "ticket": ticket,
        "title": f"اصلاح و ویرایش مدیریتی قبض {ticket.serial_number}",
        "sales_op_ids": sales_op_ids,
    })


@login_required
@manager_or_admin_required
def ticket_cancel(request, pk):
    """
    Cancel/invalidate ticket with mandatory reason (No hard delete).
    """
    ticket = get_object_or_404(WeighTicket, pk=pk)

    if request.method == "POST":
        reason = request.POST.get("cancellation_reason", "").strip()
        if not reason:
            messages.error(request, "وارد کردن دلیل ابطال سند اجباری است.")
            return redirect("weighbridge:ticket_detail", pk=ticket.id)

        ticket.status = TicketStatus.CANCELLED
        ticket.cancellation_reason = reason
        ticket.cancelled_by = request.user
        ticket.cancelled_at = timezone.now()
        ticket.save()

        log_audit(
            action=AuditAction.CANCEL,
            model_name="WeighTicket",
            record_id=ticket.id,
            record_repr=f"قبض شماره {ticket.serial_number}",
            new_values={"status": "cancelled"},
            reason=reason
        )

        messages.warning(request, f"قبض شماره {ticket.serial_number} با موفقیت باطل (لغو) گردید.")
        return redirect("weighbridge:ticket_detail", pk=ticket.id)

    return render(request, "weighbridge/ticket_cancel_confirm.html", {"ticket": ticket})


@login_required
def ticket_print(request, pk):
    """
    High quality, offline-ready print preview supporting A4, A5, and POS thermal receipts.
    Guarantees that viewing preview never modifies ticket numbers, weighing calculations, or print counters.
    Calculates prior print requests via AuditLog and embeds an offline verification QR code.
    Supports reconstructing exact historical revisions (Rev. 0, Rev. N) with superseding watermarks.
    """
    profile = getattr(request.user, "profile", None)
    can_print = request.user.is_superuser or (
        profile and profile.is_active and (profile.can_access_weighbridge or profile.can_access_reports)
    )
    if not can_print:
        messages.error(request, "شما دسترسی لازم برای چاپ و مشاهده قبوض باسکول را ندارید.")
        return redirect("dashboard:index")

    ticket = get_object_or_404(
        WeighTicket.objects.select_related(
            "operation_type", "party", "product", "driver", "vehicle", "vehicle_type",
            "origin", "destination", "unload_location", "loss_type",
            "first_weight_operator", "second_weight_operator"
        ),
        pk=pk
    )

    settings_obj = SystemSetting.get_settings()
    template_type = request.GET.get("template", settings_obj.default_print_template or "a4").lower()
    if template_type not in ["a4", "a5", "pos"]:
        template_type = "a4"

    # Query prior print requests (Read-Only: does NOT increment on GET preview, refresh or template switch)
    prior_prints = AuditLog.objects.filter(
        model_name="WeighTicket",
        record_id=str(ticket.id),
        action=AuditAction.PRINT
    ).count()
    is_reprint = prior_prints > 0
    print_number = prior_prints + 1

    # Phase 3.2.3 Ticket Revision Handling & Reconstruction
    from weighbridge.revision_service import TicketRevisionService
    current_rev_number = int(ticket.current_revision_number or 0)
    requested_rev_param = request.GET.get("rev")
    target_rev = current_rev_number

    if requested_rev_param is not None:
        try:
            target_rev = int(requested_rev_param)
        except (ValueError, TypeError):
            raise Http404("شناسه نسخه بازنگری نامعتبر است.")
        if target_rev < 0 or target_rev > current_rev_number:
            raise Http404(f"نسخه بازنگری درخواستی (Rev. {target_rev}) برای این قبض وجود ندارد یا هنوز اعمال نشده است.")

    is_superseded = target_rev < current_rev_number
    is_revised = target_rev > 0

    if target_rev == current_rev_number:
        presentation_ticket = ticket
    else:
        presentation_ticket = TicketRevisionService.get_revision_presentation(ticket, target_rev)

    # Historical revision metadata
    revision_approved_by = None
    revision_approved_at = None
    revision_reason = None

    if is_revised:
        hist_rev = ticket.revisions.filter(
            status=TicketRevision.RevisionStatus.APPLIED,
            revision_number=target_rev
        ).select_related("reviewed_by").first()
        if hist_rev:
            if hist_rev.reviewed_by:
                revision_approved_by = hist_rev.reviewed_by.get_full_name() or hist_rev.reviewed_by.username
            revision_approved_at = hist_rev.jalali_applied_at
            revision_reason = hist_rev.reason
    elif target_rev == 0 and is_superseded:
        revision_reason = "سند اولیه پیش از اعمال اصلاحات"

    # Generate offline QR verification code (derived strictly from presentation values)
    qr_b64 = ""
    try:
        import qrcode
        import base64
        import io
        qr = qrcode.QRCode(version=1, box_size=3, border=1)
        qr_data = f"WB:{presentation_ticket.serial_number}|PL:{presentation_ticket.license_plate_display}|W:{presentation_ticket.final_weight}KG|REV:{target_rev}|D:{get_today_jalali()}"
        qr.add_data(qr_data)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        qr_img.save(buf, format="PNG")
        qr_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        qr_b64 = ""

    # Phase 3.1 Hotfix: Verify finalization and supervisor approval status for official release safety
    eval_res = DiscrepancyApprovalService.evaluate_ticket_discrepancies(ticket)
    latest_approval = DiscrepancyApproval.objects.filter(
        ticket=ticket, status=ApprovalStatus.APPROVED
    ).order_by("-id").first()

    # Official release document is only valid when completed and fully approved
    is_draft = (ticket.status != TicketStatus.COMPLETED) or (not eval_res["can_finalize"])
    draft_reason = ""
    if is_draft:
        if ticket.status != TicketStatus.COMPLETED:
            draft_reason = f"سند در وضعیت «{ticket.get_status_display()}» بوده و هنوز تکمیل نهایی نشده است."
        elif not eval_res["can_finalize"]:
            draft_reason = f"سند دارای مغایرت مسدودکننده فاقد تأییدیه معتبر سرپرست است ({eval_res['blocking_reason']})."

    template_name = f"weighbridge/ticket_print_{template_type}.html"
    return render(request, template_name, {
        "ticket": presentation_ticket,
        "underlying_ticket": ticket,
        "settings": settings_obj,
        "template_type": template_type,
        "print_date": get_today_jalali(),
        "print_time": timezone.localtime().strftime("%H:%M"),
        "is_reprint": is_reprint,
        "print_number": print_number,
        "revision_number": target_rev,
        "ticket_current_rev": current_rev_number,
        "is_revised": is_revised,
        "is_superseded": is_superseded,
        "requested_rev_param": requested_rev_param,
        "revision_approved_by": revision_approved_by,
        "revision_approved_at": revision_approved_at,
        "revision_reason": revision_reason,
        "qr_b64": qr_b64,
        "is_draft": is_draft,
        "draft_reason": draft_reason,
        "latest_approval": latest_approval,
        "title": f"چاپ قبض {presentation_ticket.serial_number}" + (f" (ویرایش {target_rev})" if is_revised else " (نسخه اصلی)") + (" [منسوخ‌شده]" if is_superseded else "") + (f" (چاپ مجدد - نسخه {print_number})" if is_reprint else ""),
    })


@login_required
@require_POST
def log_ticket_print(request, pk):
    """
    Authenticated POST endpoint to explicitly record an operator print request.
    Distinguishes preview access from explicit print execution commands and
    records the exact revision number printed.
    """
    profile = getattr(request.user, "profile", None)
    can_print = request.user.is_superuser or (
        profile and profile.is_active and (profile.can_access_weighbridge or profile.can_access_reports)
    )
    if not can_print:
        return JsonResponse({"error": "Forbidden"}, status=403)

    ticket = get_object_or_404(WeighTicket, pk=pk)
    template_type = request.POST.get("template", "a4").lower()
    if template_type not in ["a4", "a5", "pos"]:
        template_type = "a4"

    requested_rev_param = request.POST.get("rev") or request.GET.get("rev")
    current_rev_number = int(ticket.current_revision_number or 0)
    target_rev = current_rev_number
    if requested_rev_param is not None:
        try:
            target_rev = int(requested_rev_param)
        except (ValueError, TypeError):
            pass

    is_superseded = target_rev < current_rev_number

    prior_prints = AuditLog.objects.filter(
        model_name="WeighTicket",
        record_id=str(ticket.id),
        action=AuditAction.PRINT
    ).count()
    is_reprint = prior_prints > 0
    print_number = prior_prints + 1

    rev_label = f"Rev. {target_rev}" + (" (منسوخ‌شده / فاقد اعتبار جاری)" if is_superseded else " (نسخه جاری)")
    log_audit(
        action=AuditAction.PRINT,
        model_name="WeighTicket",
        record_id=ticket.id,
        record_repr=f"قبض شماره {ticket.serial_number}",
        user=request.user,
        reason=f"درخواست ارسال به چاپگر ({'چاپ مجدد - نسخه ' + str(print_number) if is_reprint else 'چاپ اولیه'}) در قالب {template_type.upper()} [نسخه بازنگری: {rev_label}] [تأیید خروج فیزیکی کاغذ تنها با سخت‌افزار مجهز به حسگر Paper-Out امکان‌پذیر است]"
    )

    return JsonResponse({
        "status": "ok",
        "print_number": print_number,
        "is_reprint": is_reprint,
        "template": template_type,
        "printed_revision": target_rev,
        "is_superseded": is_superseded,
    })



@login_required
@weighbridge_role_required
def global_search(request):
    """
    Global search bar in navbar.
    """
    q = request.GET.get("q", "").strip()
    tickets = []
    if q:
        tickets = WeighTicket.objects.filter(
            Q(serial_number__icontains=q) |
            Q(license_plate_display__icontains=q) |
            Q(driver__full_name__icontains=q) |
            Q(driver_name_custom__icontains=q) |
            Q(party__name__icontains=q) |
            Q(product__name__icontains=q) |
            Q(waybill_number__icontains=q) |
            Q(notes__icontains=q)
        ).select_related("product", "party", "driver")[:50]

    return render(request, "weighbridge/global_search_results.html", {
        "q": q,
        "tickets": tickets,
        "title": f"نتایج جستجو برای «{q}»",
    })


from django.http import JsonResponse

@login_required
@weighbridge_role_required
def ajax_plate_lookup(request):
    """
    Lookup vehicle history and check for active open tickets by license plate.
    Supports plate normalization (Persian/English digits, spaces) and returns
    auto-fill data for vehicle type, driver name, mobile, etc.
    """
    plate = request.GET.get("plate", "").strip()
    if not plate:
        return JsonResponse({"found": False, "is_duplicate": False, "message": "پلاک وارد نشده است."})

    norm_plate = normalize_plate(plate)

    # 0. Check if plate is blacklisted / blocked
    from weighbridge.models import BlockedPlate
    blocked = BlockedPlate.objects.filter(normalized_plate=norm_plate, is_active=True).first() if norm_plate else None
    if blocked:
        return JsonResponse({
            "is_blocked": True,
            "block_reason": blocked.reason,
            "blocked_at": format_jalali_date(blocked.created_at.date()) if blocked.created_at else "",
            "blocked_by": blocked.blocked_by.get_full_name() or blocked.blocked_by.username,
            "found": False,
            "is_duplicate": False,
            "plate_display": blocked.license_plate_display,
        })

    # Incomplete plate check:
    # Standard Iranian vehicle plates normalize to 8 characters (or minimum 6 for special plates).
    # If the normalized plate is shorter than 6 characters and has no exact display match:
    # Treat as incomplete query: never auto-bind vehicle, driver, tare, or open tickets.
    is_incomplete = len(norm_plate) < 6 and not Vehicle.objects.filter(plate_display__iexact=plate).exists()
    if is_incomplete:
        suggestions = []
        if norm_plate:
            suggestions = list(
                Vehicle.objects.filter(normalized_plate__startswith=norm_plate)
                .values_list("plate_display", flat=True)[:5]
            )
        return JsonResponse({
            "found": False,
            "is_duplicate": False,
            "is_incomplete": True,
            "suggestions": suggestions,
            "message": "پلاک وارد شده ناقص است.",
            "plate_display": plate,
            "normalized_plate": norm_plate,
            "has_open_ticket": False,
        })

    # 1. Fast indexed vehicle lookup by normalized plate (O(1)) with display fallback
    # HOTFIX 2: Require unambiguous exact match (count == 1). Never guess on multiple matches.
    vehicle = None
    if norm_plate:
        norm_matches = Vehicle.objects.filter(normalized_plate=norm_plate).select_related("vehicle_type", "default_driver")
        norm_count = norm_matches.count()
        if norm_count == 1:
            vehicle = norm_matches.first()
        elif norm_count > 1:
            return JsonResponse({
                "found": False,
                "is_duplicate": False,
                "is_ambiguous": True,
                "ambiguity_count": norm_count,
                "message": f"چندین رکورد خودرو ({norm_count} مورد) با این پلاک در سامانه یافت شد. جهت ایمنی اطلاعات، انتساب خودکار انجام نشد.",
                "plate_display": plate,
                "normalized_plate": norm_plate,
                "has_open_ticket": False,
            })

    if not vehicle and plate:
        legacy_matches = Vehicle.objects.filter(plate_display__iexact=plate).select_related("vehicle_type", "default_driver")
        legacy_count = legacy_matches.count()
        if legacy_count == 1:
            vehicle = legacy_matches.first()
        elif legacy_count > 1:
            return JsonResponse({
                "found": False,
                "is_duplicate": False,
                "is_ambiguous": True,
                "ambiguity_count": legacy_count,
                "message": f"چندین خودرو با عنوان پلاک یکسان ({legacy_count} مورد) یافت شد. جهت ایمنی، انتساب خودکار انجام نشد.",
                "plate_display": plate,
                "normalized_plate": norm_plate,
                "has_open_ticket": False,
            })

    # 2. Search ticket history using exact vehicle or exact plate (NO icontains!)
    if vehicle:
        ticket_q = Q(vehicle=vehicle)
        if vehicle.normalized_plate:
            ticket_q |= Q(normalized_plate=vehicle.normalized_plate)
        ticket_q |= Q(license_plate_display__iexact=vehicle.plate_display)
        tickets_qs = WeighTicket.objects.filter(ticket_q).order_by("-id")
    elif norm_plate:
        tickets_qs = WeighTicket.objects.filter(
            Q(normalized_plate=norm_plate) | Q(license_plate_display__iexact=plate)
        ).order_by("-id")
    else:
        tickets_qs = WeighTicket.objects.filter(license_plate_display__iexact=plate).order_by("-id")

    trip_count = tickets_qs.count()
    last_ticket = tickets_qs.select_related("driver", "product", "party", "vehicle_type", "vehicle").first()

    # 3. Check for open / in-progress tickets (waiting for second weight or first weight)
    open_ticket = tickets_qs.filter(
        status__in=[TicketStatus.WAITING_SECOND, TicketStatus.WAITING_FIRST, TicketStatus.FIRST_REGISTERED]
    ).first()

    # 4. Determine driver info (avoid placeholder text like 'نامشخص' or '-')
    driver_id = None
    driver_name = ""
    driver_mobile = ""

    if vehicle and vehicle.default_driver:
        driver_id = vehicle.default_driver.id
        driver_name = vehicle.default_driver.full_name or ""
        driver_mobile = vehicle.default_driver.mobile or ""

    if not driver_name and tickets_qs.exists():
        ticket_with_driver = tickets_qs.filter(
            Q(driver__isnull=False) | (~Q(driver_name_custom="") & ~Q(driver_name_custom__isnull=True))
        ).select_related("driver").first()

        if ticket_with_driver:
            if ticket_with_driver.driver:
                driver_id = ticket_with_driver.driver.id
                driver_name = ticket_with_driver.driver.full_name or ""
                driver_mobile = ticket_with_driver.driver.mobile or ""
            else:
                driver_name = ticket_with_driver.driver_name_custom or ""
                driver_mobile = ticket_with_driver.driver_mobile_custom or ""

    if not driver_mobile and tickets_qs.exists():
        ticket_with_mob = tickets_qs.exclude(driver_mobile_custom="").exclude(driver_mobile_custom__isnull=True).first()
        if ticket_with_mob:
            driver_mobile = ticket_with_mob.driver_mobile_custom or ""

    # 5. Determine vehicle type info
    vehicle_type_id = None
    vehicle_type_name = ""
    vehicle_type_custom = ""

    if vehicle and vehicle.vehicle_type:
        vehicle_type_id = vehicle.vehicle_type.id
        vehicle_type_name = vehicle.vehicle_type.name
    elif tickets_qs.exists():
        ticket_with_vtype = tickets_qs.filter(vehicle_type__isnull=False).select_related("vehicle_type").first()
        if ticket_with_vtype and ticket_with_vtype.vehicle_type:
            vehicle_type_id = ticket_with_vtype.vehicle_type.id
            vehicle_type_name = ticket_with_vtype.vehicle_type.name
        else:
            ticket_with_vcustom = tickets_qs.exclude(vehicle_type_custom="").exclude(vehicle_type_custom__isnull=True).first()
            if ticket_with_vcustom:
                vehicle_type_custom = ticket_with_vcustom.vehicle_type_custom or ""

    # 6. Determine vehicle id
    vehicle_id = None
    if vehicle:
        vehicle_id = vehicle.id
    elif last_ticket and last_ticket.vehicle_id:
        vehicle_id = last_ticket.vehicle_id

    # 7. Determine empty / tare weight
    empty_weight = None
    if vehicle and vehicle.empty_weight and vehicle.empty_weight > 0:
        empty_weight = float(vehicle.empty_weight)
    elif tickets_qs.exists():
        ticket_with_tare = tickets_qs.filter(tare_weight__gt=0).first()
        if ticket_with_tare and ticket_with_tare.tare_weight:
            empty_weight = float(ticket_with_tare.tare_weight)

    is_duplicate = (vehicle is not None) or (trip_count > 0)

    # Check if plate is registered for dedicated auto-fill or has previous tickets
    from weighbridge.models import PlateAutoFill
    autofill_entry = PlateAutoFill.objects.filter(normalized_plate=norm_plate, is_active=True).first() if norm_plate else None

    # Retrieve latest non-cancelled ticket (or latest ticket) for this vehicle/plate
    last_valid_ticket = tickets_qs.exclude(status=TicketStatus.CANCELLED).select_related(
        "driver", "product", "party", "operation_type", "origin", "destination", "unload_location", "loss_type", "vehicle_type"
    ).first()

    if not last_valid_ticket and tickets_qs.exists():
        last_valid_ticket = tickets_qs.select_related(
            "driver", "product", "party", "operation_type", "origin", "destination", "unload_location", "loss_type", "vehicle_type"
        ).first()

    # ONLY enable autofill of cargo/operation fields if the plate is registered in active PlateAutoFill!
    is_autofill_enabled = bool(autofill_entry and autofill_entry.is_active)
    autofill_data = None

    if is_autofill_enabled and last_valid_ticket:
        # Fallbacks to any previous ticket of this vehicle if a field was null on the latest ticket
        def get_fallback_field(field_name):
            val = getattr(last_valid_ticket, field_name)
            if val:
                return val
            hist_t = tickets_qs.filter(**{f"{field_name}__isnull": False}).select_related(field_name).first()
            if hist_t:
                return getattr(hist_t, field_name)
            return None

        origin_obj = get_fallback_field("origin")
        dest_obj = get_fallback_field("destination")
        unload_obj = get_fallback_field("unload_location")
        op_obj = get_fallback_field("operation_type")
        party_obj = get_fallback_field("party")
        prod_obj = get_fallback_field("product")
        loss_obj = get_fallback_field("loss_type")
        vtype_obj = get_fallback_field("vehicle_type")

        final_driver_id = last_valid_ticket.driver_id or driver_id
        final_driver_name = (last_valid_ticket.driver.full_name if last_valid_ticket.driver else last_valid_ticket.driver_name_custom) or driver_name
        final_driver_mobile = (last_valid_ticket.driver.mobile if last_valid_ticket.driver else last_valid_ticket.driver_mobile_custom) or driver_mobile

        autofill_data = {
            "last_ticket_serial": last_valid_ticket.serial_number,
            "last_ticket_date": last_valid_ticket.jalali_first_date,
            "operation_type_id": op_obj.id if op_obj else None,
            "operation_type_name": op_obj.name if op_obj else "",
            "party_id": party_obj.id if party_obj else None,
            "party_name": party_obj.name if party_obj else "",
            "product_id": prod_obj.id if prod_obj else None,
            "product_name": prod_obj.name if prod_obj else "",
            "origin_id": origin_obj.id if origin_obj else None,
            "origin_name": origin_obj.name if origin_obj else "",
            "destination_id": dest_obj.id if dest_obj else None,
            "destination_name": dest_obj.name if dest_obj else "",
            "unload_location_id": unload_obj.id if unload_obj else None,
            "unload_location_name": unload_obj.name if unload_obj else "",
            "freight_amount": int(last_valid_ticket.freight_amount) if last_valid_ticket.freight_amount is not None else "",
            "load_count": last_valid_ticket.load_count or 1,
            "ingot_count": last_valid_ticket.ingot_count if last_valid_ticket.ingot_count is not None else "",
            "loss_type_id": loss_obj.id if loss_obj else None,
            "loss_type_name": loss_obj.name if loss_obj else "",
            "loss_percent": float(last_valid_ticket.loss_percent) if last_valid_ticket.loss_percent else "",
            "weight_mode": last_valid_ticket.weight_mode or "empty_first",
            "vehicle_type_id": vtype_obj.id if vtype_obj else vehicle_type_id,
            "vehicle_type_name": (vtype_obj.name if vtype_obj else vehicle_type_name),
            "vehicle_type_custom": last_valid_ticket.vehicle_type_custom or vehicle_type_custom,
            "driver_id": final_driver_id,
            "driver_name": final_driver_name,
            "driver_mobile": final_driver_mobile,
        }

    response_data = {
        "is_blocked": False,
        "found": is_duplicate,
        "is_duplicate": is_duplicate,
        "is_autofill_enabled": is_autofill_enabled,
        "autofill_notes": (autofill_entry.notes or "") if autofill_entry else "",
        "autofill_data": autofill_data,

        "trip_count": trip_count,
        "plate_display": vehicle.plate_display if vehicle else (last_ticket.license_plate_display if last_ticket else plate),
        "normalized_plate": norm_plate,
        "vehicle_id": vehicle_id,
        "vehicle_type_id": vehicle_type_id,
        "vehicle_type_name": vehicle_type_name,
        "vehicle_type_custom": vehicle_type_custom,
        "driver_id": driver_id,
        "driver_name": driver_name,
        "driver_mobile": driver_mobile,
        "empty_weight": empty_weight,
        "last_product": last_ticket.product.name if (last_ticket and last_ticket.product) else "",
        "last_party": last_ticket.party.name if (last_ticket and last_ticket.party) else "",
        "last_visit": last_ticket.jalali_first_date if last_ticket else "",
        "has_open_ticket": open_ticket is not None,
    }

    if open_ticket:
        response_data["open_ticket"] = {
            "id": open_ticket.id,
            "serial_number": open_ticket.serial_number,
            "status_display": open_ticket.get_status_display(),
            "first_weight": float(open_ticket.first_weight),
            "date": open_ticket.jalali_first_date,
            "time": open_ticket.first_time_str,
            "product": open_ticket.product.name if open_ticket.product else "-",
            "party": open_ticket.party.name if open_ticket.party else "-",
        }

    return JsonResponse(response_data)


# ==============================================================================
# بخش توزین متفرقه و آزاد (شرکت‌های دیگر / اضطراری)
# کاملاً مجزا از داده‌ها و آمارهای کارخانه
# ==============================================================================

from django.db.models import Sum
from weighbridge.models import EmergencyWeighTicket, EmergencyTicketStatus
from weighbridge.forms import EmergencyTicketForm, EmergencySecondWeightForm

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager", "weighbridge_operator")
def emergency_ticket_create(request):
    """
    ثبت سریع و مستقل توزین برای سایر شرکت‌ها (توزین متفرقه / آزاد / اضطراری).
    داده‌های این بخش در آمارهای انبار و کالای کارخانه ثبت نمی‌شوند.
    """
    if request.method == "POST":
        form = EmergencyTicketForm(request.POST)
        if form.is_valid():
            ticket = form.save(commit=False)

            # ثبت تاریخ و ساعت
            weight_date_j = form.cleaned_data.get("weight_date_jalali")
            ticket.weight_date = jalali_to_gregorian(weight_date_j) if weight_date_j else get_today_gregorian()

            time_str = form.cleaned_data.get("weight_time_str")
            if time_str and ":" in time_str:
                try:
                    h, m = time_str.split(":")[:2]
                    ticket.weight_time = time(int(h), int(m))
                except Exception:
                    ticket.weight_time = timezone.localtime().time()
            else:
                ticket.weight_time = timezone.localtime().time()

            ticket.operator = request.user

            gross = ticket.gross_weight or Decimal("0")
            tare = ticket.tare_weight or Decimal("0")

            if gross > 0 and tare > 0:
                ticket.status = EmergencyTicketStatus.COMPLETED
                ticket.gross_date = ticket.weight_date
                ticket.gross_time = ticket.weight_time
                ticket.tare_date = ticket.weight_date
                ticket.tare_time = ticket.weight_time
            else:
                ticket.status = EmergencyTicketStatus.WAITING_SECOND
                if gross > 0:
                    ticket.gross_date = ticket.weight_date
                    ticket.gross_time = ticket.weight_time
                elif tare > 0:
                    ticket.tare_date = ticket.weight_date
                    ticket.tare_time = ticket.weight_time

            ticket.save()

            messages.success(
                request,
                f"قبض توزین متفرقه شماره {ticket.serial_number} با موفقیت ثبت گردید."
            )

            if "save_and_print" in request.POST:
                return redirect("weighbridge:emergency_ticket_print", pk=ticket.pk)
            return redirect("weighbridge:emergency_ticket_detail", pk=ticket.pk)
    else:
        initial_data = {
            "weight_date_jalali": get_today_jalali(),
            "weight_time_str": timezone.localtime().strftime("%H:%M"),
        }
        form = EmergencyTicketForm(initial=initial_data)

    return render(request, "weighbridge/emergency_ticket_create.html", {
        "form": form,
        "title": "ثبت باسکول متفرقه / آزاد (شرکت‌های دیگر)",
        "today_jalali": get_today_jalali(),
        "current_time": timezone.localtime().strftime("%H:%M"),
    })


@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager", "weighbridge_operator")
def emergency_ticket_second_weight(request, pk):
    """
    تکمیل وزن دوم برای قبض متفرقه که در انتظار وزن دوم بوده است.
    """
    ticket = get_object_or_404(EmergencyWeighTicket, pk=pk)

    if ticket.status == EmergencyTicketStatus.COMPLETED:
        messages.info(request, "این قبض قبلاً هر دو وزن را ثبت کرده و تکمیل شده است.")
        return redirect("weighbridge:emergency_ticket_detail", pk=ticket.pk)

    is_missing_tare = (ticket.gross_weight > 0 and (not ticket.tare_weight or ticket.tare_weight == 0))
    missing_weight_name = "وزن خالی (تار)" if is_missing_tare else "وزن پر (ناخالص)"

    if request.method == "POST":
        form = EmergencySecondWeightForm(request.POST, instance=ticket)
        if form.is_valid():
            sec_weight = form.cleaned_data.get("second_weight")
            date_j = form.cleaned_data.get("second_weight_date_jalali")
            sec_date = jalali_to_gregorian(date_j) if date_j else get_today_gregorian()

            time_str = form.cleaned_data.get("second_weight_time_str")
            if time_str and ":" in time_str:
                try:
                    h, m = time_str.split(":")[:2]
                    sec_time = time(int(h), int(m))
                except Exception:
                    sec_time = timezone.localtime().time()
            else:
                sec_time = timezone.localtime().time()

            if is_missing_tare:
                ticket.tare_weight = sec_weight
                ticket.tare_date = sec_date
                ticket.tare_time = sec_time
            else:
                ticket.gross_weight = sec_weight
                ticket.gross_date = sec_date
                ticket.gross_time = sec_time

            ticket.status = EmergencyTicketStatus.COMPLETED
            if form.cleaned_data.get("notes"):
                extra_notes = form.cleaned_data.get("notes")
                ticket.notes = (ticket.notes + "\n" + extra_notes).strip() if ticket.notes else extra_notes

            ticket.save()

            messages.success(request, f"وزن دوم برای قبض متفرقه {ticket.serial_number} با موفقیت ثبت و قبض تکمیل گردید.")
            if "save_and_print" in request.POST:
                return redirect("weighbridge:emergency_ticket_print", pk=ticket.pk)
            return redirect("weighbridge:emergency_ticket_detail", pk=ticket.pk)
    else:
        form = EmergencySecondWeightForm(
            instance=ticket,
            initial={
                "second_weight_date_jalali": get_today_jalali(),
                "second_weight_time_str": timezone.localtime().strftime("%H:%M"),
            }
        )

    return render(request, "weighbridge/emergency_ticket_second_weight.html", {
        "form": form,
        "ticket": ticket,
        "is_missing_tare": is_missing_tare,
        "missing_weight_name": missing_weight_name,
        "title": f"ثبت وزن دوم قبض متفرقه {ticket.serial_number}",
    })


@login_required
@weighbridge_role_required
def emergency_ticket_list(request):
    """
    لیست جامع قبوض توزین متفرقه / آزاد (مستقل از قبوض کارخانه).
    """
    today_g = get_today_gregorian()
    qs = EmergencyWeighTicket.objects.all().order_by("-id")

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(serial_number__icontains=q) |
            Q(driver_name__icontains=q) |
            Q(driver_mobile__icontains=q) |
            Q(company_name__icontains=q) |
            Q(license_plate__icontains=q)
        )

    status = request.GET.get("status", "").strip()
    if status in EmergencyTicketStatus.values:
        qs = qs.filter(status=status)

    date_from_j = request.GET.get("date_from", "").strip()
    date_to_j = request.GET.get("date_to", "").strip()
    if date_from_j:
        try:
            g_from = jalali_to_gregorian(date_from_j)
            qs = qs.filter(weight_date__gte=g_from)
        except Exception:
            pass
    if date_to_j:
        try:
            g_to = jalali_to_gregorian(date_to_j)
            qs = qs.filter(weight_date__lte=g_to)
        except Exception:
            pass

    total_count = EmergencyWeighTicket.objects.count()
    today_count = EmergencyWeighTicket.objects.filter(weight_date=today_g).count()
    waiting_count = EmergencyWeighTicket.objects.filter(status=EmergencyTicketStatus.WAITING_SECOND).count()
    total_net_kg = EmergencyWeighTicket.objects.filter(status=EmergencyTicketStatus.COMPLETED).aggregate(
        s=Sum("net_weight")
    )["s"] or Decimal("0")
    total_net_ton = round(total_net_kg / Decimal("1000"), 2)

    paginator = Paginator(qs, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(request, "weighbridge/emergency_ticket_list.html", {
        "page_obj": page_obj,
        "total_count": total_count,
        "today_count": today_count,
        "waiting_count": waiting_count,
        "total_net_ton": total_net_ton,
        "query": q,
        "selected_status": status,
        "date_from": date_from_j,
        "date_to": date_to_j,
        "title": "لیست قبوض توزین متفرقه / آزاد (سایر شرکت‌ها)",
    })


@login_required
def emergency_ticket_detail(request, pk):
    """
    مشاهده جزئیات قبض متفرقه.
    """
    ticket = get_object_or_404(EmergencyWeighTicket, pk=pk)
    return render(request, "weighbridge/emergency_ticket_detail.html", {
        "ticket": ticket,
        "title": f"جزئیات قبض متفرقه {ticket.serial_number}",
    })


@login_required
def emergency_ticket_print(request, pk):
    """
    چاپ قبض توزین متفرقه ویژه شرکت‌های متقاضی (A5 / A4 / POS).
    """
    ticket = get_object_or_404(EmergencyWeighTicket, pk=pk)
    settings_obj = SystemSetting.get_settings()
    template_type = request.GET.get("template", settings_obj.default_print_template or "a5")

    return render(request, "weighbridge/emergency_ticket_print.html", {
        "ticket": ticket,
        "settings": settings_obj,
        "template_type": template_type,
        "print_date": get_today_jalali(),
        "print_time": timezone.localtime().strftime("%H:%M"),
        "title": f"چاپ قبض متفرقه {ticket.serial_number}",
    })


@login_required
@manager_or_admin_required
def emergency_ticket_cancel(request, pk):
    """
    ابطال قبض متفرقه با درج دلیل.
    """
    ticket = get_object_or_404(EmergencyWeighTicket, pk=pk)

    if request.method == "POST":
        reason = request.POST.get("cancellation_reason", "").strip()
        if not reason:
            messages.error(request, "وارد کردن دلیل ابطال سند الزامی است.")
            return redirect("weighbridge:emergency_ticket_detail", pk=ticket.pk)

        ticket.status = EmergencyTicketStatus.CANCELLED
        ticket.cancellation_reason = reason
        ticket.cancelled_by = request.user
        ticket.cancelled_at = timezone.now()
        ticket.save()

        messages.warning(request, f"قبض متفرقه {ticket.serial_number} با موفقیت باطل گردید.")
        return redirect("weighbridge:emergency_ticket_detail", pk=ticket.pk)

    return render(request, "weighbridge/emergency_ticket_cancel_confirm.html", {
        "ticket": ticket,
        "title": f"ابطال قبض متفرقه {ticket.serial_number}",
    })


@login_required
def print_center(request):
    """
    مرکز جامع و هوشمند چاپ قبض‌های باسکول
    دسترسی آزاد برای تمامی کاربران با هر سطح دسترسی و نقش در سیستم.
    قابلیت‌های حرفه‌ای:
    - چاپ سریع تمام قبض‌های امروز با یک کلیک (در انواع قالب‌ها)
    - فیلترهای پیشرفته زمانی (امروز، دیروز، ۷ روز گذشته، ماه جاری، بازه دلخواه جلالی)
    - فیلتر وضعیت، طرف حساب، کالا، نوع عملیات، جستجوی پلاک و شماره قبض
    - تفکیک قبوض رسمی و قبوض متفرقه (آزاد)
    - چاپ گروهی موارد انتخاب شده در قالب‌های A4، A5، ۲ قبض در یک صفحه، POS، و کارنامه تجمیعی
    """
    tab = request.GET.get("tab", "regular")
    date_preset = request.GET.get("date_preset", "")
    start_date_j = request.GET.get("start_date", "").strip()
    end_date_j = request.GET.get("end_date", "").strip()
    status_filter = request.GET.get("status", "all")
    product_filter = request.GET.get("product", "")
    party_filter = request.GET.get("party", "")
    op_filter = request.GET.get("operation_type", "")
    q = request.GET.get("q", "").strip()

    today_g = get_today_gregorian()
    today_j = get_today_jalali()

    # Determine date range based on preset or explicit dates
    g_start = None
    g_end = None

    if date_preset and date_preset not in ("all", "custom"):
        try:
            g_start, g_end = get_jalali_range_gregorian(date_preset)
        except Exception:
            g_start, g_end = None, None
    elif start_date_j or end_date_j:
        date_preset = "custom"
        if start_date_j:
            g_start = jalali_to_gregorian(start_date_j)
        if end_date_j:
            g_end = jalali_to_gregorian(end_date_j)

    # 1. Regular Tickets Queryset
    reg_qs = WeighTicket.objects.select_related(
        "operation_type", "party", "product", "driver", "vehicle", "vehicle_type",
        "first_weight_operator", "second_weight_operator"
    ).all().order_by("-id")

    if g_start:
        reg_qs = reg_qs.filter(first_weight_date__gte=g_start)
    if g_end:
        reg_qs = reg_qs.filter(first_weight_date__lte=g_end)

    if status_filter and status_filter != "all":
        reg_qs = reg_qs.filter(status=status_filter)

    if product_filter:
        reg_qs = reg_qs.filter(product_id=product_filter)

    if party_filter:
        reg_qs = reg_qs.filter(party_id=party_filter)

    if op_filter:
        reg_qs = reg_qs.filter(operation_type_id=op_filter)

    if q:
        reg_qs = reg_qs.filter(
            Q(serial_number__icontains=q) |
            Q(license_plate_display__icontains=q) |
            Q(driver__full_name__icontains=q) |
            Q(driver_name_custom__icontains=q) |
            Q(party__name__icontains=q) |
            Q(product__name__icontains=q) |
            Q(waybill_number__icontains=q) |
            Q(notes__icontains=q)
        )

    # 2. Emergency Tickets Queryset
    emg_qs = EmergencyWeighTicket.objects.select_related("operator").all().order_by("-id")

    if g_start:
        emg_qs = emg_qs.filter(weight_date__gte=g_start)
    if g_end:
        emg_qs = emg_qs.filter(weight_date__lte=g_end)

    if status_filter and status_filter != "all":
        if status_filter in [EmergencyTicketStatus.WAITING_SECOND, EmergencyTicketStatus.COMPLETED, EmergencyTicketStatus.CANCELLED]:
            emg_qs = emg_qs.filter(status=status_filter)

    if q:
        emg_qs = emg_qs.filter(
            Q(serial_number__icontains=q) |
            Q(license_plate__icontains=q) |
            Q(driver_name__icontains=q) |
            Q(company_name__icontains=q) |
            Q(notes__icontains=q)
        )

    # General Today Counters for quick actions badge
    today_reg_total = WeighTicket.objects.filter(first_weight_date=today_g).count()
    today_reg_completed = WeighTicket.objects.filter(first_weight_date=today_g, status=TicketStatus.COMPLETED).count()
    today_in_yard = WeighTicket.objects.filter(status=TicketStatus.WAITING_SECOND).count()
    today_emg_total = EmergencyWeighTicket.objects.filter(weight_date=today_g).count()

    # Active tab dataset & metrics
    if tab == "emergency":
        active_count = emg_qs.count()
        aggregates = emg_qs.aggregate(
            total_net=Sum("net_weight"),
            total_gross=Sum("gross_weight"),
            total_tare=Sum("tare_weight"),
        )
        total_net = aggregates["total_net"] or Decimal("0")
        total_gross = aggregates["total_gross"] or Decimal("0")
        total_tare = aggregates["total_tare"] or Decimal("0")
        total_freight = Decimal("0")
        total_loss = Decimal("0")

        paginator = Paginator(emg_qs, 40)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)
    else:
        active_count = reg_qs.count()
        aggregates = reg_qs.aggregate(
            total_net=Sum("net_weight"),
            total_gross=Sum("gross_weight"),
            total_tare=Sum("tare_weight"),
            total_loss=Sum("loss_weight"),
            total_freight=Sum("freight_amount"),
        )
        total_net = aggregates["total_net"] or Decimal("0")
        total_gross = aggregates["total_gross"] or Decimal("0")
        total_tare = aggregates["total_tare"] or Decimal("0")
        total_loss = aggregates["total_loss"] or Decimal("0")
        total_freight = aggregates["total_freight"] or Decimal("0")

        paginator = Paginator(reg_qs, 40)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

    regular_tab_count = reg_qs.count()
    emergency_tab_count = emg_qs.count()

    total_net_ton = round(total_net / Decimal("1000"), 3)
    total_gross_ton = round(total_gross / Decimal("1000"), 3)

    # Masterdata for dropdowns
    products = Product.objects.filter(is_active=True).order_by("name")
    parties = Party.objects.filter(is_active=True).order_by("name")
    op_types = OperationType.objects.filter(is_active=True).order_by("name")

    return render(request, "weighbridge/print_center.html", {
        "tab": tab,
        "page_obj": page_obj,
        "active_count": active_count,
        "regular_tab_count": regular_tab_count,
        "emergency_tab_count": emergency_tab_count,
        "total_net": total_net,
        "total_gross": total_gross,
        "total_tare": total_tare,
        "total_loss": total_loss,
        "total_freight": total_freight,
        "total_net_ton": total_net_ton,
        "total_gross_ton": total_gross_ton,
        # Today counters for quick one-click badges
        "today_reg_total": today_reg_total,
        "today_reg_completed": today_reg_completed,
        "today_in_yard": today_in_yard,
        "today_emg_total": today_emg_total,
        # Filters state
        "date_preset": date_preset,
        "start_date_j": start_date_j,
        "end_date_j": end_date_j,
        "status_filter": status_filter,
        "product_filter": product_filter,
        "party_filter": party_filter,
        "op_filter": op_filter,
        "q": q,
        # Masterdata
        "products": products,
        "parties": parties,
        "op_types": op_types,
        "today_jalali": today_j,
        "title": "مرکز جامع چاپ قبض‌های باسکول",
    })


@login_required
def batch_print(request):
    """
    چاپ گروهی و دسته‌ای قبض‌های باسکول
    پشتیبانی از قالب‌های A4، A5، ۲ قبض در یک برگه A4، فیش حرارتی POS، و جدول خلاصه.
    """
    ticket_type = request.GET.get("ticket_type") or request.POST.get("ticket_type", "regular")
    layout = request.GET.get("layout") or request.POST.get("layout", "a4")
    autoprint = (request.GET.get("autoprint", "1") == "1")
    preset = request.GET.get("preset", "")

    today_g = get_today_gregorian()

    # Determine ticket IDs
    ticket_ids = []
    if request.method == "POST":
        ticket_ids = request.POST.getlist("ticket_ids")
        if not ticket_ids and request.POST.get("ids"):
            ticket_ids = [x.strip() for x in request.POST.get("ids").split(",") if x.strip()]
        if not ticket_ids and request.POST.get("ticket_ids_str"):
            ticket_ids = [x.strip() for x in request.POST.get("ticket_ids_str").split(",") if x.strip()]
    else:
        ids_str = request.GET.get("ids") or request.GET.get("ticket_ids_str", "")
        if ids_str:
            ticket_ids = [x.strip() for x in ids_str.split(",") if x.strip()]
        if not ticket_ids and request.GET.getlist("ticket_ids"):
            ticket_ids = request.GET.getlist("ticket_ids")

    tickets = []
    if ticket_type == "emergency":
        qs = EmergencyWeighTicket.objects.select_related("operator").all().order_by("-id")
        if ticket_ids:
            qs = qs.filter(id__in=ticket_ids)
        elif preset == "today":
            qs = qs.filter(weight_date=today_g)
        elif preset == "in_yard":
            qs = qs.filter(status=EmergencyTicketStatus.WAITING_SECOND)
        else:
            # apply any query filters
            start_date_j = request.GET.get("start_date")
            end_date_j = request.GET.get("end_date")
            if start_date_j:
                g_start = jalali_to_gregorian(start_date_j)
                if g_start:
                    qs = qs.filter(weight_date__gte=g_start)
            if end_date_j:
                g_end = jalali_to_gregorian(end_date_j)
                if g_end:
                    qs = qs.filter(weight_date__lte=g_end)
            status = request.GET.get("status")
            if status and status != "all":
                qs = qs.filter(status=status)
            q = request.GET.get("q", "").strip()
            if q:
                qs = qs.filter(
                    Q(serial_number__icontains=q) |
                    Q(license_plate__icontains=q) |
                    Q(driver_name__icontains=q) |
                    Q(company_name__icontains=q)
                )

        tickets = list(qs[:150])
    else:
        qs = WeighTicket.objects.select_related(
            "operation_type", "party", "product", "driver", "vehicle", "vehicle_type",
            "origin", "destination", "unload_location", "loss_type",
            "first_weight_operator", "second_weight_operator"
        ).all().order_by("-id")

        if ticket_ids:
            qs = qs.filter(id__in=ticket_ids)
        elif preset == "today":
            qs = qs.filter(first_weight_date=today_g)
        elif preset == "today_completed":
            qs = qs.filter(first_weight_date=today_g, status=TicketStatus.COMPLETED)
        elif preset == "in_yard":
            qs = qs.filter(status=TicketStatus.WAITING_SECOND)
        else:
            # Apply date preset or query filters
            date_preset = request.GET.get("date_preset")
            if date_preset and date_preset not in ("all", "custom"):
                try:
                    g_start, g_end = get_jalali_range_gregorian(date_preset)
                    if g_start:
                        qs = qs.filter(first_weight_date__gte=g_start)
                    if g_end:
                        qs = qs.filter(first_weight_date__lte=g_end)
                except Exception:
                    pass
            else:
                start_date_j = request.GET.get("start_date")
                end_date_j = request.GET.get("end_date")
                if start_date_j:
                    g_start = jalali_to_gregorian(start_date_j)
                    if g_start:
                        qs = qs.filter(first_weight_date__gte=g_start)
                if end_date_j:
                    g_end = jalali_to_gregorian(end_date_j)
                    if g_end:
                        qs = qs.filter(first_weight_date__lte=g_end)

            status = request.GET.get("status")
            if status and status != "all":
                qs = qs.filter(status=status)
            product = request.GET.get("product")
            if product:
                qs = qs.filter(product_id=product)
            party = request.GET.get("party")
            if party:
                qs = qs.filter(party_id=party)
            op = request.GET.get("operation_type")
            if op:
                qs = qs.filter(operation_type_id=op)
            q = request.GET.get("q", "").strip()
            if q:
                qs = qs.filter(
                    Q(serial_number__icontains=q) |
                    Q(license_plate_display__icontains=q) |
                    Q(driver__full_name__icontains=q) |
                    Q(party__name__icontains=q) |
                    Q(product__name__icontains=q) |
                    Q(waybill_number__icontains=q)
                )

        tickets = list(qs[:150])

    if not tickets:
        messages.warning(request, "هیچ قبض معتبری با معیارهای انتخابی برای چاپ یافت نشد.")
        return redirect("weighbridge:print_center")

    log_audit(
        action=AuditAction.PRINT,
        model_name="WeighTicketBatch",
        record_id=f"batch_{len(tickets)}",
        record_repr=f"چاپ گروهی {len(tickets)} قبض ({ticket_type})",
        reason=f"چاپ در قالب {layout.upper()} - کاربر: {request.user.username}"
    )

    settings_obj = SystemSetting.get_settings()

    total_net = sum([t.net_weight or Decimal("0") for t in tickets])
    total_gross = sum([t.gross_weight or Decimal("0") for t in tickets])
    total_tare = sum([t.tare_weight or Decimal("0") for t in tickets])
    total_loss = sum([getattr(t, "loss_weight", Decimal("0")) or Decimal("0") for t in tickets])
    total_freight = sum([getattr(t, "freight_amount", Decimal("0")) or Decimal("0") for t in tickets])

    ticket_pairs = []
    if layout == "two_in_one":
        for i in range(0, len(tickets), 2):
            ticket_pairs.append({
                "first": tickets[i],
                "second": tickets[i+1] if i+1 < len(tickets) else None
            })

    ticket_ids_str = ",".join(str(t.id) for t in tickets)

    context = {
        "tickets": tickets,
        "ticket_pairs": ticket_pairs,
        "tickets_count": len(tickets),
        "ticket_ids_str": ticket_ids_str,
        "layout": layout,
        "ticket_type": ticket_type,
        "settings": settings_obj,
        "print_date": get_today_jalali(),
        "print_time": timezone.localtime().strftime("%H:%M"),
        "total_net": total_net,
        "total_gross": total_gross,
        "total_tare": total_tare,
        "total_loss": total_loss,
        "total_freight": total_freight,
        "total_net_ton": round(total_net / Decimal("1000"), 3),
        "total_gross_ton": round(total_gross / Decimal("1000"), 3),
        "autoprint": autoprint,
        "title": f"چاپ گروهی {len(tickets)} قبض - {settings_obj.company_name}",
    }

    if layout == "summary":
        return render(request, "weighbridge/print_summary_sheet.html", context)
    return render(request, "weighbridge/batch_ticket_print.html", context)


@login_required
@manager_or_admin_required
@require_POST
def ticket_revision_approve(request, revision_id):
    """
    Supervisor action to approve and apply an existing pending revision.
    Enforces separation of duties and atomic lock acquisition.
    """
    review_reason = request.POST.get("review_reason", "").strip()
    if not review_reason or len(review_reason) < 3:
        messages.error(request, "ثبت ادله تصمیم (حداقل ۳ نویسه) برای تأیید درخواست بازنگری الزامی است.")
        rev_obj = TicketRevision.objects.filter(pk=revision_id).first()
        return redirect("weighbridge:ticket_detail", pk=rev_obj.ticket_id) if rev_obj else redirect("weighbridge:ticket_list")

    from weighbridge.revision_service import TicketRevisionService
    try:
        rev = TicketRevisionService.approve_revision(
            revision=revision_id,
            reviewer=request.user,
            review_reason=review_reason,
            auto_apply=True,
            client_ip=request.META.get("REMOTE_ADDR")
        )
        messages.success(
            request,
            f"بازنگری ویرایش {rev.revision_number} با موفقیت تأیید و مقادیر جدید بر قبض {rev.ticket.serial_number} اعمال گردید."
        )
        return redirect("weighbridge:ticket_detail", pk=rev.ticket_id)
    except (ValidationError, PermissionDenied) as exc:
        err_msg = exc.messages[0] if hasattr(exc, "messages") else str(exc)
        messages.error(request, f"عدم امکان تأیید بازنگری: {err_msg}")
        rev_obj = TicketRevision.objects.filter(pk=revision_id).first()
        ticket_id = rev_obj.ticket_id if rev_obj else None
        if ticket_id:
            return redirect("weighbridge:ticket_detail", pk=ticket_id)
        return redirect("weighbridge:ticket_list")


@login_required
@manager_or_admin_required
@require_POST
def ticket_revision_reject(request, revision_id):
    """
    Supervisor action to reject a pending revision.
    """
    review_reason = request.POST.get("review_reason", "").strip()
    if not review_reason or len(review_reason) < 3:
        messages.error(request, "ثبت دلیل برای رد درخواست بازنگری الزامی است (حداقل ۳ نویسه).")
        rev_obj = TicketRevision.objects.filter(pk=revision_id).first()
        return redirect("weighbridge:ticket_detail", pk=rev_obj.ticket_id) if rev_obj else redirect("weighbridge:ticket_list")

    from weighbridge.revision_service import TicketRevisionService
    try:
        rev = TicketRevisionService.reject_revision(
            revision=revision_id,
            reviewer=request.user,
            review_reason=review_reason,
            client_ip=request.META.get("REMOTE_ADDR")
        )
        messages.warning(request, f"درخواست بازنگری برای قبض {rev.ticket.serial_number} رد شد.")
        return redirect("weighbridge:ticket_detail", pk=rev.ticket_id)
    except (ValidationError, PermissionDenied) as exc:
        err_msg = exc.messages[0] if hasattr(exc, "messages") else str(exc)
        messages.error(request, f"عدم امکان رد بازنگری: {err_msg}")
        rev_obj = TicketRevision.objects.filter(pk=revision_id).first()
        return redirect("weighbridge:ticket_detail", pk=rev_obj.ticket_id) if rev_obj else redirect("weighbridge:ticket_list")


@login_required
@require_POST
def ticket_revision_withdraw(request, revision_id):
    """
    Requester action to withdraw a pending revision.
    """
    withdraw_reason = request.POST.get("withdraw_reason", "").strip()
    from weighbridge.revision_service import TicketRevisionService
    try:
        rev = TicketRevisionService.withdraw_revision(
            revision=revision_id,
            user=request.user,
            reason=withdraw_reason,
            client_ip=request.META.get("REMOTE_ADDR")
        )
        messages.info(request, f"انصراف از درخواست بازنگری برای قبض {rev.ticket.serial_number} با موفقیت ثبت شد.")
        return redirect("weighbridge:ticket_detail", pk=rev.ticket_id)
    except (ValidationError, PermissionDenied) as exc:
        err_msg = exc.messages[0] if hasattr(exc, "messages") else str(exc)
        messages.error(request, f"عدم امکان انصراف: {err_msg}")
        rev_obj = TicketRevision.objects.filter(pk=revision_id).first()
        return redirect("weighbridge:ticket_detail", pk=rev_obj.ticket_id) if rev_obj else redirect("weighbridge:ticket_list")


