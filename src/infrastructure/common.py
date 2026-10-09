# src/infrastructure/common.py
"""Адаптеры транзакций, аудита, шифрования и защищённого project storage."""

import json
import os
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from django.db import transaction
from redis import Redis

from domain.common import BusinessError
from persistence_app.models import AuditEvent


class DjangoUnitOfWork:
    """Предоставляет atomic context; исключение откатывает запись события и outbox."""

    def transaction(self):
        """Открывает транзакцию по границе application-операции."""
        return transaction.atomic()


class DjangoAudit:
    """Хранит минимальный аудит без пользовательского payload."""

    def record(self, actor_id, operation: str, object_id: str = "") -> None:
        """Добавляет identity и название операции в текущую транзакцию."""
        AuditEvent.objects.create(actor_id=actor_id, operation=operation, object_id=object_id)


class FernetCredentialCipher:
    """Аутентифицированное шифрование credentials ключом из private environment."""

    def __init__(self, key: str):
        """Отклоняет отсутствующий или некорректный ключ без вывода его значения."""
        try:
            self.fernet = Fernet(key.encode())
        except (ValueError, TypeError):
            raise BusinessError(
                "encryption_unconfigured", "Задайте CAMERA_CREDENTIALS_KEY.", 503
            ) from None

    def encrypt(self, data: dict) -> str:
        """Шифрует JSON вместе с URL, query string, логином и паролем."""
        return self.fernet.encrypt(json.dumps(data).encode()).decode()

    def decrypt(self, ciphertext: str) -> dict:
        """Проверяет подпись и скрывает внутренний текст ошибки расшифровки."""
        try:
            return json.loads(self.fernet.decrypt(ciphertext.encode()))
        except InvalidToken:
            raise BusinessError(
                "credentials_unreadable", "Не удалось расшифровать подключение.", 503
            ) from None


class LocalMediaStorage:
    """Атомарное файловое хранилище, закрытое от path traversal и static server."""

    def __init__(self, root: Path):
        """Закрепляет абсолютный корень project-owned volume."""
        self.root = root.resolve()

    def _path(self, path: str) -> Path:
        """Проверяет нахождение конечного пути строго внутри media root."""
        result = (self.root / path).resolve()
        if not result.is_relative_to(self.root) or result == self.root:
            raise BusinessError("invalid_media_path", "Недопустимый путь файла.")
        return result

    def write(self, path: str, content: bytes) -> None:
        """Записывает временный файл и атомарно заменяет конечный evidence."""
        target = self._path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f".{uuid4()}.tmp")
        try:
            temp.write_bytes(content)
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)

    def read(self, path: str) -> bytes:
        """Выдаёт bytes или предметный not found без раскрытия абсолютного пути."""
        try:
            return self._path(path).read_bytes()
        except FileNotFoundError:
            raise BusinessError("media_not_found", "Файл не найден.", 404) from None

    def delete(self, path: str) -> None:
        """Удаляет только проверенный файл; повторное удаление безопасно."""
        self._path(path).unlink(missing_ok=True)

    def expire_orphans(self, cutoff: datetime, referenced: set[str]) -> int:
        """Удаляет старые файлы без DB-ссылок и пустые каталоги только внутри media root."""
        count = 0
        if not self.root.exists():
            return count
        for path in self.root.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(self.root).as_posix()
            checked = self._path(relative)
            if relative not in referenced and checked.stat().st_mtime < cutoff.timestamp():
                checked.unlink(missing_ok=True)
                count += 1
        directories = sorted(
            (path for path in self.root.rglob("*") if path.is_dir() and not path.is_symlink()),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for directory in directories:
            self._path(directory.relative_to(self.root).as_posix())
            with suppress(OSError):
                directory.rmdir()
        return count


class RedisLiveFrameCache:
    """TTL cache последних JPEG; source of truth событий остаётся PostgreSQL."""

    def __init__(self, client: Redis, ttl: int):
        """Получает уже созданный клиент Redis и срок жизни кадра."""
        self.client, self.ttl = client, ttl

    def get(self, camera_id: str) -> bytes | None:
        """Не возвращает устаревшие кадры после истечения TTL."""
        return self.client.get(f"warehouse:frame:{camera_id}")

    def put(self, camera_id: str, jpeg: bytes) -> None:
        """Атомарно заменяет JPEG и обновляет ограниченный TTL."""
        self.client.setex(f"warehouse:frame:{camera_id}", self.ttl, jpeg)
