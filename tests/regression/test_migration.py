# tests/regression/test_migration.py
"""Регрессии переноса Django-приложений и полного опубликованного исходника."""

import io
import tarfile
from pathlib import Path

from django.apps import apps

from infrastructure.source_archive import source_bytes
from persistence_app.models import Camera, Violation

ROOT = Path(__file__).resolve().parents[2]


def test_existing_database_labels_and_tables_are_stable():
    """Новая раскладка кода сохраняет имена таблиц и зависимости старых миграций."""
    assert apps.get_app_config("accounts").name == "accounts_app"
    assert apps.get_app_config("persistence").name == "persistence_app"
    assert Camera._meta.db_table == "persistence_camera"
    assert Violation._meta.db_table == "persistence_violation"


def test_source_download_contains_frontend_and_license():
    """Архив сборки содержит код кабинета и AGPL без временной копии legacy."""
    with tarfile.open(fileobj=io.BytesIO(source_bytes(ROOT)), mode="r:gz") as archive:
        names = set(archive.getnames())
    prefix = "warehouse-perimeter-watch/"
    assert prefix + "LICENSE" in names
    assert prefix + "Dockerfile" in names
    assert prefix + "compose.yaml" in names
    assert prefix + "templates/base.html" in names
    assert prefix + "static/css/style.css" in names
    assert prefix + "static/js/features/layout-state.js" in names
    assert prefix + "src/application/cameras/service.py" in names
    assert not any(name.startswith(prefix + "legacy/") for name in names)
