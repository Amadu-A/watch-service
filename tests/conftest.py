# tests/conftest.py
"""Изолированные fixtures; SQLite по умолчанию, PostgreSQL при container integration запуске."""

import os

os.environ.setdefault("DATABASE_ENGINE", "sqlite")
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")
os.environ.setdefault("CAMERA_CREDENTIALS_KEY", "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")

import pytest
from rest_framework.test import APIClient

from core import container as c


class FakeFrameCache:
    """Ephemeral fake с тем же get/put контрактом, без подключения к Redis."""

    def __init__(self):
        """Хранит тестовые кадры в памяти одного test case."""
        self.values = {}
        self.client = self

    def get(self, camera_id):
        """Возвращает только заранее положенный кадр."""
        return self.values.get(camera_id)

    def put(self, camera_id, jpeg):
        """Обновляет последний frame без persistence business state."""
        self.values[camera_id] = jpeg

    def ping(self):
        """Отмечает fake dependency доступной для readiness tests."""
        return True


@pytest.fixture(autouse=True)
def isolated_dependencies(monkeypatch, tmp_path):
    """Подменяет frame cache и media root, не меняя существующий приватный .env."""
    c.configuration.cache_clear()
    c.frames.cache_clear()
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    cache = FakeFrameCache()
    monkeypatch.setattr(c, "frames", lambda: cache)
    monkeypatch.setattr(c, "probe", lambda connection: True)
    yield cache
    c.configuration.cache_clear()


@pytest.fixture
def admin(db, django_user_model):
    """Создаёт администратора для API permission и CRUD сценариев."""
    return django_user_model.objects.create_user(
        username="admin", password="local-test-password", role="ADMINISTRATOR"
    )


@pytest.fixture
def client_api(admin):
    """Аутентифицирует test client штатным Django session context."""
    client = APIClient()
    client.force_authenticate(user=admin)
    return client


@pytest.fixture
def camera(client_api):
    """Регистрирует камеру только через внешний write contract."""
    response = client_api.post(
        "/api/v1/cameras",
        {
            "name": "Главный вход",
            "location": "Склад 1",
            "rtsp": {
                "url": "rtsp://10.0.0.25/stream1",
                "username": "camera-user",
                "password": "private-camera-password",
            },
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    return response.data["data"]
