from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from decimal import Decimal

from weighbridge.models import WeighTicket, TicketStatus
from masterdata.models import Product, Party, Driver, Vehicle, VehicleType, OperationType, LossType
from accounts.models import RoleChoices
from audit.models import AuditLog


class TicketAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Users
        self.operator = User.objects.create_user(username="operator1", password="password")
        self.operator.profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        self.operator.profile.save()

        self.manager = User.objects.create_user(username="manager1", password="password")
        self.manager.profile.role = RoleChoices.WEIGHBRIDGE_MANAGER
        self.manager.profile.save()

        # Master Data
        self.product = Product.objects.create(name="سنگ آهن دانه‌بندی", code="IR-01", standard_tolerance_kg=Decimal("100.00"))
        self.party = Party.objects.create(name="شرکت فولاد مبارکه", code="FO-101")
        self.op_type = OperationType.objects.create(name="خرید داخلی", direction="inbound")
        self.v_type = VehicleType.objects.create(name="تریلی کمپرسی")
        self.vehicle = Vehicle.objects.create(
            plate_display="12 ع 345 - ایران 68",
            vehicle_type=self.v_type,
            empty_weight=Decimal("14200.00")
        )
        self.driver = Driver.objects.create(full_name="حمید رضایی", mobile="09121112233")
        self.loss_type = LossType.objects.create(name="رطوبت بار", default_percent=Decimal("1.50"))

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def test_create_ticket_success(self):
        self.authenticate(self.operator)
        payload = {
            "license_plate_display": "12 ع 345 - ایران 68",
            "product": self.product.id,
            "party": self.party.id,
            "operation_type": self.op_type.id,
            "vehicle": self.vehicle.id,
            "driver": self.driver.id,
            "first_weight": 14250,
            "sent_weight": 22000,
            "notes": "ثبت تستی API"
        }
        res = self.client.post("/api/v1/tickets/", payload)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res.data["serial_number"])
        self.assertEqual(res.data["status"]["code"], TicketStatus.WAITING_SECOND)
        self.assertEqual(float(res.data["first_weight"]), 14250.0)

        # Check Audit Log created
        self.assertTrue(AuditLog.objects.filter(model_name="WeighTicket", record_id=str(res.data["id"])).exists())

    def test_record_first_and_second_weight(self):
        self.authenticate(self.operator)
        
        # 1. Create ticket
        create_res = self.client.post("/api/v1/tickets/", {
            "license_plate_display": "12 ع 345 - ایران 68",
            "product": self.product.id,
            "party": self.party.id,
            "operation_type": self.op_type.id,
            "first_weight": 0
        })
        ticket_id = create_res.data["id"]

        # 2. Record First Weight
        w1_res = self.client.post(f"/api/v1/tickets/{ticket_id}/first-weight/", {
            "weight": 14200
        })
        self.assertEqual(w1_res.status_code, status.HTTP_200_OK)
        self.assertEqual(float(w1_res.data["data"]["first_weight"]), 14200.0)

        # 3. Record Second Weight
        w2_res = self.client.post(f"/api/v1/tickets/{ticket_id}/second-weight/", {
            "weight": 35200,
            "loss_percent": 1.0
        })
        self.assertEqual(w2_res.status_code, status.HTTP_200_OK)
        t_data = w2_res.data["data"]
        self.assertEqual(t_data["status"]["code"], TicketStatus.COMPLETED)
        self.assertEqual(float(t_data["gross_weight"]), 35200.0)
        self.assertEqual(float(t_data["tare_weight"]), 14200.0)
        self.assertEqual(float(t_data["net_weight"]), 21000.0)
        self.assertEqual(float(t_data["loss_weight"]), 210.0)
        self.assertEqual(float(t_data["final_weight"]), 20790.0)

    def test_operator_cannot_cancel_or_correct_completed_ticket(self):
        # Create completed ticket
        ticket = WeighTicket.objects.create(
            serial_number="TEST-999",
            license_plate_display="12 ع 345 - ایران 68",
            product=self.product,
            first_weight=Decimal("14000.00"),
            second_weight=Decimal("34000.00"),
            gross_weight=Decimal("34000.00"),
            tare_weight=Decimal("14000.00"),
            net_weight=Decimal("20000.00"),
            final_weight=Decimal("20000.00"),
            status=TicketStatus.COMPLETED
        )

        # Operator tries to cancel
        self.authenticate(self.operator)
        cancel_res = self.client.post(f"/api/v1/tickets/{ticket.id}/cancel/", {"reason": "ابطال غیرمجاز"})
        self.assertEqual(cancel_res.status_code, status.HTTP_403_FORBIDDEN)

        # Operator tries to correct
        correct_res = self.client.post(f"/api/v1/tickets/{ticket.id}/correct/", {
            "field": "tare_weight",
            "new_value": 14500,
            "reason": "تغییر غیرمجاز"
        })
        self.assertEqual(correct_res.status_code, status.HTTP_403_FORBIDDEN)

    def test_manager_can_cancel_and_correct(self):
        ticket = WeighTicket.objects.create(
            serial_number="TEST-888",
            license_plate_display="12 ع 345 - ایران 68",
            product=self.product,
            first_weight=Decimal("14000.00"),
            second_weight=Decimal("34000.00"),
            gross_weight=Decimal("34000.00"),
            tare_weight=Decimal("14000.00"),
            net_weight=Decimal("20000.00"),
            final_weight=Decimal("20000.00"),
            status=TicketStatus.WAITING_SECOND
        )

        self.authenticate(self.manager)

        # Correct
        correct_res = self.client.post(f"/api/v1/tickets/{ticket.id}/correct/", {
            "field": "first_weight",
            "new_value": 14500,
            "reason": "اصلاح خطای باسکول"
        })
        self.assertEqual(correct_res.status_code, status.HTTP_200_OK)
        self.assertEqual(float(correct_res.data["data"]["tare_weight"]), 14500.0)
        self.assertEqual(float(correct_res.data["data"]["net_weight"]), 19500.0)

        # Cancel
        cancel_res = self.client.post(f"/api/v1/tickets/{ticket.id}/cancel/", {
            "reason": "ابطال با دلیل موجه مدیریتی"
        })
        self.assertEqual(cancel_res.status_code, status.HTTP_200_OK)
        self.assertEqual(cancel_res.data["data"]["status"]["code"], TicketStatus.CANCELLED)

    def test_ticket_filtering_and_search(self):
        WeighTicket.objects.create(
            serial_number="SN-101",
            license_plate_display="34 ب 789 - ایران 11",
            product=self.product,
            party=self.party,
            status=TicketStatus.COMPLETED
        )
        WeighTicket.objects.create(
            serial_number="SN-102",
            license_plate_display="55 ج 111 - ایران 22",
            product=self.product,
            status=TicketStatus.WAITING_SECOND
        )

        self.authenticate(self.operator)

        # Filter by status
        res = self.client.get("/api/v1/tickets/?status=completed")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["count"], 1)
        self.assertEqual(res.data["results"][0]["serial_number"], "SN-101")

        # Search by plate
        res_search = self.client.get("/api/v1/tickets/?search=55 ج 111")
        self.assertEqual(res_search.status_code, status.HTTP_200_OK)
        self.assertEqual(res_search.data["count"], 1)
        self.assertEqual(res_search.data["results"][0]["serial_number"], "SN-102")
