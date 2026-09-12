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
            "class": "form-select text-center iran-plate-part iran-plate-letter",
            "id": "id_plate_letter",
        })
    )

    class Meta:
        model = Vehicle
        fields = [
            "plate_part1", "plate_letter", "plate_part2", "plate_iran", 
            "plate_display", "vehicle_type", "default_driver", "empty_weight", "description", "is_active"
        ]
        widgets = {
            "plate_part1": forms.TextInput(attrs={"class": "form-control text-center iran-plate-part iran-plate-part1", "maxlength": "2", "id": "id_plate_part1"}),
            "plate_part2": forms.TextInput(attrs={"class": "form-control text-center iran-plate-part iran-plate-part2", "maxlength": "3", "id": "id_plate_part2"}),
            "plate_iran": forms.TextInput(attrs={"class": "form-control text-center iran-plate-part iran-plate-iran", "maxlength": "2", "id": "id_plate_iran"}),
            "plate_display": forms.TextInput(attrs={"class": "form-control", "id": "id_plate_display"}),
            "vehicle_type": forms.Select(attrs={"class": "form-select"}),
            "default_driver": forms.Select(attrs={"class": "form-select"}),
            "empty_weight": forms.NumberInput(attrs={"class": "form-control", "step": "any"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


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
