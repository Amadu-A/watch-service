# tests/unit/test_vision_adapters.py
"""Контракты наших vision adapters проверяются без скачивания модели, GPU и RTSP."""

import subprocess
from datetime import UTC, datetime
from unittest.mock import Mock

import httpx

from infrastructure.inference import SharedPersonDetector, SharedTrackMapper
from infrastructure.vision import connection_url, probe_rtsp
from workers.capture import CameraReader
from workers.vision import flush_entry


def test_detector_reuses_http_client_and_preserves_frame_context():
    """Кадры идут в shared API с camera/session/sequence; person tracks сохраняют bbox и ID."""
    requests = []

    def respond(request):
        """Эмулирует документированный внешний CV-контракт без модели или GPU."""
        requests.append(request)
        assert b'name="image"' in request.content and b"jpeg" in request.content
        return httpx.Response(
            200,
            json={
                "version": 1,
                "camera_id": "camera-1",
                "session_id": "session-1",
                "sequence": len(requests),
                "tracks": [{"track_id": 24, "confidence": 0.91, "bbox": [0.1, 0.1, 0.4, 0.9]}],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        detector = SharedPersonDetector(
            client,
            "http://shared-cv/v1/person-tracks",
            "",
            "camera-1",
            "session-1",
            Mock(original=Mock(return_value=b"jpeg")),
            2,
        )
        for _ in range(2):
            tracks = detector.detect("frame", datetime.now(UTC))
            assert SharedTrackMapper().update(tracks, "frame") == [
                {"track_id": 24, "confidence": 0.91, "bbox": [0.1, 0.1, 0.4, 0.9]},
            ]
    assert len(requests) == 2
    assert all("authorization" not in request.headers for request in requests)


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
    monkeypatch.setattr("workers.capture.close_old_connections", Mock())
    first, second = Mock(), Mock()
    first.read.return_value = None
    source_factory = Mock(side_effect=[first, second])
    reader = CameraReader({"id": "camera-1"}, {}, repository, 4, source_factory)
    count = 0

    def read():
        """Отдаёт два кадра и завершает тест без ожидания настоящего потока."""
        nonlocal count
        count += 1
        if count == 3:
            reader.stop.set()
            return None
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
    entry = {"pipeline": pipeline, "camera": {"id": "camera-1"}}
    assert not flush_entry(entry, "timestamp", force=True)
    pipeline.flush.side_effect = None
    assert flush_entry(entry, "timestamp", force=True)
