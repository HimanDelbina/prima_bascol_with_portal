from django import forms

from core.jalali import jalali_to_gregorian
from masterdata.models import Party, Product
from weighbridge.models import TicketStatus


def validate_report_params(params):
    errors = {}
    ids = ("operation_type", "product", "party", "driver", "vehicle", "origin", "destination",
           "unload_location", "operator", "first_weight_operator", "second_weight_operator", "loss_type")
    numbers = ("min_loss_pct", "max_loss_pct", "min_gross", "max_gross", "min_tare", "max_tare",
               "min_net", "max_net", "min_final", "max_final", "min_diff", "max_diff")
    for key in (*ids, *numbers, "start_time", "end_time", "per_page"):
        values = params.getlist(key) if hasattr(params, "getlist") else params.get(key, [])
        if not isinstance(values, (list, tuple)):
            values = [values]
        for value in values:
            if value in (None, ""):
                continue
            if key in ids or key == "per_page":
                field = forms.IntegerField(min_value=1, max_value=500 if key == "per_page" else 2147483647)
            elif key in numbers:
                field = forms.DecimalField(max_digits=12, decimal_places=2)
            else:
                field = forms.TimeField()
            try:
                field.clean(value)
            except forms.ValidationError:
                errors[key] = "مقدار فیلتر معتبر نیست."
    dates = {}
    for key in ("start_date", "end_date"):
        if params.get(key):
            dates[key] = jalali_to_gregorian(params[key])
            if dates[key] is None:
                errors[key] = "تاریخ شمسی معتبر وارد کنید."
    if dates.get("start_date") and dates.get("end_date") and dates["start_date"] > dates["end_date"]:
        errors["end_date"] = "تاریخ پایان باید برابر یا بعد از تاریخ شروع باشد."
    if errors:
        raise forms.ValidationError(errors)


class JalaliReportDateField(forms.CharField):
    def to_python(self, value):
        value = super().to_python(value)
        if not value:
            return None
        result = jalali_to_gregorian(value)
        if result is None:
            raise forms.ValidationError("تاریخ شمسی معتبر وارد کنید؛ مانند ۱۴۰۵/۰۶/۲۴.")
        return result


class FreightReportForm(forms.Form):
    start_date = JalaliReportDateField(label="از تاریخ (شمسی)", required=False)
    end_date = JalaliReportDateField(label="تا تاریخ (شمسی)", required=False)
    party = forms.ModelChoiceField(label="طرف حساب", queryset=Party.objects.all(), required=False)
    product = forms.ModelChoiceField(label="محصول", queryset=Product.objects.all(), required=False)
    ticket_number = forms.CharField(label="شماره قبض", max_length=50, required=False)
    waybill_number = forms.CharField(label="شماره بارنامه", max_length=60, required=False)
    plate = forms.CharField(label="پلاک خودرو", max_length=60, required=False)
    driver_search = forms.CharField(label="نام راننده", max_length=150, required=False)
    status = forms.ChoiceField(label="وضعیت قبض", required=False, choices=[
        ("", "همه به‌جز ابطال‌شده"), ("all", "همه (شامل ابطال‌شده)"),
        *TicketStatus.choices,
    ])
    amount_status = forms.ChoiceField(label="وضعیت مبلغ کرایه", required=False, choices=[
        ("", "همه مبالغ"), ("recorded", "مبلغ ثبت‌شده"), ("missing", "بدون مبلغ"),
    ])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs["class"] = "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            if name in ("start_date", "end_date"):
                field.widget.attrs.update({"class": "form-control pdate-picker", "placeholder": "۱۴۰۵/۰۶/۲۴"})
            elif name == "ticket_number":
                field.widget.attrs.update({"placeholder": "مثال: 1001"})
            elif name == "waybill_number":
                field.widget.attrs.update({"placeholder": "شماره بارنامه..."})

    def clean(self):
        data = super().clean()
        start, end = data.get("start_date"), data.get("end_date")
        if start and end and start > end:
            self.add_error("end_date", "تاریخ پایان باید برابر یا بعد از تاریخ شروع باشد.")
        return data
