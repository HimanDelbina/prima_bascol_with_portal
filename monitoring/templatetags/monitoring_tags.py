from django import template
from django.utils.safestring import mark_safe
from monitoring.models import AlertSeverity, AlertStatus, AlertConfidence, AlertType

register = template.Library()


@register.filter(name="severity_badge")
def severity_badge(severity_code):
    """
    Return colored Bootstrap badge with Icon + Text for alert severity.
    """
    badges = {
        AlertSeverity.INFO: (
            '<span class="badge bg-info-subtle text-info border border-info px-2 py-1">'
            '<i class="bi bi-info-circle me-1"></i>اطلاعات (Info)</span>'
        ),
        AlertSeverity.LOW: (
            '<span class="badge bg-success-subtle text-success border border-success px-2 py-1">'
            '<i class="bi bi-shield-check me-1"></i>ریسک پایین (Low)</span>'
        ),
        AlertSeverity.MEDIUM: (
            '<span class="badge bg-warning-subtle text-warning border border-warning px-2 py-1 text-dark">'
            '<i class="bi bi-exclamation-triangle me-1"></i>متوسط (Medium)</span>'
        ),
        AlertSeverity.HIGH: (
            '<span class="badge bg-danger-subtle text-danger border border-danger px-2 py-1 fw-bold">'
            '<i class="bi bi-exclamation-octagon me-1"></i>بالا (High)</span>'
        ),
        AlertSeverity.CRITICAL: (
            '<span class="badge bg-danger text-white px-2 py-1 fw-bold shadow-sm animate-pulse">'
            '<i class="bi bi-radiation me-1"></i>بحرانی (Critical)</span>'
        ),
    }
    return mark_safe(badges.get(severity_code, f'<span class="badge bg-secondary">{severity_code}</span>'))


@register.filter(name="alert_status_badge")
def alert_status_badge(status_code):
    """
    Return colored badge with icon for alert status.
    """
    badges = {
        AlertStatus.OPEN: (
            '<span class="badge bg-danger-subtle text-danger border border-danger px-2 py-1 fw-bold">'
            '<i class="bi bi-envelope-open me-1"></i>باز (Open)</span>'
        ),
        AlertStatus.REVIEWED: (
            '<span class="badge bg-warning-subtle text-warning border border-warning px-2 py-1 text-dark">'
            '<i class="bi bi-eye me-1"></i>بررسی‌شده (Reviewed)</span>'
        ),
        AlertStatus.RESOLVED: (
            '<span class="badge bg-success-subtle text-success border border-success px-2 py-1 fw-bold">'
            '<i class="bi bi-check2-circle me-1"></i>اقدام/حل شده (Resolved)</span>'
        ),
        AlertStatus.IGNORED: (
            '<span class="badge bg-secondary-subtle text-secondary border border-secondary px-2 py-1">'
            '<i class="bi bi-dash-circle me-1"></i>نادیده‌گرفته (Ignored)</span>'
        ),
    }
    return mark_safe(badges.get(status_code, f'<span class="badge bg-secondary">{status_code}</span>'))


@register.filter(name="confidence_badge")
def confidence_badge(confidence_code):
    """
    Return badge indicating baseline sample size quality.
    """
    badges = {
        AlertConfidence.INSUFFICIENT: (
            '<span class="badge bg-secondary-subtle text-secondary border border-secondary" title="تعداد سوابق کمتر از حد مجاز است">'
            '<i class="bi bi-question-circle me-1"></i>داده ناکافی</span>'
        ),
        AlertConfidence.LOW: (
            '<span class="badge bg-warning-subtle text-dark border border-warning" title="۱۰ الی ۱۹ سابقه قبلی">'
            '<i class="bi bi-reception-2 me-1"></i>اطمینان پایین</span>'
        ),
        AlertConfidence.MEDIUM: (
            '<span class="badge bg-info-subtle text-info border border-info" title="۲۰ الی ۴۹ سابقه قبلی">'
            '<i class="bi bi-reception-3 me-1"></i>اطمینان متوسط</span>'
        ),
        AlertConfidence.HIGH: (
            '<span class="badge bg-success-subtle text-success border border-success fw-bold" title="۵۰+ سابقه قبلی">'
            '<i class="bi bi-reception-4 me-1"></i>اطمینان بالا</span>'
        ),
    }
    return mark_safe(badges.get(confidence_code, f'<span class="badge bg-light text-dark">{confidence_code}</span>'))


@register.filter(name="risk_score_badge")
def risk_score_badge(score):
    """
    Render risk score gauge/badge (0-100).
    """
    try:
        val = int(score)
    except Exception:
        val = 0

    if val >= 80:
        css = "bg-danger text-white border-danger"
        level_text = "بحرانی"
        icon = "bi-radioactive"
    elif val >= 60:
        css = "bg-danger-subtle text-danger border-danger"
        level_text = "پرخطر"
        icon = "bi-exclamation-octagon"
    elif val >= 40:
        css = "bg-warning-subtle text-dark border-warning"
        level_text = "نیازمند بررسی"
        icon = "bi-exclamation-triangle"
    elif val >= 20:
        css = "bg-info-subtle text-info border-info"
        level_text = "کم‌خطر"
        icon = "bi-info-circle"
    else:
        css = "bg-success-subtle text-success border-success"
        level_text = "عادی"
        icon = "bi-shield-check"

    return mark_safe(
        f'<span class="badge {css} border px-2 py-1 font-monospace fs-6">'
        f'<i class="bi {icon} me-1"></i>{val} / ۱۰۰ <small class="fw-normal">({level_text})</small></span>'
    )


@register.filter(name="alert_type_icon")
def alert_type_icon(alert_type):
    """
    Return appropriate Bootstrap icon class for alert type.
    """
    icons = {
        AlertType.VEHICLE_TARE_ANOMALY: "bi-truck text-danger",
        AlertType.WEIGHT_DISCREPANCY: "bi-arrow-left-right text-warning",
        AlertType.LOSS_ANOMALY: "bi-percent text-danger",
        AlertType.NET_WEIGHT_ANOMALY: "bi-box-seam text-primary",
        AlertType.LONG_WAITING_TIME: "bi-hourglass-split text-warning",
        AlertType.WEIGHT_EDIT_ANOMALY: "bi-pencil-square text-danger",
    }
    return icons.get(alert_type, "bi-bell")
