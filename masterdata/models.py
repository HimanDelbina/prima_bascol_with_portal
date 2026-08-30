from django.db import models
from decimal import Decimal
from core.models import BaseModel

class Product(BaseModel):
    name = models.CharField(max_length=150, verbose_name="نام محصول")
    code = models.CharField(max_length=50, blank=True, null=True, verbose_name="کد محصول")
    standard_tolerance_kg = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=Decimal("50.00"), 
        verbose_name="حد مجاز انحراف استاندارد (کیلوگرم)"
    )
    default_loss_percent = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=Decimal("0.00"), 
        verbose_name="درصد افت پیش‌فرض (%)"
    )
    description = models.TextField(blank=True, verbose_name="توضیحات")

    class Meta:
        verbose_name = "محصول"
        verbose_name_plural = "محصولات"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})" if self.code else self.name


class PartyType(models.TextChoices):
    CUSTOMER = "customer", "خریدار / مشتری"
    SUPPLIER = "supplier", "فروشنده / تامین‌کننده"
    CONTRACTOR = "contractor", "پیمانکار حمل و نقل"
    INTERNAL = "internal", "واحد داخلی / انبار"
    OTHER = "other", "سایر"

class Party(BaseModel):
    name = models.CharField(max_length=200, verbose_name="نام طرف حساب")
    code = models.CharField(max_length=50, blank=True, null=True, verbose_name="کد حساب")
    party_type = models.CharField(
        max_length=30, 
        choices=PartyType.choices, 
        default=PartyType.CUSTOMER, 
        verbose_name="نوع طرف حساب"
    )
    phone = models.CharField(max_length=30, blank=True, verbose_name="شماره همراه")
    tel = models.CharField(max_length=30, blank=True, verbose_name="تلفن ثابت / فکس")
    email = models.EmailField(blank=True, verbose_name="ایمیل")
    address = models.TextField(blank=True, verbose_name="آدرس")
    national_id = models.CharField(max_length=30, blank=True, verbose_name="شناسه / کد ملی")
    economic_code = models.CharField(max_length=30, blank=True, verbose_name="کد اقتصادی")

    class Meta:
        verbose_name = "طرف حساب"
        verbose_name_plural = "طرف‌های حساب"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_party_type_display()})"


class Driver(BaseModel):
    full_name = models.CharField(max_length=150, verbose_name="نام و نام خانوادگی راننده")
    mobile = models.CharField(max_length=30, blank=True, verbose_name="شماره موبایل")
    national_code = models.CharField(max_length=20, blank=True, verbose_name="کد ملی")
    license_number = models.CharField(max_length=30, blank=True, verbose_name="شماره گواهینامه")
    description = models.TextField(blank=True, verbose_name="توضیحات")

    class Meta:
        verbose_name = "راننده"
        verbose_name_plural = "رانندگان"
        ordering = ["full_name"]

    def __str__(self):
        return f"{self.full_name}" + (f" - {self.mobile}" if self.mobile else "")


class VehicleType(BaseModel):
    name = models.CharField(max_length=100, verbose_name="نوع / شرح خودرو")
    code = models.CharField(max_length=50, blank=True, null=True, verbose_name="کد")
    standard_tare_weight = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=Decimal("0.00"), 
        verbose_name="میانگین وزن خالی استاندارد (Kg)"
    )

    class Meta:
        verbose_name = "نوع خودرو"
        verbose_name_plural = "انواع خودروها"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Vehicle(BaseModel):
    # Iranian Plate structure: e.g. [12] [ع] [345] [ایران 67]
    plate_part1 = models.CharField(max_length=5, blank=True, verbose_name="دو رقم اول پلاک")
    plate_letter = models.CharField(max_length=10, blank=True, verbose_name="حرف پلاک")
    plate_part2 = models.CharField(max_length=5, blank=True, verbose_name="سه رقم بعد پلاک")
    plate_iran = models.CharField(max_length=5, blank=True, verbose_name="کد ایران (دو رقم)")
    plate_display = models.CharField(max_length=50, db_index=True, verbose_name="شماره کامل پلاک")
    
    vehicle_type = models.ForeignKey(
        VehicleType, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="vehicles", 
        verbose_name="نوع خودرو"
    )
    default_driver = models.ForeignKey(
        Driver, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="vehicles", 
        verbose_name="راننده پیش‌فرض"
    )
    empty_weight = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=Decimal("0.00"), 
        verbose_name="وزن خالی ثبت شده (Kg)"
    )
    description = models.TextField(blank=True, verbose_name="توضیحات")

    class Meta:
        verbose_name = "خودرو"
        verbose_name_plural = "خودروها"
        ordering = ["plate_display"]

    def __str__(self):
        v_type = f" ({self.vehicle_type.name})" if self.vehicle_type else ""
        return f"{self.plate_display}{v_type}"

    def save(self, *args, **kwargs):
        # Auto compute plate_display if structured parts are provided
        if self.plate_part1 and self.plate_letter and self.plate_part2 and self.plate_iran:
            self.plate_display = f"{self.plate_part1} {self.plate_letter} {self.plate_part2} - ایران {self.plate_iran}"
        elif not self.plate_display:
            self.plate_display = "بدون پلاک"
        super().save(*args, **kwargs)


class LocationType(models.TextChoices):
    ORIGIN = "origin", "مبدأ"
    DESTINATION = "destination", "مقصد"
    BOTH = "both", "مبدأ و مقصد"

class Location(BaseModel):
    name = models.CharField(max_length=150, verbose_name="نام محل")
    location_type = models.CharField(
        max_length=20, 
        choices=LocationType.choices, 
        default=LocationType.BOTH, 
        verbose_name="نوع محل"
    )
    description = models.TextField(blank=True, verbose_name="توضیحات")

    class Meta:
        verbose_name = "محل (مبدأ / مقصد)"
        verbose_name_plural = "محل‌ها (مبادی و مقاصد)"
        ordering = ["name"]

    def __str__(self):
        return self.name


class UnloadLocation(BaseModel):
    name = models.CharField(max_length=150, verbose_name="نام جایگاه تخلیه / بارگیری")
    code = models.CharField(max_length=50, blank=True, null=True, verbose_name="کد جایگاه")
    description = models.TextField(blank=True, verbose_name="توضیحات")

    class Meta:
        verbose_name = "جایگاه تخلیه"
        verbose_name_plural = "جایگاه‌های تخلیه"
        ordering = ["name"]

    def __str__(self):
        return self.name


class OperationDirection(models.TextChoices):
    INBOUND = "inbound", "وارده (خرید / ورود)"
    OUTBOUND = "outbound", "صادره (فروش / خروج)"
    INTERNAL = "internal", "داخلی"
    TRANSFER = "transfer", "انتقال بین‌واحدی"
    OTHER = "other", "سایر"

class OperationType(BaseModel):
    name = models.CharField(max_length=100, verbose_name="نوع عملیات / وضعیت محموله")
    code = models.CharField(max_length=50, blank=True, null=True, verbose_name="کد")
    direction = models.CharField(
        max_length=20, 
        choices=OperationDirection.choices, 
        default=OperationDirection.INBOUND, 
        verbose_name="جهت عملیات"
    )

    class Meta:
        verbose_name = "نوع عملیات"
        verbose_name_plural = "انواع عملیات"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_direction_display()})"


class LossType(BaseModel):
    name = models.CharField(max_length=100, verbose_name="نوع افت")
    code = models.CharField(max_length=50, blank=True, null=True, verbose_name="کد")
    default_percent = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=Decimal("0.00"), 
        verbose_name="درصد افت پیش‌فرض (%)"
    )
    description = models.TextField(blank=True, verbose_name="توضیحات")

    class Meta:
        verbose_name = "نوع افت"
        verbose_name_plural = "انواع افت"
        ordering = ["name"]

    def __str__(self):
        return self.name
