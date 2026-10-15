# گزارش جامع بازرسی و یکپارچگی شماره‌گذاری قبوض باسکول (Ticket Numbering Integrity Report)
**تاریخ بازرسی:** 2026-10-15 05:00:10 UTC  
**نسخه سیستم:** Prima Bascol v2.2-pre  
**پایگاه داده:** PostgreSQL 18.x (prima_bascol)  

---

### ۱. تنظیمات جاری سامانه (System Settings)
- **پیشوند تنظیم‌شده در سامانه (SystemSetting.serial_prefix):** `WB-`
- **شماره شروع تنظیم‌شده (SystemSetting.serial_start_number):** `1001`
- **تعداد کل قبوض باسکول شرکتی (WeighTicket):** `134`
- **تعداد کل قبوض متفرقه و اضطراری (EmergencyWeighTicket):** `4`

---

### ۲. آنالیز قبوض باسکول شرکتی (WeighTicket)
- **بررسی رکوردهای تکراری (Duplicate Check):** ✅ هیچ شماره قبض تکراری یافت نشد (Zero Duplicates).
- **کوچک‌ترین شماره عددی در پایگاه داده:** `1001`
- **بزرگ‌ترین شماره عددی در پایگاه داده:** `2134`
- **شماره بعدی مورد انتظار برای تخصیص:** `WB-2135` (`WB-2135`)

#### الگوها و فرمت‌های موجود در سوابق:
- **الگوی `WB-####`:** 20 فقره
- **الگوی `WB-SIM-####`:** 114 فقره

#### وضعیت گسستگی‌ها و فاصله‌های عددی (Gaps Analysis):
- فاصله از شماره **1004** تا **2005** (تعداد فواصل پرنشده: 1000 شماره)

*توضیح فنی فواصل:* فاصله بین ۱۰04 تا ۲۰۰۵ به دلیل ورود فیکسچرهای داده شبیه‌سازی (`WB-SIM-2005` الی `WB-SIM-2118`) در فاز تست بوده است و قبوض عملیاتی اخیر شرکت از شماره `WB-2119` الی `WB-2134` کاملاً منظم، متوالی و متصل هستند.

---

### ۳. آنالیز قبوض متفرقه (EmergencyWeighTicket)
- **بررسی رکوردهای تکراری:** ✅ هیچ شماره قبض متفرقه تکراری وجود ندارد.
- **کوچک‌ترین شماره:** `1001`
- **بزرگ‌ترین شماره:** `1004`
- **تعداد کل رکوردهای متفرقه:** `4` (`EXT-1001` تا `EXT-1004`)
- **شماره بعدی مورد انتظار برای قبوض متفرقه:** `EXT-1005` (`EXT-1005`)

---

### ۴. قیدهای یکتایی فعال در پایگاه داده (PostgreSQL Constraints Catalog)
- **`weighbridge_weightic_cancelled_by_id_db6612df_fk_auth_user`** (f): `FOREIGN KEY (cancelled_by_id) REFERENCES auth_user(id) DEFERRABLE INITIALLY DEFERRED`
- **`weighbridge_weightic_destination_id_3fe55fc9_fk_masterdat`** (f): `FOREIGN KEY (destination_id) REFERENCES masterdata_location(id) DEFERRABLE INITIALLY DEFERRED`
- **`weighbridge_weightic_driver_id_e9577551_fk_masterdat`** (f): `FOREIGN KEY (driver_id) REFERENCES masterdata_driver(id) DEFERRABLE INITIALLY DEFERRED`
- **`weighbridge_weightic_duplicate_exception__caaf0f44_fk_weighbrid`** (f): `FOREIGN KEY (duplicate_exception_id) REFERENCES weighbridge_plateregistrationexception(id) DEFERRABLE INITIALLY DEFERRED`
- **`weighbridge_weightic_first_weight_operato_54a350f2_fk_auth_user`** (f): `FOREIGN KEY (first_weight_operator_id) REFERENCES auth_user(id) DEFERRABLE INITIALLY DEFERRED`
- **`weighbridge_weightic_last_edited_by_id_18198405_fk_auth_user`** (f): `FOREIGN KEY (last_edited_by_id) REFERENCES auth_user(id) DEFERRABLE INITIALLY DEFERRED`
- **`weighbridge_weightic_loss_type_id_f4f425c8_fk_masterdat`** (f): `FOREIGN KEY (loss_type_id) REFERENCES masterdata_losstype(id) DEFERRABLE INITIALLY DEFERRED`
- **`weighbridge_weightic_operation_type_id_f76c9c79_fk_masterdat`** (f): `FOREIGN KEY (operation_type_id) REFERENCES masterdata_operationtype(id) DEFERRABLE INITIALLY DEFERRED`
- **`weighbridge_weightic_origin_id_0ee188bc_fk_masterdat`** (f): `FOREIGN KEY (origin_id) REFERENCES masterdata_location(id) DEFERRABLE INITIALLY DEFERRED`
- **`weighbridge_weightic_party_id_17674f41_fk_masterdat`** (f): `FOREIGN KEY (party_id) REFERENCES masterdata_party(id) DEFERRABLE INITIALLY DEFERRED`
- **`weighbridge_weightic_product_id_fb1edec8_fk_masterdat`** (f): `FOREIGN KEY (product_id) REFERENCES masterdata_product(id) DEFERRABLE INITIALLY DEFERRED`
- **`weighbridge_weightic_second_weight_operat_9e693ba5_fk_auth_user`** (f): `FOREIGN KEY (second_weight_operator_id) REFERENCES auth_user(id) DEFERRABLE INITIALLY DEFERRED`
- **`weighbridge_weightic_unload_location_id_acef53c2_fk_masterdat`** (f): `FOREIGN KEY (unload_location_id) REFERENCES masterdata_unloadlocation(id) DEFERRABLE INITIALLY DEFERRED`
- **`weighbridge_weightic_vehicle_id_0db5f8b3_fk_masterdat`** (f): `FOREIGN KEY (vehicle_id) REFERENCES masterdata_vehicle(id) DEFERRABLE INITIALLY DEFERRED`
- **`weighbridge_weightic_vehicle_type_id_3afac660_fk_masterdat`** (f): `FOREIGN KEY (vehicle_type_id) REFERENCES masterdata_vehicletype(id) DEFERRABLE INITIALLY DEFERRED`
- **`weighbridge_weighticket_cancellation_reason_not_null`** (n): `NOT NULL cancellation_reason`
- **`weighbridge_weighticket_created_at_not_null`** (n): `NOT NULL created_at`
- **`weighbridge_weighticket_driver_mobile_custom_not_null`** (n): `NOT NULL driver_mobile_custom`
- **`weighbridge_weighticket_driver_name_custom_not_null`** (n): `NOT NULL driver_name_custom`
- **`weighbridge_weighticket_final_weight_not_null`** (n): `NOT NULL final_weight`
- **`weighbridge_weighticket_first_weight_not_null`** (n): `NOT NULL first_weight`
- **`weighbridge_weighticket_gross_weight_not_null`** (n): `NOT NULL gross_weight`
- **`weighbridge_weighticket_id_not_null`** (n): `NOT NULL id`
- **`weighbridge_weighticket_ingot_count_check`** (c): `CHECK ((ingot_count >= 0))`
- **`weighbridge_weighticket_is_active_not_null`** (n): `NOT NULL is_active`
- **`weighbridge_weighticket_is_loss_overridden_not_null`** (n): `NOT NULL is_loss_overridden`
- **`weighbridge_weighticket_is_tolerance_exceeded_not_null`** (n): `NOT NULL is_tolerance_exceeded`
- **`weighbridge_weighticket_last_edit_reason_not_null`** (n): `NOT NULL last_edit_reason`
- **`weighbridge_weighticket_license_plate_display_not_null`** (n): `NOT NULL license_plate_display`
- **`weighbridge_weighticket_load_count_check`** (c): `CHECK ((load_count >= 0))`
- **`weighbridge_weighticket_load_count_not_null`** (n): `NOT NULL load_count`
- **`weighbridge_weighticket_loss_override_reason_not_null`** (n): `NOT NULL loss_override_reason`
- **`weighbridge_weighticket_loss_percent_not_null`** (n): `NOT NULL loss_percent`
- **`weighbridge_weighticket_loss_weight_not_null`** (n): `NOT NULL loss_weight`
- **`weighbridge_weighticket_net_weight_not_null`** (n): `NOT NULL net_weight`
- **`weighbridge_weighticket_normalized_plate_not_null`** (n): `NOT NULL normalized_plate`
- **`weighbridge_weighticket_notes_not_null`** (n): `NOT NULL notes`
- **`weighbridge_weighticket_pkey`** (p): `PRIMARY KEY (id)`
- **`weighbridge_weighticket_sent_weight_not_null`** (n): `NOT NULL sent_weight`
- **`weighbridge_weighticket_serial_number_key`** (u): `UNIQUE (serial_number)`
- **`weighbridge_weighticket_serial_number_not_null`** (n): `NOT NULL serial_number`
- **`weighbridge_weighticket_status_not_null`** (n): `NOT NULL status`
- **`weighbridge_weighticket_tare_weight_not_null`** (n): `NOT NULL tare_weight`
- **`weighbridge_weighticket_updated_at_not_null`** (n): `NOT NULL updated_at`
- **`weighbridge_weighticket_vehicle_type_custom_not_null`** (n): `NOT NULL vehicle_type_custom`
- **`weighbridge_weighticket_waybill_number_not_null`** (n): `NOT NULL waybill_number`
- **`weighbridge_weighticket_weight_difference_not_null`** (n): `NOT NULL weight_difference`
- **`weighbridge_weighticket_weight_difference_percent_not_null`** (n): `NOT NULL weight_difference_percent`
- **`weighbridge_weighticket_weight_mode_not_null`** (n): `NOT NULL weight_mode`
- **`weighbridge_emergenc_cancelled_by_id_a41db7fd_fk_auth_user`** (f): `FOREIGN KEY (cancelled_by_id) REFERENCES auth_user(id) DEFERRABLE INITIALLY DEFERRED`
- **`weighbridge_emergenc_operator_id_6f91f170_fk_auth_user`** (f): `FOREIGN KEY (operator_id) REFERENCES auth_user(id) DEFERRABLE INITIALLY DEFERRED`
- **`weighbridge_emergencyweighticket_cancellation_reason_not_null`** (n): `NOT NULL cancellation_reason`
- **`weighbridge_emergencyweighticket_company_name_not_null`** (n): `NOT NULL company_name`
- **`weighbridge_emergencyweighticket_created_at_not_null`** (n): `NOT NULL created_at`
- **`weighbridge_emergencyweighticket_driver_mobile_not_null`** (n): `NOT NULL driver_mobile`
- **`weighbridge_emergencyweighticket_driver_name_not_null`** (n): `NOT NULL driver_name`
- **`weighbridge_emergencyweighticket_gross_weight_not_null`** (n): `NOT NULL gross_weight`
- **`weighbridge_emergencyweighticket_id_not_null`** (n): `NOT NULL id`
- **`weighbridge_emergencyweighticket_is_active_not_null`** (n): `NOT NULL is_active`
- **`weighbridge_emergencyweighticket_license_plate_not_null`** (n): `NOT NULL license_plate`
- **`weighbridge_emergencyweighticket_net_weight_not_null`** (n): `NOT NULL net_weight`
- **`weighbridge_emergencyweighticket_notes_not_null`** (n): `NOT NULL notes`
- **`weighbridge_emergencyweighticket_pkey`** (p): `PRIMARY KEY (id)`
- **`weighbridge_emergencyweighticket_serial_number_key`** (u): `UNIQUE (serial_number)`
- **`weighbridge_emergencyweighticket_serial_number_not_null`** (n): `NOT NULL serial_number`
- **`weighbridge_emergencyweighticket_status_not_null`** (n): `NOT NULL status`
- **`weighbridge_emergencyweighticket_tare_weight_not_null`** (n): `NOT NULL tare_weight`
- **`weighbridge_emergencyweighticket_updated_at_not_null`** (n): `NOT NULL updated_at`
- **`weighbridge_emergencyweighticket_weight_date_not_null`** (n): `NOT NULL weight_date`

---

### ۵. نتیجه‌گیری ممیزی پیش از مایگریشن
1. هیچ‌گونه تداخل کلید یکتا یا شماره تکراری در پایگاه داده وجود ندارد.
2. هیچ رکورد پلاک یا تاریخی نیاز به اصلاح یا حذف فیزیکی ندارد.
3. مقداردهی اولیه مدل `TicketSequence` باید برای دامنه `standard` بر روی عدد **2134** (با پیشوند `WB-`) و برای دامنه `emergency` بر روی عدد **1004** (با پیشوند `EXT-`) انجام گیرد تا توالی بدون پرش و بدون برخورد با سوابق تاریخی ادامه یابد.
4. مجوز اعمال ایمن تغییرات معماری و مایگریشن: **تأیید شد (APPROVED)**.
