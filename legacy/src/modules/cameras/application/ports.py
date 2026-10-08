# src/modules/cameras/application/ports.py
"""Контракт persistence камер; выдаёт DTO вместо моделей Django."""

from typing import Protocol


class CameraRepository(Protocol):
    """Хранит камеры и линии; encrypted credentials доступны только worker-композиции."""

    def list(self) -> list[dict]:
        """Возвращает несекретный список зарегистрированных камер."""
        ...

    def get(self, camera_id) -> dict:
        """Получает камеру или выбрасывает предметный not found."""
        ...

    def save(self, camera_id, data: dict, encrypted: str | None) -> dict:
        """Создаёт/обновляет конфигурацию и необязательный ciphertext."""
        ...

    def line(self, camera_id, data: dict | None = None) -> dict | None:
        """Читает или заменяет line configuration."""
        ...

    def connection(self, camera_id) -> str:
        """Возвращает ciphertext для доверенного RTSP worker."""
        ...

    def status(self, camera_id, status: str) -> None:
        """Записывает статус и время последнего успешного кадра."""
        ...
