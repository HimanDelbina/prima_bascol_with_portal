from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.http import Http404
from django.views.decorators.http import require_http_methods

from audit.services import log_audit
from core.constants import IRAN_PLATE_LETTERS
from weighbridge.models import PlateAutoFill, WeighTicket, TicketStatus
from weighbridge.plate_policy import can_manage_plate_autofill, normalize_plate


class PlateAutoFillForm(forms.Form):
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
    notes = forms.CharField(
        label="یادداشت / توضیحات",
        required=False,
        max_length=1000,
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "rows": 2,
            "placeholder": "مثلاً: خودروهای تردد مکرر حمل شمش، بارگیری روزانه معدن، کامیون ثابت شرکت و..."
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
def plate_autofill_list(request):
    if not can_manage_plate_autofill(request.user):
        raise PermissionDenied("فقط مدیر ارشد مجاز به مدیریت و افزودن پلاک به سیستم تکمیل خودکار داده‌ها است.")

    form = PlateAutoFillForm(request.POST if request.method == "POST" else None)

    if request.method == "POST":
        action = request.POST.get("action", "save")

        # Toggle Active / Inactive
        if action in ("activate", "deactivate"):
            item_id = request.POST.get("item_id", "")
            if not item_id.isdecimal():
                raise Http404("پلاک مورد نظر یافت نشد.")

            with transaction.atomic():
                obj = get_object_or_404(PlateAutoFill.objects.select_for_update(), pk=item_id)
                old = {"is_active": obj.is_active}
                obj.is_active = (action == "activate")
                obj.save()

                status_label = "فعال‌سازی" if obj.is_active else "غیرفعال‌سازی"
                log_audit(
                    action="update",
                    model_name="PlateAutoFill",
                    record_id=obj.pk,
                    record_repr=obj.license_plate_display,
                    user=request.user,
                    old_values=old,
                    new_values={"is_active": obj.is_active},
                    reason=f"{status_label} تکمیل خودکار پلاک"
                )

            msg = f"پلاک «{obj.license_plate_display}» فعال شد و در صدور قبوض جدید به‌طور خودکار پر می‌شود." if obj.is_active else f"تکمیل خودکار پلاک «{obj.license_plate_display}» غیرفعال شد."
            messages.success(request, msg)
            return redirect("weighbridge:plate_autofill")

        # Delete action
        if action == "delete":
            item_id = request.POST.get("item_id", "")
            if not item_id.isdecimal():
                raise Http404("پلاک مورد نظر یافت نشد.")

            with transaction.atomic():
                obj = get_object_or_404(PlateAutoFill.objects.select_for_update(), pk=item_id)
                disp = obj.license_plate_display
                log_audit(
                    action="delete",
                    model_name="PlateAutoFill",
                    record_id=obj.pk,
                    record_repr=disp,
                    user=request.user,
                    old_values={"license_plate_display": disp, "notes": obj.notes},
                    new_values={},
                    reason="حذف پلاک از سیستم تکمیل خودکار"
                )
                obj.delete()

            messages.success(request, f"پلاک «{disp}» از لیست تکمیل خودکار حذف شد.")
            return redirect("weighbridge:plate_autofill")

        # Save / Create
        if action == "save" and form.is_valid():
            with transaction.atomic():
                plate_disp = form.cleaned_data["license_plate_display"]
                notes_text = form.cleaned_data.get("notes", "").strip()
                norm = normalize_plate(plate_disp)

                obj, created = PlateAutoFill.objects.select_for_update().get_or_create(
                    normalized_plate=norm,
                    defaults={
                        "license_plate_display": plate_disp,
                        "notes": notes_text,
                        "created_by": request.user,
                        "is_active": True,
                    },
                )
                old = {} if created else {"notes": obj.notes, "is_active": obj.is_active}
                obj.license_plate_display = plate_disp
                obj.notes = notes_text
                obj.is_active = True
                obj.save()

                log_audit(
                    action="create" if created else "update",
                    model_name="PlateAutoFill",
                    record_id=obj.pk,
                    record_repr=obj.license_plate_display,
                    user=request.user,
                    old_values=old,
                    new_values={"plate": obj.license_plate_display, "notes": obj.notes, "is_active": True},
                    reason="افزودن پلاک به سیستم تکمیل خودکار"
                )

            messages.success(
                request,
                f"پلاک «{plate_disp}» در لیست تکمیل خودکار ثبت شد. هنگام ثبت قبض جدید، داده‌های آخرین ورود این خودرو (به‌جز وزن) خودکار بارگذاری خواهد شد."
            )
            return redirect("weighbridge:plate_autofill")

    query = request.GET.get("q", "").strip()
    queryset = PlateAutoFill.objects.select_related("created_by").all().order_by("-is_active", "-updated_at")
    if query:
        norm_q = normalize_plate(query)
        queryset = queryset.filter(
            Q(normalized_plate__contains=norm_q) |
            Q(license_plate_display__icontains=query) |
            Q(notes__icontains=query)
        )

    # Attach last ticket summary to displayed items for convenience
    items = list(queryset)
    for item in items:
        last_t = WeighTicket.objects.filter(
            Q(normalized_plate=item.normalized_plate) |
            Q(license_plate_display__icontains=item.license_plate_display)
        ).exclude(status=TicketStatus.CANCELLED).select_related("party", "product").order_by("-id").first()
        item.last_ticket = last_t

    paginator = Paginator(items, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "weighbridge/plate_autofill.html", {
        "title": "پلاک‌های تکمیل خودکار (بارگذاری از آخرین ورود)",
        "form": form,
        "query": query,
        "page_obj": page_obj,
    })
