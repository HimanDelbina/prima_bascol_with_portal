# راهنمای جامع استقرار سامانه باسکول صنعتی پریما (Prima Bascol) روی سرور Production

این مستند شامل دستورالعمل‌های دقیق، گام‌به‌گام و استاندارد برای استقرار، پیکربندی، به‌روزرسانی، پشتیبان‌گیری و اتصال سامانه به Reverse Proxy (Nginx / Nginx Proxy Manager) با گواهی SSL/HTTPS برای دامنه `bascol.ferion.ir` است.

---

## ۱. مشخصات معماری استقرار (Architecture Overview)

- **سیستم‌عامل مقصد:** Ubuntu Server 22.04 LTS / 24.04 LTS
- **محیط اجرا:** Docker & Docker Compose
- **وب‌سرور داخلی (WSGI):** Gunicorn (پیکربندی شده روی پورت داخلی `8000`)
- **مدیریت فایل‌های استاتیک:** WhiteNoise با کش فشرده Manifest + حجم مشترک Docker
- **پایگاه داده:** PostgreSQL 16 (با حجم ماندگار `postgres_data` و Healthcheck خودکار)
- **پروکسی معکوس (Reverse Proxy):** Nginx Proxy Manager یا Nginx با SSL خودکار Let's Encrypt
- **دامنه رسمی:** `https://bascol.ferion.ir`
- **مسیر پایه API:** `https://bascol.ferion.ir/api/v1/`
- **مستندات تعاملی Swagger:** `https://bascol.ferion.ir/api/docs/`
- **بررسی سلامت سامانه (Health Check):** `https://bascol.ferion.ir/health/`

---

## ۲. گام‌های استقرار اولیه روی سرور اوبونتو (Initial Deployment)

### ۲.۱. آماده‌سازی بسته‌ها و داکر در سرور
```bash
# به‌روزرسانی مخازن لینوکس
sudo apt update && sudo apt upgrade -y

# نصب بسته‌های پیش‌نیاز، git و curl
sudo apt install -y git curl ufw htop ca-certificates gnupg

# نصب Docker و Docker Compose (پلاگین رسمی)
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# اضافه کردن کاربر جاری به گروه داکر (بدون نیاز به sudo مداوم)
sudo usermod -aG docker $USER
newgrp docker
```

### ۲.۲. کلون پروژه و تنظیم متغیرهای محیطی (.env)
```bash
# رفتن به پوشه استاندارد برنامه‌ها
cd /opt
sudo git clone https://github.com/HimanDelbina/prima_bascol.git
sudo chown -R $USER:$USER /opt/prima_bascol
cd /opt/prima_bascol

# ایجاد فایل .env بر اساس فایل الگو
cp .env.example .env

# ویرایش متغیرهای محیطی
nano .env
```

> [!IMPORTANT]
> در فایل `.env` حتماً مقادیر زیر را به دقت تنظیم فرمایید:
> 1. `DJANGO_SECRET_KEY`: یک کلید تصادفی امن حداقل ۵۰ کاراکتری تولید کنید:
>    ```bash
>    python3 -c "import secrets; print(secrets.token_urlsafe(50))"
>    ```
> 2. `DJANGO_DEBUG=False`
> 3. `POSTGRES_PASSWORD`: یک کلمه عبور قوی و اختصاصی برای پایگاه داده انتخاب کنید.
> 4. `DJANGO_ALLOWED_HOSTS=bascol.ferion.ir,www.bascol.ferion.ir,127.0.0.1,localhost,web`
> 5. `DJANGO_CSRF_TRUSTED_ORIGINS=https://bascol.ferion.ir,https://www.bascol.ferion.ir`
> 6. `DJANGO_CORS_ALLOWED_ORIGINS=https://bascol.ferion.ir,https://www.bascol.ferion.ir`

### ۲.۳. ساخت کانتینرها و راه‌اندازی اولیه پایگاه داده
```bash
# ۱. بیلد ایمیج داکر
docker compose build

# ۲. راه‌اندازی سرویس دیتابیس در پس‌زمینه
docker compose up -d db

# ۳. اجرای Migrationها روی دیتابیس
docker compose run --rm web python manage.py migrate --noinput

# ۴. جمع‌آوری و فشرده‌سازی فایل‌های استاتیک
docker compose run --rm web python manage.py collectstatic --noinput

# ۵. راه‌اندازی کامل تمامی سرویس‌ها
docker compose up -d

# ۶. بررسی سلامت و لاگ‌های اجرا
docker compose ps
docker compose logs -f web
```

---

## ۳. ایجاد کاربر مدیر ارشد (Superuser)

پس از بالا آمدن کانتینر، با دستور زیر بدون ذخیره رمز عبور در کد، مدیر سیستم را بسازید:
```bash
docker compose run --rm web python manage.py createsuperuser
```
*(نام کاربری، ایمیل و رمز عبور را به دلخواه وارد کنید. کاربر ایجادشده به دلیل سیگنال‌های اتوماتیک سیستم بلافاصله با نقش **Super Admin** تعریف می‌گردد).*

---

## ۴. تنظیمات Nginx Proxy Manager (توصیه‌شده)

اگر از رابط گرافیکی **Nginx Proxy Manager** برای مدیریت دامنه‌ها و SSL استفاده می‌کنید:

1. وارد پنل Nginx Proxy Manager شوید.
2. به بخش **Proxy Hosts** رفته و روی **Add Proxy Host** کلیک کنید.
3. در تب **Details**:
   - **Domain Names:** `bascol.ferion.ir` و `www.bascol.ferion.ir`
   - **Scheme:** `http`
   - **Forward Hostname / IP:**
     - اگر NPM روی همان سرور و خارج از شبکه داکر کانتینر اجرا شده است: `127.0.0.1` یا `172.17.0.1`
     - اگر NPM داخل همان شبکه داکر متصل است: `bascol_web`
   - **Forward Port:** `8000`
   - **Cache Assets:** غیرفعال (یا فعال)
   - **Block Common Exploits:** تیک بزنید (Enabled)
   - **Websockets Support:** غیرفعال (پروژه بر پایه WSGI استاندارد است)
4. در تب **SSL**:
   - **SSL Certificate:** گزینه *Request a new SSL Certificate with Let's Encrypt*
   - **Force SSL:** تیک بزنید (Enabled)
   - **HTTP/2 Support:** تیک بزنید (Enabled)
   - **HSTS Enabled:** پس از اطمینان از عملکرد صحیح SSL تیک بزنید.
   - **I Agree to the Let's Encrypt Terms:** تیک بزنید.
5. در تب **Advanced** (اختیاری جهت افزایش سقف آپلود برای فایل‌های اکسل و تصاویر):
   ```nginx
   client_max_body_size 50M;
   proxy_read_timeout 180s;
   proxy_connect_timeout 180s;
   ```
6. روی دکمه **Save** کلیک نمایید.

---

## ۵. تنظیمات با Nginx بومی (Native Nginx Config)

در صورتی که به جای NPM از Nginx مستقیم روی اوبونتو استفاده می‌کنید، یک کانفیگ در `/etc/nginx/sites-available/bascol.ferion.ir` ایجاد کنید:

```nginx
server {
    server_name bascol.ferion.ir www.bascol.ferion.ir;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 180;
        proxy_connect_timeout 180;
    }

    # لاگ‌های اختصاصی
    access_log /var/log/nginx/bascol_access.log;
    error_log /var/log/nginx/bascol_error.log;
}
```
سپس فعال‌سازی و صدور SSL با Certbot:
```bash
sudo ln -s /etc/nginx/sites-available/bascol.ferion.ir /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d bascol.ferion.ir -d www.bascol.ferion.ir
```

---

## ۶. فرآیند استاندارد به‌روزرسانی (Update Procedure)

برای اعمال تغییرات و آپدیت‌های آینده بدون اختلال یا افت اطلاعات:
```bash
cd /opt/prima_bascol

# دریافت آخرین تغییرات از مخزن گیت
git pull origin master

# بازسازی ایمیج وب
docker compose build web

# اعمال تغییرات احتمالی در دیتابیس
docker compose run --rm web python manage.py migrate --noinput

# به‌روزرسانی فایل‌های استاتیک
docker compose run --rm web python manage.py collectstatic --noinput

# بالا آوردن کانتینر جدید
docker compose up -d

# بررسی وضعیت
docker compose ps
```

---

## ۷. پشتیبان‌گیری و بازیابی داده‌ها (Backup & Restore)

> [!CAUTION]
> هرگز برای مدیریت روزمره از دستور `docker compose down -v` استفاده نکنید زیرا کلید `-v` والیوم‌های دیتابیس را حذف خواهد کرد! دستور صحیح توقف `docker compose down` است.

### ۷.۱. تهیه پشتیبان از دیتابیس PostgreSQL با `pg_dump`
```bash
# ایجاد پوشه بکاپ
mkdir -p /opt/backups

# استخراج نسخه پشتیبان فشرده
docker compose exec -T db pg_dump -U postgres -d prima_bascol -F c -b -v > /opt/backups/bascol_db_$(date +%Y%m%d_%H%M%S).dump

# مشاهده فایل‌های پشتیبان
ls -lh /opt/backups
```

### ۷.۲. تهیه پشتیبان از فایل‌های رسانه (Media Files)
```bash
# کپی فایل‌های آپلود شده از کانتینر به آرشیو فشرده
docker compose cp web:/app/media /opt/backups/media_$(date +%Y%m%d_%H%M%S)
tar -czvf /opt/backups/media_$(date +%Y%m%d_%H%M%S).tar.gz -C /opt/backups media_*
```

### ۷.۳. بازیابی اطلاعات (Restore Procedure)
```bash
# ۱. بازیابی دیتابیس از فایل dump:
docker compose exec -T db pg_restore -U postgres -d prima_bascol -c -v < /opt/backups/bascol_db_FILENAME.dump

# ۲. بازیابی فایل‌های رسانه:
tar -xzvf /opt/backups/media_FILENAME.tar.gz -C /tmp/
docker compose cp /tmp/media/. web:/app/media/
```

---

## ۸. زمان‌بندی بررسی خودکار خودروهای باز (Smart Monitoring Cron)

جهت اجرای دوره‌ای قانون بررسی خودروهای بیش از حد متوقف‌شده در محوطه باسکول:
```bash
# باز کردن crontab سرور
crontab -e

# افزودن دستور اجرای هر ۱۵ دقیقه:
*/15 * * * * cd /opt/prima_bascol && docker compose exec -T web python manage.py check_open_tickets >> /var/log/bascol_cron.log 2>&1
```

---

## ۹. فهرست بررسی و اعتبارسنجی نهایی (Health & Verification Checklist)

پس از بالا آمدن سامانه، موارد زیر را بررسی فرمایید:
- [ ] تست بررسی سلامت سرور: `curl -I https://bascol.ferion.ir/health/` (باید کد `200 OK` برگرداند)
- [ ] ورود به سامانه: `https://bascol.ferion.ir/accounts/login/`
- [ ] پنل ادمین جنگو: `https://bascol.ferion.ir/admin/`
- [ ] مستندات تعاملی API Swagger: `https://bascol.ferion.ir/api/docs/`
- [ ] مستندات اسکیما API: `https://bascol.ferion.ir/api/schema/`
- [ ] دریافت توکن JWT: ارسال درخواست `POST` به `/api/v1/auth/token/`
- [ ] رفرش توکن JWT: ارسال درخواست `POST` به `/api/v1/auth/token/refresh/`
- [ ] خروجی لاگ‌های زنده: `docker compose logs -f`
