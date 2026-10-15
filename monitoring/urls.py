from django.urls import path
from monitoring import views

app_name = "monitoring"

urlpatterns = [
    path("", views.monitoring_dashboard, name="dashboard"),
    path("alerts/", views.alert_list, name="alert_list"),
    path("alerts/<int:pk>/", views.alert_detail, name="alert_detail"),
    path("alerts/<int:pk>/resolve/", views.resolve_alert, name="resolve_alert"),
    path("approvals/", views.approval_list, name="approval_list"),
    path("approvals/<int:pk>/decision/", views.approval_decision, name="approval_decision"),
    path("tickets/<int:pk>/request-approval/", views.ticket_request_approval, name="ticket_request_approval"),
    path("settings/", views.monitoring_settings, name="settings"),
    path("reports/", views.monitoring_reports, name="reports"),
]
