from django.urls import path
from weighbridge.exception_views import plate_exceptions
from weighbridge.blocked_plate_views import blocked_plates
from weighbridge import plate_autofill_views
from weighbridge import views

app_name = "weighbridge"

urlpatterns = [
    path("plate-exceptions/", plate_exceptions, name="plate_exceptions"),
    path("blocked-plates/", blocked_plates, name="blocked_plates"),
    path("plate-autofill/", plate_autofill_views.plate_autofill_list, name="plate_autofill"),
    path("tickets/create/", views.ticket_create, name="ticket_create"),

    path("tickets/<int:pk>/second-weight/", views.ticket_second_weight, name="ticket_second_weight"),
    path("trucks-in-yard/", views.trucks_in_yard, name="trucks_in_yard"),
    path("tickets/", views.ticket_list, name="ticket_list"),
    path("tickets/<int:pk>/", views.ticket_detail, name="ticket_detail"),
    path("tickets/<int:pk>/edit/", views.ticket_edit, name="ticket_edit"),
    path("tickets/<int:pk>/cancel/", views.ticket_cancel, name="ticket_cancel"),
    path("revisions/<uuid:revision_id>/approve/", views.ticket_revision_approve, name="ticket_revision_approve"),
    path("revisions/<uuid:revision_id>/reject/", views.ticket_revision_reject, name="ticket_revision_reject"),
    path("revisions/<uuid:revision_id>/withdraw/", views.ticket_revision_withdraw, name="ticket_revision_withdraw"),
    path("tickets/<int:pk>/print/", views.ticket_print, name="ticket_print"),
    path("tickets/<int:pk>/log-print/", views.log_ticket_print, name="log_ticket_print"),
    path("search/", views.global_search, name="global_search"),
    path("ajax/plate-lookup/", views.ajax_plate_lookup, name="ajax_plate_lookup"),

    # مرکز جامع چاپ و صدور مجدد قبوض (دسترس‌پذیر برای همه کاربران)
    path("print-center/", views.print_center, name="print_center"),
    path("print-center/batch-print/", views.batch_print, name="batch_print"),

    # توزین متفرقه و آزاد (شرکت‌های دیگر / اضطراری)
    path("emergency/", views.emergency_ticket_list, name="emergency_ticket_list"),
    path("emergency/create/", views.emergency_ticket_create, name="emergency_ticket_create"),
    path("emergency/<int:pk>/", views.emergency_ticket_detail, name="emergency_ticket_detail"),
    path("emergency/<int:pk>/second-weight/", views.emergency_ticket_second_weight, name="emergency_ticket_second_weight"),
    path("emergency/<int:pk>/print/", views.emergency_ticket_print, name="emergency_ticket_print"),
    path("emergency/<int:pk>/cancel/", views.emergency_ticket_cancel, name="emergency_ticket_cancel"),
]
