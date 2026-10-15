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
    Financial Manager, or Report Manager.
    Excludes weighbridge_manager, weighbridge_operator, viewer.
    """
    return role_required(
        "super_admin", "system_admin", "ceo", "factory_manager",
        "commercial_manager", "financial_manager", "report_manager"
    )(view_func)

def monitoring_role_required(view_func):
    """
    Decorator requiring executive management or admin roles for smart monitoring.
    Excludes weighbridge_manager, weighbridge_operator, viewer.
    """
    return role_required(
        "super_admin", "system_admin", "ceo", "factory_manager",
        "commercial_manager", "financial_manager", "report_manager"
    )(view_func)

def discrepancy_approver_required(view_func):
    """
    Decorator requiring supervisor/manager role authorized to approve weighbridge discrepancies:
    Super Admin, System Admin, CEO, Factory Manager, Commercial Manager, Financial Manager, Weighbridge Manager.
    """
    return role_required(
        "super_admin", "system_admin", "ceo", "factory_manager",
        "commercial_manager", "financial_manager", "weighbridge_manager"
    )(view_func)

def audit_role_required(view_func):
    """
    Decorator requiring audit access:
    Super Admin, System Admin, CEO.
    Excludes weighbridge_manager, weighbridge_operator, viewer.
    """
    return role_required("super_admin", "system_admin", "ceo")(view_func)

def weighbridge_role_required(view_func):
    """
    Decorator requiring weighbridge operations access.
    Excludes CEO, Viewer, Financial Manager, Warehouse, Report Manager.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_active:
            return redirect("accounts:login")
        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)
        profile = getattr(request.user, "profile", None)
        if profile and profile.is_active and profile.can_access_weighbridge:
            return view_func(request, *args, **kwargs)
        messages.error(request, "شما دسترسی لازم برای عملیات باسکول را ندارید.")
        return redirect("dashboard:index")
    return _wrapped_view

def masterdata_role_required(view_func):
    """
    Decorator requiring master data access.
    Excludes CEO, Viewer, Financial Manager, Warehouse, Report Manager.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_active:
            return redirect("accounts:login")
        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)
        profile = getattr(request.user, "profile", None)
        if profile and profile.is_active and profile.can_access_masterdata:
            return view_func(request, *args, **kwargs)
        messages.error(request, "شما دسترسی لازم برای اطلاعات پایه را ندارید.")
        return redirect("dashboard:index")
    return _wrapped_view
