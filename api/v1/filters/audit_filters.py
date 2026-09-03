import django_filters
from audit.models import AuditLog, AuditAction
from core.jalali import jalali_to_gregorian


class AuditLogFilter(django_filters.FilterSet):
    action = django_filters.ChoiceFilter(choices=AuditAction.choices)
    user = django_filters.NumberFilter(field_name='user_id')
    model_name = django_filters.CharFilter(lookup_expr='iexact')
    record_id = django_filters.CharFilter(lookup_expr='iexact')
    
    date_from = django_filters.CharFilter(method='filter_date_from')
    date_to = django_filters.CharFilter(method='filter_date_to')

    class Meta:
        model = AuditLog
        fields = ['action', 'user', 'model_name', 'record_id']

    def filter_date_from(self, queryset, name, value):
        if not value:
            return queryset
        val_str = str(value).strip()
        g_date = jalali_to_gregorian(val_str)
        if g_date:
            return queryset.filter(timestamp__date__gte=g_date)
        try:
            return queryset.filter(timestamp__date__gte=val_str)
        except Exception:
            return queryset

    def filter_date_to(self, queryset, name, value):
        if not value:
            return queryset
        val_str = str(value).strip()
        g_date = jalali_to_gregorian(val_str)
        if g_date:
            return queryset.filter(timestamp__date__lte=g_date)
        try:
            return queryset.filter(timestamp__date__lte=val_str)
        except Exception:
            return queryset
