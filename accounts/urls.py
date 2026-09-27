from django.urls import path
from accounts import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("password-change/", views.password_change_view, name="password_change"),
    path("password-reset/", views.password_reset_view, name="password_reset"),
    path("profile/", views.profile_view, name="profile"),
    path("users/", views.user_list_view, name="user_list"),
    path("users/create/", views.user_create_view, name="user_create"),
    path("users/<int:user_id>/edit/", views.user_edit_view, name="user_edit"),
    path("users/<int:user_id>/toggle/", views.user_toggle_status_view, name="user_toggle_status"),
]
