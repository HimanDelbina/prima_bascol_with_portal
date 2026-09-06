from django.urls import path, include
from rest_framework.routers import DefaultRouter

from api.v1.views.auth_views import (
    VerifyPasswordView,
    CustomTokenObtainPairView, CustomTokenRefreshView,
    CustomTokenVerifyView, LogoutView, CurrentUserView
)
from api.v1.views.masterdata_views import (
    ProductViewSet, PartyViewSet, DriverViewSet,
    VehicleViewSet, VehicleTypeViewSet, LocationViewSet,
    UnloadLocationViewSet, OperationTypeViewSet, LossTypeViewSet
)
from api.v1.views.ticket_views import WeighTicketViewSet
from api.v1.views.dashboard_views import (
    DashboardSummaryView, DashboardTrendsView
)
from api.v1.views.management_views import (
    ManagementSummaryView, ManagementProductsView,
    ManagementPartiesView, ManagementDiscrepanciesView,
    ManagementLossesView, ManagementVehiclesView,
    ManagementDriversView, ManagementTurnaroundView,
    ManagementPartyDetailView, ManagementPartyAnalyticsView,
    ManagementPartyScoreView, ManagementPartyTrendView,
    ManagementPartyRankingView, ManagementPartyCompareView,
    ManagementPartyConfigView, ManagementPartyExportXlsxView,
    ManagementPartyExportCsvView, ManagementPartyExportPdfView
)
from api.v1.views.monitoring_views import (
    MonitoringAlertViewSet, MonitoringRuleConfigViewSet
)
from api.v1.views.reports_views import (
    ReportTicketsView, ReportSummaryView, ReportGroupedView,
    ReportExportXlsxView, ReportExportCsvView, ReportExportPdfView
)
from api.v1.views.audit_views import AuditLogViewSet
from api.v1.views.user_views import UserViewSet, RoleListView
from api.v1.views.system_views import (
    PublicSettingsView, AdminSettingsView, HealthCheckView, MetaView
)

app_name = 'api_v1'

router = DefaultRouter()
router.register('products', ProductViewSet, basename='product')
router.register('parties', PartyViewSet, basename='party')
router.register('drivers', DriverViewSet, basename='driver')
router.register('vehicles', VehicleViewSet, basename='vehicle')
router.register('vehicle-types', VehicleTypeViewSet, basename='vehicletype')
router.register('locations', LocationViewSet, basename='location')
router.register('unload-locations', UnloadLocationViewSet, basename='unloadlocation')
router.register('operation-types', OperationTypeViewSet, basename='operationtype')
router.register('loss-types', LossTypeViewSet, basename='losstype')
router.register('tickets', WeighTicketViewSet, basename='ticket')
router.register('monitoring/alerts', MonitoringAlertViewSet, basename='monitoring-alert')
router.register('monitoring/rules', MonitoringRuleConfigViewSet, basename='monitoring-rule')
router.register('audit', AuditLogViewSet, basename='audit')
router.register('users', UserViewSet, basename='user')

urlpatterns = [
    # Authentication
    path('auth/token/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/token/refresh/', CustomTokenRefreshView.as_view(), name='token_refresh'),
    path('auth/token/verify/', CustomTokenVerifyView.as_view(), name='token_verify'),
    path('auth/logout/', LogoutView.as_view(), name='logout'),
    path('auth/me/', CurrentUserView.as_view(), name='auth_me'),
    path('auth/verify-password/', VerifyPasswordView.as_view(), name='verify_password'),

    # Dashboard
    path('dashboard/summary/', DashboardSummaryView.as_view(), name='dashboard_summary'),
    path('dashboard/trends/', DashboardTrendsView.as_view(), name='dashboard_trends'),

    # Management Suite (BI)
    path('management/summary/', ManagementSummaryView.as_view(), name='management_summary'),
    path('management/products/', ManagementProductsView.as_view(), name='management_products'),
    path('management/parties/', ManagementPartiesView.as_view(), name='management_parties'),
    path('management/parties/ranking/', ManagementPartyRankingView.as_view(), name='management_parties_ranking'),
    path('management/parties/compare/', ManagementPartyCompareView.as_view(), name='management_parties_compare'),
    path('management/parties/config/', ManagementPartyConfigView.as_view(), name='management_parties_config'),
    path('management/parties/export/xlsx/', ManagementPartyExportXlsxView.as_view(), name='management_parties_export_xlsx'),
    path('management/parties/export/csv/', ManagementPartyExportCsvView.as_view(), name='management_parties_export_csv'),
    path('management/parties/export/pdf/', ManagementPartyExportPdfView.as_view(), name='management_parties_export_pdf'),
    path('management/parties/<int:pk>/', ManagementPartyDetailView.as_view(), name='management_party_detail'),
    path('management/parties/<int:pk>/analytics/', ManagementPartyAnalyticsView.as_view(), name='management_party_analytics'),
    path('management/parties/<int:pk>/score/', ManagementPartyScoreView.as_view(), name='management_party_score'),
    path('management/parties/<int:pk>/trend/', ManagementPartyTrendView.as_view(), name='management_party_trend'),
    path('management/discrepancies/', ManagementDiscrepanciesView.as_view(), name='management_discrepancies'),
    path('management/losses/', ManagementLossesView.as_view(), name='management_losses'),
    path('management/vehicles/', ManagementVehiclesView.as_view(), name='management_vehicles'),
    path('management/drivers/', ManagementDriversView.as_view(), name='management_drivers'),
    path('management/turnaround/', ManagementTurnaroundView.as_view(), name='management_turnaround'),

    # Monitoring Summary Shortcut
    path('monitoring/summary/', MonitoringAlertViewSet.as_view({'get': 'monitoring_summary'}), name='monitoring_summary'),

    # Reports & Exports
    path('reports/tickets/', ReportTicketsView.as_view(), name='reports_tickets'),
    path('reports/tickets/summary/', ReportSummaryView.as_view(), name='reports_tickets_summary'),
    path('reports/tickets/grouped/', ReportGroupedView.as_view(), name='reports_tickets_grouped'),
    path('reports/tickets/export/xlsx/', ReportExportXlsxView.as_view(), name='reports_export_xlsx'),
    path('reports/tickets/export/csv/', ReportExportCsvView.as_view(), name='reports_export_csv'),
    path('reports/tickets/export/pdf/', ReportExportPdfView.as_view(), name='reports_export_pdf'),

    # Roles & Permissions
    path('roles/', RoleListView.as_view(), name='roles_list'),

    # System Settings & Meta
    path('settings/', PublicSettingsView.as_view(), name='public_settings'),
    path('admin/settings/', AdminSettingsView.as_view(), name='admin_settings'),
    path('health/', HealthCheckView.as_view(), name='health_check'),
    path('meta/', MetaView.as_view(), name='meta'),

    # Router ViewSets
    path('', include(router.urls)),
]
