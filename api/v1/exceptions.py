from rest_framework.views import exception_handler
from rest_framework.exceptions import (
    ValidationError, AuthenticationFailed, NotAuthenticated,
    PermissionDenied, NotFound, MethodNotAllowed, Throttled
)
from rest_framework.response import Response
from rest_framework import status
import logging
from django.core.exceptions import ValidationError as DjangoValidationError

logger = logging.getLogger(__name__)

def custom_exception_handler(exc, context):
    """
    Standardized global exception handler ensuring uniform error response format:
    {
        "success": false,
        "error": {
            "code": "ERROR_CODE",
            "message": "Human readable message",
            "fields": { ... } // optional validation details
        }
    }
    """
    if isinstance(exc, DjangoValidationError):
        exc = ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages)
    response = exception_handler(exc, context)

    if response is not None:
        error_code = "API_ERROR"
        message = "خطایی در پردازش درخواست رخ داد."
        fields = {}

        if isinstance(exc, ValidationError):
            error_code = "VALIDATION_ERROR"
            message = "اطلاعات وارد شده معتبر نمی‌باشد."
            if isinstance(response.data, dict):
                fields = response.data
            elif isinstance(response.data, list):
                fields = {"non_field_errors": response.data}
            else:
                fields = {"detail": [str(response.data)]}

        elif isinstance(exc, (NotAuthenticated, AuthenticationFailed)):
            error_code = "AUTHENTICATION_REQUIRED"
            message = "احراز هویت الزامی است. لطفاً توکن معتبر ارسال نمایید."
            if isinstance(response.data, dict) and "detail" in response.data:
                message = str(response.data["detail"])

        elif isinstance(exc, PermissionDenied):
            error_code = "PERMISSION_DENIED"
            message = "شما دسترسی لازم برای انجام این عملیات را ندارید."
            if isinstance(response.data, dict) and "detail" in response.data:
                message = str(response.data["detail"])

        elif isinstance(exc, NotFound):
            error_code = "NOT_FOUND"
            message = "منبع یا رکورد مورد نظر یافت نشد."

        elif isinstance(exc, MethodNotAllowed):
            error_code = "METHOD_NOT_ALLOWED"
            message = f"متد {context.get('request').method if context.get('request') else ''} مجاز نمی‌باشد."

        elif isinstance(exc, Throttled):
            error_code = "RATE_LIMITED"
            wait_seconds = getattr(exc, 'wait', None)
            message = f"تعداد درخواست‌های شما فراتر از حد مجاز است. لطفاً {wait_seconds or ''} ثانیه دیگر مجدداً تلاش کنید."

        else:
            if isinstance(response.data, dict):
                if "detail" in response.data:
                    message = str(response.data["detail"])
                else:
                    fields = response.data

        custom_data = {
            "success": False,
            "error": {
                "code": error_code,
                "message": message,
            }
        }
        if fields:
            custom_data["error"]["fields"] = fields

        response.data = custom_data

    return response
