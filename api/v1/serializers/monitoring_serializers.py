from rest_framework import serializers
from monitoring.models import (
    MonitoringAlert, MonitoringRuleConfig,
    AlertType, AlertSeverity, AlertStatus, AlertConfidence
)
from api.v1.utils import format_choice_field
from core.jalali import format_jalali_datetime


class MonitoringAlertSerializer(serializers.ModelSerializer):
    alert_type = serializers.SerializerMethodField()
    severity = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    confidence = serializers.SerializerMethodField()
    ticket_serial = serializers.CharField(source='ticket.serial_number', read_only=True)
    ticket_plate = serializers.CharField(source='ticket.license_plate_display', read_only=True)
    created_at_jalali = serializers.CharField(source='jalali_created_at', read_only=True)
    resolved_at_jalali = serializers.CharField(source='jalali_resolved_at', read_only=True)
    resolved_by_name = serializers.CharField(source='resolved_by.get_full_name', read_only=True)

    class Meta:
        model = MonitoringAlert
        fields = [
            'id', 'ticket', 'ticket_serial', 'ticket_plate',
            'alert_type',
            'severity',
            'title', 'description', 'reason',
            'current_value', 'baseline_value', 'deviation_value', 'deviation_percent',
            'sample_size', 'confidence',
            'status',
            'created_at', 'created_at_jalali',
            'resolved_at', 'resolved_at_jalali',
            'resolved_by', 'resolved_by_name',
            'resolution_note', 'metadata'
        ]
        read_only_fields = fields

    def get_alert_type(self, obj):
        return format_choice_field(obj.alert_type, obj.get_alert_type_display())

    def get_severity(self, obj):
        return format_choice_field(obj.severity, obj.get_severity_display())

    def get_status(self, obj):
        return format_choice_field(obj.status, obj.get_status_display())

    def get_confidence(self, obj):
        return format_choice_field(obj.confidence, obj.get_confidence_display())


class AlertReviewSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True)


class AlertResolveSerializer(serializers.Serializer):
    resolution_note = serializers.CharField(required=True, min_length=3, error_messages={
        "required": "وارد کردن یادداشت اقدام / حل هشدار اجباری است.",
        "blank": "یادداشت اقدام نمی‌تواند خالی باشد."
    })


class AlertIgnoreSerializer(serializers.Serializer):
    reason = serializers.CharField(required=True, min_length=3, error_messages={
        "required": "وارد کردن دلیل نادیده‌گرفتن هشدار اجباری است.",
        "blank": "دلیل نمی‌تواند خالی باشد."
    })


class MonitoringRuleConfigSerializer(serializers.ModelSerializer):
    rule_type_display = serializers.CharField(source='get_rule_type_display', read_only=True)
    updated_by_name = serializers.CharField(source='updated_by.get_full_name', read_only=True)

    class Meta:
        model = MonitoringRuleConfig
        fields = [
            'id', 'rule_type', 'rule_type_display', 'name_fa', 'description',
            'enabled', 'warning_threshold', 'high_threshold', 'critical_threshold',
            'percentage_warning', 'percentage_high', 'percentage_critical',
            'minimum_history', 'extra_params', 'updated_at', 'updated_by_name'
        ]
        read_only_fields = ['id', 'rule_type', 'rule_type_display', 'name_fa', 'updated_at', 'updated_by_name']
