"""
Jalali (Solar Hijri) Date and Time Utilities for Prima Bascol Weighbridge System.
"""
from datetime import datetime, date, time
import jdatetime
from django.utils import timezone

# Persian digit translation
PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
ENGLISH_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")

def to_persian_digits(val) -> str:
    """Convert English digits to Persian digits."""
    if val is None:
        return ""
    return str(val).translate(PERSIAN_DIGITS)

def to_english_digits(val) -> str:
    """Convert Persian digits to English digits."""
    if val is None:
        return ""
    return str(val).translate(ENGLISH_DIGITS)

def gregorian_to_jalali(dt_or_date):
    """Convert Gregorian datetime/date to jdatetime."""
    if not dt_or_date:
        return None
    if isinstance(dt_or_date, datetime):
        return jdatetime.datetime.fromgregorian(datetime=dt_or_date)
    elif isinstance(dt_or_date, date):
        return jdatetime.date.fromgregorian(date=dt_or_date)
    return None

def jalali_to_gregorian(jdate_str: str) -> date | None:
    """
    Parse a Jalali date string (e.g. '1405/06/06' or '1405-06-06') to a standard Gregorian date.
    Accepts both English and Persian digits.
    """
    if not jdate_str or not str(jdate_str).strip():
        return None
    clean_str = to_english_digits(str(jdate_str).strip()).replace("-", "/")
    parts = clean_str.split("/")
    if len(parts) == 3:
        try:
            year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
            j_date = jdatetime.date(year, month, day)
            return j_date.togregorian()
        except (ValueError, TypeError):
            return None
    return None

def format_jalali_date(dt_or_date, fmt: str = "%Y/%m/%d") -> str:
    """Format Gregorian date/datetime to Jalali string (e.g., '1405/06/06')."""
    if not dt_or_date:
        return ""
    j_dt = gregorian_to_jalali(dt_or_date)
    if j_dt:
        return j_dt.strftime(fmt)
    return ""

def format_jalali_datetime(dt, fmt: str = "%Y/%m/%d %H:%M") -> str:
    """Format Gregorian datetime to Jalali datetime string."""
    if not dt:
        return ""
    j_dt = gregorian_to_jalali(dt)
    if j_dt:
        return j_dt.strftime(fmt)
    return ""

def format_time_hhmm(t) -> str:
    """Format time object as HH:MM."""
    if not t:
        return ""
    if isinstance(t, datetime):
        return t.strftime("%H:%M")
    elif isinstance(t, time):
        return t.strftime("%H:%M")
    return str(t)

def get_today_jalali() -> str:
    """Return today's Jalali date as string 'YYYY/MM/DD'."""
    return jdatetime.date.today().strftime("%Y/%m/%d")

def get_today_gregorian() -> date:
    """Return today's date in Tehran timezone."""
    return timezone.localdate()

def get_jalali_month_name(month_num: int) -> str:
    """Return Persian name of Jalali month."""
    months = [
        "فروردین", "اردیبهشت", "خرداد",
        "تیر", "مرداد", "شهریور",
        "مهر", "آبان", "آذر",
        "دی", "بهمن", "اسفند"
    ]
    if 1 <= month_num <= 12:
        return months[month_num - 1]
    return str(month_num)

def get_jalali_days_in_month(year: int, month: int) -> int:
    """Return number of days in a given Jalali year and month."""
    if month <= 6:
        return 31
    elif month <= 11:
        return 30
    else:
        return 30 if jdatetime.date(year, 1, 1).isleap() else 29

def get_jalali_range_gregorian(period_type: str = "today"):
    """
    Get Gregorian start and end date for all standard Jalali quick filter periods:
    'today', 'yesterday', 'last_7_days', 'this_week', 'last_week',
    'this_month', 'last_month', 'last_3_months', 'last_6_months',
    'this_year', 'last_year'.
    """
    j_today = jdatetime.date.today()
    
    if period_type == "today":
        g_date = j_today.togregorian()
        return g_date, g_date
    elif period_type == "yesterday":
        j_yest = j_today - jdatetime.timedelta(days=1)
        g_date = j_yest.togregorian()
        return g_date, g_date
    elif period_type == "last_7_days":
        start_j = j_today - jdatetime.timedelta(days=6)
        return start_j.togregorian(), j_today.togregorian()
    elif period_type == "this_week":
        # Jalali weekday: Saturday is 0, Friday is 6
        start_j = j_today - jdatetime.timedelta(days=j_today.weekday())
        end_j = start_j + jdatetime.timedelta(days=6)
        return start_j.togregorian(), end_j.togregorian()
    elif period_type == "last_week":
        current_week_start = j_today - jdatetime.timedelta(days=j_today.weekday())
        start_j = current_week_start - jdatetime.timedelta(days=7)
        end_j = start_j + jdatetime.timedelta(days=6)
        return start_j.togregorian(), end_j.togregorian()
    elif period_type == "this_month":
        start_j = jdatetime.date(j_today.year, j_today.month, 1)
        days = get_jalali_days_in_month(j_today.year, j_today.month)
        end_j = jdatetime.date(j_today.year, j_today.month, days)
        return start_j.togregorian(), end_j.togregorian()
    elif period_type == "last_month":
        if j_today.month == 1:
            lm_year = j_today.year - 1
            lm_month = 12
        else:
            lm_year = j_today.year
            lm_month = j_today.month - 1
        start_j = jdatetime.date(lm_year, lm_month, 1)
        days = get_jalali_days_in_month(lm_year, lm_month)
        end_j = jdatetime.date(lm_year, lm_month, days)
        return start_j.togregorian(), end_j.togregorian()
    elif period_type == "last_3_months":
        start_j = j_today - jdatetime.timedelta(days=90)
        return start_j.togregorian(), j_today.togregorian()
    elif period_type == "last_6_months":
        start_j = j_today - jdatetime.timedelta(days=180)
        return start_j.togregorian(), j_today.togregorian()
    elif period_type == "this_year":
        start_j = jdatetime.date(j_today.year, 1, 1)
        days_in_last = get_jalali_days_in_month(j_today.year, 12)
        end_j = jdatetime.date(j_today.year, 12, days_in_last)
        return start_j.togregorian(), end_j.togregorian()
    elif period_type == "last_year":
        ly_year = j_today.year - 1
        start_j = jdatetime.date(ly_year, 1, 1)
        days_in_last = get_jalali_days_in_month(ly_year, 12)
        end_j = jdatetime.date(ly_year, 12, days_in_last)
        return start_j.togregorian(), end_j.togregorian()
    else:
        g_date = j_today.togregorian()
        return g_date, g_date

def get_comparison_period_gregorian(start_date, end_date, period_type: str = ""):
    """
    Given a current period (start_date, end_date), return the corresponding previous comparison period (prev_start, prev_end).
    """
    if period_type == "today":
        return get_jalali_range_gregorian("yesterday")
    elif period_type == "yesterday":
        j_today = jdatetime.date.today()
        j_prev = j_today - jdatetime.timedelta(days=2)
        g_prev = j_prev.togregorian()
        return g_prev, g_prev
    elif period_type == "this_week":
        return get_jalali_range_gregorian("last_week")
    elif period_type == "last_week":
        j_today = jdatetime.date.today()
        curr_week_start = j_today - jdatetime.timedelta(days=j_today.weekday())
        start_j = curr_week_start - jdatetime.timedelta(days=14)
        end_j = start_j + jdatetime.timedelta(days=6)
        return start_j.togregorian(), end_j.togregorian()
    elif period_type == "this_month":
        return get_jalali_range_gregorian("last_month")
    elif period_type == "last_month":
        j_today = jdatetime.date.today()
        if j_today.month == 1:
            lm_year = j_today.year - 1
            lm_month = 11
        elif j_today.month == 2:
            lm_year = j_today.year - 1
            lm_month = 12
        else:
            lm_year = j_today.year
            lm_month = j_today.month - 2
        start_j = jdatetime.date(lm_year, lm_month, 1)
        days = get_jalali_days_in_month(lm_year, lm_month)
        end_j = jdatetime.date(lm_year, lm_month, days)
        return start_j.togregorian(), end_j.togregorian()
    elif period_type == "this_year":
        return get_jalali_range_gregorian("last_year")
    else:
        # Generic time window delta
        delta_days = (end_date - start_date).days + 1
        prev_end = start_date - timedelta(days=1)
        prev_start = prev_end - timedelta(days=delta_days - 1)
        return prev_start, prev_end
