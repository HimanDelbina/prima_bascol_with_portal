from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from weighbridge.models import WeighTicket, TicketStatus
from monitoring.services.anomaly_engine import AnomalyDetectionEngine


class Command(BaseCommand):
    help = "Re-analyze historical weighbridge tickets and generate or update monitoring alerts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Number of past days to scan (default: 30)."
        )
        parser.add_argument(
            "--from-date",
            type=str,
            help="Start date filter in YYYY-MM-DD format."
        )
        parser.add_argument(
            "--to-date",
            type=str,
            help="End date filter in YYYY-MM-DD format."
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Perform analysis in simulation mode without writing alerts to database."
        )

    def safe_print(self, text: str, style_func=None):
        try:
            msg = style_func(text) if style_func else text
            self.stdout.write(msg)
        except UnicodeEncodeError:
            safe_text = text.encode("ascii", "replace").decode("ascii")
            msg = style_func(safe_text) if style_func else safe_text
            self.stdout.write(msg)

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        days = options["days"]
        from_date_str = options.get("from_date")
        to_date_str = options.get("to_date")

        qs = WeighTicket.objects.exclude(status=TicketStatus.CANCELLED)

        if from_date_str:
            try:
                start_d = datetime.strptime(from_date_str, "%Y-%m-%d").date()
                qs = qs.filter(created_at__date__gte=start_d)
            except ValueError:
                self.safe_print(f"Invalid from-date format: {from_date_str}", self.style.ERROR)
                return

        if to_date_str:
            try:
                end_d = datetime.strptime(to_date_str, "%Y-%m-%d").date()
                qs = qs.filter(created_at__date__lte=end_d)
            except ValueError:
                self.safe_print(f"Invalid to-date format: {to_date_str}", self.style.ERROR)
                return

        if not from_date_str and not to_date_str:
            since = timezone.now().date() - timedelta(days=days)
            qs = qs.filter(created_at__date__gte=since)

        total_tickets = qs.count()
        mode_str = "[DRY-RUN SIMULATION]" if dry_run else "[LIVE RUN]"
        self.safe_print(f"{mode_str} Scanning {total_tickets} tickets for historical anomaly detection...")

        total_alerts_found = 0
        analyzed_count = 0

        for ticket in qs.iterator(chunk_size=100):
            analyzed_count += 1
            if dry_run:
                # In dry-run mode, analyze without calling _upsert_alert
                for alert_type, analyzer_cls in AnomalyDetectionEngine.ANALYZERS:
                    from monitoring.models import MonitoringRuleConfig
                    config = MonitoringRuleConfig.get_rule_config(alert_type)
                    if not config.enabled:
                        continue
                    try:
                        alert_data = analyzer_cls.analyze(ticket=ticket, config=config)
                        if alert_data:
                            total_alerts_found += 1
                    except Exception:
                        pass
            else:
                alerts = AnomalyDetectionEngine.run_for_ticket(ticket)
                total_alerts_found += len(alerts)

            if analyzed_count % 50 == 0:
                self.safe_print(f"Processed {analyzed_count}/{total_tickets} tickets...")

        self.safe_print(
            f"{mode_str} Finished analysis: {analyzed_count} tickets analyzed, {total_alerts_found} anomaly conditions identified.",
            self.style.SUCCESS
        )
