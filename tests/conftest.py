# tests/conftest.py
"""
Общие фикстуры автоматических тестов Warehouse Perimeter Watch.

Bootstrap-тесты выполняются без подключения к внешним сервисам.
Для существующих unit, integration, architecture
и E2E тестов сохраняются прежние fixtures и их поведение.

Фикстуры используют единый composition root из новой структуры.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from rest_framework.test import APIClient

os.environ.setdefault("DATABASE_ENGINE", "sqlite")
os.environ.setdefault(
    "DJANGO_ALLOWED_HOSTS",
    "localhost,127.0.0.1,testserver",
)
os.environ.setdefault(
    "CAMERA_CREDENTIALS_KEY",
    "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
)

TESTS_ROOT = Path(__file__).resolve().parent


class FakeFrameCache:
    """Хранит тестовые кадры в памяти без подключения к Redis."""

    def __init__(self) -> None:
        """Создаёт независимое хранилище тестовых кадров."""
        self.values: dict = {}
        self.client = self

    def get(self, camera_id):
        """Возвращает кадр камеры, если он был сохранён фикстурой."""
        return self.values.get(camera_id)

    def put(self, camera_id, jpeg) -> None:
        """Сохраняет последний тестовый кадр камеры."""
        self.values[camera_id] = jpeg

    def ping(self) -> bool:
        """Подтверждает доступность fake-зависимости."""
        return True


@pytest.fixture(autouse=True)
def isolated_dependencies(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """
    Изолирует инфраструктуру каждого теста.

    Корневые bootstrap-тесты не создают адаптеры.
    В остальных тестах сохраняются исторические подмены Redis,
    RTSP probe, media storage и process configuration.
    """
    if request.node.path.parent == TESTS_ROOT:
        yield FakeFrameCache()
        return

    from core import container as c

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
    """
    Создаёт администратора для тестирования API.

    Использует перенесённую custom user model с меткой accounts.
    """
    return django_user_model.objects.create_user(
        username="admin",
        password="local-test-password",
        role="ADMINISTRATOR",
    )


@pytest.fixture
def client_api(admin):
    """Создаёт авторизованный DRF-клиент с правами тестового администратора."""
    client = APIClient()
    client.force_authenticate(user=admin)
    return client


@pytest.fixture
def camera(client_api):
    """
    Создаёт тестовую камеру через публичный API.

    Проверяет создание камеры через HTTP-контракт, а не прямую
    запись ORM. Фикстура заработает после переноса camera API.
    """
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
