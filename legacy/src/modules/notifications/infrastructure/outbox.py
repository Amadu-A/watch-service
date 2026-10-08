# src/modules/notifications/infrastructure/outbox.py
"""Публикация durable outbox в shared RabbitMQ и восстановление bounded retry."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from modules.persistence.models import NotificationDelivery, NotificationOutbox


class CeleryOutboxPublisher:
    """Передаёт только UUID; непубликуемое поручение остаётся в project БД."""

    def __init__(self, task):
        """Получает уже настроенную Celery task из composition root."""
        self.task = task

    def pump(self) -> int:
        """Публикует до 100 записей; broker failure оставляет outbox для следующего цикла."""
        now = timezone.now()
        NotificationDelivery.objects.filter(status="FAILED", next_attempt_at__lte=now).update(
            status="RETRYING"
        )
        # Если consumer потерял задание, безопасно повторяем UUID после пяти минут.
        NotificationOutbox.objects.filter(
            published_at__lt=now - timedelta(minutes=5), delivery__status__in=["QUEUED", "RETRYING"]
        ).update(published_at=None)
        NotificationOutbox.objects.filter(delivery__status="RETRYING").update(published_at=None)
        count = 0
        for outbox_id in NotificationOutbox.objects.filter(
            published_at=None, delivery__status__in=["PENDING", "RETRYING", "QUEUED"]
        ).values_list("id", flat=True)[:100]:
            with transaction.atomic():
                row = (
                    NotificationOutbox.objects.select_for_update()
                    .select_related("delivery")
                    .get(pk=outbox_id)
                )
                if row.published_at is not None or row.delivery.status not in (
                    "PENDING",
                    "RETRYING",
                    "QUEUED",
                ):
                    continue
                self.task.apply_async(
                    args=[str(row.delivery_id)], queue="warehouse.notifications", retry=False
                )
                row.published_at = now
                row.save(update_fields=["published_at"])
                row.delivery.status = "QUEUED"
                row.delivery.save(update_fields=["status"])
                count += 1
        return count
