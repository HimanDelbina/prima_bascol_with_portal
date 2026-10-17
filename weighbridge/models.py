import uuid
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
        verbose_name="مبلغ کرایه (ریال)",
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
    load_count = models.PositiveIntegerField(default=1, verbose_name="تعداد بار و شمش")
    ingot_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="تعداد شمش",
        help_text="مختص عملیات فروش"
    )
    
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
    first_weight_shift_session = models.ForeignKey(
        'shifts.ShiftSession',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="first_weight_tickets",
        verbose_name="جلسه شیفت وزن اول",
    )
    first_weight_out_of_shift = models.BooleanField(
        default=False,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="توزین اول خارج از شیفت / بدون شیفت فعال"
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
    second_weight_shift_session = models.ForeignKey(
        'shifts.ShiftSession',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="second_weight_tickets",
        verbose_name="جلسه شیفت وزن دوم",
    )
    second_weight_out_of_shift = models.BooleanField(
        default=False,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="توزین دوم خارج از شیفت / بدون شیفت فعال"
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
    current_revision_number = models.PositiveIntegerField(
        default=0,
        db_index=True,
        verbose_name="شماره نسخه جاری"
    )
    original_net_weight = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="وزن خالص اولیه ثبت‌شده (Kg)"
    )

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
            models.Index(fields=["current_revision_number"]),
        ]

    def __str__(self):
        return f"قبض {self.serial_number} - {self.license_plate_display} ({self.get_status_display()})"

    @property
    def has_revisions(self) -> bool:
        return self.current_revision_number > 0

    @property
    def revision_display(self) -> str:
        if self.current_revision_number == 0:
            return "نسخه اصلی (Rev. 0)"
        return f"نسخه اصلاح‌شده (Rev. {self.current_revision_number})"

    def clean(self):
        super().clean()
        from weighbridge.plate_policy import DailyPlatePolicy
        with DailyPlatePolicy.locked(self):
            DailyPlatePolicy.check(self)

    def save(self, *args, **kwargs):
        from weighbridge.plate_policy import normalize_plate
        from django.core.exceptions import ValidationError

        self.normalized_plate = normalize_plate(self.license_plate_display)
        if kwargs.get("update_fields") is not None and "license_plate_display" in kwargs["update_fields"]:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"normalized_plate"}

        if self.pk:
            orig_serial = WeighTicket.objects.filter(pk=self.pk).values_list("serial_number", flat=True).first()
            if orig_serial and self.serial_number and orig_serial != self.serial_number:
                raise ValidationError({"serial_number": "شماره سریال قبض پس از صدور قطعی قابل تغییر نیست."})
        elif not self.serial_number:
            from weighbridge.services import SerialNumberService
            self.serial_number = SerialNumberService.allocate_serial_number(SerialNumberService.SCOPE_STANDARD)

        if self.first_weight_out_of_shift is None:
            self.first_weight_out_of_shift = False
        if self.second_weight_out_of_shift is None:
            self.second_weight_out_of_shift = False

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
        return format_time_hhmm(self.first_weight_time or getattr(self, "created_at", None))

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
        if self.vehicle_type:
            return self.vehicle_type.name
        if self.vehicle and self.vehicle.vehicle_type:
            return self.vehicle.vehicle_type.name
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

    @property
    def load_and_ingot_display(self):
        lc = self.load_count or 1
        if self.ingot_count:
            return f"{lc} (بار) - {self.ingot_count} (شمش)"
        return f"{lc} (بار)"

    @property
    def load_count_display(self):
        return self.load_and_ingot_display


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


class PlateAutoFill(BaseModel):
    license_plate_display = models.CharField(max_length=60, verbose_name="شماره پلاک")
    normalized_plate = models.CharField(max_length=60, unique=True, editable=False)
    notes = models.TextField(blank=True, verbose_name="یادداشت / توضیحات")
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="plate_autofills",
        verbose_name="کاربر ثبت‌کننده"
    )

    class Meta:
        verbose_name = "پلاک تکمیل خودکار"
        verbose_name_plural = "پلاک‌های تکمیل خودکار (بارگذاری از آخرین ورود)"
        ordering = ["-updated_at"]

    def __str__(self):
        status = "فعال" if self.is_active else "غیرفعال"
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


class EmergencyTicketStatus(models.TextChoices):
    WAITING_SECOND = "waiting_second", "در انتظار وزن دوم"
    COMPLETED = "completed", "تکمیل شده"
    CANCELLED = "cancelled", "ابطال شده"


class EmergencyWeighTicket(BaseModel):
    """
    قبض توزین اضطراری / متفرقه برای شرکت‌های خارج از مجموعه.
    این رکوردها کاملاً ایزوله بوده و در آمارها و داده‌های انبار، کالا و طرف‌حساب‌های کارخانه تأثیری ندارند.
    """
    serial_number = models.CharField(max_length=50, unique=True, db_index=True, verbose_name="شماره قبض")
    status = models.CharField(
        max_length=30,
        choices=EmergencyTicketStatus.choices,
        default=EmergencyTicketStatus.COMPLETED,
        db_index=True,
        verbose_name="وضعیت سند"
    )

    # اطلاعات متقاضی و خودرو
    company_name = models.CharField(max_length=150, blank=True, verbose_name="نام شرکت / متقاضی")
    driver_name = models.CharField(max_length=150, verbose_name="نام راننده")
    driver_mobile = models.CharField(max_length=30, blank=True, verbose_name="شماره موبایل")
    license_plate = models.CharField(max_length=60, blank=True, verbose_name="شماره پلاک")

    # اوزان (کیلوگرم)
    gross_weight = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), verbose_name="وزن پر (Kg)")
    tare_weight = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), verbose_name="وزن خالی (Kg)")
    net_weight = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), verbose_name="وزن خالص (Kg)")

    # تاریخ و زمان
    weight_date = models.DateField(db_index=True, verbose_name="تاریخ توزین")
    weight_time = models.TimeField(null=True, blank=True, verbose_name="ساعت توزین")

    gross_date = models.DateField(null=True, blank=True, verbose_name="تاریخ وزن پر")
    gross_time = models.TimeField(null=True, blank=True, verbose_name="ساعت وزن پر")
    tare_date = models.DateField(null=True, blank=True, verbose_name="تاریخ وزن خالی")
    tare_time = models.TimeField(null=True, blank=True, verbose_name="ساعت وزن خالی")

    operator = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emergency_tickets",
        verbose_name="اپراتور ثبت‌کننده"
    )
    notes = models.TextField(blank=True, verbose_name="توضیحات")

    # ابطال
    cancellation_reason = models.TextField(blank=True, verbose_name="دلیل ابطال")
    cancelled_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cancelled_emergency_tickets",
        verbose_name="کاربر ابطال‌کننده"
    )
    cancelled_at = models.DateTimeField(null=True, blank=True, verbose_name="زمان ابطال")

    class Meta:
        verbose_name = "قبض توزین متفرقه / آزاد"
        verbose_name_plural = "قبوض توزین متفرقه و آزاد"
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["serial_number"]),
            models.Index(fields=["weight_date"]),
            models.Index(fields=["driver_name"]),
            models.Index(fields=["driver_mobile"]),
            models.Index(fields=["license_plate"]),
            models.Index(fields=["company_name"]),
        ]

    def __str__(self):
        return f"قبض متفرقه {self.serial_number} - {self.driver_name} ({self.license_plate})"

    def save(self, *args, **kwargs):
        if not self.serial_number:
            from weighbridge.services import SerialNumberService
            self.serial_number = SerialNumberService.allocate_serial_number(SerialNumberService.SCOPE_EMERGENCY)
        elif self.pk:
            orig_serial = EmergencyWeighTicket.objects.filter(pk=self.pk).values_list("serial_number", flat=True).first()
            if orig_serial and orig_serial != self.serial_number:
                from django.core.exceptions import ValidationError
                raise ValidationError({"serial_number": "شماره سریال قبض متفرقه پس از صدور قطعی قابل تغییر نیست."})

        # محاسبه وزن خالص
        if self.gross_weight and self.tare_weight:
            if self.gross_weight >= self.tare_weight:
                self.net_weight = self.gross_weight - self.tare_weight
            else:
                self.net_weight = self.tare_weight - self.gross_weight
        super().save(*args, **kwargs)

    @classmethod
    def generate_serial(cls) -> str:
        from weighbridge.services import SerialNumberService
        return SerialNumberService.allocate_serial_number(SerialNumberService.SCOPE_EMERGENCY)

    @property
    def jalali_weight_date(self):
        return format_jalali_date(self.weight_date)

    @property
    def jalali_gross_date(self):
        return format_jalali_date(self.gross_date or self.weight_date)

    @property
    def jalali_tare_date(self):
        return format_jalali_date(self.tare_date or self.weight_date)

    @property
    def time_str(self):
        return format_time_hhmm(self.weight_time)

    @property
    def gross_time_str(self):
        return format_time_hhmm(self.gross_time or self.weight_time)

    @property
    def tare_time_str(self):
        return format_time_hhmm(self.tare_time or self.weight_time)

    @property
    def net_tonnage(self):
        return round((self.net_weight or Decimal("0")) / Decimal("1000"), 3)

    @property
    def gross_tonnage(self):
        return round((self.gross_weight or Decimal("0")) / Decimal("1000"), 3)

    @property
    def tare_tonnage(self):
        return round((self.tare_weight or Decimal("0")) / Decimal("1000"), 3)

    @property
    def operator_name(self):
        if self.operator:
            return self.operator.get_full_name() or self.operator.username
        return "سیستم باسکول"


class TicketSequence(BaseModel):
    """
    Dedicated atomic sequence counter for weighbridge tickets.
    Provides row-level locked, concurrency-safe, gap-managed,
    and audit-traceable monotonic numbering.
    """
    scope = models.CharField(
        max_length=50, 
        unique=True, 
        db_index=True, 
        verbose_name="دامنه شماره‌گذاری"
    )
    prefix = models.CharField(
        max_length=20, 
        blank=True, 
        default="", 
        verbose_name="پیشوند شماره سریال"
    )
    last_number = models.BigIntegerField(
        default=0, 
        verbose_name="آخرین شماره تخصیص‌یافته"
    )
    description = models.CharField(
        max_length=150, 
        blank=True, 
        verbose_name="شرح دامنه"
    )

    class Meta:
        verbose_name = "توالی شماره قبض"
        verbose_name_plural = "توالی‌های شماره قبض"
        ordering = ["scope"]

    def __str__(self):
        return f"توالی {self.scope}: آخرین شماره {self.last_number} (پیشوند: '{self.prefix}')"


class TicketRevision(models.Model):
    """
    Formal governance and versioning model for completed weighbridge tickets (Phase 3.2.3).
    Ensures complete auditability, preserves historical weighing evidence,
    records immutable before/after snapshots, and strictly isolates revision numbers from print counts.
    """
    class RevisionStatus(models.TextChoices):
        PENDING = "PENDING", "در انتظار بررسی"
        APPROVED = "APPROVED", "تأیید شده"
        APPLIED = "APPLIED", "اعمال شده"
        REJECTED = "REJECTED", "رد شده"
        WITHDRAWN = "WITHDRAWN", "انصراف داده شده"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(
        WeighTicket,
        on_delete=models.PROTECT,
        related_name="revisions",
        verbose_name="قبض مربوطه"
    )
    revision_number = models.PositiveIntegerField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="شماره نسخه اعمال‌شده"
    )
    ticket_current_revision_at_request = models.PositiveIntegerField(
        default=0,
        verbose_name="شماره نسخه قبض هنگام ثبت درخواست"
    )
    status = models.CharField(
        max_length=20,
        choices=RevisionStatus.choices,
        default=RevisionStatus.PENDING,
        db_index=True,
        verbose_name="وضعیت بازنگری"
    )
    reason = models.TextField(
        verbose_name="دلیل و توجیه درخواست بازنگری"
    )

    # Immutable JSON snapshots with Decimal-safe data
    before_snapshot = models.JSONField(
        default=dict,
        verbose_name="اسنپ‌شات مقادیر قبل از اصلاح"
    )
    after_snapshot = models.JSONField(
        default=dict,
        verbose_name="اسنپ‌شات مقادیر پیشنهادی جدید"
    )
    changed_fields = models.JSONField(
        default=list,
        verbose_name="فهرست فیلدهای تغییریافته"
    )

    # Requester identity & audit
    requested_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="requested_ticket_revisions",
        verbose_name="ثبت‌کننده درخواست"
    )
    requested_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name="زمان ثبت درخواست"
    )

    # Supervisor Reviewer identity & audit
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_ticket_revisions",
        verbose_name="بررسی‌کننده / تأییدکننده"
    )
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="زمان بررسی"
    )
    review_notes = models.TextField(
        blank=True,
        verbose_name="توضیحات و ادله بررسی"
    )

    # Applier identity & audit
    applied_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="applied_ticket_revisions",
        verbose_name="اعمال‌کننده در سیستم"
    )
    applied_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="زمان اعمال"
    )

    # Discrepancy link
    discrepancy_approval = models.ForeignKey(
        "monitoring.DiscrepancyApproval",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revisions",
        verbose_name="تأییدیه مغایرت مرتبط"
    )
    discrepancy_details = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="جزییات ارزیابی مغایرت"
    )

    class Meta:
        verbose_name = "بازنگری قبض"
        verbose_name_plural = "بازنگری‌های قبوض"
        ordering = ["-requested_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["ticket"],
                condition=models.Q(status="PENDING"),
                name="unique_pending_revision_per_ticket"
            ),
            models.UniqueConstraint(
                fields=["ticket", "revision_number"],
                condition=models.Q(revision_number__isnull=False),
                name="unique_ticket_applied_revision_number"
            ),
        ]
        indexes = [
            models.Index(fields=["ticket", "status"]),
            models.Index(fields=["status", "requested_at"]),
        ]

    def __str__(self):
        rev_str = f"Rev. {self.revision_number}" if self.revision_number else "در انتظار بررسی"
        return f"بازنگری قبض {self.ticket.serial_number} ({rev_str}) - {self.get_status_display()}"

    @property
    def jalali_requested_at(self):
        return format_jalali_datetime(self.requested_at) if self.requested_at else "-"

    @property
    def jalali_reviewed_at(self):
        return format_jalali_datetime(self.reviewed_at) if self.reviewed_at else "-"

    @property
    def jalali_applied_at(self):
        return format_jalali_datetime(self.applied_at) if self.applied_at else "-"

    @property
    def is_pending(self):
        return self.status == self.RevisionStatus.PENDING

    @property
    def is_applied(self):
        return self.status == self.RevisionStatus.APPLIED





