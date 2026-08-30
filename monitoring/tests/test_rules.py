from decimal import Decimal
from datetime import datetime, date, time, timedelta
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.management import call_command
from core.jalali import get_today_gregorian

from weighbridge.models import WeighTicket, TicketStatus, WeightMode
from masterdata.models import Product, Party, Vehicle, VehicleType, Driver, UnloadLocation, Location, OperationType
from audit.models import AuditLog, AuditAction
from audit.services import log_audit
from monitoring.models import (
    MonitoringAlert, MonitoringRuleConfig, AlertType, AlertSeverity, AlertStatus, AlertConfidence
)
from monitoring.services.anomaly_engine import AnomalyDetectionEngine
from monitoring.services.vehicle_analysis import VehicleTareAnalysisService
from monitoring.services.discrepancy_analysis import WeightDiscrepancyAnalysisService
from monitoring.services.loss_analysis import LossAnomalyAnalysisService
from monitoring.services.ticket_analysis import NetWeightAnalysisService
from monitoring.services.waiting_time_analysis import WaitingTimeAnalysisService
from monitoring.services.weight_edit_analysis import WeightEditAnalysisService


class MonitoringSmartAnalysisTests(TestCase):
    def setUp(self):
        # Create standard test users
        self.admin_user = User.objects.create_superuser(
            username="admin_test",
            password="password123",
            email="admin@example.com"
        )
        self.operator_user = User.objects.create_user(
            username="operator_test",
            password="password123",
            first_name="علی",
            last_name="رضایی"
        )
        self.operator_user.profile.role = "weighbridge_operator"
        self.operator_user.profile.save()

        # Masterdata fixtures
        self.product = Product.objects.create(name="آهن اسفنجی", code="P-SPONGE", standard_tolerance_kg=Decimal("50.00"), default_loss_percent=Decimal("0.50"))
        self.party = Party.objects.create(name="فولاد مبارکه", code="PT-100", phone="09120000000")
        self.v_type = VehicleType.objects.create(name="تریلی لبه‌دار", standard_tare_weight=Decimal("9800.00"))
        self.driver = Driver.objects.create(full_name="حسین علیزاده", mobile="09121111111")
        self.vehicle = Vehicle.objects.create(
            plate_display="12 ع 345 - ایران 67",
            vehicle_type=self.v_type,
            default_driver=self.driver,
            empty_weight=Decimal("9780.00")
        )
        self.unload_loc = UnloadLocation.objects.create(name="سیلو شماره ۲")
        self.op_type = OperationType.objects.create(name="وارده خرید", direction="inbound")

    def _create_completed_ticket(self, vehicle, tare, gross, net, sent_weight=Decimal("0"), loss_pct=Decimal("0.45"), duration_mins=40, party=None, product=None, serial_suffix=1):
        today = date(1405, 6, 1)
        t1_time = time(8, 0)
        t2_time = time(8 + (duration_mins // 60), duration_mins % 60)
        
        t = WeighTicket.objects.create(
            serial_number=f"T-HIST-{serial_suffix}-{vehicle.id}",
            status=TicketStatus.COMPLETED,
            weight_mode=WeightMode.EMPTY_FIRST,
            vehicle=vehicle,
            license_plate_display=vehicle.plate_display,
            party=party or self.party,
            product=product or self.product,
            driver=self.driver,
            first_weight=tare,
            first_weight_date=today,
            first_weight_time=t1_time,
            first_weight_operator=self.operator_user,
            second_weight=gross,
            second_weight_date=today,
            second_weight_time=t2_time,
            second_weight_operator=self.operator_user,
            gross_weight=gross,
            tare_weight=tare,
            net_weight=net,
            sent_weight=sent_weight,
            weight_difference=(net - sent_weight) if sent_weight > 0 else Decimal("0"),
            weight_difference_percent=round(((net - sent_weight) / sent_weight * Decimal("100")), 2) if sent_weight > 0 else Decimal("0"),
            loss_percent=loss_pct,
            loss_weight=round(net * (loss_pct / Decimal("100")), 2),
            final_weight=round(net - (net * (loss_pct / Decimal("100"))), 2),
            unload_location=self.unload_loc,
            operation_type=self.op_type
        )
        return t

    def test_vehicle_tare_normal_and_anomaly(self):
        """
        Test Scenario 1 & 2:
        50 historical completed trips for Vehicle with tare between 9,650 and 9,950 Kg (Average: 9,780 Kg).
        1) New ticket with tare 9,790 Kg -> Normal (no alert).
        2) New ticket with tare 10,420 Kg (+640 Kg / +6.54%) -> HIGH/CRITICAL alert with explainable reason.
        """
        # Create 50 baseline trips
        for i in range(1, 51):
            tare_w = Decimal(str(9700 + (i % 15) * 10))  # 9700 to 9840
            self._create_completed_ticket(
                vehicle=self.vehicle,
                tare=tare_w,
                gross=Decimal("37500.00"),
                net=Decimal("37500.00") - tare_w,
                serial_suffix=i
            )

        # 1. Normal Tare ticket (in progress)
        ticket_normal = WeighTicket.objects.create(
            serial_number="T-TEST-NORM",
            status=TicketStatus.WAITING_SECOND,
            vehicle=self.vehicle,
            license_plate_display=self.vehicle.plate_display,
            party=self.party,
            product=self.product,
            tare_weight=Decimal("9780.00"),
            gross_weight=Decimal("37500.00"),
            net_weight=Decimal("27720.00"),
        )
        alert_normal = VehicleTareAnalysisService.analyze(ticket_normal)
        self.assertIsNone(alert_normal, "Normal tare weight should not trigger an anomaly alert.")

        # 2. Anomaly Tare ticket (10,420 Kg)
        ticket_anomaly = WeighTicket.objects.create(
            serial_number="T-TEST-ANOMALY",
            status=TicketStatus.WAITING_SECOND,
            vehicle=self.vehicle,
            license_plate_display=self.vehicle.plate_display,
            party=self.party,
            product=self.product,
            tare_weight=Decimal("10420.00"),
            gross_weight=Decimal("38000.00"),
            net_weight=Decimal("27580.00"),
        )
        alert_res = VehicleTareAnalysisService.analyze(ticket_anomaly)
        self.assertIsNotNone(alert_res, "Tare of 10,420 Kg must trigger an anomaly alert.")
        self.assertEqual(alert_res["alert_type"], AlertType.VEHICLE_TARE_ANOMALY)
        self.assertIn(alert_res["severity"], [AlertSeverity.HIGH, AlertSeverity.CRITICAL])
        self.assertEqual(alert_res["confidence"], AlertConfidence.HIGH)
        self.assertEqual(alert_res["sample_size"], 50)
        self.assertIn("10,420", alert_res["reason"])
        self.assertIn("50", alert_res["reason"])
        self.assertIn("درصد", alert_res["reason"])

    def test_insufficient_history_no_false_positive(self):
        """
        Test Scenario 3:
        Vehicle with only 3 trips (< minimum_history of 10) does not generate low-confidence false positive alert.
        """
        new_vehicle = Vehicle.objects.create(plate_display="99 ب 999 - ایران 11")
        for i in range(1, 4):
            self._create_completed_ticket(vehicle=new_vehicle, tare=Decimal("9500.00"), gross=Decimal("25000.00"), net=Decimal("15500.00"), serial_suffix=f"sparse-{i}")

        ticket_sparse = WeighTicket.objects.create(
            serial_number="T-SPARSE-1",
            status=TicketStatus.COMPLETED,
            vehicle=new_vehicle,
            license_plate_display=new_vehicle.plate_display,
            party=self.party,
            product=self.product,
            tare_weight=Decimal("10800.00"),
            gross_weight=Decimal("25000.00"),
            net_weight=Decimal("14200.00"),
        )
        alert_res = VehicleTareAnalysisService.analyze(ticket_sparse)
        self.assertIsNone(alert_res, "Should not trigger tare alert when history sample size < minimum_history.")

    def test_weight_discrepancy_and_party_behavior(self):
        """
        Test Scenario 4 & 5:
        1) Net 9,020 vs Sent 9,000 (20 Kg diff) -> Normal.
        2) Net 9,250 vs Sent 9,000 (250 Kg diff) -> CRITICAL alert + Party historical reason.
        """
        # Create 15 party history trips with ~25 Kg avg discrepancy
        for i in range(1, 16):
            self._create_completed_ticket(
                vehicle=self.vehicle,
                tare=Decimal("9780.00"),
                gross=Decimal("18805.00"),
                net=Decimal("9025.00"),
                sent_weight=Decimal("9000.00"),
                serial_suffix=f"party-hist-{i}"
            )

        # 1. Normal Discrepancy (20 Kg)
        ticket_norm = WeighTicket.objects.create(
            serial_number="T-DISC-NORM",
            status=TicketStatus.COMPLETED,
            party=self.party,
            product=self.product,
            sent_weight=Decimal("9000.00"),
            net_weight=Decimal("9020.00"),
            weight_difference=Decimal("20.00"),
            weight_difference_percent=Decimal("0.22"),
        )
        res_norm = WeightDiscrepancyAnalysisService.analyze(ticket_norm)
        self.assertIsNone(res_norm)

        # 2. Critical Discrepancy (250 Kg)
        ticket_crit = WeighTicket.objects.create(
            serial_number="T-DISC-CRIT",
            status=TicketStatus.COMPLETED,
            party=self.party,
            product=self.product,
            sent_weight=Decimal("9000.00"),
            net_weight=Decimal("9250.00"),
            weight_difference=Decimal("250.00"),
            weight_difference_percent=Decimal("2.78"),
        )
        res_crit = WeightDiscrepancyAnalysisService.analyze(ticket_crit)
        self.assertIsNotNone(res_crit)
        self.assertEqual(res_crit["alert_type"], AlertType.WEIGHT_DISCREPANCY)
        self.assertEqual(res_crit["severity"], AlertSeverity.CRITICAL)
        self.assertIn("250", res_crit["reason"])
        self.assertIn("فولاد مبارکه", res_crit["reason"])

    def test_loss_anomaly_detection(self):
        """
        Test Scenario 6:
        Product baseline loss is 0.45%. A ticket with 2.10% loss generates LOSS_ANOMALY alert.
        """
        # Create 20 baseline trips with 0.45% loss
        for i in range(1, 21):
            self._create_completed_ticket(
                vehicle=self.vehicle,
                tare=Decimal("9780.00"),
                gross=Decimal("35000.00"),
                net=Decimal("25220.00"),
                loss_pct=Decimal("0.45"),
                serial_suffix=f"loss-hist-{i}"
            )

        ticket_loss = WeighTicket.objects.create(
            serial_number="T-LOSS-ANOM",
            status=TicketStatus.COMPLETED,
            party=self.party,
            product=self.product,
            net_weight=Decimal("25000.00"),
            loss_percent=Decimal("2.10"),
            is_loss_overridden=True,
            loss_override_reason="رطوبت بالا و ناخالصی خاکستر"
        )
        alert_res = LossAnomalyAnalysisService.analyze(ticket_loss)
        self.assertIsNotNone(alert_res)
        self.assertEqual(alert_res["alert_type"], AlertType.LOSS_ANOMALY)
        self.assertIn("2.10", alert_res["reason"])
        self.assertIn("0.45", alert_res["reason"])

    def test_net_weight_hierarchical_anomaly(self):
        """
        Test Scenario 7:
        Hierarchical baseline for Vehicle+Product is 27,800 Kg.
        Current net is 18,200 Kg (-9,600 Kg / -34.5%) -> NET_WEIGHT_ANOMALY alert.
        """
        for i in range(1, 25):
            self._create_completed_ticket(
                vehicle=self.vehicle,
                tare=Decimal("9780.00"),
                gross=Decimal("37580.00"),
                net=Decimal("27800.00"),
                product=self.product,
                serial_suffix=f"net-hist-{i}"
            )

        ticket_net = WeighTicket.objects.create(
            serial_number="T-NET-ANOM",
            status=TicketStatus.COMPLETED,
            vehicle=self.vehicle,
            license_plate_display=self.vehicle.plate_display,
            product=self.product,
            party=self.party,
            tare_weight=Decimal("9780.00"),
            gross_weight=Decimal("27980.00"),
            net_weight=Decimal("18200.00"),
        )
        alert_res = NetWeightAnalysisService.analyze(ticket_net)
        self.assertIsNotNone(alert_res)
        self.assertEqual(alert_res["alert_type"], AlertType.NET_WEIGHT_ANOMALY)
        self.assertIn("18,200", alert_res["reason"])
        self.assertIn("27,800", alert_res["reason"])

    def test_long_waiting_and_check_open_tickets_command(self):
        """
        Test Scenario 8:
        1) Completed ticket with 165 minutes turnaround vs average 42 minutes -> LONG_WAITING_TIME.
        2) Open ticket in yard waiting 200 minutes -> check_open_tickets management command detects it.
        """
        ticket_completed = WeighTicket.objects.create(
            serial_number="T-WAIT-COMPLETED",
            status=TicketStatus.COMPLETED,
            first_weight_date=date(1405, 6, 1),
            first_weight_time=time(8, 0),
            second_weight_date=date(1405, 6, 1),
            second_weight_time=time(10, 45),
            product=self.product,
            party=self.party,
            unload_location=self.unload_loc
        )
        res = WaitingTimeAnalysisService.analyze(ticket_completed)
        self.assertIsNotNone(res)
        self.assertEqual(res["alert_type"], AlertType.LONG_WAITING_TIME)
        self.assertIn("165", res["reason"])

        # Open ticket created earlier today
        ticket_open = WeighTicket.objects.create(
            serial_number="T-WAIT-OPEN-1",
            status=TicketStatus.WAITING_SECOND,
            first_weight_date=get_today_gregorian(),
            first_weight_time=time(6, 0),
            created_at=timezone.now() - timedelta(hours=4),
            vehicle=self.vehicle,
            license_plate_display=self.vehicle.plate_display,
            product=self.product,
            party=self.party,
            first_weight=Decimal("9780.00")
        )
        # Run check_open_tickets command
        call_command("check_open_tickets")
        
        # Verify alert was generated for ticket_open
        alert = MonitoringAlert.objects.filter(ticket=ticket_open, alert_type=AlertType.LONG_WAITING_TIME).first()
        self.assertIsNotNone(alert, "Management command check_open_tickets must create alert for long waiting open ticket.")

    def test_weight_edit_anomaly(self):
        """
        Test Scenario 9:
        Weigh ticket tare weight modified post-registration by 560 Kg (9,760 to 10,320) recorded in AuditLog.
        """
        ticket_edit = WeighTicket.objects.create(
            serial_number="T-EDIT-ANOM",
            status=TicketStatus.COMPLETED,
            tare_weight=Decimal("10320.00"),
            gross_weight=Decimal("38000.00"),
            net_weight=Decimal("27680.00"),
            last_edited_by=self.admin_user,
            last_edit_reason="اصلاح وزن خالی طبق تایید مدیر باسکول"
        )
        log_audit(
            action=AuditAction.OVERRIDE_WEIGHT,
            model_name="WeighTicket",
            record_id=ticket_edit.id,
            record_repr=f"قبض شماره {ticket_edit.serial_number}",
            old_values={"tare_weight": 9760.0, "gross_weight": 38000.0, "net_weight": 28240.0},
            new_values={"tare_weight": 10320.0, "gross_weight": 38000.0, "net_weight": 27680.0},
            reason="اصلاح وزن خالی طبق تایید مدیر باسکول",
            user=self.admin_user
        )
        res = WeightEditAnalysisService.analyze(ticket_edit)
        self.assertIsNotNone(res)
        self.assertEqual(res["alert_type"], AlertType.WEIGHT_EDIT_ANOMALY)
        self.assertIn("560", res["reason"])
        self.assertIn("9,760", res["reason"])
        self.assertIn("10,320", res["reason"])

    def test_duplicate_alert_prevention_and_risk_score(self):
        """
        Test Scenario 10 & 11:
        1) Running AnomalyDetectionEngine multiple times updates alert rather than creating duplicate records (UniqueConstraint).
        2) Risk score sums up alert severity weights and caps at 100.
        """
        # Create baseline history
        for i in range(1, 15):
            self._create_completed_ticket(
                vehicle=self.vehicle,
                tare=Decimal("9780.00"),
                gross=Decimal("37580.00"),
                net=Decimal("27800.00"),
                sent_weight=Decimal("27800.00"),
                serial_suffix=f"dup-test-{i}"
            )

        ticket_multi = WeighTicket.objects.create(
            serial_number="T-MULTI-RISK",
            status=TicketStatus.COMPLETED,
            vehicle=self.vehicle,
            license_plate_display=self.vehicle.plate_display,
            party=self.party,
            product=self.product,
            tare_weight=Decimal("10600.00"),
            gross_weight=Decimal("35000.00"),
            net_weight=Decimal("24400.00"),
            sent_weight=Decimal("27800.00"),
            weight_difference=Decimal("-3400.00"),
            weight_difference_percent=Decimal("12.23"),
            first_weight_date=date(1405, 6, 1),
            first_weight_time=time(7, 0),
            second_weight_date=date(1405, 6, 1),
            second_weight_time=time(11, 0),
        )

        # Run engine 1st time
        AnomalyDetectionEngine.run_for_ticket(ticket_multi)
        count_1 = MonitoringAlert.objects.filter(ticket=ticket_multi).count()
        self.assertTrue(count_1 >= 2, "Should detect at least 2 alerts.")

        # Run engine 2nd time (must not duplicate)
        AnomalyDetectionEngine.run_for_ticket(ticket_multi)
        count_2 = MonitoringAlert.objects.filter(ticket=ticket_multi).count()
        self.assertEqual(count_1, count_2, "Engine must not create duplicate alerts on rerun (Upsert).")

        # Check Risk Score summary
        summary = AnomalyDetectionEngine.get_ticket_analysis_summary(ticket_multi)
        self.assertTrue(0 <= summary["risk_score"] <= 100)
        self.assertTrue(summary["has_high"] or summary["has_critical"])
        self.assertIn(summary["risk_level"], ["پرخطر (High Risk)", "بحرانی (Critical)", "نیازمند بررسی (Needs Review)"])

    def test_resolve_alert_workflow_and_audit(self):
        """
        Test Scenario 12:
        Resolving an alert updates status, records resolver and timestamp, requires resolution note, and logs to AuditLog.
        """
        ticket = WeighTicket.objects.create(serial_number="T-RESOLVE-1", status=TicketStatus.COMPLETED)
        alert = MonitoringAlert.objects.create(
            ticket=ticket,
            alert_type=AlertType.WEIGHT_DISCREPANCY,
            severity=AlertSeverity.HIGH,
            title="مغایرت تست",
            reason="تست",
            status=AlertStatus.OPEN
        )

        client = Client()
        client.force_login(self.admin_user)

        # Resolve alert with resolution note
        url = f"/monitoring/alerts/{alert.id}/resolve/"
        resp = client.post(url, {
            "action_type": AlertStatus.RESOLVED,
            "resolution_note": "خودرو دارای بار اضافی ابزار بوده و وزن مجدداً تایید شد."
        }, follow=True)

        self.assertEqual(resp.status_code, 200)
        alert.refresh_from_db()
        self.assertEqual(alert.status, AlertStatus.RESOLVED)
        self.assertEqual(alert.resolved_by, self.admin_user)
        self.assertIsNotNone(alert.resolved_at)
        self.assertIn("ابزار", alert.resolution_note)

        # Verify audit log entry
        audit_entry = AuditLog.objects.filter(model_name="MonitoringAlert", record_id=str(alert.id)).first()
        self.assertIsNotNone(audit_entry, "Resolving an alert must create an AuditLog entry.")
        self.assertEqual(audit_entry.action, AuditAction.STATUS_CHANGE)

    def test_monitoring_views_and_exports(self):
        """
        Test Scenario 13:
        Verify dashboard, alert list, settings, reports, Excel and CSV export views.
        """
        client = Client()
        client.force_login(self.admin_user)

        # 1. Dashboard
        resp = client.get("/monitoring/")
        self.assertEqual(resp.status_code, 200)

        # 2. Alert List
        resp = client.get("/monitoring/alerts/")
        self.assertEqual(resp.status_code, 200)

        # 3. Excel export
        resp_excel = client.get("/monitoring/alerts/?export=excel")
        self.assertEqual(resp_excel.status_code, 200)
        self.assertEqual(resp_excel["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        # 4. CSV export
        resp_csv = client.get("/monitoring/alerts/?export=csv")
        self.assertEqual(resp_csv.status_code, 200)
        self.assertEqual(resp_csv["Content-Type"], "text/csv; charset=utf-8-sig")

        # 5. Settings view
        resp_settings = client.get("/monitoring/settings/")
        self.assertEqual(resp_settings.status_code, 200)

        # 6. Reports view
        resp_reports = client.get("/monitoring/reports/")
        self.assertEqual(resp_reports.status_code, 200)
