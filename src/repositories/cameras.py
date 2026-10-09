# src/repositories/cameras.py
"""Django ORM адаптер камер и линий с безопасным преобразованием в DTO."""

from django.utils import timezone

from domain.common import BusinessError
from persistence_app.models import Camera, CameraCredential, GuardLineRecord


def camera_dto(camera: Camera) -> dict:
    """Возвращает конфигурацию без credential relation и query string."""
    return {
        "id": str(camera.id),
        "name": camera.name,
        "location": camera.location,
        "enabled": camera.enabled,
        "status": camera.status,
        "rtsp_endpoint": camera.rtsp_url,
        "last_seen": camera.last_seen.isoformat() if camera.last_seen else None,
        "updated_at": camera.updated_at.isoformat(),
    }


class DjangoCameraRepository:
    """Сосредотачивает ORM и исключает утечку credentials в presentation layer."""

    def _get(self, camera_id) -> Camera:
        """Получает модель или преобразует DoesNotExist в предметную ошибку."""
        try:
            return Camera.objects.get(pk=camera_id)
        except Camera.DoesNotExist:
            raise BusinessError("camera_not_found", "Камера не найдена.", 404) from None

    def list(self) -> list[dict]:
        """Выдаёт список в стабильном порядке создания."""
        return [camera_dto(camera) for camera in Camera.objects.order_by("created_at")]

    def get(self, camera_id) -> dict:
        """Преобразует одну модель в безопасный DTO."""
        return camera_dto(self._get(camera_id))

    def save(self, camera_id, data: dict, encrypted: str | None) -> dict:
        """Сохраняет настройки; ciphertext никогда не включается в результат."""
        camera = self._get(camera_id) if camera_id else Camera()
        for key, value in data.items():
            setattr(camera, key, value)
        camera.status = "CONNECTING" if camera.enabled else "DISABLED"
        camera.save()
        if encrypted is not None:
            CameraCredential.objects.update_or_create(
                camera=camera, defaults={"ciphertext": encrypted}
            )
        return camera_dto(camera)

    def line(self, camera_id, data: dict | None = None) -> dict | None:
        """Хранит line snapshot отдельно от непубличных camera credentials."""
        camera = self._get(camera_id)
        if data is not None:
            line, _ = GuardLineRecord.objects.update_or_create(
                camera=camera, defaults={"configuration": data}
            )
            values = {**data, "id": str(line.id)}
            line.configuration = values
            line.save(update_fields=["configuration", "updated_at"])
            return values
        line = GuardLineRecord.objects.filter(camera=camera).first()
        return line.configuration if line else None

    def connection(self, camera_id) -> str:
        """Выдаёт encrypted blob только доверенному application worker."""
        self._get(camera_id)
        credential = CameraCredential.objects.filter(camera_id=camera_id).first()
        if not credential:
            raise BusinessError("credentials_missing", "Подключение камеры не настроено.", 409)
        return credential.ciphertext

    def status(self, camera_id, status: str) -> None:
        """Обновляет connection state без изменения версии конфигурации."""
        values = {"status": status}
        if status == "ONLINE":
            values["last_seen"] = timezone.now()
        Camera.objects.filter(pk=camera_id).update(**values)
