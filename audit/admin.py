from django.contrib import admin
from audit.models import AuditLog

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["timestamp", "action", "model_name", "record_repr", "user", "ip_address", "reason"]
    list_filter = ["action", "model_name", "timestamp"]
    search_fields = ["record_repr", "record_id", "reason", "user__username", "ip_address"]
    readonly_fields = ["user", "ip_address", "timestamp", "action", "model_name", "record_id", "record_repr", "old_values", "new_values", "reason"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
