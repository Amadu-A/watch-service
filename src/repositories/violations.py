# src/repositories/violations.py
"""ORM-адаптер нарушений с предзагрузкой media/deliveries и параметризованными фильтрами."""

from django.db.models import Count, Q

from domain.common import BusinessError
from persistence_app.models import NotificationDelivery, Violation, ViolationMedia


def delivery_dto(obj) -> dict:
    """Преобразует delivery в безопасное представление без adapter payload."""
    return {
        "id": str(obj.id),
        "violation_id": str(obj.violation_id) if obj.violation_id else None,
        "recipient_id": str(obj.recipient_id) if obj.recipient_id else None,
        "channel": obj.channel,
        "target": obj.target,
        "status": obj.status,
        "attempt_count": obj.attempt_count,
        "last_error_code": obj.last_error_code,
        "created_at": obj.created_at.isoformat(),
        "sent_at": obj.sent_at.isoformat() if obj.sent_at else None,
    }


def event_dto(obj: Violation) -> dict:
    """Возвращает неизменяемый camera snapshot и URLs защищённых evidence endpoints."""
    paths = {item.kind: item.path for item in obj.media.all()}
    return {
        "id": str(obj.id),
        "camera": {"id": str(obj.camera_id), **obj.camera_snapshot},
        "detected_at": obj.detected_at.isoformat(),
        "direction": obj.direction,
        "confidence": obj.confidence,
        "track_id": obj.track_id,
        "bbox": obj.bbox,
        "crossing_point": obj.crossing_point,
        "line": obj.line_snapshot,
        "media_paths": paths,
        "media": {
            f"{kind}_url": f"/api/v1/violations/{obj.id}/media/{kind}" if kind in paths else None
            for kind in ("original", "annotated", "clip")
        },
        "deliveries": [delivery_dto(item) for item in obj.deliveries.all()],
    }


def filter_events(query, filters: dict):
    """Применяет allow-list ORM filters; arbitrary lookup из HTTP не принимается."""
    for key in ("camera_id", "direction"):
        if filters.get(key):
            query = query.filter(**{key: filters[key]})
    if filters.get("camera_ids"):
        query = query.filter(camera_id__in=filters["camera_ids"])
    if filters.get("date_from"):
        query = query.filter(detected_at__gte=filters["date_from"])
    if filters.get("date_to"):
        query = query.filter(detected_at__lt=filters["date_to"])
    if filters.get("notification_status"):
        query = query.filter(deliveries__status=filters["notification_status"]).distinct()
    return query


class DjangoViolationRepository:
    """Хранит business history в БД независимо от Redis frame cache."""

    def _query(self):
        """Предзагружает обратные связи, исключая N+1 при отображении таблицы."""
        return Violation.objects.prefetch_related("media", "deliveries")

    def exists(self, event_key: str) -> dict | None:
        """Проверяет устойчивый idempotency key worker session/track/crossing."""
        event = self._query().filter(event_key=event_key).first()
        return event_dto(event) if event else None

    def create(self, event: dict, paths: dict) -> dict:
        """Создаёт metadata для уже записанных evidence файлов."""
        obj = Violation.objects.create(**event)
        ViolationMedia.objects.bulk_create(
            [ViolationMedia(violation=obj, kind=kind, path=path) for kind, path in paths.items()]
        )
        return self.get(obj.id)

    def get(self, event_id) -> dict:
        """Преобразует not found в стабильный API-совместимый domain error."""
        try:
            return event_dto(self._query().get(pk=event_id))
        except Violation.DoesNotExist:
            raise BusinessError("violation_not_found", "Нарушение не найдено.", 404) from None

    def list(self, filters: dict) -> tuple[list[dict], int]:
        """Получает только requested page после применения filters."""
        query = filter_events(self._query(), filters).order_by("-detected_at", "-id")
        total = query.count()
        start = (filters.get("page", 1) - 1) * filters.get("page_size", 50)
        return [
            event_dto(event) for event in query[start : start + filters.get("page_size", 50)]
        ], total

    def statistics(self, filters: dict) -> dict:
        """Считает статус каждого адресата без повторного учёта attempts."""
        events = filter_events(Violation.objects.all(), filters)
        result = NotificationDelivery.objects.filter(violation__in=events).aggregate(
            email_sent=Count("id", filter=Q(channel="EMAIL", status="SENT")),
            telegram_sent=Count("id", filter=Q(channel="TELEGRAM", status="SENT")),
            delivery_errors=Count("id", filter=Q(status__in=["FAILED", "DEAD"])),
        )
        return {"violations": events.count(), **result}
