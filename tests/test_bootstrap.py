# tests/test_bootstrap.py
"""
Регрессионные тесты начальной конфигурации Django.

Проверяют импортируемость проекта, изоляцию тестовой БД,
безопасность feature flags, доступность статических файлов
и корректное подключение class-based health endpoint.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.staticfiles import finders
from django.template.loader import get_template
from django.test import Client
from django.urls import resolve

from watch_app.views import LivenessView


def test_django_uses_project_settings() -> None:
    """Подтверждает загрузку настроек текущего проекта через пакет config."""
    assert settings.ROOT_URLCONF == "config.urls"
    assert settings.USE_TZ is True
    assert settings.LANGUAGE_CODE == "ru-ru"


def test_testing_database_is_isolated() -> None:
    """Не допускает обращения bootstrap-тестов к production PostgreSQL."""
    assert settings.APP_ENV == "testing"
    assert settings.DATABASES["default"]["ENGINE"] == ("django.db.backends.sqlite3")


def test_notifications_are_disabled() -> None:
    """Проверяет отключение всех внешних отправок в тестовом окружении."""
    assert settings.NOTIFICATIONS_ENABLED is False
    assert settings.EMAIL_NOTIFICATIONS_ENABLED is False
    assert settings.TELEGRAM_NOTIFICATIONS_ENABLED is False


def test_health_endpoint_uses_cbv() -> None:
    """Проверяет URL resolution именно на class-based view."""
    match = resolve("/health/live")

    assert match.func.view_class is LivenessView


def test_health_endpoint_response() -> None:
    """Подтверждает JSON ответ без необходимости создавать базу данных."""
    response = Client().get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_existing_styles_are_discoverable() -> None:
    """Проверяет обнаружение перенесённых static assets Django."""
    assert finders.find("css/style.css") is not None


def test_existing_base_template_is_discoverable() -> None:
    """Подтверждает доступность базового HTML шаблона после настройки DIRS."""
    assert get_template("base.html") is not None
