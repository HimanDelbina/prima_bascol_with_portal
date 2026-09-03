"""
Django settings for prima_bascol project.
Comprehensive Industrial Weighbridge Management System (سامانه جامع باسکول صنعتی).
"""

from pathlib import Path
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-=y$+k=y&1v8urdlo#y+l7f_k1f0&(ad4sx6)025l*kiv#$(qob'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ['*']

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
    'api.apps.ApiConfig',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
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

# Database
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql_psycopg2",
        "NAME": "prima_bascol",
        "USER": "postgres",
        "PASSWORD": "11193",
        "HOST": "localhost",
        "PORT": "5432",
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

# Media files
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
    'SIGNING_KEY': SECRET_KEY,
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
# CORS Configuration
# ==========================================
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://192.168.1.105:8000",
    "http://2.184.55.37:5500",
]

