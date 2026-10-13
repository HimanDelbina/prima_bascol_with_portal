from django.db import models
from decimal import Decimal

class BaseModel(models.Model):
    """Abstract base model with timestamps and soft delete flag."""
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ایجاد")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاریخ ویرایش")
    is_active = models.BooleanField(default=True, verbose_name="فعال / معتبر")

    class Meta:
        abstract = True

class SystemSetting(models.Model):
    """Global system configuration for Prima Bascol Weighbridge."""
    company_name = models.CharField(max_length=200, default="شرکت فولاد پریما", verbose_name="نام شرکت")
    company_logo = models.ImageField(upload_to="settings/", blank=True, null=True, verbose_name="لوگوی شرکت")
    company_address = models.TextField(blank=True, default="تهران، شهرک صنعتی، بلوار صنعت، پلاک ۱", verbose_name="آدرس شرکت")
    company_phone = models.CharField(max_length=50, blank=True, default="۰۲۱-۸۸۸۸۸۸۸۸", verbose_name="تلفن")
    company_email = models.EmailField(blank=True, default="info@primasystem.ir", verbose_name="ایمیل")
    
    receipt_header_title = models.CharField(max_length=200, default="قبض رسمی توزین و باسکول صنعتی", verbose_name="عنوان بالای قبض")
    serial_start_number = models.PositiveIntegerField(default=1001, verbose_name="شماره سریال شروع")
    serial_prefix = models.CharField(max_length=20, blank=True, default="", verbose_name="پیشوند شماره سریال (اختیاری)")
    
    weight_unit = models.CharField(max_length=20, default="کیلوگرم", verbose_name="واحد وزن")
    decimal_places = models.PositiveSmallIntegerField(default=0, verbose_name="تعداد ارقام اعشار وزن")
    
    max_tolerance_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("1.00"), verbose_name="حداکثر درصد مجاز انحراف (%)")
    max_tolerance_kg = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("50.00"), verbose_name="حداکثر کیلوگرم مجاز انحراف (Kg)")
    
    require_waybill = models.BooleanField(default=False, verbose_name="شماره بارنامه اجباری باشد")
    require_driver = models.BooleanField(default=True, verbose_name="اطلاعات راننده اجباری باشد")
    require_origin = models.BooleanField(default=False, verbose_name="مبدأ بار اجباری باشد")
    require_destination = models.BooleanField(default=False, verbose_name="مقصد بار اجباری باشد")
    require_unload_location = models.BooleanField(default=False, verbose_name="جایگاه تخلیه اجباری باشد")
    
    PRINT_CHOICES = [
        ("a4", "برگه A4 استاندارد"),
        ("a5", "برگه A5 نیم صفحه"),
        ("pos", "فیش حرارتی پرینتر کوچک (POS)"),
    ]
    default_print_template = models.CharField(max_length=20, choices=PRINT_CHOICES, default="a4", verbose_name="قالب پیش‌فرض چاپ")
    receipt_footer_note = models.TextField(
        blank=True, 
        default="این برگه به عنوان سند رسمی توزین تلقی گردیده و هرگونه خط خوردگی فاقد اعتبار است.",
        verbose_name="متن پاورقی قبض"
    )
    items_per_page = models.PositiveIntegerField(default=20, verbose_name="تعداد رکورد در هر صفحه")

    class Meta:
        verbose_name = "تنظیمات سامانه"
        verbose_name_plural = "تنظیمات سامانه"

    def __str__(self):
        return f"تنظیمات سامانه - {self.company_name}"

    @classmethod
    def get_settings(cls):
        obj = cls.objects.first()
        if not obj:
            obj = cls.objects.create()
        return obj
