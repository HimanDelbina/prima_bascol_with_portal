import sys
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from decimal import Decimal
from datetime import date, time, timedelta
from django.utils import timezone

from core.models import SystemSetting
from accounts.models import UserProfile, RoleChoices
from masterdata.models import (
    Product, Party, Driver, VehicleType, Vehicle, 
    Location, UnloadLocation, OperationType, LossType
)
from weighbridge.models import WeighTicket, TicketStatus, WeightMode
from weighbridge.services import TicketCalculationService, SerialNumberService
from audit.services import log_audit
from audit.models import AuditAction

class Command(BaseCommand):
    help = "Seed initial production & test data for Prima Bascol Weighbridge System."

    def safe_print(self, text, style_func=None):
        try:
            if style_func:
                self.stdout.write(style_func(text))
            else:
                self.stdout.write(text)
        except Exception:
            try:
                print(text.encode("utf-8", errors="replace").decode("ascii", errors="replace"))
            except Exception:
                pass

    def handle(self, *args, **options):
        self.safe_print("Starting Prima Bascol database seed...", self.style.NOTICE)

        # 1. System Settings
        settings_obj, _ = SystemSetting.objects.get_or_create(id=1)
        settings_obj.company_name = "مجتمع صنعتی و معدنی فولاد پریما"
        settings_obj.receipt_header_title = "قبض رسمی توزین و باسکول دیجیتال"
        settings_obj.company_address = "اصفهان، شهرک صنعتی رازی، بلوار فناوری، پلاک ۱۰۰"
        settings_obj.company_phone = "۰۳۱-۳۳۳۳۴۴۴۴"
        settings_obj.company_email = "info@primasteel.ir"
        settings_obj.serial_start_number = 1001
        settings_obj.serial_prefix = "WB-"
        settings_obj.weight_unit = "کیلوگرم"
        settings_obj.max_tolerance_kg = Decimal("50.00")
        settings_obj.max_tolerance_percent = Decimal("1.00")
        settings_obj.default_print_template = "a4"
        settings_obj.receipt_footer_note = "این قبض به عنوان سند رسمی خروج و ورود کالا تلقی شده و بدون مهر و امضا فاقد اعتبار است."
        settings_obj.save()
        self.safe_print("[OK] System settings saved.", self.style.SUCCESS)

        # 2. Users & Roles
        users_data = [
            ("admin", "مدیر", "ارشد سیستم", "admin@prima.ir", "admin123", RoleChoices.SUPER_ADMIN, True),
            ("ceo", "دکتر", "احمدی (مدیرعامل)", "ceo@prima.ir", "ceo123", RoleChoices.CEO, False),
            ("factory_mgr", "مهندس", "رستمی (مدیر کارخانه)", "factory@prima.ir", "factory123", RoleChoices.FACTORY_MANAGER, False),
            ("commercial_mgr", "علیرضا", "نادری (مدیر بازرگانی)", "commercial@prima.ir", "commercial123", RoleChoices.COMMERCIAL_MANAGER, False),
            ("financial_mgr", "مریم", "سعیدی (مدیر مالی)", "finance@prima.ir", "finance123", RoleChoices.FINANCIAL_MANAGER, False),
            ("manager", "مهندس", "کاظمی (مدیر باسکول)", "manager@prima.ir", "manager123", RoleChoices.WEIGHBRIDGE_MANAGER, False),
            ("operator1", "حسین", "مرادی (اپراتور شیفت ۱)", "op1@prima.ir", "operator123", RoleChoices.WEIGHBRIDGE_OPERATOR, False),
            ("operator2", "رضا", "اکبری (اپراتور شیفت ۲)", "op2@prima.ir", "operator123", RoleChoices.WEIGHBRIDGE_OPERATOR, False),
            ("reporter", "سارا", "کریمی (مدیر گزارشات)", "report@prima.ir", "report123", RoleChoices.REPORT_MANAGER, False),
            ("viewer", "محسن", "شفیعی (مشاهده‌گر)", "viewer@prima.ir", "viewer123", RoleChoices.VIEWER, False),
        ]

        users_dict = {}
        for username, fn, ln, email, pwd, role, is_super in users_data:
            user, created = User.objects.get_or_create(username=username)
            user.first_name = fn
            user.last_name = ln
            user.email = email
            user.is_superuser = is_super
            user.is_staff = is_super or role in [RoleChoices.SYSTEM_ADMIN, RoleChoices.WEIGHBRIDGE_MANAGER]
            user.set_password(pwd)
            user.save()

            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = role
            profile.mobile = "0912" + str(1000000 + user.id)
            profile.save()
            users_dict[username] = user

        self.safe_print("[OK] 6 User roles and accounts created.", self.style.SUCCESS)

        # 3. Products
        prods_data = [
            ("آهن اسفنجی (DRI)", "DRI-101", Decimal("50.00"), Decimal("0.50"), "آهن اسفنجی ویژه احیا مستقیم با کربن استاندارد"),
            ("گندله سنگ آهن", "PEL-201", Decimal("60.00"), Decimal("1.00"), "گندله سنگ آهن درجه یک مناسب کوره قوس"),
            ("بریکت گرم آهن (HBI)", "HBI-301", Decimal("40.00"), Decimal("0.00"), "بریکت آهن فشرده مناسب صادرات"),
            ("شمش فولادی (بیلت)", "BLT-401", Decimal("30.00"), Decimal("0.00"), "شمش فولادی ۱۵۰×۱۵۰ استاندارد 5sp"),
            ("میلگرد آجدار A3", "RBR-501", Decimal("30.00"), Decimal("0.00"), "میلگرد سایز ۱۶ و ۲۰ استاندارد"),
            ("ضایعات آهن و قراضه سنگین", "SCR-601", Decimal("80.00"), Decimal("2.50"), "قراضه روغنی و سنگین صنعتی"),
            ("کنسانتره سنگ آهن", "CON-701", Decimal("70.00"), Decimal("1.50"), "کنسانتره سنگ آهن رطوبت‌دار عیار ۶۷٪"),
        ]
        prods_dict = {}
        for name, code, tol, loss, desc in prods_data:
            p, _ = Product.objects.get_or_create(name=name, defaults={
                "code": code, "standard_tolerance_kg": tol, "default_loss_percent": loss, "description": desc
            })
            prods_dict[code] = p
        self.safe_print("[OK] Master products created.", self.style.SUCCESS)

        # 4. Parties
        parties_data = [
            ("شرکت صنایع فولاد خوزستان", "PT-101", "supplier", "09161111111", "061-32222222", "اهواز، کیلومتر ۱۰ جاده کوت عبدالله"),
            ("مجتمع فولاد مبارکه اصفهان", "PT-102", "customer", "09131111111", "031-52732222", "اصفهان، مبارکه"),
            ("شرکت معدنی و صنعتی چادرملو", "PT-103", "supplier", "09121111111", "021-88889999", "یزد، بهاباد، معدن چادرملو"),
            ("شرکت سنگ آهن گل‌گهر سیرجان", "PT-104", "supplier", "09132222222", "034-41423000", "کرمان، سیرجان، کیلومتر ۵۰ جاده شیراز"),
            ("شرکت فولاد کاوه جنوب کیش", "PT-105", "customer", "09171111111", "076-33512000", "بندرعباس، منطقه ویژه صنایع معدنی"),
            ("شرکت حمل و نقل سراسری بارگستر شرق", "PT-106", "contractor", "09151111111", "051-38400000", "مشهد، پایانه بار"),
        ]
        parties_dict = {}
        for name, code, ptype, phone, tel, addr in parties_data:
            pt, _ = Party.objects.get_or_create(name=name, defaults={
                "code": code, "party_type": ptype, "phone": phone, "tel": tel, "address": addr
            })
            parties_dict[code] = pt
        self.safe_print("[OK] Master parties created.", self.style.SUCCESS)

        # 5. Drivers
        drivers_data = [
            ("علی رضایی", "09121112233", "0012345678", "LIC-98765"),
            ("محمد حسینی", "09122223344", "0023456789", "LIC-87654"),
            ("حسین کریمی", "09123334455", "0034567890", "LIC-76543"),
            ("رضا مرادی", "09124445566", "0045678901", "LIC-65432"),
            ("مهدی احمدی", "09125556677", "0056789012", "LIC-54321"),
        ]
        drivers_list = []
        for name, mob, nat, lic in drivers_data:
            d, _ = Driver.objects.get_or_create(full_name=name, defaults={
                "mobile": mob, "national_code": nat, "license_number": lic
            })
            drivers_list.append(d)
        self.safe_print("[OK] Drivers registered.", self.style.SUCCESS)

        # 6. Vehicle Types & Vehicles
        vtypes_data = [
            ("تریلی ۱۸ چرخ کفی", "TRL-FLAT", Decimal("15500.00")),
            ("کمپرسی بنز ده چرخ", "CMP-10W", Decimal("11200.00")),
            ("کمپرسی تریلی جفت", "CMP-TRL", Decimal("16800.00")),
            ("تریلی لبه‌دار", "TRL-EDGE", Decimal("15800.00")),
            ("کامیون تک ۶ چرخ", "TRK-6W", Decimal("7500.00")),
        ]
        vtypes_dict = {}
        for name, code, empty_w in vtypes_data:
            vt, _ = VehicleType.objects.get_or_create(name=name, defaults={"code": code, "standard_tare_weight": empty_w})
            vtypes_dict[code] = vt

        vehicles_data = [
            ("12", "ع", "345", "67", "12 ع 345 - ایران 67", "TRL-FLAT", drivers_list[0], Decimal("15720.00")),
            ("34", "ج", "567", "88", "34 ج 567 - ایران 88", "CMP-10W", drivers_list[1], Decimal("11340.00")),
            ("56", "د", "789", "21", "56 د 789 - ایران 21", "CMP-TRL", drivers_list[2], Decimal("16950.00")),
            ("78", "س", "123", "44", "78 س 123 - ایران 44", "TRL-EDGE", drivers_list[3], Decimal("15420.00")),
            ("91", "ط", "456", "55", "91 ط 456 - ایران 55", "TRK-6W", drivers_list[4], Decimal("7680.00")),
        ]
        vehicles_list = []
        for p1, pL, p2, pI, disp, vt_code, drv, ew in vehicles_data:
            veh, _ = Vehicle.objects.get_or_create(plate_display=disp, defaults={
                "plate_part1": p1, "plate_letter": pL, "plate_part2": p2, "plate_iran": pI,
                "vehicle_type": vtypes_dict[vt_code], "default_driver": drv, "empty_weight": ew
            })
            vehicles_list.append(veh)
        self.safe_print("[OK] Vehicles and Iranian plates registered.", self.style.SUCCESS)

        # 7. Locations & Unload Locations
        locs = ["مجتمع فولاد پریما (اصفهان)", "معدن چادرملو (یزد)", "بندر شهید رجایی (بندرعباس)", "کارخانه فولاد خوزستان (اهواز)", "انبار مرکزی تهران (شورآباد)"]
        loc_objs = [Location.objects.get_or_create(name=n)[0] for n in locs]

        ulocs = [
            ("داخل سالن تولید شماره ۱", "UL-01"),
            ("انبار مواد اولیه و دپو روباز", "UL-02"),
            ("سیلوهای ذخیره آهن اسفنجی", "UL-03"),
            ("محوطه انبار قراضه", "UL-04"),
            ("انبار محصول نهایی و بارگیری بیلت", "UL-05"),
        ]
        uloc_objs = [UnloadLocation.objects.get_or_create(name=n, defaults={"code": c})[0] for n, c in ulocs]
        self.safe_print("[OK] Locations and Unload bays registered.", self.style.SUCCESS)

        # 8. Operation Types & Loss Types
        op_types_data = [
            ("وارده (خرید مواد اولیه)", "OP-IN", "inbound"),
            ("صادره (فروش محصول)", "OP-OUT", "outbound"),
            ("انتقال بین انبارها", "OP-TRF", "transfer"),
            ("تردد داخلی کارخانه", "OP-INT", "internal"),
        ]
        op_dict = {}
        for n, c, d in op_types_data:
            op, _ = OperationType.objects.get_or_create(name=n, defaults={"code": c, "direction": d})
            op_dict[c] = op

        loss_types_data = [
            ("بدون افت", "LS-0", Decimal("0.00")),
            ("افت رطوبت", "LS-MOIST", Decimal("1.50")),
            ("افت ناخالصی و خاک", "LS-DIRT", Decimal("2.00")),
            ("افت کسری وزن و ریزش", "LS-LEAK", Decimal("0.80")),
            ("افت توافقی بازرگانی", "LS-AGREE", Decimal("1.00")),
        ]
        loss_dict = {}
        for n, c, p in loss_types_data:
            ls, _ = LossType.objects.get_or_create(name=n, defaults={"code": c, "default_percent": p})
            loss_dict[c] = ls
        self.safe_print("[OK] Operation & Loss types registered.", self.style.SUCCESS)

        # 9. Sample Weigh Tickets
        today = timezone.localdate()
        op_user = users_dict["operator1"]

        # Ticket 1: Inbound Sponge Iron (Completed)
        t1, created = WeighTicket.objects.get_or_create(serial_number="WB-1001", defaults={
            "status": TicketStatus.COMPLETED,
            "weight_mode": WeightMode.FULL_FIRST,
            "operation_type": op_dict["OP-IN"],
            "party": parties_dict["PT-103"],
            "product": prods_dict["DRI-101"],
            "vehicle": vehicles_list[0],
            "driver": drivers_list[0],
            "license_plate_display": vehicles_list[0].plate_display,
            "waybill_number": "WB-982410",
            "origin": loc_objs[1],
            "destination": loc_objs[0],
            "unload_location": uloc_objs[2],
            "first_weight": Decimal("39840.00"),
            "first_weight_date": today,
            "first_weight_time": time(8, 30),
            "first_weight_operator": op_user,
            "second_weight": Decimal("15720.00"),
            "second_weight_date": today,
            "second_weight_time": time(9, 45),
            "second_weight_operator": op_user,
            "gross_weight": Decimal("39840.00"),
            "tare_weight": Decimal("15720.00"),
            "net_weight": Decimal("24120.00"),
            "sent_weight": Decimal("24100.00"),
            "weight_difference": Decimal("20.00"),
            "weight_difference_percent": Decimal("0.08"),
            "loss_type": loss_dict["LS-MOIST"],
            "loss_percent": Decimal("0.50"),
            "loss_weight": Decimal("120.60"),
            "final_weight": Decimal("23999.40"),
            "notes": "بارگیری از معدن چادرملو، کیفیت مطلوب و بدون ناخالصی غیرمجاز",
        })

        # Ticket 2: Outbound Steel Billet (Completed)
        t2, created = WeighTicket.objects.get_or_create(serial_number="WB-1002", defaults={
            "status": TicketStatus.COMPLETED,
            "weight_mode": WeightMode.EMPTY_FIRST,
            "operation_type": op_dict["OP-OUT"],
            "party": parties_dict["PT-102"],
            "product": prods_dict["BLT-401"],
            "vehicle": vehicles_list[3],
            "driver": drivers_list[3],
            "license_plate_display": vehicles_list[3].plate_display,
            "waybill_number": "WB-982411",
            "origin": loc_objs[0],
            "destination": loc_objs[1],
            "unload_location": uloc_objs[4],
            "first_weight": Decimal("15420.00"),
            "first_weight_date": today,
            "first_weight_time": time(10, 15),
            "first_weight_operator": op_user,
            "second_weight": Decimal("40280.00"),
            "second_weight_date": today,
            "second_weight_time": time(11, 20),
            "second_weight_operator": op_user,
            "gross_weight": Decimal("40280.00"),
            "tare_weight": Decimal("15420.00"),
            "net_weight": Decimal("24860.00"),
            "sent_weight": Decimal("24860.00"),
            "weight_difference": Decimal("0.00"),
            "weight_difference_percent": Decimal("0.00"),
            "loss_type": loss_dict["LS-0"],
            "loss_percent": Decimal("0.00"),
            "loss_weight": Decimal("0.00"),
            "final_weight": Decimal("24860.00"),
            "notes": "ارسال شمش فولادی ۵sp به مقصد فولاد مبارکه",
        })

        # Ticket 3: In Yard / Waiting for Second Weight
        t3, created = WeighTicket.objects.get_or_create(serial_number="WB-1003", defaults={
            "status": TicketStatus.WAITING_SECOND,
            "weight_mode": WeightMode.FULL_FIRST,
            "operation_type": op_dict["OP-IN"],
            "party": parties_dict["PT-104"],
            "product": prods_dict["PEL-201"],
            "vehicle": vehicles_list[1],
            "driver": drivers_list[1],
            "license_plate_display": vehicles_list[1].plate_display,
            "waybill_number": "WB-982412",
            "origin": loc_objs[2],
            "destination": loc_objs[0],
            "unload_location": uloc_objs[1],
            "first_weight": Decimal("36450.00"),
            "first_weight_date": today,
            "first_weight_time": time(12, 5),
            "first_weight_operator": op_user,
            "gross_weight": Decimal("36450.00"),
            "tare_weight": Decimal("0.00"),
            "net_weight": Decimal("0.00"),
            "sent_weight": Decimal("25100.00"),
            "loss_type": loss_dict["LS-DIRT"],
            "loss_percent": Decimal("1.00"),
            "notes": "کامیون در محوطه تخلیه گندله منتظر نوبت است",
        })

        # Ticket 4: Discrepancy / Tolerance Exceeded (For test)
        t4, created = WeighTicket.objects.get_or_create(serial_number="WB-1004", defaults={
            "status": TicketStatus.COMPLETED,
            "weight_mode": WeightMode.FULL_FIRST,
            "operation_type": op_dict["OP-IN"],
            "party": parties_dict["PT-101"],
            "product": prods_dict["SCR-601"],
            "vehicle": vehicles_list[2],
            "driver": drivers_list[2],
            "license_plate_display": vehicles_list[2].plate_display,
            "waybill_number": "WB-982413",
            "origin": loc_objs[3],
            "destination": loc_objs[0],
            "unload_location": uloc_objs[3],
            "first_weight": Decimal("41800.00"),
            "first_weight_date": today,
            "first_weight_time": time(13, 0),
            "first_weight_operator": op_user,
            "second_weight": Decimal("16950.00"),
            "second_weight_date": today,
            "second_weight_time": time(14, 10),
            "second_weight_operator": op_user,
            "gross_weight": Decimal("41800.00"),
            "tare_weight": Decimal("16950.00"),
            "net_weight": Decimal("24850.00"),
            "sent_weight": Decimal("25500.00"),  # 650kg difference (exceeds 80kg limit!)
            "weight_difference": Decimal("-650.00"),
            "weight_difference_percent": Decimal("-2.55"),
            "is_tolerance_exceeded": True,
            "loss_type": loss_dict["LS-LEAK"],
            "loss_percent": Decimal("2.00"),
            "loss_weight": Decimal("497.00"),
            "final_weight": Decimal("24353.00"),
            "notes": "مغایرت ۶۵۰ کیلوگرمی با بارنامه مبدا اهواز - گزارش به حراست و بازرگانی",
        })

        self.safe_print("[OK] Sample tickets created.", self.style.SUCCESS)

        # 10. Audit Log Seed
        log_audit(
            action=AuditAction.CREATE,
            model_name="System",
            record_id="1",
            record_repr="System Initialization",
            reason="Seed data executed.",
            user=users_dict["admin"]
        )

        self.safe_print("[SUCCESS] All seed data successfully loaded into database.", self.style.SUCCESS)
        self.safe_print("Admin login: admin / admin123")
        self.safe_print("Weighbridge Manager login: manager / manager123")
        self.safe_print("Operator login: operator1 / operator123")
