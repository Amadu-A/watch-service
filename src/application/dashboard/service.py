# src/application/dashboard/service.py
"""Application-операции dashboard, weekly schedule и ограниченной retention policy."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from application.cameras.ports import CameraRepository
from application.dashboard.ports import MonitoringRepository
from application.ports import Audit, UnitOfWork
from domain.common import Actor, BusinessError
from domain.surveillance.schedule import validate_schedule


class MonitoringService:
    """Проверяет layout, права изменения расписания и потолок хранения 30 дней."""

    def __init__(
        self,
        repository: MonitoringRepository,
        cameras: CameraRepository,
        uow: UnitOfWork,
        audit: Audit,
        max_cameras: int,
        retention_limit: int,
    ):
        """Получает конфигурационные ограничения и persistence ports извне."""
        self.repository, self.cameras, self.uow, self.audit = repository, cameras, uow, audit
        self.max_cameras, self.retention_limit = max_cameras, retention_limit

    def layout(self, actor: Actor, data: dict | None = None) -> dict:
        """Сохраняет уникальные зарегистрированные IDs в пользовательском порядке."""
        if data is None:
            return self.repository.layout(actor.id)
        ids = [str(value) for value in data["camera_ids"]]
        if len(ids) != len(set(ids)) or len(ids) > self.max_cameras:
            raise BusinessError("invalid_layout", f"Выберите до {self.max_cameras} разных камер.")
        known = {item["id"] for item in self.cameras.list()}
        if not set(ids) <= known:
            raise BusinessError("camera_not_found", "В раскладке есть неизвестная камера.", 404)
        if data.get("grid", "auto") not in ("auto", "1", "2", "3", "4"):
            raise BusinessError("invalid_grid", "Неизвестная плотность сетки.")
        return self.repository.layout(
            actor.id, {"camera_ids": ids, "grid": data.get("grid", "auto")}
        )

    def schedule(self, actor: Actor, data: dict | None = None) -> dict:
        """Читает либо атомарно заменяет weekly schedule после проверки domain rules."""
        if data is None:
            return self.repository.schedule()
        actor.require("ADMINISTRATOR")
        values = validate_schedule(data)
        with self.uow.transaction():
            result = self.repository.schedule(values)
            self.audit.record(actor.id, "schedule_update")
        return result

    def timezones(self, actor: Actor) -> list[str]:
        """Возвращает поддерживаемые IANA identifiers для UI."""
        return sorted(available_timezones())

    def settings(self, actor: Actor, data: dict | None = None) -> dict:
        """Запрещает изменять deployment secrets и увеличивать retention сверх лимита."""
        if data is None:
            return {
                **self.repository.settings(),
                "retention_limit": self.retention_limit,
                "max_visible_cameras": self.max_cameras,
            }
        actor.require("ADMINISTRATOR")
        if not set(data) <= {"default_timezone", "media_retention_days", "default_confidence"}:
            raise BusinessError("forbidden_setting", "Настройка недоступна через API.")
        if (
            "media_retention_days" in data
            and not 1 <= data["media_retention_days"] <= self.retention_limit
        ):
            raise BusinessError(
                "retention_limit", f"Хранение допускается до {self.retention_limit} дней."
            )
        if "default_confidence" in data and not 0 <= data["default_confidence"] <= 1:
            raise BusinessError("invalid_confidence", "Confidence должен быть от 0 до 1.")
        try:
            if "default_timezone" in data:
                ZoneInfo(data["default_timezone"])
        except ZoneInfoNotFoundError:
            raise BusinessError("invalid_timezone", "Неизвестный часовой пояс.") from None
        with self.uow.transaction():
            result = self.repository.settings(data)
            self.audit.record(actor.id, "system_settings_update")
        return result
