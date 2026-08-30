import logging
from django.db import transaction
from weighbridge.models import WeighTicket, TicketStatus
from monitoring.models import MonitoringAlert, MonitoringRuleConfig, AlertType, AlertStatus
from monitoring.selectors.monitoring_queries import get_ticket_risk_score

from monitoring.services.vehicle_analysis import VehicleTareAnalysisService
from monitoring.services.discrepancy_analysis import WeightDiscrepancyAnalysisService
from monitoring.services.loss_analysis import LossAnomalyAnalysisService
from monitoring.services.ticket_analysis import NetWeightAnalysisService
from monitoring.services.waiting_time_analysis import WaitingTimeAnalysisService
from monitoring.services.weight_edit_analysis import WeightEditAnalysisService

logger = logging.getLogger(__name__)


class AnomalyDetectionEngine:
    """
    Core Anomaly Detection Engine (Phase 1).
    Evaluates active rule sets against weighbridge tickets, prevents duplicate alerts (upsert),
    computes ticket risk score, and provides explainable results for operators and managers.
    """
    ANALYZERS = [
        (AlertType.VEHICLE_TARE_ANOMALY, VehicleTareAnalysisService),
        (AlertType.WEIGHT_DISCREPANCY, WeightDiscrepancyAnalysisService),
        (AlertType.LOSS_ANOMALY, LossAnomalyAnalysisService),
        (AlertType.NET_WEIGHT_ANOMALY, NetWeightAnalysisService),
        (AlertType.LONG_WAITING_TIME, WaitingTimeAnalysisService),
        (AlertType.WEIGHT_EDIT_ANOMALY, WeightEditAnalysisService),
    ]

    @classmethod
    def run_for_ticket(cls, ticket: WeighTicket) -> list[MonitoringAlert]:
        """
        Execute all active monitoring rules for a given ticket.
        Returns the list of generated or updated MonitoringAlert instances.
        """
        if not ticket or ticket.status == TicketStatus.CANCELLED:
            return []

        generated_alerts = []

        with transaction.atomic():
            for alert_type, analyzer_cls in cls.ANALYZERS:
                config = MonitoringRuleConfig.get_rule_config(alert_type)
                if not config.enabled:
                    continue

                try:
                    alert_data = analyzer_cls.analyze(ticket=ticket, config=config)
                    if alert_data:
                        alert_obj = cls._upsert_alert(ticket=ticket, data=alert_data)
                        if alert_obj:
                            generated_alerts.append(alert_obj)
                    else:
                        # If condition no longer holds and alert is OPEN, can either keep or close
                        pass
                except Exception as ex:
                    logger.exception(f"Error evaluating rule {alert_type} on ticket {ticket.id}: {ex}")

        return generated_alerts

    @classmethod
    def _upsert_alert(cls, ticket: WeighTicket, data: dict) -> MonitoringAlert:
        """
        Create new alert or safely update existing alert to prevent duplicate records.
        """
        alert_type = data["alert_type"]
        existing_alert = MonitoringAlert.objects.filter(
            ticket=ticket,
            alert_type=alert_type
        ).first()

        if existing_alert:
            # If already resolved or ignored, do not force reopen unless severity escalated
            if existing_alert.status not in [AlertStatus.RESOLVED, AlertStatus.IGNORED]:
                existing_alert.severity = data["severity"]
                existing_alert.title = data["title"]
                existing_alert.description = data["description"]
                existing_alert.reason = data["reason"]
                existing_alert.current_value = data.get("current_value")
                existing_alert.baseline_value = data.get("baseline_value")
                existing_alert.deviation_value = data.get("deviation_value")
                existing_alert.deviation_percent = data.get("deviation_percent")
                existing_alert.sample_size = data.get("sample_size", 0)
                existing_alert.confidence = data.get("confidence")
                existing_alert.metadata = data.get("metadata", {})
                existing_alert.save()
            return existing_alert

        # Create new alert
        new_alert = MonitoringAlert.objects.create(
            ticket=ticket,
            alert_type=alert_type,
            severity=data["severity"],
            title=data["title"],
            description=data["description"],
            reason=data["reason"],
            current_value=data.get("current_value"),
            baseline_value=data.get("baseline_value"),
            deviation_value=data.get("deviation_value"),
            deviation_percent=data.get("deviation_percent"),
            sample_size=data.get("sample_size", 0),
            confidence=data.get("confidence"),
            status=AlertStatus.OPEN,
            metadata=data.get("metadata", {}),
        )
        return new_alert

    @classmethod
    def get_ticket_analysis_summary(cls, ticket: WeighTicket) -> dict:
        """
        Retrieve risk score, active alerts, and explainable summary for a ticket.
        """
        alerts = MonitoringAlert.objects.filter(ticket=ticket).order_by("-id")
        open_alerts = [a for a in alerts if a.status in [AlertStatus.OPEN, AlertStatus.REVIEWED]]
        
        risk_score, risk_level = get_ticket_risk_score(ticket.id)
        has_critical = any(a.severity == "CRITICAL" for a in open_alerts)
        has_high = any(a.severity == "HIGH" for a in open_alerts)

        return {
            "risk_score": risk_score,
            "risk_level": risk_level,
            "total_alerts_count": alerts.count(),
            "open_alerts_count": len(open_alerts),
            "has_critical": has_critical,
            "has_high": has_high,
            "open_alerts": open_alerts,
            "all_alerts": alerts,
        }
