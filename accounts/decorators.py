from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.core.exceptions import PermissionDenied

def role_required(*allowed_roles):
    """
    Decorator for views that checks if the user has one of the allowed roles.
    Superusers always pass.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated or not request.user.is_active:
                return redirect("accounts:login")
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            
            profile = getattr(request.user, "profile", None)
            if profile and profile.is_active and profile.role in allowed_roles:
                return view_func(request, *args, **kwargs)
            
            messages.error(request, "شما دسترسی لازم برای مشاهده این بخش را ندارید.")
            return redirect("dashboard:index")
        return _wrapped_view
    return decorator

def manager_or_admin_required(view_func):
    """Decorator requiring Super Admin, System Admin, or Weighbridge Manager role."""
    return role_required("super_admin", "system_admin", "weighbridge_manager")(view_func)

def admin_only_required(view_func):
    """Decorator requiring Super Admin or System Admin."""
    return role_required("super_admin", "system_admin")(view_func)

def management_role_required(view_func):
    """
    Decorator requiring executive management roles:
    Super Admin, System Admin, CEO, Factory Manager, Commercial Manager,
    Financial Manager, Weighbridge Manager, or Report Manager.
    """
    return role_required(
        "super_admin", "system_admin", "ceo", "factory_manager",
        "commercial_manager", "financial_manager", "weighbridge_manager", "report_manager"
    )(view_func)
