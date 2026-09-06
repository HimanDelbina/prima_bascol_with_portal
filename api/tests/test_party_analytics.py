from decimal import Decimal
from datetime import date, time, timedelta
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.core.exceptions import ValidationError

from accounts.models import RoleChoices
from masterdata.models import Party, Product, OperationType, Driver, Vehicle
from weighbridge.models import WeighTicket, TicketStatus, WeightMode
from monitoring.models import MonitoringAlert, AlertType, AlertSeverity, AlertStatus
from audit.models import AuditLog, AuditAction
from management.models import PartyScoringConfig, PartyScoreSnapshot, ScoreConfidence, ScoreLevel, TrendDirection
from management.party_analytics_service import PartyAnalyticsService


class PartyAnalyticsAndScoringTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Users
        self.admin = User.objects.create_superuser(username="admin_scoring", password="password123")
        self.manager = User.objects.create_user(username="manager_scoring", password="password123")
        self.manager.profile.role = RoleChoices.WEIGHBRIDGE_MANAGER
        self.manager.profile.save()

        self.operator = User.objects.create_user(username="op_scoring", password="password123")
        self.operator.profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        self.operator.profile.save()

        # Masterdata
        self.product = Product.objects.create(
            name="کنسانتره سنگ آهن",
            code="CONC-01",
            standard_tolerance_kg=Decimal("50.00"),
            default_loss_percent=Decimal("0.50")
        )

        self.party_insufficient = Party.objects.create(name="تأمین‌کننده تازه‌وارد", party_type="supplier")
        self.party_high_acc = Party.objects.create(name="شرکت فولاد پارس (دقت بالا)", party_type="supplier")
        self.party_high_disc = Party.objects.create(name="شرکت بارآوران (مغایرت بالا)", party_type="supplier")
        self.party_high_loss = Party.objects.create(name="شرکت کانسار (افت بالا)", party_type="supplier")

        self.op_in = OperationType.objects.create(name="ورود مواد اولیه", direction="inbound")
        self.driver = Driver.objects.create(full_name="حمید سهرابی")
        self.vehicle = Vehicle.objects.create(plate_display="34 ب 567 ایران 11")

        today = date.today()

        # 1. Party with insufficient data (only 3 tickets)
        for i in range(3):
            WeighTicket.objects.create(
                serial_number=f"INSUF-{i+1}",
                party=self.party_insufficient,
                product=self.product,
                operation_type=self.op_in,
                driver=self.driver,
                vehicle=self.vehicle,
                first_weight_date=today,
                first_weight_time=time(8, 0),
                second_weight_date=today,
                second_weight_time=time(8, 35),
                gross_weight=Decimal("30000"),
                tare_weight=Decimal("10000"),
                net_weight=Decimal("20000"),
                sent_weight=Decimal("20020"),
                weight_difference=Decimal("-20"),
                loss_weight=Decimal("100"),
                loss_percent=Decimal("0.50"),
                final_weight=Decimal("19900"),
                status=TicketStatus.COMPLETED
            )

        # 2. Party with high accuracy (25 tickets, low discrepancy, low loss, good turnaround)
        for i in range(25):
            t = WeighTicket.objects.create(
                serial_number=f"HIGH-ACC-{i+1}",
                party=self.party_high_acc,
                product=self.product,
                operation_type=self.op_in,
                driver=self.driver,
                vehicle=self.vehicle,
                first_weight_date=today - timedelta(days=i % 15),
                first_weight_time=time(9, 0),
                second_weight_date=today - timedelta(days=i % 15),
                second_weight_time=time(9, 40), # 40 min turnaround
                gross_weight=Decimal("32000"),
                tare_weight=Decimal("11000"),
                net_weight=Decimal("21000"),
                sent_weight=Decimal("21015"),
                weight_difference=Decimal("-15"), # only 15 kg difference
                is_tolerance_exceeded=False,
                loss_weight=Decimal("80"),
                loss_percent=Decimal("0.38"), # below 0.50% baseline
                final_weight=Decimal("20920"),
                status=TicketStatus.COMPLETED
            )

        # 3. Party with high discrepancy and alerts (25 tickets, high discrepancy, high loss, critical alerts)
        for i in range(25):
            t = WeighTicket.objects.create(
                serial_number=f"HIGH-DISC-{i+1}",
                party=self.party_high_disc,
                product=self.product,
                operation_type=self.op_in,
                driver=self.driver,
                vehicle=self.vehicle,
                first_weight_date=today - timedelta(days=i % 15),
                first_weight_time=time(10, 0),
                second_weight_date=today - timedelta(days=i % 15),
                second_weight_time=time(12, 10), # 130 min turnaround (long wait)
                gross_weight=Decimal("35000"),
                tare_weight=Decimal("11000"),
                net_weight=Decimal("24000"),
                sent_weight=Decimal("24250"),
                weight_difference=Decimal("-250"), # 250 kg discrepancy!
                is_tolerance_exceeded=True,
                loss_weight=Decimal("350"),
                loss_percent=Decimal("1.45"), # much higher than baseline
                final_weight=Decimal("23650"),
                status=TicketStatus.COMPLETED
            )
            # Add alerts to some tickets of this party
            if i < 4:
                MonitoringAlert.objects.create(
                    ticket=t,
                    alert_type=AlertType.WEIGHT_DISCREPANCY,
                    severity=AlertSeverity.CRITICAL,
                    title="مغایرت شدید وزن ارسالی",
                    deviation_value=Decimal("250.00"),
                    status=AlertStatus.OPEN
                )
            if i in [5, 6, 7]:
                MonitoringAlert.objects.create(
                    ticket=t,
                    alert_type=AlertType.LONG_WAITING_TIME,
                    severity=AlertSeverity.HIGH,
                    title="توقف غیرعادی خودرو",
                    deviation_value=Decimal("130.00"),
                    status=AlertStatus.OPEN
                )

    def test_party_with_insufficient_history(self):
        """Party with <10 tickets must have INSUFFICIENT confidence and no misleading score."""
        analysis = PartyAnalyticsService.analyze_party(self.party_insufficient)
        score_data = analysis['score']
        
        self.assertEqual(score_data['confidence'], ScoreConfidence.INSUFFICIENT)
        self.assertIsNone(score_data['overall_score'])
        self.assertFalse(score_data['is_score_reliable'])
        self.assertEqual(analysis['profile']['completed_tickets'], 3)
        self.assertGreater(len(score_data['explanation']['positive_points']), 0)

    def test_high_accuracy_vs_high_discrepancy_score(self):
        """Party A (high accuracy) must score significantly higher than Party B (high discrepancy/alerts)."""
        analysis_a = PartyAnalyticsService.analyze_party(self.party_high_acc)
        analysis_b = PartyAnalyticsService.analyze_party(self.party_high_disc)

        score_a = analysis_a['score']
        score_b = analysis_b['score']

        self.assertIsNotNone(score_a['overall_score'])
        self.assertIsNotNone(score_b['overall_score'])
        self.assertGreater(score_a['overall_score'], 80.0)
        self.assertLess(score_b['overall_score'], 60.0)

        # Dimension scores
        self.assertGreater(score_a['dimension_scores']['weight_accuracy'], score_b['dimension_scores']['weight_accuracy'])
        self.assertGreater(score_a['dimension_scores']['monitoring_quality'], score_b['dimension_scores']['monitoring_quality'])
        self.assertGreater(score_a['dimension_scores']['operational_efficiency'], score_b['dimension_scores']['operational_efficiency'])

    def test_scoring_weights_validation(self):
        """Scoring config weights must strictly sum to 100% and be non-negative."""
        config = PartyScoringConfig.get_config()

        # Valid update
        config.dimension_weights = {
            'weight_accuracy': 35,
            'loss_performance': 25,
            'consistency': 15,
            'monitoring_quality': 15,
            'operational_efficiency': 5,
            'data_reliability': 5,
        }
        config.full_clean()
        config.save()
        self.assertEqual(sum(config.dimension_weights.values()), 100)

        # Invalid update (sum != 100)
        config.dimension_weights['weight_accuracy'] = 50
        with self.assertRaises(ValidationError):
            config.full_clean()

    def test_ranking_minimum_sample_filtering(self):
        """Parties with fewer tickets than minimum_tickets_for_ranking must be excluded from ranking."""
        ranking = PartyAnalyticsService.get_party_ranking(minimum_tickets=20)
        ranked_ids = [item['party_id'] for item in ranking]

        # 25-ticket parties should be included
        self.assertIn(self.party_high_acc.id, ranked_ids)
        self.assertIn(self.party_high_disc.id, ranked_ids)

        # 3-ticket party must be excluded
        self.assertNotIn(self.party_insufficient.id, ranked_ids)

        # High accuracy party must rank #1
        self.assertEqual(ranking[0]['party_id'], self.party_high_acc.id)
        self.assertEqual(ranking[0]['rank'], 1)

    def test_trend_comparison(self):
        """Trend calculation must compute deltas and valid directions."""
        trend = PartyAnalyticsService.calculate_trend_analysis(self.party_high_acc, quick_period='this_month')
        self.assertIn('kpi_comparison', trend)
        self.assertIn('score', trend['kpi_comparison'])
        self.assertIn('average_discrepancy_kg', trend['kpi_comparison'])

    def test_api_permissions_and_security(self):
        """Check API access control: unauthenticated -> 401, operator -> 403, manager -> 200."""
        url = reverse('api_v1:management_parties_ranking')

        # 1. Unauthenticated
        res_unauth = self.client.get(url)
        self.assertEqual(res_unauth.status_code, status.HTTP_401_UNAUTHORIZED)

        # 2. Operator
        self.client.force_authenticate(user=self.operator)
        res_op = self.client.get(url)
        self.assertEqual(res_op.status_code, status.HTTP_403_FORBIDDEN)

        # 3. Manager
        self.client.force_authenticate(user=self.manager)
        res_mgr = self.client.get(url)
        self.assertEqual(res_mgr.status_code, status.HTTP_200_OK)

    def test_api_party_analytics_detail_and_score(self):
        """Check API endpoints for detail analytics, score, and comparison."""
        self.client.force_authenticate(user=self.manager)

        # Detail analytics
        url_analytics = reverse('api_v1:management_party_analytics', kwargs={'pk': self.party_high_acc.id})
        res_analytics = self.client.get(url_analytics)
        self.assertEqual(res_analytics.status_code, status.HTTP_200_OK)
        self.assertEqual(res_analytics.data['profile']['completed_tickets'], 25)

        # Score breakdown
        url_score = reverse('api_v1:management_party_score', kwargs={'pk': self.party_high_acc.id})
        res_score = self.client.get(url_score)
        self.assertEqual(res_score.status_code, status.HTTP_200_OK)
        self.assertIn('dimension_scores', res_score.data)
        self.assertIn('explanation', res_score.data)

        # Multi-party comparison
        url_comp = reverse('api_v1:management_parties_compare') + f"?party_ids={self.party_high_acc.id},{self.party_high_disc.id}"
        res_comp = self.client.get(url_comp)
        self.assertEqual(res_comp.status_code, status.HTTP_200_OK)
        self.assertEqual(res_comp.data['parties_count'], 2)

    def test_scoring_config_update_and_audit(self):
        """Updating scoring config via API must record an entry in AuditLog (source='API')."""
        self.client.force_authenticate(user=self.manager)
        url_config = reverse('api_v1:management_parties_config')

        res_get = self.client.get(url_config)
        self.assertEqual(res_get.status_code, status.HTTP_200_OK)

        # Update weights
        put_data = {
            'minimum_tickets_for_ranking': 15,
            'dimension_weights': {
                'weight_accuracy': 30,
                'loss_performance': 20,
                'consistency': 15,
                'monitoring_quality': 20,
                'operational_efficiency': 10,
                'data_reliability': 5,
            }
        }
        res_put = self.client.put(url_config, put_data, format='json')
        self.assertEqual(res_put.status_code, status.HTTP_200_OK)
        self.assertEqual(res_put.data['minimum_tickets_for_ranking'], 15)

        # Verify AuditLog
        audit_entry = AuditLog.objects.filter(
            model_name="PartyScoringConfig",
            action=AuditAction.UPDATE,
            source="API"
        ).first()
        self.assertIsNotNone(audit_entry)
        self.assertEqual(audit_entry.user, self.manager)

    def test_exports_endpoints(self):
        """Check Excel, CSV, and PDF export endpoints."""
        self.client.force_authenticate(user=self.manager)

        # Excel ranking
        res_xlsx_rank = self.client.get(reverse('api_v1:management_parties_export_xlsx'))
        self.assertEqual(res_xlsx_rank.status_code, status.HTTP_200_OK)
        self.assertEqual(res_xlsx_rank['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

        # Excel single party
        res_xlsx_party = self.client.get(reverse('api_v1:management_parties_export_xlsx') + f"?party_id={self.party_high_acc.id}")
        self.assertEqual(res_xlsx_party.status_code, status.HTTP_200_OK)
        self.assertEqual(res_xlsx_party['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

        # CSV ranking
        res_csv = self.client.get(reverse('api_v1:management_parties_export_csv'))
        self.assertEqual(res_csv.status_code, status.HTTP_200_OK)
        self.assertEqual(res_csv['Content-Type'], 'text/csv; charset=utf-8')

        # PDF single party
        res_pdf = self.client.get(reverse('api_v1:management_parties_export_pdf') + f"?party_id={self.party_high_acc.id}")
        self.assertEqual(res_pdf.status_code, status.HTTP_200_OK)
        self.assertEqual(res_pdf['Content-Type'], 'application/pdf')
