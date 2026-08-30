from django.test import TestCase, Client
from django.contrib.auth.models import User
from decimal import Decimal
from datetime import date, time

from weighbridge.models import WeighTicket, TicketStatus, WeightMode
from weighbridge.services import TicketCalculationService, SerialNumberService
from masterdata.models import Product, Party, Driver, VehicleType, Vehicle, OperationType, LossType
from accounts.models import UserProfile, RoleChoices
from core.models import SystemSetting
from core.weight_provider import ManualWeightProvider, WeightUnit
from audit.models import AuditLog

class WeighbridgeCalculationTests(TestCase):
    def setUp(self):
        self.settings = SystemSetting.objects.create(
            company_name="شرکت تست",
            serial_start_number=1001,
            serial_prefix="TEST-",
            max_tolerance_kg=Decimal("50.00"),
            max_tolerance_percent=Decimal("1.00")
        )
        self.product = Product.objects.create(
            name="آهن اسفنجی",
            standard_tolerance_kg=Decimal("50.00"),
            default_loss_percent=Decimal("1.00")
        )

    def test_gross_tare_net_calculation_full_first(self):
        """Test calculation when truck is weighed Full first, then Empty."""
        w1 = Decimal("35000.00")  # Full
        w2 = Decimal("15000.00")  # Empty
        sent_weight = Decimal("20000.00")

        res = TicketCalculationService.calculate_ticket(
            first_weight=w1,
            second_weight=w2,
            sent_weight=sent_weight,
            loss_percent=Decimal("0.00"),
            product=self.product
        )

        self.assertEqual(res["gross_weight"], Decimal("35000.00"))
        self.assertEqual(res["tare_weight"], Decimal("15000.00"))
        self.assertEqual(res["net_weight"], Decimal("20000.00"))
        self.assertEqual(res["final_weight"], Decimal("20000.00"))
        self.assertEqual(res["weight_difference"], Decimal("0.00"))
        self.assertFalse(res["is_tolerance_exceeded"])

    def test_gross_tare_net_calculation_empty_first(self):
        """Test calculation when truck is weighed Empty first, then Full."""
        w1 = Decimal("12000.00")  # Empty
        w2 = Decimal("28500.00")  # Full
        sent_weight = Decimal("16500.00")

        res = TicketCalculationService.calculate_ticket(
            first_weight=w1,
            second_weight=w2,
            sent_weight=sent_weight,
            loss_percent=Decimal("0.00"),
            product=self.product
        )

        self.assertEqual(res["gross_weight"], Decimal("28500.00"))
        self.assertEqual(res["tare_weight"], Decimal("12000.00"))
        self.assertEqual(res["net_weight"], Decimal("16500.00"))
        self.assertEqual(res["final_weight"], Decimal("16500.00"))

    def test_loss_calculation(self):
        """Test loss weight calculation based on net weight and loss percentage."""
        w1 = Decimal("30000.00")
        w2 = Decimal("10000.00")
        # Net = 20,000 Kg, Loss % = 2.0% -> Loss Kg = 400 Kg, Final = 19,600 Kg
        res = TicketCalculationService.calculate_ticket(
            first_weight=w1,
            second_weight=w2,
            loss_percent=Decimal("2.00"),
            product=self.product
        )

        self.assertEqual(res["net_weight"], Decimal("20000.00"))
        self.assertEqual(res["loss_weight"], Decimal("400.00"))
        self.assertEqual(res["final_weight"], Decimal("19600.00"))

    def test_manual_loss_override(self):
        """Test manual override of loss weight."""
        w1 = Decimal("30000.00")
        w2 = Decimal("10000.00")
        manual_loss = Decimal("550.00")

        res = TicketCalculationService.calculate_ticket(
            first_weight=w1,
            second_weight=w2,
            loss_percent=Decimal("2.00"),
            manual_loss_weight=manual_loss,
            is_loss_overridden=True,
            product=self.product
        )

        self.assertEqual(res["loss_weight"], Decimal("550.00"))
        self.assertEqual(res["final_weight"], Decimal("19450.00"))

    def test_tolerance_exceeded_discrepancy(self):
        """Test detection of weight variance exceeding allowed standard tolerance."""
        w1 = Decimal("30000.00")
        w2 = Decimal("10000.00")
        # Net = 20,000 Kg, Sent = 20,200 Kg -> Diff = -200 Kg (> 50 Kg allowed)
        sent_weight = Decimal("20200.00")

        res = TicketCalculationService.calculate_ticket(
            first_weight=w1,
            second_weight=w2,
            sent_weight=sent_weight,
            product=self.product
        )

        self.assertEqual(res["weight_difference"], Decimal("-200.00"))
        self.assertTrue(res["is_tolerance_exceeded"])

    def test_serial_number_generation(self):
        """Test atomic serial numbering with prefix."""
        s1 = SerialNumberService.get_next_serial_number()
        self.assertEqual(s1, "TEST-1001")

        WeighTicket.objects.create(
            serial_number="TEST-1001",
            first_weight=Decimal("1000.00"),
            license_plate_display="12 ج 345 - ایران 67"
        )

        s2 = SerialNumberService.get_next_serial_number()
        self.assertEqual(s2, "TEST-1002")

class WeightProviderTests(TestCase):
    def test_manual_weight_provider_sanitization(self):
        provider = ManualWeightProvider(unit=WeightUnit.KG)
        
        # Test comma removal
        res1 = provider.get_weight("18,780")
        self.assertTrue(res1.is_stable)
        self.assertEqual(res1.weight, Decimal("18780"))

        # Test Persian digits
        res2 = provider.get_weight("۱۲۳۴۰")
        self.assertTrue(res2.is_stable)
        self.assertEqual(res2.weight, Decimal("12340"))

        # Test negative weight rejection
        res3 = provider.get_weight("-500")
        self.assertFalse(res3.is_stable)
        self.assertIsNotNone(res3.error_message)

class WorkflowAndPermissionTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(username="admin_test", password="password123")
        self.op_user = User.objects.create_user(username="op_test", password="password123")
        UserProfile.objects.filter(user=self.op_user).update(role=RoleChoices.WEIGHBRIDGE_OPERATOR)
        
        self.client = Client()

    def test_operator_ticket_creation_and_completion(self):
        self.client.login(username="op_test", password="password123")
        
        ticket = WeighTicket.objects.create(
            serial_number="WB-TEST-1",
            status=TicketStatus.WAITING_SECOND,
            license_plate_display="12 ج 345 - ایران 67",
            first_weight=Decimal("30000.00"),
            first_weight_operator=self.op_user
        )

        # Operator completes 2nd weight
        response = self.client.post(f"/weighbridge/tickets/{ticket.id}/second-weight/", {
            "second_weight": "12000",
            "second_weight_date_jalali": "1405/06/06",
            "second_weight_time_str": "14:30",
            "loss_percent": "0",
            "sent_weight": "18000",
            "submit_action": "save"
        })

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.COMPLETED)
        self.assertEqual(ticket.net_weight, Decimal("18000.00"))
        self.assertEqual(ticket.tare_weight, Decimal("12000.00"))
        self.assertEqual(ticket.gross_weight, Decimal("30000.00"))

    def test_ticket_cancellation_and_audit(self):
        self.client.login(username="admin_test", password="password123")
        
        ticket = WeighTicket.objects.create(
            serial_number="WB-TEST-CANCEL",
            status=TicketStatus.COMPLETED,
            license_plate_display="12 ج 345 - ایران 67",
            first_weight=Decimal("30000.00"),
            second_weight=Decimal("12000.00"),
            gross_weight=Decimal("30000.00"),
            tare_weight=Decimal("12000.00"),
            net_weight=Decimal("18000.00")
        )

        response = self.client.post(f"/weighbridge/tickets/{ticket.id}/cancel/", {
            "cancellation_reason": "ثبت تکراری پلاک خودرو به اشتباه"
        })

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.CANCELLED)
        self.assertEqual(ticket.cancellation_reason, "ثبت تکراری پلاک خودرو به اشتباه")
        
        # Verify Audit Log exists
        self.assertTrue(AuditLog.objects.filter(record_id=str(ticket.id), action="cancel").exists())
