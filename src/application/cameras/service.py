# src/application/cameras/service.py
"""Операции камер и линий с permission check, шифрованием и аудитом."""

from dataclasses import asdict
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from application.cameras.ports import CameraRepository
from application.ports import Audit, CredentialCipher, LiveFrameCache, UnitOfWork
from core.timing import timed
from domain.common import Actor, BusinessError
from domain.surveillance.geometry import GuardLine, Point


class CameraService:
    """Координирует persistence камеры, не создавая ORM или сетевой клиент."""

    def __init__(
        self,
        repository: CameraRepository,
        cipher: CredentialCipher,
        uow: UnitOfWork,
        audit: Audit,
        frames: LiveFrameCache,
        probe,
    ):
        """Получает адаптеры из composition root; probe вызывается только по явному запросу."""
        self.repository, self.cipher = repository, cipher
        self.uow, self.audit, self.frames, self.probe = uow, audit, frames, probe

    def list(self, actor: Actor) -> list[dict]:
        """Показывает камеры всем авторизованным ролям, без login/password."""
        return [self._live_status(camera) for camera in self.repository.list()]

    def get(self, actor: Actor, camera_id) -> dict:
        """Возвращает безопасную карточку камеры."""
        return self._live_status(self.repository.get(camera_id))

    def _live_status(self, camera: dict) -> dict:
        """Не показывает ONLINE при истёкшем кадре, даже если worker не обновил DB status."""
        if camera["status"] == "ONLINE" and self.frames.get(camera["id"]) is None:
            return {**camera, "status": "OFFLINE"}
        return camera

    @timed("save_camera")
    def save(self, actor: Actor, data: dict, camera_id=None) -> dict:
        """Валидирует RTSP и сохраняет зашифрованные connection details атомарно."""
        actor.require("ADMINISTRATOR")
        if not camera_id and (not data.get("name") or "rtsp" not in data):
            raise BusinessError("invalid_camera", "Укажите название и RTSP-подключение.")
        values = {key: data[key] for key in ("name", "location", "enabled") if key in data}
        encrypted = None
        if "rtsp" in data:
            connection = data["rtsp"]
            try:
                parsed = urlsplit(connection["url"])
                if (
                    parsed.scheme not in ("rtsp", "rtsps")
                    or not parsed.hostname
                    or parsed.username
                    or parsed.password
                    or parsed.fragment
                ):
                    raise ValueError
                _ = parsed.port
            except (ValueError, KeyError, TypeError):
                raise BusinessError(
                    "invalid_rtsp", "Укажите RTSP URL без логина и пароля."
                ) from None
            encrypted = self.cipher.encrypt(connection)
            values["rtsp_url"] = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        with self.uow.transaction():
            result = self.repository.save(camera_id, values, encrypted)
            self.audit.record(
                actor.id, "camera_update" if camera_id else "camera_create", result["id"]
            )
        return result

    def disable(self, actor: Actor, camera_id) -> dict:
        """Деактивирует камеру с сохранением исторических нарушений."""
        return self.save(actor, {"enabled": False}, camera_id)

    def guard_line(self, actor: Actor, camera_id, data: dict | None = None) -> dict | None:
        """Читает либо сохраняет геометрию после предметной валидации."""
        if data is None:
            self.repository.get(camera_id)
            return self.repository.line(camera_id)
        actor.require("ADMINISTRATOR")
        previous = self.repository.line(camera_id)
        line = GuardLine(
            UUID(previous["id"]) if previous else uuid4(),
            Point(**data["start"]),
            Point(**data["end"]),
            data.get("inside_side", "left"),
            data.get("direction", "ENTRY"),
            data.get("min_confidence", 0.65),
            data.get("enabled", True),
        )
        values = asdict(line)
        values["id"] = str(line.id)
        with self.uow.transaction():
            result = self.repository.line(camera_id, values)
            self.audit.record(actor.id, "guard_line_update", str(camera_id))
        return result

    def snapshot(self, actor: Actor, camera_id) -> bytes:
        """Читает свежий JPEG; отсутствие кадра явно сообщает offline."""
        camera = self.repository.get(camera_id)
        frame = self.frames.get(str(camera_id)) if camera["enabled"] else None
        if frame is None:
            raise BusinessError("camera_offline", "Свежий кадр камеры недоступен.", 503)
        return frame

    @timed("camera_reconnect")
    def test(self, actor: Actor, camera_id) -> dict:
        """Проверяет получение одного кадра через внедрённый RTSP probe с timeout."""
        actor.require("ADMINISTRATOR")
        connection = self.cipher.decrypt(self.repository.connection(camera_id))
        return {"connected": self.probe(connection)}
