from datetime import datetime, date, time, timedelta
from decimal import Decimal
from django.db import models
from django.db.models import Q
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.jalali import format_jalali_date, format_jalali_datetime, format_time_hhmm, to_persian_digits


class WorkShift(models.Model):
    """
    Administrator-configurable shift definition template.
    Defines schedule parameters, time bounds, grace periods, and overnight flag.
    Editing a WorkShift does not retroactively mutate past shift sessions.
    """
    name = models.CharField(max_length=100, verbose_name="نام شیفت")
    code = models.CharField(max_length=50, unique=True, db_index=True, verbose_name="کد یکتای شیفت")
    start_time = models.TimeField(verbose_name="ساعت شروع")
    end_time = models.TimeField(verbose_name="ساعت پایان")
    is_overnight = models.BooleanField(default=False, editable=False, verbose_name="شیفت شبانه / عبور از نیمه‌شب")
    is_active = models.BooleanField(default=True, db_index=True, verbose_name="فعال")
    valid_from = models.DateField(null=True, blank=True, verbose_name="معتبر از تاریخ")
    valid_until = models.DateField(null=True, blank=True, verbose_name="معتبر تا تاریخ")
    allowed_grace_minutes = models.PositiveIntegerField(default=15, verbose_name="مهلت تاخیر مجاز ورود (دقیقه)")
    description = models.TextField(blank=True, verbose_name="توضیحات و یادداشت‌ها")
    created_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="created_shifts", verbose_name="ایجادکننده"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ایجاد")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاریخ بروزرسانی")

    class Meta:
        verbose_name = "الگوی شیفت کاری"
        verbose_name_plural = "الگوهای شیفت کاری"
        ordering = ["start_time", "code"]

    def __str__(self):
        overnight_tag = " (شبانه)" if self.is_overnight else ""
        return f"{self.name} [{self.code}]{overnight_tag} ({format_time_hhmm(self.start_time)} - {format_time_hhmm(self.end_time)})"

    def clean(self):
        super().clean()
        if self.start_time is not None and self.end_time is not None:
            if self.start_time == self.end_time:
                raise ValidationError({"end_time": "ساعت شروع و پایان شیفت نمی‌تواند یکسان باشد (مدت زمان صفر)."})
            self.is_overnight = (self.start_time > self.end_time)

        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValidationError({"valid_until": "تاریخ پایان اعتبار نمی‌تواند قبل از تاریخ شروع باشد."})

    def save(self, *args, **kwargs):
        if self.start_time is not None and self.end_time is not None:
            self.is_overnight = (self.start_time > self.end_time)
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def duration_hours(self) -> float:
        """Calculate scheduled duration in hours."""
        if not self.start_time or not self.end_time:
            return 0.0
        dummy_date = date(2000, 1, 1)
        dt_start = datetime.combine(dummy_date, self.start_time)
        if self.is_overnight:
            dt_end = datetime.combine(dummy_date + timedelta(days=1), self.end_time)
        else:
            dt_end = datetime.combine(dummy_date, self.end_time)
        diff_seconds = (dt_end - dt_start).total_seconds()
        return round(diff_seconds / 3600.0, 2)


class ShiftSessionStatus(models.TextChoices):
    SCHEDULED = "SCHEDULED", "برنامه‌ریزی شده"
    ACTIVE = "ACTIVE", "فعال / در حال کار"
    CLOSED = "CLOSED", "بسته شده"
    CANCELLED = "CANCELLED", "لغو شده"
    ABANDONED = "ABANDONED", "رها شده / ترک پست"


class ShiftSession(models.Model):
    """
    Actual instance of an operational shift session on a given operational date.
    Separates runtime shift lifecycle from schedule templates.
    """
    shift = models.ForeignKey(
        WorkShift, on_delete=models.PROTECT,
        related_name="sessions", verbose_name="الگوی شیفت"
    )
    operational_date = models.DateField(db_index=True, verbose_name="تاریخ عملیاتی شیفت")
    status = models.CharField(
        max_length=20, choices=ShiftSessionStatus.choices,
        default=ShiftSessionStatus.SCHEDULED, db_index=True, verbose_name="وضعیت جلسه"
    )
    actual_start = models.DateTimeField(null=True, blank=True, verbose_name="زمان واقعی بازگشایی")
    actual_end = models.DateTimeField(null=True, blank=True, verbose_name="زمان واقعی بستن")
    opened_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="opened_shift_sessions", verbose_name="بازگشایی توسط"
    )
    closed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="closed_shift_sessions", verbose_name="بسته شده توسط"
    )
    initial_scale_zero_ok = models.BooleanField(default=False, verbose_name="تایید صفر بودن اولیه باسکول")
    initial_printer_paper_ok = models.BooleanField(default=False, verbose_name="تایید سلامت چاپگر و رول کاغذ")
    notes = models.TextField(blank=True, verbose_name="یادداشت‌های جلسه")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ایجاد")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاریخ بروزرسانی")

    class Meta:
        verbose_name = "جلسه شیفت کاری"
        verbose_name_plural = "جلسات شیفت کاری"
        ordering = ["-operational_date", "-actual_start", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["shift", "operational_date"],
                condition=Q(status__in=[ShiftSessionStatus.SCHEDULED, ShiftSessionStatus.ACTIVE, ShiftSessionStatus.CLOSED]),
                name="unique_session_per_shift_operational_date"
            )
        ]

    def __str__(self):
        return f"{self.shift.name} - تاریخ عملیاتی: {format_jalali_date(self.operational_date)} ({self.get_status_display()})"

    @property
    def is_active(self) -> bool:
        return self.status == ShiftSessionStatus.ACTIVE

    @property
    def jalali_operational_date(self) -> str:
        return format_jalali_date(self.operational_date)

    def validate_transition(self, target_status: str):
        """Validate allowed state transitions."""
        allowed_transitions = {
            ShiftSessionStatus.SCHEDULED: [ShiftSessionStatus.ACTIVE, ShiftSessionStatus.CANCELLED],
            ShiftSessionStatus.ACTIVE: [ShiftSessionStatus.CLOSED, ShiftSessionStatus.ABANDONED],
            ShiftSessionStatus.ABANDONED: [ShiftSessionStatus.CLOSED],
            ShiftSessionStatus.CLOSED: [],
            ShiftSessionStatus.CANCELLED: [],
        }
        if target_status not in allowed_transitions.get(self.status, []):
            raise ValidationError(
                f"تغییر وضعیت نامعتبر است: انتقال از {self.get_status_display()} به {dict(ShiftSessionStatus.choices).get(target_status, target_status)} مجاز نیست."
            )

    def open_session(self, user: User, initial_scale_zero: bool = True, initial_printer_paper: bool = True, notes: str = ""):
        """Activate a scheduled session."""
        self.validate_transition(ShiftSessionStatus.ACTIVE)
        self.status = ShiftSessionStatus.ACTIVE
        self.actual_start = timezone.now()
        self.opened_by = user
        self.initial_scale_zero_ok = initial_scale_zero
        self.initial_printer_paper_ok = initial_printer_paper
        if notes:
            self.notes = f"{self.notes}\n[بازگشایی]: {notes}".strip()
        self.save()

    def close_session(self, user: User, notes: str = ""):
        """Close an active or abandoned session."""
        self.validate_transition(ShiftSessionStatus.CLOSED)
        self.status = ShiftSessionStatus.CLOSED
        self.actual_end = timezone.now()
        self.closed_by = user
        if notes:
            self.notes = f"{self.notes}\n[بستن شیفت]: {notes}".strip()
        self.save()


class ShiftOperatorRole(models.TextChoices):
    PRIMARY = "PRIMARY", "اپراتور اصلی"
    ASSISTANT = "ASSISTANT", "اپراتور کمکی"
    SUPERVISOR = "SUPERVISOR", "سرپرست ناظر"


class ShiftAssignmentStatus(models.TextChoices):
    ASSIGNED = "ASSIGNED", "تخصیص‌یافته"
    CHECKED_IN = "CHECKED_IN", "حاضر در پست"
    CHECKED_OUT = "CHECKED_OUT", "پایان حضور"
    SUBSTITUTED = "SUBSTITUTED", "جایگزین‌شده"
    CANCELLED = "CANCELLED", "لغو تخصیص"


class ShiftOperatorAssignment(models.Model):
    """
    Operator assignment and attendance record within a ShiftSession.
    Enforces individual accountability and supports multiple operators per session.
    """
    session = models.ForeignKey(
        ShiftSession, on_delete=models.CASCADE,
        related_name="assignments", verbose_name="جلسه شیفت"
    )
    operator = models.ForeignKey(
        User, on_delete=models.PROTECT,
        related_name="shift_assignments", verbose_name="اپراتور"
    )
    role = models.CharField(
        max_length=20, choices=ShiftOperatorRole.choices,
        default=ShiftOperatorRole.PRIMARY, verbose_name="نقش در شیفت"
    )
    status = models.CharField(
        max_length=20, choices=ShiftAssignmentStatus.choices,
        default=ShiftAssignmentStatus.ASSIGNED, db_index=True, verbose_name="وضعیت تخصیص"
    )
    assigned_start = models.DateTimeField(null=True, blank=True, verbose_name="زمان مقرر شروع")
    assigned_end = models.DateTimeField(null=True, blank=True, verbose_name="زمان مقرر پایان")
    check_in_time = models.DateTimeField(null=True, blank=True, verbose_name="زمان واقعی حضور")
    check_out_time = models.DateTimeField(null=True, blank=True, verbose_name="زمان پایان حضور")

    # Supervisor Substitution Fields
    is_substitution = models.BooleanField(default=False, verbose_name="جایگزینی اضطراری")
    substituted_operator = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="substituted_by_assignments", verbose_name="اپراتور اصلی جایگزین‌شده"
    )
    authorized_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="authorized_shift_substitutions", verbose_name="تاییدکننده جایگزینی (سرپرست)"
    )
    substitution_reason = models.TextField(blank=True, verbose_name="دلیل جایگزینی")
    notes = models.TextField(blank=True, verbose_name="یادداشت‌ها")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ایجاد")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاریخ بروزرسانی")

    class Meta:
        verbose_name = "تخصیص اپراتور به شیفت"
        verbose_name_plural = "تخصیص‌های اپراتوری شیفت"
        ordering = ["-session__operational_date", "role", "operator__username"]

    def __str__(self):
        return f"{self.operator.get_full_name() or self.operator.username} ({self.get_role_display()}) - {self.session}"

    def clean(self):
        super().clean()
        # Single active check-in policy
        if self.status == ShiftAssignmentStatus.CHECKED_IN:
            active_other = ShiftOperatorAssignment.objects.filter(
                operator=self.operator,
                status=ShiftAssignmentStatus.CHECKED_IN
            ).exclude(pk=self.pk)
            if active_other.exists():
                other_assignment = active_other.first()
                raise ValidationError(
                    f"اپراتور {self.operator.username} هم‌اکنون در جلسه شیفت «{other_assignment.session}» در وضعیت حضور فعال (CHECKED_IN) قرار دارد. ثبت همزمان دو حضور فعال مجاز نیست."
                )

        # Substitution requirements
        if self.is_substitution:
            if not self.substituted_operator:
                raise ValidationError({"substituted_operator": "انتخاب اپراتور جایگزین‌شده الزامی است."})
            if not self.authorized_by:
                raise ValidationError({"authorized_by": "تعیین سرپرست تاییدکننده جایگزینی الزامی است."})
            if not self.substitution_reason or len(self.substitution_reason.strip()) < 5:
                raise ValidationError({"substitution_reason": "ثبت دلیل معتبر برای جایگزینی اضطراری الزامی است (حداقل ۵ کاراکتر)."})
            if self.operator == self.substituted_operator:
                raise ValidationError({"operator": "اپراتور جایگزین نمی‌تواند همان اپراتور اصلی باشد."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def check_in(self):
        """Mark operator as checked in."""
        if self.status in [ShiftAssignmentStatus.CHECKED_OUT, ShiftAssignmentStatus.CANCELLED]:
            raise ValidationError("امکان ثبت حضور برای تخصیص لغو شده یا پایان‌یافته وجود ندارد.")
        self.status = ShiftAssignmentStatus.CHECKED_IN
        self.check_in_time = timezone.now()
        self.save()

    def check_out(self):
        """Mark operator as checked out."""
        if self.status != ShiftAssignmentStatus.CHECKED_IN:
            raise ValidationError("فقط اپراتوری که وضعیت حضور فعال دارد می‌تواند خروج ثبت کند.")
        self.status = ShiftAssignmentStatus.CHECKED_OUT
        self.check_out_time = timezone.now()
        self.save()


class ShiftExceptionLog(models.Model):
    """
    Records weighings performed outside active shifts, ensuring 100% operational continuity
    without ever blocking the physical scale, while providing full visibility to supervisors.
    """
    PHASE_CHOICES = [
        ("FIRST", "توزین اول"),
        ("SECOND", "توزین دوم"),
        ("DIRECT", "توزین مستقیم"),
    ]

    ticket = models.ForeignKey(
        "weighbridge.WeighTicket", on_delete=models.CASCADE,
        related_name="shift_exceptions", verbose_name="قبض توزین",
        db_constraint=False
    )
    weighing_phase = models.CharField(max_length=20, choices=PHASE_CHOICES, verbose_name="مرحله توزین")
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="shift_exceptions", verbose_name="اپراتور مجری"
    )
    timestamp = models.DateTimeField(default=timezone.now, verbose_name="زمان وقوع")
    reason = models.CharField(max_length=255, default="NO_ACTIVE_SHIFT", verbose_name="علت استثنا")
    notes = models.TextField(blank=True, verbose_name="توضیحات و جزییات")
    acknowledged_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="acknowledged_shift_exceptions", verbose_name="بررسی‌شده توسط سرپرست"
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True, verbose_name="زمان بررسی")
    acknowledgement_note = models.TextField(blank=True, verbose_name="توضیحات بررسی سرپرست")

    class Meta:
        verbose_name = "ثبت استثنای شیفت"
        verbose_name_plural = "استثنائات توزین خارج از شیفت"
        ordering = ["-timestamp"]

    def __str__(self):
        return f"استثنای شیفت - قبض {self.ticket.serial_number} ({self.get_weighing_phase_display()}) در {format_jalali_datetime(self.timestamp)}"

    def acknowledge(self, user: User, note: str = ""):
        """Mark exception as acknowledged by supervisor."""
        self.acknowledged_by = user
        self.acknowledged_at = timezone.now()
        self.acknowledgement_note = note
        self.save(update_fields=["acknowledged_by", "acknowledged_at", "acknowledgement_note"])
