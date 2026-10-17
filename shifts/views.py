from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib import messages
from django.utils import timezone
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from core.jalali import format_jalali_date, format_jalali_datetime, get_today_jalali, jalali_to_gregorian
from shifts.models import (
    WorkShift, ShiftSession, ShiftSessionStatus,
    ShiftOperatorAssignment, ShiftOperatorRole, ShiftAssignmentStatus,
    ShiftExceptionLog
)
from shifts.forms import (
    WorkShiftForm, ShiftSessionOpenForm, ShiftSessionCloseForm,
    ShiftOperatorAssignmentForm, ShiftSubstitutionForm, ShiftExceptionAcknowledgeForm
)
from shifts.services import ShiftResolutionService


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

    return render(request, "shifts/session_detail.html", {
        "session": session,
        "assignments": assignments,
        "first_tickets_count": first_tickets_count,
        "second_tickets_count": second_tickets_count,
        "is_checked_in": is_checked_in,
        "my_assignment": my_assignment,
        "can_manage": can_manage,
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
    active_session = ShiftResolutionService.get_active_session_for_weighing(operator=request.user)
    if active_session:
        checked_in_ops = list(
            active_session.assignments.filter(status=ShiftAssignmentStatus.CHECKED_IN)
            .values_list("operator__username", flat=True)
        )
        return JsonResponse({
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
        "has_active_shift": False,
        "message": "هیچ شیفت فعالی در حال حاضر ثبت نشده است."
    })
