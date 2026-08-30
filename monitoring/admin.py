from django.contrib import admin
from monitoring.models import MonitoringAlert, MonitoringRuleConfig


@admin.register(MonitoringRuleConfig)
class MonitoringRuleConfigAdmin(admin.ModelAdmin):
    list_display = [
        "name_fa",
        "rule_type",
        "enabled",
        "warning_threshold",
        "high_threshold",
        "critical_threshold",
        "minimum_history",
        "updated_at",
    ]
    list_filter = ["enabled", "rule_type"]
    search_fields = ["name_fa", "rule_type", "description"]


@admin.register(MonitoringAlert)
class MonitoringAlertAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "ticket",
        "alert_type",
        "severity",
        "title",
        "status",
        "confidence",
        "created_at",
        "resolved_by",
    ]
    list_filter = ["alert_type", "severity", "status", "confidence", "created_at"]
    search_fields = [
        "ticket__serial_number",
        "ticket__license_plate_display",
        "title",
        "reason",
        "resolution_note",
    ]
    readonly_fields = ["created_at", "resolved_at"]
