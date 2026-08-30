import os
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import FileResponse, Http404
from core.models import SystemSetting
from core.forms import SystemSettingForm
from core.backup import (
    create_db_backup, restore_db_backup, list_backups, 
    delete_backup_file, get_database_diagnostics, get_backups_dir
)
from accounts.decorators import admin_only_required
from audit.services import log_audit
from audit.models import AuditAction

@login_required
@admin_only_required
def settings_view(request):
    settings_obj = SystemSetting.get_settings()
    if request.method == "POST":
        form = SystemSettingForm(request.POST, request.FILES, instance=settings_obj)
        if form.is_valid():
            form.save()
            log_audit(
                action=AuditAction.UPDATE,
                model_name="SystemSetting",
                record_id=settings_obj.id,
                record_repr="تنظیمات سیستم",
                reason="بروزرسانی تنظیمات عمومی سامانه توسط مدیر"
            )
            messages.success(request, "تنظیمات سامانه با موفقیت ذخیره شد.")
            return redirect("core:settings")
    else:
        form = SystemSettingForm(instance=settings_obj)

    return render(request, "core/settings.html", {"form": form, "title": "تنظیمات عمومی سامانه باسکول"})

@login_required
@admin_only_required
def backup_view(request):
    if request.method == "POST":
        action_type = request.POST.get("action_type")
        
        # 1. Create New Backup
        if action_type == "create_backup":
            fmt = request.POST.get("format_type", "auto")
            backup_path, err = create_db_backup(format_type=fmt)
            if backup_path and os.path.exists(backup_path):
                filename = os.path.basename(backup_path)
                log_audit(
                    action=AuditAction.CREATE,
                    model_name="DatabaseBackup",
                    record_id="0",
                    record_repr=f"پشتیبان پایگاه داده ({filename})",
                    reason=f"تهیه فایل پشتیبان با فرمت {fmt} توسط مدیر"
                )
                if request.POST.get("direct_download") == "1":
                    return FileResponse(open(backup_path, 'rb'), as_attachment=True, filename=filename)
                else:
                    messages.success(request, f"فایل پشتیبان {filename} با موفقیت در سرور ایجاد و ذخیره شد.")
                    return redirect("core:backup")
            else:
                messages.error(request, f"خطا در ایجاد پشتیبان: {err}")
                return redirect("core:backup")
        
        # 2. Download Existing Backup from Server
        elif action_type == "download_file":
            filename = request.POST.get("filename")
            if filename:
                safe_name = os.path.basename(filename)
                fpath = os.path.join(get_backups_dir(), safe_name)
                if os.path.exists(fpath):
                    return FileResponse(open(fpath, 'rb'), as_attachment=True, filename=safe_name)
            messages.error(request, "فایل پشتیبان درخواستی یافت نشد.")
            return redirect("core:backup")

        # 3. Restore from Server Archive
        elif action_type == "restore_existing":
            filename = request.POST.get("filename")
            if filename:
                safe_name = os.path.basename(filename)
                fpath = os.path.join(get_backups_dir(), safe_name)
                if os.path.exists(fpath):
                    success, msg = restore_db_backup(fpath)
                    if success:
                        log_audit(
                            action=AuditAction.RESTORE,
                            model_name="DatabaseBackup",
                            record_id="0",
                            record_repr=f"بازیابی پایگاه داده ({safe_name})",
                            reason=f"بازیابی دیتابیس از آرشیو فایل {safe_name}"
                        )
                        messages.success(request, msg)
                    else:
                        messages.error(request, msg)
                    return redirect("core:backup")
            messages.error(request, "فایل پشتیبان برای بازیابی انتخاب نشده است.")
            return redirect("core:backup")

        # 4. Restore from Uploaded File
        elif action_type == "restore_upload":
            uploaded_file = request.FILES.get("backup_file")
            if not uploaded_file:
                messages.error(request, "لطفاً یک فایل معتبر پشتیبان (.json, .dump, .sql, .sqlite3) انتخاب فرمایید.")
            else:
                success, msg = restore_db_backup(uploaded_file)
                if success:
                    log_audit(
                        action=AuditAction.RESTORE,
                        model_name="DatabaseBackup",
                        record_id="0",
                        record_repr=f"بازیابی پایگاه داده ({uploaded_file.name})",
                        reason=f"بازیابی دیتابیس از فایل آپلودی {uploaded_file.name}"
                    )
                    messages.success(request, msg)
                else:
                    messages.error(request, msg)
            return redirect("core:backup")

        # 5. Delete Backup File
        elif action_type == "delete_backup":
            filename = request.POST.get("filename")
            if filename:
                success, msg = delete_backup_file(filename)
                if success:
                    log_audit(
                        action=AuditAction.DELETE,
                        model_name="DatabaseBackup",
                        record_id="0",
                        record_repr=f"حذف فایل پشتیبان ({filename})",
                        reason=f"حذف فایل پشتیبان {filename} توسط مدیر"
                    )
                    messages.success(request, msg)
                else:
                    messages.error(request, msg)
            return redirect("core:backup")

    diagnostics = get_database_diagnostics()
    backups = list_backups()

    return render(request, "core/backup.html", {
        "title": "پشتیبان‌گیری و بازیابی پایگاه داده",
        "diagnostics": diagnostics,
        "backups": backups,
    })
