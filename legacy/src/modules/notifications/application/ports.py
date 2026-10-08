# src/modules/notifications/application/ports.py
"""Порты durable доставок, брокера и внешнего канала уведомлений."""

from typing import Protocol


class NotificationRepository(Protocol):
    """Хранит settings, recipients, outbox и попытки доставки."""

    def settings(self, data: dict | None = None) -> dict:
        """Читает/изменяет бизнес-переключатели уведомлений."""
        ...

    def recipients(self) -> list[dict]:
        """Возвращает зарегистрированные адресаты обоих каналов."""
        ...

    def recipient(self, recipient_id, data: dict | None = None, delete: bool = False) -> dict:
        """Создаёт, изменяет либо удаляет одного адресата."""
        ...

    def prepare(self, event_id, enabled_channels: set[str]) -> list[str]:
        """Создаёт delivery/outbox или SKIPPED_DISABLED для отключённых каналов."""
        ...

    def delivery(self, delivery_id) -> dict:
        """Получает детали доставки и историю попыток."""
        ...

    def deliveries(self, filters: dict) -> tuple[list[dict], int]:
        """Фильтрует историю для UI."""
        ...

    def retry(self, delivery_id) -> None:
        """Переводит failed delivery в PENDING и повторно открывает outbox."""
        ...

    def lock(self, delivery_id):
        """Возвращает context с row lock для защиты от двойной доставки."""
        ...

    def finish(
        self, delivery_id, status: str, error_code: str = "", retry_seconds: int = 0
    ) -> None:
        """Записывает исход и отдельную attempt запись атомарно."""
        ...


class NotificationSender(Protocol):
    """Отправляет текст, annotated photo и PDF через один внешний канал."""

    def send(self, target: str, message: str, photo: bytes | None, report: bytes | None) -> None:
        """Выбрасывает безопасную предметную ошибку при сетевом отказе."""
        ...
