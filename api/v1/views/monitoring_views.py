from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_view

from monitoring.models import (
    MonitoringAlert, MonitoringRuleConfig,
    AlertStatus, AlertSeverity
)
from audit.services import log_audit
from audit.models import AuditAction
from core.jalali import get_today_gregorian

from api.v1.serializers.monitoring_serializers import (
    MonitoringAlertSerializer, AlertReviewSerializer,
    AlertResolveSerializer, AlertIgnoreSerializer,
    MonitoringRuleConfigSerializer
)
from api.v1.filters.monitoring_filters import MonitoringAlertFilter
from api.v1.permissions import CanManageMonitoring, IsAdminUserOnly
from api.v1.utils import api_success_response, get_client_ip


@extend_schema_view(
    list=extend_schema(tags=['Monitoring'], summary='لیست هشدارهای پایش هوشمند'),
    retrieve=extend_schema(tags=['Monitoring'], summary='مشاهده جزییات هشدار پایش'),
)
class MonitoringAlertViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = MonitoringAlert.objects.select_related(
        'ticket', 'ticket__product', 'ticket__party', 'ticket__vehicle', 'ticket__driver',
        'resolved_by', 'reviewed_by'
    ).all().order_by('-id')

    serializer_class = MonitoringAlertSerializer
    permission_classes = [IsAuthenticated, CanManageMonitoring]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = MonitoringAlertFilter
    search_fields = [
        'title', 'description', 'reason',
        'ticket__serial_number', 'ticket__license_plate_display'
    ]
    ordering_fields = ['id', 'created_at', 'severity', 'status', 'deviation_value']

    @extend_schema(
        tags=['Monitoring'],
        summary='بازبینی هشدار پایش',
        description='تغییر وضعیت هشدار به بررسی‌شده (REVIEWED).',
        request=AlertReviewSerializer,
        responses={200: MonitoringAlertSerializer}
    )
    @action(detail=True, methods=['post'], url_path='review', permission_classes=[IsAuthenticated, CanManageMonitoring])
    def review_alert(self, request, pk=None):
        serializer = AlertReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = serializer.validated_data.get('note', '')

        with transaction.atomic():
            alert = MonitoringAlert.objects.select_for_update().get(pk=pk)
            old_status = alert.status
            alert.status = AlertStatus.REVIEWED
            alert.reviewed_at = timezone.now()
            alert.reviewed_by = request.user
            if note:
                alert.resolution_note = note
            alert.save()

            log_audit(
                action=AuditAction.UPDATE,
                model_name="MonitoringAlert",
                record_id=alert.id,
                record_repr=str(alert),
                old_values={"status": old_status},
                new_values={"status": AlertStatus.REVIEWED, "note": note},
                reason="بازبینی هشدار پایش از طریق API",
                user=request.user,
                ip_address=get_client_ip(request),
                source="API"
            )

        return api_success_response(
            data=MonitoringAlertSerializer(alert).data,
            message="هشدار با موفقیت بازبینی شد."
        )

    @extend_schema(
        tags=['Monitoring'],
        summary='اقدام و حل هشدار پایش',
        description='ثبت اقدام نهایی و حل هشدار با یادداشت اجباری (RESOLVED).',
        request=AlertResolveSerializer,
        responses={200: MonitoringAlertSerializer}
    )
    @action(detail=True, methods=['post'], url_path='resolve', permission_classes=[IsAuthenticated, CanManageMonitoring])
    def resolve_alert(self, request, pk=None):
        serializer = AlertResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = serializer.validated_data['resolution_note']

        with transaction.atomic():
            alert = MonitoringAlert.objects.select_for_update().get(pk=pk)
            old_status = alert.status
            alert.status = AlertStatus.RESOLVED
            alert.resolution_note = note
            alert.resolved_at = timezone.now()
            alert.resolved_by = request.user
            alert.save()

            log_audit(
                action=AuditAction.UPDATE,
                model_name="MonitoringAlert",
                record_id=alert.id,
                record_repr=str(alert),
                old_values={"status": old_status},
                new_values={"status": AlertStatus.RESOLVED, "resolution_note": note},
                reason=note,
                user=request.user,
                ip_address=get_client_ip(request),
                source="API"
            )

        return api_success_response(
            data=MonitoringAlertSerializer(alert).data,
            message="اقدام و حل هشدار با موفقیت ثبت شد."
        )

    @extend_schema(
        tags=['Monitoring'],
        summary='نادیده‌گرفتن هشدار پایش',
        description='نادیده‌گرفتن هشدار با ثبت دلیل موجه (IGNORED).',
        request=AlertIgnoreSerializer,
        responses={200: MonitoringAlertSerializer}
    )
    @action(detail=True, methods=['post'], url_path='ignore', permission_classes=[IsAuthenticated, CanManageMonitoring])
    def ignore_alert(self, request, pk=None):
        serializer = AlertIgnoreSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data['reason']

        with transaction.atomic():
            alert = MonitoringAlert.objects.select_for_update().get(pk=pk)
            old_status = alert.status
            alert.status = AlertStatus.IGNORED
            alert.resolution_note = reason
            alert.resolved_at = timezone.now()
            alert.resolved_by = request.user
            alert.save()

            log_audit(
                action=AuditAction.UPDATE,
                model_name="MonitoringAlert",
                record_id=alert.id,
                record_repr=str(alert),
                old_values={"status": old_status},
                new_values={"status": AlertStatus.IGNORED, "reason": reason},
                reason=reason,
                user=request.user,
                ip_address=get_client_ip(request),
                source="API"
            )

        return api_success_response(
            data=MonitoringAlertSerializer(alert).data,
            message="هشدار با موفقیت نادیده گرفته شد."
        )

    @extend_schema(
        tags=['Monitoring'],
        summary='خلاصه وضعیت هشدارهای پایش',
        description='آمار کلی هشدارهای باز، بررسی‌شده، حل‌شده، نادیده‌گرفته، بحرانی، بالا و هشدارهای ثبت‌شده امروز.',
    )
    @action(detail=False, methods=['get'], url_path='summary')
    def monitoring_summary(self, request):
        today_g = get_today_gregorian()
        qs = MonitoringAlert.objects.all()

        open_cnt = qs.filter(status=AlertStatus.OPEN).count()
        reviewed_cnt = qs.filter(status=AlertStatus.REVIEWED).count()
        resolved_cnt = qs.filter(status=AlertStatus.RESOLVED).count()
        ignored_cnt = qs.filter(status=AlertStatus.IGNORED).count()

        high_cnt = qs.filter(severity=AlertSeverity.HIGH, status__in=[AlertStatus.OPEN, AlertStatus.REVIEWED]).count()
        critical_cnt = qs.filter(severity=AlertSeverity.CRITICAL, status__in=[AlertStatus.OPEN, AlertStatus.REVIEWED]).count()

        today_cnt = qs.filter(created_at__date=today_g).count()

        by_type_qs = qs.filter(status__in=[AlertStatus.OPEN, AlertStatus.REVIEWED]).values('alert_type').annotate(count=Count('id'))
        by_type = {item['alert_type']: item['count'] for item in by_type_qs}

        return Response({
            "total_today": today_cnt,
            "today": today_cnt,
            "open": open_cnt,
            "reviewed": reviewed_cnt,
            "resolved": resolved_cnt,
            "ignored": ignored_cnt,
            "high": high_cnt,
            "critical": critical_cnt,
            "total_open": open_cnt + reviewed_cnt,
            "by_type": by_type
        })


@extend_schema_view(
    list=extend_schema(tags=['Monitoring'], summary='لیست تنظیمات قوانین پایش'),
    retrieve=extend_schema(tags=['Monitoring'], summary='مشاهده تنظیم قانون پایش'),
    update=extend_schema(tags=['Monitoring'], summary='ویرایش تنظیمات و آستانه‌های قانون پایش'),
    partial_update=extend_schema(tags=['Monitoring'], summary='ویرایش جزیی آستانه‌های قانون پایش'),
)
class MonitoringRuleConfigViewSet(viewsets.ModelViewSet):
    queryset = MonitoringRuleConfig.objects.all().order_by('rule_type')
    serializer_class = MonitoringRuleConfigSerializer
    permission_classes = [IsAdminUserOnly]
    http_method_names = ['get', 'put', 'patch', 'head', 'options']

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)
