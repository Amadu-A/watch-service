# src/accounts_app/apps.py
"""Регистрация Django-приложения accounts с совместимой меткой БД."""

from django.apps import AppConfig


class AccountsAppConfig(AppConfig):
    """Сохраняет метку accounts для ранее созданных миграций."""

    name = "accounts_app"
    label = "accounts"
