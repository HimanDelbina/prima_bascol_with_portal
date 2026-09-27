from django.db import models
from django.core.validators import MinValueValidator
from django.contrib.auth.models import User
from decimal import Decimal
from core.models import BaseModel
from core.jalali import format_jalali_date, format_jalali_datetime, format_time_hhmm, to_persian_digits
from masterdata.models import (
    Product, Party, Driver, Vehicle, VehicleType, 
    Location, UnloadLocation, OperationType, LossType
)

class TicketStatus(models.TextChoices):
    DRAFT = "draft", "پیش‌نویس"
    WAITING_FIRST = "waiting_first", "در انتظار وزن اول"
    FIRST_REGISTERED = "first_registered", "ثبت وزن اول"
    WAITING_SECOND = "waiting_second", "در انتظار وزن دوم (داخل محوطه)"
    COMPLETED = "completed", "تکمیل شده"
    CANCELLED = "cancelled", "ابطال / لغو شده"

class WeightMode(models.TextChoices):
    EMPTY_FIRST = "empty_first", "ابتدا خالی (توزین اول) سپس پر (توزین دوم)"
    FULL_FIRST = "full_first", "ابتدا پر (توزین اول) سپس خالی (توزین دوم)"
    DIRECT = "direct", "ثبت مستقیم هر دو وزن همزمان"

class WeighTicket(BaseModel):
    normalized_plate = models.CharField(max_length=60, db_index=True, editable=False, default="")
    duplicate_exception = models.ForeignKey(
        "PlateRegistrationException", null=True, blank=True, editable=False,
        on_delete=models.PROTECT, related_name="tickets", verbose_name="مجوز ثبت تکراری روزانه",
    )
    # Serial & Status
    serial_number = models.CharField(max_length=50, unique=True, db_index=True, verbose_name="شماره قبض / سریال")
    status = models.CharField(
        max_length=30, 
        choices=TicketStatus.choices, 
        default=TicketStatus.WAITING_SECOND, 
        db_index=True, 
        verbose_name="وضعیت سند"
    )
    weight_mode = models.CharField(
        max_length=30, 
        choices=WeightMode.choices, 
        default=WeightMode.EMPTY_FIRST, 
        verbose_name="سناریوی توزین"
    )
    
    # Operation & Masterdata FKs
    operation_type = models.ForeignKey(
        OperationType, 
        on_delete=models.PROTECT, 
        null=True, 
        blank=True, 
        related_name="tickets", 
        verbose_name="نوع عملیات / وضعیت محموله"
    )
    party = models.ForeignKey(
        Party, 
        on_delete=models.PROTECT, 
        null=True, 
        blank=True, 
        related_name="tickets", 
        verbose_name="طرف حساب"
    )
    product = models.ForeignKey(
        Product, 
        on_delete=models.PROTECT, 
        null=True, 
        blank=True, 
        related_name="tickets", 
        verbose_name="نام محصول"
    )
    
    # Vehicle & Driver
    vehicle = models.ForeignKey(
        Vehicle, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="tickets", 
        verbose_name="خودرو"
    )
    vehicle_type = models.ForeignKey(
        VehicleType, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        verbose_name="نوع خودرو"
    )
    vehicle_type_custom = models.CharField(max_length=100, blank=True, verbose_name="شرح دستی نوع ماشین")
    
    driver = models.ForeignKey(
        Driver, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="tickets", 
        verbose_name="راننده"
    )
    driver_name_custom = models.CharField(max_length=150, blank=True, verbose_name="نام راننده (دستی)")
    driver_mobile_custom = models.CharField(max_length=30, blank=True, verbose_name="شماره موبایل راننده")
    license_plate_display = models.CharField(max_length=60, db_index=True, verbose_name="شماره پلاک")
    
    # Logistics
    freight_amount = models.DecimalField(
        max_digits=15, decimal_places=0, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name="مبلغ کرایه (تومان)",
    )
    waybill_number = models.CharField(max_length=60, blank=True, db_index=True, verbose_name="شماره بارنامه")
    origin = models.ForeignKey(
        Location, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="origin_tickets", 
        verbose_name="مبدأ بار"
    )
    destination = models.ForeignKey(
        Location, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="destination_tickets", 
        verbose_name="مقصد بار"
    )
    unload_location = models.ForeignKey(
        UnloadLocation, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="tickets", 
        verbose_name="جایگاه تخلیه / بارگیری"
    )
    load_count = models.PositiveIntegerField(default=1, verbose_name="تعداد بار / سرویس")
    
    # First Weight
    first_weight = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), verbose_name="وزن اول (Kg)")
    first_weight_date = models.DateField(null=True, blank=True, db_index=True, verbose_name="تاریخ وزن اول")
    first_weight_time = models.TimeField(null=True, blank=True, verbose_name="ساعت وزن اول")
    first_weight_operator = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="first_weight_tickets", 
        verbose_name="مسئول وزن اول"
    )
    
    # Second Weight
    second_weight = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="وزن دوم (Kg)")
    second_weight_date = models.DateField(null=True, blank=True, db_index=True, verbose_name="تاریخ وزن دوم")
    second_weight_time = models.TimeField(null=True, blank=True, verbose_name="ساعت وزن دوم")
    second_weight_operator = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="second_weight_tickets", 
        verbose_name="مسئول وزن دوم"
    )
    
    # Official Computed Weights (Gross / Tare / Net)
    gross_weight = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), db_index=True, verbose_name="وزن پر (Kg)")
    tare_weight = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), db_index=True, verbose_name="وزن خالی (Kg)")
    net_weight = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), db_index=True, verbose_name="وزن خالص (Kg)")
    sent_weight = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), verbose_name="وزن ارسالی / مبدا (Kg)")
    
    # Discrepancy / Variance
    weight_difference = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), verbose_name="اختلاف با وزن ارسالی (Kg)")
    weight_difference_percent = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0.00"), verbose_name="درصد اختلاف وزن (%)")
    is_tolerance_exceeded = models.BooleanField(default=False, db_index=True, verbose_name="مغایرت بیش از حد مجاز")
    
    # Loss / Waste
    loss_type = models.ForeignKey(
        LossType, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="tickets", 
        verbose_name="نوع افت"
    )
    loss_percent = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0.00"), verbose_name="درصد افت (%)")
    loss_weight = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), verbose_name="وزن افت (Kg)")
    is_loss_overridden = models.BooleanField(default=False, verbose_name="افت دستی تنظیم شده")
    loss_override_reason = models.TextField(blank=True, verbose_name="دلیل تنظیم دستی افت")
    
    # Final Result
    final_weight = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), db_index=True, verbose_name="وزن نهایی پس از کسر افت (Kg)")
    
    # Additional info, Cancellation & Auditing
    notes = models.TextField(blank=True, verbose_name="توضیحات قبض")
    cancellation_reason = models.TextField(blank=True, verbose_name="دلیل ابطال")
    cancelled_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="cancelled_tickets", 
        verbose_name="کاربر ابطال‌کننده"
    )
    cancelled_at = models.DateTimeField(null=True, blank=True, verbose_name="زمان ابطال")
    
    last_edited_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="edited_tickets", 
        verbose_name="آخرین ویرایش‌کننده"
    )
    last_edit_reason = models.TextField(blank=True, verbose_name="دلیل آخرین ویرایش")

    class Meta:
        verbose_name = "قبض باسکول"
        verbose_name_plural = "قبوض باسکول"
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["serial_number"]),
            models.Index(fields=["status"]),
            models.Index(fields=["first_weight_date"]),
            models.Index(fields=["second_weight_date"]),
            models.Index(fields=["license_plate_display"]),
            models.Index(fields=["party"]),
            models.Index(fields=["product"]),
            models.Index(fields=["waybill_number"]),
        ]

    def __str__(self):
        return f"قبض {self.serial_number} - {self.license_plate_display} ({self.get_status_display()})"

    def clean(self):
        super().clean()
        from weighbridge.plate_policy import DailyPlatePolicy
        with DailyPlatePolicy.locked(self):
            DailyPlatePolicy.check(self)

    def save(self, *args, **kwargs):
        from weighbridge.plate_policy import normalize_plate
        self.normalized_plate = normalize_plate(self.license_plate_display)
        if kwargs.get("update_fields") is not None and "license_plate_display" in kwargs["update_fields"]:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"normalized_plate"}
        return super().save(*args, **kwargs)

    @property
    def jalali_first_date(self):
        return format_jalali_date(self.first_weight_date)

    @property
    def jalali_second_date(self):
        return format_jalali_date(self.second_weight_date)

    @property
    def jalali_created_at(self):
        return format_jalali_datetime(self.created_at)

    @property
    def first_time_str(self):
        return format_time_hhmm(self.first_weight_time)

    @property
    def second_time_str(self):
        return format_time_hhmm(self.second_weight_time)

    @property
    def driver_display(self):
        if self.driver:
            return self.driver.full_name
        return self.driver_name_custom or "نامشخص"

    @property
    def driver_mobile_display(self):
        if self.driver and self.driver.mobile:
            return self.driver.mobile
        return self.driver_mobile_custom or "-"

    @property
    def vehicle_type_display(self):
        if self.vehicle and self.vehicle.vehicle_type:
            return self.vehicle.vehicle_type.name
        if self.vehicle_type:
            return self.vehicle_type.name
        return self.vehicle_type_custom or "-"

    @property
    def gross_weight_operator(self):
        """Return the user who recorded the Gross weight."""
        if self.second_weight is not None:
            if self.first_weight >= self.second_weight:
                return self.first_weight_operator
            return self.second_weight_operator
        # If only first weight exists
        return self.first_weight_operator

    @property
    def tare_weight_operator(self):
        """Return the user who recorded the Tare weight."""
        if self.second_weight is not None:
            if self.first_weight < self.second_weight:
                return self.first_weight_operator
            return self.second_weight_operator
        return None

    @property
    def gross_date(self):
        if self.second_weight is not None and self.second_weight > self.first_weight:
            return self.second_weight_date
        return self.first_weight_date

    @property
    def gross_time(self):
        if self.second_weight is not None and self.second_weight > self.first_weight:
            return self.second_weight_time
        return self.first_weight_time

    @property
    def tare_date(self):
        if self.second_weight is not None and self.second_weight <= self.first_weight:
            return self.second_weight_date
        return self.first_weight_date if self.second_weight is not None else None

    @property
    def tare_time(self):
        if self.second_weight is not None and self.second_weight <= self.first_weight:
            return self.second_weight_time
        return self.first_weight_time if self.second_weight is not None else None

    @property
    def jalali_gross_date(self):
        return format_jalali_date(self.gross_date)

    @property
    def jalali_tare_date(self):
        return format_jalali_date(self.tare_date)


class PlateRegistrationException(BaseModel):
    license_plate_display = models.CharField(max_length=60, verbose_name="پلاک خودرو")
    normalized_plate = models.CharField(max_length=60, unique=True, editable=False)
    reason = models.TextField(verbose_name="دلیل مجوز ثبت چندباره در روز")
    approved_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="plate_registration_exceptions", verbose_name="سرپرست تأییدکننده")

    class Meta:
        verbose_name = "استثنای ثبت روزانه پلاک"
        verbose_name_plural = "استثناهای ثبت روزانه پلاک"
        ordering = ["-updated_at"]

    def __str__(self):
        return self.license_plate_display

    def save(self, *args, **kwargs):
        from weighbridge.plate_policy import normalize_plate
        self.normalized_plate = normalize_plate(self.license_plate_display)
        super().save(*args, **kwargs)


class BlockedPlate(BaseModel):
    license_plate_display = models.CharField(max_length=60, verbose_name="شماره پلاک")
    normalized_plate = models.CharField(max_length=60, unique=True, editable=False)
    reason = models.TextField(verbose_name="دلیل مسدودسازی")
    blocked_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="blocked_plates",
        verbose_name="کاربر مسدودکننده"
    )

    class Meta:
        verbose_name = "پلاک مسدود شده"
        verbose_name_plural = "لیست سیاه پلاک‌ها (مسدودشده)"
        ordering = ["-updated_at"]

    def __str__(self):
        status = "مسدود" if self.is_active else "رفع مسدودی"
        return f"{self.license_plate_display} ({status})"

    def save(self, *args, **kwargs):
        from weighbridge.plate_policy import normalize_plate
        self.normalized_plate = normalize_plate(self.license_plate_display)
        super().save(*args, **kwargs)


class PlateDayLock(models.Model):
    plate = models.CharField(max_length=60)
    date = models.DateField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["plate", "date"], name="unique_plate_day_lock")]

