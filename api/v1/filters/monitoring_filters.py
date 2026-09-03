import django_filters
from django.db.models import Q
from monitoring.models import MonitoringAlert, AlertSeverity, AlertStatus, AlertType
from core.jalali import jalali_to_gregorian


class MonitoringAlertFilter(django_filters.FilterSet):
    severity = django_filters.ChoiceFilter(choices=AlertSeverity.choices)
    status = django_filters.ChoiceFilter(choices=AlertStatus.choices)
    alert_type = django_filters.ChoiceFilter(choices=AlertType.choices)
    ticket = django_filters.NumberFilter(field_name='ticket_id')
    vehicle = django_filters.NumberFilter(field_name='ticket__vehicle_id')
    party = django_filters.NumberFilter(field_name='ticket__party_id')
    product = django_filters.NumberFilter(field_name='ticket__product_id')
    plate = django_filters.CharFilter(field_name='ticket__license_plate_display', lookup_expr='icontains')
    
    date_from = django_filters.CharFilter(method='filter_date_from')
    date_to = django_filters.CharFilter(method='filter_date_to')

    class Meta:
        model = MonitoringAlert
        fields = ['severity', 'status', 'alert_type', 'ticket']

    def filter_date_from(self, queryset, name, value):
        if not value:
            return queryset
        val_str = str(value).strip()
        g_date = jalali_to_gregorian(val_str)
        if g_date:
            return queryset.filter(created_at__date__gte=g_date)
        try:
            return queryset.filter(created_at__date__gte=val_str)
        except Exception:
            return queryset

    def filter_date_to(self, queryset, name, value):
        if not value:
            return queryset
        val_str = str(value).strip()
        g_date = jalali_to_gregorian(val_str)
        if g_date:
            return queryset.filter(created_at__date__lte=g_date)
        try:
            return queryset.filter(created_at__date__lte=val_str)
        except Exception:
            return queryset
