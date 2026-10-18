import statistics
from decimal import Decimal
from datetime import datetime, date, time, timedelta
from typing import Dict, Any, List, Optional, Tuple

from django.db.models import Sum, Count, Avg, Min, Max, Q, F
from django.utils import timezone
from django.conf import settings

from core.jalali import (
    format_jalali_date,
    format_jalali_datetime,
    get_today_gregorian,
    jalali_to_gregorian,
)
from shifts.models import (
    WorkShift,
    ShiftSession,
    ShiftSessionStatus,
    ShiftOperatorAssignment,
    ShiftAssignmentStatus,
    ShiftExceptionLog,
    ShiftHandover,
    ShiftHandoverStatus,
    ShiftHandoverItem,
    ShiftHandoverItemCategory,
)
from weighbridge.models import WeighTicket, TicketStatus, WeightMode
from monitoring.models import DiscrepancyApproval, ApprovalStatus


class ShiftKPIService:
    """
    Authoritative, concurrency-safe, single-source-of-truth KPI Calculation Service
    for Prima Bascol Shift Management, Operator Accountability, and Formal Handovers.

    Core Principles:
    1. Operational Attribution:
       - Uses ShiftSession references (`first_weight_shift_session`, `second_weight_shift_session`)
         and `ShiftSession.operational_date` as the authoritative operational grouping.
       - Leaves existing financial daily reports (based on `completion_date`) completely untouched.
    2. Strict Data Integrity:
       - Completed tonnage strictly requires `status=TicketStatus.COMPLETED`.
       - Cancelled, draft, and in-yard open tickets are excluded from completed tonnage.
       - Current effective `net_weight` is used for tonnage (quantized to Metric Tons via Decimal).
       - Historical revisions are NEVER summed as additional tickets or duplicate tonnage.
    3. Mathematical Rigor:
       - Second-weighing count is NOT assumed to always equal completed-ticket count.
       - Turnaround calculations exclude missing timestamps and negative durations.
       - Physical vehicles are strictly distinguished from ticket counts.
       - Handover snapshots are strictly separated from live operational yard records.
       - `YARD_VEHICLE` items and `WAITING_SECOND` items in snapshots are NEVER summed together.
    """

    @staticmethod
    def kg_to_ton(kg_val, decimal_places=2) -> Decimal:
        """
        Safely convert a kilogram value to metric tonnes using exact Decimal arithmetic.
        """
        if kg_val is None:
            return Decimal("0.00")
        if not isinstance(kg_val, Decimal):
            kg_val = Decimal(str(kg_val))
        ton = kg_val / Decimal("1000")
        quantizer = Decimal("1." + "0" * decimal_places)
        return ton.quantize(quantizer)

    @staticmethod
    def merge_attendance_intervals(
        intervals: List[Tuple[datetime, datetime]]
    ) -> List[Tuple[datetime, datetime]]:
        """
        Merges overlapping or contiguous attendance intervals for an operator,
        guaranteeing zero double-counting of overlapping active shifts.
        """
        if not intervals:
            return []
        # Filter invalid inverted intervals
        valid = [iv for iv in intervals if iv[0] <= iv[1]]
        if not valid:
            return []
        sorted_iv = sorted(valid, key=lambda x: x[0])
        merged = [sorted_iv[0]]
        for cur in sorted_iv[1:]:
            prev_start, prev_end = merged[-1]
            cur_start, cur_end = cur
            if cur_start <= prev_end:
                merged[-1] = (prev_start, max(prev_end, cur_end))
            else:
                merged.append(cur)
        return merged

    @classmethod
    def calculate_turnaround_metrics(cls, tickets) -> Dict[str, Any]:
        """
        Calculates exact vehicle turnaround statistics (first weight to second weight)
        for completed tickets. Excludes missing timestamps and negative durations.
        """
        tz = timezone.get_current_timezone()
        valid_durations_minutes: List[float] = []
        excluded_missing = 0
        excluded_negative = 0

        # Buckets
        under_30m = 0
        between_30_60m = 0
        between_1_2h = 0
        over_2h = 0

        for t in tickets:
            d1, t1 = t.first_weight_date, t.first_weight_time
            d2, t2 = t.second_weight_date, t.second_weight_time

            if not d1 or not t1 or not d2 or not t2:
                excluded_missing += 1
                continue

            dt1 = timezone.make_aware(datetime.combine(d1, t1), tz)
            dt2 = timezone.make_aware(datetime.combine(d2, t2), tz)

            diff_seconds = (dt2 - dt1).total_seconds()
            if diff_seconds < 0:
                excluded_negative += 1
                continue

            dur_min = round(diff_seconds / 60.0, 1)
            valid_durations_minutes.append(dur_min)

            if dur_min < 30.0:
                under_30m += 1
            elif dur_min <= 60.0:
                between_30_60m += 1
            elif dur_min <= 120.0:
                between_1_2h += 1
            else:
                over_2h += 1

        valid_count = len(valid_durations_minutes)
        if valid_count > 0:
            avg_min = round(statistics.mean(valid_durations_minutes), 1)
            med_min = round(statistics.median(valid_durations_minutes), 1)
            min_min = round(min(valid_durations_minutes), 1)
            max_min = round(max(valid_durations_minutes), 1)
        else:
            avg_min = 0.0
            med_min = 0.0
            min_min = 0.0
            max_min = 0.0

        return {
            "valid_count": valid_count,
            "excluded_count": excluded_missing + excluded_negative,
            "excluded_reasons": {
                "missing_timestamps": excluded_missing,
                "negative_duration": excluded_negative,
            },
            "avg_minutes": avg_min,
            "median_minutes": med_min,
            "min_minutes": min_min,
            "max_minutes": max_min,
            "under_30m_count": under_30m,
            "between_30_60m_count": between_30_60m,
            "between_1_2h_count": between_1_2h,
            "over_2h_count": over_2h,
        }

    @classmethod
    def calculate_session_kpis(cls, session: ShiftSession) -> Dict[str, Any]:
        """
        Computes authoritative, comprehensive KPIs for a single ShiftSession.
        """
        first_weighings_qs = WeighTicket.objects.filter(first_weight_shift_session=session)
        second_weighings_qs = WeighTicket.objects.filter(second_weight_shift_session=session)
        completed_tickets_qs = second_weighings_qs.filter(status=TicketStatus.COMPLETED)

        # 1. Single-Pass Aggregation on First Weighings
        first_aggr = first_weighings_qs.aggregate(
            total=Count("id"),
            waiting_second=Count("id", filter=Q(status=TicketStatus.WAITING_SECOND)),
            out_of_shift=Count("id", filter=Q(first_weight_out_of_shift=True)),
            distinct_vehicles=Count("license_plate_display", distinct=True),
        )
        first_weighings_count = first_aggr["total"] or 0
        waiting_second_count = first_aggr["waiting_second"] or 0
        out_of_shift_first = first_aggr["out_of_shift"] or 0
        distinct_vehicles_first_weighed = first_aggr["distinct_vehicles"] or 0

        # 2. Single-Pass Aggregation on Second Weighings (Tonnage + Volumes + Revisions)
        second_aggr = second_weighings_qs.aggregate(
            total=Count("id"),
            completed=Count("id", filter=Q(status=TicketStatus.COMPLETED)),
            direct=Count("id", filter=Q(status=TicketStatus.COMPLETED, weight_mode=WeightMode.DIRECT)),
            cancelled=Count("id", filter=Q(status=TicketStatus.CANCELLED)),
            solo=Count(
                "id",
                filter=Q(
                    status=TicketStatus.COMPLETED,
                    first_weight_operator=F("second_weight_operator"),
                    first_weight_operator__isnull=False,
                ),
            ),
            dual=Count(
                "id",
                filter=Q(
                    status=TicketStatus.COMPLETED,
                    first_weight_operator__isnull=False,
                    second_weight_operator__isnull=False,
                )
                & ~Q(first_weight_operator=F("second_weight_operator")),
            ),
            distinct_vehicles_completed=Count(
                "license_plate_display", distinct=True, filter=Q(status=TicketStatus.COMPLETED)
            ),
            out_of_shift=Count("id", filter=Q(second_weight_out_of_shift=True)),
            discrepancy=Count("id", filter=Q(status=TicketStatus.COMPLETED, is_tolerance_exceeded=True)),
            revisions=Count("id", filter=Q(status=TicketStatus.COMPLETED, current_revision_number__gt=0)),
            net_kg=Sum("net_weight", filter=Q(status=TicketStatus.COMPLETED)),
            gross_kg=Sum("gross_weight", filter=Q(status=TicketStatus.COMPLETED)),
            tare_kg=Sum("tare_weight", filter=Q(status=TicketStatus.COMPLETED)),
            final_kg=Sum("final_weight", filter=Q(status=TicketStatus.COMPLETED)),
            loss_kg=Sum("loss_weight", filter=Q(status=TicketStatus.COMPLETED)),
            inbound_net_kg=Sum(
                "net_weight",
                filter=Q(status=TicketStatus.COMPLETED, operation_type__direction="inbound"),
            ),
            outbound_net_kg=Sum(
                "net_weight",
                filter=Q(status=TicketStatus.COMPLETED, operation_type__direction="outbound"),
            ),
            internal_net_kg=Sum(
                "net_weight",
                filter=Q(status=TicketStatus.COMPLETED, operation_type__direction="internal"),
            ),
        )

        second_weighings_count = second_aggr["total"] or 0
        completed_tickets_count = second_aggr["completed"] or 0
        direct_weighings_count = second_aggr["direct"] or 0
        cancelled_after_second_weight_count = second_aggr["cancelled"] or 0
        solo_completed_count = second_aggr["solo"] or 0
        dual_operator_completed_count = second_aggr["dual"] or 0
        distinct_vehicles_completed = second_aggr["distinct_vehicles_completed"] or 0
        out_of_shift_second = second_aggr["out_of_shift"] or 0
        discrepancy_tickets_count = second_aggr["discrepancy"] or 0
        revisions_applied_count = second_aggr["revisions"] or 0

        completed_net_kg = second_aggr["net_kg"] or Decimal("0.00")
        completed_gross_kg = second_aggr["gross_kg"] or Decimal("0.00")
        completed_tare_kg = second_aggr["tare_kg"] or Decimal("0.00")
        completed_final_kg = second_aggr["final_kg"] or Decimal("0.00")
        completed_loss_kg = second_aggr["loss_kg"] or Decimal("0.00")
        inbound_net_kg = second_aggr["inbound_net_kg"] or Decimal("0.00")
        outbound_net_kg = second_aggr["outbound_net_kg"] or Decimal("0.00")
        internal_net_kg = second_aggr["internal_net_kg"] or Decimal("0.00")

        completed_net_ton = cls.kg_to_ton(completed_net_kg)
        completed_gross_ton = cls.kg_to_ton(completed_gross_kg)
        completed_tare_ton = cls.kg_to_ton(completed_tare_kg)
        completed_final_ton = cls.kg_to_ton(completed_final_kg)
        completed_loss_ton = cls.kg_to_ton(completed_loss_kg)
        inbound_net_ton = cls.kg_to_ton(inbound_net_kg)
        outbound_net_ton = cls.kg_to_ton(outbound_net_kg)
        internal_net_ton = cls.kg_to_ton(internal_net_kg)

        # 3. Turnaround Time Statistics (Only for completed tickets)
        completed_tickets_for_turnaround = list(
            second_weighings_qs.filter(status=TicketStatus.COMPLETED).only(
                "id",
                "first_weight_date",
                "first_weight_time",
                "second_weight_date",
                "second_weight_time",
            )
        )
        turnaround_stats = cls.calculate_turnaround_metrics(completed_tickets_for_turnaround)

        # 4. Out-of-shift & Exceptions (Aggregated)
        exceptions_qs = ShiftExceptionLog.objects.filter(
            Q(ticket__first_weight_shift_session=session) |
            Q(ticket__second_weight_shift_session=session)
        ).distinct()
        exceptions_aggr = exceptions_qs.aggregate(
            total=Count("id"),
            unresolved=Count("id", filter=Q(acknowledged_by__isnull=True)),
        )
        shift_exceptions_count = exceptions_aggr["total"] or 0
        unresolved_exceptions_count = exceptions_aggr["unresolved"] or 0

        # 6. Discrepancies and Approvals
        pending_approvals_count = DiscrepancyApproval.objects.filter(
            ticket__in=second_weighings_qs,
            status=ApprovalStatus.PENDING
        ).count()

        # 7. Handover Integration & Snapshots
        outgoing_handover = ShiftHandover.objects.filter(outgoing_session=session).first()
        incoming_handover = ShiftHandover.objects.filter(incoming_session=session).first()

        outgoing_handover_data = {
            "exists": outgoing_handover is not None,
            "id": outgoing_handover.pk if outgoing_handover else None,
            "status": outgoing_handover.status if outgoing_handover else None,
            "is_disputed": outgoing_handover.status == ShiftHandoverStatus.DISPUTED if outgoing_handover else False,
            "is_historically_disputed": (
                outgoing_handover.disputed_at is not None or
                outgoing_handover.status in [ShiftHandoverStatus.DISPUTED, ShiftHandoverStatus.SUPERVISOR_RESOLVED]
            ) if outgoing_handover else False,
            "is_supervisor_resolved": (
                outgoing_handover.status == ShiftHandoverStatus.SUPERVISOR_RESOLVED
            ) if outgoing_handover else False,
            "snapshot_yard_vehicles_count": outgoing_handover.yard_vehicles_count if outgoing_handover else 0,
            "snapshot_waiting_second_count": outgoing_handover.waiting_second_count if outgoing_handover else 0,
            "submission_duration_minutes": round(
                (outgoing_handover.submitted_at - outgoing_handover.initiated_at).total_seconds() / 60.0, 1
            ) if outgoing_handover and outgoing_handover.submitted_at else None,
            "acceptance_delay_minutes": round(
                (outgoing_handover.accepted_at - outgoing_handover.submitted_at).total_seconds() / 60.0, 1
            ) if outgoing_handover and outgoing_handover.accepted_at and outgoing_handover.submitted_at else None,
        }

        # 8. Operator Analytics in this Session
        operator_analytics = cls._calculate_session_operator_metrics(
            session=session,
            first_weighings_qs=first_weighings_qs,
            second_weighings_qs=second_weighings_qs,
            completed_tickets_qs=completed_tickets_qs
        )

        return {
            "session_id": session.pk,
            "shift_id": session.shift_id,
            "shift_name": session.shift.name,
            "shift_code": session.shift.code,
            "is_overnight": session.shift.is_overnight,
            "operational_date": session.operational_date,
            "operational_date_jalali": format_jalali_date(session.operational_date),
            "status": session.status,
            "actual_start": session.actual_start,
            "actual_end": session.actual_end,

            # Volume Metrics
            "first_weighings_count": first_weighings_count,
            "second_weighings_count": second_weighings_count,
            "completed_tickets_count": completed_tickets_count,
            "direct_weighings_count": direct_weighings_count,
            "cancelled_after_second_weight_count": cancelled_after_second_weight_count,
            "waiting_second_count": waiting_second_count,
            "solo_completed_count": solo_completed_count,
            "dual_operator_completed_count": dual_operator_completed_count,

            # Vehicles vs Tickets
            "distinct_vehicles_first_weighed": distinct_vehicles_first_weighed,
            "distinct_vehicles_completed": distinct_vehicles_completed,

            # Tonnage Metrics (Current effective values)
            "tonnage_basis": "current_effective_net_weight",
            "historical_point_in_time_reconstructed": False,
            "revisions_applied_count": revisions_applied_count,
            "completed_net_kg": completed_net_kg,
            "completed_net_ton": completed_net_ton,
            "completed_gross_kg": completed_gross_kg,
            "completed_gross_ton": completed_gross_ton,
            "completed_tare_kg": completed_tare_kg,
            "completed_tare_ton": completed_tare_ton,
            "completed_final_kg": completed_final_kg,
            "completed_final_ton": completed_final_ton,
            "completed_loss_kg": completed_loss_kg,
            "completed_loss_ton": completed_loss_ton,
            "inbound_net_kg": inbound_net_kg,
            "inbound_net_ton": inbound_net_ton,
            "outbound_net_kg": outbound_net_kg,
            "outbound_net_ton": outbound_net_ton,
            "internal_net_kg": internal_net_kg,
            "internal_net_ton": internal_net_ton,

            # Turnaround
            "turnaround": turnaround_stats,

            # Exceptions & Approvals
            "out_of_shift_first": out_of_shift_first,
            "out_of_shift_second": out_of_shift_second,
            "shift_exceptions_count": shift_exceptions_count,
            "unresolved_exceptions_count": unresolved_exceptions_count,
            "discrepancy_tickets_count": discrepancy_tickets_count,
            "pending_approvals_count": pending_approvals_count,

            # Handover
            "outgoing_handover": outgoing_handover_data,
            "incoming_handover_exists": incoming_handover is not None,

            # Operator Breakdown
            "operators": operator_analytics,
        }

    @classmethod
    def _calculate_session_operator_metrics(
        cls,
        session: ShiftSession,
        first_weighings_qs,
        second_weighings_qs,
        completed_tickets_qs
    ) -> List[Dict[str, Any]]:
        """
        Calculates exact per-operator task counts, valid attendance hours,
        and throughput per hour without overlapping interval inflation.
        """
        now = timezone.now()
        assignments = list(session.assignments.select_related("operator", "substituted_operator").all())
        
        # Operators from assignments
        operators_dict: Dict[int, Dict[str, Any]] = {}

        for a in assignments:
            u = a.operator
            if u.pk not in operators_dict:
                operators_dict[u.pk] = {
                    "id": u.pk,
                    "username": u.username,
                    "full_name": u.get_full_name() or u.username,
                    "role": a.role,
                    "is_substitution": a.is_substitution,
                    "substituted_operator": a.substituted_operator.username if a.substituted_operator else None,
                    "raw_intervals": [],
                    "first_weights": 0,
                    "second_weights": 0,
                    "solo_completed": 0,
                    "completed_net_kg": Decimal("0.00"),
                    "shift_exceptions_count": 0,
                }
            
            # Attendance interval evaluation
            if a.check_in_time:
                if a.check_out_time:
                    end_time = a.check_out_time
                    is_open = False
                elif session.status == ShiftSessionStatus.CLOSED and session.actual_end:
                    end_time = session.actual_end
                    is_open = False
                else:
                    end_time = now
                    is_open = True
                
                if end_time >= a.check_in_time:
                    operators_dict[u.pk]["raw_intervals"].append((a.check_in_time, end_time))

        # Query first weight operators in this session
        first_op_counts = first_weighings_qs.filter(first_weight_operator__isnull=False).values(
            "first_weight_operator__id",
            "first_weight_operator__username",
            "first_weight_operator__first_name",
            "first_weight_operator__last_name",
        ).annotate(count=Count("id"))

        for r in first_op_counts:
            uid = r["first_weight_operator__id"]
            if uid not in operators_dict:
                fname = f"{r['first_weight_operator__first_name']} {r['first_weight_operator__last_name']}".strip()
                operators_dict[uid] = {
                    "id": uid,
                    "username": r["first_weight_operator__username"],
                    "full_name": fname or r["first_weight_operator__username"],
                    "role": "EXTERNAL",
                    "is_substitution": False,
                    "substituted_operator": None,
                    "raw_intervals": [],
                    "first_weights": 0,
                    "second_weights": 0,
                    "solo_completed": 0,
                    "completed_net_kg": Decimal("0.00"),
                    "shift_exceptions_count": 0,
                }
            operators_dict[uid]["first_weights"] += r["count"]

        # Query second weight operators in this session
        second_op_counts = second_weighings_qs.filter(second_weight_operator__isnull=False).values(
            "second_weight_operator__id",
            "second_weight_operator__username",
            "second_weight_operator__first_name",
            "second_weight_operator__last_name",
        ).annotate(count=Count("id"))

        for r in second_op_counts:
            uid = r["second_weight_operator__id"]
            if uid not in operators_dict:
                fname = f"{r['second_weight_operator__first_name']} {r['second_weight_operator__last_name']}".strip()
                operators_dict[uid] = {
                    "id": uid,
                    "username": r["second_weight_operator__username"],
                    "full_name": fname or r["second_weight_operator__username"],
                    "role": "EXTERNAL",
                    "is_substitution": False,
                    "substituted_operator": None,
                    "raw_intervals": [],
                    "first_weights": 0,
                    "second_weights": 0,
                    "solo_completed": 0,
                    "completed_net_kg": Decimal("0.00"),
                    "shift_exceptions_count": 0,
                }
            operators_dict[uid]["second_weights"] += r["count"]

        # Solo completed tickets per operator
        solo_counts = completed_tickets_qs.filter(
            first_weight_operator=F("second_weight_operator"),
            first_weight_operator__isnull=False,
        ).values("first_weight_operator__id").annotate(count=Count("id"))

        for r in solo_counts:
            uid = r["first_weight_operator__id"]
            if uid in operators_dict:
                operators_dict[uid]["solo_completed"] = r["count"]

        # Completed net kg per second-weight operator
        completed_tonnage_per_op = completed_tickets_qs.filter(
            second_weight_operator__isnull=False
        ).values("second_weight_operator__id").annotate(total_net=Sum("net_weight"))

        for r in completed_tonnage_per_op:
            uid = r["second_weight_operator__id"]
            if uid in operators_dict:
                operators_dict[uid]["completed_net_kg"] = r["total_net"] or Decimal("0.00")

        # Query exceptions in this session per operator
        session_exceptions_counts = ShiftExceptionLog.objects.filter(
            Q(ticket__first_weight_shift_session=session) | Q(ticket__second_weight_shift_session=session),
            operator__isnull=False
        ).values("operator__id").annotate(count=Count("id"))

        for r in session_exceptions_counts:
            uid = r["operator__id"]
            if uid in operators_dict:
                operators_dict[uid]["shift_exceptions_count"] = r["count"]

        # Compile final operator records
        results = []
        for uid, d in operators_dict.items():
            merged_iv = cls.merge_attendance_intervals(d["raw_intervals"])
            total_seconds = sum((iv[1] - iv[0]).total_seconds() for iv in merged_iv)
            attendance_hours = round(Decimal(str(total_seconds)) / Decimal("3600.0"), 2)

            total_tasks = d["first_weights"] + d["second_weights"]
            if attendance_hours > Decimal("0.00"):
                tasks_per_hour = round(float(Decimal(str(total_tasks)) / attendance_hours), 1)
            else:
                tasks_per_hour = 0.0

            results.append({
                "operator_id": uid,
                "username": d["username"],
                "full_name": d["full_name"],
                "role": d["role"],
                "is_substitution": d["is_substitution"],
                "substituted_operator": d["substituted_operator"],
                "attendance_hours": attendance_hours,
                "first_weights": d["first_weights"],
                "second_weights": d["second_weights"],
                "total_tasks": total_tasks,
                "solo_completed": d["solo_completed"],
                "completed_net_kg": d["completed_net_kg"],
                "completed_net_ton": cls.kg_to_ton(d["completed_net_kg"]),
                "tasks_per_hour": tasks_per_hour,
                "shift_exceptions_count": d.get("shift_exceptions_count", 0),
                "raw_intervals": d["raw_intervals"],
            })

        results.sort(key=lambda x: (x["total_tasks"], x["completed_net_kg"]), reverse=True)
        return results

    @classmethod
    def calculate_period_operator_metrics(
        cls,
        sessions_kpi_list: List[Dict[str, Any]],
        start_date: date,
        end_date: date,
        operator_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Aggregates operator performance metrics across a reporting period.
        Accurately clips all attendance intervals to [start_date 00:00:00, end_date 23:59:59]
        in the local timezone and merges them to avoid double counting across sessions.
        """
        tz = timezone.get_current_timezone()
        period_start = timezone.make_aware(datetime.combine(start_date, time.min), tz)
        period_end = timezone.make_aware(datetime.combine(end_date, time.max), tz)

        operators_map: Dict[int, Dict[str, Any]] = {}

        for session_kpi in sessions_kpi_list:
            for op in session_kpi.get("operators", []):
                uid = op["operator_id"]
                if operator_id and uid != operator_id:
                    continue

                if uid not in operators_map:
                    operators_map[uid] = {
                        "operator_id": uid,
                        "username": op["username"],
                        "full_name": op["full_name"],
                        "role": op["role"],
                        "first_weights": 0,
                        "second_weights": 0,
                        "total_tasks": 0,
                        "solo_completed": 0,
                        "completed_net_kg": Decimal("0.00"),
                        "shift_exceptions_count": 0,
                        "raw_clipped_intervals": [],
                    }

                entry = operators_map[uid]
                entry["first_weights"] += op["first_weights"]
                entry["second_weights"] += op["second_weights"]
                entry["total_tasks"] += op["total_tasks"]
                entry["solo_completed"] += op["solo_completed"]
                entry["completed_net_kg"] += op["completed_net_kg"]
                entry["shift_exceptions_count"] += op.get("shift_exceptions_count", 0)

                # Clip attendance intervals to period boundary
                for s, e in op.get("raw_intervals", []):
                    s_aware = s if timezone.is_aware(s) else timezone.make_aware(s, tz)
                    e_aware = e if timezone.is_aware(e) else timezone.make_aware(e, tz)

                    clip_s = max(s_aware, period_start)
                    clip_e = min(e_aware, period_end)
                    if clip_e > clip_s:
                        entry["raw_clipped_intervals"].append((clip_s, clip_e))

        # Finalize metrics with interval union
        final_list = []
        for uid, data in operators_map.items():
            merged_iv = cls.merge_attendance_intervals(data["raw_clipped_intervals"])
            total_seconds = sum((iv[1] - iv[0]).total_seconds() for iv in merged_iv)
            attendance_hours = round(Decimal(str(total_seconds)) / Decimal("3600.0"), 2)

            total_tasks = data["total_tasks"]
            if attendance_hours > Decimal("0.00"):
                tasks_per_hour = round(float(Decimal(str(total_tasks)) / attendance_hours), 1)
            else:
                tasks_per_hour = 0.0

            final_list.append({
                "operator_id": uid,
                "username": data["username"],
                "full_name": data["full_name"],
                "role": data["role"],
                "first_weights": data["first_weights"],
                "second_weights": data["second_weights"],
                "total_tasks": total_tasks,
                "solo_completed": data["solo_completed"],
                "completed_net_kg": data["completed_net_kg"],
                "completed_net_ton": cls.kg_to_ton(data["completed_net_kg"]),
                "attendance_hours": attendance_hours,
                "tasks_per_hour": tasks_per_hour,
                "shift_exceptions_count": data["shift_exceptions_count"],
            })

        final_list.sort(key=lambda x: (x["total_tasks"], x["completed_net_kg"]), reverse=True)
        return final_list

    @classmethod
    def calculate_period_shift_kpis(
        cls,
        start_date: date,
        end_date: Optional[date] = None,
        shift_id: Optional[int] = None,
        operator_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Computes aggregated shift KPIs across an operational date range.
        Includes an explicit 'unattributed_legacy' group to isolate tickets created
        without ShiftSession assignments (e.g., historical Phase 3 data or feature-disabled mode).
        """
        if end_date is None:
            end_date = start_date

        if start_date > end_date:
            raise ValidationError("تاریخ شروع نمی‌تواند پس از تاریخ پایان باشد.")
        if (end_date - start_date).days > 31:
            raise ValidationError("حداکثر بازه زمانی قابل گزارش‌گیری ۳۱ روز می‌باشد.")

        sessions_qs = ShiftSession.objects.filter(
            operational_date__range=[start_date, end_date]
        ).select_related("shift", "opened_by", "closed_by")

        if shift_id:
            sessions_qs = sessions_qs.filter(shift_id=shift_id)

        if operator_id:
            sessions_qs = sessions_qs.filter(assignments__operator_id=operator_id).distinct()

        # Compute per-session KPIs
        sessions_kpi_list = []
        for s in sessions_qs.order_by("operational_date", "shift__start_time"):
            sessions_kpi_list.append(cls.calculate_session_kpis(s))

        # Overall Totals across matching sessions
        total_sessions = len(sessions_kpi_list)
        total_first_weighings = sum(s["first_weighings_count"] for s in sessions_kpi_list)
        total_second_weighings = sum(s["second_weighings_count"] for s in sessions_kpi_list)
        total_completed_tickets = sum(s["completed_tickets_count"] for s in sessions_kpi_list)
        total_direct_weighings = sum(s["direct_weighings_count"] for s in sessions_kpi_list)
        total_cancelled_after_second = sum(s["cancelled_after_second_weight_count"] for s in sessions_kpi_list)
        total_solo_completed = sum(s["solo_completed_count"] for s in sessions_kpi_list)

        total_completed_net_kg = sum(s["completed_net_kg"] for s in sessions_kpi_list)
        total_completed_net_ton = cls.kg_to_ton(total_completed_net_kg)
        total_completed_gross_kg = sum(s["completed_gross_kg"] for s in sessions_kpi_list)
        total_completed_gross_ton = cls.kg_to_ton(total_completed_gross_kg)
        total_completed_tare_kg = sum(s["completed_tare_kg"] for s in sessions_kpi_list)
        total_completed_tare_ton = cls.kg_to_ton(total_completed_tare_kg)
        total_inbound_net_kg = sum(s.get("inbound_net_kg", Decimal("0.00")) for s in sessions_kpi_list)
        total_inbound_net_ton = cls.kg_to_ton(total_inbound_net_kg)
        total_outbound_net_kg = sum(s.get("outbound_net_kg", Decimal("0.00")) for s in sessions_kpi_list)
        total_outbound_net_ton = cls.kg_to_ton(total_outbound_net_kg)

        # Unattributed / Legacy tickets within this date range (Calendar date comparison)
        unattributed_first_qs = WeighTicket.objects.filter(
            first_weight_date__range=[start_date, end_date],
            first_weight_shift_session__isnull=True,
        )
        unattributed_second_qs = WeighTicket.objects.filter(
            second_weight_date__range=[start_date, end_date],
            second_weight_shift_session__isnull=True,
        )
        unattributed_completed_qs = unattributed_second_qs.filter(status=TicketStatus.COMPLETED)

        unattr_tonnage = unattributed_completed_qs.aggregate(net_kg=Sum("net_weight"))
        unattr_net_kg = unattr_tonnage["net_kg"] or Decimal("0.00")
        unattr_net_ton = cls.kg_to_ton(unattr_net_kg)

        unattributed_data = {
            "first_weighings_count": unattributed_first_qs.count(),
            "second_weighings_count": unattributed_second_qs.count(),
            "completed_tickets_count": unattributed_completed_qs.count(),
            "completed_net_kg": unattr_net_kg,
            "completed_net_ton": unattr_net_ton,
            "description": "قبوض ثبت‌شده بدون انتساب شیفت (سوابق تاریخی فاز ۳ یا زمان غیرفعال بودن ماژول شیفت)",
        }

        # Handover statistics in period
        handover_kpis = cls.calculate_handover_kpis(start_date=start_date, end_date=end_date)

        # Aggregated operator statistics across the period with clipped attendance
        period_operators = cls.calculate_period_operator_metrics(
            sessions_kpi_list=sessions_kpi_list,
            start_date=start_date,
            end_date=end_date,
            operator_id=operator_id,
        )

        return {
            "period": {
                "start_date": start_date,
                "end_date": end_date,
                "start_date_jalali": format_jalali_date(start_date),
                "end_date_jalali": format_jalali_date(end_date),
            },
            "shift_management_enabled": getattr(settings, "ENABLE_SHIFT_MANAGEMENT", True),
            "total_sessions": total_sessions,
            "summary": {
                "first_weighings_count": total_first_weighings,
                "second_weighings_count": total_second_weighings,
                "completed_tickets_count": total_completed_tickets,
                "direct_weighings_count": total_direct_weighings,
                "cancelled_after_second_weight_count": total_cancelled_after_second,
                "solo_completed_count": total_solo_completed,
                "completed_net_kg": total_completed_net_kg,
                "completed_net_ton": total_completed_net_ton,
                "completed_gross_kg": total_completed_gross_kg,
                "completed_gross_ton": total_completed_gross_ton,
                "completed_tare_kg": total_completed_tare_kg,
                "completed_tare_ton": total_completed_tare_ton,
                "inbound_net_kg": total_inbound_net_kg,
                "inbound_net_ton": total_inbound_net_ton,
                "outbound_net_kg": total_outbound_net_kg,
                "outbound_net_ton": total_outbound_net_ton,
            },
            "sessions": sessions_kpi_list,
            "operators": period_operators,
            "unattributed_legacy": unattributed_data,
            "handovers": handover_kpis,
        }

    @classmethod
    def calculate_handover_kpis(
        cls,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """
        Authoritative statistics on formal shift handovers and supervisor interventions.
        Accurately counts historically disputed handovers (even if resolved later).
        """
        qs = ShiftHandover.objects.all()
        if start_date and end_date:
            qs = qs.filter(outgoing_session__operational_date__range=[start_date, end_date])
        elif start_date:
            qs = qs.filter(outgoing_session__operational_date__gte=start_date)
        elif end_date:
            qs = qs.filter(outgoing_session__operational_date__lte=end_date)

        total_handovers = qs.count()
        draft_count = qs.filter(status=ShiftHandoverStatus.DRAFT).count()
        submitted_count = qs.filter(
            status__in=[
                ShiftHandoverStatus.SUBMITTED,
                ShiftHandoverStatus.ACCEPTED,
                ShiftHandoverStatus.DISPUTED,
                ShiftHandoverStatus.SUPERVISOR_RESOLVED,
            ]
        ).count()
        accepted_count = qs.filter(status=ShiftHandoverStatus.ACCEPTED).count()
        currently_disputed_count = qs.filter(status=ShiftHandoverStatus.DISPUTED).count()
        supervisor_resolved_count = qs.filter(status=ShiftHandoverStatus.SUPERVISOR_RESOLVED).count()
        cancelled_count = qs.filter(status=ShiftHandoverStatus.CANCELLED).count()

        # Historically disputed: either currently disputed, supervisor-resolved, or disputed_at recorded
        historically_disputed_count = qs.filter(
            Q(status=ShiftHandoverStatus.DISPUTED) |
            Q(status=ShiftHandoverStatus.SUPERVISOR_RESOLVED) |
            Q(disputed_at__isnull=False)
        ).distinct().count()

        if submitted_count > 0:
            dispute_rate_pct = round((historically_disputed_count / submitted_count) * 100.0, 1)
        else:
            dispute_rate_pct = 0.0

        # Checklist compliance rate
        checklist_compliant_count = qs.filter(
            scale_zero_confirmed=True,
            printer_paper_confirmed=True,
            workstation_clean_confirmed=True,
            physical_documents_confirmed=True,
        ).exclude(status=ShiftHandoverStatus.DRAFT).count()

        if submitted_count > 0:
            checklist_compliance_pct = round((checklist_compliant_count / submitted_count) * 100.0, 1)
        else:
            checklist_compliance_pct = 0.0

        # Average submission and acceptance delay (minutes)
        submission_durations = []
        acceptance_delays = []

        for h in qs.filter(submitted_at__isnull=False):
            if h.initiated_at and h.submitted_at and h.submitted_at >= h.initiated_at:
                submission_durations.append((h.submitted_at - h.initiated_at).total_seconds() / 60.0)
            if h.accepted_at and h.accepted_at >= h.submitted_at:
                acceptance_delays.append((h.accepted_at - h.submitted_at).total_seconds() / 60.0)

        avg_submission_min = round(statistics.mean(submission_durations), 1) if submission_durations else 0.0
        avg_acceptance_min = round(statistics.mean(acceptance_delays), 1) if acceptance_delays else 0.0

        return {
            "total_handovers": total_handovers,
            "draft_count": draft_count,
            "submitted_count": submitted_count,
            "accepted_count": accepted_count,
            "currently_disputed_count": currently_disputed_count,
            "historically_disputed_count": historically_disputed_count,
            "supervisor_resolved_count": supervisor_resolved_count,
            "cancelled_count": cancelled_count,
            "dispute_rate_pct": dispute_rate_pct,
            "checklist_compliant_count": checklist_compliant_count,
            "checklist_compliance_pct": checklist_compliance_pct,
            "avg_submission_minutes": avg_submission_min,
            "avg_acceptance_delay_minutes": avg_acceptance_min,
        }
