from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from decimal import Decimal
from datetime import timedelta
from drf_spectacular.utils import extend_schema

from core.jalali import get_today_gregorian
from management.kpi_service import OperationalKPIService
from api.v1.serializers.dashboard_serializers import (
    DashboardSummarySerializer, DashboardTrendSerializer
)


class DashboardSummaryView(APIView):
    """
    دریافت شاخص‌های کلیدی عملکرد امروز (تناژ، تعداد قبوض، وارده، صادره، مغایرت‌ها و هشدارهای باز).
    مبتنی بر سرویس یکپارچه OperationalKPIService.
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
        summary = OperationalKPIService.get_daily_operational_summary(today_g)

        data = {
            "today_ticket_count": summary["today_count"],
            "today_completed_count": summary["today_completed_count"],
            "today_net_weight": summary["today_net_kg"],
            "today_tonnage": float(summary["today_tonnage"]),
            "today_inbound_weight": summary["today_inbound_net"],
            "today_outbound_weight": summary["today_outbound_net"],
            "waiting_second_weight": summary["waiting_trucks_count"],
            "today_discrepancies": summary["today_discrepancies_count"],
            "open_alerts_count": summary["open_alerts_count"],
            "today_critical_alerts": summary["today_critical_alerts"],
        }
        return Response(data)


class DashboardTrendsView(APIView):
    """
    دریافت روندهای آماری ۳۰ روزه تناژ، سهم محصولات، مبادلات وارده/صادره و طرف‌های حساب جهت نمایش در نمودارها.
    مبتنی بر سرویس یکپارچه OperationalKPIService.
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
        start_date_30 = today_g - timedelta(days=29)

        trends_30 = OperationalKPIService.get_tonnage_trend(start_date_30, today_g, granularity="daily")
        prod_share = OperationalKPIService.get_product_share(limit=6)
        kpis_30 = OperationalKPIService.calculate_period_kpis(start_date=start_date_30, end_date=today_g)
        party_share = OperationalKPIService.get_party_share(limit=6)

        data = {
            "dates_30": trends_30["labels"],
            "tonnage_30": trends_30["net"],
            "trips_30": trends_30["trips"],
            "product_labels": prod_share["labels"],
            "product_values": prod_share["values"],
            "inbound_tonnage": kpis_30["inbound_net_ton"],
            "outbound_tonnage": kpis_30["outbound_net_ton"],
            "party_labels": party_share["labels"],
            "party_values": party_share["values"],
        }
        return Response(data)
