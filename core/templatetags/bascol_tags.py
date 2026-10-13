from django import template
from django.utils.safestring import mark_safe
from decimal import Decimal
from core.jalali import format_jalali_date, format_jalali_datetime, format_time_hhmm, to_persian_digits

register = template.Library()

@register.filter(name="jdate")
def jdate(value, fmt="%Y/%m/%d"):
    """Format date to Jalali string."""
    return format_jalali_date(value, fmt)

@register.filter(name="jdatetime")
def jdatetime(value, fmt="%Y/%m/%d %H:%M"):
    """Format datetime to Jalali datetime string."""
    return format_jalali_datetime(value, fmt)

@register.filter(name="hhmm")
def hhmm(value):
    """Format time to HH:MM."""
    return format_time_hhmm(value)

@register.filter(name="pdigits")
def pdigits(value):
    """Convert digits to Persian digits."""
    return to_persian_digits(value)

@register.filter(name="weight_fmt")
def weight_fmt(value, decimals=None):
    """Format weight with comma separator and preserve decimals if present."""
    if value is None or value == "":
        return "-"
    try:
        dec = Decimal(str(value))
        if decimals is not None and str(decimals).strip() != "":
            d_int = int(decimals)
            if d_int == 0:
                return f"{int(round(dec)):,}"
            return f"{dec:,.{d_int}f}"
        
        # If integer
        if dec % 1 == 0:
            return f"{int(dec):,}"
        else:
            # Format with 2 decimals without trailing zeros
            formatted = f"{dec:,.2f}".rstrip("0").rstrip(".")
            return formatted
    except Exception:
        return str(value)

@register.filter(name="weight_ton")
def weight_ton(value, decimals=2):
    """Convert weight in Kg to Ton and format."""
    if value is None or value == "":
        return "-"
    try:
        dec = Decimal(str(value)) / Decimal("1000.0")
        return f"{dec:,.{decimals}f}"
    except Exception:
        return str(value)

@register.filter(name="status_badge")
def status_badge(status_code):
    """Return colored Bootstrap badge HTML for ticket status."""
    badges = {
        "draft": '<span class="badge bg-secondary-subtle text-secondary border border-secondary">پیش‌نویس</span>',
        "waiting_first": '<span class="badge bg-warning-subtle text-warning border border-warning">در انتظار وزن اول</span>',
        "first_registered": '<span class="badge bg-info-subtle text-info border border-info">ثبت وزن اول</span>',
        "waiting_second": '<span class="badge bg-primary-subtle text-primary border border-primary fw-bold"><i class="bi bi-clock-history me-1"></i>در انتظار وزن دوم (داخل محوطه)</span>',
        "completed": '<span class="badge bg-success-subtle text-success border border-success fw-bold"><i class="bi bi-check-circle me-1"></i>تکمیل شده</span>',
        "cancelled": '<span class="badge bg-danger-subtle text-danger border border-danger fw-bold"><i class="bi bi-x-circle me-1"></i>ابطال شده</span>',
    }
    return mark_safe(badges.get(status_code, f'<span class="badge bg-light text-dark">{status_code}</span>'))

@register.filter(name="audit_action_badge")
def audit_action_badge(action_code):
    """Return colored Bootstrap badge HTML for audit action."""
    badges = {
        "create": '<span class="badge bg-success-subtle text-success">ثبت جدید</span>',
        "update": '<span class="badge bg-primary-subtle text-primary">ویرایش</span>',
        "delete": '<span class="badge bg-danger-subtle text-danger">حذف</span>',
        "override_weight": '<span class="badge bg-danger text-white fw-bold">اورراید وزن</span>',
        "override_loss": '<span class="badge bg-warning text-dark fw-bold">اورراید افت</span>',
        "cancel": '<span class="badge bg-danger-subtle text-danger">ابطال سند</span>',
        "status_change": '<span class="badge bg-info-subtle text-info">تغییر وضعیت</span>',
        "print": '<span class="badge bg-secondary-subtle text-secondary">چاپ قبض</span>',
    }
    return mark_safe(badges.get(action_code, f'<span class="badge bg-light text-dark">{action_code}</span>'))

@register.filter(name="get_item")
def get_item(dictionary, key):
    """Safely get dictionary item in template."""
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None

from core.jalali import number_to_persian_words

@register.filter(name="persian_words")
def persian_words_filter(value):
    """Convert number or amount to Persian words."""
    if value is None or value == "":
        return ""
    return number_to_persian_words(value)

