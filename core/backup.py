import os
import glob
import json
import gzip
import shutil
import sqlite3
import subprocess
from datetime import datetime
from django.conf import settings
from django.core.management import call_command
from django.db import connection
from core.jalali import format_jalali_datetime, gregorian_to_jalali
from weighbridge.models import WeighTicket
from masterdata.models import Product, Party
from django.contrib.auth.models import User

def get_db_info():
    """Return dict of database engine and connection properties."""
    db_config = settings.DATABASES['default']
    engine = db_config.get('ENGINE', '')
    is_postgres = 'postgresql' in engine or 'psycopg' in engine
    is_sqlite = 'sqlite3' in engine

    return {
        'engine': engine,
        'is_postgres': is_postgres,
        'is_sqlite': is_sqlite,
        'engine_name': 'PostgreSQL' if is_postgres else ('SQLite' if is_sqlite else 'Other'),
        'name': str(db_config.get('NAME', '')),
        'user': db_config.get('USER', ''),
        'password': db_config.get('PASSWORD', ''),
        'host': db_config.get('HOST', 'localhost') or 'localhost',
        'port': str(db_config.get('PORT', '5432') or '5432'),
    }

def find_postgres_binary(bin_name):
    """Find pg_dump, pg_restore, or psql binary path on Windows or Linux."""
    found = shutil.which(bin_name)
    if found:
        return found
    
    patterns = [
        rf"C:\Program Files\PostgreSQL\*\bin\{bin_name}.exe",
        rf"C:\Program Files (x86)\PostgreSQL\*\bin\{bin_name}.exe",
    ]
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches:
            matches.sort(reverse=True)
            return matches[0]

    return None

def get_backups_dir():
    """Ensure and return the backups folder path."""
    bdir = os.path.join(settings.BASE_DIR, 'backups')
    os.makedirs(bdir, exist_ok=True)
    return bdir

def create_db_backup(format_type='auto'):
    """
    Create a backup of the current database.
    format_type: 'auto' | 'json' | 'dump' | 'sql'
    """
    db_info = get_db_info()
    backup_dir = get_backups_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        if db_info['is_postgres']:
            pg_dump_bin = find_postgres_binary('pg_dump')

            if format_type == 'json' or not pg_dump_bin:
                filename = f"backup_bascol_{timestamp}.json"
                filepath = os.path.join(backup_dir, filename)

                with open(filepath, 'w', encoding='utf-8') as f:
                    call_command(
                        'dumpdata',
                        '--exclude', 'contenttypes',
                        '--exclude', 'auth.permission',
                        '--indent', '2',
                        stdout=f
                    )
                return filepath, None

            else:
                filename = f"backup_bascol_{timestamp}.dump"
                filepath = os.path.join(backup_dir, filename)

                env = os.environ.copy()
                if db_info['password']:
                    env['PGPASSWORD'] = str(db_info['password'])

                cmd = [
                    pg_dump_bin,
                    '-U', db_info['user'],
                    '-h', db_info['host'],
                    '-p', db_info['port'],
                    '-F', 'c',
                    '-b',
                    '-v',
                    '-f', filepath,
                    db_info['name']
                ]

                res = subprocess.run(cmd, env=env, capture_output=True, text=True)
                if res.returncode == 0 and os.path.exists(filepath):
                    return filepath, None
                else:
                    json_filename = f"backup_bascol_{timestamp}.json"
                    json_filepath = os.path.join(backup_dir, json_filename)
                    with open(json_filepath, 'w', encoding='utf-8') as f:
                        call_command(
                            'dumpdata',
                            '--exclude', 'contenttypes',
                            '--exclude', 'auth.permission',
                            '--indent', '2',
                            stdout=f
                        )
                    return json_filepath, None

        elif db_info['is_sqlite']:
            db_path = db_info['name']
            if not os.path.exists(db_path):
                return None, "فایل دیتابیس SQLite یافت نشد."

            if format_type == 'json':
                filename = f"backup_bascol_{timestamp}.json"
                filepath = os.path.join(backup_dir, filename)
                with open(filepath, 'w', encoding='utf-8') as f:
                    call_command('dumpdata', '--exclude', 'contenttypes', '--exclude', 'auth.permission', '--indent', '2', stdout=f)
                return filepath, None
            else:
                filename = f"backup_bascol_{timestamp}.sqlite3"
                filepath = os.path.join(backup_dir, filename)
                src_conn = sqlite3.connect(db_path)
                dst_conn = sqlite3.connect(filepath)
                with dst_conn:
                    src_conn.backup(dst_conn)
                dst_conn.close()
                src_conn.close()
                return filepath, None

        else:
            filename = f"backup_bascol_{timestamp}.json"
            filepath = os.path.join(backup_dir, filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                call_command('dumpdata', '--exclude', 'contenttypes', '--exclude', 'auth.permission', '--indent', '2', stdout=f)
            return filepath, None

    except Exception as e:
        return None, str(e)

def restore_db_backup(file_input):
    """
    Restore database from an uploaded file or existing filepath on server.
    file_input: uploaded InMemoryUploadedFile / TemporaryUploadedFile OR string path.
    """
    db_info = get_db_info()
    backup_dir = get_backups_dir()

    if isinstance(file_input, str):
        filepath = file_input
        filename = os.path.basename(filepath)
    else:
        filename = file_input.name
        temp_filename = f"restore_temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
        filepath = os.path.join(backup_dir, temp_filename)
        with open(filepath, 'wb+') as dest:
            for chunk in file_input.chunks():
                dest.write(chunk)

    if not os.path.exists(filepath):
        return False, "فایل پشتیبان انتخاب شده بر روی سرور یافت نشد."

    # Auto-Safety Backup before restoring
    try:
        create_db_backup(format_type='json')
    except Exception:
        pass

    ext = os.path.splitext(filename)[1].lower()

    try:
        if ext == '.json':
            call_command('loaddata', filepath)
            return True, "اطلاعات پایگاه داده از فایل JSON با موفقیت بازیابی شد."

        elif ext in ['.dump', '.backup', '.sql']:
            if not db_info['is_postgres']:
                return False, "فایل‌های .dump و .sql مخصوص پایگاه داده PostgreSQL هستند."

            pg_restore_bin = find_postgres_binary('pg_restore')
            psql_bin = find_postgres_binary('psql')

            env = os.environ.copy()
            if db_info['password']:
                env['PGPASSWORD'] = str(db_info['password'])

            if ext == '.sql' and psql_bin:
                cmd = [
                    psql_bin,
                    '-U', db_info['user'],
                    '-h', db_info['host'],
                    '-p', db_info['port'],
                    '-d', db_info['name'],
                    '-f', filepath
                ]
                res = subprocess.run(cmd, env=env, capture_output=True, text=True)
                if res.returncode == 0:
                    return True, "پایگاه داده PostgreSQL با موفقیت از فایل SQL بازیابی شد."
                else:
                    return False, f"خطا در اجرای psql: {res.stderr or res.stdout}"

            elif pg_restore_bin:
                cmd = [
                    pg_restore_bin,
                    '-U', db_info['user'],
                    '-h', db_info['host'],
                    '-p', db_info['port'],
                    '-d', db_info['name'],
                    '--clean',
                    '--if-exists',
                    '-v',
                    filepath
                ]
                res = subprocess.run(cmd, env=env, capture_output=True, text=True)
                if res.returncode in [0, 1]:
                    return True, "پایگاه داده PostgreSQL با موفقیت بازیابی شد."
                else:
                    return False, f"خطا در بازیابی pg_restore: {res.stderr or res.stdout}"
            else:
                return False, "ابزار pg_restore بر روی سرور یافت نشد."

        elif ext == '.sqlite3' or ext == '.db':
            if not db_info['is_sqlite']:
                return False, "فایل پشتیبان SQLite است در حالی که سیستم از PostgreSQL استفاده می‌کند. برای جابجایی داده‌ها از فرمت JSON استفاده فرمایید."

            db_path = db_info['name']
            shutil.copy2(filepath, db_path)
            return True, "پایگاه داده SQLite با موفقیت جایگزین و بازیابی شد."

        else:
            return False, f"فرمت فایل '{ext}' پشتیبانی نمی‌شود. فرمت‌های مجاز: .json, .dump, .sql, .sqlite3"

    except Exception as e:
        return False, f"خطا در عملیات بازیابی: {str(e)}"

def list_backups():
    """Return sorted list of all backup files in backups folder."""
    backup_dir = get_backups_dir()
    files = []

    for fname in os.listdir(backup_dir):
        fpath = os.path.join(backup_dir, fname)
        if os.path.isfile(fpath) and not fname.startswith('restore_temp_'):
            stats = os.stat(fpath)
            mtime = datetime.fromtimestamp(stats.st_mtime)
            size_kb = round(stats.st_size / 1024.0, 1)
            size_str = f"{size_kb} KB" if size_kb < 1024 else f"{round(size_kb / 1024.0, 2)} MB"

            ext = os.path.splitext(fname)[1].lower()
            type_label = {
                '.json': 'داده‌های سازگار (JSON)',
                '.dump': 'بومی PostgreSQL (.dump)',
                '.sql': 'دستورات SQL',
                '.sqlite3': 'نسخه SQLite',
                '.db': 'نسخه SQLite',
            }.get(ext, 'سایر')

            files.append({
                'filename': fname,
                'filepath': fpath,
                'filesize': size_str,
                'raw_size': stats.st_size,
                'created_at_jalali': format_jalali_datetime(mtime, "%Y/%m/%d %H:%M:%S"),
                'mtime': mtime,
                'type_label': type_label,
                'ext': ext,
            })

    files.sort(key=lambda x: x['mtime'], reverse=True)
    return files

def delete_backup_file(filename):
    """Safely delete a backup file."""
    backup_dir = get_backups_dir()
    safe_name = os.path.basename(filename)
    filepath = os.path.join(backup_dir, safe_name)
    if os.path.exists(filepath) and os.path.isfile(filepath):
        os.remove(filepath)
        return True, "فایل پشتیبان با موفقیت حذف شد."
    return False, "فایل مورد نظر یافت نشد."

def get_database_diagnostics():
    """Return diagnostic metrics about current database."""
    db_info = get_db_info()
    
    is_connected = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        is_connected = False

    tickets_count = WeighTicket.objects.count()
    products_count = Product.objects.count()
    parties_count = Party.objects.count()
    users_count = User.objects.count()

    backups = list_backups()
    last_backup_jalali = backups[0]['created_at_jalali'] if backups else "تاکنون ثبت نشده"

    return {
        'db_info': db_info,
        'is_connected': is_connected,
        'tickets_count': tickets_count,
        'products_count': products_count,
        'parties_count': parties_count,
        'users_count': users_count,
        'backups_count': len(backups),
        'last_backup_jalali': last_backup_jalali,
    }
