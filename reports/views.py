from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, Http404
from django.core.paginator import Paginator

from weighbridge.models import WeighTicket, TicketStatus
from masterdata.models import (
    Product, Party, Driver, Vehicle, Location, 
    UnloadLocation, OperationType, LossType
)
from reports.services import ReportService
from reports.preset_reports import PRESET_REPORTS, get_preset_report_by_code, get_preset_report_by_id
from reports.exports import export_excel, export_csv
from core.jalali import get_today_jalali, get_jalali_range_gregorian, format_jalali_date
from accounts.decorators import role_required
from django.contrib.auth.models import User
from django.urls import reverse
from django.core.exceptions import ValidationError
from reports.forms import FreightReportForm
from reports.services import FreightReportService
from reports.exports import export_freight_report


@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager", "report_manager", "viewer", "weighbridge_operator", "financial_manager", "ceo", "factory_manager", "commercial_manager")
def freight_report(request):
    form = FreightReportForm(request.GET)
    valid = form.is_valid()
    qs = FreightReportService.filter_tickets(form.cleaned_data) if valid else WeighTicket.objects.none()
    summaries = FreightReportService.summarize(qs)
    export_format = request.GET.get("export")
    if valid and export_format in ("excel", "csv"):
        return export_freight_report(qs, summaries, export_format)
    params = request.GET.copy()
    params.pop("page", None)
    params.pop("export", None)
    page_obj = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "reports/freight_report.html", {
        "title": "گزارش مبالغ کرایه", "form": form, "summaries": summaries,
        "page_obj": page_obj, "params": params,
    })

@login_required
@role_required("super_admin", "system_admin", "weighbridge_manager", "report_manager", "viewer", "weighbridge_operator")
def report_builder(request):
    """
    Dynamic Advanced Report Builder view.
    Executes multi-criteria queries, summary metrics, and optional group-by.
    """
    params = request.GET.copy()
    
    # Check if export requested
    export_format = request.GET.get("export")
    
    try:
        qs = ReportService.filter_tickets(params)
    except ValidationError as exc:
        messages.error(request, "خطا در فیلتر گزارش: " + " ".join(exc.messages))
        qs = WeighTicket.objects.none()
        export_format = None
    summaries = ReportService.get_summary_metrics(qs)
    
    group_by = request.GET.get("group_by", "none")
    group_data = []
    if group_by and group_by != "none":
        group_data = ReportService.group_by_field(qs, group_by)

    # Export handling
    if export_format == "excel":
        return export_excel(qs, summaries, title="گزارش جامع باسکول")
    elif export_format == "csv":
        return export_csv(qs, title="گزارش جامع باسکول")
    elif export_format == "print":
        return render(request, "reports/print_report.html", {
            "tickets": qs,
            "summaries": summaries,
            "group_data": group_data,
            "group_by": group_by,
            "title": "گزارش جامع باسکول",
            "today_jalali": get_today_jalali(),
        })

    # Pagination for table view
    try:
        per_page = min(500, max(1, int(request.GET.get("per_page", 25))))
    except (TypeError, ValueError):
        per_page = 25
    paginator = Paginator(qs, per_page)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    params.pop("page", None)
    params.pop("export", None)

    # Filter dropdown data
    products = Product.objects.filter(is_active=True)
    parties = Party.objects.filter(is_active=True)
    drivers = Driver.objects.filter(is_active=True)
    vehicles = Vehicle.objects.filter(is_active=True)
    locations = Location.objects.filter(is_active=True)
    unload_locations = UnloadLocation.objects.filter(is_active=True)
    operation_types = OperationType.objects.filter(is_active=True)
    loss_types = LossType.objects.filter(is_active=True)
    operators = User.objects.filter(is_active=True)

    return render(request, "reports/report_builder.html", {
        "page_obj": page_obj,
        "summaries": summaries,
        "group_data": group_data,
        "group_by": group_by,
        "total_count": paginator.count,
        "products": products,
        "parties": parties,
        "drivers": drivers,
        "vehicles": vehicles,
        "locations": locations,
        "unload_locations": unload_locations,
        "operation_types": operation_types,
        "loss_types": loss_types,
        "operators": operators,
        "params": params,
        "title": "گزارش‌ساز پیشرفته باسکول",
    })


@login_required
def preset_reports_list(request):
    """
    Directory of 30 Preset Reports categorized cleanly.
    """
    categories = {}
    for r in PRESET_REPORTS:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(r)

    return render(request, "reports/preset_reports.html", {
        "categories": categories,
        "total_preset_count": len(PRESET_REPORTS),
        "title": "گزارش‌های از پیش‌تعریف‌شده (۳۰ گزارش تخصصی)",
    })


@login_required
def preset_report_view(request, code):
    """
    Execute a specific preset report.
    """
    report_meta = get_preset_report_by_code(code)
    if not report_meta:
        raise Http404("گزارش یافت نشد.")

    if code != report_meta["code"]:
        url = reverse("reports:preset_report_view", args=[report_meta["code"]])
        query = request.GET.urlencode()
        return redirect(f"{url}?{query}" if query else url)

    # Combine preset defaults with request GET params
    combined_params = request.GET.copy()
    for k, v in report_meta.get("default_params", {}).items():
        if k not in combined_params or not combined_params[k]:
            combined_params[k] = v

    # Handle preset period if specified
    period = combined_params.get("period")
    if period and not combined_params.get("start_date") and not combined_params.get("end_date"):
        g_start, g_end = get_jalali_range_gregorian(period)
        combined_params["start_date"] = format_jalali_date(g_start)
        combined_params["end_date"] = format_jalali_date(g_end)

    filter_error = False
    try:
        qs = ReportService.filter_tickets(combined_params)
    except ValidationError as exc:
        messages.error(request, "خطا در فیلتر گزارش: " + " ".join(exc.messages))
        qs = WeighTicket.objects.none()
        filter_error = True
    summaries = ReportService.get_summary_metrics(qs)

    group_by = combined_params.get("group_by", "none")
    group_data = []
    if group_by and group_by != "none":
        group_data = ReportService.group_by_field(qs, group_by)

    # Export handling
    export_format = None if filter_error else request.GET.get("export")
    if export_format == "excel":
        return export_excel(qs, summaries, title=report_meta["title"])
    elif export_format == "csv":
        return export_csv(qs, title=report_meta["title"])
    elif export_format == "print":
        return render(request, "reports/print_report.html", {
            "tickets": qs,
            "summaries": summaries,
            "group_data": group_data,
            "group_by": group_by,
            "title": report_meta["title"],
            "today_jalali": get_today_jalali(),
        })

    # Pagination
    paginator = Paginator(qs, 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    combined_params.pop("page", None)
    combined_params.pop("export", None)

    return render(request, "reports/preset_report_detail.html", {
        "report_meta": report_meta,
        "page_obj": page_obj,
        "summaries": summaries,
        "group_data": group_data,
        "group_by": group_by,
        "total_count": paginator.count,
        "params": combined_params,
        "title": report_meta["title"],
    })
