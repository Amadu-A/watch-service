# tests/unit/test_bootstrap.py
"""Безопасный bootstrap: sparse секреты, сохранение existing env и скрытые validation inputs."""

import json
import socket
import subprocess
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


@pytest.mark.parametrize(
    "endpoint",
    ["", "file:///model.pt", "http://user:secret@shared-cv/", "http://shared-cv/?token=secret"],
)
def test_inference_requires_explicit_safe_http_contract(endpoint):
    """Включённый inference требует внешний endpoint без секретов в URL и физического GPU."""
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None, app_env="testing", vision_enabled=True, vision_inference_url=endpoint
        )
    config = Settings(
        _env_file=None,
        app_env="testing",
        vision_enabled=True,
        vision_inference_url="http://shared-cv/v1/person-tracks",
    )
    assert not hasattr(config, "vision_device") and not hasattr(config, "vision_model")


def broker_settings(monkeypatch):
    """Подменяет секреты и namespace для изолированной проверки bootstrap."""
    config = Settings(_env_file=None, app_env="testing", rabbitmq_password="private-broker-secret")
    monkeypatch.setattr(bootstrap, "Settings", lambda: config)
    monkeypatch.setenv("SHARED_NETWORK", "ai-shared")
    return config


def test_rabbit_stopped_container_is_reported_without_lifecycle_change(monkeypatch):
    """Остановленный shared брокер не запускается и не пересоздаётся прикладным сервисом."""
    broker_settings(monkeypatch)
    command = Mock(return_value=json.dumps({"Running": False, "Status": "exited"}))
    monkeypatch.setattr(bootstrap, "docker_command", command)
    with pytest.raises(RuntimeError, match="shared-infrastructure"):
        bootstrap.provision_rabbitmq("shared-rabbitmq-1")
    assert [call.args[0] for call in command.call_args_list] == ["inspect"]


def test_rabbit_existing_namespace_is_updated_without_shared_restart(monkeypatch, capsys):
    """Настройка обновляет только проектный пароль и права, сохраняя работающий shared брокер."""
    broker_settings(monkeypatch)
    command = Mock(
        side_effect=[
            json.dumps({"Running": True}),
            json.dumps({"ai-shared": {"Aliases": ["rabbitmq"]}}),
            "warehouse-watch\t[]\nother-project\t[]",
            "warehouse-watch\nother-project",
            "",
            "",
        ]
    )
    monkeypatch.setattr(bootstrap, "docker_command", command)
    monkeypatch.setattr(bootstrap, "wait_for_rabbitmq", Mock())
    bootstrap.provision_rabbitmq("shared-rabbitmq-1")
    commands = [call.args for call in command.call_args_list]
    assert not any(item[0] in ("start", "restart", "stop", "rm") for item in commands)
    assert commands[-1] == (
        "exec",
        "shared-rabbitmq-1",
        "rabbitmqctl",
        "set_permissions",
        "-p",
        "warehouse-watch",
        "warehouse-watch",
        r"^warehouse\..*",
        r"^warehouse\..*",
        r"^warehouse\..*",
    )
    assert "private-broker-secret" not in capsys.readouterr().out


def test_rabbit_readiness_has_bounded_wait(monkeypatch):
    """Неготовый RabbitMQ не вызывает бесконечное ожидание или команды настройки."""
    elapsed = [0.0]
    monkeypatch.setattr(bootstrap.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(
        bootstrap.time, "sleep", lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds)
    )
    run = Mock(return_value=Mock(returncode=1))
    monkeypatch.setattr(bootstrap.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="docker logs"):
        bootstrap.wait_for_rabbitmq("shared-rabbitmq-1", timeout_seconds=2)
    assert elapsed[0] == 2 and run.call_count == 2
    assert all(call.kwargs["timeout"] <= 2 for call in run.call_args_list)


@pytest.mark.parametrize(
    "failure",
    [socket.gaierror("private-broker-secret"), ConnectionRefusedError("private-broker-secret")],
)
def test_broker_preflight_reports_connectivity_without_secret(monkeypatch, failure):
    """DNS и недоступный listener обнаруживаются до сборки тестов без вывода пароля."""
    broker_settings(monkeypatch)
    connection = Mock()
    connection.__enter__ = Mock(return_value=connection)
    connection.__exit__ = Mock(return_value=False)
    connection.ensure_connection.side_effect = failure
    monkeypatch.setattr(bootstrap, "Connection", Mock(return_value=connection))
    with pytest.raises(RuntimeError) as result:
        bootstrap.check_broker()
    assert "RabbitMQ" in str(result.value) and "private-broker-secret" not in str(result.value)


def test_docker_failure_hides_password_argv(monkeypatch):
    """Ошибка Docker не печатает argv или stderr команды смены пароля."""
    command = [
        "docker",
        "exec",
        "rabbit",
        "rabbitmqctl",
        "change_password",
        "warehouse-watch",
        "private-broker-secret",
    ]
    monkeypatch.setattr(
        bootstrap.subprocess,
        "run",
        Mock(side_effect=subprocess.CalledProcessError(1, command, stderr="private-broker-secret")),
    )
    with pytest.raises(RuntimeError) as result:
        bootstrap.docker_command(*command[1:])
    assert "private-broker-secret" not in str(result.value)
