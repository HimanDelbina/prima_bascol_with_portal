from rest_framework import serializers
from decimal import Decimal
from masterdata.models import (
    Product, Party, Driver, VehicleType, Vehicle,
    Location, UnloadLocation, OperationType, LossType,
    PartyType, LocationType, OperationDirection
)
from api.v1.utils import format_choice_field
from core.jalali import format_jalali_datetime


class ProductSerializer(serializers.ModelSerializer):
    created_at_jalali = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'code', 'standard_tolerance_kg', 'default_loss_percent',
            'description', 'is_active', 'created_at', 'created_at_jalali', 'updated_at'
        ]
        read_only_fields = ['created_at', 'created_at_jalali', 'updated_at']

    def get_created_at_jalali(self, obj):
        return format_jalali_datetime(obj.created_at)


class PartySerializer(serializers.ModelSerializer):
    party_type_display = serializers.SerializerMethodField()
    created_at_jalali = serializers.SerializerMethodField()

    class Meta:
        model = Party
        fields = [
            'id', 'name', 'code', 'party_type', 'party_type_display',
            'phone', 'tel', 'email', 'address', 'national_id', 'economic_code',
            'is_active', 'created_at', 'created_at_jalali', 'updated_at'
        ]
        read_only_fields = ['created_at', 'created_at_jalali', 'updated_at']

    def get_party_type_display(self, obj):
        return format_choice_field(obj.party_type, obj.get_party_type_display())

    def get_created_at_jalali(self, obj):
        return format_jalali_datetime(obj.created_at)


class DriverSerializer(serializers.ModelSerializer):
    created_at_jalali = serializers.SerializerMethodField()

    class Meta:
        model = Driver
        fields = [
            'id', 'full_name', 'mobile', 'national_code', 'license_number',
            'description', 'is_active', 'created_at', 'created_at_jalali', 'updated_at'
        ]
        read_only_fields = ['created_at', 'created_at_jalali', 'updated_at']

    def get_created_at_jalali(self, obj):
        return format_jalali_datetime(obj.created_at)


class VehicleTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleType
        fields = [
            'id', 'name', 'code', 'standard_tare_weight',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


class VehicleSerializer(serializers.ModelSerializer):
    vehicle_type_name = serializers.CharField(source='vehicle_type.name', read_only=True)
    default_driver_name = serializers.CharField(source='default_driver.full_name', read_only=True)
    created_at_jalali = serializers.SerializerMethodField()
    trip_count = serializers.SerializerMethodField()
    last_trip_date = serializers.SerializerMethodField()
    avg_empty_weight = serializers.SerializerMethodField()

    class Meta:
        model = Vehicle
        fields = [
            'id', 'plate_part1', 'plate_letter', 'plate_part2', 'plate_iran',
            'plate_display', 'vehicle_type', 'vehicle_type_name',
            'default_driver', 'default_driver_name',
            'empty_weight', 'description', 'trip_count', 'last_trip_date',
            'avg_empty_weight', 'is_active', 'created_at', 'created_at_jalali', 'updated_at'
        ]
        read_only_fields = ['created_at', 'created_at_jalali', 'updated_at', 'plate_display']

    def get_created_at_jalali(self, obj):
        return format_jalali_datetime(obj.created_at)

    def get_trip_count(self, obj):
        return obj.tickets.filter(status="completed").count()

    def get_last_trip_date(self, obj):
        last = obj.tickets.filter(status="completed").order_by("-id").first()
        return last.jalali_first_date if last else None

    def get_avg_empty_weight(self, obj):
        from django.db.models import Avg
        avg = obj.tickets.filter(status="completed", tare_weight__gt=0).aggregate(a=Avg("tare_weight"))["a"]
        return round(float(avg), 2) if avg else float(obj.empty_weight or 0)


class LocationSerializer(serializers.ModelSerializer):
    location_type_display = serializers.SerializerMethodField()

    class Meta:
        model = Location
        fields = [
            'id', 'name', 'location_type', 'location_type_display',
            'description', 'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_location_type_display(self, obj):
        return format_choice_field(obj.location_type, obj.get_location_type_display())


class UnloadLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnloadLocation
        fields = [
            'id', 'name', 'code', 'description',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


class OperationTypeSerializer(serializers.ModelSerializer):
    direction_display = serializers.SerializerMethodField()

    class Meta:
        model = OperationType
        fields = [
            'id', 'name', 'code', 'direction', 'direction_display',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_direction_display(self, obj):
        return format_choice_field(obj.direction, obj.get_direction_display())


class LossTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LossType
        fields = [
            'id', 'name', 'code', 'default_percent', 'description',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']
