from django.urls import path
from reports import views

app_name = "reports"

urlpatterns = [
    path("freight/", views.freight_report, name="freight_report"),
    path("builder/", views.report_builder, name="report_builder"),
    path("presets/", views.preset_reports_list, name="preset_reports_list"),
    path("presets/<str:code>/", views.preset_report_view, name="preset_report_view"),
]
