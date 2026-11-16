from django.contrib import admin
from accounts.models import BascolIdentity, UserProfile

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "role", "mobile", "personnel_code", "is_active"]
    list_filter = ["role", "is_active"]
    search_fields = ["user__username", "user__first_name", "user__last_name", "mobile"]


@admin.register(BascolIdentity)
class BascolIdentityAdmin(admin.ModelAdmin):
    list_display = ("user", "issuer", "enabled")
    search_fields = ("user__username", "subject")

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    has_add_permission = has_change_permission = has_delete_permission = has_view_permission
