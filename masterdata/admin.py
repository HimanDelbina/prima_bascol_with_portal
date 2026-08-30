from django.contrib import admin
from masterdata.models import (
    Product, Party, Driver, VehicleType, Vehicle,
    Location, UnloadLocation, OperationType, LossType
)

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "standard_tolerance_kg", "default_loss_percent", "is_active"]
    search_fields = ["name", "code"]
    list_filter = ["is_active"]

@admin.register(Party)
class PartyAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "party_type", "phone", "national_id", "is_active"]
    search_fields = ["name", "code", "phone", "national_id"]
    list_filter = ["party_type", "is_active"]

@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ["full_name", "mobile", "national_code", "license_number", "is_active"]
    search_fields = ["full_name", "mobile", "national_code"]
    list_filter = ["is_active"]

@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ["plate_display", "vehicle_type", "default_driver", "empty_weight", "is_active"]
    search_fields = ["plate_display"]
    list_filter = ["vehicle_type", "is_active"]

@admin.register(VehicleType)
class VehicleTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "standard_tare_weight", "is_active"]
    search_fields = ["name", "code"]

@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ["name", "location_type", "is_active"]
    search_fields = ["name"]
    list_filter = ["location_type", "is_active"]

@admin.register(UnloadLocation)
class UnloadLocationAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "is_active"]
    search_fields = ["name", "code"]

@admin.register(OperationType)
class OperationTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "direction", "is_active"]
    list_filter = ["direction", "is_active"]

@admin.register(LossType)
class LossTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "default_percent", "is_active"]
    list_filter = ["is_active"]
