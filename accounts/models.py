from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

class RoleChoices(models.TextChoices):
    SUPER_ADMIN = "super_admin", "مدیر ارشد (Super Admin)"
    SYSTEM_ADMIN = "system_admin", "مدیر سیستم (System Admin)"
    CEO = "ceo", "مدیرعامل (CEO)"
    FACTORY_MANAGER = "factory_manager", "مدیر کارخانه (Factory Manager)"
    COMMERCIAL_MANAGER = "commercial_manager", "مدیر بازرگانی (Commercial Manager)"
    FINANCIAL_MANAGER = "financial_manager", "مدیر مالی (Financial Manager)"
    WEIGHBRIDGE_MANAGER = "weighbridge_manager", "مدیر باسکول (Weighbridge Manager)"
    WEIGHBRIDGE_OPERATOR = "weighbridge_operator", "اپراتور باسکول (Operator)"
    REPORT_MANAGER = "report_manager", "مدیر گزارشات (Report Manager)"
    WAREHOUSE = "warehouse", "مسئول انبار (Warehouse)"
    VIEWER = "viewer", "مشاهده‌گر (Viewer)"

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile", verbose_name="کاربر")
    role = models.CharField(
        max_length=30, 
        choices=RoleChoices.choices, 
        default=RoleChoices.WEIGHBRIDGE_OPERATOR,
        verbose_name="نقش کاربری"
    )
    mobile = models.CharField(max_length=20, blank=True, verbose_name="شماره موبایل")
    personnel_code = models.CharField(max_length=30, blank=True, verbose_name="کد پرسنلی")
    is_active = models.BooleanField(default=True, verbose_name="فعال")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ایجاد")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاریخ ویرایش")

    class Meta:
        verbose_name = "پروفایل کاربر"
        verbose_name_plural = "پروفایل کاربران"

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.get_role_display()})"

    @property
    def is_admin_or_manager(self):
        return self.user.is_superuser or self.role in [
            RoleChoices.SUPER_ADMIN,
            RoleChoices.SYSTEM_ADMIN,
            RoleChoices.CEO,
            RoleChoices.FACTORY_MANAGER,
            RoleChoices.COMMERCIAL_MANAGER,
            RoleChoices.FINANCIAL_MANAGER,
            RoleChoices.WEIGHBRIDGE_MANAGER,
        ]

    @property
    def is_executive_manager(self):
        return self.user.is_superuser or self.role in [
            RoleChoices.SUPER_ADMIN,
            RoleChoices.SYSTEM_ADMIN,
            RoleChoices.CEO,
            RoleChoices.FACTORY_MANAGER,
            RoleChoices.COMMERCIAL_MANAGER,
            RoleChoices.FINANCIAL_MANAGER,
            RoleChoices.REPORT_MANAGER,
        ]

    @property
    def can_view_management_dashboard(self):
        return self.is_executive_manager

    @property
    def can_view_monitoring(self):
        return self.is_executive_manager or self.role == RoleChoices.WEIGHBRIDGE_MANAGER

    @property
    def can_approve_discrepancy(self):
        return self.is_admin_or_manager

    @property
    def can_manage_settings(self):
        return self.user.is_superuser or self.role in [RoleChoices.SUPER_ADMIN, RoleChoices.SYSTEM_ADMIN]

    @property
    def can_edit_completed_ticket(self):
        return self.user.is_superuser or self.role in [
            RoleChoices.SUPER_ADMIN,
            RoleChoices.SYSTEM_ADMIN,
            RoleChoices.WEIGHBRIDGE_MANAGER,
        ]

    @property
    def can_cancel_ticket(self):
        return self.user.is_superuser or self.role in [
            RoleChoices.SUPER_ADMIN,
            RoleChoices.SYSTEM_ADMIN,
            RoleChoices.WEIGHBRIDGE_MANAGER,
        ]

    @property
    def can_access_reports(self):
        return self.user.is_superuser or self.role in [
            RoleChoices.SUPER_ADMIN,
            RoleChoices.SYSTEM_ADMIN,
            RoleChoices.CEO,
            RoleChoices.FACTORY_MANAGER,
            RoleChoices.COMMERCIAL_MANAGER,
            RoleChoices.FINANCIAL_MANAGER,
            RoleChoices.WEIGHBRIDGE_MANAGER,
            RoleChoices.REPORT_MANAGER,
            RoleChoices.VIEWER,
            RoleChoices.WEIGHBRIDGE_OPERATOR,
            RoleChoices.WAREHOUSE,
        ]

    @property
    def can_access_audit(self):
        return self.user.is_superuser or self.role in [
            RoleChoices.SUPER_ADMIN,
            RoleChoices.SYSTEM_ADMIN,
            RoleChoices.CEO,
        ]

    @property
    def can_access_masterdata(self):
        """
        Permission to access masterdata app.
        Revoked for CEO, Viewer, Financial Manager, Warehouse, and Report Manager.
        """
        if self.user.is_superuser:
            return True
        revoked = [
            RoleChoices.CEO,
            RoleChoices.VIEWER,
            RoleChoices.FINANCIAL_MANAGER,
            RoleChoices.WAREHOUSE,
            RoleChoices.REPORT_MANAGER,
        ]
        return self.role not in revoked

    @property
    def can_access_weighbridge(self):
        """
        Permission to access weighbridge operations (weighbridge app).
        Revoked for CEO, Viewer, Financial Manager, Warehouse, and Report Manager.
        """
        if self.user.is_superuser:
            return True
        revoked = [
            RoleChoices.CEO,
            RoleChoices.VIEWER,
            RoleChoices.FINANCIAL_MANAGER,
            RoleChoices.WAREHOUSE,
            RoleChoices.REPORT_MANAGER,
        ]
        return self.role not in revoked

@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created:
        role = RoleChoices.SUPER_ADMIN if instance.is_superuser else RoleChoices.WEIGHBRIDGE_OPERATOR
        UserProfile.objects.create(user=instance, role=role)
    else:
        if hasattr(instance, 'profile'):
            instance.profile.save()
        else:
            role = RoleChoices.SUPER_ADMIN if instance.is_superuser else RoleChoices.WEIGHBRIDGE_OPERATOR
            UserProfile.objects.create(user=instance, role=role)
