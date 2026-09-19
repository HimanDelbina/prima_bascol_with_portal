from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
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
