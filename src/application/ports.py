# src/application/ports.py
"""Общие application-порты; конкретные DB, crypto и storage адаптеры внедряются извне."""

from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol


class UnitOfWork(Protocol):
    """Определяет атомарную границу операции; исключение откатывает изменения."""

    def transaction(self) -> AbstractContextManager:
        """Возвращает контекст одной бизнес-транзакции."""
        ...


class Audit(Protocol):
    """Записывает только тип операции и identity, исключая секретные payload."""

    def record(self, actor_id, operation: str, object_id: str = "") -> None:
        """Добавляет событие аудита в текущую транзакцию."""
        ...


class CredentialCipher(Protocol):
    """Шифрует connection details перед сохранением в БД."""

    def encrypt(self, data: dict) -> str:
        """Возвращает аутентифицированный ciphertext."""
        ...

    def decrypt(self, ciphertext: str) -> dict:
        """Расшифровывает данные только для RTSP-адаптера."""
        ...


class MediaStorage(Protocol):
    """Изолирует application от локальных абсолютных путей."""

    def write(self, path: str, content: bytes) -> None:
        """Атомарно сохраняет evidence в пространстве проекта."""
        ...

    def read(self, path: str) -> bytes:
        """Возвращает защищённый файл после application permission check."""
        ...

    def delete(self, path: str) -> None:
        """Идемпотентно удаляет один файл в рамках retention."""
        ...

    def expire_orphans(self, cutoff: datetime, referenced: set[str]) -> int:
        """Удаляет просроченные файлы, не связанные с business metadata."""
        ...


class LiveFrameCache(Protocol):
    """Хранит последний JPEG, который можно потерять без потери business state."""

    def get(self, camera_id: str) -> bytes | None:
        """Возвращает кадр или None после TTL."""
        ...

    def put(self, camera_id: str, jpeg: bytes) -> None:
        """Обновляет latest frame с конечным TTL."""
        ...
