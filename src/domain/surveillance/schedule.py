# src/domain/surveillance/schedule.py
"""Чистые правила недельного расписания, полуночи, временных зон и DST."""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from domain.common import BusinessError

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def minutes(value: str, *, end: bool = False) -> int:
    """Преобразует HH:MM; 24:00 разрешено только как конец полного дня."""
    try:
        hour, minute = map(int, value.split(":"))
        if len(value) != 5 or minute not in range(60) or hour not in range(24):
            if end and value == "24:00":
                return 1440
            raise ValueError
        return hour * 60 + minute
    except (ValueError, AttributeError):
        raise BusinessError("invalid_time", "Ожидается время HH:MM.") from None


def validate_schedule(data: dict) -> dict:
    """Проверяет weekly intervals; нулевая длительность запрещена, пустая неделя допустима."""
    try:
        ZoneInfo(data["timezone"])
    except (ZoneInfoNotFoundError, KeyError, TypeError):
        raise BusinessError("invalid_timezone", "Неизвестный часовой пояс.") from None
    week = data.get("week", {})
    if not isinstance(week, dict) or any(day not in DAYS for day in week):
        raise BusinessError("invalid_week", "Неизвестный день недели.")
    for intervals in week.values():
        if not isinstance(intervals, list) or len(intervals) > 24:
            raise BusinessError("invalid_intervals", "Допустимо до 24 интервалов в сутки.")
        for interval in intervals:
            if not isinstance(interval, dict) or not {"start", "end"} <= interval.keys():
                raise BusinessError("invalid_interval", "Укажите начало и конец интервала.")
            if minutes(interval["start"]) == minutes(interval["end"], end=True):
                raise BusinessError("empty_interval", "Для полного дня используйте 00:00–24:00.")
    return {"timezone": data["timezone"], "week": week, "enabled": data.get("enabled", True)}


class SchedulePolicy:
    """Определяет активность по локальному времени объекта, с открытой правой границей."""

    def active(self, schedule: dict, timestamp: datetime) -> bool:
        """Учитывает остаток ночного интервала предыдущего дня и календарный DST."""
        if timestamp.tzinfo is None:
            raise BusinessError("naive_datetime", "Дата должна содержать часовой пояс.")
        if not schedule.get("enabled", True):
            return False
        local = timestamp.astimezone(ZoneInfo(schedule["timezone"]))
        current = local.hour * 60 + local.minute + local.second / 60
        week = schedule["week"]
        for item in week.get(DAYS[local.weekday()], []):
            start, end = minutes(item["start"]), minutes(item["end"], end=True)
            if (start < end and start <= current < end) or (start > end and current >= start):
                return True
        for item in week.get(DAYS[(local.weekday() - 1) % 7], []):
            start, end = minutes(item["start"]), minutes(item["end"], end=True)
            if start > end and current < end:
                return True
        return False
