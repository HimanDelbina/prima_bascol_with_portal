from django.contrib import admin
from shifts.models import (
    WorkShift, ShiftSession, ShiftOperatorAssignment, ShiftExceptionLog,
    ShiftHandover, ShiftHandoverItem, ShiftHandoverStatus
)


class ShiftOperatorAssignmentInline(admin.TabularInline):
    model = ShiftOperatorAssignment
    extra = 0
    fields = ["operator", "role", "status", "check_in_time", "check_out_time", "is_substitution"]
    readonly_fields = ["check_in_time", "check_out_time"]


class ShiftHandoverItemInline(admin.TabularInline):
    model = ShiftHandoverItem
    extra = 0
    fields = ["category", "item_identifier", "item_title", "source_status", "source_timestamp", "created_at"]
    readonly_fields = ["category", "item_identifier", "item_title", "source_status", "source_timestamp", "created_at"]

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ShiftHandover)
class ShiftHandoverAdmin(admin.ModelAdmin):
    list_display = [
        "id", "outgoing_session", "outgoing_operator", "incoming_operator",
        "status", "initiated_at", "submitted_at", "accepted_at",
        "yard_vehicles_count", "pending_discrepancies_count"
    ]
    list_filter = ["status", "outgoing_session__shift", "initiated_at"]
    search_fields = [
        "outgoing_operator__username", "incoming_operator__username",
        "outgoing_notes", "incoming_notes", "dispute_reason"
    ]
    readonly_fields = [
        "initiated_at", "submitted_at", "accepted_at", "disputed_at",
        "supervisor_resolved_at", "snapshot_version",
        "yard_vehicles_count", "waiting_second_count", "pending_discrepancies_count",
        "overdue_waiting_count", "unresolved_exceptions_count",
        "created_at", "updated_at"
    ]
    inlines = [ShiftHandoverItemInline]

    def has_delete_permission(self, request, obj=None):
        # Shift handover records constitute formal operational evidence and cannot be deleted via Admin
        return False

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.status != ShiftHandoverStatus.DRAFT:
            return [f.name for f in obj._meta.fields]
        return self.readonly_fields


@admin.register(WorkShift)
class WorkShiftAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "start_time", "end_time", "is_overnight", "duration_display", "is_active", "valid_from", "valid_until"]
    list_filter = ["is_active", "is_overnight"]
    search_fields = ["name", "code", "description"]
    readonly_fields = ["is_overnight", "created_at", "updated_at"]

    def duration_display(self, obj):
        return f"{obj.duration_hours} ساعت"
    duration_display.short_description = "مدت زمان"


@admin.register(ShiftSession)
class ShiftSessionAdmin(admin.ModelAdmin):
    list_display = ["shift", "operational_date", "status", "actual_start", "actual_end", "opened_by", "closed_by", "initial_scale_zero_ok", "initial_printer_paper_ok"]
    list_filter = ["status", "shift", "operational_date"]
    search_fields = ["shift__name", "shift__code", "notes", "opened_by__username", "closed_by__username"]
    readonly_fields = ["actual_start", "actual_end", "created_at", "updated_at"]
    inlines = [ShiftOperatorAssignmentInline]


@admin.register(ShiftOperatorAssignment)
class ShiftOperatorAssignmentAdmin(admin.ModelAdmin):
    list_display = ["session", "operator", "role", "status", "check_in_time", "check_out_time", "is_substitution", "authorized_by"]
    list_filter = ["status", "role", "is_substitution"]
    search_fields = ["operator__username", "operator__first_name", "operator__last_name", "session__shift__name"]
    readonly_fields = ["check_in_time", "check_out_time", "created_at", "updated_at"]


@admin.register(ShiftExceptionLog)
class ShiftExceptionLogAdmin(admin.ModelAdmin):
    list_display = ["ticket", "weighing_phase", "operator", "timestamp", "reason", "acknowledged_by", "acknowledged_at"]
    list_filter = ["weighing_phase", "reason"]
    search_fields = ["ticket__serial_number", "operator__username", "reason", "notes"]
    readonly_fields = ["ticket", "weighing_phase", "operator", "timestamp", "reason", "notes"]
