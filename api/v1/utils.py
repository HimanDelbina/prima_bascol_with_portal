from rest_framework.response import Response
from rest_framework import status
from core.jalali import format_jalali_date, format_jalali_datetime


def api_success_response(data=None, message="عملیات با موفقیت انجام شد.", status_code=status.HTTP_200_OK):
    """
    Standardized success envelope for action endpoints:
    {
        "success": true,
        "message": "...",
        "data": { ... }
    }
    """
    payload = {
        "success": True,
        "message": message,
    }
    if data is not None:
        payload["data"] = data
    return Response(payload, status=status_code)


def format_choice_field(code, label):
    """Format an enum/choice into machine code & human readable label."""
    if not code:
        return None
    return {
        "code": code,
        "label": label or code
    }


def get_client_ip(request):
    """Safely extract client IP from request."""
    if not request:
        return None
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip
