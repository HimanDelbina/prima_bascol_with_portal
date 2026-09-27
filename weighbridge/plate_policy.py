import re
import unicodedata
from contextlib import contextmanager

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone


def normalize_plate(value):
    value = unicodedata.normalize("NFKC", str(value or ""))
    value = value.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩يك", "01234567890123456789یک"))
    value = value.replace("ایران", "").replace("ايران", "")
    return re.sub(r"[\W_\u200c\u200d\u200e\u200f\u0640]+", "", value).upper()


def can_manage_plate_exceptions(user):
    profile = getattr(user, "profile", None)
    return bool(user and user.is_authenticated and user.is_active and (
        user.is_superuser or (profile and profile.is_active and profile.role in (
            "super_admin", "system_admin", "weighbridge_manager",
        ))
    ))


def can_manage_blocked_plates(user):
    """فقط مدیر ارشد و مدیر باسکول مجاز به مدیریت لیست سیاه پلاک‌ها هستند."""
    profile = getattr(user, "profile", None)
    return bool(user and user.is_authenticated and user.is_active and (
        user.is_superuser or (profile and profile.is_active and profile.role in (
            "super_admin", "weighbridge_manager",
        ))
    ))


class DailyPlatePolicy:
    @staticmethod
    def registration_date(ticket):
        return ticket.first_weight_date or (timezone.localtime(ticket.created_at).date() if ticket.created_at else timezone.localdate())

    @classmethod
    @contextmanager
    def locked(cls, ticket):
        from weighbridge.models import PlateDayLock
        plate = normalize_plate(ticket.license_plate_display)
        with transaction.atomic():
            if plate:
                guard, _ = PlateDayLock.objects.get_or_create(plate=plate, date=cls.registration_date(ticket))
                PlateDayLock.objects.select_for_update().get(pk=guard.pk)
            yield

    @classmethod
    def check(cls, ticket):
        from weighbridge.models import WeighTicket, TicketStatus, PlateRegistrationException, BlockedPlate
        plate = normalize_plate(ticket.license_plate_display)
        day = cls.registration_date(ticket)
        if not plate:
            raise ValidationError({"license_plate_display": "پلاک معتبر وارد کنید."})
        if ticket.status == TicketStatus.CANCELLED:
            return None

        # 1. Enforcement: Blocked / Blacklisted Plates
        blocked = BlockedPlate.objects.filter(normalized_plate=plate, is_active=True).first()
        if blocked:
            raise ValidationError({"license_plate_display": (
                f"⛔ پلاک «{ticket.license_plate_display}» در لیست سیاه مسدود شده است و مجاز به بارگیری و ورود نمی‌باشد. "
                f"دلیل مسدودسازی: {blocked.reason}"
            )})

        old = WeighTicket.objects.filter(pk=ticket.pk).first() if ticket.pk else None
        if old and normalize_plate(old.license_plate_display) == plate and cls.registration_date(old) == day and old.status != TicketStatus.CANCELLED:
            return None  # Completing an existing ticket, including historical duplicates, remains valid.
        conflict = WeighTicket.objects.filter(normalized_plate=plate).exclude(
            status=TicketStatus.CANCELLED,
        ).exclude(pk=ticket.pk).annotate(
            registration_day=Coalesce("first_weight_date", TruncDate("created_at")),
        ).filter(registration_day=day).first()
        if not conflict:
            return None
        exception = PlateRegistrationException.objects.filter(normalized_plate=plate, is_active=True).first()
        if exception:
            return exception
        raise ValidationError({"license_plate_display": (
            f"این پلاک در این تاریخ با قبض شماره {conflict.serial_number} ثبت شده است. "
            "برای ثبت مجدد، سرپرست باسکول باید پلاک را در استثناهای ثبت روزانه مجاز کند."
        )})

    @classmethod
    def save(cls, ticket, *, user=None, assign_serial=False):
        from weighbridge.models import WeighTicket, TicketStatus
        from weighbridge.services import SerialNumberService
        from audit.services import log_audit
        with cls.locked(ticket):
            exception = cls.check(ticket)
            old = WeighTicket.objects.filter(pk=ticket.pk).first() if ticket.pk else None
            changed = not old or normalize_plate(old.license_plate_display) != normalize_plate(ticket.license_plate_display) or cls.registration_date(old) != cls.registration_date(ticket) or old.status == TicketStatus.CANCELLED
            if changed:
                ticket.duplicate_exception = exception
            if assign_serial:
                ticket.serial_number = SerialNumberService.get_next_serial_number()
            if not ticket.pk and not ticket.first_weight_date:
                ticket.first_weight_date = cls.registration_date(ticket)
            ticket.save()
            if exception:
                log_audit(action="create" if not old else "update", model_name="WeighTicket",
                          record_id=ticket.pk, record_repr=f"قبض {ticket.serial_number}", user=user,
                          reason=f"ثبت تکراری روزانه با مجوز پلاک: {exception.reason}",
                          new_values={"duplicate_exception_id": exception.pk, "plate": ticket.license_plate_display,
                                      "date": str(cls.registration_date(ticket)), "approved_by": exception.approved_by_id})
        return ticket
