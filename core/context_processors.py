from core.models import SystemSetting
from core.jalali import get_today_jalali, to_persian_digits
from datetime import datetime

def global_context(request):
    """Context processor for settings, Persian date/time, and user role."""
    settings_obj = SystemSetting.get_settings()
    now = datetime.now()
    
    user_role = "مهمان"
    user_role_code = "guest"
    if request.user.is_authenticated:
        if request.user.is_superuser:
            user_role = "مدیر ارشد (Super Admin)"
            user_role_code = "super_admin"
        elif hasattr(request.user, "profile"):
            user_role = request.user.profile.get_role_display()
            user_role_code = request.user.profile.role
        elif request.user.is_staff:
            user_role = "مدیر سیستم"
            user_role_code = "system_admin"
        else:
            user_role = "کاربر عادی"
            user_role_code = "viewer"

    return {
        "sys_settings": settings_obj,
        "today_jalali": get_today_jalali(),
        "today_jalali_persian_digits": to_persian_digits(get_today_jalali()),
        "current_time_str": now.strftime("%H:%M"),
        "user_role_display": user_role,
        "user_role_code": user_role_code,
    }
