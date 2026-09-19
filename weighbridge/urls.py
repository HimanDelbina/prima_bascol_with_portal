from django.urls import path
from weighbridge.exception_views import plate_exceptions
from weighbridge import views

app_name = "weighbridge"

urlpatterns = [
    path("plate-exceptions/", plate_exceptions, name="plate_exceptions"),
    path("tickets/create/", views.ticket_create, name="ticket_create"),
    path("tickets/<int:pk>/second-weight/", views.ticket_second_weight, name="ticket_second_weight"),
    path("trucks-in-yard/", views.trucks_in_yard, name="trucks_in_yard"),
    path("tickets/", views.ticket_list, name="ticket_list"),
    path("tickets/<int:pk>/", views.ticket_detail, name="ticket_detail"),
    path("tickets/<int:pk>/edit/", views.ticket_edit, name="ticket_edit"),
    path("tickets/<int:pk>/cancel/", views.ticket_cancel, name="ticket_cancel"),
    path("tickets/<int:pk>/print/", views.ticket_print, name="ticket_print"),
    path("search/", views.global_search, name="global_search"),
    path("ajax/plate-lookup/", views.ajax_plate_lookup, name="ajax_plate_lookup"),
]
