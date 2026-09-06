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


from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from django.shortcuts import get_object_or_404
from masterdata.models import Party, Product
from management.models import PartyScoringConfig, PartyScoreSnapshot
from management.party_analytics_service import PartyAnalyticsService
from audit.services import log_audit
from audit.models import AuditAction
from api.v1.permissions import (
    CanViewPartyAnalytics, CanViewPartyScore, CanViewPartyRanking,
    CanExportPartyAnalytics, CanManagePartyScoringConfig
)
from api.v1.serializers.management_serializers import (
    PartyScoringConfigSerializer, PartyDetailAnalyticsSerializer,
    PartyScoreResponseSerializer, PartyTrendResponseSerializer,
    PartyRankingResponseSerializer, PartyComparisonResponseSerializer
)
from management.exports import (
    export_party_ranking_excel, export_party_analytics_excel,
    export_party_ranking_csv, export_party_analytics_pdf
)
from core.jalali import jalali_to_gregorian, get_jalali_range_gregorian


class ManagementPartyDetailView(APIView):
    """
    مشاهده مشخصات کلی و شناسنامه اولیه طرف‌حساب.
    """
    permission_classes = [CanViewPartyAnalytics]

    @extend_schema(
        tags=['Management'],
        summary='مشاهده شناسنامه پایه طرف‌حساب',
        responses={200: OpenApiResponse(description='اطلاعات پایه طرف حساب')}
    )
    def get(self, request, pk):
        party = get_object_or_404(Party, pk=pk)
        return Response({
            "id": party.id,
            "name": party.name,
            "code": party.code,
            "party_type": party.party_type,
            "party_type_fa": party.get_party_type_display(),
            "phone": party.phone,
            "national_id": party.national_id,
            "economic_code": party.economic_code,
            "address": party.address,
        })


class ManagementPartyAnalyticsView(APIView):
    """
    تحلیل جامع آماری عملکرد طرف‌حساب شامل حجم، مغایرت وزن، افت، هشدارهای پایش، زمان توقف و اصلاحات.
    """
    permission_classes = [CanViewPartyAnalytics]

    @extend_schema(
        tags=['Management'],
        summary='تحلیل جامع آماری طرف‌حساب (Profile & KPIs)',
        parameters=[
            OpenApiParameter('quick_period', OpenApiTypes.STR, description='بازه سریع: today, this_week, this_month, last_month, this_year'),
            OpenApiParameter('start_date', OpenApiTypes.STR, description='تاریخ شروع شمسی مثلاً 1405/01/01 یا میلادی 2026-09-01'),
            OpenApiParameter('end_date', OpenApiTypes.STR, description='تاریخ پایان شمسی مثلاً 1405/06/31 یا میلادی 2026-09-30'),
            OpenApiParameter('product', OpenApiTypes.INT, description='شناسه محصول'),
        ],
        responses={200: PartyDetailAnalyticsSerializer}
    )
    def get(self, request, pk):
        party = get_object_or_404(Party, pk=pk)
        
        quick_period = request.GET.get('quick_period')
        start_str = request.GET.get('start_date')
        end_str = request.GET.get('end_date')
        prod_id = request.GET.get('product')

        start_d, end_d = None, None
        if quick_period and quick_period != 'custom':
            start_d, end_d = get_jalali_range_gregorian(quick_period)
        elif start_str and end_str:
            start_d = jalali_to_gregorian(start_str) if '/' in start_str else None
            end_d = jalali_to_gregorian(end_str) if '/' in end_str else None

        prod_obj = Product.objects.filter(pk=prod_id).first() if prod_id else None

        analysis = PartyAnalyticsService.analyze_party(
            party=party,
            start_date=start_d,
            end_date=end_d,
            product=prod_obj
        )
        return Response(analysis)


class ManagementPartyScoreView(APIView):
    """
    محاسبه و دریافت امتیاز کیفی طرف‌حساب به تفکیک ابعاد ۶ گانه و توضیحات تحلیلی شفاف.
    """
    permission_classes = [CanViewPartyScore]

    @extend_schema(
        tags=['Management'],
        summary='امتیاز کیفی و ابعاد ۶ گانه طرف‌حساب (Score Breakdown)',
        parameters=[
            OpenApiParameter('quick_period', OpenApiTypes.STR, description='بازه سریع: this_month, last_month, this_year'),
            OpenApiParameter('product', OpenApiTypes.INT, description='شناسه محصول'),
        ],
        responses={200: PartyScoreResponseSerializer}
    )
    def get(self, request, pk):
        party = get_object_or_404(Party, pk=pk)
        quick_period = request.GET.get('quick_period', 'this_month')
        prod_id = request.GET.get('product')

        start_d, end_d = get_jalali_range_gregorian(quick_period) if quick_period != 'custom' else (None, None)
        prod_obj = Product.objects.filter(pk=prod_id).first() if prod_id else None

        analysis = PartyAnalyticsService.analyze_party(party=party, start_date=start_d, end_date=end_d, product=prod_obj)
        return Response(analysis['score'])


class ManagementPartyTrendView(APIView):
    """
    تحلیل روند عملکردی طرف‌حساب در مقایسه با دوره مشابه قبلی و درصد تغییر شاخص‌ها.
    """
    permission_classes = [CanViewPartyAnalytics]

    @extend_schema(
        tags=['Management'],
        summary='تحلیل روند عملکرد طرف‌حساب (Trend Analysis)',
        parameters=[
            OpenApiParameter('quick_period', OpenApiTypes.STR, description='بازه سریع: this_month, last_month, this_year'),
            OpenApiParameter('product', OpenApiTypes.INT, description='شناسه محصول'),
        ],
        responses={200: PartyTrendResponseSerializer}
    )
    def get(self, request, pk):
        party = get_object_or_404(Party, pk=pk)
        quick_period = request.GET.get('quick_period', 'this_month')
        prod_id = request.GET.get('product')
        prod_obj = Product.objects.filter(pk=prod_id).first() if prod_id else None

        trend_res = PartyAnalyticsService.calculate_trend_analysis(
            party=party,
            quick_period=quick_period,
            product=prod_obj
        )
        return Response(trend_res)


class ManagementPartyRankingView(APIView):
    """
    رتبه‌بندی عادلانه طرف‌های حساب و تأمین‌کنندگان با اعمال حداقل سابقه آماری جهت جلوگیری از رتبه‌بندی تصادفی.
    """
    permission_classes = [CanViewPartyRanking]

    @extend_schema(
        tags=['Management'],
        summary='رتبه‌بندی طرف‌های حساب و تأمین‌کنندگان (Party Ranking)',
        parameters=[
            OpenApiParameter('party_type', OpenApiTypes.STR, description='نوع طرف حساب: supplier, customer, contractor'),
            OpenApiParameter('product', OpenApiTypes.INT, description='شناسه محصول جهت رتبه‌بندی کالامحور'),
            OpenApiParameter('minimum_tickets', OpenApiTypes.INT, description='حداقل قبوض برای ورود به رتبه‌بندی (پیش‌فرض: ۲۰)'),
            OpenApiParameter('ordering', OpenApiTypes.STR, description='مرتب‌سازی: overall_score, weight_accuracy, loss_performance, total_net_weight, alert_rate, average_discrepancy, average_turnaround'),
            OpenApiParameter('quick_period', OpenApiTypes.STR, description='بازه سریع: this_month, last_month, this_year'),
        ],
        responses={200: PartyRankingResponseSerializer}
    )
    def get(self, request):
        party_type = request.GET.get('party_type')
        prod_id = request.GET.get('product')
        min_tickets = request.GET.get('minimum_tickets')
        ordering = request.GET.get('ordering', 'overall_score')
        quick_period = request.GET.get('quick_period', 'this_month')

        min_t = int(min_tickets) if min_tickets and min_tickets.isdigit() else None
        prod_obj = Product.objects.filter(pk=prod_id).first() if prod_id else None
        start_d, end_d = get_jalali_range_gregorian(quick_period) if quick_period != 'custom' else (None, None)

        ranking_items = PartyAnalyticsService.get_party_ranking(
            start_date=start_d,
            end_date=end_d,
            party_type=party_type,
            product=prod_obj,
            minimum_tickets=min_t,
            ordering=ordering
        )

        cfg = PartyScoringConfig.get_config()
        applied_min = min_t if min_t is not None else cfg.minimum_tickets_for_ranking

        return Response({
            "count": len(ranking_items),
            "minimum_tickets_applied": applied_min,
            "ordering": ordering,
            "results": ranking_items
        })


class ManagementPartyCompareView(APIView):
    """
    مقایسه همزمان ۲ تا ۴ طرف‌حساب به صورت مقایسه جفتی/چندگانه، با امکان فیلتر کالایی.
    """
    permission_classes = [CanViewPartyAnalytics]

    @extend_schema(
        tags=['Management'],
        summary='مقایسه همزمان طرف‌های حساب (Party Comparison)',
        parameters=[
            OpenApiParameter('party_ids', OpenApiTypes.STR, required=True, description='شناسه‌های طرف‌حساب با ویرگول مثلاً 1,2,3'),
            OpenApiParameter('product', OpenApiTypes.INT, description='شناسه محصول جهت مقایسه در کانتکست یک کالای معین'),
            OpenApiParameter('quick_period', OpenApiTypes.STR, description='بازه سریع: this_month, last_month, this_year'),
        ],
        responses={200: PartyComparisonResponseSerializer}
    )
    def get(self, request):
        party_ids_str = request.GET.get('party_ids', '')
        if not party_ids_str:
            raise ValidationError({"party_ids": "ارسال حداقل ۲ شناسه طرف‌حساب الزامی است."})

        p_ids = []
        for s in party_ids_str.split(','):
            if s.strip().isdigit():
                p_ids.append(int(s.strip()))

        if len(p_ids) < 2 or len(p_ids) > 4:
            raise ValidationError({"party_ids": "امکان مقایسه همزمان بین ۲ تا ۴ طرف‌حساب مجاز است."})

        prod_id = request.GET.get('product')
        prod_obj = Product.objects.filter(pk=prod_id).first() if prod_id else None
        quick_period = request.GET.get('quick_period', 'this_month')
        start_d, end_d = get_jalali_range_gregorian(quick_period) if quick_period != 'custom' else (None, None)

        comp_res = PartyAnalyticsService.compare_parties(
            party_ids=p_ids,
            start_date=start_d,
            end_date=end_d,
            product=prod_obj
        )
        return Response(comp_res)


class ManagementPartyConfigView(APIView):
    """
    مشاهده و ویرایش وزن‌ها و تنظیمات فرمول امتیازدهی طرف‌حساب‌ها (دارای ثبت لاگ ممیزی کامل در AuditLog).
    """
    permission_classes = [CanManagePartyScoringConfig]

    @extend_schema(
        tags=['Management'],
        summary='دریافت تنظیمات فرمول امتیازدهی طرف‌حساب‌ها',
        responses={200: PartyScoringConfigSerializer}
    )
    def get(self, request):
        config = PartyScoringConfig.get_config()
        serializer = PartyScoringConfigSerializer(config)
        return Response(serializer.data)

    @extend_schema(
        tags=['Management'],
        summary='ویرایش وزن‌ها و تنظیمات فرمول امتیازدهی (نیازمند مجوز مدیریتی)',
        request=PartyScoringConfigSerializer,
        responses={200: PartyScoringConfigSerializer}
    )
    def put(self, request):
        config = PartyScoringConfig.get_config()
        old_data = {
            'dimension_weights': config.dimension_weights,
            'score_thresholds': config.score_thresholds,
            'confidence_thresholds': config.confidence_thresholds,
            'minimum_tickets_for_ranking': config.minimum_tickets_for_ranking,
            'trend_threshold': float(config.trend_threshold),
            'calculation_version': config.calculation_version,
        }

        serializer = PartyScoringConfigSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated_obj = serializer.save(updated_by=request.user)

        # ثبت تغییرات در لاگ رسمی ممیزی
        log_audit(
            action=AuditAction.UPDATE,
            model_name="PartyScoringConfig",
            record_id=str(updated_obj.id),
            record_repr=f"ویرایش فرمول امتیازدهی طرف‌حساب‌ها ({updated_obj.calculation_version})",
            old_values=old_data,
            new_values={
                'dimension_weights': updated_obj.dimension_weights,
                'score_thresholds': updated_obj.score_thresholds,
                'confidence_thresholds': updated_obj.confidence_thresholds,
                'minimum_tickets_for_ranking': updated_obj.minimum_tickets_for_ranking,
                'trend_threshold': float(updated_obj.trend_threshold),
                'calculation_version': updated_obj.calculation_version,
            },
            reason="به‌روزرسانی اوزان و آستانه‌های فرمول امتیازدهی از پنل مدیریت",
            user=request.user,
            source="API"
        )

        return Response(serializer.data)


class ManagementPartyExportXlsxView(APIView):
    """
    دانلود فایل اکسل چندبرگه تحلیل یک طرف‌حساب یا اکسل رتبه‌بندی کل طرف‌های حساب.
    """
    permission_classes = [CanExportPartyAnalytics]
    throttle_scope = 'export'

    @extend_schema(
        tags=['Management'],
        summary='خروجی اکسل کارنامه طرف‌حساب یا رتبه‌بندی',
        parameters=[
            OpenApiParameter('party_id', OpenApiTypes.INT, description='شناسه طرف‌حساب جهت دریافت کارنامه تک‌نفره چندبرگه'),
            OpenApiParameter('party_type', OpenApiTypes.STR, description='نوع طرف‌حساب جهت رتبه‌بندی'),
            OpenApiParameter('quick_period', OpenApiTypes.STR, description='بازه سریع'),
        ],
        responses={200: OpenApiResponse(description='فایل مایکروسافت اکسل (.xlsx)')}
    )
    def get(self, request):
        party_id = request.GET.get('party_id')
        quick_period = request.GET.get('quick_period', 'this_month')
        start_d, end_d = get_jalali_range_gregorian(quick_period) if quick_period != 'custom' else (None, None)

        if party_id:
            party = get_object_or_404(Party, pk=party_id)
            analysis = PartyAnalyticsService.analyze_party(party=party, start_date=start_d, end_date=end_d)
            return export_party_analytics_excel(party, analysis)
        else:
            party_type = request.GET.get('party_type')
            ranking_items = PartyAnalyticsService.get_party_ranking(
                start_date=start_d,
                end_date=end_d,
                party_type=party_type
            )
            return export_party_ranking_excel(ranking_items)


class ManagementPartyExportCsvView(APIView):
    """
    دانلود فایل CSV رتبه‌بندی یا تحلیل طرف‌حساب‌ها با انکودینگ UTF-8 BOM.
    """
    permission_classes = [CanExportPartyAnalytics]
    throttle_scope = 'export'

    @extend_schema(
        tags=['Management'],
        summary='خروجی CSV رتبه‌بندی طرف‌های حساب',
        responses={200: OpenApiResponse(description='فایل متنی CSV با انکودینگ UTF-8 BOM')}
    )
    def get(self, request):
        party_type = request.GET.get('party_type')
        quick_period = request.GET.get('quick_period', 'this_month')
        start_d, end_d = get_jalali_range_gregorian(quick_period) if quick_period != 'custom' else (None, None)

        ranking_items = PartyAnalyticsService.get_party_ranking(
            start_date=start_d,
            end_date=end_d,
            party_type=party_type
        )
        return export_party_ranking_csv(ranking_items)


class ManagementPartyExportPdfView(APIView):
    """
    دانلود کارنامه رسمی مدیریتی PDF طرف‌حساب با ReportLab.
    """
    permission_classes = [CanExportPartyAnalytics]
    throttle_scope = 'export'

    @extend_schema(
        tags=['Management'],
        summary='خروجی PDF کارنامه عملکرد طرف‌حساب',
        parameters=[
            OpenApiParameter('party_id', OpenApiTypes.INT, required=True, description='شناسه طرف‌حساب'),
            OpenApiParameter('quick_period', OpenApiTypes.STR, description='بازه زمانی'),
        ],
        responses={200: OpenApiResponse(description='سند الکترونیکی قابل حمل (.pdf)')}
    )
    def get(self, request):
        party_id = request.GET.get('party_id')
        if not party_id:
            raise ValidationError({"party_id": "شناسه طرف‌حساب جهت تولید گزارش PDF الزامی است."})

        party = get_object_or_404(Party, pk=party_id)
        quick_period = request.GET.get('quick_period', 'this_month')
        start_d, end_d = get_jalali_range_gregorian(quick_period) if quick_period != 'custom' else (None, None)

        analysis = PartyAnalyticsService.analyze_party(party=party, start_date=start_d, end_date=end_d)
        return export_party_analytics_pdf(party, analysis)
