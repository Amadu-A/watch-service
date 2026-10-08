# tests/unit/test_schedule.py
"""Расписание: ночь, границы интервала, выходные, перевод timezone и DST."""

from datetime import datetime

import pytest

from core.domain import BusinessError
from modules.surveillance.domain.schedule import SchedulePolicy, validate_schedule


@pytest.mark.parametrize(
    "timestamp,expected",
    [
        ("2026-10-05T18:59:59+03:00", False),
        ("2026-10-05T19:00:00+03:00", True),
        ("2026-10-06T07:59:59+03:00", True),
        ("2026-10-06T08:00:00+03:00", False),
        ("2026-10-05T16:00:00+00:00", True),
        ("2026-10-10T12:00:00+03:00", True),
        ("2026-10-11T00:00:00+03:00", False),
    ],
)
def test_weekly_boundaries(timestamp, expected):
    """Ночной остаток относится к дню начала, а правая граница не включена."""
    schedule = validate_schedule(
        {
            "timezone": "Europe/Moscow",
            "week": {
                "monday": [{"start": "19:00", "end": "08:00"}],
                "saturday": [{"start": "00:00", "end": "24:00"}],
            },
        }
    )
    assert SchedulePolicy().active(schedule, datetime.fromisoformat(timestamp)) is expected


@pytest.mark.parametrize("timestamp", ["2026-10-25T00:30:00+00:00", "2026-10-25T01:30:00+00:00"])
def test_repeated_hour_dst(timestamp):
    """Обе реальные UTC даты повторного локального часа корректно активны."""
    schedule = validate_schedule(
        {"timezone": "Europe/Berlin", "week": {"sunday": [{"start": "02:00", "end": "03:00"}]}}
    )
    assert SchedulePolicy().active(schedule, datetime.fromisoformat(timestamp))


def test_invalid_and_disabled_schedule():
    """Отклоняет неизвестный timezone, пустую длительность и naïve timestamps."""
    for data in (
        {"timezone": "unknown", "week": {}},
        {"timezone": "UTC", "week": {"monday": [{"start": "00:00", "end": "00:00"}]}},
    ):
        with pytest.raises(BusinessError):
            validate_schedule(data)
    with pytest.raises(BusinessError):
        SchedulePolicy().active({"timezone": "UTC", "week": {}}, datetime(2026, 1, 1))
    assert not SchedulePolicy().active(
        {"timezone": "UTC", "week": {}, "enabled": False},
        datetime.fromisoformat("2026-10-07T12:00:00+00:00"),
    )
