import random
import sys
from datetime import date, time, datetime, timedelta
from decimal import Decimal
import jdatetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth.models import User

from masterdata.models import (
    Party, Product, Driver, Vehicle, Location, UnloadLocation,
    OperationType, LossType
)
from weighbridge.models import WeighTicket, TicketStatus, WeightMode
from monitoring.models import MonitoringAlert, AlertType, AlertSeverity, AlertStatus
from management.models import PartyScoringConfig, PartyScoreSnapshot
from management.party_analytics_service import PartyAnalyticsService
from core.jalali import get_jalali_range_gregorian


class Command(BaseCommand):
    help = 'ایجاد داده‌های تستی غنی برای سناریوهای رتبه‌بندی، مقایسه و کارنامه عملکرد طرف‌حساب‌ها (Phase 4)'

    def safe_write(self, msg, style_func=None):
        try:
            if style_func:
                self.stdout.write(style_func(msg))
            else:
                self.stdout.write(msg)
        except Exception:
            try:
                print(msg)
            except Exception:
                pass

    def handle(self, *args, **options):
        if hasattr(sys.stdout, 'reconfigure'):
            try:
                sys.stdout.reconfigure(encoding='utf-8')
            except Exception:
                pass

        self.safe_write('=== آغاز ایجاد داده‌های تستی رتبه‌بندی طرف‌های حساب ===', self.style.NOTICE)

        # پایه داده‌ها
        op_user = User.objects.filter(is_superuser=True).first() or User.objects.first()
        op_in = OperationType.objects.filter(code='OP-IN').first() or OperationType.objects.first()
        op_out = OperationType.objects.filter(code='OP-OUT').first() or OperationType.objects.first()
        loss_moist = LossType.objects.filter(code='LS-MOIST').first() or LossType.objects.first()
        loss_leak = LossType.objects.filter(code='LS-LEAK').first() or LossType.objects.first()

        drivers = list(Driver.objects.all())
        vehicles = list(Vehicle.objects.all())
        locations = list(Location.objects.all())
        ulocs = list(UnloadLocation.objects.all())
        products = list(Product.objects.all())

        if not (drivers and vehicles and locations and products):
            self.safe_write('اطلاعات پایه ناقص است. لطفاً ابتدا seed_data را اجرا کنید.', self.style.ERROR)
            return

        # بررسی طرف‌های حساب
        parties = {p.id: p for p in Party.objects.all()}
        self.safe_write(f'طرف‌های حساب موجود: {len(parties)}')

        # محدوده تاریخی ماه جاری شمسی
        start_month, end_month = get_jalali_range_gregorian('this_month')
        days_in_month = (end_month - start_month).days + 1
        today = timezone.localdate()

        # تعریف پروفایل‌های عملکردی برای طرف‌های حساب:
        # 1: فولاد خوزستان -> عالی (رتبه ۱)
        # 2: فولاد مبارکه -> خوب (رتبه ۲)
        # 3: چادرملو -> قابل قبول (رتبه ۳)
        # 4: گل‌گهر سیرجان -> نیازمند بررسی (رتبه ۴)
        # 5: فولاد کاوه جنوب -> داده ناکافی (۵ قبض)
        # 6: بارگستر شرق -> پیمانکار حمل
        profiles = {
            1: {
                'tickets_count': 26,
                'avg_discrepancy_range': (-10, 10),
                'loss_range': (0.1, 0.3),
                'turnaround_range': (18, 26),
                'alerts': 0,
            },
            2: {
                'tickets_count': 24,
                'avg_discrepancy_range': (15, 35),
                'loss_range': (0.35, 0.6),
                'turnaround_range': (28, 42),
                'alerts': 1,
                'alert_type': AlertType.VEHICLE_TARE_ANOMALY,
                'alert_severity': AlertSeverity.LOW,
            },
            3: {
                'tickets_count': 22,
                'avg_discrepancy_range': (35, 65),
                'loss_range': (0.7, 1.1),
                'turnaround_range': (45, 65),
                'alerts': 2,
                'alert_type': AlertType.WEIGHT_DISCREPANCY,
                'alert_severity': AlertSeverity.MEDIUM,
            },
            4: {
                'tickets_count': 21,
                'avg_discrepancy_range': (70, 130),
                'loss_range': (1.3, 2.1),
                'turnaround_range': (65, 95),
                'alerts': 4,
                'alert_type': AlertType.LOSS_ANOMALY,
                'alert_severity': AlertSeverity.HIGH,
            },
            5: {
                'tickets_count': 5,
                'avg_discrepancy_range': (10, 40),
                'loss_range': (0.3, 0.8),
                'turnaround_range': (25, 45),
                'alerts': 0,
            },
            6: {
                'tickets_count': 16,
                'avg_discrepancy_range': (15, 45),
                'loss_range': (0.4, 0.9),
                'turnaround_range': (30, 50),
                'alerts': 1,
                'alert_type': AlertType.LONG_WAITING_TIME,
                'alert_severity': AlertSeverity.MEDIUM,
            },
        }

        # شماره سریال مبنا
        last_t = WeighTicket.objects.order_by('-id').first()
        start_serial_num = (last_t.id + 2000) if last_t else 2000

        total_created = 0
        total_alerts = 0

        for p_id, conf in profiles.items():
            party = parties.get(p_id)
            if not party:
                continue

            num_tickets = conf['tickets_count']
            self.safe_write(f'در حال ایجاد {num_tickets} قبض برای {party.name}...')

            for i in range(num_tickets):
                start_serial_num += 1
                serial = f'WB-SIM-{start_serial_num}'

                # توزیع تاریخ در بازه ماه جاری
                day_offset = int((i / max(num_tickets, 1)) * min(days_in_month - 1, 28))
                t_date = start_month + timedelta(days=day_offset)
                if t_date > today:
                    t_date = today

                turnaround_min = random.randint(*conf['turnaround_range'])
                t_hour = random.randint(7, 16)
                t_minute = random.randint(0, 30)
                t_time1 = time(t_hour, t_minute)
                dt1 = datetime.combine(t_date, t_time1)
                dt2 = dt1 + timedelta(minutes=turnaround_min)
                t_time2 = dt2.time()

                # اوزان
                base_net = Decimal(random.randint(23500, 26500))
                tare_weight = Decimal(random.randint(14500, 16500))
                gross_weight = tare_weight + base_net

                # مغایرت وزن
                disc_kg = Decimal(random.randint(*conf['avg_discrepancy_range']))
                sent_weight = base_net + disc_kg
                diff_kg = base_net - sent_weight  # منفی اگر کسری باشد
                diff_pct = round((diff_kg / sent_weight) * 100, 2)
                is_exceeded = abs(diff_kg) > Decimal('50.0')

                # افت
                loss_pct = Decimal(str(round(random.uniform(*conf['loss_range']), 2)))
                loss_kg = round(base_net * (loss_pct / Decimal('100.0')), 2)
                final_weight = base_net - loss_kg

                veh = random.choice(vehicles)
                drv = random.choice(drivers)
                prod = random.choice(products)
                loc_orig = random.choice(locations)
                loc_dest = locations[0] if locations else loc_orig
                uloc = ulocs[0] if ulocs else None

                ticket = WeighTicket.objects.create(
                    serial_number=serial,
                    status=TicketStatus.COMPLETED,
                    weight_mode=WeightMode.FULL_FIRST,
                    operation_type=op_in,
                    party=party,
                    product=prod,
                    vehicle=veh,
                    driver=drv,
                    license_plate_display=veh.plate_display,
                    waybill_number=f'WB-WAY-{start_serial_num}',
                    origin=loc_orig,
                    destination=loc_dest,
                    unload_location=uloc,
                    first_weight=gross_weight,
                    first_weight_date=t_date,
                    first_weight_time=t_time1,
                    first_weight_operator=op_user,
                    second_weight=tare_weight,
                    second_weight_date=t_date,
                    second_weight_time=t_time2,
                    second_weight_operator=op_user,
                    gross_weight=gross_weight,
                    tare_weight=tare_weight,
                    net_weight=base_net,
                    sent_weight=sent_weight,
                    weight_difference=diff_kg,
                    weight_difference_percent=diff_pct,
                    is_tolerance_exceeded=is_exceeded,
                    loss_weight=loss_kg,
                    loss_percent=loss_pct,
                    loss_type=loss_moist if random.random() > 0.4 else loss_leak,
                    final_weight=final_weight,
                )

                # تنظیم created_at منطبق با تاریخ توزین
                dt_aware = timezone.make_aware(dt1)
                WeighTicket.objects.filter(pk=ticket.pk).update(created_at=dt_aware, updated_at=dt_aware)

                total_created += 1

                # ایجاد هشدار پایش در صورت نیاز
                if conf['alerts'] > 0 and i < conf['alerts']:
                    alert_t = conf.get('alert_type', AlertType.WEIGHT_DISCREPANCY)
                    alert_s = conf.get('alert_severity', AlertSeverity.MEDIUM)
                    MonitoringAlert.objects.create(
                        ticket=ticket,
                        alert_type=alert_t,
                        severity=alert_s,
                        status=AlertStatus.OPEN if i == 0 else AlertStatus.RESOLVED,
                        title=f'ناهنجاری {alert_t}',
                        description=f'سیستم پایش هوشمند انحراف غیرعادی در قبض {serial} را شناسایی کرد.',
                        reason=f'انحراف پارامتر از آستانه مجاز',
                        current_value=abs(diff_kg),
                        baseline_value=Decimal('20.00'),
                        deviation_value=abs(diff_kg) - Decimal('20.00'),
                        deviation_percent=Decimal('35.00'),
                        created_at=dt_aware,
                    )
                    total_alerts += 1

        self.safe_write(f'مجموع {total_created} قبض و {total_alerts} هشدار پایش ایجاد شد.', self.style.SUCCESS)

        # محاسبه و ثبت اسنپ‌شات‌های رتبه‌بندی
        self.safe_write('در حال محاسبه و استخراج رتبه‌بندی طرف‌حساب‌ها...')
        ranking = PartyAnalyticsService.get_party_ranking(start_date=start_month, end_date=end_month, minimum_tickets=0)

        # ایجاد اسنپ شات در دیتابیس
        config = PartyScoringConfig.get_config()
        for party in Party.objects.filter(is_active=True):
            analysis = PartyAnalyticsService.analyze_party(
                party=party,
                start_date=start_month,
                end_date=end_month,
                config=config
            )
            score_res = analysis['score']
            profile = analysis['profile']
            PartyScoreSnapshot.objects.update_or_create(
                party=party,
                period_start=start_month,
                period_end=end_month,
                calculation_version=config.calculation_version,
                defaults={
                    'period_type': 'month',
                    'overall_score': score_res['overall_score'],
                    'score_level': score_res['level'],
                    'score_level_fa': score_res['level_fa'],
                    'confidence': score_res['confidence'],
                    'confidence_fa': score_res['confidence_fa'],
                    'ticket_count': profile['completed_tickets'],
                    'dimension_scores': score_res['dimension_scores'],
                    'metrics_snapshot': {
                        'profile': profile,
                        'discrepancy': analysis['discrepancy_metrics'],
                        'loss': analysis['loss_metrics'],
                        'monitoring': analysis['monitoring_metrics'],
                        'turnaround': analysis['turnaround_metrics'],
                        'corrections': analysis['correction_metrics'],
                        'consistency': analysis['consistency_metrics'],
                    },
                    'explanation': score_res['explanation'],
                }
            )

        self.safe_write('\n' + '='*75)
        self.safe_write(f'{"رتبه":<5} | {"نام طرف حساب":<35} | {"قبوض":<6} | {"امتیاز":<8} | {"سطح":<12} | {"اطمینان":<8}')
        self.safe_write('-'*75)

        for item in ranking:
            sc = item['overall_score']
            sc_str = f"{sc:.1f}" if sc is not None else "داده ناکافی"
            p_name = item['party_name'][:35]
            lvl = item['score_level_fa']
            cnf = item['confidence_fa']
            tc = item['completed_tickets']
            rk = item['rank']
            self.safe_write(
                f"#{rk:<4} | {p_name:<35} | {tc:<6} | {sc_str:<8} | {lvl:<12} | {cnf:<8}"
            )
        self.safe_write('='*75 + '\n')
