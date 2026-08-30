from django import forms
from decimal import Decimal
from datetime import datetime
from weighbridge.models import WeighTicket, TicketStatus, WeightMode
from masterdata.models import (
    Product, Party, Driver, Vehicle, VehicleType, 
    Location, UnloadLocation, OperationType, LossType
)
from core.jalali import get_today_jalali, jalali_to_gregorian, format_jalali_date, get_today_gregorian
from core.models import SystemSetting

IRAN_PLATE_LETTERS = [
    ("", "حرف"),
    ("الف", "الف"), ("ب", "ب"), ("پ", "پ"), ("ت", "ت"), ("ث", "ث"), 
    ("ج", "ج"), ("د", "د"), ("ز", "ز"), ("س", "س"), ("ش", "ش"), 
    ("ص", "ص"), ("ط", "ط"), ("ع", "ع"), ("ف", "ف"), ("ق", "ق"), 
    ("ک", "ک"), ("گ", "گ"), ("ل", "ل"), ("م", "م"), ("ن", "ن"), 
    ("و", "و"), ("ه", "ه"), ("ی", "ی"), ("ژ", "ژ (معلولین)"), ("D", "D (دیپلمات)")
]

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
            "license_plate_display", "waybill_number", "origin", "destination", 
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
            "vehicle_type_custom": forms.TextInput(attrs={"class": "form-control", "placeholder": "شرح نوع خودرو در صورت عدم انتخاب از لیست"}),
            "driver": forms.Select(attrs={"class": "form-select", "id": "id_driver"}),
            "driver_name_custom": forms.TextInput(attrs={"class": "form-control", "placeholder": "نام راننده"}),
            "driver_mobile_custom": forms.TextInput(attrs={"class": "form-control", "placeholder": "۰۹۱۲۳۴۵۶۷۸۹"}),
            "license_plate_display": forms.TextInput(attrs={"class": "form-control", "id": "license_plate_display", "placeholder": "مثلاً ۱۲ ج ۳۴۵ - ایران ۶۷"}),
            "waybill_number": forms.TextInput(attrs={"class": "form-control", "placeholder": "شماره بارنامه / حواله"}),
            "origin": forms.Select(attrs={"class": "form-select"}),
            "destination": forms.Select(attrs={"class": "form-select"}),
            "unload_location": forms.Select(attrs={"class": "form-select"}),
            "load_count": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            
            "first_weight": forms.NumberInput(attrs={"class": "form-control form-control-lg fw-bold text-primary", "id": "id_first_weight", "step": "any"}),
            "second_weight": forms.NumberInput(attrs={"class": "form-control form-control-lg fw-bold text-primary", "id": "id_second_weight", "step": "any"}),
            "sent_weight": forms.NumberInput(attrs={"class": "form-control", "id": "id_sent_weight", "step": "any"}),
            
            "loss_type": forms.Select(attrs={"class": "form-select", "id": "id_loss_type"}),
            "loss_percent": forms.NumberInput(attrs={"class": "form-control", "id": "id_loss_percent", "step": "0.01"}),
            "loss_weight": forms.NumberInput(attrs={"class": "form-control", "id": "id_loss_weight", "step": "any", "readonly": "readonly"}),
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

        if not self.instance.pk:
            self.fields["first_weight_date_jalali"].initial = get_today_jalali()
            self.fields["first_weight_time_str"].initial = datetime.now().strftime("%H:%M")

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

        w1 = cleaned_data.get("first_weight")
        if w1 is None or w1 <= 0:
            self.add_error("first_weight", "وزن اول باید مقداری بزرگتر از صفر باشد.")

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
            "second_weight": forms.NumberInput(attrs={"class": "form-control form-control-lg fw-bold text-success", "id": "id_second_weight", "step": "any", "autofocus": True}),
            "sent_weight": forms.NumberInput(attrs={"class": "form-control", "id": "id_sent_weight", "step": "any"}),
            "loss_type": forms.Select(attrs={"class": "form-select", "id": "id_loss_type"}),
            "loss_percent": forms.NumberInput(attrs={"class": "form-control", "id": "id_loss_percent", "step": "0.01"}),
            "loss_weight": forms.NumberInput(attrs={"class": "form-control", "id": "id_loss_weight", "step": "any", "readonly": "readonly"}),
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
            "license_plate_display", "waybill_number", "origin", "destination", 
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
            "origin": forms.Select(attrs={"class": "form-select"}),
            "destination": forms.Select(attrs={"class": "form-select"}),
            "unload_location": forms.Select(attrs={"class": "form-select"}),
            "load_count": forms.NumberInput(attrs={"class": "form-control"}),
            "first_weight": forms.NumberInput(attrs={"class": "form-control", "step": "any"}),
            "second_weight": forms.NumberInput(attrs={"class": "form-control", "step": "any"}),
            "sent_weight": forms.NumberInput(attrs={"class": "form-control", "step": "any"}),
            "loss_type": forms.Select(attrs={"class": "form-select"}),
            "loss_percent": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "loss_weight": forms.NumberInput(attrs={"class": "form-control", "step": "any"}),
            "is_loss_overridden": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "loss_override_reason": forms.TextInput(attrs={"class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }
