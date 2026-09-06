from api.v1.throttling import PasswordReauthThrottle
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.views import (
    TokenObtainPairView, TokenRefreshView, TokenVerifyView
)
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from drf_spectacular.utils import extend_schema, OpenApiResponse

from api.v1.serializers.auth_serializers import (
    CustomTokenObtainPairSerializer, UserMeSerializer
)
from api.v1.utils import api_success_response


class CustomTokenObtainPairView(TokenObtainPairView):
    """
    دریافت توکن احراز هویت JWT (Access و Refresh) با نام کاربری و رمز عبور.
    """
    serializer_class = CustomTokenObtainPairSerializer
    throttle_scope = 'auth'

    @extend_schema(
        tags=['Authentication'],
        summary='دریافت توکن JWT (لاگین)',
        description='ورود به سامانه با نام کاربری و رمز عبور و دریافت Access Token و Refresh Token به همراه مشخصات و دسترسی‌های کاربر.',
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class CustomTokenRefreshView(TokenRefreshView):
    """
    تمدید Access Token با استفاده از Refresh Token معتبر.
    """
    throttle_scope = 'auth'

    @extend_schema(
        tags=['Authentication'],
        summary='تمدید Access Token',
        description='ارسال refresh token جهت دریافت access token جدید بدون نیاز به ورود مجدد.',
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class CustomTokenVerifyView(TokenVerifyView):
    """
    بررسی اعتبار و زنده بودن توکن JWT.
    """
    throttle_scope = 'auth'

    @extend_schema(
        tags=['Authentication'],
        summary='اعتبارسنجی توکن',
        description='بررسی صحت و عدم انقضای توکن ارسالی.',
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class LogoutView(APIView):
    """
    خروج از سامانه و ابطال (Blacklist) کردن Refresh Token.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Authentication'],
        summary='خروج از سامانه (Logout)',
        description='ابطال Refresh Token و قرار دادن آن در لیست سیاه جهت جلوگیری از استفاده مجدد.',
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'refresh': {'type': 'string', 'description': 'توکن رفرش جاری'}
                },
                'required': ['refresh']
            }
        },
        responses={
            200: OpenApiResponse(description='خروج با موفقیت انجام شد.'),
            400: OpenApiResponse(description='توکن نامعتبر است.')
        }
    )
    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "ارسال فیلد refresh الزامی است."
                    }
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
            return api_success_response(message="خروج با موفقیت انجام شد و توکن ابطال گردید.")
        except TokenError as e:
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "INVALID_TOKEN",
                        "message": f"توکن نامعتبر است یا قبلاً منقضی شده است: {str(e)}"
                    }
                },
                status=status.HTTP_400_BAD_REQUEST
            )


class CurrentUserView(APIView):
    """
    دریافت اطلاعات، نقش و ماتریس دسترسی‌های کاربر احراز هویت شده جاری.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Authentication'],
        summary='مشخصات کاربر جاری (/me)',
        description='دریافت اطلاعات پروفایل، نقش، شماره پرسنلی و لیست مجوزهای مجاز کاربر فعلی.',
        responses={200: UserMeSerializer}
    )
    def get(self, request):
        serializer = UserMeSerializer(request.user)
        return Response(serializer.data)


class VerifyPasswordView(APIView):
    """
    اعتبارسنجی رمز عبور کاربر لاگین‌شده برای Re-authentication و عملیات حساس.
    - فقط برای کاربر لاگین‌شده (IsAuthenticated)
    - دارای محدودیت نرخ اختصاصی (password_reauth: 5/min)
    - ثبت رویداد امنیتی در سرور بدون ذخیره کلمه عبور، توکن یا اطلاعات هدر
    - بدون برگرداندن هیچ توکن جدیدی
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [PasswordReauthThrottle]
    throttle_scope = 'password_reauth'

    @extend_schema(
        tags=['Authentication'],
        summary='اعتبارسنجی رمز عبور جهت عملیات حساس',
        description='بررسی رمز عبور فعلی کاربر بدون ایجاد توکن جدید جهت تایید هویت مجدد.',
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'password': {'type': 'string', 'description': 'رمز عبور کاربر'}
                },
                'required': ['password']
            }
        },
        responses={
            200: OpenApiResponse(description='نتیجه بررسی رمز عبور (valid: true/false)')
        }
    )
    def post(self, request):
        password = request.data.get('password')
        if not password:
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "فیلد رمز عبور الزامی است."
                    }
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        is_valid = request.user.check_password(password)

        if not is_valid:
            try:
                from audit.services import log_audit
                from audit.models import AuditAction
                from api.v1.utils import get_client_ip
                log_audit(
                    action=AuditAction.UPDATE,
                    model_name="UserSecurity",
                    record_id=request.user.id,
                    record_repr=f"کاربر {request.user.username}",
                    old_values={},
                    new_values={"reauth_status": "failed"},
                    reason="شکست در تایید مجدد رمز عبور (Re-authentication Failed)",
                    user=request.user,
                    ip_address=get_client_ip(request),
                    source="API"
                )
            except Exception:
                pass

        return Response({
            "success": True,
            "valid": is_valid
        }, status=status.HTTP_200_OK)
