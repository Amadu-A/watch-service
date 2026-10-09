# src/application/surveillance/capture.py
"""Публикация кадров для просмотра независимо от доступности распознавания."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from application.ports import LiveFrameCache
from application.surveillance.ports import FrameRenderer


@dataclass(frozen=True)
class CapturedFrame:
    """Свежий JPEG с идентификатором сессии декодера и порядком кадров."""

    jpeg: bytes
    captured_at: datetime
    session_id: str
    sequence: int


class CapturedFrameStore(Protocol):
    """Передаёт последний исходный кадр из CPU-захвата в отдельный inference-процесс."""

    def get(self, camera_id: str) -> CapturedFrame | None:
        """Возвращает только доступный кадр с конечным сроком хранения."""
        ...

    def put(self, camera_id: str, frame: CapturedFrame) -> None:
        """Заменяет кадр без накопления очереди при медленном inference."""
        ...

    def delete(self, camera_id: str) -> None:
        """Удаляет кадр отключённой или изменённой камеры."""
        ...


class PublishCameraFrame:
    """Показывает камеру без detector, tracker, RabbitMQ и внешнего inference."""

    def __init__(
        self,
        camera: dict,
        line: dict | None,
        renderer: FrameRenderer,
        cache: LiveFrameCache,
        captured: CapturedFrameStore,
        timezone: str,
    ):
        """Получает порты публикации и настройки подписи из composition root."""
        self.camera, self.line, self.renderer = camera, line, renderer
        self.cache, self.captured, self.timezone = cache, captured, ZoneInfo(timezone)
        self.sequence = 0

    def process(self, frame, timestamp: datetime, session_id: str) -> None:
        """Сначала публикует live JPEG, затем исходный кадр для необязательного inference."""
        label = f"{self.camera['name']} | {timestamp.astimezone(self.timezone).isoformat()}"
        jpeg = self.renderer.annotated(frame, [], self.line, label)
        self.cache.put(self.camera["id"], jpeg)
        self.sequence += 1
        self.captured.put(
            self.camera["id"],
            CapturedFrame(self.renderer.original(frame), timestamp, session_id, self.sequence),
        )
