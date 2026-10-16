from django.contrib import admin
from django.core.exceptions import ValidationError
from weighbridge.models import WeighTicket, EmergencyWeighTicket, TicketSequence, TicketStatus, TicketRevision
from weighbridge.services import TicketCalculationService
from monitoring.services.discrepancy_service import DiscrepancyApprovalService

@admin.register(WeighTicket)
class WeighTicketAdmin(admin.ModelAdmin):
    list_display = [
        "serial_number", "status", "party", "product", "license_plate_display",
        "driver_display", "gross_weight", "tare_weight", "net_weight", "final_weight",
        "first_weight_date", "created_at"
    ]
    list_filter = ["status", "weight_mode", "operation_type", "product", "is_tolerance_exceeded", "first_weight_date"]
    search_fields = ["serial_number", "license_plate_display", "waybill_number", "party__name", "product__name", "driver__full_name"]
    readonly_fields = ["gross_weight", "tare_weight", "net_weight", "final_weight", "weight_difference", "weight_difference_percent", "created_at", "updated_at"]
    ordering = ["-id"]

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        ro = list(self.readonly_fields)
        if obj:
            ro.extend(["serial_number", "current_revision_number", "original_net_weight"])
            if obj.status in [TicketStatus.COMPLETED, TicketStatus.CANCELLED]:
                # ALL users (including superusers) are blocked from mutating material/immutable fields in Admin
                return [f.name for f in self.model._meta.fields if f.name != "notes"]
        return ro

    def save_model(self, request, obj, form, change):
        is_already_completed = False
        if change and obj.pk:
            old_ticket = WeighTicket.objects.get(pk=obj.pk)
            if old_ticket.status in [TicketStatus.COMPLETED, TicketStatus.CANCELLED]:
                is_already_completed = True
                from weighbridge.revision_service import TicketRevisionService
                for field in TicketRevisionService.IMMUTABLE_FIELDS | TicketRevisionService.CONTROLLED_FIELDS:
                    if hasattr(old_ticket, field):
                        old_v = getattr(old_ticket, field)
                        new_v = getattr(obj, field)
                        if hasattr(old_v, "pk"):
                            old_v = old_v.pk
                        if hasattr(new_v, "pk"):
                            new_v = new_v.pk
                        if str(old_v or "") != str(new_v or ""):
                            raise ValidationError(
                                f"ویرایش مستقیم فیلد «{field}» برای قبض نهایی‌شده در پنل مدیریت مجاز نیست. "
                                "برای اصلاح اطلاعات، لطفاً از فرآیند رسمی بازنگری قبض (Ticket Revision) استفاده فرمایید."
                            )
                if old_ticket.notes != obj.notes:
                    from audit.utils import log_audit
                    from audit.models import AuditAction
                    log_audit(
                        action=AuditAction.UPDATE,
                        model_name="WeighTicket",
                        record_id=str(obj.id),
                        record_repr=f"قبض شماره {obj.serial_number}",
                        user=request.user,
                        old_values={"notes": old_ticket.notes},
                        new_values={"notes": obj.notes},
                        reason="ویرایش یادداشت‌ها از پنل مدیریت جنگو",
                        source="DjangoAdmin"
                    )

        if obj.first_weight and obj.second_weight and not is_already_completed:
            calc = TicketCalculationService.calculate_ticket(
                first_weight=obj.first_weight,
                second_weight=obj.second_weight,
                sent_weight=obj.sent_weight,
                loss_percent=obj.loss_percent,
                manual_loss_weight=obj.loss_weight if obj.is_loss_overridden else None,
                product=obj.product,
                is_loss_overridden=obj.is_loss_overridden
            )
            obj.gross_weight = calc["gross_weight"]
            obj.tare_weight = calc["tare_weight"]
            obj.net_weight = calc["net_weight"]
            obj.loss_percent = calc["loss_percent"]
            obj.loss_weight = calc["loss_weight"]
            obj.final_weight = calc["final_weight"]
            obj.weight_difference = calc["weight_difference"]
            obj.weight_difference_percent = calc["weight_difference_percent"]
            obj.is_tolerance_exceeded = calc["is_tolerance_exceeded"]

            DiscrepancyApprovalService.check_and_invalidate_stale_approvals(
                obj,
                calc["gross_weight"],
                calc["tare_weight"],
                calc["net_weight"],
                current_product=obj.product,
                current_sent_weight=obj.sent_weight,
            )

        if obj.status == TicketStatus.COMPLETED and not is_already_completed:
            val_res = DiscrepancyApprovalService.validate_ticket_finalization(obj)
            if not val_res["valid"]:
                raise ValidationError(
                    f"امکان تکمیل یا ذخیره قبض در وضعیت تکمیل‌شده به دلیل مغایرت تاییدنشده وجود ندارد: {val_res['message']}"
                )

        from weighbridge.plate_policy import DailyPlatePolicy
        DailyPlatePolicy.save(obj, user=request.user)


@admin.register(TicketRevision)
class TicketRevisionAdmin(admin.ModelAdmin):
    list_display = [
        "id", "ticket", "revision_number", "status",
        "requested_by", "requested_at", "reviewed_by", "reviewed_at", "applied_at"
    ]
    list_filter = ["status", "requested_at"]
    search_fields = ["ticket__serial_number", "reason", "requested_by__username", "reviewed_by__username"]
    ordering = ["-requested_at"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]


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

