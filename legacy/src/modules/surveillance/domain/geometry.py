# src/modules/surveillance/domain/geometry.py
"""Нормализованная геометрия и конечный автомат пересечений с гистерезисом."""

import math
from dataclasses import dataclass
from uuid import UUID

from core.domain import BusinessError


@dataclass(frozen=True)
class Point:
    """Координата в долях размера кадра; не зависит от resolution камеры."""

    x: float
    y: float

    def __post_init__(self):
        """Запрещает NaN, бесконечность и координаты вне кадра."""
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in (self.x, self.y)):
            raise BusinessError("invalid_point", "Координаты должны быть от 0 до 1.")


@dataclass(frozen=True)
class GuardLine:
    """Описывает ориентированный отрезок и ограничения подтверждения crossing."""

    id: UUID
    start: Point
    end: Point
    inside_side: str = "left"
    direction: str = "ENTRY"
    min_confidence: float = 0.65
    enabled: bool = True

    def __post_init__(self):
        """Отклоняет вырожденную линию и неизвестные правила направления."""
        if self.start == self.end:
            raise BusinessError("invalid_line", "Точки линии должны различаться.")
        if self.inside_side not in ("left", "right") or self.direction not in (
            "ENTRY",
            "EXIT",
            "BOTH",
        ):
            raise BusinessError("invalid_direction", "Неверная сторона или направление.")
        if not math.isfinite(self.min_confidence) or not 0 <= self.min_confidence <= 1:
            raise BusinessError("invalid_confidence", "Confidence должен быть от 0 до 1.")

    def distance(self, point: Point) -> float:
        """Возвращает знаковое расстояние от ног человека до ориентированной линии."""
        dx, dy = self.end.x - self.start.x, self.end.y - self.start.y
        return (dx * (point.y - self.start.y) - dy * (point.x - self.start.x)) / math.hypot(dx, dy)

    def intersection(self, previous: Point, current: Point) -> Point | None:
        """Вычисляет точку пересечения траектории с отрезком, включая его концы."""
        a, b = self.distance(previous), self.distance(current)
        if a * b >= 0 or a == b:
            return None
        ratio = a / (a - b)
        x = previous.x + ratio * (current.x - previous.x)
        y = previous.y + ratio * (current.y - previous.y)
        dx, dy = self.end.x - self.start.x, self.end.y - self.start.y
        projection = ((x - self.start.x) * dx + (y - self.start.y) * dy) / (dx * dx + dy * dy)
        return Point(x, y) if 0 <= projection <= 1 else None

    def intersects(self, previous: Point, current: Point) -> bool:
        """Проверяет пересечение траектории именно с отрезком."""
        return self.intersection(previous, current) is not None


@dataclass
class TrackState:
    """Ограниченный состоянием камеры автомат одного устойчивого track_id."""

    age: int = 0
    side: int = 0
    stable_point: Point | None = None
    candidate_side: int = 0
    candidate_frames: int = 0
    segment_crossed: bool = False
    sequence: int = 0
    crossing_point: Point | None = None


class LineCrossingPolicy:
    """Подтверждает переход только после устойчивого положения на обеих сторонах."""

    def __init__(self, *, min_age: int = 3, stable_frames: int = 2, hysteresis: float = 0.02):
        """Получает deployment thresholds без обращения к инфраструктуре."""
        self.min_age, self.stable_frames, self.hysteresis = min_age, stable_frames, hysteresis

    def observe(
        self, state: TrackState, line: GuardLine, point: Point, confidence: float
    ) -> str | None:
        """Обновляет track; возвращает ENTRY/EXIT ровно один раз на переход."""
        state.age += 1
        if not line.enabled or confidence < line.min_confidence:
            state.candidate_side, state.candidate_frames = 0, 0
            return None
        distance = line.distance(point)
        side = 1 if distance > self.hysteresis else -1 if distance < -self.hysteresis else 0
        if side == 0:
            state.candidate_side, state.candidate_frames = 0, 0
            return None
        if side == state.side:
            state.stable_point = point
            state.candidate_side, state.candidate_frames = 0, 0
            state.segment_crossed = False
            return None
        if side != state.candidate_side:
            state.candidate_side, state.candidate_frames = side, 0
            state.crossing_point = (
                line.intersection(state.stable_point, point) if state.stable_point else None
            )
            state.segment_crossed = state.crossing_point is not None
        state.candidate_frames += 1
        if state.candidate_frames < self.stable_frames:
            return None
        old_side = state.side
        state.side, state.stable_point = side, point
        state.candidate_frames = 0
        if not old_side or not state.segment_crossed or state.age < self.min_age:
            return None
        state.sequence += 1
        inside = 1 if line.inside_side == "left" else -1
        direction = "ENTRY" if side == inside else "EXIT"
        return direction if line.direction in (direction, "BOTH") else None
