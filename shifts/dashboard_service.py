"""
Shift Dashboard Presentation and Filtering Service for Prima Bascol Weighbridge System.
Phase 4.3.2: Shift Management Dashboard & Operator Performance UI.

Strict Architectural Separation:
- Authoritative KPI Calculations: Delegated exclusively to `ShiftKPIService`.
- Zero Formula Duplication in Views, Templates, or JavaScript.
- Presentation Formatting, Authorization, Role Filtering, and Date Parsing handled here.
"""
from datetime import date, datetime, time
from decimal import Decimal
from typing import Dict, Any, Optional, Tuple, List

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count
from django.utils import timezone

from core.jalali import (
    format_jalali_date,
    format_jalali_datetime,
    get_today_gregorian,
    get_today_jalali,
    jalali_to_gregorian,
)
from shifts.models import (
    WorkShift,
    ShiftSession,
    ShiftSessionStatus,
    ShiftHandover,
    ShiftHandoverStatus,
)
from shifts.kpi_service import ShiftKPIService
from weighbridge.models import WeighTicket, TicketStatus


MAX_DASHBOARD_DATE_RANGE_DAYS = 31


class ShiftDashboardService:
    """
    Presentation and orchestration layer for the Shift Management Dashboard.
    Delegates all mathematical aggregations to ShiftKPIService.
    """

    @classmethod
    def check_user_dashboard_access(cls, user: User) -> Tuple[bool, bool]:
        """
        Determines user access level:
        Returns (has_access, is_supervisor_or_manager).
        """
        if not user or not user.is_authenticated:
            return False, False

        if user.is_superuser:
            return True, True

        has_profile = hasattr(user, "profile")
        if not has_profile:
            return False, False

        profile = user.profile
        is_admin_or_mgr = getattr(profile, "is_admin_or_manager", False)
        can_manage_shifts = getattr(profile, "can_manage_shifts", False)
        can_operate = getattr(profile, "can_operate_shift", False)
        is_supervisor_or_manager = is_admin_or_mgr or can_manage_shifts
        has_access = is_supervisor_or_manager or can_operate

        return has_access, is_supervisor_or_manager

    @classmethod
    def parse_filter_date(cls, date_str: Optional[str]) -> Optional[date]:
        """
        Parses a date string from request params.
        Supports Jalali (e.g. 1405/07/26 or 1405-07-26) or standard ISO (YYYY-MM-DD).
        """
        if not date_str or not str(date_str).strip():
            return None
        cleaned = str(date_str).strip()
        # Attempt Jalali parse
        j_date = jalali_to_gregorian(cleaned)
        if j_date:
            return j_date
        # Attempt ISO Gregorian parse
        try:
            return datetime.strptime(cleaned, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None

    @classmethod
    def resolve_and_validate_filters(
        cls,
        user: User,
        params: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        Validates server-side query parameters and enforces security boundaries.
        Returns (resolved_filters_dict, error_message).
        """
        has_access, is_supervisor_or_manager = cls.check_user_dashboard_access(user)
        if not has_access:
            raise PermissionDenied("شما مجوز دسترسی به داشبورد مدیریت شیفت را ندارید.")

        # 1. Date Resolution
        today = get_today_gregorian()
        start_date = cls.parse_filter_date(params.get("start_date"))
        end_date = cls.parse_filter_date(params.get("end_date"))

        # If both are empty, default to today
        if not start_date and not end_date:
            start_date = today
            end_date = today
        elif start_date and not end_date:
            end_date = start_date
        elif end_date and not start_date:
            start_date = end_date

        # Inversion check
        if start_date > end_date:
            start_date, end_date = end_date, start_date

        # Range bounds enforcement
        if (end_date - start_date).days > MAX_DASHBOARD_DATE_RANGE_DAYS:
            return {}, f"حداکثر بازه زمانی قابل گزارش‌گیری {MAX_DASHBOARD_DATE_RANGE_DAYS} روز می‌باشد."

        # 2. Operator Authorization Check (Strict self-service restriction)
        raw_op_param = params.get("operator")
        operator_filter_id: Optional[int] = None

        if raw_op_param:
            try:
                op_id = int(raw_op_param)
            except (ValueError, TypeError):
                op_id = None

            if op_id:
                if is_supervisor_or_manager:
                    operator_filter_id = op_id
                else:
                    if op_id != user.id:
                        raise PermissionDenied("اپراتورها تنها مجاز به مشاهده آمار و اطلاعات عملکرد خود می‌باشند.")
                    operator_filter_id = user.id
        else:
            if not is_supervisor_or_manager:
                operator_filter_id = user.id

        # 3. Shift Template Filter
        shift_id: Optional[int] = None
        raw_shift = params.get("shift")
        if raw_shift:
            try:
                shift_id = int(raw_shift)
            except (ValueError, TypeError):
                shift_id = None

        # 4. Session Filter
        session_id: Optional[int] = None
        raw_session = params.get("session")
        if raw_session:
            try:
                session_id = int(raw_session)
            except (ValueError, TypeError):
                session_id = None

        # 5. Handover Status Filter
        handover_status: Optional[str] = None
        raw_handover_status = params.get("handover_status")
        if raw_handover_status and raw_handover_status in ShiftHandoverStatus.values:
            handover_status = raw_handover_status

        resolved = {
            "start_date": start_date,
            "end_date": end_date,
            "start_date_jalali": format_jalali_date(start_date),
            "end_date_jalali": format_jalali_date(end_date),
            "operator_id": operator_filter_id,
            "shift_id": shift_id,
            "session_id": session_id,
            "handover_status": handover_status,
            "is_supervisor_or_manager": is_supervisor_or_manager,
        }
        return resolved, None

    @classmethod
    def get_dashboard_data(cls, user: User, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Builds the complete dashboard payload using ShiftKPIService as calculation engine.
        Enforces presentation formatting, authorization masks, and yard progression.
        """
        filters, error = cls.resolve_and_validate_filters(user, params)
        if error:
            return {
                "error": error,
                "filters": {
                    "start_date_jalali": get_today_jalali(),
                    "end_date_jalali": get_today_jalali(),
                },
            }

        start_date = filters["start_date"]
        end_date = filters["end_date"]
        shift_id = filters["shift_id"]
        session_id = filters["session_id"]
        operator_id = filters["operator_id"]
        handover_status = filters["handover_status"]
        is_supervisor = filters["is_supervisor_or_manager"]

        # 1. Authoritative Calculations via ShiftKPIService
        period_kpis = ShiftKPIService.calculate_period_shift_kpis(
            start_date=start_date,
            end_date=end_date,
            shift_id=shift_id,
            operator_id=operator_id,
        )

        sessions_list = period_kpis.get("sessions", [])

        # If a specific session was requested, filter the session list
        if session_id:
            sessions_list = [s for s in sessions_list if s["session_id"] == session_id]

        # 2. Compute Aggregated Turnaround for the filtered sessions
        all_turnaround_tickets = []
        for s in sessions_list:
            # Aggregate turnaround metrics across sessions in scope
            pass

        # Calculate period turnaround metrics across all sessions in scope
        period_completed_tickets = list(
            WeighTicket.objects.filter(
                second_weight_shift_session__in=[s["session_id"] for s in sessions_list],
                status=TicketStatus.COMPLETED
            ).only(
                "id",
                "first_weight_date",
                "first_weight_time",
                "second_weight_date",
                "second_weight_time",
            )
        ) if sessions_list else []

        overall_turnaround = ShiftKPIService.calculate_turnaround_metrics(period_completed_tickets)

        # 3. Handover List and Overview
        handover_qs = ShiftHandover.objects.filter(
            outgoing_session__operational_date__range=[start_date, end_date]
        ).select_related(
            "outgoing_session__shift",
            "incoming_session__shift",
            "outgoing_operator",
            "incoming_operator",
            "supervisor",
        ).order_by("-initiated_at")

        if shift_id:
            handover_qs = handover_qs.filter(outgoing_session__shift_id=shift_id)

        if handover_status:
            handover_qs = handover_qs.filter(status=handover_status)

        # If operator is non-supervisor, hide confidential supervisor notes
        handovers_formatted = []
        for h in handover_qs[:50]:
            is_disputed = (
                h.disputed_at is not None or
                h.status in [ShiftHandoverStatus.DISPUTED, ShiftHandoverStatus.SUPERVISOR_RESOLVED]
            )
            handovers_formatted.append({
                "id": h.pk,
                "status": h.status,
                "status_display": h.get_status_display(),
                "outgoing_session_id": h.outgoing_session_id,
                "outgoing_shift_name": h.outgoing_session.shift.name,
                "operational_date_jalali": format_jalali_date(h.outgoing_session.operational_date),
                "outgoing_operator_name": h.outgoing_operator.get_full_name() or h.outgoing_operator.username,
                "incoming_operator_name": (
                    h.incoming_operator.get_full_name() or h.incoming_operator.username
                ) if h.incoming_operator else "تعیین‌نشده",
                "initiated_at_jalali": format_jalali_datetime(h.initiated_at),
                "submitted_at_jalali": format_jalali_datetime(h.submitted_at),
                "accepted_at_jalali": format_jalali_datetime(h.accepted_at),
                "is_historically_disputed": is_disputed,
                "is_supervisor_resolved": h.status == ShiftHandoverStatus.SUPERVISOR_RESOLVED,
                "yard_vehicles_count": h.yard_vehicles_count,
                "waiting_second_count": h.waiting_second_count,
                # Security: Expose dispute reason & supervisor notes only to supervisors/managers
                "dispute_reason": h.dispute_reason if is_supervisor else "",
                "supervisor_notes": (
                    f"تصمیم سرپرست ({h.supervisor.username}): {h.supervisor_resolution_notes}"
                    if (is_supervisor and h.supervisor and h.supervisor_resolution_notes)
                    else ""
                ),
            })

        # 4. Operator Activity Table
        # If user is ordinary operator, period_kpis["operators"] is already filtered to self,
        # but let's strictly guarantee non-supervisors never see another operator's record:
        raw_operators = period_kpis.get("operators", [])
        if not is_supervisor:
            operators_table = [op for op in raw_operators if op["operator_id"] == user.id]
        else:
            operators_table = raw_operators

        # 5. Live Yard Overview & Historical Comparison
        live_open_tickets_qs = WeighTicket.objects.filter(status=TicketStatus.WAITING_SECOND)
        live_open_count = live_open_tickets_qs.count()
        live_distinct_vehicles = live_open_tickets_qs.values("license_plate_display").distinct().count()

        # Historical handover snapshot comparison (from latest handover in period)
        latest_handover = handover_qs.first()
        snapshot_yard_count = latest_handover.yard_vehicles_count if latest_handover else 0
        snapshot_waiting_count = latest_handover.waiting_second_count if latest_handover else 0

        # Total distinct completed vehicles across all completed tickets in period sessions
        distinct_vehicles_completed = (
            WeighTicket.objects.filter(
                second_weight_shift_session__in=[s["session_id"] for s in sessions_list],
                status=TicketStatus.COMPLETED
            ).values("license_plate_display").distinct().count()
        ) if sessions_list else 0

        # Total out of shift events in period
        out_of_shift_events_count = sum(
            s.get("out_of_shift_first", 0) + s.get("out_of_shift_second", 0)
            for s in sessions_list
        )

        # 6. Dropdown Options for Filter Form
        available_shifts = WorkShift.objects.all().order_by("start_time")
        if is_supervisor:
            available_operators = User.objects.filter(is_active=True).order_by("first_name", "last_name", "username")
        else:
            available_operators = [user]

        return {
            "error": None,
            "filters": filters,
            "is_supervisor": is_supervisor,
            "shift_management_enabled": period_kpis.get("shift_management_enabled", True),

            # A. KPI Summary
            "summary": {
                "first_weighings_count": period_kpis["summary"]["first_weighings_count"],
                "second_weighings_count": period_kpis["summary"]["second_weighings_count"],
                "completed_tickets_count": period_kpis["summary"]["completed_tickets_count"],
                "direct_weighings_count": period_kpis["summary"]["direct_weighings_count"],
                "cancelled_after_second_weight_count": period_kpis["summary"]["cancelled_after_second_weight_count"],
                "solo_completed_count": period_kpis["summary"]["solo_completed_count"],
                "completed_net_kg": period_kpis["summary"]["completed_net_kg"],
                "completed_net_ton": period_kpis["summary"]["completed_net_ton"],
                "completed_gross_ton": period_kpis["summary"]["completed_gross_ton"],
                "completed_tare_ton": period_kpis["summary"]["completed_tare_ton"],
                "inbound_net_ton": period_kpis["summary"]["inbound_net_ton"],
                "outbound_net_ton": period_kpis["summary"]["outbound_net_ton"],
                "out_of_shift_events_count": out_of_shift_events_count,
                "distinct_vehicles_completed": distinct_vehicles_completed,
                "turnaround": overall_turnaround,
            },

            # B. Shift Comparison Table
            "sessions": sessions_list,
            "total_sessions_count": len(sessions_list),

            # C. Operator Activity Table
            "operators": operators_table,

            # D. Handover Overview
            "handover_kpis": period_kpis.get("handovers", {}),
            "handovers_list": handovers_formatted,

            # E. Yard Overview
            "yard": {
                "live_open_tickets_count": live_open_count,
                "live_distinct_vehicles_count": live_distinct_vehicles,
                "latest_snapshot_yard_count": snapshot_yard_count,
                "latest_snapshot_waiting_count": snapshot_waiting_count,
                "has_snapshot": latest_handover is not None,
                "latest_handover_id": latest_handover.pk if latest_handover else None,
            },

            # Unattributed Legacy Section
            "unattributed_legacy": period_kpis.get("unattributed_legacy", {}),

            # Dropdown Select Options
            "available_shifts": available_shifts,
            "available_operators": available_operators,
            "handover_status_choices": ShiftHandoverStatus.choices,
        }
