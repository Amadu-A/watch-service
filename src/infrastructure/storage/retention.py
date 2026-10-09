# src/infrastructure/storage/retention.py
"""Ограниченная очистка evidence, reports, attempts, audit и истёкших sessions."""

from datetime import timedelta

from django.contrib.sessions.models import Session
from django.utils import timezone

from persistence_app.models import (
    AuditEvent,
    GeneratedReport,
    NotificationDelivery,
    Violation,
    ViolationMedia,
)


class RetentionCleaner:
    """Удаляет файлы до metadata: при отказе storage запись остаётся для следующей попытки."""

    def __init__(self, storage, settings_provider, hard_limit: int):
        """Получает storage и provider текущего business retention, ограниченный deployment."""
        self.storage, self.settings_provider, self.hard_limit = (
            storage,
            settings_provider,
            hard_limit,
        )

    def execute(self) -> dict:
        """Удаляет данные старше разрешённого срока; cascade удаляет deliveries/outbox/attempts."""
        days = min(30, self.hard_limit, self.settings_provider()["media_retention_days"])
        cutoff = timezone.now() - timedelta(days=days)
        count = 0
        for event in Violation.objects.filter(detected_at__lt=cutoff).prefetch_related("media"):
            for item in event.media.all():
                self.storage.delete(item.path)
            event.delete()
            count += 1
        for report in GeneratedReport.objects.filter(created_at__lt=cutoff):
            self.storage.delete(report.path)
            report.delete()
        NotificationDelivery.objects.filter(violation=None, created_at__lt=cutoff).delete()
        AuditEvent.objects.filter(created_at__lt=cutoff).delete()
        Session.objects.filter(expire_date__lt=timezone.now()).delete()
        referenced = set(ViolationMedia.objects.values_list("path", flat=True))
        referenced.update(GeneratedReport.objects.values_list("path", flat=True))
        orphan_count = self.storage.expire_orphans(cutoff, referenced)
        return {"events_deleted": count, "orphans_deleted": orphan_count, "retention_days": days}
