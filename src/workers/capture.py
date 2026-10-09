# src/workers/capture.py
"""CPU-захват RTSP: независимые декодеры и публикация JPEG без inference."""
# ruff: noqa: E402

import logging
import os
import signal
import threading
import time
from contextlib import suppress
from datetime import UTC, datetime
from queue import Empty, Full, Queue
from uuid import uuid4

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.db import close_old_connections

from core import container as c


class CameraReader:
    """Один CPU-декодер на камеру; разрыв RTSP не блокирует остальные потоки."""

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
        self.session_id = str(uuid4())
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
                    if self.stop.is_set():
                        break
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


def log_failure(camera_id: str, entry: dict) -> None:
    """Ограничивает диагностику камеры и скрывает credentials внешних исключений."""
    if time.monotonic() >= entry.get("error_log_at", 0):
        logging.getLogger(__name__).error(
            "camera_capture_failed",
            exc_info=True,
            extra={"event": "camera_capture_failed", "camera_id": camera_id},
        )
        entry["error_log_at"] = time.monotonic() + 30


class CaptureWorker:
    """Управляет составом CPU-декодеров, не обращаясь к detector или RabbitMQ."""

    def __init__(
        self, repository, cipher, source_factory, publisher_factory, frames, captured, config
    ):
        """Получает порты из composition root и держит по одной bounded очереди на камеру."""
        self.repository, self.cipher, self.source_factory = repository, cipher, source_factory
        self.publisher_factory, self.frames, self.captured = publisher_factory, frames, captured
        self.config, self.readers, self.errors = config, {}, {}

    def retire(self, camera_id: str) -> bool:
        """Останавливает декодер до создания замены и удаляет старые кадры из Redis."""
        entry = self.readers[camera_id]
        entry["reader"].stop.set()
        self.frames.client.delete(f"warehouse:frame:{camera_id}")
        self.captured.delete(camera_id)
        entry["reader"].thread.join(timeout=6)
        if entry["reader"].thread.is_alive():
            return False
        self.readers.pop(camera_id)
        return True

    def refresh(self) -> None:
        """Подхватывает добавление, отключение, credentials и контрольную линию без рестарта web."""
        cameras = {item["id"]: item for item in self.repository.list() if item["enabled"]}
        self.errors = {key: value for key, value in self.errors.items() if key in cameras}
        for camera_id in list(self.readers):
            if (
                camera_id not in cameras
                or self.readers[camera_id]["version"] != cameras[camera_id]["updated_at"]
            ):
                self.retire(camera_id)
        for camera_id, camera in cameras.items():
            try:
                line = self.repository.line(camera_id)
                if camera_id in self.readers:
                    entry = self.readers[camera_id]
                    if entry["line"] != line:
                        entry["publisher"] = self.publisher_factory(camera, line)
                        entry["line"] = line
                    continue
                connection = self.cipher.decrypt(self.repository.connection(camera_id))
                reader = CameraReader(
                    camera,
                    connection,
                    self.repository,
                    self.config.vision_reconnect_max_seconds,
                    self.source_factory,
                )
                self.readers[camera_id] = {
                    "reader": reader,
                    "version": camera["updated_at"],
                    "line": line,
                    "publisher": self.publisher_factory(camera, line),
                }
                reader.thread.start()
            except Exception:
                entry = self.errors.setdefault(camera_id, {})
                log_failure(camera_id, entry)
                with suppress(Exception):
                    self.repository.status(camera_id, "OFFLINE")

    def tick(self) -> None:
        """Публикует только свежий последний кадр; сбой одной камеры не прерывает остальные."""
        for camera_id, entry in self.readers.items():
            if entry["reader"].stop.is_set():
                continue
            try:
                timestamp, frame, generation = entry["reader"].queue.get_nowait()
            except Empty:
                continue
            if (
                datetime.now(UTC) - timestamp
            ).total_seconds() > self.config.vision_frame_ttl_seconds:
                continue
            try:
                entry["publisher"].process(
                    frame,
                    timestamp,
                    f"{entry['reader'].session_id}:{generation}",
                )
            except Exception:
                log_failure(camera_id, entry)

    def shutdown(self) -> None:
        """Останавливает все декодеры и удаляет готовность процесса при SIGTERM."""
        for entry in self.readers.values():
            entry["reader"].stop.set()
        for camera_id in list(self.readers):
            self.retire(camera_id)
        self.frames.client.delete("warehouse:capture:ready")


def main() -> None:
    """Запускает CPU-захват для всех включённых камер независимо от VISION_ENABLED."""
    config = c.configuration()
    worker = CaptureWorker(
        c.camera_service().repository,
        c.cipher(),
        c.camera_source,
        c.capture_publisher,
        c.frames(),
        c.captured_frames(),
        config,
    )
    stop = threading.Event()

    def shutdown(signum, frame):
        """Запрашивает штатную остановку после сигнала Docker."""
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
            c.frames().client.setex("warehouse:capture:ready", 10, "1")
            stop.wait(1 / config.capture_fps)
    finally:
        worker.shutdown()
        close_old_connections()


if __name__ == "__main__":
    main()
