from django import forms
from masterdata.models import (
    Product, Party, Driver, VehicleType, Vehicle, 
    Location, UnloadLocation, OperationType, LossType
)

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "code", "standard_tolerance_kg", "default_loss_percent", "description", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "مثلاً آهن اسفنجی"}),
            "code": forms.TextInput(attrs={"class": "form-control", "placeholder": "مثلاً PRD-101"}),
            "standard_tolerance_kg": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "default_loss_percent": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

class PartyForm(forms.ModelForm):
    class Meta:
        model = Party
        fields = ["name", "code", "party_type", "phone", "tel", "email", "address", "national_id", "economic_code", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "نام شرکت یا شخص"}),
            "code": forms.TextInput(attrs={"class": "form-control"}),
            "party_type": forms.Select(attrs={"class": "form-select"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "tel": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "national_id": forms.TextInput(attrs={"class": "form-control"}),
            "economic_code": forms.TextInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

class DriverForm(forms.ModelForm):
    class Meta:
        model = Driver
        fields = ["full_name", "mobile", "national_code", "license_number", "description", "is_active"]
        widgets = {
            "full_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "نام و نام خانوادگی"}),
            "mobile": forms.TextInput(attrs={"class": "form-control", "placeholder": "۰۹۱۲۳۴۵۶۷۸۹"}),
            "national_code": forms.TextInput(attrs={"class": "form-control"}),
            "license_number": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

class VehicleTypeForm(forms.ModelForm):
    class Meta:
        model = VehicleType
        fields = ["name", "code", "standard_tare_weight", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "مثلاً تریلی ۱۸ چرخ / کمپرسی"}),
            "code": forms.TextInput(attrs={"class": "form-control"}),
            "standard_tare_weight": forms.NumberInput(attrs={"class": "form-control", "step": "any"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

from core.constants import IRAN_PLATE_LETTERS

class VehicleForm(forms.ModelForm):
    plate_letter = forms.ChoiceField(
        choices=IRAN_PLATE_LETTERS,
        required=False,
        widget=forms.Select(attrs={
            "class": "iran-plate-letter-select",
            "id": "id_plate_letter",
        })
    )
    plate_display = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control bg-light font-monospace fw-bold",
            "id": "id_plate_display",
            "placeholder": "شماره کامل پلاک پس از ورود اجزا محاسبه می‌شود"
        })
    )

    class Meta:
        model = Vehicle
        fields = [
            "plate_part1", "plate_letter", "plate_part2", "plate_iran", 
            "plate_display", "vehicle_type", "default_driver", "empty_weight", "description", "is_active"
        ]
        widgets = {
            "plate_part1": forms.TextInput(attrs={"class": "iran-plate-input-part1", "maxlength": "2", "id": "id_plate_part1", "placeholder": "12", "autocomplete": "off"}),
            "plate_part2": forms.TextInput(attrs={"class": "iran-plate-input-part2", "maxlength": "3", "id": "id_plate_part2", "placeholder": "345", "autocomplete": "off"}),
            "plate_iran": forms.TextInput(attrs={"class": "iran-plate-iran", "maxlength": "2", "id": "id_plate_iran", "placeholder": "64", "autocomplete": "off"}),
            "vehicle_type": forms.Select(attrs={"class": "form-select"}),
            "default_driver": forms.Select(attrs={"class": "form-select"}),
            "empty_weight": forms.NumberInput(attrs={"class": "form-control", "step": "any", "placeholder": "0.00"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "توضیحات و یادداشت‌ها..."}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        p1 = (cleaned_data.get("plate_part1") or "").strip()
        pL = (cleaned_data.get("plate_letter") or "").strip()
        p2 = (cleaned_data.get("plate_part2") or "").strip()
        pI = (cleaned_data.get("plate_iran") or "").strip()
        pDisp = (cleaned_data.get("plate_display") or "").strip()

        if p1 and pL and p2 and pI:
            cleaned_data["plate_display"] = f"{p1} {pL} {p2} - ایران {pI}"
        elif pDisp:
            cleaned_data["plate_display"] = pDisp
        else:
            cleaned_data["plate_display"] = "بدون پلاک"
        return cleaned_data



class LocationForm(forms.ModelForm):
    class Meta:
        model = Location
        fields = ["name", "location_type", "description", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "نام شهر یا کارخانه"}),
            "location_type": forms.Select(attrs={"class": "form-select"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

class UnloadLocationForm(forms.ModelForm):
    class Meta:
        model = UnloadLocation
        fields = ["name", "code", "description", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "مثلاً انبار مرکزی / سالن شماره ۲"}),
            "code": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

class OperationTypeForm(forms.ModelForm):
    class Meta:
        model = OperationType
        fields = ["name", "code", "direction", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "مثلاً خرید وارده"}),
            "code": forms.TextInput(attrs={"class": "form-control"}),
            "direction": forms.Select(attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

class LossTypeForm(forms.ModelForm):
    class Meta:
        model = LossType
        fields = ["name", "code", "default_percent", "description", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "مثلاً افت رطوبت"}),
            "code": forms.TextInput(attrs={"class": "form-control"}),
            "default_percent": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
