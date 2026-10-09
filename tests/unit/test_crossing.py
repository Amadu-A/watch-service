# tests/unit/test_crossing.py
"""Геометрические и regression сценарии crossing без Django, видео и GPU."""

from uuid import uuid4

import pytest

from domain.common import BusinessError
from domain.surveillance.geometry import GuardLine, LineCrossingPolicy, Point, TrackState


def run_path(path, *, direction="BOTH", confidence=0.9, min_age=3):
    """Наблюдает normalized trajectory одного человека и возвращает подтверждённые события."""
    line = GuardLine(uuid4(), Point(0.2, 0.5), Point(0.8, 0.5), direction=direction)
    policy, state, events = LineCrossingPolicy(min_age=min_age), TrackState(), []
    for point in path:
        result = policy.observe(state, line, Point(*point), confidence)
        if result:
            events.append(result)
    return events


@pytest.mark.parametrize(
    "path,expected",
    [
        ([(0.5, 0.3)] * 3 + [(0.5, 0.7)] * 3, ["ENTRY"]),
        ([(0.5, 0.7)] * 3 + [(0.5, 0.3)] * 3, ["EXIT"]),
        ([(0.3, 0.3), (0.4, 0.3), (0.5, 0.3), (0.6, 0.3)], []),
        ([(0.5, 0.3)] * 3 + [(0.5, 0.5)] * 15, []),
        ([(0.5, 0.49), (0.5, 0.51)] * 20, []),
        ([(0.9, 0.3)] * 3 + [(0.9, 0.7)] * 3, []),
        ([(0.5, 0.3)] * 3 + [(0.5, 0.7)] + [(0.5, 0.3)] * 3 + [(0.5, 0.7)] * 3, ["ENTRY"]),
        ([(0.5, 0.3)] * 3 + [(0.5, 0.7), (0.5, 0.5)] + [(0.5, 0.7)] * 3, ["ENTRY"]),
        ([(0.5, 0.3)] * 3 + [(0.5, 0.7)] * 10 + [(0.5, 0.3)] * 3, ["ENTRY", "EXIT"]),
    ],
)
def test_crossing_trajectory(path, expected):
    """Проверяет направления, stops, jitter, отрезок, дедупликацию и обратный проход."""
    assert run_path(path) == expected


def test_thresholds_and_direction():
    """Молодой track, низкий confidence и запрещённое направление не создают violation."""
    path = [(0.5, 0.3)] * 3 + [(0.5, 0.7)] * 3
    assert run_path(path, confidence=0.4) == []
    assert run_path(path, min_age=20) == []
    assert run_path(path, direction="EXIT") == []
    assert run_path(path, direction="ENTRY") == ["ENTRY"]


@pytest.mark.parametrize("point", [(float("nan"), 0.5), (float("inf"), 0.5), (-0.1, 0.5)])
def test_invalid_coordinates(point):
    """NaN и координаты вне snapshot отклоняются domain boundary."""
    with pytest.raises(BusinessError):
        Point(*point)


def test_zero_length_line():
    """Вырожденная линия не должна делить на ноль."""
    with pytest.raises(BusinessError):
        GuardLine(uuid4(), Point(0.5, 0.5), Point(0.5, 0.5))
