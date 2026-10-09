# src/application/reports/ports.py
"""Контракты renderer и хранения метаданных готовых отчётов."""

from typing import Protocol


class ReportRenderer(Protocol):
    """Формирует PDF/CSV по DTO, не читая ORM и filesystem самостоятельно."""

    def pdf(self, events: list[dict]) -> bytes:
        """Строит русскоязычный отчёт с annotated evidence."""
        ...

    def csv(self, events: list[dict]) -> bytes:
        """Формирует UTF-8 CSV с защитой от spreadsheet formula injection."""
        ...


class ReportRepository(Protocol):
    """Сохраняет историю файлов и ограничивает доступ владельцем."""

    def create(self, user_id, report_id: str, data: dict) -> dict:
        """Записывает metadata отчёта после успешной записи файла."""
        ...

    def list(self, user_id) -> list[dict]:
        """Возвращает последние отчёты пользователя."""
        ...

    def get(self, user_id, report_id) -> dict:
        """Проверяет принадлежность файла текущему пользователю."""
        ...
