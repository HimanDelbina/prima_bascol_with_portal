from django.contrib import admin
from core.models import SystemSetting

@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    list_display = ["company_name", "serial_start_number", "serial_prefix", "weight_unit", "max_tolerance_kg", "default_print_template"]
