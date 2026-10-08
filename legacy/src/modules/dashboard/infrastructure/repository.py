# src/modules/dashboard/infrastructure/repository.py
"""ORM-хранение singleton settings и пользовательской раскладки."""

from modules.persistence.models import (
    ControlSchedule,
    ControlScheduleInterval,
    MonitoringLayout,
    SystemSettings,
)
from modules.surveillance.domain.schedule import DAYS


class DjangoMonitoringRepository:
    """Преобразует settings models в DTO; default schedule закрыт до настройки."""

    def __init__(self, default_timezone: str, retention: int):
        """Принимает безопасные defaults composition root."""
        self.default_timezone, self.retention = default_timezone, retention

    def layout(self, user_id, data: dict | None = None) -> dict:
        """Получает только раскладку переданного пользователя."""
        if data is not None:
            obj, _ = MonitoringLayout.objects.update_or_create(user_id=user_id, defaults=data)
        else:
            obj = MonitoringLayout.objects.filter(user_id=user_id).first()
        return {"camera_ids": obj.camera_ids if obj else [], "grid": obj.grid if obj else "auto"}

    def schedule(self, data: dict | None = None) -> dict:
        """Заменяет интервалы в транзакции, заданной вызывающим use-case."""
        obj, _ = ControlSchedule.objects.get_or_create(
            pk=1, defaults={"timezone": self.default_timezone}
        )
        if data is not None:
            obj.timezone, obj.enabled = data["timezone"], data["enabled"]
            obj.save()
            obj.intervals.all().delete()
            ControlScheduleInterval.objects.bulk_create(
                [
                    ControlScheduleInterval(schedule=obj, weekday=DAYS.index(day), **interval)
                    for day, intervals in data["week"].items()
                    for interval in intervals
                ]
            )
        week = {day: [] for day in DAYS}
        for interval in obj.intervals.order_by("weekday", "start"):
            week[DAYS[interval.weekday]].append({"start": interval.start, "end": interval.end})
        return {"timezone": obj.timezone, "week": week, "enabled": obj.enabled}

    def settings(self, data: dict | None = None) -> dict:
        """Выдаёт DTO без каких-либо deployment secrets."""
        obj, _ = SystemSettings.objects.get_or_create(
            pk=1,
            defaults={
                "default_timezone": self.default_timezone,
                "media_retention_days": self.retention,
            },
        )
        if data is not None:
            for key, value in data.items():
                setattr(obj, key, value)
            obj.save()
        return {
            "default_timezone": obj.default_timezone,
            "media_retention_days": obj.media_retention_days,
            "default_confidence": obj.default_confidence,
        }
