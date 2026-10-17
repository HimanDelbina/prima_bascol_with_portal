"""
Django settings for prima_bascol project.
Comprehensive Industrial Weighbridge Management System (سامانه جامع باسکول صنعتی).
"""

from pathlib import Path
import os
import ipaddress
from datetime import timedelta

# Try loading environment variables from .env if present
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / '.env')
except ImportError:
    pass

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    os.environ.get('SECRET_KEY', 'django-insecure-=y$+k=y&1v8urdlo#y+l7f_k1f0&(ad4sx6)025l*kiv#$(qob')
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DJANGO_DEBUG', 'False').lower() in ('true', '1', 'yes')

# Allowed Hosts & Internal Network configuration
raw_allowed_hosts = os.environ.get('DJANGO_ALLOWED_HOSTS', os.environ.get('ALLOWED_HOSTS', ''))
if raw_allowed_hosts:
    ALLOWED_HOSTS = [h.strip() for h in raw_allowed_hosts.split(',') if h.strip()]
    for primary_host in ('bascol.ferion.ir', 'www.bascol.ferion.ir', 'localhost', '127.0.0.1'):
        if primary_host not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(primary_host)
elif DEBUG:
    ALLOWED_HOSTS = ['*']
else:
    ALLOWED_HOSTS = [
        'bascol.ferion.ir',
        'www.bascol.ferion.ir',
        'localhost',
        '127.0.0.1',
        'web',
        'testserver',
    ]

# Optional Internal / LAN IPs support (e.g. DJANGO_INTERNAL_IPS=192.168.10.50,192.168.10.51)
raw_internal_ips = os.environ.get('DJANGO_INTERNAL_IPS', os.environ.get('INTERNAL_IPS', ''))
INTERNAL_IPS_LIST = []
if raw_internal_ips:
    for raw_ip in raw_internal_ips.split(','):
        clean_ip = raw_ip.strip()
        if not clean_ip:
            continue
        try:
            ip_obj = ipaddress.ip_address(clean_ip)
            # Bracket IPv6 addresses per RFC 3986, keep IPv4 plain
            formatted_ip = f"[{ip_obj}]" if ip_obj.version == 6 else str(ip_obj)
            INTERNAL_IPS_LIST.append(formatted_ip)
            if formatted_ip not in ALLOWED_HOSTS:
                ALLOWED_HOSTS.append(formatted_ip)
            if ip_obj.version == 6 and str(ip_obj) not in ALLOWED_HOSTS:
                ALLOWED_HOSTS.append(str(ip_obj))
        except ValueError:
            # Skip invalid non-IP strings to prevent misconfiguration in production
            pass

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    
    # Third-party Apps
    'corsheaders',
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'drf_spectacular',
    'django_filters',

    # Project Apps
    'core.apps.CoreConfig',
    'accounts.apps.AccountsConfig',
    'masterdata.apps.MasterdataConfig',
    'weighbridge.apps.WeighbridgeConfig',
    'reports.apps.ReportsConfig',
    'audit.apps.AuditConfig',
    'dashboard.apps.DashboardConfig',
    'management.apps.ManagementConfig',
    'monitoring.apps.MonitoringConfig',
    'shifts.apps.ShiftsConfig',
    'api.apps.ApiConfig',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    
    # Audit & IP context middleware
    'core.middleware.ThreadLocalRequestMiddleware',
]

ROOT_URLCONF = 'prima_bascol.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.global_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'prima_bascol.wsgi.application'

# Database Configuration (PostgreSQL with psycopg 3)
db_url = os.environ.get('DATABASE_URL', '')
if db_url:
    import urllib.parse
    parsed_db_url = urllib.parse.urlparse(db_url)
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': parsed_db_url.path[1:],
            'USER': parsed_db_url.username or '',
            'PASSWORD': parsed_db_url.password or '',
            'HOST': parsed_db_url.hostname or 'localhost',
            'PORT': str(parsed_db_url.port or 5432),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('POSTGRES_DB', os.environ.get('DB_NAME', 'prima_bascol')),
            'USER': os.environ.get('POSTGRES_USER', os.environ.get('DB_USER', 'postgres')),
            'PASSWORD': os.environ.get('POSTGRES_PASSWORD', os.environ.get('DB_PASSWORD', '11193')),
            'HOST': os.environ.get('POSTGRES_HOST', os.environ.get('DB_HOST', 'localhost')),
            'PORT': str(os.environ.get('POSTGRES_PORT', os.environ.get('DB_PORT', '5432'))),
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 4},
    },
]

# Internationalization & Localization
LANGUAGE_CODE = 'fa-ir'
TIME_ZONE = 'Asia/Tehran'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# WhiteNoise storage: compress and hash static files for caching in production
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
WHITENOISE_MANIFEST_STRICT = False

# Media files (Persistent user uploaded files)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Authentication URLs
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ==========================================
# REST Framework Configuration
# ==========================================
from datetime import timedelta

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS': 'api.v1.pagination.StandardResultsSetPagination',
    'PAGE_SIZE': 25,
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ),
    'EXCEPTION_HANDLER': 'api.v1.exceptions.custom_exception_handler',
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_THROTTLE_CLASSES': [
        'api.v1.throttling.CustomAnonRateThrottle',
        'api.v1.throttling.CustomUserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '60/min',
        'user': '300/min',
        'auth': '10/min',
        'password_reauth': '5/min',
        'export': '20/min',
    },
}

# ==========================================
# Simple JWT Configuration
# ==========================================
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': os.environ.get('DJANGO_JWT_SECRET_KEY', SECRET_KEY),
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'TOKEN_OBTAIN_SERIALIZER': 'api.v1.serializers.auth_serializers.CustomTokenObtainPairSerializer',
}

# ==========================================
# OpenAPI / Spectacular Configuration
# ==========================================
SPECTACULAR_SETTINGS = {
    'TITLE': 'سامانه جامع و پیشرفته باسکول صنعتی (Prima Bascol API)',
    'DESCRIPTION': 'REST API کامل، امن و Production-Ready جهت مدیریت عملیات باسکول، پایش هوشمند، گزارشات و هوش تجاری.',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'TAGS': [
        {'name': 'Authentication', 'description': 'احراز هویت JWT و اطلاعات کاربر جاری'},
        {'name': 'Tickets', 'description': 'عملیات توزین و مدیریت قبوض باسکول'},
        {'name': 'Master Data', 'description': 'اطلاعات پایه: محصولات، طرف‌ها، رانندگان، خودروها و جایگاه‌ها'},
        {'name': 'Dashboard', 'description': 'داشبورد عملیاتی و شاخص‌های لحظه‌ای'},
        {'name': 'Management', 'description': 'هوش تجاری و گزارشات تخصصی مدیران ارشد'},
        {'name': 'Monitoring', 'description': 'ماژول پایش هوشمند و کشف مغایرت‌های توزین'},
        {'name': 'Reports', 'description': 'گزارش‌ساز پویا و خروجی‌های Excel، CSV و PDF'},
        {'name': 'Audit', 'description': 'گزارشات ممیزی و ردگیری تغییرات سیستم'},
        {'name': 'Users', 'description': 'مدیریت کاربران و نقش‌های کاربری'},
        {'name': 'System Settings', 'description': 'تنظیمات سامانه و بررسی سلامت سرویس'},
    ],
}

# ==========================================
# CORS & CSRF Configuration
# ==========================================
# CORS is strictly for Cross-Origin API clients (SPA / external web apps).
# Standard server-rendered Django templates DO NOT require CORS.
CORS_ALLOW_ALL_ORIGINS = False  # NEVER True in production
CORS_ALLOW_CREDENTIALS = True

raw_cors = os.environ.get('DJANGO_CORS_ALLOWED_ORIGINS', os.environ.get('CORS_ALLOWED_ORIGINS', ''))
if raw_cors:
    CORS_ALLOWED_ORIGINS = [c.strip() for c in raw_cors.split(',') if c.strip()]
elif DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True
    CORS_ALLOWED_ORIGINS = []
else:
    CORS_ALLOWED_ORIGINS = [
        "https://bascol.ferion.ir",
        "https://www.bascol.ferion.ir",
    ]

# CSRF Trusted Origins Configuration
raw_csrf = os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', os.environ.get('CSRF_TRUSTED_ORIGINS', ''))
if raw_csrf:
    CSRF_TRUSTED_ORIGINS = [c.strip() for c in raw_csrf.split(',') if c.strip()]
else:
    CSRF_TRUSTED_ORIGINS = [
        "https://bascol.ferion.ir",
        "https://www.bascol.ferion.ir",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost",
        "http://127.0.0.1",
    ]

# Add specific internal IP endpoints (strictly HTTPS in production via reverse proxy + Private CA)
for ip in INTERNAL_IPS_LIST:
    https_origin = f"https://{ip}"
    if https_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(https_origin)
    if DEBUG:
        for dev_origin in (f"http://{ip}", f"http://{ip}:8000"):
            if dev_origin not in CSRF_TRUSTED_ORIGINS:
                CSRF_TRUSTED_ORIGINS.append(dev_origin)

# ==========================================
# Security & Reverse Proxy Settings
# ==========================================
# Trusted proxy SSL header configuration
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True

if not DEBUG:
    # Cookie security: Strict HTTPS on both domain and internal IP (Private CA with IP SAN).
    # Browsers strictly enforce Secure cookies over TLS (RFC 6265).
    # No middleware or configuration dynamically removes the Secure flag.
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = 'same-origin'
    X_FRAME_OPTIONS = 'DENY'
    
    # HSTS: Strict-Transport-Security policy.
    # SecurityMiddleware sends this header ONLY on HTTPS responses (request.is_secure() is True).
    # Browsers ignore HSTS on IP addresses (RFC 6797), preserving full domain security.
    SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_SECURE_HSTS_SECONDS', '3600'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.environ.get('DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS', 'False').lower() in ('true', '1')
    SECURE_HSTS_PRELOAD = False
    
    # Reverse proxy (NPM/Nginx) handles SSL redirect by default
    SECURE_SSL_REDIRECT = os.environ.get('DJANGO_SECURE_SSL_REDIRECT', 'False').lower() in ('true', '1')

# ==========================================
# Logging Configuration (12-Factor stdout/stderr)
# ==========================================
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} [{name}:{lineno}] {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': os.environ.get('DJANGO_LOG_LEVEL', 'INFO'),
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': os.environ.get('DJANGO_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'gunicorn.error': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

