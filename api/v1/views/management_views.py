from rest_framework.views import APIView
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes

from management.services import ManagementDashboardService, ManagementReportService
from api.v1.permissions import IsExecutiveManager
from api.v1.serializers.management_serializers import ManagementSummarySerializer
from core.jalali import format_jalali_date


class ManagementSummaryView(APIView):
    """
    خلاصه شاخص‌های عملکرد و تحلیل مقایسه‌ای دوره‌ای مدیران ارشد.
    """
    permission_classes = [IsExecutiveManager]

    @extend_schema(
        tags=['Management'],
        summary='خلاصه هوش تجاری و مقایسه دوره‌ای',
        description='دریافت شاخص‌های کلیدی عملکرد با مقایسه خودکار نسبت به دوره مشابه قبل (درصد تغییر، تفاضل، تحلیل متنی خودکار).',
        responses={200: ManagementSummarySerializer},
        parameters=[
            OpenApiParameter('quick_period', OpenApiTypes.STR, description='بازه سریع: today, this_week, this_month, this_year, last_month'),
            OpenApiParameter('start_date_jalali', OpenApiTypes.STR, description='تاریخ شروع شمسی مثلاً 1405/01/01'),
            OpenApiParameter('end_date_jalali', OpenApiTypes.STR, description='تاریخ پایان شمسی مثلاً 1405/06/31'),
            OpenApiParameter('operation_type', OpenApiTypes.INT, description='شناسه نوع عملیات'),
            OpenApiParameter('product', OpenApiTypes.INT, description='شناسه محصول'),
            OpenApiParameter('party', OpenApiTypes.INT, description='شناسه طرف حساب'),
        ]
    )
    def get(self, request):
        curr_qs, prev_qs, s_date, e_date, p_start, p_end, period_label = (
            ManagementDashboardService.get_filtered_queryset(request.GET)
        )
        curr_kpi, prev_kpi, comparison = ManagementDashboardService.calculate_kpis_with_comparison(curr_qs, prev_qs)
        top_metrics = ManagementDashboardService.get_top10_metrics(curr_qs)
        
        top_prod = top_metrics['top_products'][0]['name'] if top_metrics['top_products'] else ""
        top_party = top_metrics['top_parties'][0]['name'] if top_metrics['top_parties'] else ""
        narrative = ManagementDashboardService.generate_executive_narrative(curr_kpi, comparison, top_prod, top_party)
        alerts = ManagementDashboardService.detect_management_alerts(curr_qs)

        return Response({
            "period_label": period_label,
            "start_date": s_date.isoformat(),
            "end_date": e_date.isoformat(),
            "start_date_jalali": format_jalali_date(s_date),
            "end_date_jalali": format_jalali_date(e_date),
            "narrative": narrative,
            "kpis": curr_kpi,
            "comparison": comparison,
            "alerts": alerts,
        })


class ManagementProductsView(APIView):
    """
    تحلیل جامع عملکرد، تناژ و سهم محصولات در بازه انتخابی.
    """
    permission_classes = [IsExecutiveManager]

    @extend_schema(
        tags=['Management'],
        summary='تحلیل محصولات مدیران',
        responses={200: OpenApiResponse(description='لیست آمار تناژ و افت محصولات')}
    )
    def get(self, request):
        curr_qs, _, _, _, _, _, _ = ManagementDashboardService.get_filtered_queryset(request.GET)
        products_analysis = ManagementReportService.get_product_analysis(curr_qs)
        return Response({
            "count": len(products_analysis),
            "results": products_analysis
        })


class ManagementPartiesView(APIView):
    """
    تحلیل رفتار تجاری، تناژ، افت و مغایرت‌های طرف‌های حساب.
    """
    permission_classes = [IsExecutiveManager]

    @extend_schema(
        tags=['Management'],
        summary='تحلیل طرف‌های حساب مدیران',
        responses={200: OpenApiResponse(description='لیست آمار تناژ و رفتار تجاری طرف‌های حساب')}
    )
    def get(self, request):
        curr_qs, _, _, _, _, _, _ = ManagementDashboardService.get_filtered_queryset(request.GET)
        parties_analysis = ManagementReportService.get_party_analysis(curr_qs)
        return Response({
            "count": len(parties_analysis),
            "results": parties_analysis
        })


class ManagementDiscrepanciesView(APIView):
    """
    تحلیل تخصصی مغایرت‌های وزنی بارنامه و باسکول.
    """
    permission_classes = [IsExecutiveManager]

    @extend_schema(
        tags=['Management'],
        summary='تحلیل مغایرت‌های وزنی',
        responses={200: OpenApiResponse(description='آمار و گزارش مغایرت‌های وزنی')}
    )
    def get(self, request):
        curr_qs, _, _, _, _, _, _ = ManagementDashboardService.get_filtered_queryset(request.GET)
        discrepancy_data = ManagementReportService.get_discrepancy_analysis(curr_qs)
        
        party_aggr = list(discrepancy_data['party_aggr'])
        prod_aggr = list(discrepancy_data['prod_aggr'])

        return Response({
            "discrepancies_count": discrepancy_data['count'],
            "by_party": party_aggr,
            "by_product": prod_aggr,
        })


class ManagementLossesView(APIView):
    """
    تحلیل افت و کسری محموله‌ها به تفکیک نوع افت، کالا و تامین‌کننده.
    """
    permission_classes = [IsExecutiveManager]

    @extend_schema(
        tags=['Management'],
        summary='تحلیل افت و کسری محموله‌ها',
        responses={200: OpenApiResponse(description='تحلیل افت و کسری محموله‌ها')}
    )
    def get(self, request):
        curr_qs, _, _, _, _, _, _ = ManagementDashboardService.get_filtered_queryset(request.GET)
        loss_data = ManagementReportService.get_loss_analysis(curr_qs)
        
        return Response({
            "net_ton": loss_data['net_ton'],
            "loss_ton": loss_data['loss_ton'],
            "final_ton": loss_data['final_ton'],
            "avg_loss_pct": loss_data['avg_loss_pct'],
            "total_loads": loss_data['total_loads'],
            "loss_loads": loss_data['loss_loads'],
            "by_type": list(loss_data['by_type']),
            "by_product": list(loss_data['by_product']),
            "by_party": list(loss_data['by_party']),
        })


class ManagementVehiclesView(APIView):
    """
    تحلیل عملکرد ناوگان حمل و نقل و خودروها.
    """
    permission_classes = [IsExecutiveManager]

    @extend_schema(
        tags=['Management'],
        summary='تحلیل عملکرد ناوگان و خودروها',
        responses={200: OpenApiResponse(description='تحلیل عملکرد خودروها')}
    )
    def get(self, request):
        curr_qs, _, _, _, _, _, _ = ManagementDashboardService.get_filtered_queryset(request.GET)
        _, vehicle_rows = ManagementReportService.get_fleet_performance(curr_qs)
        return Response({
            "count": len(vehicle_rows),
            "results": vehicle_rows
        })


class ManagementDriversView(APIView):
    """
    تحلیل عملکرد و سفرهای رانندگان.
    """
    permission_classes = [IsExecutiveManager]

    @extend_schema(
        tags=['Management'],
        summary='تحلیل عملکرد رانندگان',
        responses={200: OpenApiResponse(description='تحلیل عملکرد رانندگان')}
    )
    def get(self, request):
        curr_qs, _, _, _, _, _, _ = ManagementDashboardService.get_filtered_queryset(request.GET)
        driver_rows, _ = ManagementReportService.get_fleet_performance(curr_qs)
        return Response({
            "count": len(driver_rows),
            "results": driver_rows
        })


class ManagementTurnaroundView(APIView):
    """
    تحلیل زمان حضور و معطلی خودروها در کارخانه.
    """
    permission_classes = [IsExecutiveManager]

    @extend_schema(
        tags=['Management'],
        summary='تحلیل زمان توقف و معطلی',
        responses={200: OpenApiResponse(description='تحلیل زمان معطلی ناوگان')}
    )
    def get(self, request):
        curr_qs, _, _, _, _, _, _ = ManagementDashboardService.get_filtered_queryset(request.GET)
        routes = ManagementReportService.get_routes_analysis(curr_qs)
        return Response({
            "origins": list(routes[0]),
            "destinations": list(routes[1]),
            "top_routes": list(routes[2]),
        })

