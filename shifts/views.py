from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib import messages
from django.utils import timezone
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import IntegrityError, models

from core.jalali import format_jalali_date, format_jalali_datetime, get_today_jalali, jalali_to_gregorian
from shifts.models import (
    WorkShift, ShiftSession, ShiftSessionStatus,
    ShiftOperatorAssignment, ShiftOperatorRole, ShiftAssignmentStatus,
    ShiftExceptionLog, ShiftHandover, ShiftHandoverStatus,
    ShiftHandoverItem, ShiftHandoverItemCategory
)
from shifts.forms import (
    WorkShiftForm, ShiftSessionOpenForm, ShiftSessionCloseForm,
    ShiftOperatorAssignmentForm, ShiftSubstitutionForm, ShiftExceptionAcknowledgeForm,
    ShiftHandoverInitiateForm, ShiftHandoverAcceptForm, ShiftHandoverDisputeForm, ShiftHandoverResolveForm
)
from shifts.services import ShiftResolutionService
from shifts.handover_service import ShiftHandoverService
from audit.services import log_audit
from audit.models import AuditAction


# ---------------------------------------------------------
# WorkShift Schedule Administration Views
# ---------------------------------------------------------

@login_required
def shift_list(request):
    """List of all configured work shifts."""
    if not (request.user.is_superuser or request.user.profile.can_manage_shifts):
        messages.error(request, "شما مجوز مدیریت الگوهای شیفت را ندارید.")
        return redirect("dashboard:index")

    shifts = WorkShift.objects.all().order_by("start_time")
    return render(request, "shifts/shift_list.html", {
        "shifts": shifts,
        "title": "تعریف و مدیریت الگوهای شیفت کاری",
    })


@login_required
def shift_create(request):
    """Create a new work shift definition."""
    if not (request.user.is_superuser or request.user.profile.can_manage_shifts):
        messages.error(request, "شما مجوز تعریف شیفت جدید را ندارید.")
        return redirect("shifts:shift_list")

    if request.method == "POST":
        form = WorkShiftForm(request.POST)
        if form.is_valid():
            shift = form.save(commit=False)
            shift.created_by = request.user
            shift.save()
            messages.success(request, f"الگوی شیفت «{shift.name}» با موفقیت ثبت شد.")
            return redirect("shifts:shift_list")
    else:
        form = WorkShiftForm()

    return render(request, "shifts/shift_form.html", {
        "form": form,
        "title": "تعریف الگوی شیفت جدید",
        "is_edit": False,
    })


@login_required
def shift_edit(request, pk):
    """Edit an existing work shift definition."""
    if not (request.user.is_superuser or request.user.profile.can_manage_shifts):
        messages.error(request, "شما مجوز ویرایش الگوی شیفت را ندارید.")
        return redirect("shifts:shift_list")

    shift = get_object_or_404(WorkShift, pk=pk)
    if request.method == "POST":
        form = WorkShiftForm(request.POST, instance=shift)
        if form.is_valid():
            form.save()
            messages.success(request, f"الگوی شیفت «{shift.name}» با موفقیت ویرایش شد.")
            return redirect("shifts:shift_list")
    else:
        form = WorkShiftForm(instance=shift)

    return render(request, "shifts/shift_form.html", {
        "form": form,
        "shift": shift,
        "title": f"ویرایش الگوی شیفت {shift.name}",
        "is_edit": True,
    })


@login_required
@require_POST
def shift_toggle(request, pk):
    """Toggle active/inactive status of a work shift."""
    if not (request.user.is_superuser or request.user.profile.can_manage_shifts):
        return JsonResponse({"success": False, "error": "دسترسی غیرمجاز"}, status=403)

    shift = get_object_or_404(WorkShift, pk=pk)
    shift.is_active = not shift.is_active
    shift.save(update_fields=["is_active"])
    status_text = "فعال" if shift.is_active else "غیرفعال"
    messages.success(request, f"وضعیت شیفت «{shift.name}» به {status_text} تغییر یافت.")
    return redirect("shifts:shift_list")


# ---------------------------------------------------------
# ShiftSession Runtime Lifecycle Views
# ---------------------------------------------------------

@login_required
def session_list(request):
    """List of all shift sessions with filtering."""
    if not (request.user.is_superuser or request.user.profile.can_operate_shift):
        messages.error(request, "شما مجوز مشاهده جلسات شیفت را ندارید.")
        return redirect("dashboard:index")

    status_filter = request.GET.get("status", "")
    date_filter = request.GET.get("date", "")
    qs = ShiftSession.objects.select_related("shift", "opened_by", "closed_by").all().order_by("-operational_date", "-actual_start", "-id")

    if status_filter:
        qs = qs.filter(status=status_filter)
    if date_filter:
        g_date = jalali_to_gregorian(date_filter)
        if g_date:
            qs = qs.filter(operational_date=g_date)

    paginator = Paginator(qs, 15)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    active_sessions = ShiftSession.objects.filter(status=ShiftSessionStatus.ACTIVE).select_related("shift", "opened_by")

    return render(request, "shifts/session_list.html", {
        "page_obj": page_obj,
        "active_sessions": active_sessions,
        "status_filter": status_filter,
        "date_filter": date_filter,
        "statuses": ShiftSessionStatus.choices,
        "title": "مدیریت و پایش جلسات شیفت کاری",
        "is_shift_management_enabled": ShiftResolutionService.is_shift_management_enabled(),
    })


@login_required
def session_open(request):
    """Open and activate a new shift session."""
    if not (request.user.is_superuser or request.user.profile.can_operate_shift):
        messages.error(request, "شما مجوز افتتاح شیفت را ندارید.")
        return redirect("shifts:session_list")

    if request.method == "POST":
        form = ShiftSessionOpenForm(request.POST)
        if form.is_valid():
            session = form.save(commit=False)
            session.opened_by = request.user
            session.actual_start = timezone.now()
            session.status = ShiftSessionStatus.ACTIVE

            try:
                session.save()
                # Automatically check in the opening user as primary operator
                ShiftResolutionService.check_in_operator(
                    session=session,
                    operator=request.user,
                    role=ShiftOperatorRole.PRIMARY
                )
                messages.success(request, f"شیفت «{session.shift.name}» برای تاریخ عملیاتی {session.jalali_operational_date} با موفقیت افتتاح شد.")
                return redirect("shifts:session_detail", pk=session.pk)
            except IntegrityError:
                form.add_error(None, "جلسه فعال یا بسته‌شده دیگری برای این الگوی شیفت در این تاریخ عملیاتی قبلاً ثبت شده است.")
            except ValidationError as exc:
                form.add_error(None, exc)
    else:
        # Prepopulate with active shift matching current time if available
        today_j = get_today_jalali()
        initial_data = {"operational_date_jalali": today_j}
        active_shifts = WorkShift.objects.filter(is_active=True)
        if active_shifts.exists():
            initial_data["shift"] = active_shifts.first()
        form = ShiftSessionOpenForm(initial=initial_data)

    return render(request, "shifts/session_open.html", {
        "form": form,
        "title": "افتتاح و آغاز رسمی جلسه شیفت کاری",
    })


@login_required
def session_detail(request, pk):
    """Detailed view of a shift session including assignments and tickets."""
    session = get_object_or_404(
        ShiftSession.objects.select_related("shift", "opened_by", "closed_by"),
        pk=pk
    )
    assignments = session.assignments.select_related("operator", "operator__profile", "authorized_by", "substituted_operator").all()
    first_tickets_count = session.first_weight_tickets.count()
    second_tickets_count = session.second_weight_tickets.count()

    is_checked_in = False
    my_assignment = None
    if request.user.is_authenticated:
        my_assignment = assignments.filter(operator=request.user, status=ShiftAssignmentStatus.CHECKED_IN).first()
        is_checked_in = bool(my_assignment)

    can_manage = request.user.is_superuser or request.user.profile.can_manage_shifts
    active_handover = ShiftHandoverService.get_active_handover_for_session(session)
    last_handover = session.outgoing_handovers.order_by("-id").first()

    return render(request, "shifts/session_detail.html", {
        "session": session,
        "assignments": assignments,
        "first_tickets_count": first_tickets_count,
        "second_tickets_count": second_tickets_count,
        "is_checked_in": is_checked_in,
        "my_assignment": my_assignment,
        "can_manage": can_manage,
        "active_handover": active_handover,
        "last_handover": last_handover,
        "title": f"جزییات {session}",
    })


@login_required
def session_close(request, pk):
    """Close an active shift session."""
    if not (request.user.is_superuser or request.user.profile.can_operate_shift):
        messages.error(request, "شما مجوز بستن شیفت را ندارید.")
        return redirect("shifts:session_list")

    session = get_object_or_404(ShiftSession, pk=pk)
    if session.status != ShiftSessionStatus.ACTIVE:
        messages.warning(request, "این جلسه در وضعیت فعال نیست.")
        return redirect("shifts:session_detail", pk=session.pk)

    if request.method == "POST":
        form = ShiftSessionCloseForm(request.POST)
        if form.is_valid():
            notes = form.cleaned_data.get("notes", "")
            try:
                ShiftResolutionService.close_session(session, user=request.user, notes=notes)
                messages.success(request, f"جلسه شیفت «{session.shift.name}» با موفقیت بسته شد.")
                return redirect("shifts:session_detail", pk=session.pk)
            except ValidationError as exc:
                messages.error(request, f"خطا در بستن شیفت: {exc}")
    else:
        form = ShiftSessionCloseForm()

    return render(request, "shifts/session_close.html", {
        "form": form,
        "session": session,
        "title": f"بستن رسمی جلسه شیفت {session.shift.name}",
    })


# ---------------------------------------------------------
# Operator Assignment & Attendance Views
# ---------------------------------------------------------

@login_required
def operator_check_in(request, pk):
    """Operator registers self check-in to an active session."""
    session = get_object_or_404(ShiftSession, pk=pk)
    try:
        ShiftResolutionService.check_in_operator(session, request.user, role=ShiftOperatorRole.PRIMARY)
        messages.success(request, f"حضور شما در شیفت «{session.shift.name}» با موفقیت ثبت شد.")
    except ValidationError as exc:
        messages.error(request, f"خطا در ثبت حضور: {exc}")

    return redirect("shifts:session_detail", pk=session.pk)


@login_required
def operator_check_out(request, pk):
    """Operator registers check-out."""
    assignment = get_object_or_404(ShiftOperatorAssignment, pk=pk)
    if assignment.operator != request.user and not (request.user.is_superuser or request.user.profile.can_manage_shifts):
        messages.error(request, "شما مجاز به ثبت خروج برای کاربر دیگری نیستید.")
        return redirect("shifts:session_detail", pk=assignment.session.pk)

    try:
        ShiftResolutionService.check_out_operator(assignment, user=request.user)
        messages.success(request, "خروج شما از شیفت با موفقیت ثبت شد.")
    except ValidationError as exc:
        messages.error(request, f"خطا در ثبت خروج: {exc}")

    return redirect("shifts:session_detail", pk=assignment.session.pk)


@login_required
def operator_assign(request, session_pk):
    """Supervisor assigns an operator to a session."""
    if not (request.user.is_superuser or request.user.profile.can_manage_shifts):
        messages.error(request, "شما مجوز تخصیص پرسنل به شیفت را ندارید.")
        return redirect("shifts:session_list")

    session = get_object_or_404(ShiftSession, pk=session_pk)
    if request.method == "POST":
        form = ShiftOperatorAssignmentForm(request.POST, session=session)
        if form.is_valid():
            assignment = form.save(commit=False)
            assignment.session = session
            try:
                assignment.save()
                messages.success(request, f"اپراتور {assignment.operator.get_full_name() or assignment.operator.username} به شیفت تخصیص یافت.")
                return redirect("shifts:session_detail", pk=session.pk)
            except ValidationError as exc:
                form.add_error(None, exc)
    else:
        form = ShiftOperatorAssignmentForm(session=session)

    return render(request, "shifts/assignment_form.html", {
        "form": form,
        "session": session,
        "title": "تخصیص اپراتور به جلسه شیفت",
    })


@login_required
def operator_substitute(request, assignment_pk):
    """Supervisor-authorized emergency substitution of an operator."""
    if not (request.user.is_superuser or request.user.profile.can_authorize_substitution):
        messages.error(request, "شما مجوز تایید جایگزینی اضطراری اپراتور را ندارید.")
        return redirect("shifts:session_list")

    assignment = get_object_or_404(ShiftOperatorAssignment, pk=assignment_pk)
    session = assignment.session

    if request.method == "POST":
        form = ShiftSubstitutionForm(request.POST, current_operator=assignment.operator)
        if form.is_valid():
            replacement = form.cleaned_data["replacement_operator"]
            reason = form.cleaned_data["substitution_reason"]
            try:
                ShiftResolutionService.substitute_operator(
                    session=session,
                    original_operator=assignment.operator,
                    replacement_operator=replacement,
                    authorized_by=request.user,
                    reason=reason
                )
                messages.success(request, f"جایگزینی اضطراری اپراتور {assignment.operator.username} با {replacement.username} با موفقیت اعمال گردید.")
                return redirect("shifts:session_detail", pk=session.pk)
            except ValidationError as exc:
                form.add_error(None, exc)
    else:
        form = ShiftSubstitutionForm(current_operator=assignment.operator)

    return render(request, "shifts/substitution_form.html", {
        "form": form,
        "session": session,
        "assignment": assignment,
        "title": "تعویض اضطراری اپراتور شیفت (تحت نظارت سرپرست)",
    })


# ---------------------------------------------------------
# Supervisor Exception Visibility Views
# ---------------------------------------------------------

@login_required
def exception_list(request):
    """View unblocked out-of-shift weighings for supervisor review."""
    if not (request.user.is_superuser or request.user.profile.can_manage_shifts):
        messages.error(request, "شما مجوز مشاهده استثنائات شیفت را ندارید.")
        return redirect("dashboard:index")

    filter_ack = request.GET.get("acknowledged", "0")
    qs = ShiftExceptionLog.objects.select_related("ticket", "operator", "acknowledged_by").all().order_by("-timestamp")

    if filter_ack == "0":
        qs = qs.filter(acknowledged_by__isnull=True)
    elif filter_ack == "1":
        qs = qs.filter(acknowledged_by__isnull=False)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "shifts/exception_list.html", {
        "page_obj": page_obj,
        "filter_ack": filter_ack,
        "title": "استثنائات توزین خارج از شیفت (دیده‌بانی سرپرست)",
        "is_shift_management_enabled": ShiftResolutionService.is_shift_management_enabled(),
    })


@login_required
@require_POST
def exception_acknowledge(request, pk):
    """Supervisor marks an exception as acknowledged."""
    if not (request.user.is_superuser or request.user.profile.can_manage_shifts):
        return JsonResponse({"success": False, "error": "دسترسی غیرمجاز"}, status=403)

    exc = get_object_or_404(ShiftExceptionLog, pk=pk)
    form = ShiftExceptionAcknowledgeForm(request.POST)
    if form.is_valid():
        note = form.cleaned_data["acknowledgement_note"]
        exc.acknowledge(user=request.user, note=note)
        # Log administrative action to immutable audit trail
        log_audit(
            user=request.user,
            action=AuditAction.DISCREPANCY_APPROVAL,
            model_name="ShiftExceptionLog",
            record_id=str(exc.pk),
            record_repr=f"استثنای شیفت - قبض {exc.ticket.serial_number} ({exc.get_weighing_phase_display()})",
            old_values={"is_acknowledged": False},
            new_values={
                "is_acknowledged": True,
                "acknowledged_by": request.user.username,
                "acknowledged_at": str(exc.acknowledged_at),
                "acknowledgement_note": note
            },
            reason=note,
            source="Web"
        )
        messages.success(request, f"استثنای قبض شماره {exc.ticket.serial_number} بررسی و تایید شد.")
    else:
        messages.error(request, "ثبت توضیحات بررسی الزامی است.")

    return redirect("shifts:exception_list")


# ---------------------------------------------------------
# Live Current Shift Status API
# ---------------------------------------------------------

@login_required
def current_shift_status(request):
    """JSON API returning current active shift and checked-in operators."""
    if not ShiftResolutionService.is_shift_management_enabled():
        return JsonResponse({
            "is_enabled": False,
            "has_active_shift": False,
            "message": "سیستم مدیریت خودکار شیفت در تنظیمات سامانه غیرفعال است (ENABLE_SHIFT_MANAGEMENT = False)."
        })

    active_session = ShiftResolutionService.get_active_session_for_weighing(operator=request.user)
    if active_session:
        checked_in_ops = list(
            active_session.assignments.filter(status=ShiftAssignmentStatus.CHECKED_IN)
            .values_list("operator__username", flat=True)
        )
        return JsonResponse({
            "is_enabled": True,
            "has_active_shift": True,
            "shift_id": active_session.shift.id,
            "shift_name": active_session.shift.name,
            "shift_code": active_session.shift.code,
            "operational_date": format_jalali_date(active_session.operational_date),
            "scale_zero_ok": active_session.initial_scale_zero_ok,
            "printer_paper_ok": active_session.initial_printer_paper_ok,
            "checked_in_operators": checked_in_ops,
        })
    return JsonResponse({
        "is_enabled": True,
        "has_active_shift": False,
        "message": "هیچ شیفت فعالی در حال حاضر ثبت نشده است."
    })


# ---------------------------------------------------------
# Phase 4.2: Formal Shift Handover Views
# ---------------------------------------------------------

@login_required
def handover_list(request):
    """List of all shift handovers with filtering and pagination."""
    if not (request.user.is_superuser or request.user.profile.can_operate_shift or request.user.profile.can_manage_shifts):
        messages.error(request, "شما مجوز مشاهده تحویل و تحول‌های شیفت را ندارید.")
        return redirect("dashboard:index")

    status_filter = request.GET.get("status", "")
    date_filter = request.GET.get("date", "")
    operator_filter = request.GET.get("operator", "")

    qs = ShiftHandover.objects.select_related(
        "outgoing_session", "outgoing_session__shift",
        "incoming_session", "incoming_session__shift",
        "outgoing_operator", "incoming_operator", "supervisor"
    ).all().order_by("-initiated_at", "-id")

    if status_filter:
        qs = qs.filter(status=status_filter)
    if date_filter:
        g_date = jalali_to_gregorian(date_filter)
        if g_date:
            qs = qs.filter(outgoing_session__operational_date=g_date)
    if operator_filter:
        qs = qs.filter(
            models.Q(outgoing_operator__username__icontains=operator_filter) |
            models.Q(incoming_operator__username__icontains=operator_filter)
        )

    paginator = Paginator(qs, 15)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(request, "shifts/handover_list.html", {
        "page_obj": page_obj,
        "status_filter": status_filter,
        "date_filter": date_filter,
        "operator_filter": operator_filter,
        "statuses": ShiftHandoverStatus.choices,
        "title": "سوابق تحویل و تحول شیفت (Handover Registry)",
    })


@login_required
def handover_initiate(request, session_pk):
    """
    Start or resume a shift handover draft for an active session.
    Provides live preview of snapshot items and checklist declarations.
    """
    session = get_object_or_404(ShiftSession, pk=session_pk)

    if not (request.user.is_superuser or request.user.profile.can_operate_shift):
        messages.error(request, "شما مجوز انجام تحویل و تحول شیفت را ندارید.")
        return redirect("shifts:session_detail", pk=session.pk)

    if session.status != ShiftSessionStatus.ACTIVE:
        messages.error(request, "تنها برای جلسات شیفت فعال امکان ثبت تحویل شیفت وجود دارد.")
        return redirect("shifts:session_detail", pk=session.pk)

    # Check for existing active handover
    existing_handover = ShiftHandoverService.get_active_handover_for_session(session)
    if existing_handover and existing_handover.status != ShiftHandoverStatus.DRAFT:
        messages.info(request, f"تحویل شیفت #{existing_handover.pk} در وضعیت {existing_handover.get_status_display()} در جریان است.")
        return redirect("shifts:handover_detail", pk=existing_handover.pk)

    handover = existing_handover

    if request.method == "POST":
        form = ShiftHandoverInitiateForm(request.POST, current_operator=request.user)
        if form.is_valid():
            incoming_op = form.cleaned_data.get("incoming_operator")
            incoming_sess = form.cleaned_data.get("incoming_session")
            checklist_data = {
                "scale_zero_confirmed": form.cleaned_data.get("scale_zero_confirmed", False),
                "printer_paper_confirmed": form.cleaned_data.get("printer_paper_confirmed", False),
                "workstation_clean_confirmed": form.cleaned_data.get("workstation_clean_confirmed", False),
                "physical_documents_confirmed": form.cleaned_data.get("physical_documents_confirmed", False),
                "checklist_notes": form.cleaned_data.get("checklist_notes", ""),
            }
            outgoing_notes = form.cleaned_data.get("outgoing_notes", "")

            try:
                # Initiate or reuse draft
                handover = ShiftHandoverService.initiate_handover(
                    outgoing_session=session,
                    operator=request.user,
                    incoming_operator=incoming_op,
                    incoming_session=incoming_sess,
                    outgoing_notes=outgoing_notes
                )

                # Save checklist declarations on draft
                handover.scale_zero_confirmed = checklist_data["scale_zero_confirmed"]
                handover.printer_paper_confirmed = checklist_data["printer_paper_confirmed"]
                handover.workstation_clean_confirmed = checklist_data["workstation_clean_confirmed"]
                handover.physical_documents_confirmed = checklist_data["physical_documents_confirmed"]
                handover.checklist_notes = checklist_data["checklist_notes"]
                handover.save()

                # If user clicked "submit" button
                if "submit_handover" in request.POST:
                    ShiftHandoverService.submit_handover(
                        handover=handover,
                        operator=request.user,
                        checklist_data=checklist_data,
                        notes=outgoing_notes
                    )
                    messages.success(request, f"تحویل شیفت #{handover.pk} با موفقیت ارسال و اسنپ‌شات عملیاتی منجمد گردید.")
                    return redirect("shifts:handover_detail", pk=handover.pk)
                else:
                    messages.success(request, "پیش‌نویس تحویل شیفت با موفقیت ذخیره شد.")
                    return redirect("shifts:handover_detail", pk=handover.pk)

            except ValidationError as exc:
                form.add_error(None, exc)
            except PermissionDenied as exc:
                messages.error(request, str(exc))
                return redirect("shifts:session_detail", pk=session.pk)
    else:
        initial_data = {}
        if handover:
            initial_data = {
                "incoming_operator": handover.incoming_operator,
                "incoming_session": handover.incoming_session,
                "scale_zero_confirmed": handover.scale_zero_confirmed,
                "printer_paper_confirmed": handover.printer_paper_confirmed,
                "workstation_clean_confirmed": handover.workstation_clean_confirmed,
                "physical_documents_confirmed": handover.physical_documents_confirmed,
                "checklist_notes": handover.checklist_notes,
                "outgoing_notes": handover.outgoing_notes,
            }
        form = ShiftHandoverInitiateForm(initial=initial_data, current_operator=request.user)

    # Live snapshot preview
    from weighbridge.models import WeighTicket, TicketStatus
    from monitoring.models import DiscrepancyApproval, ApprovalStatus, MonitoringAlert, AlertType, AlertStatus

    yard_tickets = WeighTicket.objects.filter(status=TicketStatus.WAITING_SECOND).select_related("product", "party", "vehicle")
    pending_approvals = DiscrepancyApproval.objects.filter(status=ApprovalStatus.PENDING).select_related("ticket")
    overdue_alerts = MonitoringAlert.objects.filter(alert_type=AlertType.LONG_WAITING_TIME, status=AlertStatus.OPEN).select_related("ticket")
    unresolved_exceptions = ShiftExceptionLog.objects.filter(acknowledged_by__isnull=True).select_related("ticket", "operator")

    return render(request, "shifts/handover_form.html", {
        "form": form,
        "session": session,
        "handover": handover,
        "yard_tickets": yard_tickets,
        "pending_approvals": pending_approvals,
        "overdue_alerts": overdue_alerts,
        "unresolved_exceptions": unresolved_exceptions,
        "title": f"تحویل و تحول شیفت - {session.shift.name}",
    })


@login_required
def handover_detail(request, pk):
    """
    Detailed audit view of a shift handover, its operational snapshot items,
    checklist declarations, notes, and transition controls.
    """
    handover = get_object_or_404(
        ShiftHandover.objects.select_related(
            "outgoing_session", "outgoing_session__shift",
            "incoming_session", "incoming_session__shift",
            "outgoing_operator", "outgoing_operator__profile",
            "incoming_operator", "incoming_operator__profile",
            "supervisor", "supervisor__profile"
        ),
        pk=pk
    )

    items = handover.items.select_related("ticket", "discrepancy_approval", "monitoring_alert", "shift_exception").all()

    # Categorize items for clean visual presentation
    yard_items = [it for it in items if it.category == ShiftHandoverItemCategory.YARD_VEHICLE]
    waiting_items = [it for it in items if it.category == ShiftHandoverItemCategory.WAITING_SECOND]
    approval_items = [it for it in items if it.category == ShiftHandoverItemCategory.PENDING_APPROVAL]
    alert_items = [it for it in items if it.category == ShiftHandoverItemCategory.OVERDUE_ALERT]
    exception_items = [it for it in items if it.category == ShiftHandoverItemCategory.SHIFT_EXCEPTION]

    is_supervisor = request.user.is_superuser or (hasattr(request.user, "profile") and request.user.profile.can_manage_shifts)
    is_outgoing = (request.user == handover.outgoing_operator)
    is_incoming = (request.user == handover.incoming_operator) or (handover.incoming_operator is None and not is_outgoing)

    # Forms for actions
    accept_form = ShiftHandoverAcceptForm()
    dispute_form = ShiftHandoverDisputeForm()
    resolve_form = ShiftHandoverResolveForm()

    return render(request, "shifts/handover_detail.html", {
        "handover": handover,
        "yard_items": yard_items,
        "waiting_items": waiting_items,
        "approval_items": approval_items,
        "alert_items": alert_items,
        "exception_items": exception_items,
        "is_supervisor": is_supervisor,
        "is_outgoing": is_outgoing,
        "is_incoming": is_incoming,
        "accept_form": accept_form,
        "dispute_form": dispute_form,
        "resolve_form": resolve_form,
        "title": f"جزئیات تحویل شیفت #{handover.pk}",
    })


@login_required
@require_POST
def handover_submit(request, pk):
    """Submit a draft handover, freezing the operational snapshot."""
    handover = get_object_or_404(ShiftHandover, pk=pk)
    try:
        ShiftHandoverService.submit_handover(
            handover=handover,
            operator=request.user,
            notes=request.POST.get("outgoing_notes", "")
        )
        messages.success(request, f"تحویل شیفت #{handover.pk} با موفقیت ارسال شد.")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, f"خطا در ارسال تحویل شیفت: {exc}")

    return redirect("shifts:handover_detail", pk=handover.pk)


@login_required
@require_POST
def handover_accept(request, pk):
    """Incoming operator formally accepts shift responsibility."""
    handover = get_object_or_404(ShiftHandover, pk=pk)
    form = ShiftHandoverAcceptForm(request.POST)
    if form.is_valid():
        notes = form.cleaned_data.get("incoming_notes", "")
        try:
            ShiftHandoverService.accept_handover(
                handover=handover,
                operator=request.user,
                notes=notes
            )
            messages.success(request, "مسئولیت شیفت با موفقیت توسط شما (اپراتور تحویل‌گیرنده) پذیرفته شد.")
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, f"خطا در پذیرش تحویل شیفت: {exc}")
    else:
        messages.error(request, "داده‌های فرم پذیرش نامعتبر است.")

    return redirect("shifts:handover_detail", pk=handover.pk)


@login_required
@require_POST
def handover_dispute(request, pk):
    """Incoming operator records an operational discrepancy/dispute."""
    handover = get_object_or_404(ShiftHandover, pk=pk)
    form = ShiftHandoverDisputeForm(request.POST)
    if form.is_valid():
        reason = form.cleaned_data.get("dispute_reason", "")
        notes = form.cleaned_data.get("incoming_notes", "")
        try:
            ShiftHandoverService.dispute_handover(
                handover=handover,
                operator=request.user,
                dispute_reason=reason,
                notes=notes
            )
            messages.warning(request, f"مغایرت تحویل شیفت #{handover.pk} ثبت گردید و جهت تصمیم‌گیری به سرپرست ارجاع شد.")
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, f"خطا در ثبت مغایرت: {exc}")
    else:
        messages.error(request, "شرح دقیق علت مغایرت الزامی است (حداقل ۵ کاراکتر).")

    return redirect("shifts:handover_detail", pk=handover.pk)


@login_required
def handover_resolve(request, pk):
    """Supervisor intervenes to resolve or cancel a disputed handover."""
    handover = get_object_or_404(ShiftHandover, pk=pk)

    if not (request.user.is_superuser or request.user.profile.can_manage_shifts):
        messages.error(request, "تنها سرپرست یا مدیر سیستم مجاز به حل‌وفصل مغایرت‌های تحویل شیفت است.")
        return redirect("shifts:handover_detail", pk=handover.pk)

    if request.method == "POST":
        form = ShiftHandoverResolveForm(request.POST)
        if form.is_valid():
            action = form.cleaned_data.get("action")
            resolution_notes = form.cleaned_data.get("resolution_notes")
            try:
                ShiftHandoverService.resolve_dispute(
                    handover=handover,
                    supervisor=request.user,
                    resolution_notes=resolution_notes,
                    action=action
                )
                action_text = "حل‌وفصل و تایید" if action == "RESOLVE" else "لغو"
                messages.success(request, f"تصمیم سرپرست مبنی بر {action_text} تحویل شیفت #{handover.pk} با موفقیت ثبت شد.")
                return redirect("shifts:handover_detail", pk=handover.pk)
            except (ValidationError, PermissionDenied) as exc:
                form.add_error(None, exc)
    else:
        form = ShiftHandoverResolveForm()

    return render(request, "shifts/handover_resolve.html", {
        "form": form,
        "handover": handover,
        "title": f"تصمیم‌گیری سرپرست در خصوص تحویل شیفت #{handover.pk}",
    })


@login_required
@require_POST
def handover_cancel(request, pk):
    """Cancel a draft or submitted handover."""
    handover = get_object_or_404(ShiftHandover, pk=pk)
    reason = request.POST.get("reason", "")
    try:
        ShiftHandoverService.cancel_handover(handover, user=request.user, reason=reason)
        messages.success(request, f"تحویل شیفت #{handover.pk} با موفقیت لغو شد.")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, f"خطا در لغو تحویل شیفت: {exc}")

    return redirect("shifts:handover_detail", pk=handover.pk)
