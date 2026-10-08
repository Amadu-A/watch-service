# src/modules/notifications/infrastructure/repository.py
"""ORM delivery/outbox адаптер; locks защищают от повторных concurrent заданий."""

from contextlib import contextmanager
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.domain import BusinessError
from modules.persistence.models import (
    NotificationDelivery,
    NotificationDeliveryAttempt,
    NotificationOutbox,
    NotificationRecipient,
    NotificationSettings,
)
from modules.violations.infrastructure.repository import delivery_dto


def recipient_dto(obj) -> dict:
    """Возвращает настройки адресата без токенов каналов."""
    return {
        "id": str(obj.id),
        "channel": obj.channel,
        "target": obj.target,
        "display_name": obj.display_name,
        "enabled": obj.enabled,
    }


class DjangoNotificationRepository:
    """Хранит состояния, attempts и durable поручения в project PostgreSQL."""

    def settings(self, data: dict | None = None) -> dict:
        """Создаёт безопасные выключенные business defaults при первом чтении."""
        obj, _ = NotificationSettings.objects.get_or_create(pk=1)
        if data is not None:
            for key, value in data.items():
                setattr(obj, key, value)
            obj.save()
        return {
            key: getattr(obj, key)
            for key in ("global_enabled", "email_enabled", "telegram_enabled")
        }

    def recipients(self) -> list[dict]:
        """Выдаёт адресатов в порядке создания."""
        return [recipient_dto(obj) for obj in NotificationRecipient.objects.order_by("created_at")]

    def recipient(self, recipient_id, data: dict | None = None, delete: bool = False) -> dict:
        """Обрабатывает duplicate target внутри savepoint без поломки внешней транзакции."""
        obj = (
            NotificationRecipient.objects.filter(pk=recipient_id).first()
            if recipient_id
            else NotificationRecipient()
        )
        if obj is None:
            raise BusinessError("recipient_not_found", "Получатель не найден.", 404)
        if delete:
            result = recipient_dto(obj)
            obj.delete()
            return result
        for key, value in data.items():
            setattr(obj, key, value)
        try:
            with transaction.atomic():
                obj.save()
        except IntegrityError:
            raise BusinessError(
                "duplicate_recipient", "Получатель уже зарегистрирован.", 409
            ) from None
        return recipient_dto(obj)

    def prepare(self, event_id, enabled_channels: set[str]) -> list[str]:
        """Фиксирует отдельный delivery для каждого включённого адресата."""
        ids = []
        for recipient in NotificationRecipient.objects.filter(enabled=True):
            enabled = recipient.channel in enabled_channels
            if event_id is None and not enabled:
                continue
            obj = NotificationDelivery.objects.create(
                violation_id=event_id,
                recipient=recipient,
                channel=recipient.channel,
                target=recipient.target,
                status="PENDING" if enabled else "SKIPPED_DISABLED",
            )
            if enabled:
                NotificationOutbox.objects.create(delivery=obj)
                ids.append(str(obj.id))
        return ids

    def delivery(self, delivery_id) -> dict:
        """Выдаёт current state и хронологические attempts одним prefetched запросом."""
        obj = (
            NotificationDelivery.objects.prefetch_related("attempts").filter(pk=delivery_id).first()
        )
        if not obj:
            raise BusinessError("delivery_not_found", "Отправка не найдена.", 404)
        return {
            **delivery_dto(obj),
            "attempts": [
                {
                    "status": item.status,
                    "error_code": item.error_code,
                    "created_at": item.created_at.isoformat(),
                }
                for item in obj.attempts.all()
            ],
        }

    def deliveries(self, filters: dict) -> tuple[list[dict], int]:
        """Пагинирует и фильтрует без динамических ORM lookup из пользовательских ключей."""
        query = NotificationDelivery.objects.order_by("-created_at")
        for key in ("violation_id", "recipient_id", "channel", "status"):
            if filters.get(key):
                query = query.filter(**{key: filters[key]})
        if filters.get("date_from"):
            query = query.filter(created_at__gte=filters["date_from"])
        if filters.get("date_to"):
            query = query.filter(created_at__lt=filters["date_to"])
        total = query.count()
        size, page = filters.get("page_size", 50), filters.get("page", 1)
        return [delivery_dto(obj) for obj in query[(page - 1) * size : page * size]], total

    def retry(self, delivery_id) -> None:
        """Повторно открывает outbox только для terminal failed состояния."""
        obj = NotificationDelivery.objects.select_for_update().get(pk=delivery_id)
        if obj.status not in ("FAILED", "DEAD", "SKIPPED_DISABLED"):
            raise BusinessError(
                "invalid_delivery_state", "Повторная отправка сейчас недоступна.", 409
            )
        obj.status, obj.next_attempt_at = "PENDING", None
        # Ручной retry открывает новый bounded цикл; полная история attempts сохраняется.
        obj.attempt_count = 0
        obj.save()
        NotificationOutbox.objects.update_or_create(delivery=obj, defaults={"published_at": None})

    @contextmanager
    def lock(self, delivery_id):
        """Удерживает row lock до сохранения исхода внешнего вызова."""
        with transaction.atomic():
            obj = NotificationDelivery.objects.select_for_update().filter(pk=delivery_id).first()
            if obj is None:
                raise BusinessError("delivery_not_found", "Отправка не найдена.", 404)
            yield

    def finish(
        self, delivery_id, status: str, error_code: str = "", retry_seconds: int = 0
    ) -> None:
        """Записывает attempt и назначает время следующего bounded retry."""
        obj = NotificationDelivery.objects.get(pk=delivery_id)
        obj.status, obj.last_error_code = status, error_code
        obj.attempt_count += 1
        obj.next_attempt_at = (
            timezone.now() + timedelta(seconds=retry_seconds) if retry_seconds else None
        )
        if status == "SENT":
            obj.sent_at = timezone.now()
        obj.save()
        NotificationDeliveryAttempt.objects.create(
            delivery=obj, status=status, error_code=error_code
        )
