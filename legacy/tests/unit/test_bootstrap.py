# tests/unit/test_bootstrap.py
"""Безопасный bootstrap: sparse секреты, сохранение existing env и скрытые validation inputs."""

from unittest.mock import Mock

import pytest
from cryptography.fernet import Fernet
from dotenv import dotenv_values
from pydantic import ValidationError

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


def test_settings_errors_hide_secret_values():
    """Ошибка startup не печатает реальные passwords из environment input."""
    with pytest.raises(ValidationError) as result:
        Settings(
            app_env="production", django_secret_key="", postgres_password="private-test-secret"
        )
    assert "private-test-secret" not in str(result.value)


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
