from decimal import Decimal
import threading
from django.test import TestCase, TransactionTestCase, Client
from django.db import IntegrityError, connection
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils import timezone

from core.models import SystemSetting
from masterdata.models import Vehicle, VehicleType, Driver, OperationType, Location, UnloadLocation, Party, Product
from weighbridge.models import WeighTicket, EmergencyWeighTicket, TicketStatus, WeightMode, TicketSequence
from weighbridge.services import SerialNumberService
from weighbridge.plate_policy import DailyPlatePolicy
from accounts.models import RoleChoices


class TicketNumberingSequentialTests(TestCase):
    """
    Tests covering sequential allocation, prefix synchronization, and collision skipping.
    """

    def setUp(self):
        self.settings = SystemSetting.get_settings()
        self.settings.serial_prefix = "WB-"
        self.settings.serial_start_number = 1001
        self.settings.save()

    def test_sequential_allocation_monotonicity(self):
        """
        Sequential allocations must yield strictly increasing numbers.
        """
        sn1 = SerialNumberService.allocate_serial_number(SerialNumberService.SCOPE_STANDARD)
        sn2 = SerialNumberService.allocate_serial_number(SerialNumberService.SCOPE_STANDARD)
        sn3 = SerialNumberService.allocate_serial_number(SerialNumberService.SCOPE_STANDARD)

        self.assertTrue(sn1.startswith("WB-"))
        self.assertTrue(sn2.startswith("WB-"))
        self.assertTrue(sn3.startswith("WB-"))

        num1 = int(sn1.replace("WB-", ""))
        num2 = int(sn2.replace("WB-", ""))
        num3 = int(sn3.replace("WB-", ""))

        self.assertEqual(num2, num1 + 1)
        self.assertEqual(num3, num2 + 1)

    def test_prefix_change_synchronization(self):
        """
        If SystemSetting.serial_prefix changes, the sequence counter must adopt the new prefix.
        """
        self.settings.serial_prefix = "PRIMA-"
        self.settings.save()

        sn = SerialNumberService.allocate_serial_number(SerialNumberService.SCOPE_STANDARD)
        self.assertTrue(sn.startswith("PRIMA-"))

        # Restore prefix
        self.settings.serial_prefix = "WB-"
        self.settings.save()

    def test_collision_forward_skip(self):
        """
        If a ticket with a future number already exists (e.g. manual import),
        the allocator must automatically skip it and provide the next free number.
        """
        seq = TicketSequence.objects.get(scope=SerialNumberService.SCOPE_STANDARD)
        target_collision_num = seq.last_number + 1
        collision_serial = f"WB-{target_collision_num}"

        # Pre-create a ticket with collision serial
        v_type = VehicleType.objects.first()
        WeighTicket.objects.create(
            serial_number=collision_serial,
            license_plate_display="11 ع 111 - ایران 11",
            first_weight=Decimal("12000.00"),
            vehicle_type=v_type,
        )

        # Allocate next -> should skip target_collision_num and return target_collision_num + 1
        allocated = SerialNumberService.allocate_serial_number(SerialNumberService.SCOPE_STANDARD)
        expected_serial = f"WB-{target_collision_num + 1}"
        self.assertEqual(allocated, expected_serial)


class TicketNumberingConcurrencyTests(TransactionTestCase):
    """
    True multi-threaded PostgreSQL concurrency tests for ticket allocation.
    """

    def setUp(self):
        self.settings = SystemSetting.get_settings()
        self.settings.serial_prefix = "WB-"
        self.settings.save()

    def test_concurrent_allocation_no_duplicates(self):
        """
        Multiple concurrent threads allocating serial numbers must never receive
        duplicate numbers and must complete without unhandled database errors.
        """
        thread_count = 6
        barrier = threading.Barrier(thread_count)
        allocated_serials = []
        errors = []

        def worker(worker_id):
            connection.close()
            try:
                barrier.wait()
                sn = SerialNumberService.allocate_serial_number(SerialNumberService.SCOPE_STANDARD)
                allocated_serials.append((worker_id, sn))
            except Exception as e:
                errors.append((worker_id, type(e).__name__, str(e)))
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(thread_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Encountered concurrency errors: {errors}")
        self.assertEqual(len(allocated_serials), thread_count)

        serials = [item[1] for item in allocated_serials]
        unique_serials = set(serials)
        self.assertEqual(len(serials), len(unique_serials), f"Duplicate serials found: {serials}")

    def test_concurrent_ticket_creation_via_policy(self):
        """
        Multiple operators submitting new tickets concurrently via DailyPlatePolicy
        must successfully create all tickets with distinct serial numbers without HTTP 500.
        """
        op_user = User.objects.create_user(username="concur_ticket_op", password="password123")
        v_type = VehicleType.objects.create(name="کامیون تست همزمانی", code="TR-CONCUR")

        thread_count = 4
        barrier = threading.Barrier(thread_count)
        created_tickets = []
        errors = []

        def worker(idx):
            connection.close()
            try:
                plate_str = f"8{idx} م 888 - ایران 8{idx}"
                ticket = WeighTicket(
                    license_plate_display=plate_str,
                    first_weight=Decimal("15000.00"),
                    vehicle_type=v_type,
                    first_weight_date=timezone.localdate(),
                )
                barrier.wait()
                DailyPlatePolicy.save(ticket, user=op_user, assign_serial=True)
                created_tickets.append((idx, ticket.id, ticket.serial_number))
            except Exception as e:
                errors.append((idx, type(e).__name__, str(e)))
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(thread_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Encountered errors during concurrent ticket save: {errors}")
        self.assertEqual(len(created_tickets), thread_count)

        serials = [t[2] for t in created_tickets]
        self.assertEqual(len(serials), len(set(serials)), f"Duplicate serial numbers generated: {serials}")


class TicketLifecycleNumberingTests(TestCase):
    """
    Tests covering serial number persistence and immutability across the full ticket lifecycle:
    First weighing -> Second weighing -> Direct completion -> Cancellation -> Reprinting.
    """

    def setUp(self):
        self.operator_user = User.objects.create_user(username="lifecycle_op", password="password123")
        self.operator_user.profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        self.operator_user.profile.save()

        self.admin_user = User.objects.create_user(username="lifecycle_admin", password="password123")
        self.admin_user.profile.role = RoleChoices.SUPER_ADMIN
        self.admin_user.profile.save()

        self.client = Client()
        self.client.force_login(self.operator_user)

        self.v_type = VehicleType.objects.create(name="تریلی لبه‌دار", code="TR-LIP")
        self.party = Party.objects.create(name="فولاد پریما")
        self.product = Product.objects.create(name="آهن اسفنجی", code="SPONGE")
        self.op_type = OperationType.objects.create(name="ورود مواد اولیه", code="IN-01", direction="inbound")
        self.origin = Location.objects.create(name="مبدأ تست")
        self.dest = Location.objects.create(name="مقصد تست")
        self.unload_loc = UnloadLocation.objects.create(name="سیلو ۱")

        self.settings = SystemSetting.get_settings()
        self.settings.serial_prefix = "WB-"
        self.settings.serial_start_number = 1001
        self.settings.save()

    def test_first_and_second_weighing_retains_identical_serial_number(self):
        """
        A ticket must retain its exact original serial number when second weighing is completed.
        """
        ticket = WeighTicket(
            license_plate_display="22 ع 222 - ایران 22",
            first_weight=Decimal("35000.00"),
            vehicle_type=self.v_type,
            party=self.party,
            product=self.product,
            operation_type=self.op_type,
            status=TicketStatus.WAITING_SECOND,
        )
        DailyPlatePolicy.save(ticket, user=self.operator_user, assign_serial=True)
        initial_serial = ticket.serial_number
        self.assertTrue(initial_serial.startswith("WB-"))

        # Second weighing submission
        ticket.second_weight = Decimal("14500.00")
        ticket.gross_weight = Decimal("35000.00")
        ticket.tare_weight = Decimal("14500.00")
        ticket.net_weight = Decimal("20500.00")
        ticket.final_weight = Decimal("20500.00")
        ticket.status = TicketStatus.COMPLETED
        ticket.save()

        ticket.refresh_from_db()
        self.assertEqual(ticket.serial_number, initial_serial, "Serial number must not change upon second weighing")
        self.assertEqual(ticket.status, TicketStatus.COMPLETED)

    def test_direct_completion_allocates_single_serial(self):
        """
        Direct completion mode allocates exactly one serial number and immediately completes the ticket.
        """
        ticket = WeighTicket(
            license_plate_display="33 ع 333 - ایران 33",
            first_weight=Decimal("38000.00"),
            second_weight=Decimal("15000.00"),
            gross_weight=Decimal("38000.00"),
            tare_weight=Decimal("15000.00"),
            net_weight=Decimal("23000.00"),
            final_weight=Decimal("23000.00"),
            weight_mode=WeightMode.DIRECT,
            vehicle_type=self.v_type,
            party=self.party,
            product=self.product,
            operation_type=self.op_type,
            status=TicketStatus.COMPLETED,
        )
        DailyPlatePolicy.save(ticket, user=self.operator_user, assign_serial=True)
        self.assertIsNotNone(ticket.serial_number)
        self.assertEqual(ticket.status, TicketStatus.COMPLETED)

    def test_cancellation_retains_serial_and_does_not_reuse_it(self):
        """
        Cancelling a ticket retains its serial number in status CANCELLED,
        and subsequent tickets receive the next sequential number without reusing the cancelled number.
        """
        ticket1 = WeighTicket(
            license_plate_display="44 ع 444 - ایران 44",
            first_weight=Decimal("20000.00"),
            vehicle_type=self.v_type,
        )
        DailyPlatePolicy.save(ticket1, user=self.operator_user, assign_serial=True)
        cancelled_serial = ticket1.serial_number

        # Cancel ticket1
        ticket1.status = TicketStatus.CANCELLED
        ticket1.cancellation_reason = "انصراف راننده از ورود"
        ticket1.cancelled_by = self.admin_user
        ticket1.cancelled_at = timezone.now()
        ticket1.save()

        ticket1.refresh_from_db()
        self.assertEqual(ticket1.serial_number, cancelled_serial)
        self.assertEqual(ticket1.status, TicketStatus.CANCELLED)

        # Allocate new ticket
        ticket2 = WeighTicket(
            license_plate_display="55 ع 555 - ایران 55",
            first_weight=Decimal("22000.00"),
            vehicle_type=self.v_type,
        )
        DailyPlatePolicy.save(ticket2, user=self.operator_user, assign_serial=True)

        self.assertNotEqual(ticket2.serial_number, cancelled_serial, "Cancelled number must never be reused")
        num1 = int(cancelled_serial.replace("WB-", ""))
        num2 = int(ticket2.serial_number.replace("WB-", ""))
        self.assertEqual(num2, num1 + 1)

    def test_reprinting_does_not_allocate_new_number(self):
        """
        Reprinting a ticket (GET print view) must never alter or re-allocate serial numbers.
        """
        ticket = WeighTicket(
            license_plate_display="66 ع 666 - ایران 66",
            first_weight=Decimal("25000.00"),
            vehicle_type=self.v_type,
        )
        DailyPlatePolicy.save(ticket, user=self.operator_user, assign_serial=True)
        orig_serial = ticket.serial_number

        # Call print view
        print_url = reverse("weighbridge:ticket_print", kwargs={"pk": ticket.id})
        response = self.client.get(print_url)
        self.assertEqual(response.status_code, 200)

        ticket.refresh_from_db()
        self.assertEqual(ticket.serial_number, orig_serial)

    def test_serial_number_immutability(self):
        """
        Attempting to alter serial_number on an existing persisted ticket must raise ValidationError.
        """
        ticket = WeighTicket(
            license_plate_display="77 ع 777 - ایران 77",
            first_weight=Decimal("28000.00"),
            vehicle_type=self.v_type,
        )
        DailyPlatePolicy.save(ticket, user=self.operator_user, assign_serial=True)

        # Attempt to change serial_number
        ticket.serial_number = "WB-HACKED-999"
        with self.assertRaises(ValidationError):
            ticket.save()

    def test_emergency_ticket_allocation_and_immutability(self):
        """
        Emergency tickets allocate sequential EXT-#### serials and enforce immutability.
        """
        et1 = EmergencyWeighTicket.objects.create(
            company_name="شرکت کاوه",
            driver_name="راننده متفرقه",
            driver_mobile="09121110000",
            license_plate="88 ع 888 - ایران 88",
            gross_weight=Decimal("30000.00"),
            tare_weight=Decimal("12000.00"),
            weight_date=timezone.localdate(),
        )
        self.assertTrue(et1.serial_number.startswith("EXT-"))

        et2 = EmergencyWeighTicket.objects.create(
            company_name="شرکت پارس",
            driver_name="راننده متفرقه ۲",
            driver_mobile="09121110001",
            license_plate="99 ع 999 - ایران 99",
            gross_weight=Decimal("32000.00"),
            tare_weight=Decimal("13000.00"),
            weight_date=timezone.localdate(),
        )
        self.assertTrue(et2.serial_number.startswith("EXT-"))

        num1 = int(et1.serial_number.replace("EXT-", ""))
        num2 = int(et2.serial_number.replace("EXT-", ""))
        self.assertEqual(num2, num1 + 1)

        # Immutability
        et1.serial_number = "EXT-FORGED"
        with self.assertRaises(ValidationError):
            et1.save()


class DatabaseUniquenessConstraintTests(TestCase):
    """
    Tests proving PostgreSQL uniqueness constraint enforcement on serial_number.
    """

    def test_database_enforces_serial_number_uniqueness(self):
        """
        PostgreSQL unique constraint must prevent duplicate serial numbers even on direct inserts.
        """
        v_type = VehicleType.objects.first()
        WeighTicket.objects.create(
            serial_number="UNIQUE-TEST-001",
            license_plate_display="12 د 123 - ایران 45",
            first_weight=Decimal("18000.00"),
            vehicle_type=v_type,
        )

        with self.assertRaises(IntegrityError):
            WeighTicket.objects.create(
                serial_number="UNIQUE-TEST-001",
                license_plate_display="34 د 567 - ایران 89",
                first_weight=Decimal("20000.00"),
                vehicle_type=v_type,
            )
