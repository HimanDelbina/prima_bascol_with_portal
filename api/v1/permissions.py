from rest_framework.permissions import BasePermission, SAFE_METHODS
from accounts.models import RoleChoices


class IsAuthenticatedAndActive(BasePermission):
    """Allows access only to authenticated and active users."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_active)


class IsAdminUserOnly(BasePermission):
    """Allows access only to Super Admins and System Admins."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "profile", None)
        return bool(profile and profile.can_manage_settings)


class IsManagerOrAdmin(BasePermission):
    """Allows access to Super Admins, System Admins, and Weighbridge Managers."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "profile", None)
        return bool(profile and profile.is_admin_or_manager)


class IsExecutiveManager(BasePermission):
    """Allows access to executive management roles (CEO, Managers, Reports)."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "profile", None)
        return bool(profile and profile.is_executive_manager)


class CanManageTicket(BasePermission):
    """Allows creating/viewing for operators, but sensitive edits/cancels only for managers."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated and request.user.is_active):
            return False
        profile = getattr(request.user, "profile", None)
        if profile and not profile.is_active:
            return False
        if request.method in SAFE_METHODS or request.user.is_superuser:
            return True
        return bool(profile and profile.role in (
            RoleChoices.SUPER_ADMIN, RoleChoices.SYSTEM_ADMIN,
            RoleChoices.WEIGHBRIDGE_MANAGER, RoleChoices.WEIGHBRIDGE_OPERATOR,
        ))

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        # For sensitive actions, view-level or action-level checks apply
        return True


class CanEditCompletedTicket(BasePermission):
    """Permission required to edit or correct completed weighbridge tickets."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "profile", None)
        return bool(profile and profile.can_edit_completed_ticket)


class CanCancelTicket(BasePermission):
    """Permission required to invalidate/cancel a weighbridge ticket."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "profile", None)
        return bool(profile and profile.can_cancel_ticket)


class CanAccessAudit(BasePermission):
    """Permission required to inspect audit logs."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "profile", None)
        return bool(profile and profile.can_access_audit)


class IsMasterDataAdminOrReadOnly(BasePermission):
    """Authenticated users can read master data; only managers/admins can modify."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "profile", None)
        return bool(profile and profile.is_admin_or_manager)


class CanManageMonitoring(BasePermission):
    """Permission for viewing and managing monitoring alerts and thresholds."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "profile", None)
        return bool(profile and profile.can_view_monitoring)


class CanViewPartyAnalytics(BasePermission):
    """Permission to view party analytics and profile."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "profile", None)
        return bool(profile and profile.is_executive_manager)


class CanViewPartyScore(BasePermission):
    """Permission to view party scores and performance breakdowns."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "profile", None)
        return bool(profile and profile.is_executive_manager)


class CanViewPartyRanking(BasePermission):
    """Permission to view party rankings and peer comparisons."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "profile", None)
        return bool(profile and profile.is_executive_manager)


class CanExportPartyAnalytics(BasePermission):
    """Permission to export party analytics in Excel, CSV, or PDF format."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "profile", None)
        return bool(profile and profile.is_executive_manager)


class CanManagePartyScoringConfig(BasePermission):
    """Permission required to modify party scoring configurations and weights."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            profile = getattr(request.user, "profile", None)
            return bool(request.user.is_superuser or (profile and profile.is_executive_manager))
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "profile", None)
        return bool(profile and profile.can_manage_settings)
