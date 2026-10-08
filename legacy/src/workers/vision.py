# src/workers/vision.py
"""Vision worker: независимые decoder threads и одна resident model для всех камер."""
# ruff: noqa: E402

import logging
import os
import signal
import threading
import time
from contextlib import suppress
from datetime import UTC, datetime
from queue import Empty, Full, Queue

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.db import close_old_connections

from core import container as c


class CameraReader:
    """Один thread на decoder: отказ RTSP не блокирует inference остальных камер."""

    def __init__(
        self, camera: dict, connection: dict, repository, max_backoff: int, source_factory
    ):
        """Создаёт bounded очередь последнего кадра и остановку decoder."""
        self.camera, self.connection, self.repository = camera, connection, repository
        self.max_backoff = max_backoff
        self.source_factory = source_factory
        self.queue = Queue(maxsize=1)
        self.stop = threading.Event()
        self.generation = 0
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self) -> None:
        """Переподключает камеру с bounded exponential backoff и state-change logs."""
        retry = 1
        while not self.stop.is_set():
            source = None
            try:
                close_old_connections()
                self.repository.status(self.camera["id"], "CONNECTING")
                source = self.source_factory(self.connection)
                self.generation += 1
                first, status_at = True, 0
                while not self.stop.is_set():
                    frame = source.read()
                    if frame is None:
                        raise RuntimeError("camera_disconnected")
                    if first or time.monotonic() >= status_at:
                        self.repository.status(self.camera["id"], "ONLINE")
                        first, retry = False, 1
                        status_at = time.monotonic() + 5
                    try:
                        self.queue.put_nowait((datetime.now(UTC), frame, self.generation))
                    except Full:
                        with suppress(Empty):
                            self.queue.get_nowait()
                        self.queue.put_nowait((datetime.now(UTC), frame, self.generation))
            except Exception:
                logging.getLogger(__name__).warning(
                    "camera_disconnected",
                    extra={"event": "camera_disconnected", "camera_id": self.camera["id"]},
                )
                with suppress(Exception):
                    self.repository.status(self.camera["id"], "OFFLINE")
            finally:
                if source:
                    source.close()
                close_old_connections()
            self.stop.wait(retry)
            retry = min(self.max_backoff, retry * 2)


def log_failure(entry) -> None:
    """Ограничивает повторные сообщения одной камеры одним событием в 30 секунд."""
    if time.monotonic() >= entry.get("error_log_at", 0):
        logging.getLogger(__name__).error(
            "camera_pipeline_failed",
            extra={"event": "camera_pipeline_failed", "camera_id": entry["reader"].camera["id"]},
        )
        entry["error_log_at"] = time.monotonic() + 30


def flush_entry(entry, timestamp, force=False) -> bool:
    """Сохраняет pending evidence; сбой одной камеры не останавливает остальные."""
    try:
        if entry["pipeline"]:
            entry["pipeline"].flush(timestamp, force=force)
        return True
    except Exception:
        log_failure(entry)
        return False


def main() -> None:
    """Загружает модель один раз и обновляет состав камер без перезапуска web."""
    config = c.configuration()
    detector = c.vision_detector()
    renderer, repository, readers = (
        c.frame_renderer(),
        c.camera_service().repository,
        {},
    )
    stop = threading.Event()

    def shutdown(signum, frame):
        """Останавливает loop после штатного SIGTERM/SIGINT."""
        stop.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    refresh_at = 0
    try:
        while not stop.is_set():
            c.frames().client.setex("warehouse:vision:ready", 10, "1")
            if time.monotonic() >= refresh_at:
                close_old_connections()
                cameras = {
                    item["id"]: item for item in repository.list() if item["enabled"] and detector
                }
                for camera_id in list(readers):
                    if (
                        camera_id not in cameras
                        or readers[camera_id]["version"] != cameras[camera_id]["updated_at"]
                    ):
                        entry = readers[camera_id]
                        entry["reader"].stop.set()
                        entry["reader"].thread.join(timeout=6)
                        if not flush_entry(entry, datetime.now(UTC), force=True):
                            continue
                        readers.pop(camera_id)
                for camera_id, camera in cameras.items():
                    line = repository.line(camera_id)
                    if camera_id in readers and readers[camera_id]["line"] != line:
                        if not flush_entry(readers[camera_id], datetime.now(UTC), force=True):
                            continue
                        readers[camera_id]["pipeline"] = None
                        readers[camera_id]["line"] = line
                    if camera_id not in readers:
                        reader = CameraReader(
                            camera,
                            c.cipher().decrypt(repository.connection(camera_id)),
                            repository,
                            config.vision_reconnect_max_seconds,
                            c.camera_source,
                        )
                        readers[camera_id] = {
                            "reader": reader,
                            "version": camera["updated_at"],
                            "line": line,
                            "pipeline": None,
                            "generation": -1,
                        }
                        reader.thread.start()
                refresh_at = time.monotonic() + 5
            for entry in readers.values():
                try:
                    timestamp, frame, generation = entry["reader"].queue.get_nowait()
                except Empty:
                    flush_entry(entry, datetime.now(UTC))
                    continue
                if entry["pipeline"] is None or generation != entry["generation"]:
                    if not flush_entry(entry, timestamp, force=True):
                        continue
                    entry["pipeline"] = c.camera_pipeline(
                        entry["reader"].camera,
                        entry["line"],
                        detector,
                        renderer,
                    )
                    entry["generation"] = generation
                try:
                    entry["pipeline"].process(frame, timestamp)
                except Exception:
                    log_failure(entry)
            stop.wait(1 / config.vision_fps)
    finally:
        for entry in readers.values():
            entry["reader"].stop.set()
            flush_entry(entry, datetime.now(UTC), force=True)
        c.frames().client.delete("warehouse:vision:ready")


if __name__ == "__main__":
    main()
