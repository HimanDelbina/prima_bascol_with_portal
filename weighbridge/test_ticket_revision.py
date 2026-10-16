import json
from decimal import Decimal
from datetime import timedelta
import io
import openpyxl

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import IntegrityError
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile, RoleChoices
from audit.models import AuditLog, AuditAction
from masterdata.models import Product, Party, Driver, Vehicle, VehicleType, OperationType, Location, UnloadLocation
from weighbridge.models import WeighTicket, TicketStatus, WeightMode, TicketRevision
from weighbridge.revision_service import TicketRevisionService
from management.kpi_service import OperationalKPIService
from reports.exports import export_revision_reconciliation_excel


class TicketRevisionBaseTestCase(TestCase):
    def setUp(self):
        self.client = Client()

        # Users and roles
        self.operator = User.objects.create_user(
            username="op_user", password="password123", first_name="رضا", last_name="صالحی"
        )
        self.op_profile = self.operator.profile
        self.op_profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        self.op_profile.save()

        self.supervisor = User.objects.create_user(
            username="sup_user", password="password123", first_name="احمد", last_name="کریمی"
        )
        self.sup_profile = self.supervisor.profile
        self.sup_profile.role = RoleChoices.WEIGHBRIDGE_MANAGER
        self.sup_profile.save()

        self.other_supervisor = User.objects.create_user(
            username="sup_user2", password="password123", first_name="محسن", last_name="رضایی"
        )
        self.sup_profile2 = self.other_supervisor.profile
        self.sup_profile2.role = RoleChoices.WEIGHBRIDGE_MANAGER
        self.sup_profile2.save()

        self.superuser = User.objects.create_superuser(
            username="admin_user", password="password123", email="admin@example.com"
        )

        # Master Data
        self.product_iron = Product.objects.create(name="میلگرد ۱۶", code="P-201", is_active=True)
        self.product_scrap = Product.objects.create(name="ضایعات مس", code="P-202", is_active=True)
        self.party_a = Party.objects.create(name="شرکت فولاد اکسین", code="C-101", is_active=True)
        self.party_b = Party.objects.create(name="مجتمع فولاد اهواز", code="C-102", is_active=True)
        self.driver = Driver.objects.create(full_name="علی رستمی", mobile="09121112233", is_active=True)
        self.vehicle_type = VehicleType.objects.create(name="تریلی کفی", standard_tare_weight=Decimal("14000.00"))
        self.vehicle = Vehicle.objects.create(plate_display="12ع345-Iran78", vehicle_type=self.vehicle_type)
        self.op_type = OperationType.objects.create(name="فروش تجاری", direction="outbound", is_active=True)
        self.origin = Location.objects.create(name="مبدأ تهران", is_active=True)
        self.destination = Location.objects.create(name="مقصد اصفهان", is_active=True)
        self.unload_location = UnloadLocation.objects.create(name="انبار مرکزی", is_active=True)

        now = timezone.now()

        # Completed ticket baseline
        self.ticket = WeighTicket.objects.create(
            serial_number="WB-1001",
            operation_type=self.op_type,
            party=self.party_a,
            product=self.product_iron,
            vehicle=self.vehicle,
            driver=self.driver,
            origin=self.origin,
            destination=self.destination,
            unload_location=self.unload_location,
            license_plate_display="12ع345-Iran78",
            gross_weight=Decimal("38500.00"),
            tare_weight=Decimal("14200.00"),
            net_weight=Decimal("24300.00"),
            final_weight=Decimal("24300.00"),
            original_net_weight=Decimal("24300.00"),
            current_revision_number=0,
            status=TicketStatus.COMPLETED,
            weight_mode=WeightMode.EMPTY_FIRST,
            first_weight=Decimal("14200.00"),
            first_weight_date=now.date(),
            first_weight_time=(now - timedelta(hours=2)).time(),
            first_weight_operator=self.operator,
            second_weight=Decimal("38500.00"),
            second_weight_date=now.date(),
            second_weight_time=(now - timedelta(hours=1)).time(),
            second_weight_operator=self.operator,
            waybill_number="WB-8899",
            sent_weight=Decimal("24350.00"),
            weight_difference=Decimal("-50.00"),
            weight_difference_percent=Decimal("-0.21"),
            loss_percent=Decimal("0.00"),
            loss_weight=Decimal("0.00"),
            freight_amount=Decimal("15000000"),
        )


class TicketRevisionModelTests(TicketRevisionBaseTestCase):
    def test_revision_creation_and_properties(self):
        revision = TicketRevision.objects.create(
            ticket=self.ticket,
            ticket_current_revision_at_request=0,
            status=TicketRevision.RevisionStatus.PENDING,
            before_snapshot={"net_weight": "24300.00", "gross_weight": "38500.00"},
            after_snapshot={"net_weight": "25000.00", "gross_weight": "39200.00"},
            changed_fields=["gross_weight", "net_weight"],
            reason="خطای کاربر در ثبت اولیه باسکول دوم",
            requested_by=self.operator,
        )

        self.assertTrue(revision.is_pending)
        self.assertFalse(revision.is_applied)
        self.assertIn(f"بازنگری قبض {self.ticket.serial_number}", str(revision))
        self.assertIsNotNone(revision.jalali_requested_at)

    def test_unique_pending_revision_constraint(self):
        TicketRevision.objects.create(
            ticket=self.ticket,
            ticket_current_revision_at_request=0,
            status=TicketRevision.RevisionStatus.PENDING,
            before_snapshot={"net_weight": "24300.00"},
            after_snapshot={"net_weight": "25000.00"},
            changed_fields=["net_weight"],
            reason="درخواست اصلاح اول",
            requested_by=self.operator,
        )

        with self.assertRaises(IntegrityError):
            TicketRevision.objects.create(
                ticket=self.ticket,
                ticket_current_revision_at_request=0,
                status=TicketRevision.RevisionStatus.PENDING,
                before_snapshot={"net_weight": "24300.00"},
                after_snapshot={"net_weight": "25200.00"},
                changed_fields=["net_weight"],
                reason="درخواست اصلاح دوم همزمان",
                requested_by=self.supervisor,
            )

    def test_unique_applied_revision_number_constraint(self):
        TicketRevision.objects.create(
            ticket=self.ticket,
            revision_number=1,
            ticket_current_revision_at_request=0,
            status=TicketRevision.RevisionStatus.APPLIED,
            before_snapshot={"net_weight": "24300.00"},
            after_snapshot={"net_weight": "25000.00"},
            changed_fields=["net_weight"],
            reason="اصلاح اول اعمال شد",
            requested_by=self.operator,
            reviewed_by=self.supervisor,
            applied_by=self.supervisor,
            applied_at=timezone.now(),
        )

        with self.assertRaises(IntegrityError):
            TicketRevision.objects.create(
                ticket=self.ticket,
                revision_number=1,  # Duplicate revision_number 1
                ticket_current_revision_at_request=1,
                status=TicketRevision.RevisionStatus.APPLIED,
                before_snapshot={"net_weight": "25000.00"},
                after_snapshot={"net_weight": "25500.00"},
                changed_fields=["net_weight"],
                reason="اصلاح دوم اعمال نشدنی با شماره تکراری",
                requested_by=self.operator,
                reviewed_by=self.supervisor,
                applied_by=self.supervisor,
                applied_at=timezone.now(),
            )


class TicketRevisionServiceTests(TicketRevisionBaseTestCase):
    def test_request_revision_success(self):
        proposed_data = {
            "gross_weight": Decimal("39000.00"),
            "tare_weight": Decimal("14200.00"),
            "reason": "اشتباه اپراتور در خواندن نشان‌دهنده باسکول",
        }

        rev = TicketRevisionService.request_revision(
            ticket=self.ticket,
            proposed_data=proposed_data,
            requested_by=self.operator,
            reason="اشتباه اپراتور در خواندن نشان‌دهنده باسکول",
        )

        self.assertIsNotNone(rev.id)
        self.assertEqual(rev.status, TicketRevision.RevisionStatus.PENDING)
        self.assertEqual(rev.ticket_current_revision_at_request, 0)
        self.assertIn("gross_weight", rev.changed_fields)
        self.assertIn("net_weight", rev.changed_fields)
        self.assertEqual(Decimal(rev.after_snapshot["net_weight"]), Decimal("24800.00"))

        # Check AuditLog was recorded
        audit = AuditLog.objects.filter(
            action=AuditAction.REVISION_REQUEST,
            model_name="WeighTicket",
            record_id=str(self.ticket.id),
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.user, self.operator)

    def test_request_revision_rejects_non_completed_tickets(self):
        in_progress_ticket = WeighTicket.objects.create(
            serial_number="WB-1002",
            status=TicketStatus.WAITING_SECOND,
            gross_weight=Decimal("30000.00"),
            first_weight=Decimal("30000.00"),
            license_plate_display="12ع345-Iran78",
        )

        with self.assertRaises(ValidationError) as ctx:
            TicketRevisionService.request_revision(
                ticket=in_progress_ticket,
                proposed_data={"gross_weight": Decimal("31000.00")},
                requested_by=self.operator,
                reason="تغییر وزن بار اول",
            )
        self.assertIn("تکمیل شده", str(ctx.exception))

    def test_request_revision_rejects_duplicate_pending(self):
        TicketRevisionService.request_revision(
            ticket=self.ticket,
            proposed_data={"gross_weight": Decimal("39000.00")},
            requested_by=self.operator,
            reason="درخواست اول",
        )

        with self.assertRaises(ValidationError) as ctx:
            TicketRevisionService.request_revision(
                ticket=self.ticket,
                proposed_data={"gross_weight": Decimal("39500.00")},
                requested_by=self.operator,
                reason="درخواست دوم همزمان",
            )
        self.assertIn("درخواست بازنگری در انتظار", str(ctx.exception))

    def test_request_revision_rejects_immutable_fields(self):
        with self.assertRaises(ValidationError) as ctx:
            TicketRevisionService.request_revision(
                ticket=self.ticket,
                proposed_data={"serial_number": "WB-9999"},
                requested_by=self.operator,
                reason="تغییر شماره سریال غیرقانونی",
            )
        self.assertIn("غیرقابل", str(ctx.exception))

    def test_request_revision_validates_weights(self):
        # Gross weight less than tare weight
        with self.assertRaises(ValidationError) as ctx:
            TicketRevisionService.request_revision(
                ticket=self.ticket,
                proposed_data={
                    "gross_weight": Decimal("10000.00"),
                    "tare_weight": Decimal("14200.00"),
                },
                requested_by=self.operator,
                reason="وزن ناخالص کمتر از خالی",
            )
        self.assertIn("کمتر از وزن خالی", str(ctx.exception))

    def test_request_revision_rejects_no_changes(self):
        with self.assertRaises(ValidationError) as ctx:
            TicketRevisionService.request_revision(
                ticket=self.ticket,
                proposed_data={
                    "gross_weight": Decimal("38500.00"),
                    "tare_weight": Decimal("14200.00"),
                },
                requested_by=self.operator,
                reason="بدون تغییر مقادیر",
            )
        self.assertIn("هیچ تغییری", str(ctx.exception))

    def test_separation_of_duties_self_approval(self):
        # Operator requests revision
        rev = TicketRevisionService.request_revision(
            ticket=self.ticket,
            proposed_data={"gross_weight": Decimal("39000.00")},
            requested_by=self.operator,
            reason="درخواست اصلاح وزن توسط اپراتور",
        )

        # Operator tries to approve their own request
        with self.assertRaises((ValidationError, PermissionDenied)) as ctx:
            TicketRevisionService.approve_revision(
                revision=rev,
                reviewer=self.operator,
                decision_notes="خودم تأیید می‌کنم",
            )
        self.assertIn("تفکیک وظایف", str(ctx.exception))

    def test_approve_and_apply_revision_success(self):
        rev = TicketRevisionService.request_revision(
            ticket=self.ticket,
            proposed_data={
                "gross_weight": Decimal("39000.00"),
                "tare_weight": Decimal("14200.00"),
                "product": self.product_scrap.id,
            },
            requested_by=self.operator,
            reason="اصلاح نوع کالا و وزن ناخالص",
        )

        # Supervisor approves and automatically applies
        approved_rev = TicketRevisionService.approve_revision(
            revision=rev,
            reviewer=self.supervisor,
            decision_notes="مورد بررسی قرار گرفت و با باسکول مجدد تطابق دارد",
            auto_apply=True,
        )

        self.assertEqual(approved_rev.status, TicketRevision.RevisionStatus.APPLIED)
        self.assertEqual(approved_rev.revision_number, 1)
        self.assertEqual(approved_rev.reviewed_by, self.supervisor)
        self.assertEqual(approved_rev.applied_by, self.supervisor)

        # Refresh ticket from database
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.current_revision_number, 1)
        self.assertTrue(self.ticket.has_revisions)
        self.assertEqual(self.ticket.gross_weight, Decimal("39000.00"))
        self.assertEqual(self.ticket.net_weight, Decimal("24800.00"))
        self.assertEqual(self.ticket.product, self.product_scrap)

        # STRICT CHECK: Ticket status must REMAIN COMPLETED! Never WAITING_SECOND!
        self.assertEqual(self.ticket.status, TicketStatus.COMPLETED)

        # Original evidence preserved
        self.assertEqual(self.ticket.original_net_weight, Decimal("24300.00"))

        # AuditLog recorded
        apply_audit = AuditLog.objects.filter(
            action=AuditAction.REVISION_APPLY,
            model_name="WeighTicket",
            record_id=str(self.ticket.id),
        ).first()
        self.assertIsNotNone(apply_audit)
        self.assertEqual(apply_audit.user, self.supervisor)

    def test_approve_rejects_stale_revision(self):
        # Request Rev A at revision 0
        rev_a = TicketRevisionService.request_revision(
            ticket=self.ticket,
            proposed_data={"gross_weight": Decimal("39000.00")},
            requested_by=self.operator,
            reason="درخواست اصلاح اول",
        )

        # Manually bump ticket current revision to simulate concurrent modification
        WeighTicket.objects.filter(id=self.ticket.id).update(current_revision_number=1)

        with self.assertRaises(ValidationError) as ctx:
            TicketRevisionService.approve_revision(
                revision=rev_a,
                reviewer=self.supervisor,
                decision_notes="تأیید درخواست منسوخ",
            )
        self.assertIn("منسوخ", str(ctx.exception))

    def test_reject_revision(self):
        rev = TicketRevisionService.request_revision(
            ticket=self.ticket,
            proposed_data={"gross_weight": Decimal("40000.00")},
            requested_by=self.operator,
            reason="درخواست اصلاح غیرواقعی",
        )

        rejected_rev = TicketRevisionService.reject_revision(
            revision=rev,
            reviewer=self.supervisor,
            decision_notes="مورد تأیید نیست، با برگ باسکول همخوانی ندارد",
        )

        self.assertEqual(rejected_rev.status, TicketRevision.RevisionStatus.REJECTED)
        self.assertEqual(rejected_rev.reviewed_by, self.supervisor)
        self.assertIn("مورد تأیید نیست", rejected_rev.review_notes)

        # Ticket must remain unchanged
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.current_revision_number, 0)
        self.assertEqual(self.ticket.gross_weight, Decimal("38500.00"))

        # Rejection AuditLog
        reject_audit = AuditLog.objects.filter(
            action=AuditAction.REVISION_REJECT,
            model_name="WeighTicket",
            record_id=str(self.ticket.id),
        ).first()
        self.assertIsNotNone(reject_audit)

    def test_withdraw_revision(self):
        rev = TicketRevisionService.request_revision(
            ticket=self.ticket,
            proposed_data={"gross_weight": Decimal("39000.00")},
            requested_by=self.operator,
            reason="ثبت اشتباه توسط خودم",
        )

        # Other operator cannot withdraw
        other_user = User.objects.create_user(username="other_op", password="password123")
        with self.assertRaises((ValidationError, PermissionDenied)):
            TicketRevisionService.withdraw_revision(
                revision=rev,
                user=other_user,
                notes="ابطال توسط فرد متفرقه",
            )

        # Original requester can withdraw
        withdrawn_rev = TicketRevisionService.withdraw_revision(
            revision=rev,
            user=self.operator,
            notes="انصراف از بازنگری",
        )
        self.assertEqual(withdrawn_rev.status, TicketRevision.RevisionStatus.WITHDRAWN)

        withdraw_audit = AuditLog.objects.filter(
            action=AuditAction.REVISION_WITHDRAW,
            model_name="WeighTicket",
            record_id=str(self.ticket.id),
        ).first()
        self.assertIsNotNone(withdraw_audit)


class EntryPointHardeningTests(TicketRevisionBaseTestCase):
    def test_admin_save_model_blocks_material_changes(self):
        from weighbridge.admin import WeighTicketAdmin
        from django.contrib.admin.sites import AdminSite

        site = AdminSite()
        admin = WeighTicketAdmin(WeighTicket, site)

        # Attempt to change gross_weight via admin on completed ticket
        self.ticket.gross_weight = Decimal("45000.00")

        # Fake request
        class MockRequest:
            user = self.superuser

        with self.assertRaises(ValidationError) as ctx:
            admin.save_model(MockRequest(), self.ticket, form=None, change=True)
        self.assertIn("ویرایش مستقیم فیلد", str(ctx.exception))
        self.assertIn("Ticket Revision", str(ctx.exception))

    def test_api_first_and_second_weight_blocked_on_completed_ticket(self):
        self.client.force_login(self.operator)

        # Try POST to first-weight on completed ticket
        res1 = self.client.post(
            f"/api/v1/tickets/{self.ticket.id}/first-weight/",
            data=json.dumps({"weight": 15000}),
            content_type="application/json",
        )
        self.assertEqual(res1.status_code, 400)
        self.assertEqual(res1.json().get("error", {}).get("code"), "TICKET_ALREADY_COMPLETED")

        # Try POST to second-weight on completed ticket
        res2 = self.client.post(
            f"/api/v1/tickets/{self.ticket.id}/second-weight/",
            data=json.dumps({"weight": 40000}),
            content_type="application/json",
        )
        self.assertEqual(res2.status_code, 400)
        self.assertEqual(res2.json().get("error", {}).get("code"), "TICKET_ALREADY_COMPLETED")

    def test_api_correct_ticket_routes_to_revision(self):
        self.client.force_login(self.supervisor)

        payload = {
            "field": "second_weight",
            "new_value": "39200.00",
            "reason": "درخواست اصلاحیه از طریق وب‌سرویس REST",
        }
        res = self.client.post(
            f"/api/v1/tickets/{self.ticket.id}/correct/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 202)
        resp_json = res.json()
        self.assertTrue(resp_json.get("success"))
        data = resp_json.get("data", {})
        self.assertIn("revision_id", data)

        # Verify revision created in DB
        rev_id = data["revision_id"]
        rev = TicketRevision.objects.get(id=rev_id)
        self.assertEqual(rev.status, TicketRevision.RevisionStatus.PENDING)
        self.assertEqual(rev.reason, "درخواست اصلاحیه از طریق وب‌سرویس REST")

    def test_api_revision_workflow_actions(self):
        self.client.force_login(self.supervisor)

        # 1. Request via REST API
        req_res = self.client.post(
            f"/api/v1/tickets/{self.ticket.id}/revisions/request/",
            data=json.dumps({
                "reason": "اصلاح خطای باسکول ورودی",
                "proposed_data": {
                    "gross_weight": "39100.00",
                },
            }),
            content_type="application/json",
        )
        self.assertEqual(req_res.status_code, 201)
        rev_id = req_res.json()["data"]["id"]

        # 2. List revisions
        list_res = self.client.get(f"/api/v1/tickets/{self.ticket.id}/revisions/")
        self.assertEqual(list_res.status_code, 200)
        self.assertEqual(len(list_res.json()["data"]), 1)

        # 3. Approve via other supervisor (separation of duties)
        self.client.force_login(self.other_supervisor)
        appr_res = self.client.post(
            f"/api/v1/tickets/revisions/{rev_id}/approve/",
            data=json.dumps({
                "review_reason": "تأیید شد و اعمال گردید",
            }),
            content_type="application/json",
        )
        self.assertEqual(appr_res.status_code, 200)
        self.assertEqual(appr_res.json()["data"]["status"], "APPLIED")
        self.assertEqual(appr_res.json()["data"]["revision_number"], 1)

    def test_web_ticket_edit_routes_to_revision_without_demoting_ticket(self):
        self.client.force_login(self.supervisor)

        url = reverse("weighbridge:ticket_edit", kwargs={"pk": self.ticket.pk})
        post_data = {
            "operation_type": self.op_type.id,
            "party": self.party_a.id,
            "product": self.product_iron.id,
            "vehicle": self.vehicle.id,
            "vehicle_type": self.vehicle_type.id,
            "driver": self.driver.id,
            "license_plate_display": "12ع345-Iran78",
            "driver_name_custom": "علی رستمی",
            "driver_mobile_custom": "09121112233",
            "origin": self.origin.id,
            "destination": self.destination.id,
            "unload_location": self.unload_location.id,
            "first_weight": "14200",
            "second_weight": "39500",
            "first_weight_date_jalali": "1405/01/01",
            "first_weight_time_str": "10:00",
            "manager_reason": "درخواست اصلاح وزن توسط فرم وب",
        }
        res = self.client.post(url, post_data)
        # Should redirect to ticket_detail
        self.assertRedirects(res, reverse("weighbridge:ticket_detail", kwargs={"pk": self.ticket.pk}))

        # Ticket must remain COMPLETED
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.COMPLETED)
        self.assertNotEqual(self.ticket.status, TicketStatus.WAITING_SECOND)

        # Pending revision was created
        pending = TicketRevision.objects.filter(ticket=self.ticket, status=TicketRevision.RevisionStatus.PENDING).first()
        self.assertIsNotNone(pending)
        self.assertEqual(pending.reason, "درخواست اصلاح وزن توسط فرم وب")


class YardAndKPIConsistencyTests(TicketRevisionBaseTestCase):
    def test_completed_ticket_never_in_yard(self):
        from weighbridge.views import trucks_in_yard

        # Trucks in yard query
        in_yard = WeighTicket.objects.filter(status=TicketStatus.WAITING_SECOND)
        self.assertNotIn(self.ticket, in_yard)

        # Request revision
        rev = TicketRevisionService.request_revision(
            ticket=self.ticket,
            proposed_data={"gross_weight": Decimal("39000.00")},
            requested_by=self.operator,
            reason="اصلاح ناخالص",
        )

        in_yard = WeighTicket.objects.filter(status=TicketStatus.WAITING_SECOND)
        self.assertNotIn(self.ticket, in_yard)

        # Approve and apply revision
        TicketRevisionService.approve_revision(
            revision=rev,
            reviewer=self.supervisor,
            decision_notes="تأیید شد",
            auto_apply=True,
        )

        in_yard = WeighTicket.objects.filter(status=TicketStatus.WAITING_SECOND)
        self.assertNotIn(self.ticket, in_yard)

    def test_kpi_service_uses_effective_corrected_tonnage(self):
        today = timezone.now().date()
        kpis_before = OperationalKPIService.calculate_period_kpis(start_date=today, end_date=today)
        self.assertEqual(kpis_before["completed_trips"], 1)
        self.assertEqual(kpis_before["net_kg_dec"], Decimal("24300.00"))

        # Apply revision increasing net weight by 500 kg
        rev = TicketRevisionService.request_revision(
            ticket=self.ticket,
            proposed_data={"gross_weight": Decimal("39000.00"), "tare_weight": Decimal("14200.00")},
            requested_by=self.operator,
            reason="افزایش ۵۰۰ کیلوگرمی به دلیل اصلاح وزن باسکول",
        )
        TicketRevisionService.approve_revision(
            revision=rev,
            reviewer=self.supervisor,
            decision_notes="تأیید شد",
            auto_apply=True,
        )

        # KPI after revision
        kpis_after = OperationalKPIService.calculate_period_kpis(start_date=today, end_date=today)
        self.assertEqual(kpis_after["completed_trips"], 1)
        # Should now reflect the corrected net weight (24,800 kg)
        self.assertEqual(kpis_after["net_kg_dec"], Decimal("24800.00"))
        self.assertEqual(kpis_after["net_ton_dec"], Decimal("24.80"))


class ReportingAndPrintingTests(TicketRevisionBaseTestCase):
    def test_excel_reconciliation_report(self):
        # Create an applied revision
        rev = TicketRevisionService.request_revision(
            ticket=self.ticket,
            proposed_data={"gross_weight": Decimal("39000.00"), "tare_weight": Decimal("14200.00")},
            requested_by=self.operator,
            reason="اصلاح وزن ناخالص",
        )
        TicketRevisionService.approve_revision(
            revision=rev,
            reviewer=self.supervisor,
            decision_notes="تأیید شد",
            auto_apply=True,
        )

        queryset = TicketRevision.objects.filter(status=TicketRevision.RevisionStatus.APPLIED)
        response = export_revision_reconciliation_excel(queryset)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        # Verify Excel content by reading back with openpyxl
        content = io.BytesIO(response.content)
        wb = openpyxl.load_workbook(content)
        ws = wb.active
        self.assertEqual(ws.title, "تطبیق بازنگری قبوض")

        # Verify header title
        self.assertIn("گزارش تطبیق و تعدیلات بازنگری قبوض", ws["A1"].value)

        # Check row 5 has the ticket data
        # Column 2 is ticket serial
        self.assertEqual(ws.cell(row=5, column=2).value, "WB-1001")
        # Column 3 is revision
        self.assertEqual(ws.cell(row=5, column=3).value, "Rev. 1")
        # Column 6 is original net weight (24300)
        self.assertEqual(ws.cell(row=5, column=6).value, 24300.0)
        # Column 7 is corrected net weight (24800)
        self.assertEqual(ws.cell(row=5, column=7).value, 24800.0)
        # Column 8 is diff (500)
        self.assertEqual(ws.cell(row=5, column=8).value, 500.0)

    def test_ticket_print_rev0_and_rev1(self):
        self.client.force_login(self.operator)

        # Rev 0 print
        res_a4_rev0 = self.client.get(reverse("weighbridge:ticket_print", kwargs={"pk": self.ticket.pk}) + "?template=a4")
        self.assertEqual(res_a4_rev0.status_code, 200)
        self.assertContains(res_a4_rev0, "Rev. 0")
        self.assertNotContains(res_a4_rev0, "SUPERSEDED")

        # Apply revision
        rev = TicketRevisionService.request_revision(
            ticket=self.ticket,
            proposed_data={"gross_weight": Decimal("39000.00"), "tare_weight": Decimal("14200.00")},
            requested_by=self.operator,
            reason="اصلاح وزن ناخالص",
        )
        TicketRevisionService.approve_revision(
            revision=rev,
            reviewer=self.supervisor,
            decision_notes="تأیید شد",
            auto_apply=True,
        )

        # Rev 1 print A4
        res_a4_rev1 = self.client.get(reverse("weighbridge:ticket_print", kwargs={"pk": self.ticket.pk}) + "?template=a4")
        self.assertEqual(res_a4_rev1.status_code, 200)
        self.assertContains(res_a4_rev1, "Rev. 1")
        self.assertContains(res_a4_rev1, "قبض اصلاح‌شده")
        self.assertContains(res_a4_rev1, "احمد کریمی")

        # Rev 1 print A5
        res_a5_rev1 = self.client.get(reverse("weighbridge:ticket_print", kwargs={"pk": self.ticket.pk}) + "?template=a5")
        self.assertEqual(res_a5_rev1.status_code, 200)
        self.assertContains(res_a5_rev1, "Rev. 1")

        # Rev 1 print POS
        res_pos_rev1 = self.client.get(reverse("weighbridge:ticket_print", kwargs={"pk": self.ticket.pk}) + "?template=pos")
        self.assertEqual(res_pos_rev1.status_code, 200)
        self.assertContains(res_pos_rev1, "Rev. 1")
