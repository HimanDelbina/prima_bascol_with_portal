from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view

from audit.models import AuditLog
from api.v1.serializers.audit_serializers import AuditLogSerializer
from api.v1.filters.audit_filters import AuditLogFilter
from api.v1.permissions import CanAccessAudit


@extend_schema_view(
    list=extend_schema(tags=['Audit'], summary='لیست گزارشات ممیزی (Audit Log)'),
    retrieve=extend_schema(tags=['Audit'], summary='مشاهده لاگ ممیزی و تغییرات'),
)
class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    مشاهده گزارشات ممیزی و ردیابی تغییرات حساس سیستم (فقط‌خواندنی - بدون امکان ویرایش یا حذف).
    """
    queryset = AuditLog.objects.select_related('user').all().order_by('-timestamp')
    serializer_class = AuditLogSerializer
    permission_classes = [CanAccessAudit]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = AuditLogFilter
    search_fields = ['record_repr', 'reason', 'user__username', 'user__first_name', 'user__last_name']
    ordering_fields = ['timestamp', 'action', 'model_name']
