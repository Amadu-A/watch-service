# tests/integration/test_event_delivery.py
"""Регрессии транзакций evidence, outbox, доставки, отчётов и политики хранения."""

import io
import os
from datetime import timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.utils import timezone
from PIL import Image

from core import container as c
from core.domain import Actor, BusinessError
from modules.notifications.infrastructure.outbox import CeleryOutboxPublisher
from modules.persistence.models import (
    NotificationDelivery,
    NotificationOutbox,
    NotificationRecipient,
    Violation,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def event_command(camera):
    """Создаёт допустимую команду пересечения с неизменяемым снимком камеры."""
    return {
        "camera_id": camera["id"],
        "guard_line_id": None,
        "event_key": str(uuid4()),
        "track_id": 7,
        "direction": "ENTRY",
        "detected_at": timezone.now(),
        "confidence": 0.91,
        "bbox": [0.3, 0.2, 0.5, 0.7],
        "crossing_point": {"x": 0.4, "y": 0.5},
        "line_snapshot": {},
        "camera_snapshot": {"name": camera["name"], "location": "Склад"},
    }


@pytest.fixture
def jpeg():
    """Кодирует настоящий JPEG для PDF и защищённых media endpoints."""
    output = io.BytesIO()
    Image.new("RGB", (320, 180), "#15243a").save(output, "JPEG")
    return output.getvalue()


@pytest.fixture
def saved_event(event_command, jpeg):
    """Фиксирует нарушение штатным application use-case."""
    return c.create_violation().execute(event_command, jpeg, jpeg)


def enabled_dispatch():
    """Разрешает только fake Email adapter, не изменяя process feature flags."""
    dispatch = c.dispatch_notification()
    dispatch.settings.runtime_enabled = True
    dispatch.settings.channel_flags = {"EMAIL": True, "TELEGRAM": False}
    dispatch.repository.settings({"global_enabled": True, "email_enabled": True})
    sender = Mock()
    dispatch.senders = {"EMAIL": sender}
    return dispatch, sender


def test_event_idempotency_and_disabled_delivery(event_command, jpeg):
    """Повтор команды не дублирует событие, media или задания выключенных каналов."""
    NotificationRecipient.objects.create(channel="EMAIL", target="security@example.com")
    service = c.create_violation()
    first = service.execute(event_command, jpeg, jpeg)
    assert service.execute(event_command, jpeg, jpeg)["id"] == first["id"]
    assert Violation.objects.count() == 1
    assert Violation.objects.get().media.count() == 2
    assert NotificationDelivery.objects.get().status == "SKIPPED_DISABLED"
    assert not NotificationOutbox.objects.exists()


def test_enabled_event_creates_outbox_in_same_transaction(event_command, jpeg):
    """Разрешённый Email получает PENDING/outbox; отключённый Telegram сохраняет skipped state."""
    creator = c.create_violation()
    creator.notifications.runtime_enabled = True
    creator.notifications.channel_flags = {"EMAIL": True, "TELEGRAM": False}
    creator.notifications.repository.settings(
        {"global_enabled": True, "email_enabled": True, "telegram_enabled": True}
    )
    NotificationRecipient.objects.create(channel="EMAIL", target="a@example.com")
    NotificationRecipient.objects.create(channel="TELEGRAM", target="123456789")
    event = creator.execute(event_command, jpeg, jpeg)
    statuses = dict(
        NotificationDelivery.objects.filter(violation_id=event["id"]).values_list(
            "channel", "status"
        )
    )
    assert statuses == {"EMAIL": "PENDING", "TELEGRAM": "SKIPPED_DISABLED"}
    assert NotificationOutbox.objects.filter(delivery__violation_id=event["id"]).count() == 1


def test_csv_escapes_spreadsheet_formula_prefix(saved_event):
    """Имя камеры не превращается в формулу при открытии выгруженного CSV."""
    event = {**saved_event, "camera": {**saved_event["camera"], "name": '=HYPERLINK("bad")'}}
    content = c.renderer().csv([event]).decode("utf-8-sig")
    assert "'=HYPERLINK" in content


@pytest.mark.parametrize("failure", ["storage", "outbox"])
def test_failed_event_compensates_files_and_database(event_command, jpeg, monkeypatch, failure):
    """Сбой второго файла или outbox откатывает metadata и удаляет уже записанные файлы."""
    service = c.create_violation()
    if failure == "storage":
        write = service.storage.write

        def broken_write(path, content):
            """Имитирует заполненный диск на втором доказательстве."""
            if "annotated" in path:
                raise OSError("disk_full")
            write(path, content)

        monkeypatch.setattr(service.storage, "write", broken_write)
    else:
        monkeypatch.setattr(service.notifications, "prepare", Mock(side_effect=RuntimeError("db")))
    with pytest.raises((OSError, RuntimeError)):
        service.execute(event_command, jpeg, jpeg)
    assert not Violation.objects.exists()
    assert not list(service.storage.root.rglob("*.jpg"))


def test_outbox_survives_broker_failure():
    """Недоступность RabbitMQ сохраняет неопубликованное поручение для следующего цикла."""
    delivery = NotificationDelivery.objects.create(channel="EMAIL", target="a@example.com")
    outbox = NotificationOutbox.objects.create(delivery=delivery)
    task = Mock()
    task.apply_async.side_effect = ConnectionError("broker_offline")
    with pytest.raises(ConnectionError):
        CeleryOutboxPublisher(task).pump()
    outbox.refresh_from_db()
    delivery.refresh_from_db()
    assert outbox.published_at is None and delivery.status == "PENDING"
    task.apply_async.side_effect = None
    assert CeleryOutboxPublisher(task).pump() == 1
    delivery.refresh_from_db()
    assert delivery.status == "QUEUED"


@pytest.mark.regression
def test_stale_queued_outbox_is_published_again():
    """Потерянное consumer задание QUEUED восстанавливается по тому же delivery UUID."""
    delivery = NotificationDelivery.objects.create(
        channel="EMAIL", target="a@example.com", status="QUEUED"
    )
    NotificationOutbox.objects.create(
        delivery=delivery, published_at=timezone.now() - timedelta(minutes=6)
    )
    task = Mock()
    assert CeleryOutboxPublisher(task).pump() == 1
    task.apply_async.assert_called_once_with(
        args=[str(delivery.id)], queue="warehouse.notifications", retry=False
    )


def test_dispatch_idempotency_and_gate():
    """Повтор UUID после SENT не вызывает sender; hard flag проверяется перед I/O."""
    dispatch, sender = enabled_dispatch()
    delivery = NotificationDelivery.objects.create(
        channel="EMAIL", target="a@example.com", status="QUEUED"
    )
    dispatch.execute(delivery.id)
    dispatch.execute(delivery.id)
    sender.send.assert_called_once()
    delivery.refresh_from_db()
    assert delivery.status == "SENT" and delivery.attempts.count() == 1
    gated = NotificationDelivery.objects.create(channel="EMAIL", target="b@example.com")
    dispatch.settings.runtime_enabled = False
    dispatch.execute(gated.id)
    gated.refresh_from_db()
    assert gated.status == "SKIPPED_DISABLED"
    assert sender.send.call_count == 1


def test_retry_backoff_dead_state_and_safe_error():
    """Отказы ограничены числом попыток; текст исключения с секретом не попадает в БД."""
    dispatch, sender = enabled_dispatch()
    dispatch.max_attempts = 2
    sender.send.side_effect = RuntimeError("private-token-should-not-leak")
    delivery = NotificationDelivery.objects.create(channel="EMAIL", target="a@example.com")
    outbox = NotificationOutbox.objects.create(delivery=delivery)
    dispatch.execute(delivery.id)
    delivery.refresh_from_db()
    assert delivery.status == "FAILED" and delivery.next_attempt_at > timezone.now()
    NotificationDelivery.objects.filter(pk=delivery.id).update(
        next_attempt_at=timezone.now() - timedelta(seconds=1)
    )
    assert CeleryOutboxPublisher(Mock()).pump() == 1
    outbox.refresh_from_db()
    assert outbox.published_at is not None
    dispatch.execute(delivery.id)
    delivery.refresh_from_db()
    assert delivery.status == "DEAD" and delivery.attempt_count == 2
    dispatch.execute(delivery.id)
    assert sender.send.call_count == 2
    assert "private-token" not in str(list(delivery.attempts.values()))


def test_manual_retry_preserves_history_and_rejects_sent(admin):
    """Новый ручной цикл сохраняет предыдущие attempts и закрывает retry успешной доставки."""
    dispatch, sender = enabled_dispatch()
    delivery = NotificationDelivery.objects.create(channel="EMAIL", target="a@example.com")
    sender.send.side_effect = RuntimeError("failure")
    dispatch.execute(delivery.id)
    dispatch.settings.retry(Actor(admin.id, "ADMINISTRATOR"), delivery.id)
    sender.send.side_effect = None
    dispatch.execute(delivery.id)
    assert delivery.attempts.count() == 2
    with pytest.raises(BusinessError, match="Повторная"):
        dispatch.settings.retry(Actor(admin.id, "ADMINISTRATOR"), delivery.id)


def test_evidence_pdf_report_history_and_ownership(client_api, saved_event, django_user_model):
    """Кириллица и фото входят в PDF; чужой пользователь не получает персональный отчёт."""
    event_id = saved_event["id"]
    original = client_api.get(f"/api/v1/violations/{event_id}/media/original")
    assert original.status_code == 200 and original["Cache-Control"] == "no-store"
    pdf = client_api.get(f"/api/v1/violations/{event_id}/report.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
    assert b"/Subtype /Image" in pdf.content and b"/FontFile2" in pdf.content
    result = client_api.post("/api/v1/reports", {"format": "CSV", "filters": {}}, format="json")
    assert result.status_code == 201, result.data
    report_id = result.data["data"]["id"]
    csv = client_api.get(f"/api/v1/reports/{report_id}/download")
    assert saved_event["camera"]["name"] in csv.content.decode("utf-8-sig")
    another = django_user_model.objects.create_user(username="another-report-owner")
    client_api.force_authenticate(another)
    assert client_api.get(f"/api/v1/reports/{report_id}/download").status_code == 404


def test_dispatch_sends_evidence_pdf_and_local_timestamp(saved_event):
    """Уведомление содержит название, направление, local time и настоящие JPEG/PDF."""
    dispatch, sender = enabled_dispatch()
    delivery = NotificationDelivery.objects.create(
        violation_id=saved_event["id"], channel="EMAIL", target="a@example.com"
    )
    dispatch.execute(delivery.id)
    target, text, photo, pdf = sender.send.call_args.args
    assert target == "a@example.com" and "Europe/Moscow" in text
    assert "Главный вход" in text and "Вход на территорию" in text
    assert photo.startswith(b"\xff\xd8") and pdf.startswith(b"%PDF-")


def test_retention_deletes_old_evidence_and_orphans(saved_event, event_command, jpeg):
    """Событие старше 30 дней и orphan удаляются; свежие evidence сохраняются."""
    root = c.storage().root
    old_time = timezone.now() - timedelta(days=31)
    Violation.objects.filter(pk=saved_event["id"]).update(detected_at=old_time)
    new_event = c.create_violation().execute(
        {**event_command, "event_key": str(uuid4())}, jpeg, jpeg
    )
    c.storage().write("orphans/crash.jpg", jpeg)
    os.utime(root / "orphans/crash.jpg", (old_time.timestamp(), old_time.timestamp()))
    result = c.retention_cleaner().execute()
    assert result["events_deleted"] == 1 and result["orphans_deleted"] == 1
    assert not Violation.objects.filter(pk=saved_event["id"]).exists()
    for path in saved_event["media_paths"].values():
        assert not (root / path).exists()
    for path in new_event["media_paths"].values():
        assert (root / path).is_file()


def test_retention_storage_failure_keeps_metadata(saved_event, monkeypatch):
    """Неудаляемый файл сохраняет metadata для повторной очистки после восстановления диска."""
    Violation.objects.filter(pk=saved_event["id"]).update(
        detected_at=timezone.now() - timedelta(days=31)
    )
    cleaner = c.retention_cleaner()
    monkeypatch.setattr(cleaner.storage, "delete", Mock(side_effect=OSError("disk")))
    with pytest.raises(OSError):
        cleaner.execute()
    assert Violation.objects.filter(pk=saved_event["id"]).exists()


def test_media_storage_rejects_path_escape():
    """Путь из БД также проверяется: выход из project volume невозможен."""
    with pytest.raises(BusinessError):
        c.storage().read("../outside.jpg")
