# tests/integration/test_user_command.py
"""Создание ролей с проверкой паролей и защитой существующих пользователей."""

from io import StringIO
from unittest.mock import Mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

pytestmark = pytest.mark.django_db


def test_create_operator_and_reject_existing(monkeypatch, django_user_model):
    """Новый оператор получает нужную роль; повтор команды не меняет его пароль/права."""
    password = "safe-test-only-password-93812"
    prompt = Mock(side_effect=[password, password])
    monkeypatch.setattr("accounts_app.management.commands.create_watch_user.getpass", prompt)
    output = StringIO()
    call_command("create_watch_user", "night-operator", "OPERATOR", stdout=output)
    user = django_user_model.objects.get(username="night-operator")
    assert user.role == "OPERATOR" and user.check_password(password)
    assert not user.is_superuser and password not in output.getvalue()
    with pytest.raises(CommandError, match="Пользователь уже существует"):
        call_command("create_watch_user", "night-operator", "ADMINISTRATOR")
    assert prompt.call_count == 2


def test_weak_password_does_not_create_user(monkeypatch, django_user_model):
    """Password validators действуют также для CLI создания ролей."""
    monkeypatch.setattr(
        "accounts_app.management.commands.create_watch_user.getpass",
        Mock(side_effect=["123", "123"]),
    )
    with pytest.raises(CommandError):
        call_command("create_watch_user", "invalid-password", "VIEWER")
    assert not django_user_model.objects.filter(username="invalid-password").exists()
