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
