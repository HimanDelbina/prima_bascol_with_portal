from django.contrib import admin
from weighbridge.models import WeighTicket

@admin.register(WeighTicket)
class WeighTicketAdmin(admin.ModelAdmin):
    list_display = [
        "serial_number", "status", "party", "product", "license_plate_display",
        "driver_display", "gross_weight", "tare_weight", "net_weight", "final_weight",
        "first_weight_date", "created_at"
    ]
    list_filter = ["status", "weight_mode", "operation_type", "product", "is_tolerance_exceeded", "first_weight_date"]
    search_fields = ["serial_number", "license_plate_display", "waybill_number", "party__name", "product__name", "driver__full_name"]
    readonly_fields = ["gross_weight", "tare_weight", "net_weight", "final_weight", "weight_difference", "weight_difference_percent", "created_at", "updated_at"]
    ordering = ["-id"]
