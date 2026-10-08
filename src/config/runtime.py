# src/config/runtime.py
"""
Типизированная конфигурация окружения Warehouse Perimeter Watch.

Читает безопасный baseline из .env.example и приватные переопределения
из .env. Значения переменных процесса имеют наивысший приоритет.

Не открывает соединений с БД или внешними сервисами.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class RuntimeSettings(BaseSettings):
    """
    Содержит настройки начального Django-каркаса.

    Неизвестные переменные baseline игнорируются: они будут типизированы
    на следующих этапах при переносе соответствующих модулей.
    """

    model_config = SettingsConfigDict(
        env_file=(
            PROJECT_ROOT / ".env.example",
            PROJECT_ROOT / ".env",
        ),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["development", "testing", "production"] = "development"

    django_debug: bool = False
    django_secret_key: SecretStr = SecretStr("")
    django_allowed_hosts: str = "localhost,127.0.0.1"
    django_csrf_trusted_origins: str = ""
    django_secure_cookies: bool = False

    database_engine: Literal["sqlite", "postgresql"] = "sqlite"
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "warehouse_watch"
    postgres_user: str = "warehouse_watch"
    postgres_password: SecretStr = SecretStr("")

    notifications_enabled: bool = False
    email_notifications_enabled: bool = False
    telegram_notifications_enabled: bool = False
    event_clip_enabled: bool = False
