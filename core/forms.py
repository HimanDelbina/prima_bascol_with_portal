from django import forms
from core.models import SystemSetting

class SystemSettingForm(forms.ModelForm):
    class Meta:
        model = SystemSetting
        fields = [
            "company_name", "company_logo", "company_address", "company_phone", "company_email",
            "receipt_header_title", "serial_start_number", "serial_prefix", "weight_unit",
            "decimal_places", "max_tolerance_percent", "max_tolerance_kg",
            "require_waybill", "require_driver", "require_origin", "require_destination", "require_unload_location",
            "default_print_template", "receipt_footer_note", "items_per_page"
        ]
        widgets = {
            "company_name": forms.TextInput(attrs={"class": "form-control"}),
            "company_address": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "company_phone": forms.TextInput(attrs={"class": "form-control"}),
            "company_email": forms.EmailInput(attrs={"class": "form-control"}),
            "receipt_header_title": forms.TextInput(attrs={"class": "form-control"}),
            "serial_start_number": forms.NumberInput(attrs={"class": "form-control"}),
            "serial_prefix": forms.TextInput(attrs={"class": "form-control", "placeholder": "مثلاً WB-"}),
            "weight_unit": forms.TextInput(attrs={"class": "form-control"}),
            "decimal_places": forms.NumberInput(attrs={"class": "form-control"}),
            "max_tolerance_percent": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "max_tolerance_kg": forms.NumberInput(attrs={"class": "form-control", "step": "1"}),
            "require_waybill": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "require_driver": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "require_origin": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "require_destination": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "require_unload_location": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "default_print_template": forms.Select(attrs={"class": "form-select"}),
            "receipt_footer_note": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "items_per_page": forms.NumberInput(attrs={"class": "form-control"}),
        }
