# src/config/settings.py
"""Настройки Django; SQL и секреты остаются за границами application/domain."""

from core.config import ROOT, Settings

env = Settings()
BASE_DIR = ROOT
SECRET_KEY = env.django_secret_key.get_secret_value()
if not SECRET_KEY:
    # Только изолированные проверки могут работать с таким ключом.
    if env.database_engine != "sqlite":
        raise ValueError("Задайте DJANGO_SECRET_KEY в .env")
    SECRET_KEY = "isolated-tests-only-never-use-in-production"
DEBUG = env.django_debug
ALLOWED_HOSTS = env.django_allowed_hosts.split(",")
CSRF_TRUSTED_ORIGINS = list(filter(None, env.django_csrf_trusted_origins.split(",")))
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
AUTH_USER_MODEL = "accounts.User"
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "modules.accounts",
    "modules.persistence",
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
    "core.middleware.RequestIdMiddleware",
]
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [ROOT / "src/web/templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env.postgres_db,
        "USER": env.postgres_user,
        "PASSWORD": env.postgres_password.get_secret_value(),
        "HOST": env.postgres_host,
        "PORT": env.postgres_port,
        "CONN_MAX_AGE": 60,
    }
}
if env.database_engine == "sqlite":
    DATABASES = {
        "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ROOT / "local.sqlite3"}
    }
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "UTC"
USE_TZ = True
USE_I18N = True
STATIC_URL = "/static/"
STATIC_ROOT = ROOT / "staticfiles"
STATICFILES_DIRS = [ROOT / "src/web/static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/monitoring/"
LOGOUT_REDIRECT_URL = "/login/"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = env.django_secure_cookies
CSRF_COOKIE_SECURE = env.django_secure_cookies
SESSION_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "web.errors.exception_handler",
}
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
    "root": {"handlers": ["console"], "level": env.log_level},
    "loggers": {"httpx": {"level": "WARNING"}, "httpcore": {"level": "WARNING"}},
}
