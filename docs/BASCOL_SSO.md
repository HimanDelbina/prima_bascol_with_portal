# ورود سازمانی باسکول

روی محیط آزمایشی و شاخه develop اجرا شود. ابتدا وابستگی‌ها را نصب و migration حساب‌ها را اجرا کنید. سپس متغیرهای زیر را در محیط سرویس قرار دهید.

- BASCOL_SSO_ENABLED=True
- BASCOL_OIDC_ISSUER=https://auth.ferion.ir/realms/ferion
- BASCOL_OIDC_CLIENT_ID=ferion-bascol
- BASCOL_OIDC_CLIENT_SECRET از Keycloak
- BASCOL_OIDC_REDIRECT_URI آدرس HTTPS محیط آزمایشی به همراه مسیر /accounts/oidc/callback/

در Keycloak کلاینت باید confidential با Standard Flow و callback دقیق باشد. Audience کلاینت ferion-bascol باید به توکن دسترسی اضافه شود. نقش کلاینت bascol-user را برای حساب آزمایشی تخصیص دهید.

مدیر محلی در Django Admin از «پیوندهای حساب سازمانی» یک پیوند برای حساب محلی موجود با issuer و subject کاربر Keycloak ثبت می‌کند. subject شناسه کاربر در Keycloak است. نقش باسکول از پروفایل حساب محلی خوانده می‌شود. حساب‌های مدیریتی Django و نقش‌های system_admin و super_admin برای ورود سازمانی کنار گذاشته می‌شوند.

برای آزمایش از /accounts/oidc/login/ وارد شوید. بررسی کنید حساب پیوندخورده با نقش اپراتور وارد شود و حساب بدون پیوند یا بدون نقش bascol-user با 403 رد شود. غیرفعال کردن پیوند باید نشست جاری را در درخواست بعدی متوقف کند. خروج عادی نشست محلی را می‌بندد. پس از انقضای توکن دسترسی، درخواست خواندن کاربر را برای ورود مجدد به Keycloak می‌برد. این نسخه تمدید در پس‌زمینه ندارد و درخواست نوشتن منقضی را اجرا نمی‌کند.
