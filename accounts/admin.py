from django.contrib import admin
from accounts.models import UserProfile

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "role", "mobile", "personnel_code", "is_active"]
    list_filter = ["role", "is_active"]
    search_fields = ["user__username", "user__first_name", "user__last_name", "mobile"]
