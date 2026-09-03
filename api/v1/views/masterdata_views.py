from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view

from masterdata.models import (
    Product, Party, Driver, VehicleType, Vehicle,
    Location, UnloadLocation, OperationType, LossType
)
from api.v1.serializers.masterdata_serializers import (
    ProductSerializer, PartySerializer, DriverSerializer,
    VehicleTypeSerializer, VehicleSerializer, LocationSerializer,
    UnloadLocationSerializer, OperationTypeSerializer, LossTypeSerializer
)
from api.v1.permissions import IsMasterDataAdminOrReadOnly
from weighbridge.models import WeighTicket


@extend_schema_view(
    list=extend_schema(tags=['Master Data'], summary='لیست محصولات'),
    retrieve=extend_schema(tags=['Master Data'], summary='مشاهده محصول'),
    create=extend_schema(tags=['Master Data'], summary='ایجاد محصول جدید'),
    update=extend_schema(tags=['Master Data'], summary='ویرایش کامل محصول'),
    partial_update=extend_schema(tags=['Master Data'], summary='ویرایش جزیی محصول'),
    destroy=extend_schema(tags=['Master Data'], summary='حذف محصول'),
)
class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all().order_by('name')
    serializer_class = ProductSerializer
    permission_classes = [IsMasterDataAdminOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active', 'code']
    search_fields = ['name', 'code', 'description']
    ordering_fields = ['name', 'code', 'created_at', 'standard_tolerance_kg']


@extend_schema_view(
    list=extend_schema(tags=['Master Data'], summary='لیست طرف‌های حساب'),
    retrieve=extend_schema(tags=['Master Data'], summary='مشاهده طرف حساب'),
    create=extend_schema(tags=['Master Data'], summary='ایجاد طرف حساب جدید'),
    update=extend_schema(tags=['Master Data'], summary='ویرایش طرف حساب'),
    partial_update=extend_schema(tags=['Master Data'], summary='ویرایش جزیی طرف حساب'),
    destroy=extend_schema(tags=['Master Data'], summary='حذف طرف حساب'),
)
class PartyViewSet(viewsets.ModelViewSet):
    queryset = Party.objects.all().order_by('name')
    serializer_class = PartySerializer
    permission_classes = [IsMasterDataAdminOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active', 'party_type', 'code']
    search_fields = ['name', 'code', 'phone', 'tel', 'national_id', 'economic_code']
    ordering_fields = ['name', 'code', 'created_at', 'party_type']


@extend_schema_view(
    list=extend_schema(tags=['Master Data'], summary='لیست رانندگان'),
    retrieve=extend_schema(tags=['Master Data'], summary='مشاهده راننده'),
    create=extend_schema(tags=['Master Data'], summary='ثبت راننده جدید'),
    update=extend_schema(tags=['Master Data'], summary='ویرایش راننده'),
    partial_update=extend_schema(tags=['Master Data'], summary='ویرایش جزیی راننده'),
    destroy=extend_schema(tags=['Master Data'], summary='حذف راننده'),
)
class DriverViewSet(viewsets.ModelViewSet):
    queryset = Driver.objects.all().order_by('full_name')
    serializer_class = DriverSerializer
    permission_classes = [IsMasterDataAdminOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active']
    search_fields = ['full_name', 'mobile', 'national_code', 'license_number']
    ordering_fields = ['full_name', 'created_at']


@extend_schema_view(
    list=extend_schema(tags=['Master Data'], summary='لیست خودروها'),
    retrieve=extend_schema(tags=['Master Data'], summary='مشاهده خودرو'),
    create=extend_schema(tags=['Master Data'], summary='ثبت خودرو جدید'),
    update=extend_schema(tags=['Master Data'], summary='ویرایش خودرو'),
    partial_update=extend_schema(tags=['Master Data'], summary='ویرایش جزیی خودرو'),
    destroy=extend_schema(tags=['Master Data'], summary='حذف خودرو'),
)
class VehicleViewSet(viewsets.ModelViewSet):
    queryset = Vehicle.objects.select_related('vehicle_type', 'default_driver').all().order_by('plate_display')
    serializer_class = VehicleSerializer
    permission_classes = [IsMasterDataAdminOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active', 'vehicle_type']
    search_fields = ['plate_display', 'plate_part1', 'plate_part2', 'plate_iran', 'default_driver__full_name']
    ordering_fields = ['plate_display', 'created_at', 'empty_weight']

    @extend_schema(
        tags=['Master Data'],
        summary='سوابق توزین و تردد خودرو',
        description='دریافت لیست تمام قبوض ثبت‌شده برای این خودرو به صورت صفحه‌بندی‌شده.',
    )
    @action(detail=True, methods=['get'], url_path='history')
    def history(self, request, pk=None):
        vehicle = self.get_object()
        from api.v1.serializers.ticket_serializers import WeighTicketListSerializer
        tickets = WeighTicket.objects.filter(
            vehicle=vehicle
        ).select_related("product", "party", "driver", "operation_type").order_by('-id')

        page = self.paginate_queryset(tickets)
        if page is not None:
            serializer = WeighTicketListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = WeighTicketListSerializer(tickets, many=True)
        return Response(serializer.data)


@extend_schema_view(
    list=extend_schema(tags=['Master Data'], summary='لیست انواع خودروها'),
    retrieve=extend_schema(tags=['Master Data'], summary='مشاهده نوع خودرو'),
    create=extend_schema(tags=['Master Data'], summary='ثبت نوع خودرو جدید'),
    update=extend_schema(tags=['Master Data'], summary='ویرایش نوع خودرو'),
    destroy=extend_schema(tags=['Master Data'], summary='حذف نوع خودرو'),
)
class VehicleTypeViewSet(viewsets.ModelViewSet):
    queryset = VehicleType.objects.all().order_by('name')
    serializer_class = VehicleTypeSerializer
    permission_classes = [IsMasterDataAdminOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active']
    search_fields = ['name', 'code']


@extend_schema_view(
    list=extend_schema(tags=['Master Data'], summary='لیست مبادی و مقاصد'),
    retrieve=extend_schema(tags=['Master Data'], summary='مشاهده محل'),
    create=extend_schema(tags=['Master Data'], summary='ثبت محل جدید'),
    update=extend_schema(tags=['Master Data'], summary='ویرایش محل'),
    destroy=extend_schema(tags=['Master Data'], summary='حذف محل'),
)
class LocationViewSet(viewsets.ModelViewSet):
    queryset = Location.objects.all().order_by('name')
    serializer_class = LocationSerializer
    permission_classes = [IsMasterDataAdminOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active', 'location_type']
    search_fields = ['name', 'description']


@extend_schema_view(
    list=extend_schema(tags=['Master Data'], summary='لیست جایگاه‌های تخلیه/بارگیری'),
    retrieve=extend_schema(tags=['Master Data'], summary='مشاهده جایگاه'),
    create=extend_schema(tags=['Master Data'], summary='ثبت جایگاه جدید'),
    update=extend_schema(tags=['Master Data'], summary='ویرایش جایگاه'),
    destroy=extend_schema(tags=['Master Data'], summary='حذف جایگاه'),
)
class UnloadLocationViewSet(viewsets.ModelViewSet):
    queryset = UnloadLocation.objects.all().order_by('name')
    serializer_class = UnloadLocationSerializer
    permission_classes = [IsMasterDataAdminOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active']
    search_fields = ['name', 'code', 'description']


@extend_schema_view(
    list=extend_schema(tags=['Master Data'], summary='لیست انواع عملیات بار'),
    retrieve=extend_schema(tags=['Master Data'], summary='مشاهده نوع عملیات'),
    create=extend_schema(tags=['Master Data'], summary='ثبت نوع عملیات جدید'),
    update=extend_schema(tags=['Master Data'], summary='ویرایش نوع عملیات'),
    destroy=extend_schema(tags=['Master Data'], summary='حذف نوع عملیات'),
)
class OperationTypeViewSet(viewsets.ModelViewSet):
    queryset = OperationType.objects.all().order_by('name')
    serializer_class = OperationTypeSerializer
    permission_classes = [IsMasterDataAdminOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active', 'direction']
    search_fields = ['name', 'code']


@extend_schema_view(
    list=extend_schema(tags=['Master Data'], summary='لیست انواع افت کالا'),
    retrieve=extend_schema(tags=['Master Data'], summary='مشاهده نوع افت'),
    create=extend_schema(tags=['Master Data'], summary='ثبت نوع افت جدید'),
    update=extend_schema(tags=['Master Data'], summary='ویرایش نوع افت'),
    destroy=extend_schema(tags=['Master Data'], summary='حذف نوع افت'),
)
class LossTypeViewSet(viewsets.ModelViewSet):
    queryset = LossType.objects.all().order_by('name')
    serializer_class = LossTypeSerializer
    permission_classes = [IsMasterDataAdminOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active']
    search_fields = ['name', 'code', 'description']
