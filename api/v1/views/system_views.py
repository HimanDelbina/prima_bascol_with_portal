from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.db import connection
from django.utils import timezone
from drf_spectacular.utils import extend_schema

from core.models import SystemSetting
from api.v1.serializers.system_serializers import (
    PublicSystemSettingSerializer, AdminSystemSettingSerializer,
    HealthCheckSerializer, MetaSerializer
)
from api.v1.permissions import IsAdminUserOnly
from api.v1.utils import api_success_response


class PublicSettingsView(APIView):
    """
    دریافت تنظیمات عمومی و غیرحساس سیستم (نام شرکت، واحد وزن، پیشوند و الگوی چاپ).
    """
    permission_classes = [AllowAny]

    @extend_schema(
        tags=['System Settings'],
        summary='تنظیمات عمومی سامانه',
        description='دریافت متغیرهای عمومی و غیرحساس مورد نیاز کلاینت‌های موبایل، وب و تبلت اپراتور.',
        responses={200: PublicSystemSettingSerializer}
    )
    def get(self, request):
        settings_obj = SystemSetting.get_settings()
        serializer = PublicSystemSettingSerializer(settings_obj)
        return Response(serializer.data)


class AdminSettingsView(APIView):
    """
    مشاهده و ویرایش کلیه تنظیمات سیستمی (محدود به مدیر ارشد و مدیر سیستم).
    """
    permission_classes = [IsAdminUserOnly]

    @extend_schema(
        tags=['System Settings'],
        summary='تنظیمات مدیریتی سامانه (ادمین)',
        description='دریافت کلیه پارامترها و آستانه‌های سامانه.',
        responses={200: AdminSystemSettingSerializer}
    )
    def get(self, request):
        settings_obj = SystemSetting.get_settings()
        serializer = AdminSystemSettingSerializer(settings_obj)
        return Response(serializer.data)

    @extend_schema(
        tags=['System Settings'],
        summary='ویرایش تنظیمات مدیریتی (ادمین)',
        description='ویرایش آستانه‌های انحراف، پیشوند سریال و الزامات فرم‌ها.',
        request=AdminSystemSettingSerializer,
        responses={200: AdminSystemSettingSerializer}
    )
    def patch(self, request):
        settings_obj = SystemSetting.get_settings()
        serializer = AdminSystemSettingSerializer(settings_obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return api_success_response(data=serializer.data, message="تنظیمات سامانه با موفقیت بروزرسانی شد.")


class HealthCheckView(APIView):
    """
    بررسی سلامت سرویس و اتصال به پایگاه داده PostgreSQL.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        tags=['System Settings'],
        summary='بررسی سلامت سرویس (Health Check)',
        description='تست اتصال به پایگاه داده و در دسترس بودن سرور بدون افشای اطلاعات حساس.',
        responses={200: HealthCheckSerializer}
    )
    def get(self, request):
        db_status = "ok"
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                row = cursor.fetchone()
                if not row or row[0] != 1:
                    db_status = "unhealthy"
        except Exception:
            db_status = "disconnected"

        data = {
            "status": "ok" if db_status == "ok" else "error",
            "database": db_status,
            "timestamp": timezone.now().isoformat(),
        }
        return Response(data)


class MetaView(APIView):
    """
    اطلاعات نسخه API، سیستم، تایم‌زون و واحد استاندارد وزن.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        tags=['System Settings'],
        summary='متادیتای API',
        description='مشخصات نسخه جاری API، نام سامانه و تنظیمات بومی‌سازی.',
        responses={200: MetaSerializer}
    )
    def get(self, request):
        settings_obj = SystemSetting.get_settings()
        return Response({
            "api_version": "v1.0.0",
            "application_name": "Prima Bascol Weighbridge Management System",
            "application_version": "1.0.0",
            "timezone": "Asia/Tehran",
            "weight_unit": settings_obj.weight_unit or "کیلوگرم",
        })
