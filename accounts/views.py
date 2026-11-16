from django.views.decorators.http import require_POST
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from accounts.forms import (
    PersianAuthenticationForm, 
    UserForm, 
    PasswordChangeDirectForm, 
    PasswordResetVerifyForm
)
from accounts.models import BascolIdentity, UserProfile, RoleChoices
from accounts.decorators import admin_only_required, role_required
from audit.services import log_audit
from audit.models import AuditAction

def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard:index")
    
    if request.method == "POST":
        form = PersianAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            
            # Remember me logic
            if form.cleaned_data.get("remember_me"):
                request.session.set_expiry(1209600)  # 14 days
            else:
                request.session.set_expiry(0)  # On browser close
                
            log_audit(
                action=AuditAction.LOGIN,
                model_name="User",
                record_id=user.id,
                record_repr=f"کاربر {user.username}",
                reason="ورود موفق به سامانه باسکول",
                user=user
            )
            messages.success(request, f"خوش آمدید، {user.get_full_name() or user.username}")
            next_url = request.GET.get("next")
            if next_url and not next_url.startswith("/accounts/logout"):
                return redirect(next_url)
            return redirect("dashboard:index")
        else:
            messages.error(request, "نام کاربری یا رمز عبور اشتباه است.")
    else:
        form = PersianAuthenticationForm()
    
    change_form = PasswordChangeDirectForm()
    reset_form = PasswordResetVerifyForm()
    
    return render(request, "accounts/login.html", {
        "sso_enabled": settings.BASCOL_SSO_ENABLED,
        "form": form,
        "change_form": change_form,
        "reset_form": reset_form,
    })

def password_change_view(request):
    """
    Direct password change view (requires username + current password + new password).
    Accessible to both authenticated users and users at the login page.
    """
    initial_user = request.user if request.user.is_authenticated else None
    
    if request.method == "POST":
        form = PasswordChangeDirectForm(request.POST, user=initial_user)
        if form.is_valid():
            user = form.save()
            if request.user.is_authenticated:
                update_session_auth_hash(request, user)
            
            log_audit(
                action=AuditAction.UPDATE,
                model_name="User",
                record_id=user.id,
                record_repr=f"کاربر {user.username}",
                reason="تغییر موفقیت‌آمیز رمز عبور با اعتبارسنجی رمز قبلی",
                user=user
            )
            messages.success(request, "رمز عبور با موفقیت تغییر یافت. لطفاً با رمز عبور جدید وارد شوید.")
            if request.user.is_authenticated:
                return redirect("accounts:profile")
            return redirect("accounts:login")
        else:
            for error in form.non_field_errors():
                messages.error(request, error)
            for field, err_list in form.errors.items():
                if field != "__all__":
                    for err in err_list:
                        messages.error(request, f"{form.fields[field].label}: {err}")
    else:
        username_query = request.GET.get("username", "")
        initial = {"username": username_query} if username_query else None
        form = PasswordChangeDirectForm(user=initial_user, initial=initial)
        
    return render(request, "accounts/password_change.html", {"form": form})

def password_reset_view(request):
    """
    Identity-verified password reset view (requires username + registered mobile or personnel code).
    For users who forgot their existing password.
    """
    if request.method == "POST":
        form = PasswordResetVerifyForm(request.POST)
        if form.is_valid():
            user = form.save()
            log_audit(
                action=AuditAction.UPDATE,
                model_name="User",
                record_id=user.id,
                record_repr=f"کاربر {user.username}",
                reason="بازیابی موفق رمز عبور با تطبیق شماره موبایل یا کد پرسنلی",
                user=user
            )
            messages.success(request, f"رمز عبور کاربر {user.username} با موفقیت بازنشانی شد. اکنون می‌توانید وارد شوید.")
            return redirect("accounts:login")
        else:
            for error in form.non_field_errors():
                messages.error(request, error)
            for field, err_list in form.errors.items():
                if field != "__all__":
                    for err in err_list:
                        messages.error(request, f"{form.fields[field].label}: {err}")
    else:
        username_query = request.GET.get("username", "")
        initial = {"username": username_query} if username_query else None
        form = PasswordResetVerifyForm(initial=initial)
        
    return render(request, "accounts/password_reset.html", {"form": form})

def logout_view(request):
    if request.user.is_authenticated:
        logout(request)
        messages.info(request, "شما با موفقیت از سیستم خارج شدید.")
    return redirect("accounts:login")

@login_required
def profile_view(request):
    user = request.user
    profile, _ = UserProfile.objects.get_or_create(user=user)
    
    if request.method == "POST":
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        email = request.POST.get("email", "").strip()
        mobile = request.POST.get("mobile", "").strip()
        password = request.POST.get("password", "").strip()
        
        user.first_name = first_name
        user.last_name = last_name
        user.email = email
        if password:
            user.set_password(password)
        user.save()
        
        profile.mobile = mobile
        profile.save()
        
        messages.success(request, "اطلاعات پروفایل شما با موفقیت بروزرسانی شد.")
        return redirect("accounts:profile")
        
    return render(request, "accounts/profile.html", {"user": user, "profile": profile})

def can_manage_identity_links(request):
    return (
        settings.BASCOL_SSO_ENABLED and request.user.is_superuser
        and not request.session.get("bascol_identity_id")
    )


@login_required
@admin_only_required
def user_list_view(request):
    users = User.objects.select_related("profile").order_by("-id")
    show_identity_links = can_manage_identity_links(request)
    if show_identity_links:
        users = users.select_related("bascol_identity")
    return render(request, "accounts/user_list.html", {
        "users": users, "show_identity_links": show_identity_links,
        "oidc_issuer": settings.BASCOL_OIDC_ISSUER,
    })

@login_required
@admin_only_required
def user_create_view(request):
    if request.method == "POST":
        form = UserForm(request.POST, actor=request.user)
        if form.is_valid():
            user = form.save()
            log_audit(
                action=AuditAction.CREATE,
                model_name="User",
                record_id=user.id,
                record_repr=f"کاربر {user.username}",
                new_values={"username": user.username, "role": user.profile.role},
                reason="ایجاد کاربر جدید توسط مدیر"
            )
            messages.success(request, f"کاربر {user.username} با موفقیت ایجاد شد.")
            return redirect("accounts:user_list")
    else:
        form = UserForm(actor=request.user)
    return render(request, "accounts/user_form.html", {"form": form, "title": "افزودن کاربر جدید"})

def require_editable_user(actor, target):
    privileged = target.is_superuser or target.is_staff or (
        getattr(getattr(target, "profile", None), "role", None) in ("super_admin", "system_admin")
    )
    if privileged and not actor.is_superuser:
        raise PermissionDenied()


@login_required
@admin_only_required
def user_edit_view(request, user_id):
    target_user = get_object_or_404(User, id=user_id)
    require_editable_user(request.user, target_user)
    identity = None
    issuer = ""
    if (
        can_manage_identity_links(request)
        and not (target_user.is_superuser or target_user.is_staff)
        and getattr(getattr(target_user, "profile", None), "role", None) not in ("super_admin", "system_admin")
    ):
        identity = BascolIdentity.objects.filter(user=target_user).first()
        if identity is None or identity.issuer == settings.BASCOL_OIDC_ISSUER:
            issuer = settings.BASCOL_OIDC_ISSUER
    form = UserForm(
        request.POST if request.method == "POST" else None,
        instance=target_user, actor=request.user, identity=identity, issuer=issuer,
    )
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                user = form.save()
                if issuer and form.cleaned_data.get("sso_subject"):
                    BascolIdentity.objects.update_or_create(
                        user=user, defaults={
                            "issuer": issuer, "subject": form.cleaned_data["sso_subject"],
                            "enabled": form.cleaned_data["sso_enabled"],
                        },
                    )
                elif issuer and identity is not None:
                    identity.enabled = False
                    identity.save(update_fields=["enabled"])
        except IntegrityError:
            form.add_error(None, "ذخیره انجام نشد. نام کاربری یا شناسه سازمانی تکراری است.")
        else:
            log_audit(
                action=AuditAction.UPDATE,
                model_name="User",
                record_id=user.id,
                record_repr=f"کاربر {user.username}",
                new_values={"username": user.username, "role": user.profile.role},
                reason="ویرایش مشخصات کاربر توسط مدیر"
            )
            messages.success(request, f"مشخصات کاربر {user.username} بروزرسانی شد.")
            return redirect("accounts:user_list")
    return render(request, "accounts/user_form.html", {
        "form": form,
        "title": f"ویرایش کاربر {target_user.username}",
        "target_user": target_user,
        "oidc_issuer": issuer,
    })

@login_required
@admin_only_required
@require_POST
def user_toggle_status_view(request, user_id):
    target_user = get_object_or_404(User, id=user_id)
    require_editable_user(request.user, target_user)
    if target_user == request.user:
        messages.error(request, "شما نمی‌توانید حساب کاربری خود را غیرفعال کنید.")
        return redirect("accounts:user_list")
    
    target_user.is_active = not target_user.is_active
    target_user.save()
    status_text = "فعال" if target_user.is_active else "غیرفعال"
    messages.success(request, f"حساب کاربری {target_user.username} {status_text} شد.")
    return redirect("accounts:user_list")
