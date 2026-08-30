from django.test import TestCase
from decimal import Decimal
from django.utils import timezone
from datetime import time

from weighbridge.models import WeighTicket, TicketStatus
from masterdata.models import Product, Party
from reports.services import ReportService
from reports.preset_reports import PRESET_REPORTS, get_preset_report_by_code

class ReportServiceTests(TestCase):
    def setUp(self):
        self.p1 = Product.objects.create(name="آهن اسفنجی")
        self.p2 = Product.objects.create(name="گندله")
        self.party1 = Party.objects.create(name="فولاد خوزستان")
        self.party2 = Party.objects.create(name="فولاد مبارکه")

        today = timezone.localdate()

        WeighTicket.objects.create(
            serial_number="T-1",
            status=TicketStatus.COMPLETED,
            product=self.p1,
            party=self.party1,
            first_weight=Decimal("30000.00"),
            second_weight=Decimal("10000.00"),
            gross_weight=Decimal("30000.00"),
            tare_weight=Decimal("10000.00"),
            net_weight=Decimal("20000.00"),
            final_weight=Decimal("20000.00"),
            first_weight_date=today,
            first_weight_time=time(10, 0),
            license_plate_display="12 ج 345 - ایران 67"
        )

        WeighTicket.objects.create(
            serial_number="T-2",
            status=TicketStatus.COMPLETED,
            product=self.p2,
            party=self.party2,
            first_weight=Decimal("40000.00"),
            second_weight=Decimal("15000.00"),
            gross_weight=Decimal("40000.00"),
            tare_weight=Decimal("15000.00"),
            net_weight=Decimal("25000.00"),
            final_weight=Decimal("25000.00"),
            first_weight_date=today,
            first_weight_time=time(11, 0),
            license_plate_display="34 ج 567 - ایران 88"
        )

    def test_filter_and_summary_metrics(self):
        qs = ReportService.filter_tickets({"product": str(self.p1.id)})
        self.assertEqual(qs.count(), 1)
        
        summaries = ReportService.get_summary_metrics(qs)
        self.assertEqual(summaries["total_tickets"], 1)
        self.assertEqual(summaries["sum_net"], Decimal("20000.00"))

    def test_all_summary_metrics(self):
        qs = ReportService.filter_tickets({})
        self.assertEqual(qs.count(), 2)
        
        summaries = ReportService.get_summary_metrics(qs)
        self.assertEqual(summaries["total_tickets"], 2)
        self.assertEqual(summaries["sum_net"], Decimal("45000.00"))
        self.assertEqual(summaries["sum_gross"], Decimal("70000.00"))
        self.assertEqual(summaries["sum_tare"], Decimal("25000.00"))

    def test_group_by_product(self):
        qs = ReportService.filter_tickets({})
        group_data = ReportService.group_by_field(qs, "product")
        self.assertEqual(len(group_data), 2)

    def test_preset_reports_exist(self):
        self.assertEqual(len(PRESET_REPORTS), 30)
        daily_rep = get_preset_report_by_code("daily")
        self.assertIsNotNone(daily_rep)
        self.assertEqual(daily_rep["title"], "گزارش روزانه باسکول")
