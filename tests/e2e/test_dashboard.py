# tests/e2e/test_dashboard.py
"""Браузерные сценарии настоящего Django UI с session auth и CSRF, без внешних отправок."""

import io
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from time import sleep
from uuid import uuid4

import pytest
from PIL import Image
from playwright.sync_api import expect, sync_playwright

from core import container as c

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        os.environ.get("RUN_E2E") != "true", reason="Запуск через watch.sh e2e/local-check"
    ),
]


@pytest.fixture
def page(live_server, admin, camera):
    """Открывает Chromium и выполняет обычный login с проверкой отсутствия ошибок JavaScript."""
    errors = []
    image = io.BytesIO()
    Image.new("RGB", (320, 180), "#15243a").save(image, "JPEG")
    event = c.create_violation().execute(
        {
            "camera_id": camera["id"],
            "guard_line_id": None,
            "event_key": str(uuid4()),
            "track_id": 1,
            "direction": "ENTRY",
            "detected_at": datetime.now(UTC),
            "confidence": 0.91,
            "bbox": [0.3, 0.2, 0.5, 0.7],
            "crossing_point": {"x": 0.4, "y": 0.5},
            "line_snapshot": {},
            "camera_snapshot": {"name": camera["name"], "location": "Склад"},
        },
        image.getvalue(),
        image.getvalue(),
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel="chromium")
        context = browser.new_context(
            viewport={"width": 1536, "height": 1024}, locale="ru-RU", timezone_id="Europe/Moscow"
        )
        page = context.new_page()
        page.test_event_id = event["id"]
        page.test_event_time = event["detected_at"]
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(live_server.url + "/login/")
        page.locator('[name="username"]').fill(admin.username)
        page.locator('[name="password"]').fill("local-test-password")
        page.get_by_role("button", name="Войти", exact=True).click()
        page.wait_for_url("**/monitoring/")
        yield page
        context.close()
        browser.close()
    assert errors == []


def slow_initial_request(page, path):
    """Искусственно задерживает первый API-ответ для проверки раннего взаимодействия."""

    def delay(route):
        sleep(0.4)
        route.continue_()

    page.route(f"**{path}", delay, times=1)


def test_camera_line_and_persistent_monitoring_layout(page, camera, live_server):
    """Регистрация, линия, RTSP probe, selection, порядок и сетка проходят через реальные формы."""
    slow_initial_request(page, "/api/v1/cameras")
    page.goto(live_server.url + "/cameras/")
    form = page.locator("[data-camera-create]")
    form.locator('[name="name"]').fill("Боковой вход")
    form.locator('[name="url"]').fill("rtsp://192.0.2.11/stream1")
    form.get_by_role("button", name="Зарегистрировать камеру", exact=True).click()
    page.wait_for_url(re.compile(r"/cameras/[0-9a-f-]+/$"))
    line = page.locator("[data-line-form]")
    expect(line.locator('button[type="submit"]')).to_be_enabled()
    for field, value in {
        "start_x": "0.2",
        "start_y": "0.5",
        "end_x": "0.8",
        "end_y": "0.5",
    }.items():
        line.locator(f'[name="{field}"]').fill(value)
    line.get_by_role("button", name="Сохранить линию").click()
    expect(page.locator("[data-toast]")).to_have_text("Контрольная линия сохранена.")
    page.reload()
    expect(line.locator('[name="start_x"]')).to_have_value("0.2")
    page.get_by_role("button", name="Проверить RTSP").click()
    expect(page.locator("[data-toast]")).to_have_text("RTSP: кадр получен.")
    page.goto(live_server.url + "/monitoring/")
    selector = page.locator("[data-camera-selector]")
    for index, name in enumerate(("Главный вход", "Боковой вход"), start=1):
        expect(selector.get_by_role("option", name=name, exact=True)).to_have_count(1)
        selector.select_option(label=name)
        page.locator("[data-add-camera-form] button[type=submit]").click()
        expect(page.locator("[data-camera-grid] .camera-card")).to_have_count(index)
    cards = page.locator("[data-camera-grid] .camera-card")
    expect(cards).to_have_count(2)
    expect(cards.first.locator(".camera-card__offline")).to_be_visible()
    page.get_by_role("button", name="Поднять Боковой вход", exact=True).click()
    expect(cards.first.locator("h2")).to_have_text("Боковой вход")
    page.locator("[data-grid-fullscreen]").click()
    expect(page.locator("[data-camera-grid]")).to_have_js_property("offsetWidth", 1536)
    page.keyboard.press("Escape")
    page.locator("[data-grid]").select_option("3")
    page.reload()
    expect(page.locator("[data-grid]")).to_have_value("3")
    expect(cards.first.locator("h2")).to_have_text("Боковой вход")
    Path("test-results").mkdir(exist_ok=True)
    page.screenshot(path="test-results/monitoring.png", full_page=True)
    page.get_by_role("button", name="Убрать Главный вход", exact=True).click()
    expect(cards).to_have_count(1)


def test_notification_recipients_and_hard_flag(page, live_server):
    """Получатель редактируется и удаляется; business switch не разблокирует тестовую отправку."""
    slow_initial_request(page, "/api/v1/notification-settings")
    page.goto(live_server.url + "/notifications/")
    form = page.locator("[data-recipient-form]")
    form.locator('[name="target"]').fill("security@example.com")
    form.get_by_role("button", name="Сохранить получателя").click()
    row = page.locator("[data-recipients] li")
    expect(row).to_have_count(1)
    row.get_by_role("button", name="Изменить").click()
    form.locator('[name="target"]').fill("night@example.com")
    form.get_by_role("button", name="Сохранить получателя").click()
    expect(row).to_contain_text("night@example.com")
    settings = page.locator("[data-notification-settings]")
    settings.locator('[name="global_enabled"]').check()
    settings.locator('[name="email_enabled"]').check()
    settings.get_by_role("button", name="Сохранить настройки", exact=True).click()
    expect(page.locator("[data-notification-test]")).to_be_disabled()
    expect(page.locator("[data-runtime-notice]")).to_contain_text("Отключено конфигурацией")
    row.get_by_role("button", name="Удалить").click()
    expect(row).to_have_count(0)


def test_schedule_retention_report_and_logout(page, live_server):
    """Ночной интервал и retention переживают reload; CSV скачивается, logout закрывает кабинет."""
    slow_initial_request(page, "/api/v1/control-schedule")
    page.goto(live_server.url + "/settings/")
    schedule = page.locator("[data-schedule-form]")
    page.locator("[data-interval-add]").click()
    row = schedule.locator("[data-interval]").last
    row.locator('[name="weekday"]').select_option("monday")
    row.locator('[name="start"]').fill("19:00")
    row.locator('[name="end"]').fill("08:00")
    schedule.get_by_role("button", name="Сохранить", exact=True).click()
    expect(page.locator("[data-toast]")).to_have_text("Расписание сохранено.")
    page.reload()
    expect(schedule.locator('[data-interval] [name="end"]')).to_have_value("08:00")
    system = page.locator("[data-system-settings]")
    expect(system.locator('[name="media_retention_days"]')).to_have_value("30")
    system.locator('[name="media_retention_days"]').fill("10")
    system.get_by_role("button", name="Сохранить", exact=True).click()
    expect(page.locator("[data-toast]")).to_have_text("Настройки объекта сохранены.")
    page.reload()
    expect(system.locator('[name="media_retention_days"]')).to_have_value("10")
    page.goto(live_server.url + "/reports/")
    form = page.locator("[data-report-form]")
    form.locator('[name="format"]').select_option("CSV")
    form.get_by_role("button", name="Сформировать отчёт").click()
    download_link = page.get_by_role("link", name="Скачать отчёт")
    expect(download_link).to_have_count(1)
    with page.expect_download() as information:
        download_link.click()
    download = information.value
    assert download.suggested_filename.endswith(".csv")
    assert "Камера" in Path(download.path()).read_text(encoding="utf-8-sig")
    page.locator(".header__account summary").click()
    page.get_by_role("button", name="Выйти", exact=True).click()
    page.wait_for_url("**/login/")
    page.goto(live_server.url + "/monitoring/")
    expect(page).to_have_url(re.compile(r"/login/\?next="))


def test_violation_details_media_and_pdf(page, live_server):
    """История открывает событие, настоящие JPEG и загружаемый PDF с изображением."""
    page.goto(live_server.url + "/violations/")
    page.locator(f'a[href="/violations/{page.test_event_id}/"]').first.click()
    page.wait_for_url(f"**/violations/{page.test_event_id}/")
    expect(page.locator("[data-event-details]")).to_contain_text("Главный вход")
    photo = page.locator("[data-event-photos] img").first
    expect(photo).to_be_visible()
    expect(photo).to_have_js_property("naturalWidth", 320)
    with page.expect_download() as information:
        page.get_by_role("link", name="Скачать PDF отчёт").click()
    assert Path(information.value.path()).read_bytes().startswith(b"%PDF-")


def test_object_timezone_is_ready_before_history(page, live_server):
    """Первый рендер истории использует выбранную зону объекта, независимо от browser timezone."""
    page.goto(live_server.url + "/settings/")
    schedule = page.locator("[data-schedule-form]")
    expect(schedule.locator('[name="timezone"]')).to_have_value("Europe/Moscow")
    schedule.locator('[name="timezone"]').select_option("Europe/Berlin")
    schedule.get_by_role("button", name="Сохранить", exact=True).click()
    expect(page.locator("[data-toast]")).to_have_text("Расписание сохранено.")
    page.goto(live_server.url + f"/violations/{page.test_event_id}/")
    expected = page.evaluate(
        "value => new Intl.DateTimeFormat('ru-RU', "
        "{dateStyle:'short', timeStyle:'medium', timeZone:'Europe/Berlin'})"
        ".format(new Date(value))",
        page.test_event_time,
    )
    expect(page.locator("[data-event-details]")).to_contain_text(expected)
