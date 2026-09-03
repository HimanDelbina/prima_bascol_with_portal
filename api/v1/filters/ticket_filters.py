import django_filters
from django.db.models import Q
from decimal import Decimal

from weighbridge.models import WeighTicket, TicketStatus
from core.jalali import jalali_to_gregorian


class WeighTicketFilter(django_filters.FilterSet):
    """
    Comprehensive multi-field filterset for WeighTickets supporting 30+ criteria.
    """
    date_from = django_filters.CharFilter(method='filter_date_from')
    date_to = django_filters.CharFilter(method='filter_date_to')
    
    status = django_filters.ChoiceFilter(choices=TicketStatus.choices)
    operation_type = django_filters.NumberFilter(field_name='operation_type_id')
    party = django_filters.NumberFilter(field_name='party_id')
    product = django_filters.NumberFilter(field_name='product_id')
    driver = django_filters.NumberFilter(field_name='driver_id')
    vehicle = django_filters.NumberFilter(field_name='vehicle_id')
    
    plate = django_filters.CharFilter(field_name='license_plate_display', lookup_expr='icontains')
    waybill_number = django_filters.CharFilter(lookup_expr='icontains')
    
    origin = django_filters.NumberFilter(field_name='origin_id')
    destination = django_filters.NumberFilter(field_name='destination_id')
    unload_location = django_filters.NumberFilter(field_name='unload_location_id')
    
    operator = django_filters.CharFilter(method='filter_operator')
    
    gross_weight_min = django_filters.NumberFilter(field_name='gross_weight', lookup_expr='gte')
    gross_weight_max = django_filters.NumberFilter(field_name='gross_weight', lookup_expr='lte')
    
    tare_weight_min = django_filters.NumberFilter(field_name='tare_weight', lookup_expr='gte')
    tare_weight_max = django_filters.NumberFilter(field_name='tare_weight', lookup_expr='lte')
    
    net_weight_min = django_filters.NumberFilter(field_name='net_weight', lookup_expr='gte')
    net_weight_max = django_filters.NumberFilter(field_name='net_weight', lookup_expr='lte')
    
    sent_weight_min = django_filters.NumberFilter(field_name='sent_weight', lookup_expr='gte')
    sent_weight_max = django_filters.NumberFilter(field_name='sent_weight', lookup_expr='lte')
    
    loss_percent_min = django_filters.NumberFilter(field_name='loss_percent', lookup_expr='gte')
    loss_percent_max = django_filters.NumberFilter(field_name='loss_percent', lookup_expr='lte')
    
    has_loss = django_filters.BooleanFilter(method='filter_has_loss')
    has_discrepancy = django_filters.BooleanFilter(method='filter_has_discrepancy')

    class Meta:
        model = WeighTicket
        fields = [
            'status', 'operation_type', 'party', 'product',
            'driver', 'vehicle', 'origin', 'destination', 'unload_location',
            'is_tolerance_exceeded', 'is_loss_overridden'
        ]

    def filter_date_from(self, queryset, name, value):
        if not value:
            return queryset
        val_str = str(value).strip()
        # Check if Jalali e.g. 1405/06/07 or 1405-06-07
        g_date = jalali_to_gregorian(val_str)
        if g_date:
            return queryset.filter(Q(first_weight_date__gte=g_date) | Q(created_at__date__gte=g_date))
        # Else try ISO date
        try:
            return queryset.filter(Q(first_weight_date__gte=val_str) | Q(created_at__date__gte=val_str))
        except Exception:
            return queryset

    def filter_date_to(self, queryset, name, value):
        if not value:
            return queryset
        val_str = str(value).strip()
        g_date = jalali_to_gregorian(val_str)
        if g_date:
            return queryset.filter(Q(first_weight_date__lte=g_date) | Q(created_at__date__lte=g_date))
        try:
            return queryset.filter(Q(first_weight_date__lte=val_str) | Q(created_at__date__lte=val_str))
        except Exception:
            return queryset

    def filter_operator(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(first_weight_operator_id=value) | Q(second_weight_operator_id=value) |
            Q(first_weight_operator__username__icontains=value) |
            Q(second_weight_operator__username__icontains=value)
        )

    def filter_has_loss(self, queryset, name, value):
        if value is True:
            return queryset.filter(loss_weight__gt=0)
        elif value is False:
            return queryset.filter(loss_weight=0)
        return queryset

    def filter_has_discrepancy(self, queryset, name, value):
        if value is True:
            return queryset.filter(is_tolerance_exceeded=True)
        elif value is False:
            return queryset.filter(is_tolerance_exceeded=False)
        return queryset
