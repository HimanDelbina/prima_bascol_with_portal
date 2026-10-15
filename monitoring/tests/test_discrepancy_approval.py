from decimal import Decimal
from datetime import date, time
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied

from weighbridge.models import WeighTicket, TicketStatus, WeightMode
from masterdata.models import Product, Party, Vehicle, VehicleType, Driver
from audit.models import AuditLog, AuditAction
from monitoring.models import (
    MonitoringAlert, MonitoringRuleConfig, AlertType, AlertSeverity,
    AlertStatus, ApprovalStatus, DiscrepancyApproval
)
from monitoring.services.discrepancy_service import DiscrepancyApprovalService
from weighbridge.services import TicketCalculationService, SerialNumberService


class DiscrepancyApprovalCoreTests(TestCase):
    def setUp(self):
        # Create users with specific roles
        self.superadmin = User.objects.create_superuser(
            username="superadmin_test",
            password="password123",
            email="superadmin@example.com"
        )
        self.supervisor = User.objects.create_user(
            username="manager_test",
            password="password123",
            first_name="محمدرضا",
            last_name="مدیر"
        )
        self.supervisor.profile.role = "weighbridge_manager"
        self.supervisor.profile.save()

        self.operator = User.objects.create_user(
            username="operator_test",
            password="password123",
            first_name="امیر",
            last_name="اپراتور"
        )
        self.operator.profile.role = "weighbridge_operator"
        self.operator.profile.save()

        self.other_operator = User.objects.create_user(
            username="other_op_test",
            password="password123",
            first_name="بهرام",
            last_name="اپراتور"
        )
        self.other_operator.profile.role = "weighbridge_operator"
        self.other_operator.profile.save()

        # Masterdata fixtures
        self.product = Product.objects.create(
            name="ورق گرم فولادی",
            code="P-STEEL",
            standard_tolerance_kg=Decimal("50.00"),
            default_loss_percent=Decimal("0.50")
        )
        self.party = Party.objects.create(
            name="فولاد مبارکه اصفهان",
            code="PT-MSC",
            phone="03133333333"
        )
        self.v_type = VehicleType.objects.create(
            name="کامیون جفت ۱۰ چرخ",
            standard_tare_weight=Decimal("10500.00")
        )
        self.driver = Driver.objects.create(
            full_name="رضا حسینی",
            mobile="09121234567"
        )
        self.vehicle = Vehicle.objects.create(
            plate_display="34 ب 789 - ایران 11",
            vehicle_type=self.v_type,
            default_driver=self.driver,
            empty_weight=Decimal("10500.00")
        )

        # Baseline Ticket in yard (waiting second weight)
        self.ticket = WeighTicket.objects.create(
            serial_number=SerialNumberService.allocate_serial_number(),
            status=TicketStatus.WAITING_SECOND,
            weight_mode=WeightMode.EMPTY_FIRST,
            product=self.product,
            party=self.party,
            vehicle=self.vehicle,
            driver=self.driver,
            license_plate_display="34 ب 789 - ایران 11",
            first_weight=Decimal("10500.00"),
            first_weight_date=date(2026, 10, 15),
            first_weight_time=time(8, 30),
            first_weight_operator=self.operator,
            sent_weight=Decimal("15000.00"),
        )

    # 1. Normal tickets without discrepancies
    def test_01_normal_ticket_without_discrepancy(self):
        trial = TicketCalculationService.calculate_ticket(
            first_weight=Decimal("10500.00"),
            second_weight=Decimal("25500.00"),
            sent_weight=Decimal("15000.00"),
            product=self.product
        )
        self.assertEqual(trial["net_weight"], Decimal("15000.00"))
        self.assertEqual(trial["weight_difference"], Decimal("0.00"))
        self.assertFalse(trial["is_tolerance_exceeded"])

        eval_res = DiscrepancyApprovalService.evaluate_ticket_discrepancies(self.ticket, trial_weights=trial)
        self.assertFalse(eval_res["has_discrepancies"])
        self.assertFalse(eval_res["requires_approval"])
        self.assertTrue(eval_res["can_finalize"])

    # 2. Tolerance within allowed range
    def test_02_tolerance_within_allowed_range(self):
        trial = TicketCalculationService.calculate_ticket(
            first_weight=Decimal("10500.00"),
            second_weight=Decimal("25530.00"),  # Net: 15030, diff: +30 kg <= 50 kg tolerance
            sent_weight=Decimal("15000.00"),
            product=self.product
        )
        self.assertFalse(trial["is_tolerance_exceeded"])
        eval_res = DiscrepancyApprovalService.evaluate_ticket_discrepancies(self.ticket, trial_weights=trial)
        self.assertTrue(eval_res["can_finalize"])
        self.assertFalse(eval_res["requires_approval"])

    # 3. Tolerance exceeded with default non-blocking rule
    def test_03_tolerance_exceeded_default_non_blocking(self):
        # Configure rule without requiring approval
        rule_cfg = MonitoringRuleConfig.get_rule_config(AlertType.WEIGHT_DISCREPANCY)
        rule_cfg.requires_approval = False
        rule_cfg.warning_threshold = Decimal("50.00")
        rule_cfg.critical_threshold = Decimal("200.00")
        rule_cfg.save()

        trial = TicketCalculationService.calculate_ticket(
            first_weight=Decimal("10500.00"),
            second_weight=Decimal("25800.00"),  # Net: 15300, diff: +300 kg > 50 kg
            sent_weight=Decimal("15000.00"),
            product=self.product
        )
        self.assertTrue(trial["is_tolerance_exceeded"])

        eval_res = DiscrepancyApprovalService.evaluate_ticket_discrepancies(self.ticket, trial_weights=trial)
        self.assertTrue(eval_res["has_discrepancies"])
        self.assertFalse(eval_res["requires_approval"])
        self.assertTrue(eval_res["can_finalize"])  # Non-blocking by default

    # 4. Approval-required rule blocks finalization
    def test_04_approval_required_rule_blocks_finalization(self):
        rule_cfg = MonitoringRuleConfig.get_rule_config(AlertType.WEIGHT_DISCREPANCY)
        rule_cfg.requires_approval = True
        rule_cfg.warning_threshold = Decimal("50.00")
        rule_cfg.critical_threshold = Decimal("200.00")
        rule_cfg.save()

        trial = TicketCalculationService.calculate_ticket(
            first_weight=Decimal("10500.00"),
            second_weight=Decimal("25800.00"),  # Net: 15300, diff: +300 kg
            sent_weight=Decimal("15000.00"),
            product=self.product
        )

        eval_res = DiscrepancyApprovalService.evaluate_ticket_discrepancies(self.ticket, trial_weights=trial)
        self.assertTrue(eval_res["requires_approval"])
        self.assertFalse(eval_res["can_finalize"])
        self.assertIn("نیازمند تأیید سرپرست", eval_res["blocking_reason"])

    # 5. Requesting approval creates PENDING record with weight snapshots
    def test_05_request_approval_lifecycle(self):
        req = DiscrepancyApprovalService.request_approval(
            ticket=self.ticket,
            user=self.operator,
            reason="اختلاف وزن ۳۰۰ کیلوگرم ناشی از رطوبت محموله با تأیید انباردار",
            gross=Decimal("25800.00"),
            tare=Decimal("10500.00"),
            net=Decimal("15300.00"),
        )
        self.assertEqual(req.status, ApprovalStatus.PENDING)
        self.assertEqual(req.requested_by, self.operator)
        self.assertEqual(req.net_weight_snapshot, Decimal("15300.00"))
        self.assertEqual(req.gross_weight_snapshot, Decimal("25800.00"))
        self.assertEqual(req.tare_weight_snapshot, Decimal("10500.00"))

        # Verify AuditLog created
        log = AuditLog.objects.filter(model_name="DiscrepancyApproval", record_id=str(req.id)).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.action, AuditAction.DISCREPANCY_APPROVAL)

    # 6. Duplicate PENDING approval request is blocked
    def test_06_duplicate_pending_approval_request_blocked(self):
        DiscrepancyApprovalService.request_approval(
            ticket=self.ticket,
            user=self.operator,
            reason="درخواست اول جهت بررسی مغایرت رطوبت بار",
            gross=Decimal("25800.00"),
            tare=Decimal("10500.00"),
            net=Decimal("15300.00"),
        )
        with self.assertRaises(ValidationError):
            DiscrepancyApprovalService.request_approval(
                ticket=self.ticket,
                user=self.operator,
                reason="درخواست تکراری دوم برای همان قبض",
                gross=Decimal("25800.00"),
                tare=Decimal("10500.00"),
                net=Decimal("15300.00"),
            )

    # 7. Supervisor approves request, enabling ticket finalization
    def test_07_supervisor_approval_allows_finalization(self):
        rule_cfg = MonitoringRuleConfig.get_rule_config(AlertType.WEIGHT_DISCREPANCY)
        rule_cfg.requires_approval = True
        rule_cfg.save()

        req = DiscrepancyApprovalService.request_approval(
            ticket=self.ticket,
            user=self.operator,
            reason="مغایرت رطوبت محموله با قبض انبار مبدأ مطابقت دارد",
            gross=Decimal("25800.00"),
            tare=Decimal("10500.00"),
            net=Decimal("15300.00"),
        )

        # Supervisor decides to approve
        approved = DiscrepancyApprovalService.decide_approval(
            approval_id=req.id,
            supervisor_user=self.supervisor,
            decision="approve",
            decision_reason="مستندات رطوبت بررسی و بر اساس هماهنگی با مدیر کارخانه تأیید شد"
        )
        self.assertEqual(approved.status, ApprovalStatus.APPROVED)
        self.assertEqual(approved.reviewed_by, self.supervisor)
        self.assertIsNotNone(approved.reviewed_at)

        # Now evaluate ticket discrepancies again with the same weights
        trial = {
            "gross_weight": Decimal("25800.00"),
            "tare_weight": Decimal("10500.00"),
            "net_weight": Decimal("15300.00"),
            "sent_weight": Decimal("15000.00"),
            "weight_difference": Decimal("300.00"),
            "weight_difference_percent": Decimal("2.00"),
            "is_tolerance_exceeded": True,
        }
        eval_res = DiscrepancyApprovalService.evaluate_ticket_discrepancies(self.ticket, trial_weights=trial)
        self.assertTrue(eval_res["is_approved"])
        self.assertTrue(eval_res["can_finalize"])

    # 8. Supervisor rejects request, preventing ticket finalization
    def test_08_supervisor_rejection_blocks_finalization(self):
        rule_cfg = MonitoringRuleConfig.get_rule_config(AlertType.WEIGHT_DISCREPANCY)
        rule_cfg.requires_approval = True
        rule_cfg.save()

        req = DiscrepancyApprovalService.request_approval(
            ticket=self.ticket,
            user=self.operator,
            reason="مغایرت غیرعادی ۳۰۰ کیلوگرم",
            gross=Decimal("25800.00"),
            tare=Decimal("10500.00"),
            net=Decimal("15300.00"),
        )

        rejected = DiscrepancyApprovalService.decide_approval(
            approval_id=req.id,
            supervisor_user=self.supervisor,
            decision="reject",
            decision_reason="کسری وزن غیرموجه بوده و راننده باید مجدداً روی باسکول برود"
        )
        self.assertEqual(rejected.status, ApprovalStatus.REJECTED)

        trial = {
            "gross_weight": Decimal("25800.00"),
            "tare_weight": Decimal("10500.00"),
            "net_weight": Decimal("15300.00"),
            "sent_weight": Decimal("15000.00"),
            "weight_difference": Decimal("300.00"),
            "weight_difference_percent": Decimal("2.00"),
            "is_tolerance_exceeded": True,
        }
        eval_res = DiscrepancyApprovalService.evaluate_ticket_discrepancies(self.ticket, trial_weights=trial)
        self.assertTrue(eval_res["is_rejected"])
        self.assertFalse(eval_res["can_finalize"])

    # 9. Separation of duties: Operator or supervisor cannot approve their own request
    def test_09_self_approval_restriction(self):
        req = DiscrepancyApprovalService.request_approval(
            ticket=self.ticket,
            user=self.operator,
            reason="درخواست مجوز برای تست تفکیک وظایف",
            gross=Decimal("25800.00"),
            tare=Decimal("10500.00"),
            net=Decimal("15300.00"),
        )
        # Operator attempts to self-approve
        with self.assertRaises(ValidationError) as ctx:
            DiscrepancyApprovalService.decide_approval(
                approval_id=req.id,
                supervisor_user=self.operator,
                decision="approve",
                decision_reason="تأیید توسط خود اپراتور"
            )
        self.assertIn("تفکیک وظایف", str(ctx.exception))

        # Cancel first request to allow second request
        req.status = ApprovalStatus.CANCELLED
        req.save()

        # Supervisor who has approval rights but submitted this request attempts to self-approve
        sup_req = DiscrepancyApprovalService.request_approval(
            ticket=self.ticket,
            user=self.supervisor,
            reason="درخواست توسط سرپرست شیفت",
            gross=Decimal("25800.00"),
            tare=Decimal("10500.00"),
            net=Decimal("15300.00"),
        )
        with self.assertRaises(ValidationError) as ctx2:
            DiscrepancyApprovalService.decide_approval(
                approval_id=sup_req.id,
                supervisor_user=self.supervisor,
                decision="approve",
                decision_reason="تأیید درخواست ثبت‌شده توسط خود"
            )
        self.assertIn("تفکیک وظایف", str(ctx2.exception))

    # 10. Unauthorized user cannot decide approval
    def test_10_unauthorized_user_cannot_decide_approval(self):
        req = DiscrepancyApprovalService.request_approval(
            ticket=self.ticket,
            user=self.operator,
            reason="درخواست مجوز مغایرت",
            gross=Decimal("25800.00"),
            tare=Decimal("10500.00"),
            net=Decimal("15300.00"),
        )
        # Other operator (without manager/admin role) attempts to decide
        with self.assertRaises(PermissionDenied):
            DiscrepancyApprovalService.decide_approval(
                approval_id=req.id,
                supervisor_user=self.other_operator,
                decision="approve",
                decision_reason="تلاش غیرمجاز همکار اپراتور"
            )

    # 11. Concurrent / duplicate decision prevention
    def test_11_duplicate_decision_prevention(self):
        req = DiscrepancyApprovalService.request_approval(
            ticket=self.ticket,
            user=self.operator,
            reason="درخواست مجوز مغایرت",
            gross=Decimal("25800.00"),
            tare=Decimal("10500.00"),
            net=Decimal("15300.00"),
        )
        DiscrepancyApprovalService.decide_approval(
            approval_id=req.id,
            supervisor_user=self.supervisor,
            decision="approve",
            decision_reason="تأیید اول"
        )
        # Attempt to decide again
        with self.assertRaises(ValidationError) as ctx:
            DiscrepancyApprovalService.decide_approval(
                approval_id=req.id,
                supervisor_user=self.supervisor,
                decision="reject",
                decision_reason="تلاش مجدد برای تغییر تصمیم"
            )
        self.assertIn("قبلاً تعیین تکلیف شده است", str(ctx.exception))

    # 12. Ticket modification after approval invalidates approval
    def test_12_ticket_modification_invalidates_approval(self):
        rule_cfg = MonitoringRuleConfig.get_rule_config(AlertType.WEIGHT_DISCREPANCY)
        rule_cfg.requires_approval = True
        rule_cfg.save()

        req = DiscrepancyApprovalService.request_approval(
            ticket=self.ticket,
            user=self.operator,
            reason="درخواست مجوز با وزن خالص ۱۵,۳۰۰",
            gross=Decimal("25800.00"),
            tare=Decimal("10500.00"),
            net=Decimal("15300.00"),
        )
        DiscrepancyApprovalService.decide_approval(
            approval_id=req.id,
            supervisor_user=self.supervisor,
            decision="approve",
            decision_reason="مجوز برای اوزان فعلی صادر شد"
        )

        # Later, weights are changed (e.g., Gross changed to 26000, Net became 15500)
        invalidated = DiscrepancyApprovalService.check_and_invalidate_stale_approvals(
            ticket=self.ticket,
            current_gross=Decimal("26000.00"),
            current_tare=Decimal("10500.00"),
            current_net=Decimal("15500.00"),
        )
        self.assertTrue(invalidated)

        # Verify approval record is now CANCELLED
        req.refresh_from_db()
        self.assertEqual(req.status, ApprovalStatus.CANCELLED)

        # Ticket cannot be finalized with obsolete approval
        trial = {
            "gross_weight": Decimal("26000.00"),
            "tare_weight": Decimal("10500.00"),
            "net_weight": Decimal("15500.00"),
            "sent_weight": Decimal("15000.00"),
            "weight_difference": Decimal("500.00"),
            "weight_difference_percent": Decimal("3.33"),
            "is_tolerance_exceeded": True,
        }
        eval_res = DiscrepancyApprovalService.evaluate_ticket_discrepancies(self.ticket, trial_weights=trial)
        self.assertFalse(eval_res["can_finalize"])

    # 13. Cancellation of obsolete requests
    def test_13_cancel_approval_request(self):
        req = DiscrepancyApprovalService.request_approval(
            ticket=self.ticket,
            user=self.operator,
            reason="درخواست اشتباهی ثبت شده",
            gross=Decimal("25800.00"),
            tare=Decimal("10500.00"),
            net=Decimal("15300.00"),
        )
        cancelled = DiscrepancyApprovalService.cancel_approval_request(
            approval_id=req.id,
            user=self.operator,
            reason="لغو به علت تصحیح ورودی توسط راننده"
        )
        self.assertEqual(cancelled.status, ApprovalStatus.CANCELLED)

    # 14. Meaningful reason requirement
    def test_14_short_reason_rejected(self):
        with self.assertRaises(ValidationError):
            DiscrepancyApprovalService.request_approval(
                ticket=self.ticket,
                user=self.operator,
                reason="کم",  # < 5 chars
                gross=Decimal("25800.00"),
                tare=Decimal("10500.00"),
                net=Decimal("15300.00"),
            )


class DiscrepancyViewIntegrationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.supervisor = User.objects.create_user(
            username="manager_vtest",
            password="password123",
            first_name="مدیر",
            last_name="باسکول"
        )
        self.supervisor.profile.role = "weighbridge_manager"
        self.supervisor.profile.save()

        self.operator = User.objects.create_user(
            username="op_vtest",
            password="password123",
            first_name="اپراتور",
            last_name="ورودی"
        )
        self.operator.profile.role = "weighbridge_operator"
        self.operator.profile.save()

        self.product = Product.objects.create(
            name="کلاف گرم فولادی",
            code="P-COIL",
            standard_tolerance_kg=Decimal("50.00")
        )
        self.party = Party.objects.create(name="فولاد هرمزگان")
        self.v_type = VehicleType.objects.create(name="تریلر ۱۸ چرخ")
        self.vehicle = Vehicle.objects.create(
            plate_display="56 س 123 - ایران 88",
            vehicle_type=self.v_type,
            empty_weight=Decimal("14000.00")
        )

        self.ticket = WeighTicket.objects.create(
            serial_number=SerialNumberService.allocate_serial_number(),
            status=TicketStatus.WAITING_SECOND,
            weight_mode=WeightMode.EMPTY_FIRST,
            product=self.product,
            party=self.party,
            vehicle=self.vehicle,
            license_plate_display="56 س 123 - ایران 88",
            first_weight=Decimal("14000.00"),
            first_weight_date=date(2026, 10, 15),
            first_weight_time=time(9, 0),
            first_weight_operator=self.operator,
            sent_weight=Decimal("20000.00"),
        )

    # 15. Second weight view blocks when approval required and non-approved
    def test_15_second_weight_blocks_unauthorized_discrepancy(self):
        rule_cfg = MonitoringRuleConfig.get_rule_config(AlertType.WEIGHT_DISCREPANCY)
        rule_cfg.requires_approval = True
        rule_cfg.save()

        self.client.force_login(self.operator)
        resp = self.client.post(
            f"/weighbridge/tickets/{self.ticket.id}/second-weight/",
            {
                "second_weight": "34500",  # Net: 20500, diff: +500 kg > 50 kg
                "sent_weight": "20000",
                "loss_percent": "0",
                "submit_action": "save",
            }
        )
        self.assertEqual(resp.status_code, 200)  # Re-rendered form with error
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.WAITING_SECOND)  # NOT COMPLETED
        self.assertContains(resp, "عدم امکان تکمیل خودکار قبض")

    # 16. Second weight view completes when supervisor approval exists
    def test_16_second_weight_completes_when_approved(self):
        rule_cfg = MonitoringRuleConfig.get_rule_config(AlertType.WEIGHT_DISCREPANCY)
        rule_cfg.requires_approval = True
        rule_cfg.save()

        # Create approved discrepancy request
        appr = DiscrepancyApprovalService.request_approval(
            ticket=self.ticket,
            user=self.operator,
            reason="مغایرت اضافه بار بر اساس نامه کتبی سرپرست کارگاه",
            gross=Decimal("34500.00"),
            tare=Decimal("14000.00"),
            net=Decimal("20500.00"),
        )
        DiscrepancyApprovalService.decide_approval(
            approval_id=appr.id,
            supervisor_user=self.supervisor,
            decision="approve",
            decision_reason="نامه اضافه بار بررسی و مجاز دانسته شد"
        )

        self.client.force_login(self.operator)
        resp = self.client.post(
            f"/weighbridge/tickets/{self.ticket.id}/second-weight/",
            {
                "second_weight": "34500",
                "sent_weight": "20000",
                "loss_percent": "0",
                "submit_action": "save",
            }
        )
        self.assertEqual(resp.status_code, 302)  # Successfully redirected
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.COMPLETED)
        self.assertEqual(self.ticket.net_weight, Decimal("20500.00"))

    # 17. Supervisor dashboard view and decision endpoint
    def test_17_supervisor_dashboard_and_decision_endpoint(self):
        appr = DiscrepancyApprovalService.request_approval(
            ticket=self.ticket,
            user=self.operator,
            reason="درخواست تست جهت داشبورد سرپرست",
            gross=Decimal("34500.00"),
            tare=Decimal("14000.00"),
            net=Decimal("20500.00"),
        )

        self.client.force_login(self.supervisor)
        # 1. View dashboard
        dash_resp = self.client.get("/monitoring/approvals/")
        self.assertEqual(dash_resp.status_code, 200)
        self.assertContains(dash_resp, "کارتابل بررسی و مجوزهای مغایرت سرپرست")
        self.assertContains(dash_resp, self.ticket.serial_number)

        # 2. POST decision to approve
        dec_resp = self.client.post(
            f"/monitoring/approvals/{appr.id}/decision/",
            {
                "decision": "approve",
                "decision_reason": "مجوز با موفقیت توسط سرپرست تأیید گردید",
            }
        )
        self.assertEqual(dec_resp.status_code, 302)
        appr.refresh_from_db()
        self.assertEqual(appr.status, ApprovalStatus.APPROVED)
        self.assertEqual(appr.reviewed_by, self.supervisor)
