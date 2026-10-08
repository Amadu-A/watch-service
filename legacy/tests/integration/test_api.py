# tests/integration/test_api.py
"""Functional/API contracts: permissions, CSRF, credentials, layout, schedule, reports и errors."""

import io
import json
import tarfile
from uuid import uuid4

import pytest
from rest_framework.test import APIClient

from core import container as c
from modules.persistence.models import Camera, CameraCredential

pytestmark = pytest.mark.django_db


def test_camera_ciphertext_and_safe_api(client_api, camera):
    """Credentials encrypted at rest; GET не возвращает пароль, username или ciphertext."""
    record = CameraCredential.objects.get(camera_id=camera["id"])
    assert "private-camera-password" not in record.ciphertext
    assert c.cipher().decrypt(record.ciphertext)["password"] == "private-camera-password"
    content = json.dumps(client_api.get("/api/v1/cameras").data)
    for secret in ("private-camera-password", "camera-user", record.ciphertext):
        assert secret not in content
    assert client_api.post(f"/api/v1/cameras/{camera['id']}/test-connection").data["data"][
        "connected"
    ]


def test_auth_csrf_and_viewer_boundary(camera, admin, django_user_model):
    """Backend блокирует anonymous stream/media, viewer writes и session POST без CSRF."""
    client = APIClient(enforce_csrf_checks=True)
    assert client.get(f"/api/v1/cameras/{camera['id']}/stream.mjpeg").status_code == 403
    assert client.get(f"/api/v1/violations/{uuid4()}/media/original").status_code == 403
    client.force_login(admin)
    assert client.post("/api/v1/notifications/test").status_code == 403
    viewer = django_user_model.objects.create_user(username="viewer", role="VIEWER")
    client.force_authenticate(viewer)
    response = client.patch("/api/v1/system-settings", {"media_retention_days": 5}, format="json")
    assert response.status_code == 403
    assert response.data["error"]["code"] == "permission_denied"


def test_personal_layout_and_validation(client_api, camera, django_user_model):
    """Layout сохраняет порядок, отклоняет duplicates/unknown IDs и не общий для пользователей."""
    url = "/api/v1/users/me/monitoring-layout"
    assert (
        client_api.put(
            url, {"camera_ids": [camera["id"]], "grid": "auto"}, format="json"
        ).status_code
        == 200
    )
    assert client_api.get(url).data["data"]["camera_ids"] == [camera["id"]]
    assert (
        client_api.put(url, {"camera_ids": [camera["id"], camera["id"]]}, format="json").status_code
        == 400
    )
    assert client_api.put(url, {"camera_ids": [str(uuid4())]}, format="json").status_code == 404
    user = django_user_model.objects.create_user(username="another")
    client_api.force_authenticate(user)
    assert client_api.get(url).data["data"]["camera_ids"] == []


def test_guard_line_schedule_and_retention(client_api, camera):
    """Контракты line и schedule сохраняются; retention >30 и secret patch запрещены."""
    line = {"start": {"x": 0.2, "y": 0.5}, "end": {"x": 0.8, "y": 0.5}, "direction": "BOTH"}
    assert (
        client_api.put(
            f"/api/v1/cameras/{camera['id']}/guard-line", line, format="json"
        ).status_code
        == 200
    )
    line["end"] = line["start"]
    assert (
        client_api.put(
            f"/api/v1/cameras/{camera['id']}/guard-line", line, format="json"
        ).status_code
        == 400
    )
    schedule = {
        "timezone": "Europe/Moscow",
        "week": {"monday": [{"start": "19:00", "end": "08:00"}]},
    }
    assert client_api.put("/api/v1/control-schedule", schedule, format="json").status_code == 200
    assert (
        client_api.get("/api/v1/control-schedule").data["data"]["week"]["monday"]
        == schedule["week"]["monday"]
    )
    assert (
        client_api.patch(
            "/api/v1/system-settings", {"media_retention_days": 31}, format="json"
        ).status_code
        == 400
    )
    assert (
        client_api.patch(
            "/api/v1/system-settings", {"smtp_password": "forbidden"}, format="json"
        ).status_code
        == 400
    )


def test_notifications_hard_flag(client_api):
    """Business switches не разрешают внешнюю отправку при выключенном runtime flag."""
    response = client_api.patch(
        "/api/v1/notification-settings",
        {"global_enabled": True, "email_enabled": True, "telegram_enabled": True},
        format="json",
    )
    assert response.status_code == 200
    assert not response.data["data"]["runtime_enabled"]
    assert client_api.post("/api/v1/notifications/test").status_code == 409
    recipient = client_api.post(
        "/api/v1/notification-recipients",
        {"channel": "EMAIL", "target": "security@example.com"},
        format="json",
    )
    assert recipient.status_code == 201
    assert (
        client_api.patch(
            f"/api/v1/notification-recipients/{recipient.data['data']['id']}",
            {"display_name": "Дежурный"},
            format="json",
        ).status_code
        == 200
    )
    assert (
        client_api.post(
            "/api/v1/notification-recipients",
            {"channel": "EMAIL", "target": "security@example.com"},
            format="json",
        ).status_code
        == 409
    )


def test_errors_filters_and_schema(client_api):
    """Ошибки имеют request_id; invalid pagination и naïve filters не проходят в ORM."""
    response = client_api.get(f"/api/v1/cameras/{uuid4()}")
    assert response.status_code == 404
    assert response.data["error"]["request_id"] == response["X-Request-ID"]
    assert client_api.get("/api/v1/violations?page_size=10000").status_code == 400
    assert client_api.get("/api/v1/violations?date_from=2026-10-07T00:00:00").status_code == 400
    assert client_api.get("/api/schema/?format=json").status_code == 200
    assert client_api.get("/api/v1/cameras/invalid-uuid").data["error"]["code"] == "not_found"


def test_camera_stale_frame_and_protected_stream(client_api, camera, isolated_dependencies):
    """Протухший frame не остаётся LIVE; stream и отключение камеры соблюдают серверный доступ."""
    Camera.objects.filter(pk=camera["id"]).update(status="ONLINE")
    assert client_api.get(f"/api/v1/cameras/{camera['id']}").data["data"]["status"] == "OFFLINE"
    assert client_api.get(f"/api/v1/cameras/{camera['id']}/snapshot").status_code == 503
    isolated_dependencies.put(camera["id"], b"jpeg")
    assert client_api.get(f"/api/v1/cameras/{camera['id']}").data["data"]["status"] == "ONLINE"
    stream = client_api.get(f"/api/v1/cameras/{camera['id']}/stream.mjpeg")
    assert stream.status_code == 200
    assert b"Content-Type: image/jpeg" in next(iter(stream.streaming_content))
    stream.close()
    client_api.delete(f"/api/v1/cameras/{camera['id']}")
    assert client_api.get(f"/api/v1/cameras/{camera['id']}/snapshot").status_code == 503


@pytest.mark.parametrize(
    "path",
    [
        "/monitoring/",
        "/cameras/",
        "/violations/",
        "/reports/",
        "/notifications/",
        "/settings/",
        "/api/docs/",
    ],
)
def test_authenticated_html_pages(client, admin, path):
    """Все навигационные страницы доступны после session login."""
    client.force_login(admin)
    response = client.get(path)
    assert response.status_code == 200
    assert b'lang="ru"' in response.content


def test_source_download_is_authenticated_and_has_no_runtime_files(client, admin):
    """Пользователь получает исходники своей сборки без .env, media и моделей."""
    assert client.get("/source/").status_code == 302
    client.force_login(admin)
    response = client.get("/source/")
    assert response.status_code == 200
    with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as archive:
        names = archive.getnames()
        assert "warehouse-perimeter-watch/LICENSE" in names
        assert "warehouse-perimeter-watch/src/config/settings.py" in names
        assert "warehouse-perimeter-watch/.env" not in names
        assert all("/media/" not in name and "/models/" not in name for name in names)
