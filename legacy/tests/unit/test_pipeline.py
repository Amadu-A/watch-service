# tests/unit/test_pipeline.py
"""Пайплайн на синтетических frames: independent state, evidence и ограниченная память."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest

from modules.surveillance.application.pipeline import CameraPipeline
from modules.surveillance.domain.geometry import LineCrossingPolicy


def pipeline(*, enabled=True, create=None):
    """Собирает тестовый пайплайн только из ports и простых frames без OpenCV/YOLO."""
    tracker = Mock()
    tracker.update.return_value = []
    return CameraPipeline(
        camera={"id": str(uuid4()), "name": "Вход", "location": "Склад"},
        line={
            "id": str(uuid4()),
            "start": {"x": 0.2, "y": 0.5},
            "end": {"x": 0.8, "y": 0.5},
            "inside_side": "left",
            "direction": "BOTH",
            "min_confidence": 0.65,
            "enabled": True,
        },
        detector=Mock(),
        tracker=tracker,
        renderer=Mock(
            original=Mock(return_value=b"jpeg"), annotated=Mock(return_value=b"annotated")
        ),
        cache=Mock(),
        crossing_policy=LineCrossingPolicy(),
        schedule_provider=lambda: {
            "enabled": enabled,
            "timezone": "Europe/Moscow",
            "week": {"monday": [{"start": "00:00", "end": "24:00"}]},
        },
        create_violation=create or Mock(),
        fps=5,
        before_seconds=1,
        after_seconds=1,
        track_ttl=2,
    )


def observe(item, positions, start=None):
    """Передаёт bbox с точкой ног по заданной траектории и возрастающими UTC timestamps."""
    start = start or datetime(2026, 10, 5, 12, tzinfo=UTC)
    for index, (y, confidence) in enumerate(positions):
        item.tracker.update.return_value = [
            {"track_id": 1, "confidence": confidence, "bbox": [0.4, y - 0.2, 0.6, y]}
        ]
        item.process(f"frame-{index}", start + timedelta(seconds=index / 5))
    return start + timedelta(seconds=(len(positions) - 1) / 5)


def test_best_frame_preserves_crossing_time_and_deduplicates():
    """Лучший кадр может быть позднее crossing; timestamp и число событий остаются верными."""
    item = pipeline()
    last = observe(item, [(0.3, 0.7)] * 3 + [(0.7, 0.8)] * 2 + [(0.75, 0.99)] * 5)
    item.flush(last + timedelta(seconds=2))
    assert item.create_violation.execute.call_count == 1
    event, original, annotated, clip = item.create_violation.execute.call_args.args
    assert event["detected_at"] == datetime(2026, 10, 5, 12, tzinfo=UTC) + timedelta(seconds=0.8)
    assert event["direction"] == "ENTRY" and original == b"jpeg" and annotated == b"annotated"
    assert clip is None and item.pending == []
    evidence_tracks = item.renderer.annotated.call_args.args[1]
    assert evidence_tracks[0]["confidence"] == 0.99


def test_schedule_suppresses_events_but_keeps_live_frames():
    """Выключенный контроль запрещает нарушения, сохраняя просмотр кадров."""
    item = pipeline(enabled=False)
    last = observe(item, [(0.3, 0.9)] * 3 + [(0.7, 0.9)] * 10)
    item.flush(last, force=True)
    item.create_violation.execute.assert_not_called()
    assert item.cache.put.call_count == 13


def test_camera_state_is_independent_and_old_tracks_expire():
    """Одинаковые track IDs разных камер не делят state; пропавшие tracks удаляются по TTL."""
    first, second = pipeline(), pipeline()
    last = observe(first, [(0.3, 0.9)] * 3 + [(0.7, 0.9)] * 8)
    observe(second, [(0.3, 0.9)] * 11)
    assert first.create_violation.execute.call_count == 1
    second.create_violation.execute.assert_not_called()
    first.tracker.update.return_value = []
    first.process("empty", last + timedelta(seconds=3))
    assert not first.tracks and len(first.buffer) <= 7


def test_pending_evidence_survives_storage_failure_without_growing():
    """Неуспешный flush сохраняет bounded candidates для повторного сохранения."""
    create = Mock()
    item = pipeline(create=create)
    last = observe(item, [(0.3, 0.9)] * 3 + [(0.7, 0.9)] * 2)
    create.execute.side_effect = OSError("disk_full")
    count = len(item.pending[0].candidates)
    for index in range(20):
        with pytest.raises(OSError):
            item.process("later", last + timedelta(seconds=2 + index))
    assert len(item.pending) == 1 and len(item.pending[0].candidates) == count
    create.execute.side_effect = None
    item.flush(last, force=True)
    assert not item.pending
