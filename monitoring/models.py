from decimal import Decimal
from django.db import models
from django.contrib.auth.models import User
from core.jalali import format_jalali_datetime


class AlertType(models.TextChoices):
    VEHICLE_TARE_ANOMALY = "VEHICLE_TARE_ANOMALY", "وزن خالی غیرعادی خودرو"
    WEIGHT_DISCREPANCY = "WEIGHT_DISCREPANCY", "مغایرت وزن ارسالی و باسکول"
    LOSS_ANOMALY = "LOSS_ANOMALY", "افت غیرعادی محموله"
    NET_WEIGHT_ANOMALY = "NET_WEIGHT_ANOMALY", "وزن خالص غیرعادی"
    LONG_WAITING_TIME = "LONG_WAITING_TIME", "زمان توقف غیرعادی"
    WEIGHT_EDIT_ANOMALY = "WEIGHT_EDIT_ANOMALY", "اصلاح غیرعادی وزن"


class AlertSeverity(models.TextChoices):
    INFO = "INFO", "اطلاعات (Info)"
    LOW = "LOW", "کم (Low)"
    MEDIUM = "MEDIUM", "متوسط (Medium)"
    HIGH = "HIGH", "بالا (High)"
    CRITICAL = "CRITICAL", "بحرانی (Critical)"


class AlertStatus(models.TextChoices):
    OPEN = "OPEN", "باز (Open)"
    REVIEWED = "REVIEWED", "بررسی‌شده (Reviewed)"
    RESOLVED = "RESOLVED", "حل‌شده (Resolved)"
    IGNORED = "IGNORED", "نادیده‌گرفته‌شده (Ignored)"


class AlertConfidence(models.TextChoices):
    INSUFFICIENT = "insufficient", "داده ناکافی"
    LOW = "low", "پایین (۱۰-۱۹ نمونه)"
    MEDIUM = "medium", "متوسط (۲۰-۴۹ نمونه)"
    HIGH = "high", "بالا (۵۰+ نمونه)"


class MonitoringRuleConfig(models.Model):
    """Configuration for monitoring anomaly detection rules."""
    rule_type = models.CharField(
        max_length=50,
        unique=True,
        choices=AlertType.choices,
        verbose_name="نوع قانون"
    )
    name_fa = models.CharField(max_length=150, verbose_name="نام فارسی قانون")
    description = models.TextField(blank=True, verbose_name="شرح عملکرد قانون")
    enabled = models.BooleanField(default=True, verbose_name="فعال بودن قانون")
    
    warning_threshold = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="آستانه هشدار عددی (Warning)"
    )
    high_threshold = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="آستانه بالای عددی (High)"
    )
    critical_threshold = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="آستانه بحرانی عددی (Critical)"
    )
    
    percentage_warning = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="درصد انحراف هشدار (%)"
    )
    percentage_high = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="درصد انحراف بالا (%)"
    )
    percentage_critical = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="درصد انحراف بحرانی (%)"
    )
    
    minimum_history = models.PositiveIntegerField(
        default=10,
        verbose_name="حداقل تعداد سابقه برای تحلیل"
    )
    extra_params = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="تنظیمات اختصاصی (JSON)"
    )
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ایجاد")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخرین بروزرسانی")
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="ویرایش‌کننده"
    )

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.warning_threshold < Decimal("0") or self.high_threshold < Decimal("0") or self.critical_threshold < Decimal("0"):
            raise ValidationError("آستانه‌های عددی نمی‌توانند منفی باشند.")
        if self.warning_threshold > self.high_threshold or self.high_threshold > self.critical_threshold:
            raise ValidationError("ترتیب آستانه‌ها باید رعایت شود: هشدار <= بالا <= بحرانی.")
        if self.percentage_warning < Decimal("0") or self.percentage_high < Decimal("0") or self.percentage_critical < Decimal("0"):
            raise ValidationError("درصدهای انحراف نمی‌توانند منفی باشند.")
        if self.percentage_warning > self.percentage_high or self.percentage_high > self.percentage_critical:
            raise ValidationError("ترتیب درصدهای انحراف باید رعایت شود: هشدار <= بالا <= بحرانی.")

    class Meta:
        verbose_name = "تنظیم قانون پایش"
        verbose_name_plural = "تنظیمات قوانین پایش هوشمند"
        ordering = ["rule_type"]

    def __str__(self):
        return f"{self.name_fa} ({'فعال' if self.enabled else 'غیرفعال'})"

    @classmethod
    def get_rule_config(cls, rule_type: str):
        """Retrieve config for rule or create sensible default if missing."""
        config = cls.objects.filter(rule_type=rule_type).first()
        if config:
            return config
        
        defaults = {
            AlertType.VEHICLE_TARE_ANOMALY: {
                "name_fa": "تحلیل وزن خالی غیرعادی خودرو",
                "description": "پایش انحراف وزن خالی (Tare) ثبت‌شده نسبت به میانگین تاریخی و انحراف معیار خودرو",
                "warning_threshold": Decimal("300.00"),
                "high_threshold": Decimal("500.00"),
                "critical_threshold": Decimal("800.00"),
                "percentage_warning": Decimal("3.00"),
                "percentage_high": Decimal("5.00"),
                "percentage_critical": Decimal("8.00"),
                "minimum_history": 10,
            },
            AlertType.WEIGHT_DISCREPANCY: {
                "name_fa": "مغایرت وزن ارسالی و باسکول",
                "description": "بررسی اختلاف وزن خالص با وزن بارنامه و تحلیل سابقه رفتار طرف حساب",
                "warning_threshold": Decimal("50.00"),
                "high_threshold": Decimal("100.00"),
                "critical_threshold": Decimal("200.00"),
                "percentage_warning": Decimal("1.00"),
                "percentage_high": Decimal("2.00"),
                "percentage_critical": Decimal("3.00"),
                "minimum_history": 5,
            },
            AlertType.LOSS_ANOMALY: {
                "name_fa": "افت غیرعادی محموله",
                "description": "تشخیص درصد افت غیرعادی نسبت به میانگین کالا و تامین‌کننده",
                "warning_threshold": Decimal("0.50"),
                "high_threshold": Decimal("1.00"),
                "critical_threshold": Decimal("2.00"),
                "percentage_warning": Decimal("15.00"),
                "percentage_high": Decimal("30.00"),
                "percentage_critical": Decimal("50.00"),
                "minimum_history": 10,
            },
            AlertType.NET_WEIGHT_ANOMALY: {
                "name_fa": "وزن خالص غیرعادی",
                "description": "بررسی وزن خالص بر اساس سابقه سلسله‌مراتبی خودرو، محصول و ناوگان",
                "warning_threshold": Decimal("1000.00"),
                "high_threshold": Decimal("2500.00"),
                "critical_threshold": Decimal("5000.00"),
                "percentage_warning": Decimal("15.00"),
                "percentage_high": Decimal("25.00"),
                "percentage_critical": Decimal("40.00"),
                "minimum_history": 10,
            },
            AlertType.LONG_WAITING_TIME: {
                "name_fa": "زمان توقف غیرعادی",
                "description": "پایش زمان معطلی خودرو بین توزین اول و دوم نسبت به میانگین محصول و جایگاه",
                "warning_threshold": Decimal("60.00"),  # minutes
                "high_threshold": Decimal("120.00"),
                "critical_threshold": Decimal("180.00"),
                "percentage_warning": Decimal("50.00"),
                "percentage_high": Decimal("100.00"),
                "percentage_critical": Decimal("200.00"),
                "minimum_history": 5,
            },
            AlertType.WEIGHT_EDIT_ANOMALY: {
                "name_fa": "اصلاح غیرعادی اوزان",
                "description": "هشدار در خصوص تغییرات دستی اوزان پس از ثبت یا تکمیل با ریسک بالا",
                "warning_threshold": Decimal("100.00"),
                "high_threshold": Decimal("300.00"),
                "critical_threshold": Decimal("500.00"),
                "percentage_warning": Decimal("2.00"),
                "percentage_high": Decimal("5.00"),
                "percentage_critical": Decimal("10.00"),
                "minimum_history": 1,
            },
        }

        rule_data = defaults.get(rule_type, {
            "name_fa": rule_type,
            "description": "",
            "warning_threshold": Decimal("100.00"),
            "high_threshold": Decimal("200.00"),
            "critical_threshold": Decimal("500.00"),
            "percentage_warning": Decimal("5.00"),
            "percentage_high": Decimal("10.00"),
            "percentage_critical": Decimal("20.00"),
            "minimum_history": 10,
        })

        obj, _ = cls.objects.get_or_create(rule_type=rule_type, defaults=rule_data)
        return obj


class MonitoringAlert(models.Model):
    """Smart monitoring anomaly alerts associated with weighbridge tickets."""
    ticket = models.ForeignKey(
        "weighbridge.WeighTicket",
        on_delete=models.CASCADE,
        related_name="monitoring_alerts",
        verbose_name="قبض باسکول"
    )
    alert_type = models.CharField(
        max_length=50,
        choices=AlertType.choices,
        db_index=True,
        verbose_name="نوع هشدار"
    )
    severity = models.CharField(
        max_length=20,
        choices=AlertSeverity.choices,
        default=AlertSeverity.MEDIUM,
        db_index=True,
        verbose_name="سطح اهمیت"
    )
    title = models.CharField(max_length=255, verbose_name="عنوان هشدار")
    description = models.TextField(blank=True, verbose_name="شرح مختصر")
    reason = models.TextField(verbose_name="دلیل تحلیلی و شفاف هشدار")
    
    current_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="مقدار فعلی"
    )
    baseline_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="مقدار مبنا / میانگین تاریخی"
    )
    deviation_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="میزان انحراف عددی"
    )
    deviation_percent = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="درصد انحراف (%)"
    )
    
    sample_size = models.PositiveIntegerField(
        default=0,
        verbose_name="تعداد سوابق بررسی‌شده"
    )
    confidence = models.CharField(
        max_length=20,
        choices=AlertConfidence.choices,
        default=AlertConfidence.INSUFFICIENT,
        verbose_name="درجه اطمینان مبنا"
    )
    
    status = models.CharField(
        max_length=20,
        choices=AlertStatus.choices,
        default=AlertStatus.OPEN,
        db_index=True,
        verbose_name="وضعیت هشدار"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name="زمان ایجاد هشدار"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="زمان آخرین تغییر"
    )
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="زمان بازبینی"
    )
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_monitoring_alerts",
        verbose_name="بازبینی‌کننده"
    )
    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="زمان بررسی / حل"
    )
    resolved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_monitoring_alerts",
        verbose_name="اقدام‌کننده"
    )
    resolution_note = models.TextField(
        blank=True,
        verbose_name="یادداشت و دلیل اقدام"
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="متادیتا و جزییات محاسبات"
    )

    class Meta:
        verbose_name = "هشدار پایش هوشمند"
        verbose_name_plural = "هشدارهای پایش هوشمند"
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["ticket", "alert_type"],
                name="unique_ticket_alert_type"
            )
        ]
        indexes = [
            models.Index(fields=["ticket", "alert_type"]),
            models.Index(fields=["status"]),
            models.Index(fields=["severity"]),
            models.Index(fields=["alert_type"]),
            models.Index(fields=["created_at"]),
        ]
        permissions = [
            ("view_monitoring_dashboard", "امکان مشاهده داشبورد پایش هوشمند"),
            ("view_monitoring_alert", "امکان مشاهده هشدارهای پایش هوشمند"),
            ("review_monitoring_alert", "امکان بازبینی هشدارهای پایش"),
            ("resolve_monitoring_alert", "امکان حل / ثبت اقدام هشدارهای پایش"),
            ("ignore_monitoring_alert", "امکان نادیده گرفتن هشدارهای پایش"),
            ("manage_monitoring_settings", "امکان مدیریت تنظیمات و قوانین پایش"),
            ("export_monitoring_report", "امکان خروجی گزارشات پایش هوشمند"),
        ]

    def __str__(self):
        return f"{self.get_severity_display()} - {self.get_alert_type_display()} (قبض {self.ticket.serial_number})"

    @property
    def jalali_created_at(self):
        return format_jalali_datetime(self.created_at)

    @property
    def jalali_resolved_at(self):
        return format_jalali_datetime(self.resolved_at) if self.resolved_at else "-"

    @property
    def jalali_reviewed_at(self):
        return format_jalali_datetime(self.reviewed_at) if self.reviewed_at else "-"

    @property
    def jalali_updated_at(self):
        return format_jalali_datetime(self.updated_at) if self.updated_at else "-"

    @property
    def severity_weight(self) -> int:
        """Numerical weight for Risk Score calculation."""
        weights = {
            AlertSeverity.INFO: 2,
            AlertSeverity.LOW: 5,
            AlertSeverity.MEDIUM: 15,
            AlertSeverity.HIGH: 30,
            AlertSeverity.CRITICAL: 50,
        }
        return weights.get(self.severity, 10)
