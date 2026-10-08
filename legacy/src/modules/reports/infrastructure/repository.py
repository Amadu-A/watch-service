# src/modules/reports/infrastructure/repository.py
"""ORM-история персональных отчётов, закрытая от доступа по чужому UUID."""

from core.domain import BusinessError
from modules.persistence.models import GeneratedReport


def report_dto(obj) -> dict:
    """Возвращает metadata и защищённый download URL."""
    return {
        "id": str(obj.id),
        "format": obj.format,
        "filters": obj.filters,
        "path": obj.path,
        "status": obj.status,
        "created_at": obj.created_at.isoformat(),
        "download_url": f"/api/v1/reports/{obj.id}/download",
    }


class DjangoReportRepository:
    """Проверяет user_id непосредственно в data-access query."""

    def create(self, user_id, report_id: str, data: dict) -> dict:
        """Сохраняет metadata только после успешного создания report bytes."""
        return report_dto(GeneratedReport.objects.create(pk=report_id, user_id=user_id, **data))

    def list(self, user_id) -> list[dict]:
        """Возвращает 100 последних файлов текущего пользователя."""
        return [
            report_dto(obj)
            for obj in GeneratedReport.objects.filter(user_id=user_id).order_by("-created_at")[:100]
        ]

    def get(self, user_id, report_id) -> dict:
        """Одинаково отвечает not found для чужого и отсутствующего отчёта."""
        obj = GeneratedReport.objects.filter(user_id=user_id, pk=report_id).first()
        if not obj:
            raise BusinessError("report_not_found", "Отчёт не найден.", 404)
        return report_dto(obj)
