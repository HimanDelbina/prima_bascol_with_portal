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
