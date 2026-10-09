# src/application/surveillance/ports.py
"""Порты realtime обработки: decoder, resident detector, camera-local tracker и annotator."""

from typing import Protocol


class CameraSource(Protocol):
    """Предоставляет кадры RTSP, не раскрывая credentials application logic."""

    def read(self):
        """Возвращает кадр либо None при разрыве/таймауте."""
        ...

    def close(self) -> None:
        """Освобождает decoder без остановки других камер."""
        ...


class PersonDetector(Protocol):
    """Преобразует кадр в detections класса person одной resident моделью."""

    def detect(self, frame):
        """Возвращает detections без создания нового model instance."""
        ...


class ObjectTracker(Protocol):
    """Сохраняет track identity внутри одной камеры."""

    def update(self, detections, frame) -> list[dict]:
        """Возвращает track_id, normalized bbox и confidence каждого человека."""
        ...


class FrameRenderer(Protocol):
    """Формирует original JPEG, annotated JPEG и необязательный event clip."""

    def original(self, frame) -> bytes:
        """Кодирует исходный кадр без внесения разметки."""
        ...

    def annotated(self, frame, tracks: list[dict], line: dict | None, label: str) -> bytes:
        """Рисует bbox, линию, confidence, timestamp и направление."""
        ...

    def clip(self, frames: list, fps: int) -> bytes | None:
        """Кодирует короткий MP4; отказ не блокирует evidence JPEG."""
        ...


class ViolationCreator(Protocol):
    """Принимает готовые доказательства без зависимости пайплайна от persistence."""

    def execute(
        self, event: dict, original: bytes, annotated: bytes, clip: bytes | None = None
    ) -> dict:
        """Атомарно создаёт событие или возвращает существующее по event_key."""
        ...
