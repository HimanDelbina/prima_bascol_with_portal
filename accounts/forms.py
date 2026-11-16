from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import AuthenticationForm
from accounts.models import UserProfile, RoleChoices
from core.jalali import to_english_digits

class PersianAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="نام کاربری",
        widget=forms.TextInput(attrs={
            "class": "form-control form-control-lg", 
            "placeholder": "نام کاربری خود را وارد کنید", 
            "autofocus": True,
            "autocomplete": "username",
            "id": "login-username"
        })
    )
    password = forms.CharField(
        label="رمز عبور",
        widget=forms.PasswordInput(attrs={
            "class": "form-control form-control-lg", 
            "placeholder": "رمز عبور را وارد کنید",
            "autocomplete": "current-password",
            "id": "login-password"
        })
    )
    remember_me = forms.BooleanField(
        label="مرا به خاطر بسپار",
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input", "id": "remember-me-check"})
    )

class PasswordChangeDirectForm(forms.Form):
    """
    Direct password change requiring username, old password, and new password.
    Can be used by authenticated users or from the login screen.
    """
    username = forms.CharField(
        label="نام کاربری",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "نام کاربری"})
    )
    old_password = forms.CharField(
        label="رمز عبور فعلی",
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "رمز عبور فعلی"})
    )
    new_password = forms.CharField(
        label="رمز عبور جدید",
        min_length=4,
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "رمز عبور جدید (حداقل ۴ کاراکتر)"})
    )
    confirm_password = forms.CharField(
        label="تکرار رمز عبور جدید",
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "تکرار رمز عبور جدید"})
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_user = user
        if user and user.is_authenticated:
            self.fields["username"].initial = user.username
            self.fields["username"].widget.attrs["readonly"] = True
            self.fields["username"].widget.attrs["class"] += " bg-light text-muted"

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get("username", "").strip()
        old_password = cleaned_data.get("old_password")
        new_password = cleaned_data.get("new_password")
        confirm_password = cleaned_data.get("confirm_password")

        if not username or not old_password or not new_password or not confirm_password:
            return cleaned_data

        if self.target_user and self.target_user.is_authenticated:
            user = self.target_user
        else:
            try:
                user = User.objects.get(username__iexact=username)
            except User.DoesNotExist:
                raise forms.ValidationError("کاربری با این نام کاربری در سامانه یافت نشد.")

        if not user.check_password(old_password):
            raise forms.ValidationError("رمز عبور فعلی وارد شده نادرست است.")

        if new_password != confirm_password:
            raise forms.ValidationError("رمز عبور جدید و تکرار آن یکسان نیستند.")

        if old_password == new_password:
            raise forms.ValidationError("رمز عبور جدید نمی‌تواند همانند رمز عبور قبلی باشد.")

        self.user = user
        return cleaned_data

    def save(self):
        self.user.set_password(self.cleaned_data["new_password"])
        self.user.save()
        return self.user

class PasswordResetVerifyForm(forms.Form):
    """
    Password reset using identity verification (username + registered mobile or personnel code).
    """
    username = forms.CharField(
        label="نام کاربری",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "نام کاربری"})
    )
    verification_value = forms.CharField(
        label="شماره موبایل یا کد پرسنلی",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "مثال: 09121000001 یا کد پرسنلی"})
    )
    new_password = forms.CharField(
        label="رمز عبور جدید",
        min_length=4,
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "رمز عبور جدید (حداقل ۴ کاراکتر)"})
    )
    confirm_password = forms.CharField(
        label="تکرار رمز عبور جدید",
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "تکرار رمز عبور جدید"})
    )

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get("username", "").strip()
        raw_val = to_english_digits(cleaned_data.get("verification_value", "")).strip()
        new_password = cleaned_data.get("new_password")
        confirm_password = cleaned_data.get("confirm_password")

        if not username or not raw_val or not new_password or not confirm_password:
            return cleaned_data

        try:
            user = User.objects.select_related("profile").get(username__iexact=username)
        except User.DoesNotExist:
            raise forms.ValidationError("کاربری با این نام کاربری در سامانه یافت نشد.")

        if not user.is_active:
            raise forms.ValidationError("حساب کاربری مورد نظر غیرفعال است. لطفاً با مدیر سیستم تماس بگیرید.")

        profile = getattr(user, "profile", None)
        user_mobile = to_english_digits(profile.mobile or "").strip() if profile else ""
        user_pcode = to_english_digits(profile.personnel_code or "").strip() if profile else ""

        match_mobile = False
        if user_mobile and raw_val:
            val_norm = raw_val.lstrip("0").replace("+98", "").replace("0098", "")
            usr_norm = user_mobile.lstrip("0").replace("+98", "").replace("0098", "")
            if val_norm == usr_norm:
                match_mobile = True

        match_pcode = False
        if user_pcode and raw_val:
            if raw_val.lower() == user_pcode.lower():
                match_pcode = True

        if not (match_mobile or match_pcode):
            raise forms.ValidationError("شماره موبایل یا کد پرسنلی وارد شده با اطلاعات ثبت‌شده این کاربر تطابق ندارد.")

        if new_password != confirm_password:
            raise forms.ValidationError("رمز عبور جدید و تکرار آن یکسان نیستند.")

        self.user = user
        return cleaned_data

    def save(self):
        self.user.set_password(self.cleaned_data["new_password"])
        self.user.save()
        return self.user

class UserForm(forms.ModelForm):
    sso_subject = forms.CharField(
        label="شناسه کاربر در Keycloak (Subject)", max_length=255, required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "dir": "ltr", "autocomplete": "off"}),
    )
    sso_enabled = forms.BooleanField(
        label="پیوند ورود سازمانی فعال باشد", required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    profile_active = forms.BooleanField(
        label="پروفایل عملیاتی فعال باشد", required=False, initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    first_name = forms.CharField(label="نام", required=True, widget=forms.TextInput(attrs={"class": "form-control"}))
    last_name = forms.CharField(label="نام خانوادگی", required=True, widget=forms.TextInput(attrs={"class": "form-control"}))
    email = forms.EmailField(label="ایمیل", required=False, widget=forms.EmailInput(attrs={"class": "form-control"}))
    role = forms.ChoiceField(choices=RoleChoices.choices, label="نقش کاربری", widget=forms.Select(attrs={"class": "form-select"}))
    mobile = forms.CharField(label="شماره موبایل", required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    personnel_code = forms.CharField(label="کد پرسنلی", required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    password = forms.CharField(
        label="رمز عبور", 
        required=False, 
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "برای عدم تغییر، خالی بگذارید"})
    )

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email"]
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, actor=None, identity=None, issuer="", **kwargs):
        super().__init__(*args, **kwargs)
        self.identity = identity
        self.issuer = issuer
        if not actor or not actor.is_superuser:
            self.fields["role"].choices = [
                (code, label) for code, label in RoleChoices.choices
                if code not in ("super_admin", "system_admin")
            ]
        if not issuer:
            del self.fields["sso_subject"]
            del self.fields["sso_enabled"]
        elif identity:
            self.initial.update(sso_subject=identity.subject, sso_enabled=identity.enabled)
        if self.instance and self.instance.pk and hasattr(self.instance, "profile"):
            self.initial["profile_active"] = self.instance.profile.is_active
            self.fields["role"].initial = self.instance.profile.role
            self.fields["mobile"].initial = self.instance.profile.mobile
            self.fields["personnel_code"].initial = self.instance.profile.personnel_code
        if not self.instance.pk:
            self.fields["password"].required = True

    def clean(self):
        values = super().clean()
        if "sso_subject" not in self.fields:
            return values
        subject = values.get("sso_subject")
        if values.get("sso_enabled") and not subject:
            self.add_error("sso_subject", "برای فعال‌کردن پیوند، شناسه کاربر Keycloak را وارد کنید.")
        if subject:
            from accounts.models import BascolIdentity

            existing = BascolIdentity.objects.filter(issuer=self.issuer, subject=subject)
            if self.identity:
                existing = existing.exclude(pk=self.identity.pk)
            if existing.exists():
                self.add_error("sso_subject", "این هویت سازمانی قبلاً به حساب دیگری پیوند داده شده است.")
        return values

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("password")
        if password:
            user.set_password(password)
        if commit:
            user.save()
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = self.cleaned_data.get("role")
            profile.mobile = self.cleaned_data.get("mobile", "")
            profile.personnel_code = self.cleaned_data.get("personnel_code", "")
            profile.is_active = self.cleaned_data["profile_active"]
            profile.save()
        return user
