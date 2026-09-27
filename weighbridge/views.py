from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.core.paginator import Paginator
from django.utils import timezone
from datetime import datetime, time
from decimal import Decimal
import re

from weighbridge.models import WeighTicket, TicketStatus, WeightMode
from weighbridge.forms import TicketCreateForm, SecondWeightForm, TicketEditManagerForm
from weighbridge.services import TicketCalculationService, VehicleDriverRegistrationService
from core.weight_provider import get_active_weight_provider
from core.jalali import jalali_to_gregorian, get_today_jalali, format_jalali_date, get_today_gregorian
from core.models import SystemSetting
from masterdata.models import Product, Party, Driver, Vehicle, OperationType
from accounts.decorators import role_required, manager_or_admin_required
from audit.services import log_audit
from audit.models import AuditAction, AuditLog
from monitoring.services.anomaly_engine import AnomalyDetectionEngine
from django.core.exceptions import ValidationError
from weighbridge.plate_policy import DailyPlatePolicy, can_manage_plate_exceptions, normalize_plate

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

            # Check if second weight is also provided (direct complete mode)
            w2_raw = form.cleaned_data.get("second_weight")
            has_w2 = w2_raw is not None and str(w2_raw).strip() != "" and Decimal(str(w2_raw)) > 0
            
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

            # Auto-register or link Vehicle and Driver into system MasterData
            VehicleDriverRegistrationService.resolve_or_create(ticket, form.cleaned_data)

            try:
                DailyPlatePolicy.save(ticket, user=request.user, assign_serial=True)
            except ValidationError as exc:
                form.add_error(None, exc)
                return render(request, "weighbridge/ticket_create.html", {
                    "form": form, "title": "ثبت باسکول و توزین جدید", "settings": SystemSetting.get_settings(),
                    "can_manage_plate_exceptions": can_manage_plate_exceptions(request.user),
                })

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

            if ticket.status == TicketStatus.COMPLETED:
                messages.success(request, f"قبض شماره {ticket.serial_number} با موفقیت تکمیل و ثبت نهایی شد.")
                action_btn = request.POST.get("submit_action")
                if action_btn == "save_and_print":
                    return redirect(f"/weighbridge/tickets/{ticket.id}/print/")
                return redirect("weighbridge:ticket_detail", pk=ticket.id)
            else:
                messages.success(request, f"وزن اول برای قبض {ticket.serial_number} ثبت گردید (خودرو در انتظار وزن دوم).")
                return redirect("weighbridge:trucks_in_yard")
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
    return render(request, "weighbridge/ticket_create.html", {
        "form": form,
        "title": "ثبت باسکول و توزین جدید",
        "settings": settings_obj,
        "can_manage_plate_exceptions": can_manage_plate_exceptions(request.user),
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

    if request.method == "POST":
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
            ticket.status = TicketStatus.COMPLETED

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

            ticket.save()

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

    return render(request, "weighbridge/ticket_second_weight.html", {
        "form": form,
        "ticket": ticket,
        "title": f"ثبت وزن دوم - قبض شماره {ticket.serial_number}",
    })


@login_required
def trucks_in_yard(request):
    """
    Dedicated view for vehicles currently inside the company waiting for 2nd weight.
    """
    waiting_tickets = WeighTicket.objects.filter(
        status__in=[TicketStatus.WAITING_SECOND, TicketStatus.FIRST_REGISTERED]
    ).select_related("product", "party", "driver", "vehicle", "first_weight_operator").order_by("-created_at")

    now = timezone.now()
    tickets_with_duration = []
    for t in waiting_tickets:
        diff_mins = int((now - t.created_at).total_seconds() / 60)
        hours = diff_mins // 60
        mins = diff_mins % 60
        duration_str = f"{hours} ساعت و {mins} دقیقه" if hours > 0 else f"{mins} دقیقه"
        tickets_with_duration.append({
            "ticket": t,
            "duration_str": duration_str,
            "is_long_wait": diff_mins > 180,
        })

    return render(request, "weighbridge/trucks_in_yard.html", {
        "items": tickets_with_duration,
        "count": len(tickets_with_duration),
        "title": "خودروهای در انتظار تکمیل باسکول (داخل محوطه)",
    })


@login_required
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

    return render(request, "weighbridge/ticket_detail.html", {
        "ticket": ticket,
        "audit_logs": audit_logs,
        "monitoring_summary": monitoring_summary,
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
        }

        form = TicketEditManagerForm(request.POST, instance=ticket)
        if form.is_valid():
            reason = form.cleaned_data.get("manager_reason")
            ticket = form.save(commit=False)
            ticket.last_edited_by = request.user
            ticket.last_edit_reason = reason

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

            try:
                DailyPlatePolicy.save(ticket, user=request.user)
            except ValidationError as exc:
                form.add_error(None, exc)
                return render(request, "weighbridge/ticket_edit.html", {
                    "form": form, "ticket": ticket, "title": "اصلاح و ویرایش مدیریتی قبض",
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

    return render(request, "weighbridge/ticket_edit.html", {
        "form": form,
        "ticket": ticket,
        "title": f"اصلاح و ویرایش مدیریتی قبض {ticket.serial_number}",
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
    High quality print preview supporting A4, A5, and POS thermal receipts.
    """
    ticket = get_object_or_404(
        WeighTicket.objects.select_related(
            "operation_type", "party", "product", "driver", "vehicle", "vehicle_type",
            "origin", "destination", "unload_location", "loss_type",
            "first_weight_operator", "second_weight_operator"
        ),
        pk=pk
    )

    settings_obj = SystemSetting.get_settings()
    template_type = request.GET.get("template", settings_obj.default_print_template or "a4")

    # Audit log print action
    log_audit(
        action=AuditAction.PRINT,
        model_name="WeighTicket",
        record_id=ticket.id,
        record_repr=f"قبض شماره {ticket.serial_number}",
        reason=f"چاپ قبض در قالب {template_type.upper()}"
    )

    template_name = f"weighbridge/ticket_print_{template_type}.html"
    return render(request, template_name, {
        "ticket": ticket,
        "settings": settings_obj,
        "print_date": get_today_jalali(),
        "print_time": timezone.localtime().strftime("%H:%M"),
        "title": f"چاپ قبض {ticket.serial_number}",
    })


@login_required
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

    # 1. Find vehicle record by exact display, partial display, or normalized plate

    vehicle = Vehicle.objects.filter(
        Q(plate_display__iexact=plate) |
        Q(plate_display__icontains=plate)
    ).select_related("vehicle_type", "default_driver").first()

    if not vehicle and norm_plate:
        for v in Vehicle.objects.select_related("vehicle_type", "default_driver").all():
            if normalize_plate(v.plate_display) == norm_plate:
                vehicle = v
                break

    # 2. Search ticket history using both textual match and normalized plate
    ticket_q = Q(license_plate_display__iexact=plate) | Q(license_plate_display__icontains=plate)
    if norm_plate:
        ticket_q |= Q(normalized_plate=norm_plate)
    tickets_qs = WeighTicket.objects.filter(ticket_q).order_by("-id")
    trip_count = tickets_qs.count()

    last_ticket = tickets_qs.select_related("driver", "product", "party", "vehicle_type", "vehicle").first()

    # 3. Check for open / in-progress tickets (waiting for second weight or first weight)
    open_ticket = tickets_qs.filter(
        status__in=[TicketStatus.WAITING_SECOND, TicketStatus.WAITING_FIRST]
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

    response_data = {
        "is_blocked": False,
        "found": is_duplicate,
        "is_duplicate": is_duplicate,

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
