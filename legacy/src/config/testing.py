# src/config/testing.py
"""Изолированная конфигурация pytest; production БД не используется по умолчанию."""

import importlib
import os

os.environ.setdefault("DATABASE_ENGINE", "sqlite")
os.environ["APP_ENV"] = "testing"
os.environ["DJANGO_ALLOWED_HOSTS"] = "localhost,127.0.0.1,testserver"
os.environ["NOTIFICATIONS_ENABLED"] = "false"
base = importlib.import_module("config.settings")
globals().update({key: getattr(base, key) for key in dir(base) if key.isupper()})
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = True
DATABASES = base.DATABASES
if DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    # LiveServer делит SQLite connection между threads; CPython issue #118172.
    DATABASES["default"]["OPTIONS"] = {"cached_statements": 0}
