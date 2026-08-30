from django.urls import path
from core import views

app_name = "core"

urlpatterns = [
    path("settings/", views.settings_view, name="settings"),
    path("backup/", views.backup_view, name="backup"),
]
