from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count, Q
from decimal import Decimal
from datetime import timedelta
from drf_spectacular.utils import extend_schema

from weighbridge.models import WeighTicket, TicketStatus
from monitoring.models import MonitoringAlert, AlertStatus, AlertSeverity
from core.jalali import get_today_gregorian, format_jalali_date
from api.v1.serializers.dashboard_serializers import (
    DashboardSummarySerializer, DashboardTrendSerializer
)


class DashboardSummaryView(APIView):
    """
    دریافت شاخص‌های کلیدی عملکرد امروز (تناژ، تعداد قبوض، وارده، صادره، مغایرت‌ها و هشدارهای باز).
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Dashboard'],
        summary='خلاصه آمار لحظه‌ای امروز',
        description='محاسبه درون‌دیتابیسی تجمیعی تناژ، تعداد توزین، خودروهای در انتظار و هشدارهای پایش امروز.',
        responses={200: DashboardSummarySerializer}
    )
    def get(self, request):
        today_g = get_today_gregorian()
        today_tickets = WeighTicket.objects.filter(
            Q(first_weight_date=today_g) | Q(created_at__date=today_g)
        )

        today_count = today_tickets.count()
        today_completed_count = today_tickets.filter(status=TicketStatus.COMPLETED).count()

        aggr = today_tickets.aggregate(
            sum_net=Sum("net_weight"),
            inbound_net=Sum("net_weight", filter=Q(operation_type__direction="inbound")),
            outbound_net=Sum("net_weight", filter=Q(operation_type__direction="outbound")),
        )

        today_net = aggr["sum_net"] or Decimal("0.00")
        today_inbound = aggr["inbound_net"] or Decimal("0.00")
        today_outbound = aggr["outbound_net"] or Decimal("0.00")

        waiting_count = WeighTicket.objects.filter(
            status__in=[TicketStatus.WAITING_SECOND, TicketStatus.FIRST_REGISTERED]
        ).count()

        discrepancies_count = today_tickets.filter(is_tolerance_exceeded=True).count()

        open_alerts = MonitoringAlert.objects.filter(status__in=[AlertStatus.OPEN, AlertStatus.REVIEWED]).count()
        today_critical = MonitoringAlert.objects.filter(
            created_at__date=today_g,
            severity__in=[AlertSeverity.CRITICAL, AlertSeverity.HIGH],
            status__in=[AlertStatus.OPEN, AlertStatus.REVIEWED]
        ).count()

        data = {
            "today_ticket_count": today_count,
            "today_completed_count": today_completed_count,
            "today_net_weight": today_net,
            "today_tonnage": round(float(today_net) / 1000.0, 2),
            "today_inbound_weight": today_inbound,
            "today_outbound_weight": today_outbound,
            "waiting_second_weight": waiting_count,
            "today_discrepancies": discrepancies_count,
            "open_alerts_count": open_alerts,
            "today_critical_alerts": today_critical,
        }
        return Response(data)


class DashboardTrendsView(APIView):
    """
    دریافت روندهای آماری ۳۰ روزه تناژ، سهم محصولات، مبادلات وارده/صادره و طرف‌های حساب جهت نمایش در نمودارها.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Dashboard'],
        summary='روندهای آماری و چارت‌ها',
        description='دیتاست‌های استاندارد سری زمانی جهت رندر نمودارهای خطی، میله‌ای و دایره‌ای در فرانت‌اند، موبایل و Power BI.',
        responses={200: DashboardTrendSerializer}
    )
    def get(self, request):
        today_g = get_today_gregorian()

        # 30-day timeline
        dates_30 = []
        tonnage_30 = []
        trips_30 = []

        for i in range(29, -1, -1):
            target_day = today_g - timedelta(days=i)
            day_qs = WeighTicket.objects.filter(
                Q(first_weight_date=target_day) | Q(created_at__date=target_day)
            )
            day_net = day_qs.aggregate(s=Sum("net_weight"))["s"] or Decimal("0")
            day_trips = day_qs.count()

            dates_30.append(format_jalali_date(target_day, fmt="%m/%d"))
            tonnage_30.append(round(float(day_net) / 1000.0, 2))
            trips_30.append(day_trips)

        # Product share (top 6)
        top_prods_qs = WeighTicket.objects.filter(
            status=TicketStatus.COMPLETED,
            product__isnull=False
        ).values("product__name").annotate(
            total_net=Sum("net_weight")
        ).order_by("-total_net")[:6]

        product_labels = [p["product__name"] or "نامشخص" for p in top_prods_qs]
        product_values = [round(float(p["total_net"] or 0) / 1000.0, 2) for p in top_prods_qs]

        # Inbound vs Outbound
        inbound_net = WeighTicket.objects.filter(
            status=TicketStatus.COMPLETED,
            operation_type__direction="inbound"
        ).aggregate(s=Sum("net_weight"))["s"] or Decimal("0")

        outbound_net = WeighTicket.objects.filter(
            status=TicketStatus.COMPLETED,
            operation_type__direction="outbound"
        ).aggregate(s=Sum("net_weight"))["s"] or Decimal("0")

        # Top Parties
        top_parties_qs = WeighTicket.objects.filter(
            status=TicketStatus.COMPLETED,
            party__isnull=False
        ).values("party__name").annotate(
            total_net=Sum("net_weight")
        ).order_by("-total_net")[:6]

        party_labels = [p["party__name"] or "نامشخص" for p in top_parties_qs]
        party_values = [round(float(p["total_net"] or 0) / 1000.0, 2) for p in top_parties_qs]

        data = {
            "dates_30": dates_30,
            "tonnage_30": tonnage_30,
            "trips_30": trips_30,
            "product_labels": product_labels,
            "product_values": product_values,
            "inbound_tonnage": round(float(inbound_net) / 1000.0, 2),
            "outbound_tonnage": round(float(outbound_net) / 1000.0, 2),
            "party_labels": party_labels,
            "party_values": party_values,
        }
        return Response(data)
