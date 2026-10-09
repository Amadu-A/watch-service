# src/workers/vision.py
"""Необязательное распознавание последних JPEG через внешний shared CV API."""
# ruff: noqa: E402

import logging
import os
import signal
import threading
import time
from datetime import UTC, datetime

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.db import close_old_connections

from core import container as c


def log_failure(entry: dict) -> None:
    """Ограничивает ошибки inference одной камеры одной записью в 30 секунд."""
    if time.monotonic() >= entry.get("error_log_at", 0):
        logging.getLogger(__name__).error(
            "camera_inference_failed",
            exc_info=True,
            extra={"event": "camera_inference_failed", "camera_id": entry["camera"]["id"]},
        )
        entry["error_log_at"] = time.monotonic() + 30


def flush_entry(entry: dict, timestamp: datetime, force: bool = False) -> bool:
    """Сохраняет ожидающие доказательства, изолируя сбой одной камеры."""
    try:
        if entry["pipeline"]:
            entry["pipeline"].flush(timestamp, force=force)
        return True
    except Exception:
        log_failure(entry)
        return False


class InferenceWorker:
    """Читает bounded последние кадры, сохраняя отдельное состояние каждой камеры."""

    def __init__(self, repository, captured, pipeline_factory, decoder, config, heartbeat=None):
        """Получает порты без RTSP, credentials, доступа к GPU и live-cache writer."""
        self.repository, self.captured, self.pipeline_factory = (
            repository,
            captured,
            pipeline_factory,
        )
        self.decoder, self.config, self.entries = decoder, config, {}
        self.heartbeat = heartbeat

    def refresh(self) -> None:
        """Обновляет камеры и конфигурацию линий с завершением ожидающих доказательств."""
        cameras = {item["id"]: item for item in self.repository.list() if item["enabled"]}
        for camera_id in list(self.entries):
            if camera_id not in cameras:
                entry = self.entries[camera_id]
                entry["active"] = False
                if flush_entry(entry, datetime.now(UTC), force=True):
                    self.entries.pop(camera_id)
        for camera_id, camera in cameras.items():
            line = self.repository.line(camera_id)
            version = (camera["updated_at"], line)
            previous = self.entries.get(camera_id)
            if previous and previous["version"] == version:
                previous["active"] = True
                continue
            if previous:
                previous["active"] = False
                if not flush_entry(previous, datetime.now(UTC), force=True):
                    continue
            self.entries[camera_id] = {
                "camera": camera,
                "line": line,
                "version": version,
                "pipeline": None,
                "session": None,
                "last_key": None,
                "last_at": None,
                "active": True,
            }

    def tick(self, now: datetime | None = None) -> None:
        """Не повторяет кадры и сбрасывает трекинг при reconnect, пропуске или смене линии."""
        for camera_id, entry in self.entries.items():
            current_time = now or datetime.now(UTC)
            if self.heartbeat:
                self.heartbeat()
            try:
                if not entry["active"]:
                    flush_entry(entry, current_time, force=True)
                    continue
                captured = self.captured.get(camera_id)
                if (
                    captured is None
                    or not 0
                    <= (current_time - captured.captured_at).total_seconds()
                    <= self.config.vision_frame_ttl_seconds
                ):
                    flush_entry(entry, current_time)
                    continue
                key = (captured.session_id, captured.sequence)
                if key == entry["last_key"]:
                    flush_entry(entry, current_time)
                    continue
                gap = (
                    entry["last_at"]
                    and (captured.captured_at - entry["last_at"]).total_seconds()
                    > self.config.vision_track_ttl_seconds
                )
                if entry["session"] != captured.session_id or gap:
                    if not flush_entry(entry, current_time, force=True):
                        continue
                    entry["pipeline"] = self.pipeline_factory(
                        entry["camera"], entry["line"], captured.session_id
                    )
                    entry["session"] = captured.session_id
                entry["last_key"], entry["last_at"] = key, captured.captured_at
                frame = self.decoder(captured.jpeg)
                entry["pipeline"].process(frame, captured.captured_at)
            except Exception:
                log_failure(entry)

    def shutdown(self) -> None:
        """Завершает pending evidence при штатной остановке inference-процесса."""
        for entry in self.entries.values():
            flush_entry(entry, datetime.now(UTC), force=True)


def main() -> None:
    """Запускает внешний inference только при явно настроенном согласованном endpoint."""
    config = c.configuration()
    if not config.vision_enabled:
        raise RuntimeError("VISION_ENABLED=false: запускайте camera-capture для просмотра")
    worker = InferenceWorker(
        c.camera_service().repository,
        c.captured_frames(),
        c.inference_pipeline,
        c.captured_frame_decoder,
        config,
        lambda: c.frames().client.setex("warehouse:inference:ready", 10, "1"),
    )
    stop = threading.Event()

    def shutdown(signum, frame):
        """Останавливает обработку после SIGTERM или SIGINT."""
        stop.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    refresh_at = 0
    try:
        while not stop.is_set():
            if time.monotonic() >= refresh_at:
                close_old_connections()
                worker.refresh()
                refresh_at = time.monotonic() + 5
            worker.tick()
            c.frames().client.setex("warehouse:inference:ready", 10, "1")
            stop.wait(1 / config.vision_fps)
    finally:
        worker.shutdown()
        c.frames().client.delete("warehouse:inference:ready")
        c.inference_client().close()
        close_old_connections()


if __name__ == "__main__":
    main()
