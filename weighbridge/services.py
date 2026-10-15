from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction, IntegrityError
from django.db.models import Max
from core.models import SystemSetting
from weighbridge.models import WeighTicket, TicketStatus

class TicketCalculationService:
    """
    Pure business logic service for weighbridge calculations.
    """
    @staticmethod
    def calculate_ticket(
        first_weight: Decimal,
        second_weight: Decimal | None,
        sent_weight: Decimal = Decimal("0"),
        loss_percent: Decimal = Decimal("0"),
        manual_loss_weight: Decimal | None = None,
        product = None,
        is_loss_overridden: bool = False
    ) -> dict:
        """
        Calculate gross, tare, net, loss, final weight and variances.
        """
        w1 = Decimal(str(first_weight or 0))
        
        if second_weight is not None and str(second_weight).strip() != "":
            w2 = Decimal(str(second_weight))
            gross_weight = max(w1, w2)
            tare_weight = min(w1, w2)
            net_weight = gross_weight - tare_weight
        else:
            gross_weight = w1
            tare_weight = Decimal("0")
            net_weight = Decimal("0")

        # Loss calculation
        loss_pct = Decimal(str(loss_percent or 0))
        if is_loss_overridden and manual_loss_weight is not None:
            loss_weight = Decimal(str(manual_loss_weight))
        else:
            if net_weight > 0 and loss_pct > 0:
                loss_weight = (net_weight * (loss_pct / Decimal("100"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            else:
                loss_weight = Decimal("0.00")

        final_weight = max(Decimal("0.00"), net_weight - loss_weight)

        # Sent weight variance
        s_weight = Decimal(str(sent_weight or 0))
        if s_weight > 0 and net_weight > 0:
            weight_diff = net_weight - s_weight
            diff_percent = ((weight_diff / s_weight) * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            weight_diff = Decimal("0.00")
            diff_percent = Decimal("0.00")

        # Tolerance / Discrepancy Check
        sys_settings = SystemSetting.get_settings()
        allowed_tolerance_kg = product.standard_tolerance_kg if product and product.standard_tolerance_kg else sys_settings.max_tolerance_kg
        
        is_tolerance_exceeded = False
        if s_weight > 0 and net_weight > 0:
            if abs(weight_diff) > allowed_tolerance_kg:
                is_tolerance_exceeded = True
            elif sys_settings.max_tolerance_percent > 0 and abs(diff_percent) > sys_settings.max_tolerance_percent:
                is_tolerance_exceeded = True

        return {
            "gross_weight": gross_weight,
            "tare_weight": tare_weight,
            "net_weight": net_weight,
            "loss_percent": loss_pct,
            "loss_weight": loss_weight,
            "final_weight": final_weight,
            "sent_weight": s_weight,
            "weight_difference": weight_diff,
            "weight_difference_percent": diff_percent,
            "is_tolerance_exceeded": is_tolerance_exceeded,
        }

class SerialNumberService:
    """
    Atomic serial number generator for weighbridge tickets.
    """
    @classmethod
    def get_next_serial_number(cls) -> str:
        with transaction.atomic():
            settings_obj = SystemSetting.get_settings()
            settings_obj = SystemSetting.objects.select_for_update().get(pk=settings_obj.pk)
            prefix = settings_obj.serial_prefix.strip() if settings_obj.serial_prefix else ""
            start_num = settings_obj.serial_start_number

            # Query highest existing ticket ID or serial
            tickets = WeighTicket.objects.all()
            
            # Find max numeric serial
            highest_num = 0
            for ticket in tickets.order_by("-id")[:100]:
                sn = ticket.serial_number
                if prefix and sn.startswith(prefix):
                    sn = sn[len(prefix):]
                # extract digits
                digits = "".join(ch for ch in sn if ch.isdigit())
                if digits:
                    val = int(digits)
                    if val > highest_num:
                        highest_num = val

            if highest_num < start_num:
                next_num = start_num
            else:
                next_num = highest_num + 1

            if prefix:
                return f"{prefix}{next_num}"
            return str(next_num)


class VehicleDriverRegistrationService:
    """
    Automates vehicle and driver lookup and auto-registration:
    - If vehicle/driver already exists, retrieves and links them.
    - If vehicle/driver does not exist, automatically registers them into MasterData.
    """
    @classmethod
    def resolve_or_create(cls, ticket, cleaned_data=None):
        import re
        from masterdata.models import Driver, Vehicle
        from weighbridge.plate_policy import normalize_plate

        cleaned_data = cleaned_data or {}
        driver_name = (cleaned_data.get("driver_name_custom") or ticket.driver_name_custom or "").strip()
        driver_mobile = (cleaned_data.get("driver_mobile_custom") or ticket.driver_mobile_custom or "").strip()
        plate = (cleaned_data.get("license_plate_display") or ticket.license_plate_display or "").strip()
        v_type = cleaned_data.get("vehicle_type") or ticket.vehicle_type

        # 1. Driver Resolution & Auto-Registration
        driver = cleaned_data.get("driver") or ticket.driver
        if not driver and driver_name:
            driver = Driver.objects.filter(full_name__iexact=driver_name).first()
            if not driver and driver_mobile:
                driver = Driver.objects.filter(mobile=driver_mobile).first()
            if not driver:
                driver = Driver.objects.create(
                    full_name=driver_name,
                    mobile=driver_mobile,
                    is_active=True,
                )
            else:
                if driver_mobile and not driver.mobile:
                    driver.mobile = driver_mobile
                    driver.save(update_fields=["mobile"])

        if driver:
            ticket.driver = driver
            if not ticket.driver_name_custom:
                ticket.driver_name_custom = driver.full_name
            if not ticket.driver_mobile_custom and driver.mobile:
                ticket.driver_mobile_custom = driver.mobile

        # 2. Vehicle Resolution & Auto-Registration
        vehicle = cleaned_data.get("vehicle") or ticket.vehicle
        norm_p = normalize_plate(plate)

        if not vehicle and norm_p:
            vehicle = Vehicle.objects.filter(normalized_plate=norm_p).select_related("vehicle_type", "default_driver").first()
        if not vehicle and plate:
            vehicle = Vehicle.objects.filter(plate_display__iexact=plate).select_related("vehicle_type", "default_driver").first()

        if not vehicle:
            p1 = (cleaned_data.get("plate_part1") or "").strip()
            pL = (cleaned_data.get("plate_letter") or "").strip()
            p2 = (cleaned_data.get("plate_part2") or "").strip()
            pIran = (cleaned_data.get("plate_iran") or "").strip()

            if not (p1 and pL and p2 and pIran):
                match = re.search(
                    r"(\d{2}|[۰-۹]{2})\s*([^\d\s\-_]+)\s*(\d{3}|[۰-۹]{3})\s*(?:-?\s*(?:ایران|ايران)?\s*(\d{2}|[۰-۹]{2}))?",
                    plate
                )
                if match:
                    p1 = match.group(1) or ""
                    pL = match.group(2) or ""
                    p2 = match.group(3) or ""
                    pIran = match.group(4) or ""

            tare_wt = ticket.tare_weight if (ticket.tare_weight and ticket.tare_weight > 0) else Decimal("0.00")

            # HOTFIX 1: Concurrency-safe vehicle registration
            # Wrap creation in an isolated savepoint using transaction.atomic().
            # If two concurrent transactions attempt to register the same vehicle simultaneously,
            # PostgreSQL's unique constraint will reject the second with an IntegrityError.
            # The savepoint is rolled back cleanly without corrupting the outer transaction,
            # and the vehicle created by the competing transaction is retrieved safely.
            try:
                with transaction.atomic():
                    if norm_p:
                        vehicle = Vehicle.objects.filter(normalized_plate=norm_p).select_for_update().first()
                    elif plate:
                        vehicle = Vehicle.objects.filter(plate_display__iexact=plate).select_for_update().first()

                    if not vehicle:
                        vehicle = Vehicle.objects.create(
                            plate_display=plate,
                            plate_part1=p1,
                            plate_letter=pL,
                            plate_part2=p2,
                            plate_iran=pIran,
                            normalized_plate=norm_p,
                            vehicle_type=v_type,
                            default_driver=driver,
                            empty_weight=tare_wt,
                            is_active=True,
                        )
            except IntegrityError as exc:
                vehicle = None
                if norm_p:
                    vehicle = Vehicle.objects.filter(normalized_plate=norm_p).first()
                if not vehicle and plate:
                    vehicle = Vehicle.objects.filter(plate_display__iexact=plate).first()
                if not vehicle:
                    # Unrelated IntegrityError; re-raise!
                    raise exc

        if vehicle:
            updated_fields = []
            if not vehicle.vehicle_type and v_type:
                vehicle.vehicle_type = v_type
                updated_fields.append("vehicle_type")
            if not vehicle.default_driver and driver:
                vehicle.default_driver = driver
                updated_fields.append("default_driver")
            if (not vehicle.empty_weight or vehicle.empty_weight == 0) and (ticket.tare_weight and ticket.tare_weight > 0):
                vehicle.empty_weight = ticket.tare_weight
                updated_fields.append("empty_weight")
            if updated_fields:
                vehicle.save(update_fields=updated_fields)

        if vehicle:
            ticket.vehicle = vehicle
            if not ticket.vehicle_type and vehicle.vehicle_type:
                ticket.vehicle_type = vehicle.vehicle_type
            if not ticket.driver and vehicle.default_driver:
                ticket.driver = vehicle.default_driver

        return vehicle, driver

