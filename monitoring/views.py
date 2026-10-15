import json
from decimal import Decimal
from datetime import datetime, date, timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Count, Sum, Avg, Max
from django.utils import timezone
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST

from accounts.decorators import (
    role_required, manager_or_admin_required, admin_only_required,
    monitoring_role_required, discrepancy_approver_required
)
from core.jalali import (
    get_today_gregorian, get_today_jalali, format_jalali_date, jalali_to_gregorian
)
from core.models import SystemSetting
from weighbridge.models import WeighTicket, TicketStatus
from masterdata.models import Product, Party, Vehicle, Driver
from audit.services import log_audit
from audit.models import AuditAction
from django.core.exceptions import ValidationError, PermissionDenied

from monitoring.models import (
    MonitoringAlert, MonitoringRuleConfig, AlertType, AlertSeverity,
    AlertStatus, AlertConfidence, ApprovalStatus, DiscrepancyApproval
)
from monitoring.forms import (
    MonitoringRuleConfigForm, AlertResolveForm, AlertFilterForm,
    DiscrepancyApprovalRequestForm, DiscrepancyApprovalDecisionForm, DiscrepancyFilterForm
)
from monitoring.exports import export_monitoring_excel, export_monitoring_csv
from monitoring.selectors.monitoring_queries import (
    get_vehicle_tare_stats, get_party_discrepancy_stats, get_loss_stats,
    get_net_weight_stats, get_waiting_time_stats, get_ticket_risk_score
)
from monitoring.services.anomaly_engine import AnomalyDetectionEngine
from monitoring.services.discrepancy_service import DiscrepancyApprovalService


@login_required
@monitoring_role_required
def monitoring_dashboard(request):
    """
    Main Monitoring & Anomaly Detection Center Dashboard.
    """
    today_g = get_today_gregorian()
    
    # Today's tickets
    today_tickets = WeighTicket.objects.filter(
        Q(first_weight_date=today_g) | Q(created_at__date=today_g)
    )
    today_count = today_tickets.count()

    # Alerts related to today's tickets
    today_alerts = MonitoringAlert.objects.filter(
        Q(ticket__in=today_tickets) | Q(created_at__date=today_g)
    )
    
    # Tickets with alerts today
    tickets_with_alerts_ids = today_alerts.values_list("ticket_id", flat=True).distinct()
    tickets_with_alerts_count = len(tickets_with_alerts_ids)
    normal_services_count = max(0, today_count - tickets_with_alerts_count)

    # High risk & critical tickets today
    critical_alerts_count = today_alerts.filter(severity=AlertSeverity.CRITICAL).count()
    high_alerts_count = today_alerts.filter(severity=AlertSeverity.HIGH).count()

    # System-wide alert status counts
    open_alerts_count = MonitoringAlert.objects.filter(status=AlertStatus.OPEN).count()
    reviewed_alerts_count = MonitoringAlert.objects.filter(status=AlertStatus.REVIEWED).count()
    resolved_alerts_count = MonitoringAlert.objects.filter(status=AlertStatus.RESOLVED).count()

    # Breakdown by alert type (All-time or active)
    type_breakdown = []
    for at_code, at_label in AlertType.choices:
        cnt = MonitoringAlert.objects.filter(alert_type=at_code, status__in=[AlertStatus.OPEN, AlertStatus.REVIEWED]).count()
        type_breakdown.append({
            "code": at_code,
            "label": at_label,
            "count": cnt,
        })

    # Recent 10 alerts
    recent_alerts = MonitoringAlert.objects.select_related(
        "ticket", "ticket__product", "ticket__party", "ticket__vehicle", "ticket__driver"
    ).order_by("-id")[:10]

    # Calculate risk scores for recent tickets
    recent_alerts_with_risk = []
    for a in recent_alerts:
        risk_score, risk_level = get_ticket_risk_score(a.ticket_id)
        recent_alerts_with_risk.append({
            "alert": a,
            "risk_score": risk_score,
            "risk_level": risk_level,
        })

    return render(request, "monitoring/dashboard.html", {
        "title": "مرکز پایش هوشمند و کشف ناهنجاری‌ها",
        "today_jalali": get_today_jalali(),
        "today_count": today_count,
        "normal_services_count": normal_services_count,
        "tickets_with_alerts_count": tickets_with_alerts_count,
        "critical_alerts_count": critical_alerts_count,
        "high_alerts_count": high_alerts_count,
        "open_alerts_count": open_alerts_count,
        "reviewed_alerts_count": reviewed_alerts_count,
        "resolved_alerts_count": resolved_alerts_count,
        "type_breakdown": type_breakdown,
        "recent_alerts": recent_alerts_with_risk,
    })


@login_required
@monitoring_role_required
def alert_list(request):
    """
    Comprehensive Alert Center table view with multi-field filtering and pagination.
    """
    qs = MonitoringAlert.objects.select_related(
        "ticket", "ticket__product", "ticket__party", "ticket__vehicle", "ticket__driver"
    ).all().order_by("-id")

    filter_form = AlertFilterForm(request.GET)
    
    # Filter by search query
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(ticket__serial_number__icontains=q) |
            Q(ticket__license_plate_display__icontains=q) |
            Q(ticket__driver__full_name__icontains=q) |
            Q(ticket__driver_name_custom__icontains=q) |
            Q(ticket__party__name__icontains=q) |
            Q(ticket__product__name__icontains=q) |
            Q(title__icontains=q) |
            Q(reason__icontains=q)
        )

    # Filter by alert type
    alert_type = request.GET.get("alert_type", "").strip()
    if alert_type:
        qs = qs.filter(alert_type=alert_type)

    # Filter by severity
    severity = request.GET.get("severity", "").strip()
    if severity:
        qs = qs.filter(severity=severity)

    # Filter by status
    status = request.GET.get("status", "").strip()
    if status and status != "all":
        qs = qs.filter(status=status)
    elif not status:
        # Default to open and reviewed alerts if no status specified
        # qs = qs.filter(status__in=[AlertStatus.OPEN, AlertStatus.REVIEWED])
        pass

    # Filter by product & party
    product_id = request.GET.get("product")
    if product_id:
        qs = qs.filter(ticket__product_id=product_id)

    party_id = request.GET.get("party")
    if party_id:
        qs = qs.filter(ticket__party_id=party_id)

    # Date filters
    start_date_j = request.GET.get("start_date")
    if start_date_j:
        g_start = jalali_to_gregorian(start_date_j)
        if g_start:
            qs = qs.filter(created_at__date__gte=g_start)

    end_date_j = request.GET.get("end_date")
    if end_date_j:
        g_end = jalali_to_gregorian(end_date_j)
        if g_end:
            qs = qs.filter(created_at__date__lte=g_end)

    # Exports
    export_format = request.GET.get("export")
    if export_format == "excel":
        return export_monitoring_excel(qs)
    elif export_format == "csv":
        return export_monitoring_csv(qs)

    settings_obj = SystemSetting.get_settings()
    per_page = int(request.GET.get("per_page", settings_obj.items_per_page or 20))
    paginator = Paginator(qs, per_page)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Attach risk score to items on page
    alerts_with_risk = []
    for a in page_obj:
        risk_score, risk_level = get_ticket_risk_score(a.ticket_id)
        alerts_with_risk.append({
            "alert": a,
            "risk_score": risk_score,
            "risk_level": risk_level,
        })

    # Submenu active type title helper
    current_type_title = "همه هشدارها"
    if alert_type:
        for c, label in AlertType.choices:
            if c == alert_type:
                current_type_title = label
                break

    return render(request, "monitoring/alert_list.html", {
        "title": f"مرکز هشدارها - {current_type_title}",
        "page_obj": page_obj,
        "alerts_with_risk": alerts_with_risk,
        "total_count": paginator.count,
        "filter_form": filter_form,
        "active_alert_type": alert_type,
        "active_status": status,
        "active_severity": severity,
    })


@login_required
@monitoring_role_required
def alert_detail(request, pk):
    """
    Detailed explainable view for a single alert, including baseline statistics,
    historical comparison table, and resolve/review action form.
    """
    alert = get_object_or_404(
        MonitoringAlert.objects.select_related(
            "ticket", "ticket__product", "ticket__party", "ticket__vehicle",
            "ticket__driver", "ticket__first_weight_operator", "ticket__second_weight_operator",
            "resolved_by"
        ),
        pk=pk
    )

    ticket = alert.ticket
    risk_score, risk_level = get_ticket_risk_score(ticket.id)

    # Fetch recent historical records based on alert type for comparison
    recent_history = []
    if alert.alert_type == AlertType.VEHICLE_TARE_ANOMALY:
        stats = get_vehicle_tare_stats(vehicle_id=ticket.vehicle_id, plate=ticket.license_plate_display, exclude_ticket_id=ticket.id)
        recent_history = stats.get("recent_records", [])
    elif alert.alert_type == AlertType.WEIGHT_DISCREPANCY:
        stats = get_party_discrepancy_stats(party_id=ticket.party_id, exclude_ticket_id=ticket.id)
        recent_history = stats.get("recent_records", [])
    elif alert.alert_type == AlertType.LOSS_ANOMALY:
        stats = get_loss_stats(product_id=ticket.product_id, party_id=ticket.party_id, exclude_ticket_id=ticket.id)
        recent_history = stats.get("recent_records", [])
    elif alert.alert_type == AlertType.NET_WEIGHT_ANOMALY:
        stats = get_net_weight_stats(vehicle_id=ticket.vehicle_id, plate=ticket.license_plate_display, product_id=ticket.product_id, exclude_ticket_id=ticket.id)
        recent_history = stats.get("recent_records", [])

    resolve_form = AlertResolveForm(initial={"action_type": AlertStatus.RESOLVED})

    return render(request, "monitoring/alert_detail.html", {
        "title": f"جزئیات هشدار: {alert.title}",
        "alert": alert,
        "ticket": ticket,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "recent_history": recent_history,
        "resolve_form": resolve_form,
    })


@login_required
@monitoring_role_required
@require_POST
def resolve_alert(request, pk):
    """
    POST endpoint to resolve, review, or ignore an alert with mandatory resolution notes.
    """
    alert = get_object_or_404(MonitoringAlert, pk=pk)

    form = AlertResolveForm(request.POST)
    if form.is_valid():
        action_type = form.cleaned_data["action_type"]
        note = form.cleaned_data["resolution_note"]

        old_status = alert.status
        alert.status = action_type
        alert.resolved_by = request.user
        alert.resolved_at = timezone.now()
        alert.resolution_note = note
        alert.save()

        # Audit Log entry
        log_audit(
            action=AuditAction.STATUS_CHANGE,
            model_name="MonitoringAlert",
            record_id=alert.id,
            record_repr=f"هشدار {alert.get_alert_type_display()} (قبض {alert.ticket.serial_number})",
            old_values={"status": old_status},
            new_values={"status": alert.status, "resolution_note": note},
            reason=f"اقدام کاربر روی هشدار: {note}",
            user=request.user
        )

        messages.success(request, f"وضعیت هشدار با موفقیت به «{alert.get_status_display()}» تغییر یافت.")
        return redirect("monitoring:alert_detail", pk=alert.id)
    else:
        for err_list in form.errors.values():
            for err in err_list:
                messages.error(request, err)
        return redirect("monitoring:alert_detail", pk=alert.id)


@login_required
@admin_only_required
def monitoring_settings(request):
    """
    Configuration view for monitoring rules and thresholds.
    """
    configs = []
    for alert_type, _ in AlertType.choices:
        cfg = MonitoringRuleConfig.get_rule_config(alert_type)
        configs.append(cfg)

    if request.method == "POST":
        rule_type = request.POST.get("rule_type")
        cfg = get_object_or_404(MonitoringRuleConfig, rule_type=rule_type)
        form = MonitoringRuleConfigForm(request.POST, instance=cfg)
        if form.is_valid():
            updated_cfg = form.save(commit=False)
            updated_cfg.updated_by = request.user
            updated_cfg.save()

            log_audit(
                action=AuditAction.UPDATE,
                model_name="MonitoringRuleConfig",
                record_id=updated_cfg.id,
                record_repr=f"تنظیمات قانون {updated_cfg.name_fa}",
                new_values={
                    "enabled": updated_cfg.enabled,
                    "requires_approval": updated_cfg.requires_approval,
                    "warning_threshold": float(updated_cfg.warning_threshold),
                    "high_threshold": float(updated_cfg.high_threshold),
                    "critical_threshold": float(updated_cfg.critical_threshold),
                },
                reason="ویرایش تنظیمات پایش هوشمند توسط مدیر",
                user=request.user
            )

            messages.success(request, f"تنظیمات قانون «{updated_cfg.name_fa}» با موفقیت ذخیره شد.")
            return redirect("monitoring:settings")
        else:
            messages.error(request, "خطا در اعتبارسنجی مقادیر فرم تنظیمات.")

    return render(request, "monitoring/settings.html", {
        "title": "تنظیمات قوانین پایش هوشمند و آستانه‌های تشخیص",
        "configs": configs,
    })


@login_required
@monitoring_role_required
def monitoring_reports(request):
    """
    Analytical monitoring report including Summary by Type/Severity/Party/Product
    and Top 10 Anomalies (Vehicles, Parties, Products, Tickets).
    """
    # 1. Total Alert Metrics
    total_alerts = MonitoringAlert.objects.count()
    open_alerts = MonitoringAlert.objects.filter(status__in=[AlertStatus.OPEN, AlertStatus.REVIEWED]).count()

    # 2. Alerts by Type
    type_counts = MonitoringAlert.objects.values("alert_type").annotate(cnt=Count("id")).order_by("-cnt")
    type_summary = []
    for row in type_counts:
        type_summary.append({
            "type_code": row["alert_type"],
            "type_name": dict(AlertType.choices).get(row["alert_type"], row["alert_type"]),
            "count": row["cnt"],
        })

    # 3. Alerts by Severity
    sev_counts = MonitoringAlert.objects.values("severity").annotate(cnt=Count("id")).order_by("-cnt")
    sev_summary = []
    for row in sev_counts:
        sev_summary.append({
            "severity_code": row["severity"],
            "severity_name": dict(AlertSeverity.choices).get(row["severity"], row["severity"]),
            "count": row["cnt"],
        })

    # 4. Top 10 Vehicles with most alerts
    top_vehicles = MonitoringAlert.objects.filter(
        ticket__vehicle__isnull=False
    ).values("ticket__vehicle__plate_display", "ticket__vehicle__id").annotate(
        alert_count=Count("id")
    ).order_by("-alert_count")[:10]

    # 5. Top 10 Parties with highest discrepancies
    top_discrepancy_parties = MonitoringAlert.objects.filter(
        alert_type=AlertType.WEIGHT_DISCREPANCY,
        ticket__party__isnull=False
    ).values("ticket__party__name", "ticket__party__id").annotate(
        discrepancy_count=Count("id"),
        avg_deviation=Avg("deviation_value")
    ).order_by("-discrepancy_count")[:10]

    # 6. Top 10 Products with abnormal loss
    top_loss_products = MonitoringAlert.objects.filter(
        alert_type=AlertType.LOSS_ANOMALY,
        ticket__product__isnull=False
    ).values("ticket__product__name", "ticket__product__id").annotate(
        loss_alert_count=Count("id"),
        avg_loss=Avg("current_value")
    ).order_by("-loss_alert_count")[:10]

    # 7. Top 10 Tickets with highest risk score
    # Query open alerts grouped by ticket
    tickets_with_alerts = WeighTicket.objects.filter(
        monitoring_alerts__status__in=[AlertStatus.OPEN, AlertStatus.REVIEWED]
    ).distinct().select_related("product", "party", "vehicle", "driver")[:50]

    ticket_risk_list = []
    for t in tickets_with_alerts:
        r_score, r_level = get_ticket_risk_score(t.id)
        if r_score > 0:
            ticket_risk_list.append({
                "ticket": t,
                "risk_score": r_score,
                "risk_level": r_level,
                "alert_count": t.monitoring_alerts.count(),
            })

    ticket_risk_list.sort(key=lambda x: x["risk_score"], reverse=True)
    top_10_risk_tickets = ticket_risk_list[:10]

    # 8. Discrepancy Approval Workflow Statistics (Phase 3.1)
    total_approvals = DiscrepancyApproval.objects.count()
    pending_approvals = DiscrepancyApproval.objects.filter(status=ApprovalStatus.PENDING).count()
    approved_approvals = DiscrepancyApproval.objects.filter(status=ApprovalStatus.APPROVED).count()
    rejected_approvals = DiscrepancyApproval.objects.filter(status=ApprovalStatus.REJECTED).count()

    approval_type_summary = []
    for row in DiscrepancyApproval.objects.values("discrepancy_type").annotate(cnt=Count("id")).order_by("-cnt"):
        approval_type_summary.append({
            "type_code": row["discrepancy_type"],
            "type_name": dict(AlertType.choices).get(row["discrepancy_type"], row["discrepancy_type"]),
            "count": row["cnt"],
        })

    return render(request, "monitoring/reports.html", {
        "title": "گزارشات تحلیلی و آماری پایش هوشمند",
        "total_alerts": total_alerts,
        "open_alerts": open_alerts,
        "type_summary": type_summary,
        "sev_summary": sev_summary,
        "top_vehicles": top_vehicles,
        "top_discrepancy_parties": top_discrepancy_parties,
        "top_loss_products": top_loss_products,
        "top_10_risk_tickets": top_10_risk_tickets,
        "total_approvals": total_approvals,
        "pending_approvals": pending_approvals,
        "approved_approvals": approved_approvals,
        "rejected_approvals": rejected_approvals,
        "approval_type_summary": approval_type_summary,
        "today_jalali": get_today_jalali(),
    })


@login_required
@discrepancy_approver_required
def approval_list(request):
    """
    Supervisor Approval Dashboard (Phase 3.1).
    Displays pending, approved, and rejected discrepancy requests with filters,
    turnaround metrics, inline approve/reject actions, and separation of duties validation.
    """
    form = DiscrepancyFilterForm(request.GET)
    qs = DiscrepancyApproval.objects.select_related(
        "ticket", "ticket__product", "ticket__party", "ticket__vehicle",
        "ticket__driver", "requested_by", "reviewed_by"
    ).order_by("-id")

    status_filter = request.GET.get("status")
    type_filter = request.GET.get("discrepancy_type")
    product_filter = request.GET.get("product")
    search_query = request.GET.get("search", "").strip()

    if status_filter:
        qs = qs.filter(status=status_filter)
    if type_filter:
        qs = qs.filter(discrepancy_type=type_filter)
    if product_filter:
        qs = qs.filter(ticket__product_id=product_filter)
    if search_query:
        qs = qs.filter(
            Q(ticket__serial_number__icontains=search_query) |
            Q(ticket__license_plate_display__icontains=search_query) |
            Q(ticket__normalized_plate__icontains=search_query) |
            Q(ticket__driver_name_custom__icontains=search_query) |
            Q(ticket__driver__full_name__icontains=search_query)
        )

    # Metrics Summary
    total_requests = DiscrepancyApproval.objects.count()
    pending_count = DiscrepancyApproval.objects.filter(status=ApprovalStatus.PENDING).count()
    approved_count = DiscrepancyApproval.objects.filter(status=ApprovalStatus.APPROVED).count()
    rejected_count = DiscrepancyApproval.objects.filter(status=ApprovalStatus.REJECTED).count()

    paginator = Paginator(qs, 20)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    return render(request, "monitoring/approval_list.html", {
        "title": "کارتابل بررسی و مجوزهای مغایرت سرپرست",
        "page_obj": page_obj,
        "form": form,
        "total_requests": total_requests,
        "pending_count": pending_count,
        "approved_count": approved_count,
        "rejected_count": rejected_count,
        "today_jalali": get_today_jalali(),
    })


@login_required
@discrepancy_approver_required
@require_POST
def approval_decision(request, pk):
    """
    POST endpoint for supervisor to approve or reject a discrepancy approval request.
    Enforces separation of duties and concurrency row-locking.
    """
    decision = request.POST.get("decision", "").strip()
    reason = request.POST.get("decision_reason", "").strip()
    redirect_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or "monitoring:approval_list"

    try:
        approval = DiscrepancyApprovalService.decide_approval(
            approval_id=pk,
            supervisor_user=request.user,
            decision=decision,
            decision_reason=reason
        )
        if decision == "approve":
            messages.success(request, f"مجوز مغایرت قبض {approval.ticket.serial_number} با موفقیت صادر و تأیید شد.")
        else:
            messages.warning(request, f"درخواست مجوز قبض {approval.ticket.serial_number} توسط سرپرست رد شد.")
    except (ValidationError, PermissionDenied) as e:
        messages.error(request, f"خطا در ثبت تصمیم سرپرست: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error in approval_decision {pk}: {e}")
        messages.error(request, "خطای سیستمی رخ داد؛ لطفاً مجدداً تلاش نمایید.")

    return redirect(redirect_url)


@login_required
@require_POST
def ticket_request_approval(request, pk):
    """
    POST endpoint for operators to request supervisor approval for a ticket with discrepancies.
    """
    ticket = get_object_or_404(WeighTicket, pk=pk)
    reason = request.POST.get("request_reason", "").strip()
    discrepancy_type = request.POST.get("discrepancy_type", AlertType.WEIGHT_DISCREPANCY)
    redirect_url = request.POST.get("next") or "weighbridge:ticket_second_weight"

    try:
        approval = DiscrepancyApprovalService.request_approval(
            ticket=ticket,
            user=request.user,
            reason=reason,
            discrepancy_type=discrepancy_type,
            gross=ticket.gross_weight,
            tare=ticket.tare_weight,
            net=ticket.net_weight,
        )
        messages.success(request, f"درخواست تأیید مغایرت برای قبض {ticket.serial_number} با موفقیت ثبت شد و در کارتابل سرپرست قرار گرفت.")
    except ValidationError as e:
        messages.error(request, f"امکان ثبت درخواست وجود ندارد: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error in ticket_request_approval for ticket {pk}: {e}")
        messages.error(request, "خطای سیستمی در ثبت درخواست تأیید رخ داد.")

    return redirect(redirect_url, pk=ticket.pk)

