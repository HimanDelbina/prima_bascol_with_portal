from django.urls import path
from monitoring import views

app_name = "monitoring"

urlpatterns = [
    path("", views.monitoring_dashboard, name="dashboard"),
    path("alerts/", views.alert_list, name="alert_list"),
    path("alerts/<int:pk>/", views.alert_detail, name="alert_detail"),
    path("alerts/<int:pk>/resolve/", views.resolve_alert, name="resolve_alert"),
    path("settings/", views.monitoring_settings, name="settings"),
    path("reports/", views.monitoring_reports, name="reports"),
]
