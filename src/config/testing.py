# src/config/testing.py
"""
Изолированная конфигурация автоматических тестов.

Использует SQLite локально и отдельный PostgreSQL в контейнерных тестах,
не допуская внешних уведомлений или записи в рабочие сервисы.

Значения устанавливаются до импорта основных Django settings.
"""

from __future__ import annotations

import os
from importlib import import_module

os.environ["APP_ENV"] = "testing"
os.environ.setdefault("DATABASE_ENGINE", "sqlite")
os.environ["DJANGO_DEBUG"] = "false"
os.environ["DJANGO_ALLOWED_HOSTS"] = "localhost,127.0.0.1,testserver"

os.environ["NOTIFICATIONS_ENABLED"] = "false"
os.environ["EMAIL_NOTIFICATIONS_ENABLED"] = "false"
os.environ["TELEGRAM_NOTIFICATIONS_ENABLED"] = "false"
os.environ["EVENT_CLIP_ENABLED"] = "false"

_base_settings = import_module("config.settings")

for _name in dir(_base_settings):
    if _name.isupper():
        globals()[_name] = getattr(_base_settings, _name)

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

DATABASES = _base_settings.DATABASES
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = True
if DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    DATABASES["default"]["OPTIONS"] = {"cached_statements": 0}
