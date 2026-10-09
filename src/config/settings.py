# src/config/settings.py
"""
Базовые настройки Django Warehouse Perimeter Watch.

Конфигурация рассчитана на локальную разработку без приватного .env
и на production с обязательными внешними секретами.

Регистрирует перенесённые приложения с совместимыми метками БД.
"""

from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured

from config.runtime import PROJECT_ROOT, RuntimeSettings

runtime = RuntimeSettings()

BASE_DIR = PROJECT_ROOT

APP_ENV = runtime.app_env
DEBUG = runtime.django_debug

_secret_key = runtime.django_secret_key.get_secret_value()

if APP_ENV == "production":
    if not _secret_key:
        raise ImproperlyConfigured("Для production необходимо задать DJANGO_SECRET_KEY.")

    if DEBUG:
        raise ImproperlyConfigured("DJANGO_DEBUG должен быть false в production.")

    if runtime.database_engine != "postgresql":
        raise ImproperlyConfigured("Для production требуется PostgreSQL.")

    if not runtime.django_secure_cookies:
        raise ImproperlyConfigured("Для production необходимо включить защищённые cookies.")

SECRET_KEY = _secret_key or "unsafe-local-development-only-not-for-production"

ALLOWED_HOSTS = [host.strip() for host in runtime.django_allowed_hosts.split(",") if host.strip()]

CSRF_TRUSTED_ORIGINS = [
    origin.strip() for origin in runtime.django_csrf_trusted_origins.split(",") if origin.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "accounts_app.apps.AccountsAppConfig",
    "persistence_app.apps.PersistenceAppConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "interface.middleware.RequestIdMiddleware",
]

ROOT_URLCONF = "config.urls"
AUTH_USER_MODEL = "accounts.User"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            BASE_DIR / "templates",
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

if runtime.database_engine == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": runtime.postgres_db,
            "USER": runtime.postgres_user,
            "PASSWORD": runtime.postgres_password.get_secret_value(),
            "HOST": runtime.postgres_host,
            "PORT": runtime.postgres_port,
        },
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        },
    }

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": ("django.contrib.auth.password_validation.UserAttributeSimilarityValidator"),
    },
    {
        "NAME": ("django.contrib.auth.password_validation.MinimumLengthValidator"),
    },
    {
        "NAME": ("django.contrib.auth.password_validation.CommonPasswordValidator"),
    },
    {
        "NAME": ("django.contrib.auth.password_validation.NumericPasswordValidator"),
    },
]

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

STATICFILES_DIRS = [
    BASE_DIR / "static",
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = runtime.django_secure_cookies
CSRF_COOKIE_SECURE = runtime.django_secure_cookies
SESSION_COOKIE_SAMESITE = "Lax"

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

NOTIFICATIONS_ENABLED = runtime.notifications_enabled
EMAIL_NOTIFICATIONS_ENABLED = runtime.email_notifications_enabled
TELEGRAM_NOTIFICATIONS_ENABLED = runtime.telegram_notifications_enabled
EVENT_CLIP_ENABLED = runtime.event_clip_enabled

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": ("drf_spectacular.openapi.AutoSchema"),
    "EXCEPTION_HANDLER": "interface.errors.exception_handler",
}

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/monitoring/"
LOGOUT_REDIRECT_URL = "/login/"

SPECTACULAR_SETTINGS = {
    "TITLE": "Warehouse Perimeter Watch",
    "VERSION": "1.0.0",
    "DESCRIPTION": "Защищённый API видеоконтроля склада.",
    "SERVE_INCLUDE_SCHEMA": False,
}
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "core.logging.JsonFormatter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "root": {"handlers": ["console"], "level": runtime.log_level},
    "loggers": {"httpx": {"level": "WARNING"}, "httpcore": {"level": "WARNING"}},
}
