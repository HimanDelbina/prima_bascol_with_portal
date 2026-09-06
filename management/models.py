from decimal import Decimal
from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

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


def default_dimension_weights():
    return {
        'weight_accuracy': 30,
        'loss_performance': 20,
        'consistency': 15,
        'monitoring_quality': 20,
        'operational_efficiency': 10,
        'data_reliability': 5,
    }


def default_score_thresholds():
    return {
        'excellent': 90,
        'good': 75,
        'acceptable': 60,
        'needs_attention': 40,
        'high_risk': 0,
    }


def default_confidence_thresholds():
    return {
        'insufficient': 10,
        'low': 30,
        'medium': 100,
        'high': 300,
    }


class PartyScoringConfig(models.Model):
    """
    تنظیمات و وزن‌های فرمول امتیازدهی طرف‌حساب‌ها (قاعده‌محور و قابل تغییر توسط مدیر ارشد).
    """
    enabled = models.BooleanField(default=True, verbose_name='فعال بودن سیستم امتیازدهی')
    minimum_history_days = models.PositiveIntegerField(default=30, verbose_name='حداقل دوره تاریخی (روز)')
    minimum_tickets_for_ranking = models.PositiveIntegerField(default=20, verbose_name='حداقل قبوض برای ورود به رتبه‌بندی')
    
    dimension_weights = models.JSONField(
        default=default_dimension_weights,
        verbose_name='وزن ابعاد ۶ گانه امتیازدهی (درصد)'
    )
    score_thresholds = models.JSONField(
        default=default_score_thresholds,
        verbose_name='آستانه سطوح کیفی امتیاز'
    )
    confidence_thresholds = models.JSONField(
        default=default_confidence_thresholds,
        verbose_name='آستانه سطوح اطمینان نمونه'
    )
    trend_threshold = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('5.00'),
        verbose_name='آستانه تغییر روند (%)'
    )
    calculation_version = models.CharField(
        max_length=50,
        default='party_score_v1',
        verbose_name='نسخه فرمول امتیازدهی'
    )
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='آخرین ویرایش‌کننده'
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name='زمان آخرین ویرایش')

    class Meta:
        verbose_name = 'تنظیمات فرمول امتیازدهی طرف‌حساب'
        verbose_name_plural = 'تنظیمات فرمول امتیازدهی طرف‌حساب‌ها'

    def clean(self):
        super().clean()
        weights = self.dimension_weights or {}
        required_keys = [
            'weight_accuracy', 'loss_performance', 'consistency',
            'monitoring_quality', 'operational_efficiency', 'data_reliability'
        ]
        for key in required_keys:
            val = weights.get(key, None)
            if val is None or float(val) < 0:
                raise ValidationError(f'وزن بُعد {key} باید مقداری مثبت باشد.')
        
        total = sum(float(weights.get(k, 0)) for k in required_keys)
        if abs(total - 100.0) > 0.01:
            raise ValidationError(f'مجموع اوزان ابعاد امتیازدهی باید دقیقاً ۱۰۰ باشد (مقدار فعلی: {total}).')

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @classmethod
    def get_config(cls):
        cfg = cls.objects.first()
        if not cfg:
            cfg = cls.objects.create()
        return cfg

    def __str__(self):
        return f'تنظیمات امتیازدهی ({self.calculation_version})'


class ScoreLevel(models.TextChoices):
    EXCELLENT = 'EXCELLENT', 'عالی'
    GOOD = 'GOOD', 'خوب'
    ACCEPTABLE = 'ACCEPTABLE', 'قابل قبول'
    NEEDS_ATTENTION = 'NEEDS_ATTENTION', 'نیازمند بررسی'
    HIGH_RISK = 'HIGH_RISK', 'پرریسک'


class ScoreConfidence(models.TextChoices):
    INSUFFICIENT = 'INSUFFICIENT', 'داده ناکافی'
    LOW = 'LOW', 'پایین'
    MEDIUM = 'MEDIUM', 'متوسط'
    HIGH = 'HIGH', 'بالا'
    VERY_HIGH = 'VERY_HIGH', 'بسیار بالا'


class TrendDirection(models.TextChoices):
    IMPROVING = 'IMPROVING', 'بهبود'
    STABLE = 'STABLE', 'باثبات'
    WORSENING = 'WORSENING', 'نزولی'
    INSUFFICIENT_DATA = 'INSUFFICIENT_DATA', 'داده ناکافی'


class PartyScoreSnapshot(models.Model):
    """
    اسنپ‌شات دوره‌ای امتیاز، ابعاد، شاخص‌ها و دلایل برای هر طرف‌حساب.
    جهت حفظ تاریخچه بدون ابهام در صورت تغییرات الگوریتم.
    """
    party = models.ForeignKey(
        'masterdata.Party',
        on_delete=models.CASCADE,
        related_name='score_snapshots',
        verbose_name='طرف حساب'
    )
    period_start = models.DateField(db_index=True, verbose_name='از تاریخ')
    period_end = models.DateField(db_index=True, verbose_name='تا تاریخ')
    period_type = models.CharField(max_length=30, default='month', verbose_name='نوع دوره')
    
    overall_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='امتیاز کلی (۰ تا ۱۰۰)'
    )
    score_level = models.CharField(
        max_length=30,
        choices=ScoreLevel.choices,
        default=ScoreLevel.NEEDS_ATTENTION,
        verbose_name='سطح کیفی'
    )
    score_level_fa = models.CharField(max_length=50, default='نیازمند بررسی', verbose_name='سطح کیفی (فارسی)')
    
    confidence = models.CharField(
        max_length=30,
        choices=ScoreConfidence.choices,
        default=ScoreConfidence.INSUFFICIENT,
        verbose_name='سطح اطمینان'
    )
    confidence_fa = models.CharField(max_length=50, default='داده ناکافی', verbose_name='سطح اطمینان (فارسی)')
    
    ticket_count = models.PositiveIntegerField(default=0, verbose_name='تعداد قبوض در دوره')
    dimension_scores = models.JSONField(default=dict, verbose_name='امتیازات به تفکیک ابعاد')
    metrics_snapshot = models.JSONField(default=dict, verbose_name='ماتریس شاخص‌های خام')
    explanation = models.JSONField(default=dict, verbose_name='توضیحات تحلیلی امتیاز (نقاط مثبت و منفی)')
    
    calculation_version = models.CharField(
        max_length=50,
        default='party_score_v1',
        db_index=True,
        verbose_name='نسخه الگوریتم'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='زمان ثبت اسنپ‌شات')

    class Meta:
        verbose_name = 'اسنپ‌شات امتیاز طرف‌حساب'
        verbose_name_plural = 'اسنپ‌شات‌های امتیاز طرف‌حساب‌ها'
        ordering = ['-period_end', '-created_at']
        indexes = [
            models.Index(fields=['party', 'period_start', 'period_end']),
            models.Index(fields=['calculation_version']),
            models.Index(fields=['overall_score']),
        ]

    def __str__(self):
        return f'{self.party.name} | {self.period_start} تا {self.period_end} | {self.overall_score}'
