# src/application/dashboard/ports.py
"""Порты персональной раскладки, расписания и несекретных настроек объекта."""

from typing import Protocol


class MonitoringRepository(Protocol):
    """Хранит layout и weekly schedule без зависимости application от ORM."""

    def layout(self, user_id, data: dict | None = None) -> dict:
        """Читает или полностью заменяет персональную раскладку."""
        ...

    def schedule(self, data: dict | None = None) -> dict:
        """Читает или заменяет расписание и его интервалы."""
        ...

    def settings(self, data: dict | None = None) -> dict:
        """Выдаёт/обновляет только разрешённые несекретные business settings."""
        ...
