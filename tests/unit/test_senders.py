# tests/unit/test_senders.py
"""Email/Telegram payload и timeout проверяются fake transport без внешних сообщений."""

import smtplib
import ssl
from unittest.mock import Mock

import httpx
import pytest

from core.config import Settings
from infrastructure.messaging.senders import SMTPEmailSender, TelegramBotSender


def test_email_tls_auth_and_evidence_attachments(monkeypatch):
    """SMTP передаёт русское сообщение, JPEG и PDF после TLS с ограниченным timeout."""
    server = Mock()
    context = Mock()
    context.__enter__ = Mock(return_value=server)
    context.__exit__ = Mock(return_value=False)
    constructor = Mock(return_value=context)
    monkeypatch.setattr(smtplib, "SMTP", constructor)
    config = Settings(
        smtp_host="smtp.example.com",
        smtp_username="test-user",
        smtp_password="test-password",
        smtp_from_address="watch@example.com",
    )
    SMTPEmailSender(config).send("a@example.com", "Вход на территорию", b"jpeg", b"%PDF-test")
    constructor.assert_called_once_with("smtp.example.com", 587, timeout=15)
    server.starttls.assert_called_once()
    tls = server.starttls.call_args.kwargs["context"]
    assert tls.verify_mode == ssl.CERT_REQUIRED and tls.check_hostname
    server.login.assert_called_once_with("test-user", "test-password")
    mail = server.send_message.call_args.args[0]
    assert mail["To"] == "a@example.com"
    assert [part.get_filename() for part in mail.iter_attachments()] == [
        "annotated.jpg",
        "report.pdf",
    ]
    assert "Вход на территорию" in mail.get_body(preferencelist=("plain",)).get_content()


def test_telegram_photo_document_and_api_error(monkeypatch):
    """Bot API получает два вложения; application-level отказ становится безопасным кодом."""
    client = Mock()
    client.post.return_value.json.return_value = {"ok": True}
    context = Mock()
    context.__enter__ = Mock(return_value=client)
    context.__exit__ = Mock(return_value=False)
    constructor = Mock(return_value=context)
    monkeypatch.setattr(httpx, "Client", constructor)
    sender = TelegramBotSender("test-token", 9)
    sender.send("123456789", "Нарушение", b"jpeg", b"%PDF-test")
    constructor.assert_called_once_with(timeout=9)
    calls = client.post.call_args_list
    assert calls[0].args[0].endswith("/sendPhoto")
    assert calls[0].kwargs["data"]["caption"] == "Нарушение"
    assert calls[1].args[0].endswith("/sendDocument")
    assert calls[1].kwargs["files"]["document"][1] == b"%PDF-test"
    client.post.return_value.json.return_value = {"ok": False, "description": "private payload"}
    with pytest.raises(RuntimeError, match="^telegram_send_failed$"):
        sender.send("123456789", "Тест", None, None)


def test_telegram_http_failure_is_not_marked_success(monkeypatch):
    """Transport ошибка пробрасывается dispatch для записи FAILED и bounded retry."""
    client = Mock()
    client.post.return_value.raise_for_status.side_effect = httpx.HTTPError("provider error")
    context = Mock()
    context.__enter__ = Mock(return_value=client)
    context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(httpx, "Client", Mock(return_value=context))
    with pytest.raises(httpx.HTTPError):
        TelegramBotSender("test-token", 9).send("123456789", "Тест", None, None)
