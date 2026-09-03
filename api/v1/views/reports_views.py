from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes

from reports.services import ReportService
from reports.exports import export_excel, export_csv, export_pdf
from api.v1.serializers.ticket_serializers import WeighTicketListSerializer
from api.v1.serializers.reports_serializers import ReportSummarySerializer
from api.v1.pagination import StandardResultsSetPagination


class ReportTicketsView(APIView):
    """
    دریافت لیست داده‌های گزارش‌ساز پیشرفته با پشتیبانی همزمان از کلیه پارامترهای فیلترینگ.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Reports'],
        summary='گزارش‌ساز پیشرفته قبوض',
        description='فیلتر همزمان بر اساس تاریخ شمسی/میلادی، کالا، مشتری، راننده، پلاک، مبدأ، مقصد، اپراتور، افت و وضعیت سند با صفحه‌بندی.',
        responses={200: WeighTicketListSerializer(many=True)},
        parameters=[
            OpenApiParameter('start_date', OpenApiTypes.STR, description='تاریخ شروع شمسی مثلاً 1405/01/01'),
            OpenApiParameter('end_date', OpenApiTypes.STR, description='تاریخ پایان شمسی مثلاً 1405/06/31'),
            OpenApiParameter('product', OpenApiTypes.INT, description='شناسه محصول'),
            OpenApiParameter('party', OpenApiTypes.INT, description='شناسه طرف حساب'),
            OpenApiParameter('status', OpenApiTypes.STR, description='وضعیت سند: completed, waiting_second, cancelled'),
            OpenApiParameter('operation_direction', OpenApiTypes.STR, description='جهت عملیات: inbound, outbound, internal'),
            OpenApiParameter('tolerance_exceeded', OpenApiTypes.STR, description='مغایرت بیش از حد مجاز: yes, no'),
            OpenApiParameter('has_loss', OpenApiTypes.STR, description='دارای افت: yes, no'),
        ]
    )
    def get(self, request):
        qs = ReportService.filter_tickets(request.GET)
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(qs, request)
        if page is not None:
            serializer = WeighTicketListSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        serializer = WeighTicketListSerializer(qs, many=True)
        return Response(serializer.data)


class ReportSummaryView(APIView):
    """
    دریافت کارت‌های خلاصه آماری (مجموع تناژ ناخالص، تارا، خالص، ارسالی، افت، نهایی، میانگین و تعداد).
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Reports'],
        summary='خلاصه آماری گزارش (کارت‌های KPI)',
        description='محاسبه درون‌دیتابیسی مجموع اوزان، میانگین و افت برای رکوردهای منطبق بر فیلترهای ارسالی.',
        responses={200: ReportSummarySerializer}
    )
    def get(self, request):
        qs = ReportService.filter_tickets(request.GET)
        summary = ReportService.get_summary_metrics(qs)
        return Response(summary)


class ReportGroupedView(APIView):
    """
    گزارش تجمیعی دسته‌بندی‌شده پویا (Group By) بر اساس محصول، طرف حساب، روز، اپراتور، پلاک یا مبدأ/مقصد.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Reports'],
        summary='گزارش دسته‌بندی‌شده پویا (Group By)',
        description='تجمیع داده‌ها بر اساس یک بعد دلخواه (day, product, party, driver, plate, origin, destination, unload_location, operation_type, operator).',
        responses={200: OpenApiResponse(description='گزارش دسته‌بندی‌شده تجمیعی')},
        parameters=[
            OpenApiParameter('group_by', OpenApiTypes.STR, required=True, description='فیلد گروه‌بندی: day, product, party, driver, plate, origin, destination, unload_location, operation_type, operator'),
        ]
    )
    def get(self, request):
        group_by = request.GET.get('group_by', 'product')
        qs = ReportService.filter_tickets(request.GET)
        results = ReportService.group_by_field(qs, group_by)
        return Response({
            "group_by": group_by,
            "count": len(results),
            "results": results
        })


class ReportExportXlsxView(APIView):
    """
    خروجی فایل اکسل استایل‌بندی‌شده و راست‌چین (.xlsx) با اعمال کلیه فیلترهای جستجو.
    """
    permission_classes = [IsAuthenticated]
    throttle_scope = 'export'

    @extend_schema(
        tags=['Reports'],
        summary='خروجی اکسل گزارش (.xlsx)',
        description='دانلود فایل اکسل کامل، راست‌چین و فرمت‌بندی‌شده گزارش باسکول بر اساس فیلترهای ارسالی.',
        responses={200: OpenApiResponse(description='فایل اکسل مایکروسافت (.xlsx)')}
    )
    def get(self, request):
        qs = ReportService.filter_tickets(request.GET)
        summary = ReportService.get_summary_metrics(qs)
        return export_excel(qs, summaries=summary, title="گزارش قبوض باسکول")


class ReportExportCsvView(APIView):
    """
    خروجی فایل CSV استاندارد با انکودینگ UTF-8 BOM جهت سازگاری با اکسل.
    """
    permission_classes = [IsAuthenticated]
    throttle_scope = 'export'

    @extend_schema(
        tags=['Reports'],
        summary='خروجی CSV گزارش (.csv)',
        description='دانلود فایل CSV استاندارد با UTF-8 BOM جهت پردازش در نرم‌افزارهای تحلیلی و اکسل.',
        responses={200: OpenApiResponse(description='فایل متنی جداشده با کاما (.csv)')}
    )
    def get(self, request):
        qs = ReportService.filter_tickets(request.GET)
        return export_csv(qs, title="گزارش قبوض باسکول")


class ReportExportPdfView(APIView):
    """
    خروجی فایل PDF رسمی گزارش باسکول.
    """
    permission_classes = [IsAuthenticated]
    throttle_scope = 'export'

    @extend_schema(
        tags=['Reports'],
        summary='خروجی PDF گزارش (.pdf)',
        description='دانلود فایل PDF استاندارد جدول قبوض جهت چاپ و بایگانی اسناد.',
        responses={200: OpenApiResponse(description='سند الکترونیکی قابل حمل (.pdf)')}
    )
    def get(self, request):
        qs = ReportService.filter_tickets(request.GET)
        summary = ReportService.get_summary_metrics(qs)
        return export_pdf(qs, summaries=summary, title="گزارش رسمی قبوض باسکول")
