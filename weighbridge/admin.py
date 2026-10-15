from django.contrib import admin
from weighbridge.models import WeighTicket, EmergencyWeighTicket, TicketSequence

@admin.register(WeighTicket)
class WeighTicketAdmin(admin.ModelAdmin):
    def save_model(self, request, obj, form, change):
        from weighbridge.plate_policy import DailyPlatePolicy
        DailyPlatePolicy.save(obj, user=request.user)

    def get_readonly_fields(self, request, obj=None):
        ro = list(self.readonly_fields)
        if obj:
            ro.append("serial_number")
        return ro

    list_display = [
        "serial_number", "status", "party", "product", "license_plate_display",
        "driver_display", "gross_weight", "tare_weight", "net_weight", "final_weight",
        "first_weight_date", "created_at"
    ]
    list_filter = ["status", "weight_mode", "operation_type", "product", "is_tolerance_exceeded", "first_weight_date"]
    search_fields = ["serial_number", "license_plate_display", "waybill_number", "party__name", "product__name", "driver__full_name"]
    readonly_fields = ["gross_weight", "tare_weight", "net_weight", "final_weight", "weight_difference", "weight_difference_percent", "created_at", "updated_at"]
    ordering = ["-id"]


@admin.register(EmergencyWeighTicket)
class EmergencyWeighTicketAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        ro = list(self.readonly_fields)
        if obj:
            ro.append("serial_number")
        return ro

    list_display = [
        "serial_number", "company_name", "driver_name", "driver_mobile",
        "license_plate", "gross_weight", "tare_weight", "net_weight",
        "status", "weight_date", "created_at"
    ]
    list_filter = ["status", "weight_date"]
    search_fields = ["serial_number", "company_name", "driver_name", "driver_mobile", "license_plate"]
    readonly_fields = ["net_weight", "created_at", "updated_at"]
    ordering = ["-id"]


@admin.register(TicketSequence)
class TicketSequenceAdmin(admin.ModelAdmin):
    list_display = ["scope", "prefix", "last_number", "description", "updated_at"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["scope"]

