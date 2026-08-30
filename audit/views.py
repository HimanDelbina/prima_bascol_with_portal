from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from audit.models import AuditLog, AuditAction
from accounts.decorators import manager_or_admin_required
from core.jalali import jalali_to_gregorian

@login_required
@manager_or_admin_required
def audit_list(request):
    """
    Searchable and filterable view of all system audit logs.
    """
    qs = AuditLog.objects.select_related("user").all().order_by("-timestamp")

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(record_repr__icontains=q) |
            Q(record_id__icontains=q) |
            Q(reason__icontains=q) |
            Q(user__username__icontains=q) |
            Q(user__first_name__icontains=q) |
            Q(user__last_name__icontains=q) |
            Q(ip_address__icontains=q)
        )

    action_filter = request.GET.get("action")
    if action_filter:
        qs = qs.filter(action=action_filter)

    model_filter = request.GET.get("model_name")
    if model_filter:
        qs = qs.filter(model_name=model_filter)

    start_date_j = request.GET.get("start_date")
    if start_date_j:
        g_start = jalali_to_gregorian(start_date_j)
        if g_start:
            qs = qs.filter(timestamp__date__gte=g_start)

    end_date_j = request.GET.get("end_date")
    if end_date_j:
        g_end = jalali_to_gregorian(end_date_j)
        if g_end:
            qs = qs.filter(timestamp__date__lte=g_end)

    paginator = Paginator(qs, 30)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(request, "audit/audit_list.html", {
        "page_obj": page_obj,
        "actions": AuditAction.choices,
        "total_count": paginator.count,
        "title": "گزارش جامع تغییرات و ممیزی (Audit Log)",
    })

@login_required
@manager_or_admin_required
def audit_detail(request, pk):
    log_entry = get_object_or_404(AuditLog.objects.select_related("user"), pk=pk)
    
    # Calculate keys present in old or new
    all_keys = list(set(list(log_entry.old_values.keys()) + list(log_entry.new_values.keys())))
    diff_table = []
    for k in sorted(all_keys):
        old_v = log_entry.old_values.get(k, "-")
        new_v = log_entry.new_values.get(k, "-")
        is_changed = old_v != new_v
        diff_table.append({
            "key": k,
            "old_val": old_v,
            "new_val": new_v,
            "is_changed": is_changed
        })

    return render(request, "audit/audit_detail.html", {
        "log_entry": log_entry,
        "diff_table": diff_table,
        "title": f"جزئیات تغییرات - {log_entry.record_repr}",
    })
