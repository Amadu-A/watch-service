# tests/unit/test_bootstrap.py
"""Безопасный bootstrap: sparse секреты, сохранение existing env и скрытые validation inputs."""

import sys
from unittest.mock import Mock

import pytest
from cryptography.fernet import Fernet
from dotenv import dotenv_values
from pydantic import SecretStr, ValidationError

from core import bootstrap
from core.config import Settings


def test_environment_init_is_private_sparse_and_idempotent(monkeypatch, tmp_path, capsys):
    """Инициализация создаёт уникальные ключи, не перезаписывает значения и не выводит секреты."""
    monkeypatch.setattr(bootstrap, "ROOT", tmp_path)
    bootstrap.init_environment()
    path = tmp_path / ".env"
    initial = path.read_bytes()
    values = dotenv_values(path)
    assert set(values) == {
        "APP_ENV",
        "DJANGO_SECRET_KEY",
        "CAMERA_CREDENTIALS_KEY",
        "POSTGRES_PASSWORD",
        "RABBITMQ_PASSWORD",
    }
    assert len(values["DJANGO_SECRET_KEY"]) >= 32
    Fernet(values["CAMERA_CREDENTIALS_KEY"].encode())
    bootstrap.init_environment()
    assert path.read_bytes() == initial
    output = capsys.readouterr().out
    assert all(value not in output for value in values.values())


def test_sparse_production_uses_safe_code_defaults(monkeypatch):
    """Короткий production env наследует безопасные значения из кода."""
    for key in ("DJANGO_SECURE_COOKIES", "VISION_ENABLED", "DATABASE_ENGINE"):
        monkeypatch.delenv(key, raising=False)
    config = Settings(
        _env_file=None,
        app_env="production",
        django_secret_key="local-test-secret",
    )
    assert config.database_engine == "postgresql"
    assert config.django_secure_cookies is True
    assert config.django_debug is False
    assert config.vision_enabled is False
    assert config.notifications_enabled is False


def test_settings_errors_hide_secret_values():
    """Ошибка startup не печатает реальные passwords из environment input."""
    with pytest.raises(ValidationError) as result:
        Settings(
            app_env="production", django_secret_key="", postgres_password="private-test-secret"
        )
    assert "private-test-secret" not in str(result.value)


def test_preflight_rejects_missing_password(monkeypatch):
    """Серверная предпроверка останавливается до запуска БД без обязательного пароля."""
    config = Mock(
        app_env="production",
        postgres_password=SecretStr(""),
        rabbitmq_password=SecretStr("broker-password"),
        camera_credentials_key=SecretStr("camera-key"),
        django_secure_cookies=True,
    )
    monkeypatch.setattr(bootstrap, "Settings", lambda: config)
    monkeypatch.setattr(sys, "argv", ["bootstrap", "check"])
    with pytest.raises(ValueError, match="POSTGRES_PASSWORD"):
        bootstrap.main()


def test_existing_model_is_preserved(monkeypatch, tmp_path):
    """Повторная подготовка модели не меняет локальный файл и не идёт в сеть."""
    path = tmp_path / "model.pt"
    path.write_bytes(b"existing-model")
    monkeypatch.setattr(bootstrap, "ROOT", tmp_path)
    monkeypatch.setattr(bootstrap, "Settings", lambda: Mock(vision_model="model.pt"))
    opener = Mock()
    monkeypatch.setattr(bootstrap.urllib.request, "urlopen", opener)
    bootstrap.download_model()
    opener.assert_not_called()
    assert path.read_bytes() == b"existing-model"
