# src/infrastructure/capture.py
"""Ограниченный TTL-обмен исходными JPEG между захватом и распознаванием."""

import json
from datetime import datetime

from redis import Redis

from application.surveillance.capture import CapturedFrame


class RedisCapturedFrameStore:
    """Хранит один исходный кадр каждой камеры отдельно от JPEG для браузера."""

    def __init__(self, client: Redis, ttl: int):
        """Использует общий пул Redis и конечный срок жизни кадров."""
        self.client, self.ttl = client, ttl

    def put(self, camera_id: str, frame: CapturedFrame) -> None:
        """Атомарно записывает метаданные и бинарный JPEG без Base64 и очереди."""
        header = json.dumps(
            {
                "captured_at": frame.captured_at.isoformat(),
                "session_id": frame.session_id,
                "sequence": frame.sequence,
            }
        ).encode()
        self.client.setex(f"warehouse:capture:{camera_id}", self.ttl, header + b"\n" + frame.jpeg)

    def get(self, camera_id: str) -> CapturedFrame | None:
        """Разбирает единый пакет; отсутствие ключа означает offline или истёкший TTL."""
        data = self.client.get(f"warehouse:capture:{camera_id}")
        if data is None:
            return None
        header, jpeg = data.split(b"\n", 1)
        meta = json.loads(header)
        return CapturedFrame(
            jpeg,
            datetime.fromisoformat(meta["captured_at"]),
            meta["session_id"],
            meta["sequence"],
        )

    def delete(self, camera_id: str) -> None:
        """Удаляет исходный кадр без затрагивания данных другой камеры."""
        self.client.delete(f"warehouse:capture:{camera_id}")
