# src/modules/reports/application/service.py
"""Генерация ограниченного по объёму отчёта, защищённая история и download."""

from uuid import uuid4

from core.domain import Actor, BusinessError
from core.ports import MediaStorage
from core.timing import timed
from modules.reports.application.ports import ReportRenderer, ReportRepository
from modules.violations.application.ports import ViolationRepository


class ReportService:
    """Координирует renderer, event repository и media storage без framework зависимости."""

    def __init__(
        self,
        events: ViolationRepository,
        repository: ReportRepository,
        storage: MediaStorage,
        renderer: ReportRenderer,
    ):
        """Получает независимые application ports composition root."""
        self.events, self.repository, self.storage, self.renderer = (
            events,
            repository,
            storage,
            renderer,
        )

    @timed("generate_report")
    def single(self, actor: Actor, event_id) -> bytes:
        """Создаёт PDF одного события с фото и status summary синхронно."""
        return self.renderer.pdf([self.events.get(event_id)])

    @timed("generate_period_report")
    def create(self, actor: Actor, data: dict) -> dict:
        """Создаёт PDF/CSV до 2000 событий; для большего объёма просит сузить период."""
        filters = {**data.get("filters", {}), "page": 1, "page_size": 2000}
        events, total = self.events.list(filters)
        if total > 2000:
            raise BusinessError("report_too_large", "Сузьте период до 2000 событий.", 422)
        content = (
            self.renderer.pdf(events) if data["format"] == "PDF" else self.renderer.csv(events)
        )
        report_id = str(uuid4())
        path = f"reports/{actor.id}/{report_id}.{data['format'].lower()}"
        self.storage.write(path, content)
        try:
            return self.repository.create(
                actor.id,
                report_id,
                {"format": data["format"], "filters": data.get("filters", {}), "path": path},
            )
        except Exception:
            self.storage.delete(path)
            raise

    def list(self, actor: Actor) -> list[dict]:
        """Выдаёт только файлы, ранее сформированные текущим пользователем."""
        return self.repository.list(actor.id)

    def get(self, actor: Actor, report_id) -> dict:
        """Открывает metadata только принадлежащего пользователю отчёта."""
        return self.repository.get(actor.id, report_id)

    def download(self, actor: Actor, report_id) -> tuple[bytes, str]:
        """Проверяет владельца до чтения bytes файла."""
        report = self.repository.get(actor.id, report_id)
        return self.storage.read(report["path"]), report["format"]
