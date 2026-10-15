from decimal import Decimal
import threading
from django.test import TestCase, Client, TransactionTestCase
from django.db import IntegrityError, connection
from django.urls import reverse
from django.contrib.auth.models import User

from masterdata.models import Vehicle, VehicleType, Driver, OperationType, Location, UnloadLocation, Party, Product
from weighbridge.models import WeighTicket, TicketStatus, BlockedPlate, PlateRegistrationException
from weighbridge.plate_policy import normalize_plate
from weighbridge.services import VehicleDriverRegistrationService
from accounts.models import RoleChoices
from core.models import SystemSetting


class VehiclePlateOptimizationTests(TestCase):
    """
    Automated test suite for Phase 2.1: Fast and Reliable Vehicle Plate Lookup.
    """

    def setUp(self):
        self.operator_user = User.objects.create_user(username="test_op", password="password123")
        self.operator_user.profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        self.operator_user.profile.save()

        self.client = Client()
        self.client.force_login(self.operator_user)

        self.vehicle_type = VehicleType.objects.create(name="تریلی کفی", code="TR-FLAT")
        self.driver = Driver.objects.create(full_name="علی رضایی", mobile="09121112233")

        self.op_type = OperationType.objects.create(name="ورود مواد اولیه", code="IN-01", direction="inbound")
        self.party = Party.objects.create(name="فولاد صبا", code="P-01")
        self.product = Product.objects.create(name="شمش 150", code="PR-150")
        self.origin = Location.objects.create(name="اصفهان")
        self.dest = Location.objects.create(name="کارخانه")
        self.unload_loc = UnloadLocation.objects.create(name="انبار 1")

        SystemSetting.objects.update_or_create(id=1, defaults={"company_name": "شرکت فولاد پریما"})

    # 1. Persian/English digit normalization
    def test_persian_and_english_digit_normalization(self):
        """
        Verify that Persian, Arabic, and English digits, as well as various spacing
        and Iran prefixes, produce identical normalized values.
        """
        plate_en = "12 ع 345 - ایران 64"
        plate_fa = "۱۲ ع ۳۴۵ - ایران ۶۴"
        plate_ar = "١٢ ع ٣٤٥ - ايران ٦٤"
        plate_raw = "12ع34564"
        plate_spaced = "  12  ع  345   ایران  64  "

        expected = "12ع34564"
        self.assertEqual(normalize_plate(plate_en), expected)
        self.assertEqual(normalize_plate(plate_fa), expected)
        self.assertEqual(normalize_plate(plate_ar), expected)
        self.assertEqual(normalize_plate(plate_raw), expected)
        self.assertEqual(normalize_plate(plate_spaced), expected)

    # 2. Vehicle save synchronizes normalized_plate
    def test_vehicle_save_synchronizes_normalized_plate(self):
        """
        Creating and updating Vehicle must keep normalized_plate automatically synchronized.
        """
        # Creation with structured parts
        v = Vehicle.objects.create(
            plate_part1="24",
            plate_letter="ب",
            plate_part2="888",
            plate_iran="11",
            vehicle_type=self.vehicle_type,
        )
        self.assertEqual(v.plate_display, "24 ب 888 - ایران 11")
        self.assertEqual(v.normalized_plate, "24ب88811")

        # Updating plate_display updates normalized_plate
        v.plate_display = "35 ج 999 - ایران 22"
        v.save()
        v.refresh_from_db()
        self.assertEqual(v.normalized_plate, "35ج99922")

        # Partial update with update_fields includes normalized_plate
        v.plate_display = "46 د 111 - ایران 33"
        v.save(update_fields=["plate_display"])
        v.refresh_from_db()
        self.assertEqual(v.normalized_plate, "46د11133")

    # 3. Duplicate normalized plates rejected by unique constraint
    def test_duplicate_normalized_plates_rejected_by_db(self):
        """
        Database UniqueConstraint prevents introducing duplicate vehicles with same normalized plate,
        even if display formatting differs (e.g. Persian digits vs English digits).
        """
        Vehicle.objects.create(
            plate_display="12 ع 345 - ایران 64",
            vehicle_type=self.vehicle_type
        )

        # Attempt to insert vehicle with Persian digits equivalent
        with self.assertRaises(IntegrityError):
            Vehicle.objects.create(
                plate_display="۱۲ ع ۳۴۵ - ایران ۶۴",
                vehicle_type=self.vehicle_type
            )

    # 4. Existing plate lookup via ajax_plate_lookup (fast indexed search)
    def test_ajax_plate_lookup_finds_vehicle_across_formats(self):
        """
        ajax_plate_lookup finds the vehicle using indexed normalized_plate
        when queried with English digits, Persian digits, or unformatted input.
        """
        v = Vehicle.objects.create(
            plate_display="55 ق 777 - ایران 44",
            vehicle_type=self.vehicle_type,
            default_driver=self.driver,
            empty_weight=Decimal("14500.00")
        )

        url = reverse("weighbridge:ajax_plate_lookup")

        # Test A: Query with Persian digits
        res_fa = self.client.get(url, {"plate": "۵۵ ق ۷۷۷ - ایران ۴۴"})
        self.assertEqual(res_fa.status_code, 200)
        data_fa = res_fa.json()
        self.assertEqual(data_fa["vehicle_id"], v.id)
        self.assertEqual(data_fa["driver_name"], self.driver.full_name)
        self.assertEqual(data_fa["empty_weight"], 14500.0)

        # Test B: Query with unformatted string
        res_raw = self.client.get(url, {"plate": "55ق77744"})
        self.assertEqual(res_raw.status_code, 200)
        data_raw = res_raw.json()
        self.assertEqual(data_raw["vehicle_id"], v.id)

    # 5. New plate registration via VehicleDriverRegistrationService
    def test_new_plate_registration_via_service(self):
        """
        VehicleDriverRegistrationService resolves existing vehicle by normalized_plate
        or automatically creates a new vehicle with synchronized normalized_plate.
        """
        ticket = WeighTicket(
            license_plate_display="88 ص 222 - ایران 99",
            first_weight=Decimal("16000.00"),
            product=self.product,
            party=self.party,
            operation_type=self.op_type,
            first_weight_operator=self.operator_user,
        )

        VehicleDriverRegistrationService.resolve_or_create(ticket, {
            "license_plate_display": "88 ص 222 - ایران 99",
            "driver_name_custom": "حامد علوی",
            "driver_mobile_custom": "09123334455",
            "vehicle_type": self.vehicle_type,
        })

        self.assertIsNotNone(ticket.vehicle)
        self.assertEqual(ticket.vehicle.normalized_plate, "88ص22299")
        self.assertEqual(Vehicle.objects.filter(normalized_plate="88ص22299").count(), 1)

    # 6. Blocked plates validation preserved
    def test_blocked_plates_validation_preserved(self):
        """
        Blocked plates check remains authoritative in ajax_plate_lookup.
        """
        BlockedPlate.objects.create(
            license_plate_display="99 ط 999 - ایران 11",
            normalized_plate="99ط99911",
            reason="تخلف اضافه بار غیرمجاز",
            is_active=True,
            blocked_by=self.operator_user
        )

        url = reverse("weighbridge:ajax_plate_lookup")
        res = self.client.get(url, {"plate": "۹۹ ط ۹۹۹ - ایران ۱۱"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("is_blocked"))
        self.assertIn("تخلف اضافه بار", data.get("block_reason"))

    # 7. First weighing integration
    def test_first_weighing_integration_creates_vehicle_with_normalized_plate(self):
        """
        Submitting ticket_create creates vehicle and saves ticket with proper normalized_plate.
        """
        payload = {
            "weight_mode": "empty_first",
            "operation_type": self.op_type.id,
            "party": self.party.id,
            "product": self.product.id,
            "vehicle_type": self.vehicle_type.id,
            "driver_name_custom": "سهراب سپهری",
            "driver_mobile_custom": "09128887766",
            "origin": self.origin.id,
            "destination": self.dest.id,
            "unload_location": self.unload_loc.id,
            "plate_part1": "33",
            "plate_letter": "م",
            "plate_part2": "444",
            "plate_iran": "55",
            "license_plate_display": "33 م 444 - ایران 55",
            "first_weight": "15200",
            "load_count": "1",
            "sent_weight": "0",
            "loss_percent": "0",
            "loss_weight": "0",
            "submit_action": "save_and_new"
        }

        response = self.client.post(reverse("weighbridge:ticket_create"), payload)
        self.assertRedirects(response, reverse("weighbridge:ticket_create"))

        ticket = WeighTicket.objects.latest("id")
        self.assertIsNotNone(ticket.vehicle)
        self.assertEqual(ticket.vehicle.normalized_plate, "33م44455")
        self.assertEqual(ticket.normalized_plate, "33م44455")

    # 8. Empty plate allowed without uniqueness violation
    def test_empty_plate_allowed_without_uniqueness_collision(self):
        """
        Multiple vehicles without plate (empty display/normalized) can coexist
        thanks to partial UniqueConstraint condition.
        """
        v1 = Vehicle.objects.create(plate_display="بدون پلاک", vehicle_type=self.vehicle_type)
        v2 = Vehicle.objects.create(plate_display="بدون پلاک", vehicle_type=self.vehicle_type)
        self.assertEqual(v1.normalized_plate, "")
        self.assertEqual(v2.normalized_plate, "")
        self.assertNotEqual(v1.id, v2.id)


class ConcurrentVehicleRegistrationTests(TransactionTestCase):
    """
    Concurrency tests for vehicle registration using real database commits.
    """

    def setUp(self):
        self.op_user = User.objects.create_user(username="concur_op", password="password123")
        self.v_type = VehicleType.objects.create(name="کامیون جفت", code="TR-DOUBLE")
        self.plate_str = "66 ل 777 - ایران 88"
        self.norm_plate = normalize_plate(self.plate_str)

    def tearDown(self):
        Vehicle.objects.filter(normalized_plate=self.norm_plate).delete()

    def test_concurrent_registration_creates_exactly_one_vehicle(self):
        """
        Two simultaneous calls to resolve_or_create for the same vehicle plate
        must create exactly ONE Vehicle record without throwing unhandled exceptions.
        Both threads must resolve to the exact same vehicle ID.
        """
        Vehicle.objects.filter(normalized_plate=self.norm_plate).delete()

        barrier = threading.Barrier(2)
        results = []
        errors = []

        def worker(worker_id):
            from django.db import connection
            connection.close()
            try:
                ticket = WeighTicket(license_plate_display=self.plate_str)
                barrier.wait()
                v, d = VehicleDriverRegistrationService.resolve_or_create(ticket, {
                    "license_plate_display": self.plate_str,
                    "driver_name_custom": f"راننده همزمان {worker_id}",
                    "driver_mobile_custom": "09121239988",
                    "vehicle_type": self.v_type,
                })
                results.append((worker_id, v.id if v else None))
            except Exception as e:
                errors.append((worker_id, type(e).__name__, str(e)))
            finally:
                connection.close()

        t1 = threading.Thread(target=worker, args=(1,))
        t2 = threading.Thread(target=worker, args=(2,))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(errors, [], f"Encountered unexpected concurrency errors: {errors}")
        self.assertEqual(len(results), 2)
        self.assertIsNotNone(results[0][1])
        self.assertEqual(results[0][1], results[1][1], "Both threads must resolve to the identical vehicle ID")

        created_count = Vehicle.objects.filter(normalized_plate=self.norm_plate).count()
        self.assertEqual(created_count, 1)


class SafeVehiclePlateLookupTests(TestCase):
    """
    Automated regression tests for Hotfix 2: Safe vehicle plate lookup.
    """

    def setUp(self):
        self.operator_user = User.objects.create_user(username="hotfix2_op", password="password123")
        self.operator_user.profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        self.operator_user.profile.save()

        self.client = Client()
        self.client.force_login(self.operator_user)

        self.v_type = VehicleType.objects.create(name="تریلی لبه‌دار", code="TR-LIP")
        self.driver = Driver.objects.create(full_name="کریم باقری", mobile="09129876543")

        self.vehicle = Vehicle.objects.create(
            plate_display="12 ع 345 - ایران 67",
            normalized_plate="12ع34567",
            vehicle_type=self.v_type,
            default_driver=self.driver,
            empty_weight=Decimal("15200.00"),
        )

        self.url = reverse("weighbridge:ajax_plate_lookup")

    def test_partial_plate_returns_incomplete_without_binding(self):
        """
        Partial plate queries (e.g. '12' or '12 ع') must return is_incomplete=True,
        must NEVER bind vehicle, driver, tare weight, or open-ticket state.
        """
        for partial in ["12", "12 ع", "12ع"]:
            response = self.client.get(self.url, {"plate": partial})
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertTrue(data.get("is_incomplete"))
            self.assertFalse(data.get("found"))
            self.assertFalse(data.get("is_duplicate"))
            self.assertFalse(data.get("has_open_ticket"))
            self.assertIsNone(data.get("vehicle_id"))
            self.assertNotIn("open_ticket", data)

    def test_substring_queries_do_not_match_arbitrary_vehicles(self):
        """
        Querying a substring (e.g. '345') must NOT match '12 ع 345 - ایران 67'.
        """
        response = self.client.get(self.url, {"plate": "345"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data.get("found"))
        self.assertIsNone(data.get("vehicle_id"))

    def test_exact_lookup_persian_and_english_digits(self):
        """
        Exact plate queries with Persian or English digits resolve instantly
        to the exact vehicle record.
        """
        # English digits
        resp_en = self.client.get(self.url, {"plate": "12 ع 345 - ایران 67"})
        self.assertEqual(resp_en.status_code, 200)
        data_en = resp_en.json()
        self.assertTrue(data_en.get("found"))
        self.assertEqual(data_en.get("vehicle_id"), self.vehicle.id)
        self.assertEqual(data_en.get("driver_name"), "کریم باقری")

        # Persian digits
        resp_fa = self.client.get(self.url, {"plate": "۱۲ ع ۳۴۵ - ایران ۶۷"})
        self.assertEqual(resp_fa.status_code, 200)
        data_fa = resp_fa.json()
        self.assertTrue(data_fa.get("found"))
        self.assertEqual(data_fa.get("vehicle_id"), self.vehicle.id)
        self.assertEqual(data_fa.get("driver_name"), "کریم باقری")

    def test_open_ticket_isolated_to_exact_vehicle(self):
        """
        Open ticket for vehicle A must NEVER be returned when querying a partial plate
        or another vehicle.
        """
        open_t = WeighTicket.objects.create(
            serial_number="WB-OPEN-101",
            license_plate_display=self.vehicle.plate_display,
            normalized_plate=self.vehicle.normalized_plate,
            vehicle=self.vehicle,
            driver=self.driver,
            first_weight=Decimal("38000.00"),
            status=TicketStatus.WAITING_SECOND,
        )

        # Query exact plate -> returns open ticket
        resp = self.client.get(self.url, {"plate": self.vehicle.plate_display})
        data = resp.json()
        self.assertTrue(data.get("has_open_ticket"))
        self.assertEqual(data.get("open_ticket", {}).get("serial_number"), "WB-OPEN-101")

        # Query partial plate '12' -> NEVER returns open ticket
        resp_partial = self.client.get(self.url, {"plate": "12"})
        data_p = resp_partial.json()
        self.assertFalse(data_p.get("has_open_ticket"))
        self.assertNotIn("open_ticket", data_p)


class DatabaseIndexCleanlinessTests(TestCase):
    """
    Automated regression tests for Hotfix 3: Database index cleanliness.
    """

    def test_no_redundant_indexes_on_masterdata_vehicle(self):
        """
        Verify that PostgreSQL has exactly ONE index for normalized_plate uniqueness/lookup
        and exactly ONE index for plate_display lookup.
        """
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT indexname, indexdef 
                FROM pg_indexes 
                WHERE tablename = 'masterdata_vehicle'
                ORDER BY indexname;
            """)
            indexes = {row[0]: row[1] for row in cursor.fetchall()}

        # Verify only unique_vehicle_normalized_plate exists for normalized_plate
        norm_plate_indexes = [name for name, defn in indexes.items() if "normalized_plate" in defn]
        self.assertEqual(
            norm_plate_indexes, 
            ["unique_vehicle_normalized_plate"],
            f"Found redundant normalized_plate indexes: {norm_plate_indexes}"
        )

        # Verify only idx_vehicle_plate_disp exists for plate_display
        plate_disp_indexes = [name for name, defn in indexes.items() if "plate_display" in defn]
        self.assertEqual(
            plate_disp_indexes, 
            ["idx_vehicle_plate_disp"],
            f"Found redundant plate_display indexes: {plate_disp_indexes}"
        )
