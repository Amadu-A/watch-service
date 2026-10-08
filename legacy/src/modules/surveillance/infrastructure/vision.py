# src/modules/surveillance/infrastructure/vision.py
"""OpenCV RTSP, resident YOLO detector, отдельный ByteTrack каждой камеры и JPEG разметка."""

import io
import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote, urlsplit, urlunsplit

from PIL import Image, ImageDraw, ImageFont


def connection_url(connection: dict) -> str:
    """Добавляет percent-encoded userinfo только внутри RTSP infrastructure adapter."""
    parsed = urlsplit(connection["url"])
    user, password = connection.get("username", ""), connection.get("password", "")
    auth = f"{quote(user, safe='')}:{quote(password, safe='')}@" if user or password else ""
    return urlunsplit((parsed.scheme, auth + parsed.netloc, parsed.path, parsed.query, ""))


def probe_rtsp(connection: dict) -> bool:
    """Проверяет один кадр через FFmpeg без YOLO/OpenCV и без вывода credentials."""
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-loglevel",
                "quiet",
                "-rtsp_transport",
                "tcp",
                "-i",
                connection_url(connection),
                "-frames:v",
                "1",
                "-f",
                "null",
                "-",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=12,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class RTSPCameraSource:
    """Decoder с timeout и явным close; внешние capture errors не логируются с URL."""

    def __init__(self, connection: dict):
        """Открывает поток через FFmpeg TCP; timeout исключает вечный reconnect."""
        import cv2

        cv2.setLogLevel(0)
        os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "-8")
        os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
        self.capture = cv2.VideoCapture(
            connection_url(connection),
            cv2.CAP_FFMPEG,
            [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000],
        )

    def read(self):
        """Возвращает decoded BGR frame или None при отсутствии stream."""
        success, frame = self.capture.read()
        return frame if success else None

    def close(self) -> None:
        """Освобождает handle decoder независимо от состояния других камер."""
        self.capture.release()


class UltralyticsPersonDetector:
    """Создаёт одну YOLO model на worker и явно использует deployment device."""

    def __init__(self, model_path: str, device: str):
        """Загружает локальные weights один раз, без скачивания при inference."""
        from ultralytics import YOLO

        if not Path(model_path).is_file():
            raise RuntimeError("vision_model_missing")
        self.model, self.device = YOLO(model_path), device

    def detect(self, frame):
        """Возвращает person boxes; ByteTrack получает CPU numpy representation."""
        result = self.model.predict(
            frame, classes=[0], conf=0.1, device=self.device, verbose=False
        )[0]
        return result.boxes.cpu().numpy()


class ByteTrackTracker:
    """Содержит track state одной камеры, никогда не разделяемый между потоками."""

    def __init__(self, fps: int):
        """Создаёт tracker с ограниченным track_buffer."""
        from ultralytics.trackers.basetrack import BaseTrack
        from ultralytics.trackers.byte_tracker import BYTETracker

        previous_count = BaseTrack._count
        self.tracker = BYTETracker(
            SimpleNamespace(
                track_high_thresh=0.25,
                track_low_thresh=0.1,
                new_track_thresh=0.25,
                track_buffer=6 * fps,
                match_thresh=0.8,
                fuse_score=True,
            )
        )
        # Конструктор Ultralytics сбрасывает общий счётчик: сохраняем ID существующих камер.
        BaseTrack._count = max(previous_count, BaseTrack._count)

    def update(self, detections, frame) -> list[dict]:
        """Преобразует x1,y1,x2,y2,id,score,class,index в нормализованные DTO."""
        height, width = frame.shape[:2]
        result = []
        for values in self.tracker.update(detections, frame):
            if int(values[6]) != 0:
                continue
            result.append(
                {
                    "track_id": int(values[4]),
                    "confidence": float(values[5]),
                    "bbox": [
                        max(0.0, min(1.0, float(v) / (width if index % 2 == 0 else height)))
                        for index, v in enumerate(values[:4])
                    ],
                }
            )
        return result


class OpenCVFrameRenderer:
    """Рисует Unicode label через Pillow и кодирует JPEG/MP4 без изменения исходного frame."""

    def __init__(self, font_path: str = ""):
        """Подбирает Unicode font контейнера или Windows для camera labels."""
        candidates = [
            font_path,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]
        path = next((item for item in candidates if item and Path(item).is_file()), None)
        self.font = ImageFont.truetype(path, 18) if path else ImageFont.load_default()

    def original(self, frame) -> bytes:
        """Кодирует оригинальный BGR frame без bbox и линий."""
        import cv2

        success, content = cv2.imencode(".jpg", frame)
        if not success:
            raise RuntimeError("jpeg_encoding_failed")
        return content.tobytes()

    def annotated(self, frame, tracks: list[dict], line: dict | None, label: str) -> bytes:
        """Добавляет line, bbox, confidence и русскоязычный camera/timestamp label."""
        image = Image.fromarray(frame[:, :, ::-1])
        draw = ImageDraw.Draw(image)
        width, height = image.size
        if line and line.get("enabled"):
            points = [(line[key]["x"] * width, line[key]["y"] * height) for key in ("start", "end")]
            draw.line(points, fill="#ff5262", width=3)
            for x, y in points:
                draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill="#ff5262")
        for track in tracks:
            x1, y1, x2, y2 = [
                value * (width if index % 2 == 0 else height)
                for index, value in enumerate(track["bbox"])
            ]
            draw.rectangle((x1, y1, x2, y2), outline="#ff5262", width=2)
            draw.text(
                (x1, max(30, y1 - 22)),
                f"person {track['confidence']:.2f} #{track['track_id']}",
                font=self.font,
                fill="#ff5262",
            )
        draw.rectangle((0, 0, width, 28), fill="#111924")
        draw.text((8, 3), label, font=self.font, fill="white")
        content = io.BytesIO()
        image.save(content, "JPEG", quality=80)
        return content.getvalue()

    def clip(self, frames: list, fps: int) -> bytes | None:
        """Создаёт короткий MP4; ошибки codec возвращают None и не блокируют JPEG evidence."""
        import cv2

        if not frames:
            return None
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as file:
            path = Path(file.name)
        browser_path = path.with_name(path.stem + "-browser.mp4")
        writer = None
        try:
            height, width = frames[0].shape[:2]
            writer = cv2.VideoWriter(
                str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
            )
            if not writer.isOpened():
                return None
            for frame in frames:
                writer.write(frame)
            writer.release()
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-loglevel",
                    "quiet",
                    "-y",
                    "-i",
                    str(path),
                    "-an",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "25",
                    "-vf",
                    "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    str(browser_path),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
            return browser_path.read_bytes() if result.returncode == 0 else None
        except Exception:
            return None
        finally:
            if writer:
                writer.release()
            path.unlink(missing_ok=True)
            browser_path.unlink(missing_ok=True)
