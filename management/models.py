from django.db import models
from django.contrib.auth.models import User

class SavedReport(models.Model):
    title = models.CharField(max_length=150, verbose_name='عنوان گزارش ذخیره‌شده')
    report_type = models.CharField(max_length=50, default='dashboard', verbose_name='نوع گزارش')
    filters_json = models.JSONField(default=dict, verbose_name='تنظیمات و فیلترها (JSON)')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='saved_management_reports', verbose_name='ایجادکننده')
    is_public = models.BooleanField(default=False, verbose_name='اشتراک‌گذاری برای همه مدیران')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاریخ ذخیره')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='تاریخ ویرایش')

    class Meta:
        verbose_name = 'گزارش ذخیره‌شده مدیریتی'
        verbose_name_plural = 'گزارش‌های ذخیره‌شده مدیریتی'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} ({self.report_type})'

class ReportSnapshot(models.Model):
    title = models.CharField(max_length=200, verbose_name='عنوان اسنپ‌شات')
    period_title = models.CharField(max_length=100, verbose_name='دوره گزارش')
    start_date = models.DateField(verbose_name='از تاریخ')
    end_date = models.DateField(verbose_name='تا تاریخ')
    metrics_data = models.JSONField(default=dict, verbose_name='داده‌های تجمیعی (JSON)')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='ثبت‌کننده')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='زمان ایجاد')

    class Meta:
        verbose_name = 'اسنپ‌شات گزارش مدیریتی'
        verbose_name_plural = 'اسنپ‌شات‌های گزارش مدیریتی'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} - {self.period_title}'
