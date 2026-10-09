# src/infrastructure/messaging/senders.py
"""SMTP и Telegram adapters с конечными timeout; секреты не попадают в error messages."""

import smtplib
import ssl
from email.message import EmailMessage

import httpx

from core.timing import timed


class SMTPEmailSender:
    """Отправляет annotated JPEG и PDF письмом без хранения payload в БД."""

    def __init__(self, config):
        """Получает runtime SMTP конфигурацию с SecretStr password."""
        self.config = config

    @timed("send_email_notification")
    def send(self, target: str, message: str, photo: bytes | None, report: bytes | None) -> None:
        """Передаёт письмо SMTP; вызов разрешён только DispatchNotification hard gate."""
        mail = EmailMessage()
        mail["Subject"] = "Склад: уведомление видеоконтроля"
        mail["From"], mail["To"] = self.config.smtp_from_address, target
        mail.set_content(message)
        if photo:
            mail.add_attachment(photo, maintype="image", subtype="jpeg", filename="annotated.jpg")
        if report:
            mail.add_attachment(
                report, maintype="application", subtype="pdf", filename="report.pdf"
            )
        with smtplib.SMTP(
            self.config.smtp_host,
            self.config.smtp_port,
            timeout=self.config.notification_timeout_seconds,
        ) as server:
            if self.config.smtp_use_tls:
                server.starttls(context=ssl.create_default_context())
            if self.config.smtp_username:
                server.login(
                    self.config.smtp_username, self.config.smtp_password.get_secret_value()
                )
            server.send_message(mail)


class TelegramBotSender:
    """Отправляет фото и документ через Bot API; target — chat_id либо channel username."""

    def __init__(self, token: str, timeout: int):
        """Сохраняет токен приватно, без вывода URL с токеном в логи."""
        self._token, self.timeout = token, timeout

    @timed("send_telegram_notification")
    def send(self, target: str, message: str, photo: bytes | None, report: bytes | None) -> None:
        """Вызывает Bot API с конечным timeout и проверкой application-level ok."""
        with httpx.Client(timeout=self.timeout) as client:
            if photo:
                self._post(
                    client,
                    "sendPhoto",
                    {"chat_id": target, "caption": message[:1024]},
                    {"photo": ("annotated.jpg", photo, "image/jpeg")},
                )
            else:
                self._post(client, "sendMessage", {"chat_id": target, "text": message})
            if report:
                self._post(
                    client,
                    "sendDocument",
                    {"chat_id": target},
                    {"document": ("report.pdf", report, "application/pdf")},
                )

    def _post(self, client, method: str, data: dict, files: dict | None = None) -> None:
        """Не сохраняет response body, который может содержать чувствительные данные."""
        response = client.post(
            f"https://api.telegram.org/bot{self._token}/{method}", data=data, files=files
        )
        response.raise_for_status()
        if not response.json().get("ok"):
            raise RuntimeError("telegram_send_failed")
