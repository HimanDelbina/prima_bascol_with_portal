from django.urls import path
from management import views

app_name = 'management'

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('dashboard/', views.dashboard_view, name='dashboard_index'),
    path('api/charts/', views.api_dashboard_charts, name='api_charts'),
    path('api/filters/save/', views.api_save_filter, name='api_save_filter'),
    path('api/filters/load/', views.api_load_filters, name='api_load_filters'),
    path('inbound-outbound/', views.inbound_outbound_view, name='inbound_outbound'),
    path('purchases/', views.purchase_view, name='purchases'),
    path('sales/', views.sales_view, name='sales'),
    path('products/', views.products_view, name='products'),
    path('parties/', views.parties_view, name='parties'),
    path('discrepancies/', views.discrepancies_view, name='discrepancies'),
    path('loss/', views.loss_view, name='loss'),
    path('drivers-vehicles/', views.drivers_vehicles_view, name='drivers_vehicles'),
    path('routes/', views.routes_view, name='routes'),
    path('operations/', views.operations_view, name='operations'),
    path('monthly/', views.monthly_report_view, name='monthly'),
    path('yearly/', views.yearly_report_view, name='yearly'),
    path('print/', views.executive_print_view, name='print'),
    path('monitor/', views.tv_monitor_view, name='tv_monitor'),
]
