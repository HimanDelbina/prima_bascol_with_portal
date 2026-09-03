from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth.models import User
from accounts.models import UserProfile, RoleChoices
from api.v1.utils import format_choice_field


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Custom JWT Token Obtain Serializer adding rich user profile and role info to login response.
    """
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Custom claims
        token['username'] = user.username
        profile = getattr(user, 'profile', None)
        token['role'] = profile.role if profile else ('super_admin' if user.is_superuser else 'viewer')
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        user = self.user
        profile = getattr(user, 'profile', None)

        role_code = profile.role if profile else ('super_admin' if user.is_superuser else 'viewer')
        role_label = profile.get_role_display() if profile else ('مدیر ارشد' if user.is_superuser else 'مشاهده‌گر')

        permissions = get_user_permissions_list(user, profile)

        data['user'] = {
            'id': user.id,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'full_name': user.get_full_name() or user.username,
            'role': {
                'code': role_code,
                'label': role_label
            },
            'permissions': permissions,
            'is_active': user.is_active,
        }
        return data


def get_user_permissions_list(user, profile=None) -> list[str]:
    """Compile exhaustive list of permission strings based on user role and properties."""
    perms = [
        "ticket.view",
        "masterdata.view",
        "dashboard.view",
    ]
    if not user.is_authenticated:
        return []

    if user.is_superuser:
        return [
            "ticket.create", "ticket.view", "ticket.first_weight", "ticket.second_weight",
            "ticket.complete", "ticket.cancel", "ticket.edit_completed",
            "masterdata.view", "masterdata.manage",
            "dashboard.view", "management.view",
            "monitoring.view", "monitoring.review", "monitoring.resolve", "monitoring.ignore", "monitoring.manage",
            "reports.view", "reports.export",
            "audit.view",
            "users.view", "users.manage",
            "settings.view", "settings.manage",
        ]

    if not profile:
        profile = getattr(user, 'profile', None)

    role = profile.role if profile else 'viewer'

    if role in [RoleChoices.SUPER_ADMIN, RoleChoices.SYSTEM_ADMIN]:
        perms += [
            "ticket.create", "ticket.first_weight", "ticket.second_weight",
            "ticket.complete", "ticket.cancel", "ticket.edit_completed",
            "masterdata.manage", "management.view",
            "monitoring.view", "monitoring.review", "monitoring.resolve", "monitoring.ignore", "monitoring.manage",
            "reports.view", "reports.export", "audit.view",
            "users.view", "users.manage", "settings.view", "settings.manage",
        ]
    elif role == RoleChoices.WEIGHBRIDGE_MANAGER:
        perms += [
            "ticket.create", "ticket.first_weight", "ticket.second_weight",
            "ticket.complete", "ticket.cancel", "ticket.edit_completed",
            "masterdata.manage", "management.view",
            "monitoring.view", "monitoring.review", "monitoring.resolve", "monitoring.ignore",
            "reports.view", "reports.export", "audit.view",
        ]
    elif role == RoleChoices.WEIGHBRIDGE_OPERATOR:
        perms += [
            "ticket.create", "ticket.first_weight", "ticket.second_weight",
            "ticket.complete", "monitoring.view", "reports.view", "reports.export",
        ]
    elif role == RoleChoices.REPORT_MANAGER:
        perms += [
            "management.view", "monitoring.view", "reports.view", "reports.export",
        ]
    elif role in [RoleChoices.CEO, RoleChoices.FACTORY_MANAGER, RoleChoices.COMMERCIAL_MANAGER, RoleChoices.FINANCIAL_MANAGER]:
        perms += [
            "management.view", "monitoring.view", "reports.view", "reports.export", "audit.view",
        ]
    elif role == RoleChoices.VIEWER:
        perms += [
            "reports.view",
        ]

    return list(sorted(set(perms)))


class UserMeSerializer(serializers.ModelSerializer):
    """Serializer representing current authenticated user."""
    full_name = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    mobile = serializers.SerializerMethodField()
    personnel_code = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name', 'full_name',
            'email', 'role', 'mobile', 'personnel_code', 'permissions', 'is_active',
        ]
        read_only_fields = fields

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username

    def get_role(self, obj):
        profile = getattr(obj, 'profile', None)
        if profile:
            return format_choice_field(profile.role, profile.get_role_display())
        return format_choice_field('super_admin' if obj.is_superuser else 'viewer', 'مدیر ارشد' if obj.is_superuser else 'مشاهده‌گر')

    def get_mobile(self, obj):
        profile = getattr(obj, 'profile', None)
        return profile.mobile if profile else ""

    def get_personnel_code(self, obj):
        profile = getattr(obj, 'profile', None)
        return profile.personnel_code if profile else ""

    def get_permissions(self, obj):
        return get_user_permissions_list(obj)
