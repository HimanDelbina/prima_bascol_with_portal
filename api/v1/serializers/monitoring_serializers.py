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
    product_name = serializers.CharField(source='ticket.product.name', read_only=True, default='')
    party_name = serializers.CharField(source='ticket.party.name', read_only=True, default='')
    baseline_source = serializers.SerializerMethodField()
    
    created_at_jalali = serializers.CharField(source='jalali_created_at', read_only=True)
    updated_at_jalali = serializers.CharField(source='jalali_updated_at', read_only=True)
    reviewed_at_jalali = serializers.CharField(source='jalali_reviewed_at', read_only=True)
    reviewed_by_name = serializers.CharField(source='reviewed_by.get_full_name', read_only=True)
    resolved_at_jalali = serializers.CharField(source='jalali_resolved_at', read_only=True)
    resolved_by_name = serializers.CharField(source='resolved_by.get_full_name', read_only=True)

    ticket_summary = serializers.SerializerMethodField()
    historical_summary = serializers.SerializerMethodField()
    recent_history = serializers.SerializerMethodField()

    class Meta:
        model = MonitoringAlert
        fields = [
            'id', 'ticket', 'ticket_serial', 'ticket_plate', 'product_name', 'party_name',
            'alert_type',
            'severity',
            'title', 'description', 'reason',
            'current_value', 'baseline_value', 'deviation_value', 'deviation_percent',
            'sample_size', 'confidence', 'baseline_source',
            'status',
            'created_at', 'created_at_jalali',
            'updated_at', 'updated_at_jalali',
            'reviewed_at', 'reviewed_at_jalali',
            'reviewed_by', 'reviewed_by_name',
            'resolved_at', 'resolved_at_jalali',
            'resolved_by', 'resolved_by_name',
            'resolution_note', 'metadata',
            'ticket_summary', 'historical_summary', 'recent_history'
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

    def get_baseline_source(self, obj):
        meta = obj.metadata or {}
        return meta.get('baseline_source', '')

    def get_ticket_summary(self, obj):
        t = obj.ticket
        if not t:
            return None
        return {
            'id': t.id,
            'serial_number': t.serial_number,
            'license_plate': t.license_plate_display,
            'product_id': t.product_id,
            'product_name': t.product.name if t.product else '',
            'party_id': t.party_id,
            'party_name': t.party.name if t.party else '',
            'driver_name': t.driver_display,
            'net_weight': str(t.net_weight) if t.net_weight is not None else None,
            'first_weight': str(t.first_weight) if t.first_weight is not None else None,
            'second_weight': str(t.second_weight) if t.second_weight is not None else None,
            'status': t.status,
            'status_display': t.get_status_display(),
        }

    def get_historical_summary(self, obj):
        meta = obj.metadata or {}
        return {
            'average': meta.get('historical_average') or meta.get('average'),
            'median': meta.get('median'),
            'stddev': meta.get('stddev'),
            'min': meta.get('min'),
            'max': meta.get('max'),
            'sample_size': obj.sample_size,
            'last_5_average': meta.get('last_5_average'),
            'last_10_average': meta.get('last_10_average'),
        }

    def get_recent_history(self, obj):
        meta = obj.metadata or {}
        return meta.get('recent_history', [])


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
