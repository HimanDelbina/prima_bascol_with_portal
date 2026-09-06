import re
from datetime import date, datetime
import jdatetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from masterdata.models import Party
from management.models import PartyScoringConfig, PartyScoreSnapshot
from management.party_analytics_service import PartyAnalyticsService
from core.jalali import (
    jalali_to_gregorian, get_jalali_range_gregorian, get_today_jalali
)


class Command(BaseCommand):
    help = 'محاسبه و ثبت اسنپ‌شات دوره‌ای امتیاز طرف‌حساب‌ها و تأمین‌کنندگان (Phase 4 Scoring Engine)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--period',
            type=str,
            default='month',
            help='نوع دوره محاسباتی: month, year, custom (پیش‌فرض: month)'
        )
        parser.add_argument(
            '--date',
            type=str,
            default=None,
            help='تاریخ مبنا (شمسی مثلاً 1405/06 یا میلادی 2026-09-01)'
        )
        parser.add_argument(
            '--party-id',
            type=int,
            default=None,
            help='شناسه طرف‌حساب خاص جهت محاسبه انفرادی'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='اجرای آزمایشی و چاپ نتایج بدون ذخیره در پایگاه داده'
        )

    def handle(self, *args, **options):
        period_type = options['period']
        date_str = options['date']
        party_id = options['party_id']
        dry_run = options['dry_run']

        config = PartyScoringConfig.get_config()
        self.stdout.write(self.style.NOTICE(f'=== آغاز محاسبه امتیاز طرف‌حساب‌ها (نسخه: {config.calculation_version}) ==='))

        # تعیین محدوده تاریخی
        if not date_str:
            curr_start, curr_end = get_jalali_range_gregorian('this_month')
        else:
            # بررسی فرمت شمسی یا میلادی
            if '/' in date_str:
                parts = date_str.split('/')
                if len(parts) == 2:
                    y, m = int(parts[0]), int(parts[1])
                    j_start = jdatetime.date(y, m, 1)
                    if m <= 6:
                        days = 31
                    elif m <= 11:
                        days = 30
                    else:
                        days = 29 if not j_start.isleap() else 30
                    j_end = jdatetime.date(y, m, days)
                    curr_start = j_start.togregorian()
                    curr_end = j_end.togregorian()
                elif len(parts) == 3:
                    j_d = jalali_to_gregorian(date_str)
                    curr_start = j_d
                    curr_end = j_d
                else:
                    curr_start, curr_end = get_jalali_range_gregorian('this_month')
            else:
                curr_start = datetime.strptime(date_str, '%Y-%m-%d').date()
                curr_end = curr_start

        self.stdout.write(f'بازه محاسباتی: {curr_start} تا {curr_end}')

        if party_id:
            parties = Party.objects.filter(id=party_id, is_active=True)
            if not parties.exists():
                self.stdout.write(self.style.ERROR(f'طرف‌حساب با شناسه {party_id} یافت نشد.'))
                return
        else:
            parties = Party.objects.filter(is_active=True)

        self.stdout.write(f'تعداد طرف‌های حساب در صف بررسی: {parties.count()}')

        calculated_count = 0
        saved_count = 0

        for party in parties:
            analysis = PartyAnalyticsService.analyze_party(
                party=party,
                start_date=curr_start,
                end_date=curr_end,
                config=config
            )

            score_res = analysis['score']
            profile = analysis['profile']
            completed_count = profile['completed_tickets']

            overall_sc = score_res['overall_score']
            level_fa = score_res['level_fa']
            conf_fa = score_res['confidence_fa']

            disp_sc = overall_sc if overall_sc is not None else "داده ناکافی"
            self.stdout.write(
                f'Party #{party.id} ({party.name}): قبوض: {completed_count} | '
                f'امتیاز: {disp_sc} | '
                f'سطح: {level_fa} | اطمینان: {conf_fa}'
            )

            calculated_count += 1

            if not dry_run:
                snapshot, created = PartyScoreSnapshot.objects.update_or_create(
                    party=party,
                    period_start=curr_start,
                    period_end=curr_end,
                    calculation_version=config.calculation_version,
                    defaults={
                        'period_type': period_type,
                        'overall_score': overall_sc,
                        'score_level': score_res['level'],
                        'score_level_fa': level_fa,
                        'confidence': score_res['confidence'],
                        'confidence_fa': conf_fa,
                        'ticket_count': completed_count,
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
                saved_count += 1

        if dry_run:
            self.stdout.write(self.style.WARNING(f'اجرا به پایان رسید (حالت آزمایشی Dry-Run: {calculated_count} محاسبه انجام شد ولی هیچ اسنپ‌شاتی ذخیره نشد).'))
        else:
            self.stdout.write(self.style.SUCCESS(f'موفقیت: تعداد {saved_count} اسنپ‌شات امتیاز در پایگاه داده ثبت شد.'))
