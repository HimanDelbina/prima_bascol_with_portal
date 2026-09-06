from rest_framework import viewsets, filters, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth.models import User
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view

from accounts.models import RoleChoices
from api.v1.serializers.user_serializers import UserAdminSerializer, RoleSerializer
from api.v1.permissions import IsAdminUserOnly


@extend_schema_view(
    list=extend_schema(tags=['Users'], summary='لیست کاربران سیستم'),
    retrieve=extend_schema(tags=['Users'], summary='مشاهده کاربر'),
    create=extend_schema(tags=['Users'], summary='ایجاد کاربر جدید با تعیین نقش'),
    update=extend_schema(tags=['Users'], summary='ویرایش کامل کاربر'),
    partial_update=extend_schema(tags=['Users'], summary='ویرایش جزیی کاربر'),
    destroy=extend_schema(tags=['Users'], summary='حذف کاربر'),
)
class UserViewSet(viewsets.ModelViewSet):
    """
    مدیریت کاربران و انتساب نقش‌ها توسط مدیر سیستم.
    """
    queryset = User.objects.select_related('profile').all().order_by('id')
    serializer_class = UserAdminSerializer
    permission_classes = [IsAdminUserOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active', 'profile__role']
    search_fields = ['username', 'first_name', 'last_name', 'email', 'profile__mobile', 'profile__personnel_code']
    ordering_fields = ['id', 'username', 'date_joined', 'last_login']

    def perform_create(self, serializer):
        user = serializer.save()
        try:
            from audit.services import log_audit
            from audit.models import AuditAction
            from api.v1.utils import get_client_ip
            role = getattr(getattr(user, 'profile', None), 'role', 'viewer')
            log_audit(
                action=AuditAction.CREATE,
                model_name="User",
                record_id=user.id,
                record_repr=f"کاربر {user.username} (نقش: {role})",
                new_values={"username": user.username, "role": role, "is_active": user.is_active},
                reason="ایجاد کاربر جدید در سامانه",
                user=self.request.user,
                ip_address=get_client_ip(self.request),
                source="API"
            )
        except Exception:
            pass

    def perform_update(self, serializer):
        user = self.get_object()
        old_role = getattr(getattr(user, 'profile', None), 'role', 'viewer')
        old_active = user.is_active
        updated_user = serializer.save()
        new_role = getattr(getattr(updated_user, 'profile', None), 'role', 'viewer')
        new_active = updated_user.is_active
        try:
            from audit.services import log_audit
            from audit.models import AuditAction
            from api.v1.utils import get_client_ip
            log_audit(
                action=AuditAction.UPDATE,
                model_name="User",
                record_id=updated_user.id,
                record_repr=f"کاربر {updated_user.username}",
                old_values={"role": old_role, "is_active": old_active},
                new_values={"role": new_role, "is_active": new_active},
                reason="تغییر مشخصات، نقش یا دسترسی‌های کاربر",
                user=self.request.user,
                ip_address=get_client_ip(self.request),
                source="API"
            )
        except Exception:
            pass

    def perform_destroy(self, instance):
        try:
            from audit.services import log_audit
            from audit.models import AuditAction
            from api.v1.utils import get_client_ip
            log_audit(
                action=AuditAction.DELETE,
                model_name="User",
                record_id=instance.id,
                record_repr=f"کاربر {instance.username}",
                old_values={"username": instance.username, "is_active": instance.is_active},
                reason="حذف حساب کاربر از سامانه",
                user=self.request.user,
                ip_address=get_client_ip(self.request),
                source="API"
            )
        except Exception:
            pass
        instance.delete()


class RoleListView(APIView):
    """
    لیست نقش‌های استاندارد و پیش‌فرض تعریف‌شده در سامانه.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Users'],
        summary='لیست نقش‌های کاربری سیستم',
        description='دریافت کدهای استاندارد و عناوین فارسی نقش‌های کاربری.',
        responses={200: RoleSerializer(many=True)}
    )
    def get(self, request):
        roles = [
            {"code": choice.value, "label": choice.label}
            for choice in RoleChoices
        ]
        return Response(roles)
