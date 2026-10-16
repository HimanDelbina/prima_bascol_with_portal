from rest_framework import serializers
from decimal import Decimal
from django.utils import timezone
from datetime import time

from weighbridge.models import WeighTicket, TicketStatus, WeightMode, TicketRevision
from masterdata.models import (
    Product, Party, Driver, Vehicle, VehicleType,
    Location, UnloadLocation, OperationType, LossType
)
from api.v1.utils import format_choice_field
from core.jalali import format_jalali_date, format_jalali_datetime, format_time_hhmm


class WeighTicketListSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()
    weight_mode = serializers.SerializerMethodField()
    operation_type_name = serializers.CharField(source='operation_type.name', read_only=True)
    party_name = serializers.CharField(source='party.name', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    driver_name = serializers.CharField(source='driver_display', read_only=True)
    first_weight_date_jalali = serializers.CharField(source='jalali_first_date', read_only=True)
    second_weight_date_jalali = serializers.CharField(source='jalali_second_date', read_only=True)
    created_at_jalali = serializers.CharField(source='jalali_created_at', read_only=True)
    open_alerts_count = serializers.IntegerField(read_only=True, default=0)
    risk_score = serializers.SerializerMethodField()

    class Meta:
        model = WeighTicket
        fields = [
            'id', 'serial_number', 'status', 'weight_mode',
            'operation_type', 'operation_type_name',
            'party', 'party_name',
            'product', 'product_name',
            'license_plate_display', 'driver_name',
            'first_weight', 'first_weight_date', 'first_weight_date_jalali',
            'second_weight', 'second_weight_date', 'second_weight_date_jalali',
            'gross_weight', 'tare_weight', 'net_weight', 'sent_weight',
            'weight_difference', 'loss_weight', 'final_weight',
            'is_tolerance_exceeded', 'open_alerts_count', 'risk_score',
            'created_at', 'created_at_jalali',
        ]
        read_only_fields = fields

    def get_risk_score(self, obj):
        cnt = getattr(obj, 'open_alerts_count', None)
        if cnt == 0:
            return 0
        from monitoring.selectors.monitoring_queries import get_ticket_risk_score
        score, _ = get_ticket_risk_score(obj.id)
        return score

    def get_status(self, obj):
        return format_choice_field(obj.status, obj.get_status_display())

    def get_weight_mode(self, obj):
        return format_choice_field(obj.weight_mode, obj.get_weight_mode_display())


class WeighTicketDetailSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()
    weight_mode = serializers.SerializerMethodField()
    
    # Nested FK displays
    operation_type_display = serializers.SerializerMethodField()
    party_display = serializers.SerializerMethodField()
    product_display = serializers.SerializerMethodField()
    vehicle_display = serializers.SerializerMethodField()
    driver_display = serializers.CharField(read_only=True)
    driver_mobile_display = serializers.CharField(read_only=True)
    vehicle_type_display = serializers.CharField(read_only=True)
    origin_name = serializers.CharField(source='origin.name', read_only=True)
    destination_name = serializers.CharField(source='destination.name', read_only=True)
    unload_location_name = serializers.CharField(source='unload_location.name', read_only=True)
    loss_type_name = serializers.CharField(source='loss_type.name', read_only=True)
    
    # Operators
    first_weight_operator_name = serializers.CharField(source='first_weight_operator.get_full_name', read_only=True)
    second_weight_operator_name = serializers.CharField(source='second_weight_operator.get_full_name', read_only=True)
    cancelled_by_name = serializers.CharField(source='cancelled_by.get_full_name', read_only=True)
    last_edited_by_name = serializers.CharField(source='last_edited_by.get_full_name', read_only=True)

    # Dates Jalali
    first_weight_date_jalali = serializers.CharField(source='jalali_first_date', read_only=True)
    second_weight_date_jalali = serializers.CharField(source='jalali_second_date', read_only=True)
    created_at_jalali = serializers.CharField(source='jalali_created_at', read_only=True)
    cancelled_at_jalali = serializers.SerializerMethodField()
    
    # Monitoring Summary
    risk_score = serializers.SerializerMethodField()
    risk_level = serializers.SerializerMethodField()

    class Meta:
        model = WeighTicket
        fields = [
            'id', 'serial_number', 'status', 'weight_mode',
            'operation_type', 'operation_type_display',
            'party', 'party_display',
            'product', 'product_display',
            'vehicle', 'vehicle_display', 'vehicle_type', 'vehicle_type_display', 'vehicle_type_custom',
            'driver', 'driver_display', 'driver_mobile_display', 'driver_name_custom', 'driver_mobile_custom',
            'license_plate_display', 'waybill_number', 'freight_amount', 'duplicate_exception',
            'origin', 'origin_name', 'destination', 'destination_name',
            'unload_location', 'unload_location_name', 'load_count',
            
            # First weight
            'first_weight', 'first_weight_date', 'first_weight_date_jalali',
            'first_weight_time', 'first_weight_operator', 'first_weight_operator_name',
            
            # Second weight
            'second_weight', 'second_weight_date', 'second_weight_date_jalali',
            'second_weight_time', 'second_weight_operator', 'second_weight_operator_name',
            
            # Computed weights
            'gross_weight', 'tare_weight', 'net_weight', 'sent_weight',
            'weight_difference', 'weight_difference_percent', 'is_tolerance_exceeded',
            
            # Loss
            'loss_type', 'loss_type_name', 'loss_percent', 'loss_weight',
            'is_loss_overridden', 'loss_override_reason', 'final_weight',
            
            # Metadata & Auditing
            'current_revision_number', 'original_net_weight', 'has_revisions',
            'notes', 'cancellation_reason', 'cancelled_by', 'cancelled_by_name',
            'cancelled_at', 'cancelled_at_jalali',
            'last_edited_by', 'last_edited_by_name', 'last_edit_reason',
            'risk_score', 'risk_level',
            'created_at', 'created_at_jalali', 'updated_at',
        ]
        read_only_fields = fields

    def get_status(self, obj):
        return format_choice_field(obj.status, obj.get_status_display())

    def get_weight_mode(self, obj):
        return format_choice_field(obj.weight_mode, obj.get_weight_mode_display())

    def get_operation_type_display(self, obj):
        if obj.operation_type:
            return {'id': obj.operation_type.id, 'name': obj.operation_type.name, 'direction': obj.operation_type.direction}
        return None

    def get_party_display(self, obj):
        if obj.party:
            return {'id': obj.party.id, 'name': obj.party.name, 'code': obj.party.code}
        return None

    def get_product_display(self, obj):
        if obj.product:
            return {'id': obj.product.id, 'name': obj.product.name, 'code': obj.product.code}
        return None

    def get_vehicle_display(self, obj):
        if obj.vehicle:
            return {'id': obj.vehicle.id, 'plate': obj.vehicle.plate_display}
        return None

    def get_cancelled_at_jalali(self, obj):
        return format_jalali_datetime(obj.cancelled_at) if obj.cancelled_at else None

    def get_risk_score(self, obj):
        from monitoring.selectors.monitoring_queries import get_ticket_risk_score
        score, _ = get_ticket_risk_score(obj.id)
        return score

    def get_risk_level(self, obj):
        from monitoring.selectors.monitoring_queries import get_ticket_risk_score
        _, level = get_ticket_risk_score(obj.id)
        return level


class WeighTicketCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a new weighbridge ticket.
    Serial number is securely generated by backend.
    """
    first_weight = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False, default=Decimal("0.00"))
    second_weight = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"), required=False, allow_null=True)
    sent_weight = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False, default=0)
    loss_percent = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=0, max_value=100, required=False, default=0)
    license_plate_display = serializers.CharField(max_length=60, required=False, allow_blank=True)
    first_weight_date = serializers.DateField(required=False, allow_null=True)
    first_weight_time = serializers.TimeField(required=False, allow_null=True)

    class Meta:
        model = WeighTicket
        fields = [
            'id', 'serial_number', 'weight_mode',
            'operation_type', 'party', 'product',
            'vehicle', 'vehicle_type', 'vehicle_type_custom',
            'driver', 'driver_name_custom', 'driver_mobile_custom',
            'license_plate_display', 'waybill_number',
            'origin', 'destination', 'unload_location',
            'load_count', 'sent_weight', 'freight_amount',
            'first_weight', 'first_weight_date', 'first_weight_time',
            'second_weight', 'loss_type', 'loss_percent', 'notes'
        ]
        read_only_fields = ['id', 'serial_number']

    def validate(self, attrs):
        plate = attrs.get('license_plate_display', '').strip()
        vehicle = attrs.get('vehicle')
        if not plate and vehicle:
            attrs['license_plate_display'] = vehicle.plate_display
        elif not plate:
            raise serializers.ValidationError({"license_plate_display": "شماره پلاک الزامی است."})

        # Set driver custom if driver selected
        driver = attrs.get('driver')
        if driver:
            if not attrs.get('driver_name_custom'):
                attrs['driver_name_custom'] = driver.full_name
            if not attrs.get('driver_mobile_custom') and driver.mobile:
                attrs['driver_mobile_custom'] = driver.mobile

        return attrs


class FirstWeightSerializer(serializers.Serializer):
    weight = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("1.00"))
    date = serializers.DateField(required=False, allow_null=True)
    time = serializers.TimeField(required=False, allow_null=True)


class SecondWeightSerializer(serializers.Serializer):
    weight = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("1.00"))
    date = serializers.DateField(required=False, allow_null=True)
    time = serializers.TimeField(required=False, allow_null=True)
    loss_percent = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, allow_null=True)
    loss_type = serializers.PrimaryKeyRelatedField(queryset=LossType.objects.all(), required=False, allow_null=True)


class TicketCompleteSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True)


class TicketCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(required=True, min_length=3, error_messages={
        "required": "وارد کردن دلیل ابطال سند اجباری است.",
        "blank": "دلیل ابطال نمی‌تواند خالی باشد."
    })


class TicketCorrectSerializer(serializers.Serializer):
    field = serializers.ChoiceField(
        choices=[
            ("first_weight", "وزن اول"),
            ("second_weight", "وزن دوم"),
            ("sent_weight", "وزن ارسالی"),
            ("loss_percent", "درصد افت"),
            ("loss_weight", "وزن افت"),
            ("product", "محصول"),
            ("party", "طرف حساب"),
            ("vehicle", "خودرو"),
            ("driver", "راننده"),
            ("license_plate_display", "شماره پلاک"),
            ("waybill_number", "شماره بارنامه"),
        ],
        required=True
    )
    new_value = serializers.CharField(required=True)
    reason = serializers.CharField(required=True, min_length=3, error_messages={
        "required": "وارد کردن دلیل اصلاح مدیریتی اجباری است.",
        "blank": "دلیل اصلاح نمی‌تواند خالی باشد."
    })

    def validate(self, attrs):
        field, value = attrs["field"], attrs["new_value"]
        if field in ("product", "party", "driver", "vehicle"):
            attrs["new_value"] = serializers.IntegerField(min_value=1).run_validation(value)
        elif field in ("first_weight", "second_weight", "sent_weight", "loss_percent", "loss_weight"):
            minimum = Decimal("0.01") if field in ("first_weight", "second_weight") else Decimal("0")
            attrs["new_value"] = serializers.DecimalField(
                max_digits=6 if field == "loss_percent" else 12, decimal_places=2,
                min_value=minimum, max_value=100 if field == "loss_percent" else None,
            ).run_validation(value)
        return attrs


class TicketRevisionSerializer(serializers.ModelSerializer):
    requested_by_name = serializers.CharField(source='requested_by.get_full_name', read_only=True)
    reviewed_by_name = serializers.CharField(source='reviewed_by.get_full_name', read_only=True)
    applied_by_name = serializers.CharField(source='applied_by.get_full_name', read_only=True)
    requested_at_jalali = serializers.CharField(source='jalali_requested_at', read_only=True)
    reviewed_at_jalali = serializers.CharField(source='jalali_reviewed_at', read_only=True)
    applied_at_jalali = serializers.CharField(source='jalali_applied_at', read_only=True)

    class Meta:
        model = TicketRevision
        fields = [
            'id', 'ticket', 'revision_number', 'status', 'reason',
            'ticket_current_revision_at_request',
            'before_snapshot', 'after_snapshot', 'changed_fields',
            'requested_by', 'requested_by_name', 'requested_at', 'requested_at_jalali',
            'reviewed_by', 'reviewed_by_name', 'reviewed_at', 'reviewed_at_jalali',
            'review_notes',
            'applied_by', 'applied_by_name', 'applied_at', 'applied_at_jalali',
            'discrepancy_details',
        ]
        read_only_fields = fields


class TicketRevisionRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(required=True, min_length=3)
    proposed_data = serializers.DictField(required=True)


class TicketRevisionReviewSerializer(serializers.Serializer):
    review_reason = serializers.CharField(required=False, allow_blank=True, default="")
