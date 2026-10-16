from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction
from django.utils import timezone
from datetime import datetime, time
from decimal import Decimal
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiResponse

from weighbridge.models import WeighTicket, TicketStatus, WeightMode
from weighbridge.services import TicketCalculationService
from audit.services import log_audit
from audit.models import AuditAction
from monitoring.services.anomaly_engine import AnomalyDetectionEngine
from monitoring.services.discrepancy_service import DiscrepancyApprovalService

from api.v1.serializers.ticket_serializers import (
    WeighTicketListSerializer, WeighTicketDetailSerializer,
    WeighTicketCreateSerializer, FirstWeightSerializer,
    SecondWeightSerializer, TicketCompleteSerializer,
    TicketCancelSerializer, TicketCorrectSerializer,
    TicketRevisionSerializer, TicketRevisionRequestSerializer,
    TicketRevisionReviewSerializer
)
from api.v1.filters.ticket_filters import WeighTicketFilter
from api.v1.permissions import (
    CanManageTicket, CanEditCompletedTicket, CanCancelTicket
)
from api.v1.utils import api_success_response, get_client_ip
from core.jalali import get_today_gregorian
from weighbridge.plate_policy import DailyPlatePolicy
from django.shortcuts import get_object_or_404
from masterdata.models import Product, Party, Driver, Vehicle
from rest_framework.exceptions import ValidationError
from django.core.exceptions import PermissionDenied


@extend_schema_view(
    list=extend_schema(
        tags=['Tickets'],
        summary='لیست قبوض باسکول',
        description='دریافت لیست جامع قبوض با قابلیت جستجو، فیلتر پیشرفته (تاریخ، محصول، مشتری، پلاک، وضعیت و...) و صفحه‌بندی.'
    ),
    retrieve=extend_schema(
        tags=['Tickets'],
        summary='جزییات قبض باسکول',
        description='مشاهده اطلاعات کامل قبض، اوزان ناخالص، تارا، خالص، افت، درصد انحراف و مشخصات راننده و ناوگان.'
    ),
    create=extend_schema(
        tags=['Tickets'],
        summary='ثبت و صدور قبض جدید',
        description='صدور اولیه قبض باسکول با تولید خودکار و امن شماره سریال در سمت سرور.'
    ),
)
class WeighTicketViewSet(viewsets.ModelViewSet):
    http_method_names = ["get", "post", "head", "options"]
    queryset = WeighTicket.objects.select_related(
        "operation_type", "party", "product", "driver", "vehicle", "vehicle_type",
        "origin", "destination", "unload_location", "loss_type",
        "first_weight_operator", "second_weight_operator", "cancelled_by", "last_edited_by"
    ).all().order_by("-id")

    def get_queryset(self):
        from django.db.models import Count, Q
        return super().get_queryset().annotate(
            open_alerts_count=Count(
                'monitoring_alerts',
                filter=Q(monitoring_alerts__status__in=['OPEN', 'REVIEWED']),
                distinct=True
            )
        )

    permission_classes = [IsAuthenticated, CanManageTicket]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = WeighTicketFilter
    search_fields = [
        'serial_number', 'license_plate_display', 'waybill_number',
        'driver__full_name', 'driver_name_custom', 'party__name', 'product__name', 'notes'
    ]
    ordering_fields = [
        'id', 'serial_number', 'created_at', 'first_weight_date',
        'gross_weight', 'tare_weight', 'net_weight', 'final_weight'
    ]

    def get_serializer_class(self):
        if self.action == 'list':
            return WeighTicketListSerializer
        elif self.action == 'create':
            return WeighTicketCreateSerializer
        return WeighTicketDetailSerializer

    def create(self, request, *args, **kwargs):
        serializer = WeighTicketCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        with transaction.atomic():
            ticket = WeighTicket(
                **validated,
                first_weight_operator=request.user
            )

            # Dates and Times
            if not ticket.first_weight_date:
                ticket.first_weight_date = get_today_gregorian()
            if not ticket.first_weight_time:
                ticket.first_weight_time = timezone.localtime().time()

            # Pure backend calculation
            calc = TicketCalculationService.calculate_ticket(
                first_weight=ticket.first_weight,
                second_weight=ticket.second_weight,
                sent_weight=ticket.sent_weight,
                loss_percent=ticket.loss_percent,
                manual_loss_weight=ticket.loss_weight if ticket.is_loss_overridden else None,
                product=ticket.product,
                is_loss_overridden=ticket.is_loss_overridden
            )

            ticket.gross_weight = calc["gross_weight"]
            ticket.tare_weight = calc["tare_weight"]
            ticket.net_weight = calc["net_weight"]
            ticket.loss_percent = calc["loss_percent"]
            ticket.loss_weight = calc["loss_weight"]
            ticket.final_weight = calc["final_weight"]
            ticket.weight_difference = calc["weight_difference"]
            ticket.weight_difference_percent = calc["weight_difference_percent"]
            ticket.is_tolerance_exceeded = calc["is_tolerance_exceeded"]

            # Second weight logic if provided during creation
            if ticket.second_weight and ticket.second_weight > 0:
                val_res = DiscrepancyApprovalService.validate_ticket_finalization(ticket, trial_weights=calc)
                if not val_res["valid"]:
                    return Response(
                        {
                            "success": False,
                            "error": {
                                "code": "DISCREPANCY_APPROVAL_REQUIRED",
                                "message": f"تکمیل مستقیم قبض امکان‌پذیر نیست: {val_res['message']}",
                                "details": {
                                    "blocking_alerts": val_res["blocking_alerts"]
                                }
                            }
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )
                ticket.second_weight_date = get_today_gregorian()
                ticket.second_weight_time = timezone.localtime().time()
                ticket.second_weight_operator = request.user
                ticket.status = TicketStatus.COMPLETED
            else:
                ticket.status = TicketStatus.WAITING_SECOND

            DailyPlatePolicy.save(ticket, user=request.user, assign_serial=True)

            # Audit log
            log_audit(
                action=AuditAction.CREATE,
                model_name="WeighTicket",
                record_id=ticket.id,
                record_repr=f"قبض شماره {ticket.serial_number}",
                new_values={
                    "serial": ticket.serial_number,
                    "plate": ticket.license_plate_display,
                    "first_weight": float(ticket.first_weight),
                    "status": ticket.status,
                    "source": "API"
                },
                reason="ثبت اولیه قبض از طریق API",
                user=request.user,
                ip_address=get_client_ip(request)
            )

            # Monitoring evaluation
            AnomalyDetectionEngine.run_for_ticket(ticket)

        output_serializer = WeighTicketDetailSerializer(ticket)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=['Tickets'],
        summary='ثبت وزن اول',
        description='ثبت مقدار وزن اول برای یک قبض در جریان یا اصلاح آن با اعتبارسنجی و ثبت ممیزی.',
        request=FirstWeightSerializer,
        responses={200: WeighTicketDetailSerializer}
    )
    @action(detail=True, methods=['post'], url_path='first-weight')
    def record_first_weight(self, request, pk=None):
        serializer = FirstWeightSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        w1 = serializer.validated_data['weight']
        w_date = serializer.validated_data.get('date') or get_today_gregorian()
        w_time = serializer.validated_data.get('time') or timezone.localtime().time()

        with transaction.atomic():
            ticket = get_object_or_404(WeighTicket.objects.select_for_update(), pk=pk)

            if ticket.status == TicketStatus.CANCELLED:
                raise ValidationError("امکان ثبت وزن برای قبض ابطال‌شده وجود ندارد.")
            if ticket.status == TicketStatus.COMPLETED:
                return Response(
                    {
                        "success": False,
                        "error": {
                            "code": "TICKET_ALREADY_COMPLETED",
                            "message": "این قبض نهایی شده است و تغییر مستقیم وزن اول مجاز نیست. لطفاً از فرآیند بازنگری (Revision) استفاده فرمایید."
                        }
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            old_w1 = float(ticket.first_weight)
            ticket.first_weight = w1
            ticket.first_weight_date = w_date
            ticket.first_weight_time = w_time
            ticket.first_weight_operator = request.user
            if ticket.status == TicketStatus.WAITING_FIRST:
                ticket.status = TicketStatus.WAITING_SECOND

            # Recalculate
            calc = TicketCalculationService.calculate_ticket(
                first_weight=ticket.first_weight,
                second_weight=ticket.second_weight,
                sent_weight=ticket.sent_weight,
                loss_percent=ticket.loss_percent,
                manual_loss_weight=ticket.loss_weight if ticket.is_loss_overridden else None,
                product=ticket.product,
                is_loss_overridden=ticket.is_loss_overridden
            )
            ticket.gross_weight = calc["gross_weight"]
            ticket.tare_weight = calc["tare_weight"]
            ticket.net_weight = calc["net_weight"]
            ticket.loss_percent = calc["loss_percent"]
            ticket.loss_weight = calc["loss_weight"]
            ticket.final_weight = calc["final_weight"]
            ticket.weight_difference = calc["weight_difference"]
            ticket.weight_difference_percent = calc["weight_difference_percent"]
            ticket.is_tolerance_exceeded = calc["is_tolerance_exceeded"]

            # Invalidate any stale approval if weights changed
            DiscrepancyApprovalService.check_and_invalidate_stale_approvals(
                ticket,
                calc["gross_weight"],
                calc["tare_weight"],
                calc["net_weight"],
                current_product=ticket.product,
                current_sent_weight=ticket.sent_weight,
            )

            DailyPlatePolicy.save(ticket, user=request.user)

            log_audit(
                action=AuditAction.OVERRIDE_WEIGHT if old_w1 > 0 else AuditAction.UPDATE,
                model_name="WeighTicket",
                record_id=ticket.id,
                record_repr=f"قبض شماره {ticket.serial_number}",
                old_values={"first_weight": old_w1},
                new_values={"first_weight": float(w1)},
                reason="ثبت/اصلاح وزن اول از طریق API",
                user=request.user,
                ip_address=get_client_ip(request)
            )

            AnomalyDetectionEngine.run_for_ticket(ticket)

        return api_success_response(
            data=WeighTicketDetailSerializer(ticket).data,
            message=f"وزن اول قبض {ticket.serial_number} با موفقیت ثبت شد."
        )

    @extend_schema(
        tags=['Tickets'],
        summary='ثبت وزن دوم و تکمیل فرایند',
        description='ثبت مقدار وزن دوم، محاسبه آنی وزن ناخالص، تارا، خالص، افت و وزن نهایی و تغییر وضعیت قبض به تکمیل‌شده.',
        request=SecondWeightSerializer,
        responses={200: WeighTicketDetailSerializer}
    )
    @action(detail=True, methods=['post'], url_path='second-weight')
    def record_second_weight(self, request, pk=None):
        serializer = SecondWeightSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        w2 = serializer.validated_data['weight']
        w_date = serializer.validated_data.get('date') or get_today_gregorian()
        w_time = serializer.validated_data.get('time') or timezone.localtime().time()
        loss_pct = serializer.validated_data.get('loss_percent')
        loss_type = serializer.validated_data.get('loss_type')

        with transaction.atomic():
            ticket = get_object_or_404(WeighTicket.objects.select_for_update(), pk=pk)

            if ticket.status == TicketStatus.CANCELLED:
                return Response(
                    {
                        "success": False,
                        "error": {
                            "code": "INVALID_STATUS_TRANSITION",
                            "message": "امکان ثبت وزن برای قبض باطل‌شده وجود ندارد."
                        }
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            if ticket.status == TicketStatus.COMPLETED:
                return Response(
                    {
                        "success": False,
                        "error": {
                            "code": "TICKET_ALREADY_COMPLETED",
                            "message": "این قبض قبلاً تکمیل شده است و تغییر مستقیم وزن دوم مجاز نیست. لطفاً از فرآیند بازنگری (Revision) استفاده فرمایید."
                        }
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            if not ticket.first_weight or ticket.first_weight <= 0:
                return Response(
                    {
                        "success": False,
                        "error": {
                            "code": "VALIDATION_ERROR",
                            "message": "ابتدا باید وزن اول معتبر برای این قبض ثبت شود."
                        }
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            ticket.second_weight = w2
            ticket.second_weight_date = w_date
            ticket.second_weight_time = w_time
            ticket.second_weight_operator = request.user

            if loss_pct is not None:
                ticket.loss_percent = loss_pct
            if loss_type:
                ticket.loss_type = loss_type

            # Calculate Gross, Tare, Net, Loss, Final
            calc = TicketCalculationService.calculate_ticket(
                first_weight=ticket.first_weight,
                second_weight=ticket.second_weight,
                sent_weight=ticket.sent_weight,
                loss_percent=ticket.loss_percent,
                manual_loss_weight=ticket.loss_weight if ticket.is_loss_overridden else None,
                product=ticket.product,
                is_loss_overridden=ticket.is_loss_overridden
            )

            ticket.gross_weight = calc["gross_weight"]
            ticket.tare_weight = calc["tare_weight"]
            ticket.net_weight = calc["net_weight"]
            ticket.loss_percent = calc["loss_percent"]
            ticket.loss_weight = calc["loss_weight"]
            ticket.final_weight = calc["final_weight"]
            ticket.weight_difference = calc["weight_difference"]
            ticket.weight_difference_percent = calc["weight_difference_percent"]
            ticket.is_tolerance_exceeded = calc["is_tolerance_exceeded"]

            # Phase 3.1 Hotfix: Invalidate any stale approval if parameters changed
            DiscrepancyApprovalService.check_and_invalidate_stale_approvals(
                ticket,
                calc["gross_weight"],
                calc["tare_weight"],
                calc["net_weight"],
                current_product=ticket.product,
                current_sent_weight=ticket.sent_weight,
            )

            # Central domain validation prior to setting COMPLETED
            val_res = DiscrepancyApprovalService.validate_ticket_finalization(ticket, trial_weights=calc)
            if not val_res["valid"]:
                return Response(
                    {
                        "success": False,
                        "error": {
                            "code": "DISCREPANCY_APPROVAL_REQUIRED",
                            "message": f"ثبت وزن دوم و تکمیل قبض نیازمند تأیید سرپرست است: {val_res['message']}",
                            "details": {
                                "blocking_alerts": val_res["blocking_alerts"]
                            }
                        }
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            ticket.status = TicketStatus.COMPLETED
            DailyPlatePolicy.save(ticket, user=request.user)

            log_audit(
                action=AuditAction.STATUS_CHANGE,
                model_name="WeighTicket",
                record_id=ticket.id,
                record_repr=f"قبض شماره {ticket.serial_number}",
                new_values={
                    "second_weight": float(ticket.second_weight),
                    "gross_weight": float(ticket.gross_weight),
                    "tare_weight": float(ticket.tare_weight),
                    "net_weight": float(ticket.net_weight),
                    "final_weight": float(ticket.final_weight),
                    "status": ticket.status,
                    "source": "API"
                },
                reason="ثبت وزن دوم و تکمیل قبض از طریق API",
                user=request.user,
                ip_address=get_client_ip(request)
            )

            AnomalyDetectionEngine.run_for_ticket(ticket)

        return api_success_response(
            data=WeighTicketDetailSerializer(ticket).data,
            message=f"وزن دوم قبض {ticket.serial_number} ثبت و سند تکمیل گردید."
        )

    @extend_schema(
        tags=['Tickets'],
        summary='تکمیل نهایی قبض',
        description='نهایی‌سازی سند باسکول پس از بررسی کامل بودن اوزان و اطلاعات.',
        request=TicketCompleteSerializer,
        responses={200: WeighTicketDetailSerializer}
    )
    @action(detail=True, methods=['post'], url_path='complete')
    def complete_ticket(self, request, pk=None):
        with transaction.atomic():
            ticket = get_object_or_404(WeighTicket.objects.select_for_update(), pk=pk)

            if ticket.status == TicketStatus.CANCELLED:
                raise ValidationError("امکان تکمیل قبض ابطال‌شده وجود ندارد.")
            if ticket.status == TicketStatus.COMPLETED:
                return api_success_response(
                    data=WeighTicketDetailSerializer(ticket).data,
                    message="این قبض پیش از این تکمیل شده است."
                )

            if not ticket.first_weight or not ticket.second_weight:
                return Response(
                    {
                        "success": False,
                        "error": {
                            "code": "VALIDATION_ERROR",
                            "message": "برای تکمیل قبض باید هر دو وزن اول و دوم ثبت شده باشند."
                        }
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Recalculate and update weights prior to finalization
            calc = TicketCalculationService.calculate_ticket(
                first_weight=ticket.first_weight,
                second_weight=ticket.second_weight,
                sent_weight=ticket.sent_weight,
                loss_percent=ticket.loss_percent,
                manual_loss_weight=ticket.loss_weight if ticket.is_loss_overridden else None,
                product=ticket.product,
                is_loss_overridden=ticket.is_loss_overridden
            )
            ticket.gross_weight = calc["gross_weight"]
            ticket.tare_weight = calc["tare_weight"]
            ticket.net_weight = calc["net_weight"]
            ticket.loss_percent = calc["loss_percent"]
            ticket.loss_weight = calc["loss_weight"]
            ticket.final_weight = calc["final_weight"]
            ticket.weight_difference = calc["weight_difference"]
            ticket.weight_difference_percent = calc["weight_difference_percent"]
            ticket.is_tolerance_exceeded = calc["is_tolerance_exceeded"]

            # Phase 3.1 Hotfix: Invalidate stale approval if any parameters are mismatched
            DiscrepancyApprovalService.check_and_invalidate_stale_approvals(
                ticket,
                calc["gross_weight"],
                calc["tare_weight"],
                calc["net_weight"],
                current_product=ticket.product,
                current_sent_weight=ticket.sent_weight,
            )

            # Central domain validation prior to setting COMPLETED
            val_res = DiscrepancyApprovalService.validate_ticket_finalization(ticket, trial_weights=calc)
            if not val_res["valid"]:
                return Response(
                    {
                        "success": False,
                        "error": {
                            "code": "DISCREPANCY_APPROVAL_REQUIRED",
                            "message": f"تکمیل نهایی قبض نیازمند تأیید سرپرست است: {val_res['message']}",
                            "details": {
                                "blocking_alerts": val_res["blocking_alerts"]
                            }
                        }
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            notes = request.data.get('notes', '')
            if notes:
                ticket.notes = (ticket.notes + "\n" + notes).strip()

            ticket.status = TicketStatus.COMPLETED
            DailyPlatePolicy.save(ticket, user=request.user)

            log_audit(
                action=AuditAction.STATUS_CHANGE,
                model_name="WeighTicket",
                record_id=ticket.id,
                record_repr=f"قبض شماره {ticket.serial_number}",
                new_values={"status": "completed"},
                reason="تکمیل نهایی سند از طریق API",
                user=request.user,
                ip_address=get_client_ip(request)
            )

        return api_success_response(
            data=WeighTicketDetailSerializer(ticket).data,
            message=f"قبض شماره {ticket.serial_number} با موفقیت تکمیل شد."
        )

    @extend_schema(
        tags=['Tickets'],
        summary='ابطال / لغو قبض',
        description='ابطال سند باسکول با الزام ثبت دلیل ابطال (عدم امکان حذف فیزیکی سند جهت حفظ ممیزی).',
        request=TicketCancelSerializer,
        responses={200: WeighTicketDetailSerializer}
    )
    @action(detail=True, methods=['post'], url_path='cancel', permission_classes=[IsAuthenticated, CanCancelTicket])
    def cancel_ticket(self, request, pk=None):
        serializer = TicketCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data['reason']

        with transaction.atomic():
            ticket = get_object_or_404(WeighTicket.objects.select_for_update(), pk=pk)
            if ticket.status == TicketStatus.CANCELLED:
                return Response(
                    {
                        "success": False,
                        "error": {
                            "code": "INVALID_STATUS_TRANSITION",
                            "message": "این قبض قبلاً ابطال شده است."
                        }
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            old_status = ticket.status
            ticket.status = TicketStatus.CANCELLED
            ticket.cancellation_reason = reason
            ticket.cancelled_by = request.user
            ticket.cancelled_at = timezone.now()
            DailyPlatePolicy.save(ticket, user=request.user)

            log_audit(
                action=AuditAction.CANCEL,
                model_name="WeighTicket",
                record_id=ticket.id,
                record_repr=f"قبض شماره {ticket.serial_number}",
                old_values={"status": old_status},
                new_values={"status": TicketStatus.CANCELLED, "reason": reason},
                reason=reason,
                user=request.user,
                ip_address=get_client_ip(request),
                source="API"
            )

        return api_success_response(
            data=WeighTicketDetailSerializer(ticket).data,
            message=f"قبض شماره {ticket.serial_number} با موفقیت ابطال گردید."
        )

    @extend_schema(
        tags=['Tickets'],
        summary='اصلاح مدیریتی قبض',
        description='اصلاح مقادیر حساس (مانند اوزان، محصول، طرف حساب) توسط مدیر مجاز به همراه ثبت دقیق مقادیر قبل و بعد در Audit Log.',
        request=TicketCorrectSerializer,
        responses={200: WeighTicketDetailSerializer}
    )
    @action(detail=True, methods=['post'], url_path='correct', permission_classes=[IsAuthenticated, CanEditCompletedTicket])
    def correct_ticket(self, request, pk=None):
        serializer = TicketCorrectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        field = serializer.validated_data['field']
        new_val = serializer.validated_data['new_value']
        reason = serializer.validated_data['reason']

        with transaction.atomic():
            ticket = get_object_or_404(WeighTicket.objects.select_for_update(), pk=pk)

            old_values = {
                "field": field,
                "old_value": str(getattr(ticket, field, None)),
                "gross_weight": float(ticket.gross_weight),
                "tare_weight": float(ticket.tare_weight),
                "net_weight": float(ticket.net_weight),
                "final_weight": float(ticket.final_weight),
            }

            if ticket.status == TicketStatus.COMPLETED:
                from weighbridge.revision_service import TicketRevisionService
                if field in TicketRevisionService.IMMUTABLE_FIELDS:
                    return Response(
                        {
                            "success": False,
                            "error": {
                                "code": "IMMUTABLE_FIELD",
                                "message": f"فیلد «{field}» از فیلدهای هویتی و ثبتی باسکول بوده و غیرقابل‌تغییر است."
                            }
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )

                if field in TicketRevisionService.CONTROLLED_FIELDS:
                    prop_data = {field: new_val}
                    try:
                        revision = TicketRevisionService.request_revision(
                            ticket=ticket,
                            requester=request.user,
                            proposed_data=prop_data,
                            reason=reason,
                            client_ip=get_client_ip(request)
                        )
                        return Response(
                            {
                                "success": True,
                                "message": f"درخواست بازنگری برای قبض تکمیل‌شده {ticket.serial_number} با موفقیت ثبت شد و در صف بررسی سرپرست قرار گرفت.",
                                "data": {
                                    "revision_id": str(revision.id),
                                    "status": revision.status,
                                    "changed_fields": revision.changed_fields,
                                    "ticket_id": ticket.id,
                                    "current_revision_number": ticket.current_revision_number,
                                }
                            },
                            status=status.HTTP_202_ACCEPTED
                        )
                    except ValidationError as exc:
                        msg = exc.messages[0] if hasattr(exc, "messages") else str(exc)
                        return Response(
                            {"success": False, "error": {"code": "REVISION_VALIDATION_ERROR", "message": msg}},
                            status=status.HTTP_400_BAD_REQUEST
                        )

                # Non-material field update
                setattr(ticket, field, str(new_val))
                ticket.last_edited_by = request.user
                ticket.last_edit_reason = reason
                ticket.save(update_fields=[field, 'last_edited_by', 'last_edit_reason'])
                log_audit(
                    action=AuditAction.UPDATE,
                    model_name="WeighTicket",
                    record_id=ticket.id,
                    record_repr=f"قبض شماره {ticket.serial_number}",
                    old_values=old_values,
                    new_values={"field": field, "new_value": str(new_val)},
                    reason=reason,
                    user=request.user,
                    ip_address=get_client_ip(request),
                    source="API"
                )
                return api_success_response(
                    data=WeighTicketDetailSerializer(ticket).data,
                    message=f"فیلد اداری «{field}» برای قبض {ticket.serial_number} با موفقیت ویرایش شد."
                )

            if field in ['first_weight', 'second_weight', 'sent_weight', 'loss_percent', 'loss_weight']:
                setattr(ticket, field, Decimal(str(new_val)))
                if field == 'loss_weight':
                    ticket.is_loss_overridden = True
                    ticket.loss_override_reason = reason
            elif field == 'product':
                ticket.product = get_object_or_404(Product, pk=new_val)
            elif field == 'party':
                ticket.party = get_object_or_404(Party, pk=new_val)
            elif field == 'driver':
                ticket.driver = get_object_or_404(Driver, pk=new_val)
            elif field == 'vehicle':
                ticket.vehicle = get_object_or_404(Vehicle, pk=new_val)
            else:
                setattr(ticket, field, str(new_val))

            ticket.last_edited_by = request.user
            ticket.last_edit_reason = reason

            # Recalculate weights
            calc = TicketCalculationService.calculate_ticket(
                first_weight=ticket.first_weight,
                second_weight=ticket.second_weight,
                sent_weight=ticket.sent_weight,
                loss_percent=ticket.loss_percent,
                manual_loss_weight=ticket.loss_weight if ticket.is_loss_overridden else None,
                product=ticket.product,
                is_loss_overridden=ticket.is_loss_overridden
            )

            ticket.gross_weight = calc["gross_weight"]
            ticket.tare_weight = calc["tare_weight"]
            ticket.net_weight = calc["net_weight"]
            ticket.loss_percent = calc["loss_percent"]
            ticket.loss_weight = calc["loss_weight"]
            ticket.final_weight = calc["final_weight"]
            ticket.weight_difference = calc["weight_difference"]
            ticket.weight_difference_percent = calc["weight_difference_percent"]
            ticket.is_tolerance_exceeded = calc["is_tolerance_exceeded"]

            # Phase 3.1 Hotfix: Invalidate stale approval if weights, product, or sent_weight were modified
            DiscrepancyApprovalService.check_and_invalidate_stale_approvals(
                ticket,
                calc["gross_weight"],
                calc["tare_weight"],
                calc["net_weight"],
                current_product=ticket.product,
                current_sent_weight=ticket.sent_weight,
            )

            # Re-evaluate discrepancies after material edit (for in-flight tickets)
            eval_res = DiscrepancyApprovalService.evaluate_ticket_discrepancies(ticket, trial_weights=calc)
            if ticket.status != TicketStatus.COMPLETED and not eval_res["can_finalize"]:
                ticket.status = TicketStatus.WAITING_SECOND

            DailyPlatePolicy.save(ticket, user=request.user)

            new_values = {
                "field": field,
                "new_value": str(new_val),
                "gross_weight": float(ticket.gross_weight),
                "tare_weight": float(ticket.tare_weight),
                "net_weight": float(ticket.net_weight),
                "final_weight": float(ticket.final_weight),
            }

            audit_action = AuditAction.UPDATE
            if field in ['loss_weight', 'loss_percent']:
                audit_action = AuditAction.OVERRIDE_LOSS
            elif field in ['first_weight', 'second_weight', 'sent_weight']:
                audit_action = AuditAction.OVERRIDE_WEIGHT

            log_audit(
                action=audit_action,
                model_name="WeighTicket",
                record_id=ticket.id,
                record_repr=f"قبض شماره {ticket.serial_number}",
                old_values=old_values,
                new_values=new_values,
                reason=reason,
                user=request.user,
                ip_address=get_client_ip(request),
                source="API"
            )

            AnomalyDetectionEngine.run_for_ticket(ticket)

        return api_success_response(
            data=WeighTicketDetailSerializer(ticket).data,
            message=f"قبض شماره {ticket.serial_number} با موفقیت اصلاح گردید."
        )

    @extend_schema(
        tags=['Tickets'],
        summary='قبوض باز و در جریان',
        description='لیست خودروها و قبوضی که فرایند توزین آن‌ها هنوز تکمیل نشده است.',
    )
    @action(detail=False, methods=['get'], url_path='open')
    def open_tickets(self, request):
        qs = self.get_queryset().filter(
            status__in=[TicketStatus.WAITING_FIRST, TicketStatus.FIRST_REGISTERED, TicketStatus.WAITING_SECOND]
        )
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = WeighTicketListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = WeighTicketListSerializer(qs, many=True)
        return Response(serializer.data)

    @extend_schema(
        tags=['Tickets'],
        summary='خودروهای در انتظار وزن دوم (داخل محوطه)',
        description='لیست خودروهایی که وزن اول آن‌ها ثبت شده و هم‌اکنون داخل محوطه شرکت منتظر توزین دوم هستند به همراه مدت زمان توقف.',
    )
    @action(detail=False, methods=['get'], url_path='waiting-second-weight')
    def waiting_second_weight(self, request):
        qs = self.get_queryset().filter(
            status__in=[TicketStatus.WAITING_SECOND, TicketStatus.FIRST_REGISTERED]
        )
        now = timezone.now()
        results = []
        for t in qs:
            diff_mins = int((now - t.created_at).total_seconds() / 60)
            hours = diff_mins // 60
            mins = diff_mins % 60
            duration_str = f"{hours} ساعت و {mins} دقیقه" if hours > 0 else f"{mins} دقیقه"
            
            data = WeighTicketListSerializer(t).data
            data['waiting_duration_minutes'] = diff_mins
            data['waiting_duration_display'] = duration_str
            data['is_long_wait'] = diff_mins > 180
            results.append(data)

        return Response({
            "count": len(results),
            "results": results
        })

    @extend_schema(
        tags=['Tickets'],
        summary='تحلیل پایش هوشمند و کشف مغایرت قبض',
        description='دریافت امتیاز ریسک (0-100)، سطح ریسک، لیست هشدارهای فعال و مقایسه آماری با سوابق تاریخی خودرو و طرف حساب.',
    )
    @action(detail=True, methods=['get'], url_path='analysis')
    def ticket_analysis(self, request, pk=None):
        ticket = self.get_object()
        summary = AnomalyDetectionEngine.get_ticket_analysis_summary(ticket)
        from api.v1.serializers.monitoring_serializers import MonitoringAlertSerializer

        return Response({
            "ticket_id": ticket.id,
            "serial_number": ticket.serial_number,
            "risk_score": summary["risk_score"],
            "risk_level": summary["risk_level"],
            "has_critical": summary["has_critical"],
            "has_high": summary["has_high"],
            "open_alerts_count": summary["open_alerts_count"],
            "alerts": MonitoringAlertSerializer(summary["all_alerts"], many=True).data
        })

    @extend_schema(
        tags=['Ticket Revisions'],
        summary='فهرست بازنگری‌های یک قبض',
        responses={200: TicketRevisionSerializer(many=True)}
    )
    @action(detail=True, methods=['get'], url_path='revisions', permission_classes=[IsAuthenticated])
    def get_revisions(self, request, pk=None):
        ticket = get_object_or_404(WeighTicket, pk=pk)
        from weighbridge.revision_service import TicketRevisionService
        revisions = TicketRevisionService.get_revision_history(ticket)
        return Response({
            "success": True,
            "data": TicketRevisionSerializer(revisions, many=True).data
        })

    @extend_schema(
        tags=['Ticket Revisions'],
        summary='ثبت درخواست بازنگری برای قبض تکمیل‌شده',
        request=TicketRevisionRequestSerializer,
        responses={201: TicketRevisionSerializer}
    )
    @action(detail=True, methods=['post'], url_path='revisions/request', permission_classes=[IsAuthenticated, CanEditCompletedTicket])
    def request_revision(self, request, pk=None):
        ticket = get_object_or_404(WeighTicket, pk=pk)
        serializer = TicketRevisionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data['reason']
        proposed_data = serializer.validated_data['proposed_data']

        from weighbridge.revision_service import TicketRevisionService
        try:
            rev = TicketRevisionService.request_revision(
                ticket=ticket,
                requester=request.user,
                proposed_data=proposed_data,
                reason=reason,
                client_ip=get_client_ip(request)
            )
            return Response({
                "success": True,
                "message": "درخواست بازنگری با موفقیت ثبت شد.",
                "data": TicketRevisionSerializer(rev).data
            }, status=status.HTTP_201_CREATED)
        except ValidationError as exc:
            msg = exc.messages[0] if hasattr(exc, "messages") else str(exc)
            return Response({"success": False, "error": {"code": "VALIDATION_ERROR", "message": msg}}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['Ticket Revisions'],
        summary='تأیید و اعمال بازنگری قبض توسط سرپرست',
        request=TicketRevisionReviewSerializer,
        responses={200: TicketRevisionSerializer}
    )
    @action(detail=False, methods=['post'], url_path='revisions/(?P<revision_id>[^/.]+)/approve', permission_classes=[IsAuthenticated, CanEditCompletedTicket])
    def approve_revision(self, request, revision_id=None):
        serializer = TicketRevisionReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        review_reason = serializer.validated_data.get('review_reason', '')

        from weighbridge.revision_service import TicketRevisionService
        try:
            rev = TicketRevisionService.approve_revision(
                revision=revision_id,
                reviewer=request.user,
                review_reason=review_reason,
                auto_apply=True,
                client_ip=get_client_ip(request)
            )
            return Response({
                "success": True,
                "message": f"بازنگری ویرایش {rev.revision_number} با موفقیت تأیید و بر قبض اعمال شد.",
                "data": TicketRevisionSerializer(rev).data
            })
        except PermissionDenied as exc:
            return Response({"success": False, "error": {"code": "PERMISSION_DENIED", "message": str(exc)}}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            msg = exc.messages[0] if hasattr(exc, "messages") else str(exc)
            return Response({"success": False, "error": {"code": "VALIDATION_ERROR", "message": msg}}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['Ticket Revisions'],
        summary='رد درخواست بازنگری توسط سرپرست',
        request=TicketRevisionReviewSerializer,
        responses={200: TicketRevisionSerializer}
    )
    @action(detail=False, methods=['post'], url_path='revisions/(?P<revision_id>[^/.]+)/reject', permission_classes=[IsAuthenticated, CanEditCompletedTicket])
    def reject_revision(self, request, revision_id=None):
        serializer = TicketRevisionReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        review_reason = serializer.validated_data.get('review_reason', '')

        from weighbridge.revision_service import TicketRevisionService
        try:
            rev = TicketRevisionService.reject_revision(
                revision=revision_id,
                reviewer=request.user,
                review_reason=review_reason,
                client_ip=get_client_ip(request)
            )
            return Response({
                "success": True,
                "message": "درخواست بازنگری با موفقیت رد شد.",
                "data": TicketRevisionSerializer(rev).data
            })
        except PermissionDenied as exc:
            return Response({"success": False, "error": {"code": "PERMISSION_DENIED", "message": str(exc)}}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            msg = exc.messages[0] if hasattr(exc, "messages") else str(exc)
            return Response({"success": False, "error": {"code": "VALIDATION_ERROR", "message": msg}}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['Ticket Revisions'],
        summary='انصراف از درخواست بازنگری توسط متقاضی',
        request=TicketRevisionReviewSerializer,
        responses={200: TicketRevisionSerializer}
    )
    @action(detail=False, methods=['post'], url_path='revisions/(?P<revision_id>[^/.]+)/withdraw', permission_classes=[IsAuthenticated])
    def withdraw_revision(self, request, revision_id=None):
        serializer = TicketRevisionReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data.get('review_reason', '')

        from weighbridge.revision_service import TicketRevisionService
        try:
            rev = TicketRevisionService.withdraw_revision(
                revision=revision_id,
                user=request.user,
                reason=reason,
                client_ip=get_client_ip(request)
            )
            return Response({
                "success": True,
                "message": "درخواست بازنگری با موفقیت پس گرفته شد.",
                "data": TicketRevisionSerializer(rev).data
            })
        except PermissionDenied as exc:
            return Response({"success": False, "error": {"code": "PERMISSION_DENIED", "message": str(exc)}}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            msg = exc.messages[0] if hasattr(exc, "messages") else str(exc)
            return Response({"success": False, "error": {"code": "VALIDATION_ERROR", "message": msg}}, status=status.HTTP_400_BAD_REQUEST)
