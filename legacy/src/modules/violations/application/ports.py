# src/modules/violations/application/ports.py
"""Порт неизменяемых событий и их защищённых медиа."""

from typing import Protocol


class ViolationRepository(Protocol):
    """Изолирует историю и дедупликацию от деталей ORM."""

    def exists(self, event_key: str) -> dict | None:
        """Получает ранее зафиксированное событие при повторной обработке."""
        ...

    def create(self, event: dict, paths: dict) -> dict:
        """Создаёт событие и media metadata в текущей транзакции."""
        ...

    def get(self, event_id) -> dict:
        """Возвращает evidence metadata и историю доставок."""
        ...

    def list(self, filters: dict) -> tuple[list[dict], int]:
        """Фильтрует и пагинирует историю в обратном порядке времени."""
        ...

    def statistics(self, filters: dict) -> dict:
        """Подсчитывает нарушения и состояния доставки за один период."""
        ...
