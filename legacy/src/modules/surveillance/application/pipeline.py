# src/modules/surveillance/application/pipeline.py
"""Пайплайн кадра, crossing, weekly schedule и bounded evidence ring buffer."""

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from core.ports import LiveFrameCache
from modules.surveillance.application.ports import (
    FrameRenderer,
    ObjectTracker,
    PersonDetector,
    ViolationCreator,
)
from modules.surveillance.domain.geometry import GuardLine, Point, TrackState
from modules.surveillance.domain.schedule import SchedulePolicy


@dataclass
class PendingEvidence:
    """Ожидает кадры после crossing, сохраняя неизменный timestamp события."""

    event: dict
    deadline: datetime
    candidates: list


def evidence_score(track: dict, timestamp: datetime, detected_at: datetime) -> float:
    """Предпочитает уверенный крупный bbox без обрезания, близкий к моменту crossing."""
    x1, y1, x2, y2 = track["bbox"]
    area = max(0, x2 - x1) * max(0, y2 - y1)
    clipped = x1 <= 0.01 or y1 <= 0.01 or x2 >= 0.99 or y2 >= 0.99
    return (
        track["confidence"]
        + area
        - (0.5 if clipped else 0)
        - abs((timestamp - detected_at).total_seconds()) * 0.1
    )


class CameraPipeline:
    """Camera-local state; worker использует общий detector и независимый tracker на камеру."""

    def __init__(
        self,
        *,
        camera: dict,
        line: dict | None,
        detector: PersonDetector,
        tracker: ObjectTracker,
        renderer: FrameRenderer,
        cache: LiveFrameCache,
        crossing_policy,
        schedule_provider: Callable[[], dict],
        create_violation: ViolationCreator,
        fps: int,
        before_seconds: float,
        after_seconds: float,
        track_ttl: int,
        clip_enabled: bool = False,
        clip_before: float = 5,
        clip_after: float = 5,
    ):
        """Получает все ports извне; ограничивает память количеством кадров и track TTL."""
        self.camera, self.line = camera, line
        self.detector, self.tracker, self.renderer, self.cache = detector, tracker, renderer, cache
        self.crossing_policy, self.schedule_provider, self.create_violation = (
            crossing_policy,
            schedule_provider,
            create_violation,
        )
        self.fps, self.before_seconds, self.after_seconds, self.track_ttl = (
            fps,
            before_seconds,
            after_seconds,
            track_ttl,
        )
        self.clip_enabled, self.clip_before, self.clip_after = clip_enabled, clip_before, clip_after
        seconds = max(before_seconds, clip_before if clip_enabled else 0)
        self.buffer = deque(maxlen=max(2, int(seconds * fps) + 2))
        self.tracks, self.pending = {}, []
        self.max_pending = 32
        self.session = str(uuid4())
        self.schedule_policy = SchedulePolicy()

    def process(self, frame, timestamp: datetime) -> None:
        """Публикует annotated live frame и создаёт события только при активном расписании."""
        self.flush(timestamp)
        if len(self.pending) >= self.max_pending:
            raise RuntimeError("evidence_backlog_full")
        detections = self.detector.detect(frame)
        tracks = self.tracker.update(detections, frame)
        schedule = self.schedule_provider()
        original = self.renderer.original(frame)
        local_time = timestamp.astimezone(ZoneInfo(schedule["timezone"]))
        label = f"{self.camera['name']} | {local_time.isoformat()}"
        annotated = self.renderer.annotated(frame, tracks, self.line, label)
        self.cache.put(self.camera["id"], annotated)
        self.buffer.append((timestamp, frame, original, tracks))
        line = None
        if self.line:
            line = GuardLine(
                UUID(self.line["id"]),
                Point(**self.line["start"]),
                Point(**self.line["end"]),
                self.line["inside_side"],
                self.line["direction"],
                self.line["min_confidence"],
                self.line["enabled"],
            )
        for track in tracks:
            state, _ = self.tracks.get(track["track_id"], (TrackState(), timestamp))
            self.tracks[track["track_id"]] = (state, timestamp)
            if not line:
                continue
            x1, _, x2, y2 = track["bbox"]
            point = Point((x1 + x2) / 2, y2)
            direction = self.crossing_policy.observe(state, line, point, track["confidence"])
            if direction and self.schedule_policy.active(schedule, timestamp):
                if len(self.pending) >= self.max_pending:
                    raise RuntimeError("evidence_backlog_full")
                event = {
                    "camera_id": self.camera["id"],
                    "guard_line_id": str(line.id),
                    "event_key": (
                        f"{self.camera['id']}:{self.session}:{track['track_id']}:{state.sequence}"
                    ),
                    "track_id": track["track_id"],
                    "direction": direction,
                    "detected_at": timestamp,
                    "confidence": track["confidence"],
                    "bbox": track["bbox"],
                    "crossing_point": {"x": state.crossing_point.x, "y": state.crossing_point.y},
                    "line_snapshot": self.line,
                    "camera_snapshot": {
                        "name": self.camera["name"],
                        "location": self.camera["location"],
                    },
                }
                candidates = list(self.buffer)
                wait = max(self.after_seconds, self.clip_after if self.clip_enabled else 0)
                self.pending.append(
                    PendingEvidence(event, timestamp + timedelta(seconds=wait), candidates)
                )
        self.tracks = {
            key: value
            for key, value in self.tracks.items()
            if (timestamp - value[1]).total_seconds() <= self.track_ttl
        }
        for pending in self.pending:
            if timestamp <= pending.deadline and pending.candidates[-1][0] != timestamp:
                pending.candidates.append((timestamp, frame, original, tracks))
        self.flush(timestamp)

    def flush(self, timestamp: datetime, force: bool = False) -> None:
        """Выбирает лучший кадр; при disconnect завершает event доступными evidence."""
        ready = [item for item in self.pending if force or timestamp >= item.deadline]
        for pending in ready:
            event = pending.event
            event_time = event["detected_at"].astimezone(
                ZoneInfo(self.schedule_provider()["timezone"])
            )
            options = []
            for time, frame, original, tracks in pending.candidates:
                if (
                    not -self.before_seconds
                    <= (time - event["detected_at"]).total_seconds()
                    <= self.after_seconds
                ):
                    continue
                for track in tracks:
                    if track["track_id"] == event["track_id"]:
                        options.append(
                            (
                                evidence_score(track, time, event["detected_at"]),
                                frame,
                                original,
                                track,
                            )
                        )
            if options:
                _, frame, original, track = max(options, key=lambda option: option[0])
                annotated = self.renderer.annotated(
                    frame,
                    [track],
                    event["line_snapshot"],
                    f"{self.camera['name']} | {event_time.isoformat()} | {event['direction']}",
                )
                clip = None
                if self.clip_enabled:
                    clip = self.renderer.clip([item[1] for item in pending.candidates], self.fps)
                self.create_violation.execute(event, original, annotated, clip)
            self.pending.remove(pending)
