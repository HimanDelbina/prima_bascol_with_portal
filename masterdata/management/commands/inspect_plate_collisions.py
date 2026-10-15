import os
from collections import defaultdict
from django.core.management.base import BaseCommand
from masterdata.models import Vehicle
from weighbridge.plate_policy import normalize_plate


class Command(BaseCommand):
    help = "Inspects existing Vehicle records, detects normalized plate collisions, and generates a report."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            type=str,
            default="PLATE_COLLISION_REPORT.md",
            help="Path to output markdown report file"
        )
        parser.add_argument(
            "--resolve-unreferenced",
            action="store_true",
            help="Safely remove duplicate vehicles that have 0 tickets and identical plate attributes"
        )

    def handle(self, *args, **options):
        vehicles = list(Vehicle.objects.all().order_by("id"))
        self.stdout.write(f"Inspecting {len(vehicles)} vehicle records in database...")

        plate_groups = defaultdict(list)
        for v in vehicles:
            norm = normalize_plate(v.plate_display)
            plate_groups[norm].append(v)

        collisions = {k: v_list for k, v_list in plate_groups.items() if len(v_list) > 1}

        lines = [
            "# گزارش بازرسی و تشخیص تداخل پلاک‌های خودرو (Vehicle Plate Collision Report)",
            f"- **تعداد کل رکوردهای خودرو:** {len(vehicles)}",
            f"- **تعداد پلاک‌های نرمال یکتا:** {len(plate_groups)}",
            f"- **تعداد موارد تداخل (Collisions):** {len(collisions)}",
            "",
            "## جدول تفصیلی تداخل‌ها",
        ]

        if not collisions:
            lines.append("✅ هیچ تداخلی بین پلاک‌های استانداردشده در پایگاه داده یافت نشد.")
            self.stdout.write(self.style.SUCCESS("No plate collisions detected."))
        else:
            self.stdout.write(self.style.WARNING(f"Detected {len(collisions)} plate collision(s)!"))
            lines.extend([
                "| پلاک نرمال | شناسه خودرو (ID) | پلاک نمایشی | تاریخ ایجاد | تعداد قبوض | وضعیت فعال |",
                "| :---: | :---: | :---: | :---: | :---: | :---: |"
            ])
            for norm_p, v_list in collisions.items():
                self.stdout.write(f"\n[Collision] Normalized Plate: {norm_p}")
                for v in v_list:
                    t_count = v.tickets.count()
                    self.stdout.write(
                        f"  - ID: {v.id} | Display: {v.plate_display} | Created: {v.created_at} | Tickets: {t_count} | Active: {v.is_active}"
                    )
                    lines.append(
                        f"| `{norm_p}` | `{v.id}` | {v.plate_display} | {v.created_at.strftime('%Y-%m-%d %H:%M:%S')} | {t_count} | {'فعال' if v.is_active else 'غیرفعال'} |"
                    )

            if options["resolve_unreferenced"]:
                self.stdout.write("\nResolving unreferenced duplicates...")
                resolved_count = 0
                for norm_p, v_list in collisions.items():
                    # Keep the earliest record (lowest ID or with tickets)
                    # Find candidate to keep: primary with most tickets, or earliest ID
                    sorted_v = sorted(v_list, key=lambda x: (-x.tickets.count(), x.id))
                    keep_v = sorted_v[0]
                    duplicates = sorted_v[1:]

                    for dup in duplicates:
                        if dup.tickets.count() == 0 and dup.plate_display == keep_v.plate_display:
                            self.stdout.write(self.style.NOTICE(f"  Removing unreferenced duplicate ID {dup.id} (keeping ID {keep_v.id})"))
                            dup.delete()
                            resolved_count += 1
                        else:
                            self.stdout.write(self.style.ERROR(
                                f"  SKIPPING ID {dup.id}: Has {dup.tickets.count()} tickets or different display. Manual resolution required."
                            ))
                self.stdout.write(self.style.SUCCESS(f"Resolved {resolved_count} unreferenced duplicate(s)."))

        output_path = options["output"]
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        self.stdout.write(self.style.SUCCESS(f"Collision report written to {output_path}"))
