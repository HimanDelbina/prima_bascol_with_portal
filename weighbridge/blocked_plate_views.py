from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from audit.services import log_audit
from core.constants import IRAN_PLATE_LETTERS
from weighbridge.models import BlockedPlate
from weighbridge.plate_policy import can_manage_blocked_plates, normalize_plate


class BlockedPlateForm(forms.Form):
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
        label="علت و دلیل مسدودسازی پلاک",
        min_length=3,
        max_length=1000,
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "rows": 2,
            "placeholder": "علت ممنوعیت بارگیری و ورود خودرو (مثلاً: تخلف در تناژ، دستور حراست، عدم تسویه مالی، مغایرت باسکول و...)"
        })
    )

    def clean(self):
        cleaned_data = super().clean()
        p1 = (cleaned_data.get("plate_part1") or "").strip()
        pL = (cleaned_data.get("plate_letter") or "").strip()
        p2 = (cleaned_data.get("plate_part2") or "").strip()
        pI = (cleaned_data.get("plate_iran") or "").strip()
        disp = (cleaned_data.get("license_plate_display") or "").strip()

        # If 4 visual parts are provided, assemble full string
        if p1 and pL and p2 and pI:
            disp = f"{p1} {pL} {p2} - ایران {pI}"
            cleaned_data["license_plate_display"] = disp

        if not disp:
            self.add_error("license_plate_display", "لطفاً شماره پلاک مورد نظر برای مسدودسازی را کامل وارد کنید.")
            return cleaned_data

        norm = normalize_plate(disp)
        if not norm:
            self.add_error("license_plate_display", "پلاک وارد شده معتبر نیست. لطفاً ارقام و حرف پلاک را به درستی وارد نمایید.")
            return cleaned_data

        cleaned_data["license_plate_display"] = disp
        return cleaned_data


@login_required
@require_http_methods(["GET", "POST"])
def blocked_plates(request):
    if not can_manage_blocked_plates(request.user):
        raise PermissionDenied("فقط مدیران و سرپرست باسکول مجاز به مدیریت لیست سیاه پلاک‌ها هستند.")

    form = BlockedPlateForm(request.POST if request.method == "POST" else None)

    if request.method == "POST":
        action = request.POST.get("action", "save")

        # Action: Toggle block status (activate = block, deactivate = unblock)
        if action in ("activate", "deactivate"):
            item_id = request.POST.get("item_id", "")
            if not item_id.isdecimal():
                raise Http404("رکورد مسدودی پلاک یافت نشد.")

            with transaction.atomic():
                obj = get_object_or_404(BlockedPlate.objects.select_for_update(), pk=item_id)
                old = {"is_active": obj.is_active}
                obj.is_active = (action == "activate")
                obj.blocked_by = request.user
                obj.save()

                status_label = "مسدودسازی مجدد" if obj.is_active else "رفع مسدودی"
                log_audit(
                    action="update",
                    model_name="BlockedPlate",
                    record_id=obj.pk,
                    record_repr=obj.license_plate_display,
                    user=request.user,
                    old_values=old,
                    new_values={"is_active": obj.is_active, "blocked_by": request.user.pk},
                    reason=f"{status_label} پلاک"
                )

            msg = f"پلاک «{obj.license_plate_display}» مجدداً مسدود شد." if obj.is_active else f"مسدودی پلاک «{obj.license_plate_display}» با موفقیت لغو (رفع مسدودی) شد."
            messages.success(request, msg)
            return redirect("weighbridge:blocked_plates")

        # Action: New Block / Update Reason
        if action == "save" and form.is_valid():
            with transaction.atomic():
                plate_disp = form.cleaned_data["license_plate_display"]
                reason_text = form.cleaned_data["reason"]
                norm = normalize_plate(plate_disp)

                obj, created = BlockedPlate.objects.select_for_update().get_or_create(
                    normalized_plate=norm,
                    defaults={
                        "license_plate_display": plate_disp,
                        "reason": reason_text,
                        "blocked_by": request.user,
                        "is_active": True,
                    },
                )
                old = {} if created else {"reason": obj.reason, "is_active": obj.is_active, "blocked_by": obj.blocked_by_id}
                obj.license_plate_display = plate_disp
                obj.reason = reason_text
                obj.blocked_by = request.user
                obj.is_active = True
                obj.save()

                log_audit(
                    action="create" if created else "update",
                    model_name="BlockedPlate",
                    record_id=obj.pk,
                    record_repr=obj.license_plate_display,
                    user=request.user,
                    old_values=old,
                    new_values={"plate": obj.license_plate_display, "reason": obj.reason, "is_active": True, "blocked_by": request.user.pk},
                    reason=f"مسدودسازی پلاک: {obj.reason}"
                )

            messages.success(request, f"پلاک «{plate_disp}» در لیست سیاه ثبت و بارگیری آن مسدود گردید.")
            return redirect("weighbridge:blocked_plates")

    query = request.GET.get("q", "").strip()
    blocked_list = BlockedPlate.objects.select_related("blocked_by").all().order_by("-is_active", "-updated_at")
    if query:
        norm_q = normalize_plate(query)
        from django.db.models import Q
        filter_q = Q(license_plate_display__icontains=query) | Q(reason__icontains=query)
        if norm_q:
            filter_q |= Q(normalized_plate__contains=norm_q)
        blocked_list = blocked_list.filter(filter_q)

    return render(request, "weighbridge/blocked_plates.html", {
        "title": "پلاک‌های مسدود (لیست سیاه)",
        "form": form,
        "query": query,
        "page_obj": Paginator(blocked_list, 25).get_page(request.GET.get("page")),
    })
