# tests/test_django_bootstrap.py
"""
Тесты начального Django bootstrap.

Проверяют настройки, CBV, доступность templates/static,
отсутствие внешних отправок и плоский settings.py.

Не используют production PostgreSQL,
Redis, RabbitMQ или реальную камеру.
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.template.loader import get_template
from django.test import Client
from django.urls import resolve

from interface.pages import LivenessView


def test_django_uses_project_settings() -> None:
    """Проверяет загрузку настроек текущего проекта."""
    assert settings.ROOT_URLCONF == "config.urls"
    assert settings.USE_TZ is True
    assert settings.LANGUAGE_CODE == "ru-ru"


def test_settings_remain_single_python_module() -> None:
    """Защищает согласованную плоскую структуру settings.py."""
    module = import_module("config.settings")

    assert Path(module.__file__).name == "settings.py"


def test_testing_database_is_isolated() -> None:
    """Проверяет, что тесты используют SQLite либо отдельную контейнерную PostgreSQL."""
    assert settings.APP_ENV == "testing"
    database = settings.DATABASES["default"]
    if database["ENGINE"] == "django.db.backends.postgresql":
        assert str(database["NAME"]).startswith("test_warehouse_tests")
        assert database["HOST"] == "test-postgres"
    else:
        assert database["ENGINE"] == "django.db.backends.sqlite3"


def test_notifications_are_disabled() -> None:
    """Проверяет отключение всех внешних каналов отправки."""
    assert settings.NOTIFICATIONS_ENABLED is False
    assert settings.EMAIL_NOTIFICATIONS_ENABLED is False
    assert settings.TELEGRAM_NOTIFICATIONS_ENABLED is False


def test_event_clips_are_disabled() -> None:
    """Проверяет исходное отключение необязательной записи видеоклипов."""
    assert settings.EVENT_CLIP_ENABLED is False


def test_health_endpoint_uses_cbv() -> None:
    """Проверяет подключение health endpoint через Class-Based View."""
    match = resolve("/health/live")

    assert match.func.view_class is LivenessView


def test_health_endpoint_response() -> None:
    """Проверяет HTTP-ответ без обращения к внешней инфраструктуре."""
    response = Client().get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_existing_styles_are_discoverable() -> None:
    """Проверяет обнаружение уже перенесённых CSS-файлов."""
    assert finders.find("css/style.css") is not None


def test_existing_base_template_is_discoverable() -> None:
    """Проверяет обнаружение базового шаблона Django."""
    assert get_template("base.html") is not None
