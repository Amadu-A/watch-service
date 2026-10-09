# src/infrastructure/inference.py
"""Клиент внешнего CV-контракта; размещением модели и трекингом владеет shared runtime."""

from datetime import datetime
from typing import Annotated, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from application.surveillance.ports import FrameRenderer

Coordinate = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class PersonTrack(BaseModel):
    """Валидирует нормализованные координаты и устойчивый ID человека одной сессии."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    track_id: int = Field(ge=0)
    confidence: Coordinate
    bbox: tuple[Coordinate, Coordinate, Coordinate, Coordinate]

    @model_validator(mode="after")
    def ordered_box(self) -> "PersonTrack":
        """Отклоняет вырожденные и перевёрнутые прямоугольники."""
        x1, y1, x2, y2 = self.bbox
        if x1 >= x2 or y1 >= y2:
            raise ValueError("invalid_person_bbox")
        return self


class TrackResponse(BaseModel):
    """Связывает результат с отправленными камерой, сессией и номером кадра."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    version: Literal[1]
    camera_id: str
    session_id: str
    sequence: int = Field(ge=1)
    tracks: list[PersonTrack] = Field(max_length=256)


class SharedPersonDetector:
    """Получает готовые person tracks по HTTP без загрузки весов и доступа к GPU."""

    def __init__(
        self,
        client: httpx.Client,
        url: str,
        token: str,
        camera_id: str,
        session_id: str,
        renderer: FrameRenderer,
        timeout: float,
    ):
        """Получает транспорт, явный endpoint и контекст одной камеры извне."""
        self.client, self.url, self.token = client, url, token
        self.camera_id, self.session_id = camera_id, session_id
        self.renderer, self.timeout, self.sequence = renderer, timeout, 0

    def detect(self, frame, timestamp: datetime) -> list[dict]:
        """Проверяет ответ внешнего сервиса, не раскрывая payload, URL или токен в ошибке."""
        self.sequence += 1
        try:
            response = self.client.post(
                self.url,
                headers={"Authorization": f"Bearer {self.token}"} if self.token else {},
                data={
                    "version": "1",
                    "camera_id": self.camera_id,
                    "session_id": self.session_id,
                    "sequence": str(self.sequence),
                    "captured_at": timestamp.isoformat(),
                },
                files={"image": ("frame.jpg", self.renderer.original(frame), "image/jpeg")},
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = TrackResponse.model_validate_json(response.content)
            if (result.camera_id, result.session_id, result.sequence) != (
                self.camera_id,
                self.session_id,
                self.sequence,
            ):
                raise ValueError("inference_context_mismatch")
            tracks = [item.model_dump(mode="json") for item in result.tracks]
            if len({item["track_id"] for item in tracks}) != len(tracks):
                raise ValueError("duplicate_track_id")
            return tracks
        except (httpx.HTTPError, ValueError):
            raise RuntimeError("shared_inference_unavailable_or_invalid") from None


class SharedTrackMapper:
    """Передаёт проверенные shared track IDs в доменную геометрию без локальной модели."""

    def update(self, detections: list[dict], frame) -> list[dict]:
        """Сохраняет ID и нормализованные bbox из camera-local внешней сессии."""
        return detections
