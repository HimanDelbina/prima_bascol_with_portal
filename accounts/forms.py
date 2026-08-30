from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import AuthenticationForm
from accounts.models import UserProfile, RoleChoices

class PersianAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="نام کاربری",
        widget=forms.TextInput(attrs={"class": "form-control form-control-lg", "placeholder": "نام کاربری خود را وارد کنید", "autofocus": True})
    )
    password = forms.CharField(
        label="رمز عبور",
        widget=forms.PasswordInput(attrs={"class": "form-control form-control-lg", "placeholder": "رمز عبور"})
    )

class UserForm(forms.ModelForm):
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and hasattr(self.instance, "profile"):
            self.fields["role"].initial = self.instance.profile.role
            self.fields["mobile"].initial = self.instance.profile.mobile
            self.fields["personnel_code"].initial = self.instance.profile.personnel_code
        if not self.instance.pk:
            self.fields["password"].required = True

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
            profile.save()
        return user
