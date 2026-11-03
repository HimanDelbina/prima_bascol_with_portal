from decimal import Decimal
from datetime import date, time
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient
from rest_framework import status

from weighbridge.models import WeighTicket, TicketStatus, WeightMode
from masterdata.models import Product, Party, Vehicle, VehicleType, Driver, OperationType
from monitoring.models import (
    MonitoringAlert, MonitoringRuleConfig, AlertType, AlertSeverity,
    AlertStatus, ApprovalStatus, DiscrepancyApproval
)
from monitoring.services.discrepancy_service import DiscrepancyApprovalService
from weighbridge.services import TicketCalculationService, SerialNumberService
from weighbridge.admin import WeighTicketAdmin
from django.contrib.admin.sites import AdminSite


class MockRequest:
    def __init__(self, user):
        self.user = user


class DiscrepancyApprovalSecurityHotfixesTests(TestCase):
    def setUp(self):
        # Users
        self.superadmin = User.objects.create_superuser(
            username="superadmin_sec",
            password="password123",
            email="superadmin_sec@example.com"
        )
        self.supervisor = User.objects.create_user(
            username="supervisor_sec",
            password="password123",
            first_name="سرپرست",
            last_name="باسکول"
        )
        self.supervisor.profile.role = "weighbridge_manager"
        self.supervisor.profile.save()

        self.operator = User.objects.create_user(
            username="operator_sec",
            password="password123",
            first_name="اپراتور",
            last_name="اول"
        )
        self.operator.profile.role = "weighbridge_operator"
        self.operator.profile.save()

        # Master Data
        self.product = Product.objects.create(
            name="کنسانتره آهن",
            code="FE-CONC",
            standard_tolerance_kg=Decimal("100.00"),
            default_loss_percent=Decimal("0.00")
        )
        self.other_product = Product.objects.create(
            name="گندله سنگ آهن",
            code="FE-PELLET",
            standard_tolerance_kg=Decimal("200.00")
        )
        self.party = Party.objects.create(name="شرکت معدنی چادرملو", code="CHAD-01")
        self.v_type = VehicleType.objects.create(name="تریلی کمپرسی")
        self.driver = Driver.objects.create(full_name="حمید قادری", mobile="09131234567")
        self.vehicle = Vehicle.objects.create(
            plate_display="45 ع 123 - ایران 22",
            vehicle_type=self.v_type,
            empty_weight=Decimal("15000.00")
        )
        self.op_type = OperationType.objects.create(name="ورود مواد اولیه", direction="inbound")

        # Monitoring Rule Config: Enforce approval on tolerance breach
        self.rule_config = MonitoringRuleConfig.get_rule_config(AlertType.WEIGHT_DISCREPANCY)
        self.rule_config.requires_approval = True
        self.rule_config.warning_threshold = Decimal("50.00")
        self.rule_config.critical_threshold = Decimal("100.00")
        self.rule_config.enabled = True
        self.rule_config.save()

        self.api_client = APIClient()

    # 1. API: Direct create with blocking discrepancy without approval must be blocked
    def test_api_create_direct_complete_blocked_without_approval(self):
        self.api_client.force_authenticate(user=self.operator)
        payload = {
            "license_plate_display": "45 ع 123 - ایران 22",
            "product": self.product.id,
            "party": self.party.id,
            "operation_type": self.op_type.id,
            "vehicle": self.vehicle.id,
            "driver": self.driver.id,
            "first_weight": 15000,
            "second_weight": 40000,  # Net = 25000
            "sent_weight": 20000,    # Diff = 5000 > 100 kg tolerance!
        }
        res = self.api_client.post("/api/v1/tickets/", payload)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "DISCREPANCY_APPROVAL_REQUIRED")

    # 2. API: Second weight with blocking discrepancy without approval must be blocked
    def test_api_second_weight_blocked_without_approval(self):
        ticket = WeighTicket.objects.create(
            serial_number=SerialNumberService.allocate_serial_number(),
            status=TicketStatus.WAITING_SECOND,
            weight_mode=WeightMode.EMPTY_FIRST,
            product=self.product,
            party=self.party,
            vehicle=self.vehicle,
            driver=self.driver,
            license_plate_display="45 ع 123 - ایران 22",
            first_weight=Decimal("15000.00"),
            first_weight_date=date.today(),
            first_weight_time=time(9, 0),
            first_weight_operator=self.operator,
            sent_weight=Decimal("20000.00"),
        )
        self.api_client.force_authenticate(user=self.operator)
        payload = {
            "weight": 40000,  # Net = 25000, diff = 5000 kg > 100 kg tolerance
        }
        res = self.api_client.post(f"/api/v1/tickets/{ticket.id}/second-weight/", payload)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "DISCREPANCY_APPROVAL_REQUIRED")

        # Ticket must remain in WAITING_SECOND
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.WAITING_SECOND)

    # 3. API: Complete ticket blocked when blocking discrepancy exists
    def test_api_complete_ticket_blocked_without_approval(self):
        ticket = WeighTicket.objects.create(
            serial_number=SerialNumberService.allocate_serial_number(),
            status=TicketStatus.WAITING_SECOND,
            weight_mode=WeightMode.EMPTY_FIRST,
            product=self.product,
            party=self.party,
            vehicle=self.vehicle,
            driver=self.driver,
            license_plate_display="45 ع 123 - ایران 22",
            first_weight=Decimal("15000.00"),
            second_weight=Decimal("40000.00"),
            sent_weight=Decimal("20000.00"),
            first_weight_date=date.today(),
            second_weight_date=date.today(),
            first_weight_operator=self.operator,
        )
        self.api_client.force_authenticate(user=self.operator)
        res = self.api_client.post(f"/api/v1/tickets/{ticket.id}/complete/", {"notes": "اتمام"})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "DISCREPANCY_APPROVAL_REQUIRED")

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.WAITING_SECOND)

    # 4. API: Ticket correction invalidates stale approval and demotes COMPLETED ticket
    def test_api_ticket_correct_invalidates_stale_and_demotes_completed(self):
        calc = TicketCalculationService.calculate_ticket(
            first_weight=Decimal("15000.00"),
            second_weight=Decimal("40000.00"),
            sent_weight=Decimal("20000.00"),
            product=self.product
        )
        ticket = WeighTicket.objects.create(
            serial_number=SerialNumberService.allocate_serial_number(),
            status=TicketStatus.WAITING_SECOND,
            product=self.product,
            party=self.party,
            vehicle=self.vehicle,
            driver=self.driver,
            license_plate_display="45 ع 123 - ایران 22",
            first_weight=Decimal("15000.00"),
            second_weight=Decimal("40000.00"),
            gross_weight=calc["gross_weight"],
            tare_weight=calc["tare_weight"],
            net_weight=calc["net_weight"],
            final_weight=calc["final_weight"],
            sent_weight=Decimal("20000.00"),
            weight_difference=calc["weight_difference"],
            weight_difference_percent=calc["weight_difference_percent"],
            is_tolerance_exceeded=calc["is_tolerance_exceeded"],
            first_weight_date=date.today(),
            second_weight_date=date.today(),
            first_weight_operator=self.operator,
        )
        app_req = DiscrepancyApprovalService.request_approval(
            ticket=ticket,
            user=self.operator,
            reason="اختلاف بار ۵ تن ناشی از خطای اعلام بار",
            gross=calc["gross_weight"],
            tare=calc["tare_weight"],
            net=calc["net_weight"],
            product=self.product,
            sent_weight=Decimal("20000.00"),
        )
        DiscrepancyApprovalService.decide_approval(
            approval_id=app_req.id,
            supervisor_user=self.supervisor,
            decision="approve",
            decision_reason="موافقت با ترخیص بار"
        )
        ticket.status = TicketStatus.COMPLETED
        ticket.save()

        # Manager corrects weight via API
        self.api_client.force_authenticate(user=self.supervisor)
        res = self.api_client.post(f"/api/v1/tickets/{ticket.id}/correct/", {
            "field": "second_weight",
            "new_value": "42000",
            "reason": "اصلاح وزن دوم توسط مدیر"
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Verify approval is now CANCELLED (stale)
        app_req.refresh_from_db()
        self.assertEqual(app_req.status, ApprovalStatus.CANCELLED)
        self.assertIn("ابطال خودکار به دلیل تغییر مقادیر", app_req.decision_reason)

        # Verify ticket was demoted from COMPLETED to WAITING_SECOND
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.WAITING_SECOND)

    # 5. Separation of duties: Requester cannot self-approve, even if superuser
    def test_strict_separation_of_duties_prohibits_self_approval(self):
        calc = TicketCalculationService.calculate_ticket(
            first_weight=Decimal("15000.00"),
            second_weight=Decimal("40000.00"),
            sent_weight=Decimal("20000.00"),
            product=self.product
        )
        ticket = WeighTicket.objects.create(
            serial_number=SerialNumberService.allocate_serial_number(),
            status=TicketStatus.WAITING_SECOND,
            product=self.product,
            party=self.party,
            vehicle=self.vehicle,
            driver=self.driver,
            license_plate_display="45 ع 123 - ایران 22",
            first_weight=Decimal("15000.00"),
            second_weight=Decimal("40000.00"),
            gross_weight=calc["gross_weight"],
            tare_weight=calc["tare_weight"],
            net_weight=calc["net_weight"],
            final_weight=calc["final_weight"],
            sent_weight=Decimal("20000.00"),
            first_weight_date=date.today(),
            first_weight_operator=self.superadmin,
        )
        app_req = DiscrepancyApprovalService.request_approval(
            ticket=ticket,
            user=self.superadmin,
            reason="درخواست توسط سوپرادمین",
            gross=calc["gross_weight"],
            tare=calc["tare_weight"],
            net=calc["net_weight"],
            product=self.product,
            sent_weight=Decimal("20000.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            DiscrepancyApprovalService.decide_approval(
                approval_id=app_req.id,
                supervisor_user=self.superadmin,
                decision="approve",
                decision_reason="تأیید خودم"
            )
        self.assertIn("تفکیک وظایف", str(ctx.exception))

    # 6. Cannot request approval on closed (completed or cancelled) tickets
    def test_request_approval_rejected_on_closed_ticket(self):
        ticket = WeighTicket.objects.create(
            serial_number=SerialNumberService.allocate_serial_number(),
            status=TicketStatus.COMPLETED,
            product=self.product,
            party=self.party,
            vehicle=self.vehicle,
            driver=self.driver,
            license_plate_display="45 ع 123 - ایران 22",
            first_weight=Decimal("15000.00"),
            second_weight=Decimal("40000.00"),
            gross_weight=Decimal("40000.00"),
            tare_weight=Decimal("15000.00"),
            net_weight=Decimal("25000.00"),
            final_weight=Decimal("25000.00"),
            sent_weight=Decimal("20000.00"),
            first_weight_date=date.today(),
            first_weight_operator=self.operator,
        )
        with self.assertRaises(ValidationError) as ctx:
            DiscrepancyApprovalService.request_approval(
                ticket=ticket,
                user=self.operator,
                reason="تلاش روی قبض بسته"
            )
        self.assertIn("امکان ثبت درخواست تأیید مغایرت برای قبض", str(ctx.exception))

    # 7. Fail-closed on missing snapshots (legacy records)
    def test_missing_snapshots_fail_closed(self):
        approval = DiscrepancyApproval.objects.create(
            ticket=WeighTicket.objects.create(
                serial_number=SerialNumberService.allocate_serial_number(),
                status=TicketStatus.WAITING_SECOND,
                license_plate_display="45 ع 123 - ایران 22",
                first_weight=Decimal("10000"),
                first_weight_date=date.today()
            ),
            discrepancy_type=AlertType.WEIGHT_DISCREPANCY,
            requested_by=self.operator,
            request_reason="دلیل تست سوابق قدیمی",
            status=ApprovalStatus.APPROVED,
            gross_weight_snapshot=None,  # Legacy missing snapshot
            tare_weight_snapshot=None,
            net_weight_snapshot=None,
        )
        self.assertFalse(approval.are_parameters_matching(Decimal("30000"), Decimal("10000"), Decimal("20000")))

    # 8. Product mismatch invalidates approval
    def test_product_mismatch_invalidates_approval(self):
        calc = TicketCalculationService.calculate_ticket(
            first_weight=Decimal("15000.00"),
            second_weight=Decimal("40000.00"),
            sent_weight=Decimal("20000.00"),
            product=self.product
        )
        ticket = WeighTicket.objects.create(
            serial_number=SerialNumberService.allocate_serial_number(),
            status=TicketStatus.WAITING_SECOND,
            product=self.product,
            party=self.party,
            vehicle=self.vehicle,
            driver=self.driver,
            license_plate_display="45 ع 123 - ایران 22",
            first_weight=Decimal("15000.00"),
            second_weight=Decimal("40000.00"),
            gross_weight=calc["gross_weight"],
            tare_weight=calc["tare_weight"],
            net_weight=calc["net_weight"],
            final_weight=calc["final_weight"],
            sent_weight=Decimal("20000.00"),
            first_weight_date=date.today(),
            first_weight_operator=self.operator,
        )
        app_req = DiscrepancyApprovalService.request_approval(
            ticket=ticket,
            user=self.operator,
            reason="مغایرت تناژ بارنامه",
            gross=calc["gross_weight"],
            tare=calc["tare_weight"],
            net=calc["net_weight"],
            product=self.product,
            sent_weight=Decimal("20000.00"),
        )
        DiscrepancyApprovalService.decide_approval(
            approval_id=app_req.id,
            supervisor_user=self.supervisor,
            decision="approve",
            decision_reason="تأیید شد"
        )

        # Matching with same product
        self.assertTrue(app_req.are_parameters_matching(
            ticket.gross_weight, ticket.tare_weight, ticket.net_weight,
            product=self.product, sent_weight=Decimal("20000.00")
        ))

        # Mismatch when product is swapped
        self.assertFalse(app_req.are_parameters_matching(
            ticket.gross_weight, ticket.tare_weight, ticket.net_weight,
            product=self.other_product, sent_weight=Decimal("20000.00")
        ))

        # Run check_and_invalidate_stale_approvals
        inval = DiscrepancyApprovalService.check_and_invalidate_stale_approvals(
            ticket,
            ticket.gross_weight, ticket.tare_weight, ticket.net_weight,
            current_product=self.other_product,
            current_sent_weight=Decimal("20000.00")
        )
        self.assertEqual(inval, 1)
        app_req.refresh_from_db()
        self.assertEqual(app_req.status, ApprovalStatus.CANCELLED)
        self.assertIn("ابطال خودکار به دلیل تغییر مقادیر", app_req.decision_reason)

    # 9. Django Admin save_model validation against unapproved discrepancies
    def test_admin_save_model_blocks_unapproved_completion(self):
        admin_site = AdminSite()
        ticket_admin = WeighTicketAdmin(WeighTicket, admin_site)

        ticket = WeighTicket(
            serial_number=SerialNumberService.allocate_serial_number(),
            status=TicketStatus.COMPLETED,
            product=self.product,
            party=self.party,
            vehicle=self.vehicle,
            driver=self.driver,
            license_plate_display="45 ع 123 - ایران 22",
            first_weight=Decimal("15000.00"),
            second_weight=Decimal("40000.00"),
            sent_weight=Decimal("20000.00"),
            first_weight_date=date.today(),
            first_weight_operator=self.operator,
        )
        req = MockRequest(user=self.superadmin)
        with self.assertRaises(ValidationError) as ctx:
            ticket_admin.save_model(req, ticket, form=None, change=False)
        self.assertIn("مغایرت تاییدنشده", str(ctx.exception))

    # 10. Django Admin readonly protection and no physical delete
    def test_admin_readonly_and_no_delete(self):
        admin_site = AdminSite()
        ticket_admin = WeighTicketAdmin(WeighTicket, admin_site)

        self.assertFalse(ticket_admin.has_delete_permission(MockRequest(self.superadmin)))

        completed_ticket = WeighTicket.objects.create(
            serial_number=SerialNumberService.allocate_serial_number(),
            status=TicketStatus.COMPLETED,
            license_plate_display="45 ع 123 - ایران 22",
            first_weight=Decimal("10000"),
            first_weight_date=date.today()
        )
        ro_fields = ticket_admin.get_readonly_fields(MockRequest(self.operator), completed_ticket)
        self.assertIn("first_weight", ro_fields)
        self.assertIn("product", ro_fields)
        self.assertIn("status", ro_fields)

    # 11. Ticket Print Draft Watermark when unapproved discrepancy exists
    def test_ticket_print_draft_watermark_on_unapproved(self):
        client = Client()
        client.force_login(self.operator)

        ticket = WeighTicket.objects.create(
            serial_number=SerialNumberService.allocate_serial_number(),
            status=TicketStatus.WAITING_SECOND,
            product=self.product,
            party=self.party,
            vehicle=self.vehicle,
            driver=self.driver,
            license_plate_display="45 ع 123 - ایران 22",
            first_weight=Decimal("15000.00"),
            second_weight=Decimal("40000.00"),
            gross_weight=Decimal("40000.00"),
            tare_weight=Decimal("15000.00"),
            net_weight=Decimal("25000.00"),
            final_weight=Decimal("25000.00"),
            sent_weight=Decimal("20000.00"),
            first_weight_date=date.today(),
            second_weight_date=date.today(),
            first_weight_operator=self.operator,
        )

        res = client.get(f"/weighbridge/tickets/{ticket.id}/print/?format=a4")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.context["is_draft"])
        self.assertContains(res, "فاقد اعتبار جهت ترخیص کالا")
        self.assertContains(res, "watermark")

    # 12. Query count verification for trucks_in_yard (prefetch discrepancy_approvals)
    def test_trucks_in_yard_query_count_constant(self):
        client = Client()
        client.force_login(self.operator)

        for i in range(5):
            WeighTicket.objects.create(
                serial_number=SerialNumberService.allocate_serial_number(),
                status=TicketStatus.WAITING_SECOND,
                license_plate_display=f"11 ع {100 + i} - ایران 11",
                first_weight=Decimal("12000.00"),
                first_weight_date=date.today(),
                first_weight_time=time(8, i),
                first_weight_operator=self.operator,
            )

        # Warm up request (session, auth and user profile caching)
        client.get("/weighbridge/trucks-in-yard/")

        with CaptureQueriesContext(connection) as ctx5:
            res5 = client.get("/weighbridge/trucks-in-yard/")
            self.assertEqual(res5.status_code, 200)
        count_5 = len(ctx5.captured_queries)

        for i in range(5, 15):
            WeighTicket.objects.create(
                serial_number=SerialNumberService.allocate_serial_number(),
                status=TicketStatus.WAITING_SECOND,
                license_plate_display=f"11 ع {100 + i} - ایران 11",
                first_weight=Decimal("12000.00"),
                first_weight_date=date.today(),
                first_weight_time=time(8, i),
                first_weight_operator=self.operator,
            )

        with CaptureQueriesContext(connection) as ctx15:
            res15 = client.get("/weighbridge/trucks-in-yard/")
            self.assertEqual(res15.status_code, 200)
        count_15 = len(ctx15.captured_queries)

        self.assertEqual(count_5, count_15)
