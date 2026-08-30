from django import forms
from monitoring.models import MonitoringAlert, MonitoringRuleConfig, AlertStatus, AlertSeverity, AlertType
from masterdata.models import Product, Party, Vehicle


class MonitoringRuleConfigForm(forms.ModelForm):
    class Meta:
        model = MonitoringRuleConfig
        fields = [
            "enabled",
            "warning_threshold",
            "high_threshold",
            "critical_threshold",
            "percentage_warning",
            "percentage_high",
            "percentage_critical",
            "minimum_history",
        ]
        widgets = {
            "enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "warning_threshold": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "high_threshold": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "critical_threshold": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "percentage_warning": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "percentage_high": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "percentage_critical": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "minimum_history": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
        }


class AlertResolveForm(forms.Form):
    """
    Form for taking action on a monitoring alert (Resolve, Review, Ignore).
    Mandatory resolution note is enforced.
    """
    action_type = forms.ChoiceField(
        choices=[
            (AlertStatus.RESOLVED, "حل شد / اقدام اصلاحی انجام شد (Resolved)"),
            (AlertStatus.REVIEWED, "بررسی شد و تایید گردید (Reviewed)"),
            (AlertStatus.IGNORED, "مورد خاص و نادیده گرفته شد (Ignored)"),
        ],
        widget=forms.Select(attrs={"class": "form-select fw-bold mb-3"}),
        label="اقدام مدیریتی"
    )
    resolution_note = forms.CharField(
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "rows": 3,
            "placeholder": "ثبت شرح کامل اقدام، بررسی میدانی یا دلیل تایید/رد هشدار الزامی است..."
        }),
        label="شرح اقدام و یادداشت",
        required=True
    )

    def clean_resolution_note(self):
        note = self.cleaned_data.get("resolution_note", "").strip()
        if not note or len(note) < 5:
            raise forms.ValidationError("وارد کردن یادداشت و شرح اقدام با حداقل ۵ کاراکتر الزامی است.")
        return note


class AlertFilterForm(forms.Form):
    """
    Comprehensive filter form for Alert Center and Reports.
    """
    q = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "شماره قبض، پلاک، راننده، طرف حساب..."
        })
    )
    alert_type = forms.ChoiceField(
        required=False,
        choices=[("", "همه انواع هشدارها")] + list(AlertType.choices),
        widget=forms.Select(attrs={"class": "form-select"})
    )
    severity = forms.ChoiceField(
        required=False,
        choices=[("", "همه سطوح اهمیت")] + list(AlertSeverity.choices),
        widget=forms.Select(attrs={"class": "form-select"})
    )
    status = forms.ChoiceField(
        required=False,
        choices=[("", "همه وضعیت‌ها")] + list(AlertStatus.choices),
        widget=forms.Select(attrs={"class": "form-select"})
    )
    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(is_active=True),
        required=False,
        empty_label="همه محصولات",
        widget=forms.Select(attrs={"class": "form-select"})
    )
    party = forms.ModelChoiceField(
        queryset=Party.objects.filter(is_active=True),
        required=False,
        empty_label="همه طرف‌های حساب",
        widget=forms.Select(attrs={"class": "form-select"})
    )
    start_date = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "1405/01/01"})
    )
    end_date = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "1405/12/29"})
    )
