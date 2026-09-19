from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.http import Http404
from django.views.decorators.http import require_http_methods

from audit.services import log_audit
from weighbridge.models import PlateRegistrationException
from weighbridge.plate_policy import can_manage_plate_exceptions, normalize_plate


class PlateExceptionForm(forms.Form):
    license_plate_display = forms.CharField(label="پلاک خودرو", max_length=60,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "۱۲ ع ۳۴۵ - ایران ۶۷"}))
    reason = forms.CharField(label="دلیل مجوز ثبت چندباره در روز", min_length=3, max_length=1000,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}))

    def clean_license_plate_display(self):
        value = self.cleaned_data["license_plate_display"]
        if not normalize_plate(value):
            raise forms.ValidationError("پلاک معتبر وارد کنید.")
        return value


@login_required
@require_http_methods(["GET", "POST"])
def plate_exceptions(request):
    if not can_manage_plate_exceptions(request.user):
        raise PermissionDenied("فقط سرپرست باسکول یا مدیر سیستم مجاز به مدیریت استثناهای پلاک است.")
    form = PlateExceptionForm(request.POST if request.method == "POST" else None)
    if request.method == "POST":
        action = request.POST.get("action", "save")
        if action in ("activate", "deactivate"):
            exception_id = request.POST.get("exception_id", "")
            if not exception_id.isdecimal():
                raise Http404("مجوز پلاک یافت نشد.")
            with transaction.atomic():
                obj = get_object_or_404(PlateRegistrationException.objects.select_for_update(), pk=exception_id)
                old = {"is_active": obj.is_active}
                obj.is_active = action == "activate"
                obj.approved_by = request.user
                obj.save()
                log_audit(action="update", model_name="PlateRegistrationException", record_id=obj.pk,
                          record_repr=obj.license_plate_display, user=request.user, old_values=old,
                          new_values={"is_active": obj.is_active, "approved_by": request.user.pk},
                          reason="فعال‌سازی مجوز پلاک" if obj.is_active else "غیرفعال‌سازی مجوز پلاک")
            messages.success(request, "وضعیت مجوز پلاک به‌روز شد.")
            return redirect("weighbridge:plate_exceptions")
        if action == "save" and form.is_valid():
            with transaction.atomic():
                obj, created = PlateRegistrationException.objects.select_for_update().get_or_create(
                    normalized_plate=normalize_plate(form.cleaned_data["license_plate_display"]),
                    defaults={**form.cleaned_data, "approved_by": request.user},
                )
                old = {} if created else {"reason": obj.reason, "is_active": obj.is_active, "approved_by": obj.approved_by_id}
                obj.license_plate_display = form.cleaned_data["license_plate_display"]
                obj.reason = form.cleaned_data["reason"]
                obj.approved_by = request.user
                obj.is_active = True
                obj.save()
                log_audit(action="create" if created else "update", model_name="PlateRegistrationException",
                          record_id=obj.pk, record_repr=obj.license_plate_display, user=request.user,
                          old_values=old, new_values={"plate": obj.license_plate_display, "reason": obj.reason,
                                                     "is_active": True, "approved_by": request.user.pk}, reason=obj.reason)
            messages.success(request, "این پلاک برای ثبت چندباره در یک روز مجاز شد.")
            return redirect("weighbridge:plate_exceptions")
    query = request.GET.get("q", "").strip()
    exceptions = PlateRegistrationException.objects.select_related("approved_by").all()
    if query:
        exceptions = exceptions.filter(normalized_plate__contains=normalize_plate(query))
    return render(request, "weighbridge/plate_exceptions.html", {
        "title": "استثناهای ثبت روزانه پلاک", "form": form, "query": query,
        "page_obj": Paginator(exceptions, 25).get_page(request.GET.get("page")),
    })
