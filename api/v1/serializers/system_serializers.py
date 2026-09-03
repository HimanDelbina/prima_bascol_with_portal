from rest_framework import serializers
from core.models import SystemSetting


class PublicSystemSettingSerializer(serializers.ModelSerializer):
    """Safe public system settings."""
    class Meta:
        model = SystemSetting
        fields = [
            'company_name', 'company_address', 'company_phone', 'company_email',
            'receipt_header_title', 'weight_unit', 'decimal_places',
            'require_waybill', 'require_driver', 'require_origin', 'require_destination',
            'require_unload_location', 'default_print_template', 'receipt_footer_note'
        ]
        read_only_fields = fields


class AdminSystemSettingSerializer(serializers.ModelSerializer):
    """Full system settings for super admins / system admins."""
    class Meta:
        model = SystemSetting
        fields = '__all__'


class HealthCheckSerializer(serializers.Serializer):
    status = serializers.CharField()
    database = serializers.CharField()
    timestamp = serializers.CharField()


class MetaSerializer(serializers.Serializer):
    api_version = serializers.CharField()
    application_name = serializers.CharField()
    application_version = serializers.CharField()
    timezone = serializers.CharField()
    weight_unit = serializers.CharField()
