import sys
from django.core.management.base import BaseCommand
from django.utils import timezone
from weighbridge.models import WeighTicket, TicketStatus
from monitoring.services.anomaly_engine import AnomalyDetectionEngine
from monitoring.services.waiting_time_analysis import WaitingTimeAnalysisService
from monitoring.models import MonitoringRuleConfig, AlertType


class Command(BaseCommand):
    help = "Periodically inspect in-yard open tickets and detect prolonged waiting times or anomalies."

    def safe_print(self, text: str, style_func=None):
        """Safely write text handling cp1252 encoding on Windows consoles."""
        try:
            msg = style_func(text) if style_func else text
            self.stdout.write(msg)
        except UnicodeEncodeError:
            # Fallback to ascii/safe replacement on legacy console streams
            safe_text = text.encode("ascii", "replace").decode("ascii")
            msg = style_func(safe_text) if style_func else safe_text
            self.stdout.write(msg)

    def handle(self, *args, **options):
        open_tickets = WeighTicket.objects.filter(
            status__in=[
                TicketStatus.WAITING_SECOND,
                TicketStatus.WAITING_FIRST,
                TicketStatus.FIRST_REGISTERED,
            ]
        ).select_related("product", "party", "unload_location", "vehicle", "driver")

        total_open = open_tickets.count()
        self.safe_print(f"Checking open tickets in yard: {total_open} tickets found.")

        alerts_created_or_updated = 0
        rule_config = MonitoringRuleConfig.get_rule_config(AlertType.LONG_WAITING_TIME)

        for ticket in open_tickets:
            alert_data = WaitingTimeAnalysisService.analyze(ticket=ticket, config=rule_config)
            if alert_data:
                alert_obj = AnomalyDetectionEngine._upsert_alert(ticket=ticket, data=alert_data)
                if alert_obj:
                    alerts_created_or_updated += 1
                    self.safe_print(
                        f"Long waiting alert for ticket #{ticket.serial_number} (ID: {ticket.id})",
                        self.style.WARNING
                    )

        self.safe_print(
            f"Completed: {alerts_created_or_updated} alerts created or updated.",
            self.style.SUCCESS
        )
