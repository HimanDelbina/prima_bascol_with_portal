from django import forms
from django.db import models
from decimal import Decimal
from datetime import datetime
from weighbridge.models import WeighTicket, TicketStatus, WeightMode
from masterdata.models import (
    Product, Party, Driver, Vehicle, VehicleType, 
    Location, UnloadLocation, OperationType, LossType
)
from core.jalali import get_today_jalali, jalali_to_gregorian, format_jalali_date, get_today_gregorian
from core.models import SystemSetting
from core.constants import IRAN_PLATE_LETTERS


class TicketCreateForm(forms.ModelForm):
    plate_part1 = forms.CharField(max_length=5, required=False, widget=forms.TextInput(attrs={"class": "form-control iran-plate-part iran-plate-part1", "placeholder": "۱۲", "id": "plate_part1"}))
    plate_letter = forms.ChoiceField(choices=IRAN_PLATE_LETTERS, required=False, widget=forms.Select(attrs={"class": "form-select iran-plate-part iran-plate-letter", "id": "plate_letter"}))
    plate_part2 = forms.CharField(max_length=5, required=False, widget=forms.TextInput(attrs={"class": "form-control iran-plate-part iran-plate-part2", "placeholder": "۳۴۵", "id": "plate_part2"}))
    plate_iran = forms.CharField(max_length=5, required=False, widget=forms.TextInput(attrs={"class": "form-control iran-plate-part iran-plate-iran", "placeholder": "۶۷", "id": "plate_iran"}))
    
    first_weight_date_jalali = forms.CharField(
        label="تاریخ وزن اول (شمسی)",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control pdate-picker", "id": "first_weight_date_jalali"})
    )
    first_weight_time_str = forms.CharField(
        label="ساعت وزن اول",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control auto-current-time text-center", "placeholder": "HH:MM", "id": "first_weight_time_str"})
    )

    # Optional second weight if direct two-weight registration
    second_weight_date_jalali = forms.CharField(
        label="تاریخ وزن دوم (شمسی)",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control pdate-picker", "id": "second_weight_date_jalali"})
    )
    second_weight_time_str = forms.CharField(
        label="ساعت وزن دوم",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control auto-current-time text-center", "placeholder": "HH:MM", "id": "second_weight_time_str"})
    )

    class Meta:
        model = WeighTicket
        fields = [
            "weight_mode", "operation_type", "party", "product", 
            "vehicle", "vehicle_type", "vehicle_type_custom",
            "driver", "driver_name_custom", "driver_mobile_custom",
            "license_plate_display", "waybill_number", "freight_amount", "origin", "destination",
            "unload_location", "load_count", "first_weight", "second_weight",
            "sent_weight", "loss_type", "loss_percent", "loss_weight",
            "is_loss_overridden", "loss_override_reason", "notes"
        ]
        widgets = {
            "weight_mode": forms.Select(attrs={"class": "form-select fw-bold", "id": "id_weight_mode"}),
            "operation_type": forms.Select(attrs={"class": "form-select", "id": "id_operation_type"}),
            "party": forms.Select(attrs={"class": "form-select", "id": "id_party"}),
            "product": forms.Select(attrs={"class": "form-select", "id": "id_product"}),
            "vehicle": forms.Select(attrs={"class": "form-select", "id": "id_vehicle"}),
            "vehicle_type": forms.Select(attrs={"class": "form-select", "id": "id_vehicle_type"}),
            "vehicle_type_custom": forms.TextInput(attrs={"class": "form-control", "id": "id_vehicle_type_custom", "placeholder": "شرح نوع خودرو در صورت عدم انتخاب از لیست"}),
            "driver": forms.Select(attrs={"class": "form-select", "id": "id_driver"}),
            "driver_name_custom": forms.TextInput(attrs={"class": "form-control", "id": "id_driver_name_custom", "placeholder": "نام راننده"}),
            "driver_mobile_custom": forms.TextInput(attrs={"class": "form-control", "id": "id_driver_mobile_custom", "placeholder": "۰۹۱۲۳۴۵۶۷۸۹"}),
            "license_plate_display": forms.TextInput(attrs={"class": "form-control", "id": "license_plate_display", "placeholder": "مثلاً ۱۲ ج ۳۴۵ - ایران ۶۷"}),
            "waybill_number": forms.TextInput(attrs={"class": "form-control", "placeholder": "شماره بارنامه / حواله"}),
            "freight_amount": forms.NumberInput(attrs={"class": "form-control", "min": "0", "step": "1", "placeholder": "مبلغ به تومان", "inputmode": "numeric"}),
            "origin": forms.Select(attrs={"class": "form-select"}),
            "destination": forms.Select(attrs={"class": "form-select"}),
            "unload_location": forms.Select(attrs={"class": "form-select"}),
            "load_count": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            
            "first_weight": forms.NumberInput(attrs={"class": "form-control form-control-lg fw-bold text-primary", "id": "id_first_weight", "step": "any", "placeholder": "۰"}),
            "second_weight": forms.NumberInput(attrs={"class": "form-control form-control-lg fw-bold text-primary", "id": "id_second_weight", "step": "any", "placeholder": "۰"}),
            "sent_weight": forms.NumberInput(attrs={"class": "form-control", "id": "id_sent_weight", "step": "any", "placeholder": "۰"}),
            
            "loss_type": forms.Select(attrs={"class": "form-select", "id": "id_loss_type"}),
            "loss_percent": forms.NumberInput(attrs={"class": "form-control", "id": "id_loss_percent", "step": "0.01", "placeholder": "۰"}),
            "loss_weight": forms.NumberInput(attrs={"class": "form-control", "id": "id_loss_weight", "step": "any", "readonly": "readonly", "placeholder": "۰"}),
            "is_loss_overridden": forms.CheckboxInput(attrs={"class": "form-check-input", "id": "id_is_loss_overridden"}),
            "loss_override_reason": forms.TextInput(attrs={"class": "form-control", "placeholder": "دلیل تغییر دستی افت (اجباری در صورت اورراید)", "id": "id_loss_override_reason"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "توضیحات اختیاری سند"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter active master data
        self.fields["product"].queryset = Product.objects.filter(is_active=True)
        self.fields["party"].queryset = Party.objects.filter(is_active=True)
        self.fields["driver"].queryset = Driver.objects.filter(is_active=True)
        self.fields["vehicle"].queryset = Vehicle.objects.filter(is_active=True)
        self.fields["operation_type"].queryset = OperationType.objects.filter(is_active=True)
        self.fields["loss_type"].queryset = LossType.objects.filter(is_active=True)
        self.fields["origin"].queryset = Location.objects.filter(is_active=True)
        self.fields["second_weight"].required = False
        self.fields["sent_weight"].required = False
        self.fields["loss_type"].required = False
        self.fields["loss_percent"].required = False
        self.fields["loss_weight"].required = False
        self.fields["is_loss_overridden"].required = False
        self.fields["loss_override_reason"].required = False
        self.fields["notes"].required = False
        self.fields["vehicle_type_custom"].required = False
        self.fields["driver_name_custom"].required = False
        self.fields["driver_mobile_custom"].required = False
        self.fields["waybill_number"].required = False
        self.fields["license_plate_display"].required = False

        if not self.instance.pk:
            self.fields["first_weight_date_jalali"].initial = get_today_jalali()
            self.fields["first_weight_time_str"].initial = datetime.now().strftime("%H:%M")
            self.initial["first_weight"] = ""
            self.initial["second_weight"] = ""
            self.initial["sent_weight"] = ""
            self.initial["loss_percent"] = ""
            self.initial["loss_weight"] = ""


        # Dynamic requirements based on system settings
        sys_settings = SystemSetting.get_settings()
        if sys_settings.require_waybill:
            self.fields["waybill_number"].required = True
        if sys_settings.require_driver:
            self.fields["driver"].required = False  # can be driver or driver_name_custom
        if sys_settings.require_origin:
            self.fields["origin"].required = True
        if sys_settings.require_destination:
            self.fields["destination"].required = True
        if sys_settings.require_unload_location:
            self.fields["unload_location"].required = True

    def clean(self):
        cleaned_data = super().clean()
        for field in ("sent_weight", "loss_percent", "loss_weight"):
            if cleaned_data.get(field) is None and field not in self.errors:
                cleaned_data[field] = Decimal("0")
        first_date = cleaned_data.get("first_weight_date_jalali")
        parsed_date = jalali_to_gregorian(first_date) if first_date else get_today_gregorian()
        if not parsed_date:
            self.add_error("first_weight_date_jalali", "تاریخ وزن اول معتبر نیست.")
        else:
            self.instance.first_weight_date = parsed_date
        plate = cleaned_data.get("license_plate_display", "").strip()
        if not plate:
            # Try construct from parts
            p1 = cleaned_data.get("plate_part1", "").strip()
            pL = cleaned_data.get("plate_letter", "").strip()
            p2 = cleaned_data.get("plate_part2", "").strip()
            pIran = cleaned_data.get("plate_iran", "").strip()
            if p1 and pL and p2 and pIran:
                plate = f"{p1} {pL} {p2} - ایران {pIran}"
                cleaned_data["license_plate_display"] = plate

        if not plate:
            self.add_error("license_plate_display", "شماره پلاک خودرو الزامی است.")
        else:
            from weighbridge.models import BlockedPlate
            from weighbridge.plate_policy import normalize_plate
            norm = normalize_plate(plate)
            blocked = BlockedPlate.objects.filter(normalized_plate=norm, is_active=True).first()
            if blocked:
                self.add_error("license_plate_display", f"⛔ این خودرو در لیست سیاه پلاک‌های مسدود قرار دارد و امکان بارگیری ندارد! علت مسدودی: {blocked.reason}")

        w1 = cleaned_data.get("first_weight")
        if w1 is None or w1 <= 0:
            self.add_error("first_weight", "وزن اول باید مقداری بزرگتر از صفر باشد.")
        w2 = cleaned_data.get("second_weight")
        if w2 is not None and w2 <= 0:
            self.add_error("second_weight", "وزن دوم باید بزرگتر از صفر باشد یا خالی بماند.")
        if cleaned_data.get("weight_mode") == WeightMode.DIRECT and w2 is None:
            self.add_error("second_weight", "برای ثبت مستقیم، وزن دوم را وارد کنید.")
        if (cleaned_data.get("sent_weight") or 0) < 0:
            self.add_error("sent_weight", "وزن ارسالی نمی‌تواند منفی باشد.")
        if (cleaned_data.get("loss_weight") or 0) < 0:
            self.add_error("loss_weight", "وزن افت نمی‌تواند منفی باشد.")

        loss_pct = cleaned_data.get("loss_percent") or 0
        if loss_pct < 0 or loss_pct > 100:
            self.add_error("loss_percent", "درصد افت باید عددی بین ۰ تا ۱۰۰ باشد.")

        is_overridden = cleaned_data.get("is_loss_overridden")
        reason = cleaned_data.get("loss_override_reason", "").strip()
        if is_overridden and not reason:
            self.add_error("loss_override_reason", "در صورت تغییر دستی افت، وارد کردن دلیل الزامی است.")

        return cleaned_data


class SecondWeightForm(forms.ModelForm):
    second_weight_date_jalali = forms.CharField(
        label="تاریخ وزن دوم (شمسی)",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control pdate-picker", "id": "second_weight_date_jalali"})
    )
    second_weight_time_str = forms.CharField(
        label="ساعت وزن دوم",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control auto-current-time text-center", "placeholder": "HH:MM", "id": "second_weight_time_str"})
    )

    class Meta:
        model = WeighTicket
        fields = [
            "second_weight", "sent_weight", "loss_type", "loss_percent", 
            "loss_weight", "is_loss_overridden", "loss_override_reason", "notes"
        ]
        widgets = {
            "second_weight": forms.NumberInput(attrs={"class": "form-control form-control-lg fw-bold text-success", "id": "id_second_weight", "step": "any", "autofocus": True, "placeholder": "۰"}),
            "sent_weight": forms.NumberInput(attrs={"class": "form-control", "id": "id_sent_weight", "step": "any", "placeholder": "۰"}),
            "loss_type": forms.Select(attrs={"class": "form-select", "id": "id_loss_type"}),
            "loss_percent": forms.NumberInput(attrs={"class": "form-control", "id": "id_loss_percent", "step": "0.01", "placeholder": "۰"}),
            "loss_weight": forms.NumberInput(attrs={"class": "form-control", "id": "id_loss_weight", "step": "any", "readonly": "readonly", "placeholder": "۰"}),
            "is_loss_overridden": forms.CheckboxInput(attrs={"class": "form-check-input", "id": "id_is_loss_overridden"}),
            "loss_override_reason": forms.TextInput(attrs={"class": "form-control", "placeholder": "دلیل تغییر دستی افت (اجباری در صورت اورراید)", "id": "id_loss_override_reason"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "توضیحات اختیاری سند"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["loss_type"].queryset = LossType.objects.filter(is_active=True)
        self.fields["loss_type"].required = False
        self.fields["sent_weight"].required = False
        self.fields["loss_percent"].required = False
        self.fields["loss_weight"].required = False
        self.fields["is_loss_overridden"].required = False
        self.fields["loss_override_reason"].required = False
        self.fields["notes"].required = False

        if not self.instance.second_weight:
            self.initial["second_weight"] = ""
        if self.instance.sent_weight == 0:
            self.initial["sent_weight"] = ""
        if self.instance.loss_percent == 0:
            self.initial["loss_percent"] = ""
        if self.instance.loss_weight == 0:
            self.initial["loss_weight"] = ""

        if not self.instance.second_weight_date:
            self.fields["second_weight_date_jalali"].initial = get_today_jalali()
            self.fields["second_weight_time_str"].initial = datetime.now().strftime("%H:%M")
        else:
            self.fields["second_weight_date_jalali"].initial = format_jalali_date(self.instance.second_weight_date)
            if self.instance.second_weight_time:
                self.fields["second_weight_time_str"].initial = self.instance.second_weight_time.strftime("%H:%M")

    def clean(self):
        cleaned_data = super().clean()
        w2 = cleaned_data.get("second_weight")
        for field in ("sent_weight", "loss_percent", "loss_weight"):
            if cleaned_data.get(field) is None and field not in self.errors:
                cleaned_data[field] = Decimal("0")
        if (cleaned_data.get("sent_weight") or 0) < 0:
            self.add_error("sent_weight", "وزن ارسالی نمی‌تواند منفی باشد.")
        second_date = cleaned_data.get("second_weight_date_jalali")
        if second_date and not jalali_to_gregorian(second_date):
            self.add_error("second_weight_date_jalali", "تاریخ وزن دوم معتبر نیست.")
        if w2 is None or w2 <= 0:
            self.add_error("second_weight", "وزن دوم باید مقداری بزرگتر از صفر باشد.")

        loss_pct = cleaned_data.get("loss_percent") or 0
        if loss_pct < 0 or loss_pct > 100:
            self.add_error("loss_percent", "درصد افت باید بین ۰ تا ۱۰۰ باشد.")

        is_overridden = cleaned_data.get("is_loss_overridden")
        reason = cleaned_data.get("loss_override_reason", "").strip()
        if is_overridden and not reason:
            self.add_error("loss_override_reason", "در صورت تغییر دستی افت، وارد کردن دلیل الزامی است.")

        return cleaned_data


class TicketEditManagerForm(forms.ModelForm):
    manager_reason = forms.CharField(
        label="دلیل اصلاح و ویرایش سند (اجباری)",
        required=True,
        widget=forms.Textarea(attrs={"class": "form-control border-danger", "rows": 2, "placeholder": "دلیل فنی و رسمی اصلاح سند را به طور دقیق وارد فرمایید."})
    )

    class Meta:
        model = WeighTicket
        fields = [
            "operation_type", "party", "product", "vehicle", "vehicle_type", 
            "driver", "driver_name_custom", "driver_mobile_custom",
            "license_plate_display", "waybill_number", "freight_amount", "origin", "destination",
            "unload_location", "load_count", "first_weight", "second_weight", 
            "sent_weight", "loss_type", "loss_percent", "loss_weight", 
            "is_loss_overridden", "loss_override_reason", "notes"
        ]
        widgets = {
            "operation_type": forms.Select(attrs={"class": "form-select"}),
            "party": forms.Select(attrs={"class": "form-select"}),
            "product": forms.Select(attrs={"class": "form-select"}),
            "vehicle": forms.Select(attrs={"class": "form-select"}),
            "vehicle_type": forms.Select(attrs={"class": "form-select"}),
            "driver": forms.Select(attrs={"class": "form-select"}),
            "driver_name_custom": forms.TextInput(attrs={"class": "form-control"}),
            "driver_mobile_custom": forms.TextInput(attrs={"class": "form-control"}),
            "license_plate_display": forms.TextInput(attrs={"class": "form-control"}),
            "waybill_number": forms.TextInput(attrs={"class": "form-control"}),
            "freight_amount": forms.NumberInput(attrs={"class": "form-control", "min": "0", "step": "1", "inputmode": "numeric"}),
            "origin": forms.Select(attrs={"class": "form-select"}),
            "destination": forms.Select(attrs={"class": "form-select"}),
            "unload_location": forms.Select(attrs={"class": "form-select"}),
            "load_count": forms.NumberInput(attrs={"class": "form-control"}),
            "first_weight": forms.NumberInput(attrs={"class": "form-control", "step": "any"}),
            "second_weight": forms.NumberInput(attrs={"class": "form-control", "step": "any"}),
            "sent_weight": forms.NumberInput(attrs={"class": "form-control", "step": "any"}),
            "loss_type": forms.Select(attrs={"class": "form-select"}),
            "loss_percent": forms.NumberInput(attrs={"class": "form-control", "id": "id_loss_percent", "step": "0.01", "placeholder": "۰"}),
            "loss_weight": forms.NumberInput(attrs={"class": "form-control", "id": "id_loss_weight", "step": "any", "placeholder": "۰"}),
            "is_loss_overridden": forms.CheckboxInput(attrs={"class": "form-check-input", "id": "id_is_loss_overridden"}),
            "loss_override_reason": forms.TextInput(attrs={"class": "form-control", "id": "id_loss_override_reason"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f, model_cls in [
            ("product", Product), ("party", Party), ("driver", Driver),
            ("vehicle", Vehicle), ("operation_type", OperationType),
            ("loss_type", LossType), ("origin", Location),
            ("destination", Location), ("unload_location", UnloadLocation)
        ]:
            if f in self.fields:
                curr_val = getattr(self.instance, f + "_id", None) if self.instance and self.instance.pk else None
                if curr_val:
                    self.fields[f].queryset = model_cls.objects.filter(models.Q(is_active=True) | models.Q(pk=curr_val))
                else:
                    self.fields[f].queryset = model_cls.objects.filter(is_active=True)

        optional_fields = [
            "second_weight", "sent_weight", "loss_type", "loss_percent", 
            "loss_weight", "is_loss_overridden", "loss_override_reason", 
            "notes", "driver_name_custom", "driver_mobile_custom", 
            "waybill_number", "freight_amount", "origin", "destination", 
            "unload_location", "vehicle", "vehicle_type", "driver", "load_count"
        ]
        for field_name in optional_fields:
            if field_name in self.fields:
                self.fields[field_name].required = False

        if self.instance and self.instance.pk:
            if self.instance.loss_weight == 0:
                self.initial["loss_weight"] = ""
            if self.instance.loss_percent == 0:
                self.initial["loss_percent"] = ""
            if self.instance.sent_weight == 0:
                self.initial["sent_weight"] = ""
            if not self.instance.load_count:
                self.initial["load_count"] = 1

    def clean(self):
        cleaned_data = super().clean()
        for field in ("sent_weight", "loss_percent", "loss_weight"):
            if cleaned_data.get(field) is None and field not in self.errors:
                cleaned_data[field] = Decimal("0")

        if cleaned_data.get("load_count") is None or cleaned_data.get("load_count") == "":
            cleaned_data["load_count"] = (self.instance.load_count if self.instance and self.instance.pk else 1) or 1

        w1 = cleaned_data.get("first_weight")
        if w1 is None or w1 <= 0:
            self.add_error("first_weight", "وزن اول باید مقداری بزرگتر از صفر باشد.")

        w2 = cleaned_data.get("second_weight")
        if w2 is not None and w2 <= 0:
            self.add_error("second_weight", "وزن دوم باید بزرگتر از صفر باشد یا خالی بماند.")

        if (cleaned_data.get("sent_weight") or 0) < 0:
            self.add_error("sent_weight", "وزن ارسالی نمی‌تواند منفی باشد.")

        loss_weight = cleaned_data.get("loss_weight") or Decimal("0")
        if loss_weight < 0:
            self.add_error("loss_weight", "وزن افت نمی‌تواند منفی باشد.")

        loss_pct = cleaned_data.get("loss_percent") or Decimal("0")
        if loss_pct < 0 or loss_pct > 100:
            self.add_error("loss_percent", "درصد افت باید عددی بین ۰ تا ۱۰۰ باشد.")

        plate = cleaned_data.get("license_plate_display", "").strip()
        if not plate:
            self.add_error("license_plate_display", "شماره پلاک خودرو الزامی است.")
        else:
            from weighbridge.models import BlockedPlate
            from weighbridge.plate_policy import normalize_plate
            norm = normalize_plate(plate)
            blocked = BlockedPlate.objects.filter(normalized_plate=norm, is_active=True).first()
            if blocked:
                self.add_error("license_plate_display", f"⛔ این خودرو در لیست سیاه پلاک‌های مسدود قرار دارد و امکان بارگیری ندارد! علت مسدودی: {blocked.reason}")

        # If loss_weight is manually entered and > 0, ensure is_loss_overridden is set
        if loss_weight > 0 and not cleaned_data.get("is_loss_overridden"):
            cleaned_data["is_loss_overridden"] = True
            if not cleaned_data.get("loss_override_reason"):
                cleaned_data["loss_override_reason"] = cleaned_data.get("manager_reason", "")

        return cleaned_data

