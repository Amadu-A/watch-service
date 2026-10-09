# src/persistence_app/apps.py
"""Регистрация Django-приложения persistence с совместимой меткой БД."""

from django.apps import AppConfig


class PersistenceAppConfig(AppConfig):
    """Сохраняет метку persistence для ранее созданных миграций."""

    name = "persistence_app"
    label = "persistence"
