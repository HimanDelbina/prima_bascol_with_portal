from rest_framework import serializers
from audit.models import AuditLog, AuditAction
from api.v1.utils import format_choice_field
from core.jalali import format_jalali_datetime


class AuditLogSerializer(serializers.ModelSerializer):
    action_display = serializers.SerializerMethodField()
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)
    timestamp_jalali = serializers.CharField(source='jalali_timestamp', read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            'id', 'user', 'username', 'user_name', 'ip_address',
            'action', 'action_display',
            'model_name', 'record_id', 'record_repr',
            'old_values', 'new_values', 'reason',
            'timestamp', 'timestamp_jalali'
        ]
        read_only_fields = fields

    def get_action_display(self, obj):
        return format_choice_field(obj.action, obj.get_action_display())
