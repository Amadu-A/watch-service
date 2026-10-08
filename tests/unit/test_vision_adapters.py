# tests/unit/test_vision_adapters.py
"""Контракты наших vision adapters проверяются без скачивания модели, GPU и RTSP."""

import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from modules.surveillance.infrastructure.vision import (
    ByteTrackTracker,
    UltralyticsPersonDetector,
    connection_url,
    probe_rtsp,
)
from workers.vision import CameraReader, flush_entry


def test_detector_model_loaded_once_and_person_output(monkeypatch, tmp_path):
    """Несколько кадров используют одну модель и передают только person boxes в tracker."""
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"fake-weights")
    boxes = Mock()
    boxes.cpu.return_value.numpy.return_value = "person-boxes"
    model = Mock()
    model.predict.return_value = [SimpleNamespace(boxes=boxes)]
    constructor = Mock(return_value=model)
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=constructor))
    detector = UltralyticsPersonDetector(str(weights), "0")
    assert detector.detect("frame-1") == detector.detect("frame-2") == "person-boxes"
    constructor.assert_called_once_with(str(weights))
    assert model.predict.call_count == 2
    assert model.predict.call_args.kwargs == {
        "classes": [0],
        "conf": 0.1,
        "device": "0",
        "verbose": False,
    }


def test_tracker_mapping_and_global_counter(monkeypatch):
    """BBox нормализуется по размеру кадра; новый tracker не переиспользует глобальные ID."""
    base = SimpleNamespace(_count=23)
    tracker = Mock()
    tracker.update.return_value = [[20, 10, 80, 90, 24, 0.91, 0, 0], [0, 0, 10, 10, 25, 0.8, 2, 1]]

    def constructor(args):
        """Повторяет сброс счётчика в upstream BYTETracker.__init__."""
        base._count = 0
        return tracker

    monkeypatch.setitem(
        sys.modules, "ultralytics.trackers.byte_tracker", SimpleNamespace(BYTETracker=constructor)
    )
    monkeypatch.setitem(
        sys.modules, "ultralytics.trackers.basetrack", SimpleNamespace(BaseTrack=base)
    )
    adapter = ByteTrackTracker(5)
    result = adapter.update("boxes", SimpleNamespace(shape=(100, 200, 3)))
    assert base._count == 23
    assert result == [{"track_id": 24, "confidence": 0.91, "bbox": [0.1, 0.1, 0.4, 0.9]}]


def test_rtsp_probe_timeout_and_secret_safe_output(monkeypatch):
    """Проверка подключения имеет deadline и не передаёт stderr камеры в пользовательские логи."""
    run = Mock(side_effect=subprocess.TimeoutExpired("ffmpeg", 12))
    monkeypatch.setattr(subprocess, "run", run)
    connection = {"url": "rtsp://192.0.2.1/live", "username": "user@name", "password": "pass:word"}
    assert not probe_rtsp(connection)
    assert connection_url(connection) == "rtsp://user%40name:pass%3Aword@192.0.2.1/live"
    assert run.call_args.kwargs["timeout"] == 12
    assert run.call_args.kwargs["stderr"] == subprocess.DEVNULL
    run.side_effect = None
    run.return_value.returncode = 0
    assert probe_rtsp(connection)


def test_reader_reconnect_and_latest_frame_queue(monkeypatch):
    """Сбой decoder приводит к reconnect; очередь содержит только последний свежий кадр."""
    repository = Mock()
    monkeypatch.setattr("workers.vision.close_old_connections", Mock())
    first, second = Mock(), Mock()
    first.read.return_value = None
    source_factory = Mock(side_effect=[first, second])
    reader = CameraReader({"id": "camera-1"}, {}, repository, 4, source_factory)
    count = 0

    def read():
        """Отдаёт два кадра и завершает тест без ожидания настоящего потока."""
        nonlocal count
        count += 1
        if count == 2:
            reader.stop.set()
        return f"frame-{count}"

    second.read.side_effect = read
    monkeypatch.setattr(reader.stop, "wait", lambda timeout: False)
    reader.run()
    assert source_factory.call_count == 2 and reader.generation == 2
    assert reader.queue.qsize() == 1
    assert reader.queue.get_nowait()[1] == "frame-2"
    assert repository.status.call_args_list[-1].args == ("camera-1", "ONLINE")
    first.close.assert_called_once()
    second.close.assert_called_once()


def test_camera_flush_failure_is_isolated():
    """Неудачное сохранение evidence одной камеры не распространяет исключение в worker loop."""
    pipeline = Mock()
    pipeline.flush.side_effect = OSError("disk_full")
    entry = {"pipeline": pipeline, "reader": SimpleNamespace(camera={"id": "camera-1"})}
    assert not flush_entry(entry, "timestamp", force=True)
    pipeline.flush.side_effect = None
    assert flush_entry(entry, "timestamp", force=True)
