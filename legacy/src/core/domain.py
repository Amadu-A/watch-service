# src/core/domain.py
"""Общие предметные ошибки и контекст доступа, независимые от HTTP и ORM."""

from dataclasses import dataclass
from uuid import UUID


class BusinessError(Exception):
    """Представляет ожидаемый отказ операции с безопасным кодом и сообщением."""

    def __init__(self, code: str, message: str, status: int = 400):
        """Сохраняет предметную причину для преобразования транспортом."""
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class Actor:
    """Передаёт identity и роль без объекта Django User в application."""

    id: UUID
    role: str

    def require(self, *roles: str) -> None:
        """Отклоняет изменение, недоступное роли текущего пользователя."""
        if self.role not in roles and self.role != "ADMINISTRATOR":
            raise BusinessError("permission_denied", "Недостаточно прав для операции.", 403)
