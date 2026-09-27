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


from core.constants import IRAN_PLATE_LETTERS


class PlateExceptionForm(forms.Form):
    plate_part1 = forms.CharField(
        max_length=5,
        required=False,
        widget=forms.TextInput(attrs={
            "class": "iran-plate-input-part1",
            "maxlength": "2",
            "id": "plate_part1",
            "placeholder": "12",
            "autocomplete": "off",
            "autofocus": "autofocus",
        })
    )
    plate_letter = forms.ChoiceField(
        choices=IRAN_PLATE_LETTERS,
        required=False,
        widget=forms.Select(attrs={
            "class": "iran-plate-letter-select",
            "id": "plate_letter",
        })
    )
    plate_part2 = forms.CharField(
        max_length=5,
        required=False,
        widget=forms.TextInput(attrs={
            "class": "iran-plate-input-part2",
            "maxlength": "3",
            "id": "plate_part2",
            "placeholder": "345",
            "autocomplete": "off",
        })
    )
    plate_iran = forms.CharField(
        max_length=5,
        required=False,
        widget=forms.TextInput(attrs={
            "class": "iran-plate-iran",
            "maxlength": "2",
            "id": "plate_iran",
            "placeholder": "64",
            "autocomplete": "off",
        })
    )
    license_plate_display = forms.CharField(
        label="شماره کامل پلاک",
        max_length=60,
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control bg-light font-monospace fw-bold",
            "id": "license_plate_display",
            "placeholder": "۱۲ ع ۳۴۵ - ایران ۶۴",
            "readonly": "readonly",
        })
    )
    reason = forms.CharField(
        label="دلیل مجوز ثبت چندباره در روز",
        min_length=3,
        max_length=1000,
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "rows": 2,
            "placeholder": "مثلاً: تردد متعدد درون‌کارخانه‌ای، حمل شمش بین‌انبارها، شیفت فشرده و..."
        })
    )

    def clean(self):
        cleaned_data = super().clean()
        p1 = (cleaned_data.get("plate_part1") or "").strip()
        pL = (cleaned_data.get("plate_letter") or "").strip()
        p2 = (cleaned_data.get("plate_part2") or "").strip()
        pI = (cleaned_data.get("plate_iran") or "").strip()
        disp = (cleaned_data.get("license_plate_display") or "").strip()

        # If 4 visual parts are provided, construct full string
        if p1 and pL and p2 and pI:
            disp = f"{p1} {pL} {p2} - ایران {pI}"
            cleaned_data["license_plate_display"] = disp

        if not disp:
            self.add_error("license_plate_display", "لطفاً شماره پلاک را به صورت کامل وارد کنید.")
            return cleaned_data

        norm = normalize_plate(disp)
        if not norm:
            self.add_error("license_plate_display", "پلاک وارد شده معتبر نیست. لطفاً ارقام و حرف پلاک را به درستی وارد نمایید.")
            return cleaned_data

        cleaned_data["license_plate_display"] = disp
        return cleaned_data


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
                plate_disp = form.cleaned_data["license_plate_display"]
                reason_text = form.cleaned_data["reason"]
                norm = normalize_plate(plate_disp)
                obj, created = PlateRegistrationException.objects.select_for_update().get_or_create(
                    normalized_plate=norm,
                    defaults={
                        "license_plate_display": plate_disp,
                        "reason": reason_text,
                        "approved_by": request.user,
                        "is_active": True,
                    },
                )
                old = {} if created else {"reason": obj.reason, "is_active": obj.is_active, "approved_by": obj.approved_by_id}
                obj.license_plate_display = plate_disp
                obj.reason = reason_text
                obj.approved_by = request.user
                obj.is_active = True
                obj.save()
                log_audit(action="create" if created else "update", model_name="PlateRegistrationException",
                          record_id=obj.pk, record_repr=obj.license_plate_display, user=request.user,
                          old_values=old, new_values={"plate": obj.license_plate_display, "reason": obj.reason,
                                                     "is_active": True, "approved_by": request.user.pk}, reason=obj.reason)
            messages.success(request, f"پلاک «{plate_disp}» برای ثبت چندباره در یک روز مجاز شد.")
            return redirect("weighbridge:plate_exceptions")

    query = request.GET.get("q", "").strip()
    exceptions = PlateRegistrationException.objects.select_related("approved_by").all()
    if query:
        exceptions = exceptions.filter(normalized_plate__contains=normalize_plate(query))
    return render(request, "weighbridge/plate_exceptions.html", {
        "title": "استثناهای ثبت روزانه پلاک", "form": form, "query": query,
        "page_obj": Paginator(exceptions, 25).get_page(request.GET.get("page")),
    })
