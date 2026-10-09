# src/core/config.py
"""Слоистая конфигурация приложения: baseline, приватный файл и process environment."""

from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Типизированные параметры; секреты скрыты в repr и не выдаются транспортом."""

    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        extra="ignore",
        case_sensitive=False,
        hide_input_in_errors=True,
    )
    app_env: str = "development"
    django_debug: bool = False
    django_secret_key: SecretStr = SecretStr("")
    django_allowed_hosts: str = "localhost,127.0.0.1"
    django_csrf_trusted_origins: str = ""
    django_secure_cookies: bool = True
    database_engine: str = "postgresql"
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "warehouse_watch"
    postgres_user: str = "warehouse_watch"
    postgres_password: SecretStr = SecretStr("")
    redis_url: str = "redis://redis:6379/0"
    rabbitmq_host: str = "rabbitmq"
    rabbitmq_port: int = 5672
    rabbitmq_vhost: str = "warehouse-watch"
    rabbitmq_user: str = "warehouse-watch"
    rabbitmq_password: SecretStr = SecretStr("")
    camera_credentials_key: SecretStr = SecretStr("")
    default_timezone: str = "Europe/Moscow"
    media_retention_days: int = Field(default=30, ge=1, le=30)
    media_root: str = "media"
    monitoring_max_visible_cameras: int = Field(default=16, ge=1, le=64)
    notifications_enabled: bool = False
    email_notifications_enabled: bool = False
    telegram_notifications_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_use_tls: bool = True
    smtp_from_address: str = ""
    telegram_bot_token: SecretStr = SecretStr("")
    notification_max_attempts: int = Field(default=5, ge=1, le=20)
    notification_timeout_seconds: int = Field(default=15, ge=1, le=120)
    vision_enabled: bool = False
    vision_device: str = "cpu"
    vision_model: str = "models/yolo11n.pt"
    vision_fps: int = Field(default=5, ge=1, le=30)
    vision_frame_ttl_seconds: int = Field(default=10, ge=1)
    vision_track_ttl_seconds: int = Field(default=30, ge=1)
    vision_min_track_frames: int = Field(default=3, ge=2)
    vision_stable_frames: int = Field(default=2, ge=1)
    vision_hysteresis: float = Field(default=0.02, gt=0, lt=0.5)
    vision_reconnect_max_seconds: int = Field(default=60, ge=1)
    evidence_before_seconds: float = Field(default=1, ge=0, le=10)
    evidence_after_seconds: float = Field(default=1, ge=0, le=10)
    event_clip_enabled: bool = False
    clip_before_seconds: float = Field(default=5, ge=0, le=10)
    clip_after_seconds: float = Field(default=5, ge=0, le=10)
    report_font_path: str = ""
    log_level: str = "INFO"

    @model_validator(mode="after")
    def validate_production(self) -> "Settings":
        """Отклоняет небезопасный production baseline без печати секретных значений."""
        if self.app_env == "production":
            if not self.django_secret_key.get_secret_value():
                raise ValueError("В production требуется DJANGO_SECRET_KEY")
            if self.database_engine != "postgresql" or self.django_debug:
                raise ValueError("В production требуется PostgreSQL и отключённый DEBUG")
            if self.vision_enabled and self.vision_device == "cpu":
                raise ValueError("CPU в production запрещён: задайте VISION_DEVICE явно")
        return self
