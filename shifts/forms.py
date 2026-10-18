from django import forms
from django.contrib.auth.models import User
from django.utils import timezone
from core.jalali import (
    jalali_to_gregorian, format_jalali_date, get_today_jalali,
    get_today_gregorian, format_time_hhmm
)
from shifts.models import (
    WorkShift, ShiftSession, ShiftOperatorAssignment,
    ShiftOperatorRole, ShiftAssignmentStatus
)


class WorkShiftForm(forms.ModelForm):
    valid_from_jalali = forms.CharField(
        label="معتبر از تاریخ (شمسی)",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control text-center", "placeholder": "۱۴۰۵/۰۱/۰۱"})
    )
    valid_until_jalali = forms.CharField(
        label="معتبر تا تاریخ (شمسی)",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control text-center", "placeholder": "۱۴۰۵/۱۲/۲۹"})
    )

    class Meta:
        model = WorkShift
        fields = [
            "name", "code", "start_time", "end_time",
            "allowed_grace_minutes", "is_active", "description"
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "مثال: شیفت صبح"}),
            "code": forms.TextInput(attrs={"class": "form-control", "placeholder": "مثال: SHIFT-MORN"}),
            "start_time": forms.TimeInput(attrs={"class": "form-control text-center", "type": "time"}),
            "end_time": forms.TimeInput(attrs={"class": "form-control text-center", "type": "time"}),
            "allowed_grace_minutes": forms.NumberInput(attrs={"class": "form-control text-center", "min": 0}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            if self.instance.valid_from:
                self.fields["valid_from_jalali"].initial = format_jalali_date(self.instance.valid_from)
            if self.instance.valid_until:
                self.fields["valid_until_jalali"].initial = format_jalali_date(self.instance.valid_until)

    def clean(self):
        cleaned_data = super().clean()
        v_from_j = cleaned_data.get("valid_from_jalali")
        v_until_j = cleaned_data.get("valid_until_jalali")

        if v_from_j:
            g_from = jalali_to_gregorian(v_from_j)
            if not g_from:
                self.add_error("valid_from_jalali", "فرمت تاریخ شروع نامعتبر است.")
            else:
                self.instance.valid_from = g_from
        else:
            self.instance.valid_from = None

        if v_until_j:
            g_until = jalali_to_gregorian(v_until_j)
            if not g_until:
                self.add_error("valid_until_jalali", "فرمت تاریخ پایان نامعتبر است.")
            else:
                self.instance.valid_until = g_until
        else:
            self.instance.valid_until = None

        start_time = cleaned_data.get("start_time")
        end_time = cleaned_data.get("end_time")
        if start_time and end_time and start_time == end_time:
            self.add_error("end_time", "ساعت شروع و پایان شیفت نمی‌تواند یکسان باشد (مدت زمان صفر).")

        return cleaned_data


class ShiftSessionOpenForm(forms.ModelForm):
    operational_date_jalali = forms.CharField(
        label="تاریخ عملیاتی شیفت (شمسی)",
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control text-center"})
    )

    class Meta:
        model = ShiftSession
        fields = ["shift", "initial_scale_zero_ok", "initial_printer_paper_ok", "notes"]
        widgets = {
            "shift": forms.Select(attrs={"class": "form-select"}),
            "initial_scale_zero_ok": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "initial_printer_paper_ok": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "یادداشت‌های زمان بازگشایی..."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["shift"].queryset = WorkShift.objects.filter(is_active=True)
        if not self.initial.get("operational_date_jalali"):
            self.fields["operational_date_jalali"].initial = get_today_jalali()

    def clean(self):
        cleaned_data = super().clean()
        op_date_j = cleaned_data.get("operational_date_jalali")
        if op_date_j:
            g_date = jalali_to_gregorian(op_date_j)
            if not g_date:
                self.add_error("operational_date_jalali", "فرمت تاریخ شمسی وارد شده معتبر نیست.")
            else:
                self.instance.operational_date = g_date

        if not cleaned_data.get("initial_scale_zero_ok"):
            self.add_error("initial_scale_zero_ok", "تایید صفر بودن اولیه باسکول پیش از افتتاح شیفت الزامی است.")
        if not cleaned_data.get("initial_printer_paper_ok"):
            self.add_error("initial_printer_paper_ok", "تایید سلامت چاپگر و وجود رول کاغذ الزامی است.")

        return cleaned_data


class ShiftSessionCloseForm(forms.Form):
    notes = forms.CharField(
        label="یادداشت‌ها و توضیحات پایان شیفت",
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 4, "placeholder": "توضیحات و گزارش وضعیت نهایی شیفت..."})
    )


class ShiftOperatorAssignmentForm(forms.ModelForm):
    class Meta:
        model = ShiftOperatorAssignment
        fields = ["operator", "role"]
        widgets = {
            "operator": forms.Select(attrs={"class": "form-select"}),
            "role": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, session=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = session
        # Limit to users with operator/manager roles
        self.fields["operator"].queryset = User.objects.filter(
            is_active=True,
            profile__role__in=[
                "super_admin", "system_admin", "weighbridge_manager",
                "weighbridge_operator", "factory_manager"
            ]
        ).select_related("profile").order_by("first_name", "last_name", "username")


class ShiftSubstitutionForm(forms.Form):
    replacement_operator = forms.ModelChoiceField(
        queryset=User.objects.none(),
        label="اپراتور جایگزین",
        widget=forms.Select(attrs={"class": "form-select"})
    )
    substitution_reason = forms.CharField(
        label="دلیل و ادله جایگزینی اضطراری",
        min_length=5,
        widget=forms.Textarea(attrs={
            "class": "form-control", "rows": 3,
            "placeholder": "دلایل موجه تعویض اضطراری اپراتور (حداقل ۵ کاراکتر)..."
        })
    )

    def __init__(self, *args, current_operator=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = User.objects.filter(
            is_active=True,
            profile__role__in=[
                "super_admin", "system_admin", "weighbridge_manager",
                "weighbridge_operator", "factory_manager"
            ]
        )
        if current_operator:
            qs = qs.exclude(pk=current_operator.pk)
        self.fields["replacement_operator"].queryset = qs.select_related("profile").order_by("first_name", "username")


class ShiftExceptionAcknowledgeForm(forms.Form):
    acknowledgement_note = forms.CharField(
        label="توضیحات بررسی سرپرست",
        required=True,
        min_length=3,
        widget=forms.Textarea(attrs={
            "class": "form-control", "rows": 3,
            "placeholder": "ملاحظات سرپرست در خصوص ثبت توزین خارج از شیفت..."
        })
    )


# ---------------------------------------------------------
# Phase 4.2 Shift Handover Forms
# ---------------------------------------------------------

class ShiftHandoverInitiateForm(forms.Form):
    incoming_operator = forms.ModelChoiceField(
        label="اپراتور تحویل‌گیرنده (پیشنهادی)",
        queryset=User.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )
    incoming_session = forms.ModelChoiceField(
        label="جلسه شیفت بعدی (اختیاری)",
        queryset=ShiftSession.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )
    scale_zero_confirmed = forms.BooleanField(
        label="تأیید صفر بودن باسکول و حسگرها (اعلام اپراتور)",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"})
    )
    printer_paper_confirmed = forms.BooleanField(
        label="تأیید موجودی کاغذ پرینتر و بارکدخوان (اعلام اپراتور)",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"})
    )
    workstation_clean_confirmed = forms.BooleanField(
        label="تأیید سلامت و پاکیزگی ایستگاه کاری و سیستم توزین",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"})
    )
    physical_documents_confirmed = forms.BooleanField(
        label="تأیید تبادل اسناد فیزیکی، قبوض چاپ‌شده و ژتون‌ها",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"})
    )
    checklist_notes = forms.CharField(
        label="توضیحات تکمیلی چک‌لیست اقلام و تجهیزات",
        required=False,
        widget=forms.Textarea(attrs={
            "class": "form-control", "rows": 2,
            "placeholder": "ملاحظات تجهیزاتی، وضعیت فیزیکی باسکول..."
        })
    )
    outgoing_notes = forms.CharField(
        label="یادداشت‌های عملیاتی اپراتور تحویل‌دهنده",
        required=False,
        widget=forms.Textarea(attrs={
            "class": "form-control", "rows": 3,
            "placeholder": "گزارش وضعیت شیفت، موارد نیازمند پیگیری، شرایط محوطه..."
        })
    )

    def __init__(self, *args, current_operator=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs_users = User.objects.filter(
            is_active=True,
            profile__role__in=[
                "super_admin", "system_admin", "weighbridge_manager",
                "weighbridge_operator", "factory_manager"
            ]
        )
        if current_operator:
            qs_users = qs_users.exclude(pk=current_operator.pk)
        self.fields["incoming_operator"].queryset = qs_users.select_related("profile").order_by("first_name", "username")

        # Active or scheduled sessions for incoming session selection
        self.fields["incoming_session"].queryset = ShiftSession.objects.filter(
            status__in=["ACTIVE", "SCHEDULED"]
        ).select_related("shift").order_by("-operational_date")


class ShiftHandoverAcceptForm(forms.Form):
    incoming_notes = forms.CharField(
        label="یادداشت‌های تکمیلی اپراتور تحویل‌گیرنده",
        required=False,
        widget=forms.Textarea(attrs={
            "class": "form-control", "rows": 3,
            "placeholder": "ملاحظات پذیرش شیفت، تایید صحت اقلام محوطه و اسناد..."
        })
    )


class ShiftHandoverDisputeForm(forms.Form):
    dispute_reason = forms.CharField(
        label="شرح کامل مغایرت یا اختلاف در تحویل شیفت",
        required=True,
        min_length=5,
        widget=forms.Textarea(attrs={
            "class": "form-control is-invalid", "rows": 4,
            "placeholder": "دلایل موجه عدم پذیرش (مثال: عدم تطابق خودرو در محوطه، نقص اسناد، خرابی پرینتر)..."
        })
    )
    incoming_notes = forms.CharField(
        label="توضیحات تکمیلی",
        required=False,
        widget=forms.Textarea(attrs={
            "class": "form-control", "rows": 2,
            "placeholder": "سایر ملاحظات..."
        })
    )


class ShiftHandoverResolveForm(forms.Form):
    ACTION_CHOICES = [
        ("RESOLVE", "حل اختلاف و تأیید نهایی تحویل شیفت (SUPERVISOR_RESOLVED)"),
        ("CANCEL", "لغو فرآیند تحویل شیفت (CANCELLED)"),
    ]
    action = forms.ChoiceField(
        label="تصمیم مدیریتی سرپرست",
        choices=ACTION_CHOICES,
        widget=forms.RadioSelect(attrs={"class": "form-check-input"})
    )
    responsible_operator = forms.ModelChoiceField(
        queryset=User.objects.none(),
        label="اپراتور مسئول نهایی (اختیاری)",
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )
    resolution_notes = forms.CharField(
        label="دستورات، بررسی و ملاحظات سرپرست",
        required=True,
        min_length=5,
        widget=forms.Textarea(attrs={
            "class": "form-control", "rows": 4,
            "placeholder": "دستورات مدیریتی، راستی‌آزمایی فیزیکی محوطه و تعیین تکلیف نهایی تحویل شیفت..."
        })
    )

    def __init__(self, *args, outgoing_operator=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = User.objects.filter(
            is_active=True,
            profile__role__in=[
                "super_admin", "system_admin", "weighbridge_manager",
                "weighbridge_operator", "factory_manager"
            ]
        )
        if outgoing_operator:
            qs = qs.exclude(pk=outgoing_operator.pk)
        self.fields["responsible_operator"].queryset = qs.select_related("profile").order_by("first_name", "username")


class ShiftHandoverSubstituteForm(forms.Form):
    new_incoming_operator = forms.ModelChoiceField(
        queryset=User.objects.none(),
        label="اپراتور جایگزین تحویل‌گیرنده",
        widget=forms.Select(attrs={"class": "form-select"})
    )
    substitution_reason = forms.CharField(
        label="دلیل و ادله جایگزینی اضطراری",
        min_length=5,
        widget=forms.Textarea(attrs={
            "class": "form-control", "rows": 3,
            "placeholder": "دلایل عدم حضور یا جایگزینی اپراتور (حداقل ۵ کاراکتر)..."
        })
    )

    def __init__(self, *args, outgoing_operator=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = User.objects.filter(
            is_active=True,
            profile__role__in=[
                "super_admin", "system_admin", "weighbridge_manager",
                "weighbridge_operator", "factory_manager"
            ]
        )
        if outgoing_operator:
            qs = qs.exclude(pk=outgoing_operator.pk)
        self.fields["new_incoming_operator"].queryset = qs.select_related("profile").order_by("first_name", "username")

