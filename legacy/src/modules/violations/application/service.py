# src/modules/violations/application/service.py
"""Создание evidence и outbox с компенсацией storage при ошибке DB."""

from datetime import datetime
from uuid import uuid4

from core.domain import Actor, BusinessError
from core.ports import MediaStorage, UnitOfWork
from core.timing import timed
from modules.violations.application.ports import ViolationRepository


class CreateViolation:
    """Сохраняет original/annotated и событие; отправку выполняет отдельный worker."""

    def __init__(
        self, repository: ViolationRepository, storage: MediaStorage, uow: UnitOfWork, notifications
    ):
        """Принимает persistence, storage и порт подготовки durable доставок."""
        self.repository, self.storage, self.uow, self.notifications = (
            repository,
            storage,
            uow,
            notifications,
        )

    @timed("create_violation")
    def execute(
        self, event: dict, original: bytes, annotated: bytes, clip: bytes | None = None
    ) -> dict:
        """Идемпотентно фиксирует evidence, удаляя новые файлы при неуспехе транзакции."""
        previous = self.repository.exists(event["event_key"])
        if previous:
            return previous
        timestamp = event["detected_at"]
        if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
            raise BusinessError("naive_datetime", "Событие должно содержать дату с часовым поясом.")
        if not original or not annotated:
            raise BusinessError(
                "evidence_required", "Обязательны оригинальный и размеченный кадры."
            )
        event = {**event, "id": str(uuid4())}
        base = f"events/{timestamp:%Y/%m/%d}/{event['id']}"
        contents = {"original": original, "annotated": annotated}
        if clip:
            contents["clip"] = clip
        paths = {kind: f"{base}/{kind}.{'mp4' if kind == 'clip' else 'jpg'}" for kind in contents}
        written = []
        try:
            for kind, content in contents.items():
                self.storage.write(paths[kind], content)
                written.append(paths[kind])
            with self.uow.transaction():
                result = self.repository.create(event, paths)
                self.notifications.prepare(result["id"])
            return result
        except Exception:
            for path in written:
                self.storage.delete(path)
            # Уникальный event_key защищает от concurrent duplicate после предварительного чтения.
            previous = self.repository.exists(event["event_key"])
            if previous:
                return previous
            raise


class ViolationService:
    """Чтение истории и evidence; actor нужен для явной границы доступа."""

    def __init__(self, repository: ViolationRepository, storage: MediaStorage):
        """Получает готовые адаптеры из composition root."""
        self.repository, self.storage = repository, storage

    def get(self, actor: Actor, event_id) -> dict:
        """Открывает подробности события для авторизованного пользователя."""
        return self.repository.get(event_id)

    def list(self, actor: Actor, filters: dict) -> dict:
        """Возвращает одинаковую схему pagination для frontend и API clients."""
        values, total = self.repository.list(filters)
        size, page = filters.get("page_size", 50), filters.get("page", 1)
        return {
            "data": [
                {key: value for key, value in item.items() if key != "media_paths"}
                for item in values
            ],
            "meta": {
                "page": page,
                "page_size": size,
                "total": total,
                "pages": (total + size - 1) // size,
            },
        }

    def media(self, actor: Actor, event_id, kind: str) -> bytes:
        """Выдаёт только известный media kind текущего события."""
        event = self.repository.get(event_id)
        if kind not in event["media_paths"]:
            raise BusinessError("media_not_found", "Файл отсутствует у события.", 404)
        return self.storage.read(event["media_paths"][kind])

    def statistics(self, actor: Actor, filters: dict) -> dict:
        """Показывает фактические counts без синтетических demo values."""
        return self.repository.statistics(filters)
