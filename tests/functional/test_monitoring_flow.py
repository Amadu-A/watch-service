# tests/functional/test_monitoring_flow.py
"""Сквозной пользовательский путь от настройки камеры до кабинета наблюдения."""

import pytest


@pytest.mark.django_db
def test_administrator_configures_line_and_sees_saved_layout(client_api, client, admin, camera):
    """HTTP команды сохраняют линию и персональную сетку для открытого кабинета."""
    camera_id = camera["id"]
    line_url = f"/api/v1/cameras/{camera_id}/guard-line"
    line = {
        "start": {"x": 0.2, "y": 0.5},
        "end": {"x": 0.8, "y": 0.5},
        "direction": "ENTRY",
    }
    assert client_api.put(line_url, line, format="json").status_code == 200
    assert client_api.get(line_url).data["data"]["direction"] == "ENTRY"
    layout_url = "/api/v1/users/me/monitoring-layout"
    assert (
        client_api.put(
            layout_url, {"camera_ids": [camera_id], "grid": "1"}, format="json"
        ).status_code
        == 200
    )
    assert client_api.get(layout_url).data["data"]["camera_ids"] == [camera_id]
    client.force_login(admin)
    response = client.get("/monitoring/")
    assert response.status_code == 200
    assert b'data-page="monitoring"' in response.content
