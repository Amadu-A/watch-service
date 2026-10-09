# tests/unit/test_capture.py
"""Регрессии независимого CPU-захвата, отключения камер и внешнего inference."""

import threading
from datetime import UTC, datetime, timedelta
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from application.surveillance.capture import CapturedFrame, PublishCameraFrame
from workers.capture import CaptureWorker
from workers.vision import InferenceWorker


def camera_data(camera_id="camera-1"):
    """Создаёт минимальные безопасные настройки включённой камеры."""
    return {"id": camera_id, "name": "Вход", "enabled": True, "updated_at": "v1"}


def test_capture_publishes_live_before_failure_of_inference_handoff():
    """Отказ передачи исходника inference не лишает браузер свежего JPEG."""
    live, captured = Mock(), Mock()
    captured.put.side_effect = OSError("redis_capture_failure")
    renderer = Mock(
        annotated=Mock(return_value=b"live-jpeg"), original=Mock(return_value=b"raw-jpeg")
    )
    publisher = PublishCameraFrame(camera_data(), None, renderer, live, captured, "Europe/Moscow")
    with pytest.raises(OSError):
        publisher.process("frame", datetime.now(UTC), "capture-session")
    live.put.assert_called_once_with("camera-1", b"live-jpeg")
    assert renderer.annotated.call_args.args[1] == []


def fake_reader():
    """Подменяет поток декодера управляемой bounded очередью без настоящего RTSP."""
    thread = Mock()
    thread.is_alive.return_value = False
    return SimpleNamespace(
        thread=thread, stop=threading.Event(), queue=Queue(1), session_id="session-1"
    )


def capture_worker(repository=None):
    """Собирает worker только из портов; распознавание выключено."""
    config = SimpleNamespace(
        vision_enabled=False, vision_reconnect_max_seconds=4, vision_frame_ttl_seconds=10
    )
    repository = repository or Mock()
    repository.list.return_value = [camera_data()]
    repository.line.return_value = None
    return CaptureWorker(
        repository, Mock(), Mock(), Mock(return_value=Mock()), Mock(), Mock(), config
    )


def test_disabled_inference_still_starts_capture_and_publishes(monkeypatch):
    """VISION_ENABLED=false сохраняет запуск RTSP и появление live JPEG."""
    reader = fake_reader()
    monkeypatch.setattr("workers.capture.CameraReader", Mock(return_value=reader))
    worker = capture_worker()
    worker.refresh()
    reader.thread.start.assert_called_once()
    reader.queue.put((datetime.now(UTC), "frame", 1))
    worker.tick()
    worker.publisher_factory.return_value.process.assert_called_once()
    worker.repository.list.return_value = []
    worker.refresh()
    assert reader.stop.is_set() and not worker.readers
    worker.captured.delete.assert_called_once_with("camera-1")
    worker.frames.client.delete.assert_called_once_with("warehouse:frame:camera-1")


def test_capture_never_opens_duplicate_decoder_while_old_reader_is_stopping(monkeypatch):
    """Изменение камеры ждёт освобождения старого decoder вместо второго RTSP-подключения."""
    reader = fake_reader()
    factory = Mock(return_value=reader)
    monkeypatch.setattr("workers.capture.CameraReader", factory)
    worker = capture_worker()
    worker.refresh()
    reader.thread.is_alive.return_value = True
    worker.repository.list.return_value = [{**camera_data(), "updated_at": "v2"}]
    worker.refresh()
    assert factory.call_count == 1 and reader.stop.is_set()
    reader.thread.is_alive.return_value = False
    worker.refresh()
    assert factory.call_count == 2


def test_capture_failure_of_one_camera_preserves_other_live_frames():
    """Ошибка кодирования первой камеры не блокирует публикацию второй."""
    worker = capture_worker()
    for camera_id in ("camera-1", "camera-2"):
        reader = fake_reader()
        reader.queue.put((datetime.now(UTC), "frame", 1))
        publisher = Mock()
        if camera_id == "camera-1":
            publisher.process.side_effect = OSError("encoding_failure")
        worker.readers[camera_id] = {"reader": reader, "publisher": publisher}
    worker.tick()
    worker.readers["camera-2"]["publisher"].process.assert_called_once()


def inference_worker():
    """Собирает inference без захвата и публикации live кадров."""
    repository = Mock()
    repository.list.return_value = [camera_data()]
    repository.line.return_value = None
    config = SimpleNamespace(vision_frame_ttl_seconds=10, vision_track_ttl_seconds=30)
    worker = InferenceWorker(repository, Mock(), Mock(return_value=Mock()), Mock(), config)
    worker.refresh()
    return worker


def test_inference_skips_duplicates_stale_frames_and_resets_reconnect_session():
    """Последний JPEG обрабатывается один раз; новый RTSP session сбрасывает tracking state."""
    worker = inference_worker()
    now = datetime.now(UTC)
    worker.captured.get.return_value = CapturedFrame(b"jpeg", now - timedelta(seconds=11), "old", 1)
    worker.tick(now)
    worker.pipeline_factory.assert_not_called()
    worker.captured.get.return_value = CapturedFrame(b"jpeg", now, "session-1", 1)
    worker.tick(now)
    worker.tick(now)
    assert worker.pipeline_factory.call_count == 1
    assert worker.pipeline_factory.return_value.process.call_count == 1
    worker.captured.get.return_value = CapturedFrame(b"jpeg", now, "session-2", 1)
    worker.tick(now)
    assert worker.pipeline_factory.call_count == 2


def test_inference_dependency_failure_is_isolated_from_capture():
    """Недоступный shared API не разрушает orchestration и не повторяет старый JPEG."""
    worker = inference_worker()
    now = datetime.now(UTC)
    worker.captured.get.return_value = CapturedFrame(b"jpeg", now, "session-1", 1)
    worker.pipeline_factory.return_value.process.side_effect = RuntimeError("inference_down")
    worker.tick(now)
    worker.tick(now)
    assert worker.pipeline_factory.return_value.process.call_count == 1


def test_captured_frame_store_roundtrip_and_ttl():
    """Redis-пакет сохраняет бинарный JPEG и контекст; новый кадр заменяет старый с TTL."""
    from infrastructure.capture import RedisCapturedFrameStore

    values = {}
    client = Mock()
    client.setex.side_effect = lambda key, ttl, value: values.__setitem__(key, value)
    client.get.side_effect = values.get
    client.delete.side_effect = lambda key: values.pop(key, None)
    store = RedisCapturedFrameStore(client, 10)
    assert store.get("camera-1") is None
    first = CapturedFrame(b"\xff\xd8\nfirst\n", datetime.now(UTC), "session-1", 1)
    store.put("camera-1", first)
    assert store.get("camera-1") == first
    second = CapturedFrame(b"\xff\xd8\nsecond", datetime.now(UTC), "session-1", 2)
    store.put("camera-1", second)
    assert store.get("camera-1") == second and len(values) == 1
    assert all(call.args[1] == 10 for call in client.setex.call_args_list)
    store.delete("camera-1")
    assert store.get("camera-1") is None


def test_inference_heartbeat_continues_between_slow_camera_requests():
    """Ошибки и длительные вызовы одной камеры не оставляют worker без heartbeat."""
    worker = inference_worker()
    worker.heartbeat = Mock()
    worker.repository.list.return_value = [camera_data(), camera_data("camera-2")]
    worker.refresh()
    now = datetime.now(UTC)
    worker.captured.get.return_value = CapturedFrame(b"jpeg", now, "session-1", 1)
    worker.pipeline_factory.return_value.process.side_effect = RuntimeError("inference_timeout")
    worker.tick(now)
    assert worker.heartbeat.call_count == 2
