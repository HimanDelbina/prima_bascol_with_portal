from django.urls import path
from shifts import views

app_name = "shifts"

urlpatterns = [
    # Phase 4.3.2: Shift Management & Performance Dashboard
    path("dashboard/", views.shift_dashboard, name="dashboard"),
    path("dashboard/export/excel/", views.shift_dashboard_export_excel, name="dashboard_export_excel"),
    path("dashboard/export/pdf/", views.shift_dashboard_export_pdf, name="dashboard_export_pdf"),

    # WorkShift Schedule Management
    path("schedules/", views.shift_list, name="shift_list"),
    path("schedules/create/", views.shift_create, name="shift_create"),
    path("schedules/<int:pk>/edit/", views.shift_edit, name="shift_edit"),
    path("schedules/<int:pk>/toggle/", views.shift_toggle, name="shift_toggle"),

    # ShiftSession Lifecycle
    path("sessions/", views.session_list, name="session_list"),
    path("sessions/open/", views.session_open, name="session_open"),
    path("sessions/<int:pk>/", views.session_detail, name="session_detail"),
    path("sessions/<int:pk>/close/", views.session_close, name="session_close"),

    # Attendance & Assignment
    path("sessions/<int:session_pk>/assign/", views.operator_assign, name="operator_assign"),
    path("sessions/<int:pk>/check-in/", views.operator_check_in, name="operator_check_in"),
    path("assignments/<int:pk>/check-out/", views.operator_check_out, name="operator_check_out"),
    path("assignments/<int:assignment_pk>/substitute/", views.operator_substitute, name="operator_substitute"),

    # Supervisor Exceptions
    path("exceptions/", views.exception_list, name="exception_list"),
    path("exceptions/<int:pk>/acknowledge/", views.exception_acknowledge, name="exception_acknowledge"),

    # Phase 4.2: Formal Shift Handover
    path("handovers/", views.handover_list, name="handover_list"),
    path("handovers/initiate/<int:session_pk>/", views.handover_initiate, name="handover_initiate"),
    path("handovers/<int:pk>/", views.handover_detail, name="handover_detail"),
    path("handovers/<int:pk>/export/pdf/", views.shift_handover_export_pdf, name="handover_export_pdf"),
    path("handovers/<int:pk>/submit/", views.handover_submit, name="handover_submit"),
    path("handovers/<int:pk>/accept/", views.handover_accept, name="handover_accept"),
    path("handovers/<int:pk>/dispute/", views.handover_dispute, name="handover_dispute"),
    path("handovers/<int:pk>/resolve/", views.handover_resolve, name="handover_resolve"),
    path("handovers/<int:pk>/substitute-operator/", views.handover_substitute_operator, name="handover_substitute_operator"),
    path("handovers/<int:pk>/cancel/", views.handover_cancel, name="handover_cancel"),

    # Status API
    path("api/current-status/", views.current_shift_status, name="current_shift_status"),
]
