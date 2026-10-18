from django.db import models
from django.contrib.auth.models import User
from core.jalali import format_jalali_datetime

class AuditAction(models.TextChoices):
    CREATE = "create", "ثبت جدید"
    UPDATE = "update", "ویرایش اطلاعات"
    DELETE = "delete", "حذف رکورد"
    OVERRIDE_WEIGHT = "override_weight", "تغییر دستی اوزان"
    OVERRIDE_LOSS = "override_loss", "تغییر دستی افت"
    CANCEL = "cancel", "ابطال سند"
    STATUS_CHANGE = "status_change", "تغییر وضعیت"
    RESTORE = "restore", "بازیابی اطلاعات"
    PRINT = "print", "چاپ قبض"
    DISCREPANCY_APPROVAL = "discrepancy_approval", "تأیید/رد مغایرت سرپرست"
    REVISION_REQUEST = "revision_request", "درخواست بازنگری قبض"
    REVISION_APPLY = "revision_apply", "تأیید و اعمال بازنگری قبض"
    REVISION_REJECT = "revision_reject", "رد درخواست بازنگری"
    REVISION_WITHDRAW = "revision_withdraw", "انصراف از بازنگری"
    LOGIN = "login", "ورود به سامانه"
    LOGOUT = "logout", "خروج از سامانه"
    SHIFT_HANDOVER_SUBMIT = "shift_handover_submit", "ارسال تحویل شیفت"
    SHIFT_HANDOVER_ACCEPT = "shift_handover_accept", "پذیرش تحویل شیفت"
    SHIFT_HANDOVER_DISPUTE = "shift_handover_dispute", "ثبت اختلاف تحویل شیفت"
    SHIFT_HANDOVER_RESOLVE = "shift_handover_resolve", "حل‌وفصل اختلاف تحویل شیفت"

class AuditLog(models.Model):
    user = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="audit_logs", 
        verbose_name="کاربر اقدام‌کننده"
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="آدرس IP")
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="زمان ثبت")
    
    action = models.CharField(
        max_length=30, 
        choices=AuditAction.choices, 
        default=AuditAction.UPDATE, 
        verbose_name="نوع عملیات"
    )
    model_name = models.CharField(max_length=100, db_index=True, verbose_name="نام بخش / مدل")
    record_id = models.CharField(max_length=100, db_index=True, verbose_name="شناسه رکورد")
    record_repr = models.CharField(max_length=255, blank=True, verbose_name="عنوان رکورد")
    
    old_values = models.JSONField(default=dict, blank=True, verbose_name="مقادیر قبلی")
    new_values = models.JSONField(default=dict, blank=True, verbose_name="مقادیر جدید")
    reason = models.TextField(blank=True, verbose_name="دلیل تغییر / ابطال")
    source = models.CharField(max_length=50, default="API", verbose_name="منبع درخواست")

    class Meta:
        verbose_name = "ثبت تغییرات (Audit Log)"
        verbose_name_plural = "گزارش تغییرات و ممیزی (Audit Log)"
        ordering = ["-timestamp"]

    def __str__(self):
        user_name = self.user.get_full_name() or self.user.username if self.user else "سیستم"
        return f"{self.get_action_display()} - {self.record_repr} توسط {user_name}"

    @property
    def jalali_timestamp(self):
        return format_jalali_datetime(self.timestamp)

    @property
    def jalali_date(self):
        from core.jalali import format_jalali_date
        return format_jalali_date(self.timestamp)

    @property
    def time_str(self):
        from core.jalali import format_time_hhmm
        return format_time_hhmm(self.timestamp)
