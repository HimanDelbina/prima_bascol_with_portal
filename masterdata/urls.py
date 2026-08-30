from django.urls import path
from masterdata import views

app_name = "masterdata"

urlpatterns = [
    # Products
    path("products/", views.product_list, name="product_list"),
    path("products/create/", views.product_create, name="product_create"),
    path("products/<int:pk>/edit/", views.product_edit, name="product_edit"),
    path("products/<int:pk>/toggle/", views.product_toggle, name="product_toggle"),

    # Parties
    path("parties/", views.party_list, name="party_list"),
    path("parties/create/", views.party_create, name="party_create"),
    path("parties/<int:pk>/edit/", views.party_edit, name="party_edit"),
    path("parties/<int:pk>/toggle/", views.party_toggle, name="party_toggle"),

    # Drivers
    path("drivers/", views.driver_list, name="driver_list"),
    path("drivers/create/", views.driver_create, name="driver_create"),
    path("drivers/<int:pk>/edit/", views.driver_edit, name="driver_edit"),
    path("drivers/<int:pk>/toggle/", views.driver_toggle, name="driver_toggle"),

    # Vehicles
    path("vehicles/", views.vehicle_list, name="vehicle_list"),
    path("vehicles/create/", views.vehicle_create, name="vehicle_create"),
    path("vehicles/<int:pk>/edit/", views.vehicle_edit, name="vehicle_edit"),
    path("vehicles/<int:pk>/toggle/", views.vehicle_toggle, name="vehicle_toggle"),

    # Vehicle Types
    path("vehicle-types/", views.vehicle_type_list, name="vehicle_type_list"),
    path("vehicle-types/create/", views.vehicle_type_create, name="vehicle_type_create"),
    path("vehicle-types/<int:pk>/edit/", views.vehicle_type_edit, name="vehicle_type_edit"),
    path("vehicle-types/<int:pk>/toggle/", views.vehicle_type_toggle, name="vehicle_type_toggle"),

    # Locations
    path("locations/", views.location_list, name="location_list"),
    path("locations/create/", views.location_create, name="location_create"),
    path("locations/<int:pk>/edit/", views.location_edit, name="location_edit"),
    path("locations/<int:pk>/toggle/", views.location_toggle, name="location_toggle"),

    # Unload Locations
    path("unload-locations/", views.unload_location_list, name="unload_location_list"),
    path("unload-locations/create/", views.unload_location_create, name="unload_location_create"),
    path("unload-locations/<int:pk>/edit/", views.unload_location_edit, name="unload_location_edit"),
    path("unload-locations/<int:pk>/toggle/", views.unload_location_toggle, name="unload_location_toggle"),

    # Operation Types
    path("operation-types/", views.operation_type_list, name="operation_type_list"),
    path("operation-types/create/", views.operation_type_create, name="operation_type_create"),
    path("operation-types/<int:pk>/edit/", views.operation_type_edit, name="operation_type_edit"),
    path("operation-types/<int:pk>/toggle/", views.operation_type_toggle, name="operation_type_toggle"),

    # Loss Types
    path("loss-types/", views.loss_type_list, name="loss_type_list"),
    path("loss-types/create/", views.loss_type_create, name="loss_type_create"),
    path("loss-types/<int:pk>/edit/", views.loss_type_edit, name="loss_type_edit"),
    path("loss-types/<int:pk>/toggle/", views.loss_type_toggle, name="loss_type_toggle"),

    # Quick Add AJAX
    path("api/quick-add/party/", views.api_quick_add_party, name="api_quick_add_party"),
    path("api/quick-add/driver/", views.api_quick_add_driver, name="api_quick_add_driver"),
    path("api/quick-add/vehicle/", views.api_quick_add_vehicle, name="api_quick_add_vehicle"),
    path("api/quick-add/product/", views.api_quick_add_product, name="api_quick_add_product"),
]
