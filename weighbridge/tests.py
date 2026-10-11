from django.test import TestCase, Client
from django.contrib.auth.models import User
from decimal import Decimal
from datetime import date, time

from weighbridge.models import WeighTicket, TicketStatus, WeightMode
from weighbridge.services import TicketCalculationService, SerialNumberService
from masterdata.models import Product, Party, Driver, VehicleType, Vehicle, OperationType, LossType, Location, UnloadLocation
from accounts.models import UserProfile, RoleChoices
from core.models import SystemSetting
from core.weight_provider import ManualWeightProvider, WeightUnit
from audit.models import AuditLog
from django.urls import reverse


class FreightAmountTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username="freight_admin", password="test-password")
        self.client.force_login(self.user)
        SystemSetting.objects.create(require_driver=False)
        self.op_type = OperationType.objects.create(name="خرید تست", code="OP-FR")
        self.party = Party.objects.create(name="طرف حساب کرایه")
        self.product = Product.objects.create(name="محصول کرایه")
        self.v_type = VehicleType.objects.create(name="کامیون")
        self.origin = Location.objects.create(name="مبدأ کرایه")
        self.dest = Location.objects.create(name="مقصد کرایه")
        self.unload_loc = UnloadLocation.objects.create(name="جایگاه کرایه")
        self.payload = {
            "weight_mode": WeightMode.EMPTY_FIRST,
            "operation_type": self.op_type.pk,
            "party": self.party.pk,
            "product": self.product.pk,
            "vehicle_type": self.v_type.pk,
            "driver_name_custom": "راننده تست کرایه",
            "driver_mobile_custom": "09121112233",
            "origin": self.origin.pk,
            "destination": self.dest.pk,
            "unload_location": self.unload_loc.pk,
            "license_plate_display": "12 ج 345 - ایران 67",
            "first_weight": "12000", "load_count": "1",
            "sent_weight": "0", "loss_percent": "0", "loss_weight": "0",
        }

    def create_ticket(self, amount):
        response = self.client.post(reverse("weighbridge:ticket_create"), {
            **self.payload, "freight_amount": amount,
            "license_plate_display": f"12 ج {345 + WeighTicket.objects.count()} - ایران 67",
        })
        self.assertEqual(response.status_code, 302)
        return WeighTicket.objects.latest("id")

    def test_amount_persists_and_is_displayed(self):
        ticket = self.create_ticket("1250000")
        self.assertEqual(ticket.freight_amount, Decimal("1250000"))
        response = self.client.get(reverse("weighbridge:ticket_detail", args=[ticket.pk]))
        self.assertContains(response, "1,250,000")
        self.assertContains(response, "مبلغ کرایه (تومان)")

    def test_blank_is_distinct_from_zero(self):
        self.assertIsNone(self.create_ticket("").freight_amount)
        self.assertEqual(self.create_ticket("0").freight_amount, Decimal("0"))

    def test_invalid_amounts_do_not_create_tickets(self):
        for amount in ("-1", "1.5", "invalid", "1000000000000000"):
            with self.subTest(amount=amount):
                response = self.client.post(reverse("weighbridge:ticket_create"), {
                    **self.payload, "freight_amount": amount,
                })
                self.assertEqual(response.status_code, 200)
                self.assertIn("freight_amount", response.context["form"].errors)
        self.assertFalse(WeighTicket.objects.exists())

    def test_manager_can_edit_amount_and_audit_records_change(self):
        ticket = self.create_ticket("1250000")
        response = self.client.post(reverse("weighbridge:ticket_edit", args=[ticket.pk]), {
            **self.payload, "freight_amount": "1500000", "manager_reason": "اصلاح کرایه",
        })
        self.assertEqual(response.status_code, 302)
        ticket.refresh_from_db()
        self.assertEqual(ticket.freight_amount, Decimal("1500000"))
        audit = AuditLog.objects.filter(record_id=str(ticket.pk), action="override_weight").latest("id")
        self.assertEqual(audit.old_values["freight_amount"], "1250000")
        self.assertEqual(audit.new_values["freight_amount"], "1500000")

    def test_second_weight_preserves_amount(self):
        ticket = self.create_ticket("1250000")
        response = self.client.post(reverse("weighbridge:ticket_second_weight", args=[ticket.pk]), {
            "second_weight": "30000", "sent_weight": "18000", "loss_percent": "0",
        })
        self.assertEqual(response.status_code, 302)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.COMPLETED)
        self.assertEqual(ticket.freight_amount, Decimal("1250000"))

    def test_manager_edit_loss_weight_optional_and_allows_blank(self):
        ticket = self.create_ticket("1000")
        payload = {**self.payload, "first_weight": "25000", "second_weight": "10000", "manager_reason": "تست افت اختیاری"}
        payload["loss_weight"] = ""
        payload["loss_percent"] = ""
        response = self.client.post(reverse("weighbridge:ticket_edit", args=[ticket.pk]), payload)
        self.assertEqual(response.status_code, 302)
        ticket.refresh_from_db()
        self.assertEqual(ticket.loss_weight, Decimal("0.00"))
        self.assertEqual(ticket.net_weight, Decimal("15000.00"))
        self.assertEqual(ticket.final_weight, Decimal("15000.00"))

    def test_manager_edit_loss_weight_manual_value_saved_and_overridden(self):
        ticket = self.create_ticket("1000")
        payload = {
            **self.payload,
            "first_weight": "25000",
            "second_weight": "10000",
            "loss_weight": "120.50",
            "loss_percent": "0",
            "manager_reason": "تنظیم دستی افت توسط مدیر",
        }
        response = self.client.post(reverse("weighbridge:ticket_edit", args=[ticket.pk]), payload)
        self.assertEqual(response.status_code, 302)
        ticket.refresh_from_db()
        self.assertEqual(ticket.loss_weight, Decimal("120.50"))
        self.assertTrue(ticket.is_loss_overridden)
        self.assertEqual(ticket.net_weight, Decimal("15000.00"))
        self.assertEqual(ticket.final_weight, Decimal("14879.50"))

    def test_manager_edit_preserves_vehicle_and_vehicle_type_when_not_in_post(self):
        ticket = self.create_ticket("1250000")
        self.assertIsNotNone(ticket.vehicle)
        self.assertEqual(ticket.vehicle_type, self.v_type)
        self.assertEqual(ticket.vehicle_type_display, self.v_type.name)

        # POST without 'vehicle' or 'vehicle_type'
        edit_payload = {
            "operation_type": self.op_type.pk,
            "party": self.party.pk,
            "product": self.product.pk,
            "license_plate_display": ticket.license_plate_display,
            "first_weight": "12000",
            "manager_reason": "ویرایش بدون فیلد نوع خودرو در پست",
        }
        response = self.client.post(reverse("weighbridge:ticket_edit", args=[ticket.pk]), edit_payload)
        self.assertEqual(response.status_code, 302)
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.vehicle)
        self.assertEqual(ticket.vehicle_type, self.v_type)
        self.assertEqual(ticket.vehicle_type_display, self.v_type.name)

    def test_manager_edit_updates_vehicle_type(self):
        ticket = self.create_ticket("1250000")
        new_vtype = VehicleType.objects.create(name="تریلی کفی ۱۸ چرخ")
        edit_payload = {
            **self.payload,
            "license_plate_display": ticket.license_plate_display,
            "vehicle_type": new_vtype.pk,
            "first_weight": "12000",
            "manager_reason": "تغییر نوع خودرو",
        }
        response = self.client.post(reverse("weighbridge:ticket_edit", args=[ticket.pk]), edit_payload)
        self.assertEqual(response.status_code, 302)
        ticket.refresh_from_db()
        self.assertEqual(ticket.vehicle_type, new_vtype)
        self.assertEqual(ticket.vehicle_type_display, new_vtype.name)


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


class PlateLookupAutoFillTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username="plate_tester", password="password123")
        self.client.force_login(self.user)
        self.v_type = VehicleType.objects.create(name="تریلی لبه‌دار", code="TR-1", standard_tare_weight=Decimal("15000"))
        self.driver = Driver.objects.create(full_name="علی محمدی", mobile="09129998877")
        self.vehicle = Vehicle.objects.create(
            plate_display="34 ج 567 - ایران 88",
            plate_part1="34",
            plate_letter="ج",
            plate_part2="567",
            plate_iran="88",
            vehicle_type=self.v_type,
            default_driver=self.driver,
            empty_weight=Decimal("14800.00"),
        )

    def test_lookup_by_english_plate(self):
        response = self.client.get(reverse("weighbridge:ajax_plate_lookup"), {"plate": "34 ج 567 - ایران 88"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["found"])
        self.assertTrue(data["is_duplicate"])
        self.assertEqual(data["driver_name"], "علی محمدی")
        self.assertEqual(data["driver_mobile"], "09129998877")
        self.assertEqual(data["vehicle_type_id"], self.v_type.id)
        self.assertEqual(data["vehicle_type_name"], "تریلی لبه‌دار")
        self.assertEqual(data["empty_weight"], 14800.0)

    def test_lookup_by_persian_digits_plate(self):
        # Even if typed with Persian digits, it should match normalized plate
        response = self.client.get(reverse("weighbridge:ajax_plate_lookup"), {"plate": "۳۴ ج ۵۶۷ - ایران ۸۸"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["found"])
        self.assertEqual(data["driver_name"], "علی محمدی")
        self.assertEqual(data["driver_mobile"], "09129998877")
        self.assertEqual(data["vehicle_type_id"], self.v_type.id)

    def test_lookup_from_previous_ticket_without_masterdata_vehicle(self):
        # Create ticket for a plate that is NOT in Vehicle master table
        WeighTicket.objects.create(
            serial_number="WB-HIST-1",
            license_plate_display="77 د 123 - ایران 45",
            driver_name_custom="رضا حسینی",
            driver_mobile_custom="09351112233",
            vehicle_type=self.v_type,
            first_weight=Decimal("25000.00"),
            status=TicketStatus.COMPLETED
        )

        response = self.client.get(reverse("weighbridge:ajax_plate_lookup"), {"plate": "۷۷ د ۱۲۳ - ایران ۴۵"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["found"])
        self.assertEqual(data["driver_name"], "رضا حسینی")
        self.assertEqual(data["driver_mobile"], "09351112233")
        self.assertEqual(data["vehicle_type_id"], self.v_type.id)
        self.assertEqual(data["vehicle_type_name"], "تریلی لبه‌دار")

    def test_auto_register_new_vehicle_and_driver_on_ticket_create(self):
        # Ensure driver and vehicle do not exist yet
        self.assertFalse(Driver.objects.filter(full_name="حمید رضایی").exists())
        self.assertFalse(Vehicle.objects.filter(plate_display="88 ع 999 - ایران 11").exists())

        product = Product.objects.create(name="آهن اسفنجی", code="P-1")
        party = Party.objects.create(name="شرکت فولاد غرب")
        op_type = OperationType.objects.create(name="خرید داخلی", code="OP-1")
        origin = Location.objects.create(name="مبدأ رجیستر")
        destination = Location.objects.create(name="مقصد رجیستر")
        unload_location = UnloadLocation.objects.create(name="جایگاه رجیستر")

        response = self.client.post(reverse("weighbridge:ticket_create"), {
            "weight_mode": WeightMode.EMPTY_FIRST,
            "operation_type": op_type.id,
            "party": party.id,
            "product": product.id,
            "plate_part1": "88",
            "plate_letter": "ع",
            "plate_part2": "999",
            "plate_iran": "11",
            "license_plate_display": "88 ع 999 - ایران 11",
            "vehicle_type": self.v_type.id,
            "driver_name_custom": "حمید رضایی",
            "driver_mobile_custom": "09127776655",
            "origin": origin.id,
            "destination": destination.id,
            "unload_location": unload_location.id,
            "first_weight": "15200",
            "load_count": "1",
            "sent_weight": "0",
            "loss_percent": "0",
            "loss_weight": "0",
            "submit_action": "save",
        })
        self.assertEqual(response.status_code, 302)

        # Verify Driver was automatically created in MasterData
        driver = Driver.objects.filter(full_name="حمید رضایی").first()
        self.assertIsNotNone(driver)
        self.assertEqual(driver.mobile, "09127776655")

        # Verify Vehicle was automatically created in MasterData
        vehicle = Vehicle.objects.filter(plate_display="88 ع 999 - ایران 11").first()
        self.assertIsNotNone(vehicle)
        self.assertEqual(vehicle.vehicle_type, self.v_type)
        self.assertEqual(vehicle.default_driver, driver)
        self.assertEqual(vehicle.plate_part1, "88")
        self.assertEqual(vehicle.plate_letter, "ع")

        # Verify Ticket is linked to newly registered Vehicle and Driver
        ticket = WeighTicket.objects.latest("id")
        self.assertEqual(ticket.driver, driver)
        self.assertEqual(ticket.vehicle, vehicle)
        self.assertEqual(ticket.vehicle_type, self.v_type)

        # Now verify subsequent lookup finds it as duplicate
        lookup_resp = self.client.get(reverse("weighbridge:ajax_plate_lookup"), {"plate": "88 ع 999 - ایران 11"})
        lookup_data = lookup_resp.json()
        self.assertTrue(lookup_data["found"])
        self.assertTrue(lookup_data["is_duplicate"])
        self.assertEqual(lookup_data["driver_name"], "حمید رضایی")
        self.assertEqual(lookup_data["driver_mobile"], "09127776655")
        self.assertEqual(lookup_data["vehicle_type_id"], self.v_type.id)


class TicketPrintSentWeightTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username="print_tester", password="test-password")
        self.client.force_login(self.user)
        SystemSetting.objects.create(company_name="شرکت پریما باسکول", receipt_header_title="قبض توزین رسمی")

        self.ticket = WeighTicket.objects.create(
            serial_number="T-99001",
            license_plate_display="55 ب 678 - ایران 22",
            waybill_number="WB-884422",
            sent_weight=Decimal("18500.00"),
            first_weight=Decimal("30500.00"),
            second_weight=Decimal("12000.00"),
            gross_weight=Decimal("30500.00"),
            tare_weight=Decimal("12000.00"),
            net_weight=Decimal("18500.00"),
            final_weight=Decimal("18500.00"),
            status=TicketStatus.COMPLETED,
            weight_mode=WeightMode.EMPTY_FIRST,
            load_count=1,
        )

    def test_print_a4_contains_sent_weight_in_waybill(self):
        response = self.client.get(reverse("weighbridge:ticket_print", args=[self.ticket.pk]), {"template": "a4"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "وزن ارسالی در بارنامه:")
        self.assertContains(response, "18,500")
        self.assertContains(response, "WB-884422")

    def test_print_a5_contains_sent_weight_in_waybill(self):
        response = self.client.get(reverse("weighbridge:ticket_print", args=[self.ticket.pk]), {"template": "a5"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "وزن ارسالی در بارنامه:")
        self.assertContains(response, "18,500")
        self.assertContains(response, "WB-884422")
        self.assertContains(response, "زمان ورود (وزن ۱):")
        self.assertContains(response, "زمان خروج (وزن ۲):")
        self.assertContains(response, "اپراتور ورود:")
        self.assertContains(response, "اپراتور خروج:")

    def test_print_pos_contains_sent_weight_in_waybill(self):
        response = self.client.get(reverse("weighbridge:ticket_print", args=[self.ticket.pk]), {"template": "pos"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "وزن ارسالی در بارنامه:")
        self.assertContains(response, "18,500")

class TicketIngotCountTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username="ingot_admin", password="test-password")
        self.client.force_login(self.user)
        SystemSetting.objects.create(require_driver=False)

        self.sale_op = OperationType.objects.create(
            name="صادره (فروش محصول)",
            code="SALE",
            direction="outbound"
        )
        self.purchase_op = OperationType.objects.create(
            name="وارده (خرید مواد اولیه)",
            code="PURCHASE",
            direction="inbound"
        )
        self.party = Party.objects.create(name="طرف حساب شمش")
        self.product = Product.objects.create(name="شمش فولادی")
        self.v_type = VehicleType.objects.create(name="تریلی شمش")
        self.origin = Location.objects.create(name="مبدأ شمش")
        self.dest = Location.objects.create(name="مقصد شمش")
        self.unload_loc = UnloadLocation.objects.create(name="جایگاه شمش")

        self.payload = {
            "weight_mode": WeightMode.EMPTY_FIRST,
            "party": self.party.pk,
            "product": self.product.pk,
            "vehicle_type": self.v_type.pk,
            "driver_name_custom": "راننده شمش",
            "driver_mobile_custom": "09121112233",
            "origin": self.origin.pk,
            "destination": self.dest.pk,
            "unload_location": self.unload_loc.pk,
            "license_plate_display": "12 ج 345 - ایران 67",
            "first_weight": "12000",
            "load_count": "1",
            "sent_weight": "0",
            "loss_percent": "0",
            "loss_weight": "0",
        }

    def test_ingot_count_saved_for_sale_operation(self):
        response = self.client.post(reverse("weighbridge:ticket_create"), {
            **self.payload,
            "operation_type": self.sale_op.pk,
            "ingot_count": "120",
        })
        self.assertEqual(response.status_code, 302)
        ticket = WeighTicket.objects.latest("id")
        self.assertEqual(ticket.ingot_count, 120)

    def test_ingot_count_cleared_for_non_sale_operation(self):
        response = self.client.post(reverse("weighbridge:ticket_create"), {
            **self.payload,
            "operation_type": self.purchase_op.pk,
            "ingot_count": "120",
        })
        self.assertEqual(response.status_code, 302)
        ticket = WeighTicket.objects.latest("id")
        self.assertIsNone(ticket.ingot_count)

    def test_ingot_count_displayed_in_detail_and_print(self):
        ticket = WeighTicket.objects.create(
            serial_number="T-99002",
            license_plate_display="55 ب 678 - ایران 22",
            operation_type=self.sale_op,
            ingot_count=85,
            first_weight=Decimal("30500.00"),
            second_weight=Decimal("12000.00"),
            gross_weight=Decimal("30500.00"),
            tare_weight=Decimal("12000.00"),
            net_weight=Decimal("18500.00"),
            final_weight=Decimal("18500.00"),
            first_weight_operator=self.user,
            second_weight_operator=self.user,
            status=TicketStatus.COMPLETED,
            weight_mode=WeightMode.EMPTY_FIRST,
            load_count=1,
        )

        # Detail view
        detail_resp = self.client.get(reverse("weighbridge:ticket_detail", args=[ticket.pk]))
        self.assertEqual(detail_resp.status_code, 200)
        self.assertContains(detail_resp, "تعداد شمش (فروش):")
        self.assertContains(detail_resp, "85")
        self.assertContains(detail_resp, "تعداد بار و شمش:")
        self.assertContains(detail_resp, "1 (بار) - 85 (شمش)")

        # A4 print
        a4_resp = self.client.get(reverse("weighbridge:ticket_print", args=[ticket.pk]), {"template": "a4"})
        self.assertEqual(a4_resp.status_code, 200)
        self.assertContains(a4_resp, "تعداد شمش:")
        self.assertContains(a4_resp, "85")
        self.assertContains(a4_resp, "تعداد بار و شمش:")
        self.assertContains(a4_resp, "1 (بار) - 85 (شمش)")

        # A5 print
        a5_resp = self.client.get(reverse("weighbridge:ticket_print", args=[ticket.pk]), {"template": "a5"})
        self.assertEqual(a5_resp.status_code, 200)
        self.assertContains(a5_resp, "شمش: 85")
        self.assertContains(a5_resp, "تعداد بار و شمش:")
        self.assertContains(a5_resp, "1 (بار) - 85 (شمش)")

        # POS print
        pos_resp = self.client.get(reverse("weighbridge:ticket_print", args=[ticket.pk]), {"template": "pos"})
        self.assertEqual(pos_resp.status_code, 200)
        self.assertContains(pos_resp, "تعداد شمش (فروش):")
        self.assertContains(pos_resp, "85")
        self.assertContains(pos_resp, "تعداد بار و شمش:")
        self.assertContains(pos_resp, "1 (بار) - 85 (شمش)")

        self.assertEqual(ticket.load_and_ingot_display, "1 (بار) - 85 (شمش)")


class TicketMandatoryFieldsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username="mandatory_admin", password="test-password")
        self.client.force_login(self.user)
        SystemSetting.objects.create(require_driver=False)

        self.op_type = OperationType.objects.create(name="خرید تست", code="OP-M")
        self.party = Party.objects.create(name="طرف حساب تست")
        self.product = Product.objects.create(name="محصول تست")
        self.v_type = VehicleType.objects.create(name="تریلی لبه‌دار")
        self.origin = Location.objects.create(name="مبدأ تهران")
        self.dest = Location.objects.create(name="مقصد اصفهان")
        self.unload_loc = UnloadLocation.objects.create(name="انبار مرکزی")

        self.valid_payload = {
            "weight_mode": WeightMode.EMPTY_FIRST,
            "operation_type": self.op_type.pk,
            "party": self.party.pk,
            "product": self.product.pk,
            "vehicle_type": self.v_type.pk,
            "driver_name_custom": "حسین احمدی",
            "driver_mobile_custom": "09123456789",
            "origin": self.origin.pk,
            "destination": self.dest.pk,
            "unload_location": self.unload_loc.pk,
            "plate_part1": "12",
            "plate_letter": "ج",
            "plate_part2": "345",
            "plate_iran": "67",
            "license_plate_display": "12 ج 345 - ایران 67",
            "first_weight": "14500",
            "load_count": "1",
            "sent_weight": "0",
            "loss_percent": "0",
            "loss_weight": "0",
        }

    def test_all_10_mandatory_fields_valid_submission(self):
        response = self.client.post(reverse("weighbridge:ticket_create"), self.valid_payload)
        self.assertEqual(response.status_code, 302)
        ticket = WeighTicket.objects.latest("id")
        self.assertEqual(ticket.operation_type, self.op_type)
        self.assertEqual(ticket.party, self.party)
        self.assertEqual(ticket.product, self.product)
        self.assertEqual(ticket.vehicle_type, self.v_type)
        self.assertEqual(ticket.driver_name_custom, "حسین احمدی")
        self.assertEqual(ticket.driver_mobile_custom, "09123456789")
        self.assertEqual(ticket.origin, self.origin)
        self.assertEqual(ticket.destination, self.dest)
        self.assertEqual(ticket.unload_location, self.unload_loc)
        self.assertEqual(ticket.license_plate_display, "12 ج 345 - ایران 67")

    def test_empty_form_rejects_all_mandatory_fields(self):
        response = self.client.post(reverse("weighbridge:ticket_create"), {
            "weight_mode": WeightMode.EMPTY_FIRST,
            "first_weight": "14500",
        })
        self.assertEqual(response.status_code, 200)
        errors = response.context["form"].errors
        for field in [
            "operation_type", "party", "product", "vehicle_type",
            "license_plate_display", "driver_name_custom",
            "driver_mobile_custom", "origin", "destination", "unload_location"
        ]:
            self.assertIn(field, errors, f"Expected {field} to be mandatory and present in errors")

    def test_missing_each_field_individually(self):
        fields_to_test = [
            ("operation_type", ""),
            ("party", ""),
            ("product", ""),
            ("vehicle_type", ""),
            ("driver_name_custom", ""),
            ("driver_mobile_custom", ""),
            ("origin", ""),
            ("destination", ""),
            ("unload_location", ""),
        ]
        for field, bad_val in fields_to_test:
            with self.subTest(field=field):
                payload = dict(self.valid_payload)
                payload[field] = bad_val
                response = self.client.post(reverse("weighbridge:ticket_create"), payload)
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)

    def test_missing_plate_is_rejected(self):
        payload = dict(self.valid_payload)
        payload["license_plate_display"] = ""
        payload["plate_part1"] = ""
        payload["plate_letter"] = ""
        payload["plate_part2"] = ""
        payload["plate_iran"] = ""
        response = self.client.post(reverse("weighbridge:ticket_create"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("license_plate_display", response.context["form"].errors)

    def test_driver_mobile_validation_and_normalization(self):
        # Invalid mobile format
        payload = dict(self.valid_payload)
        payload["driver_mobile_custom"] = "091212"
        response = self.client.post(reverse("weighbridge:ticket_create"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("driver_mobile_custom", response.context["form"].errors)

        # Persian digits normalized
        payload["driver_mobile_custom"] = "۰۹۱۲۹۸۷۶۵۴۳"
        payload["license_plate_display"] = "77 ج 888 - ایران 99"
        response = self.client.post(reverse("weighbridge:ticket_create"), payload)
        self.assertEqual(response.status_code, 302)
        ticket = WeighTicket.objects.latest("id")
        self.assertEqual(ticket.driver_mobile_custom, "09129876543")

