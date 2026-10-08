# src/modules/notifications/application/service.py
"""Уведомления с hard flags, durable outbox и bounded retry; HTTP клиентов здесь нет."""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from core.domain import Actor, BusinessError
from core.ports import Audit, MediaStorage, UnitOfWork
from core.timing import timed
from modules.notifications.application.ports import NotificationRepository, NotificationSender
from modules.violations.application.ports import ViolationRepository


class NotificationService:
    """Управляет настройками и заданиями; deployment flags нельзя обойти UI переключателями."""

    def __init__(
        self,
        repository: NotificationRepository,
        uow: UnitOfWork,
        audit: Audit,
        runtime_enabled: bool,
        channel_flags: dict[str, bool],
    ):
        """Получает неизменяемые process flags из composition root."""
        self.repository, self.uow, self.audit = repository, uow, audit
        self.runtime_enabled, self.channel_flags = runtime_enabled, channel_flags

    def settings(self, actor: Actor, data: dict | None = None) -> dict:
        """Разрешает подготовить settings при отключённой внешней отправке."""
        if data is not None:
            actor.require("ADMINISTRATOR")
            with self.uow.transaction():
                self.repository.settings(data)
                self.audit.record(actor.id, "notification_settings_update")
        return {
            **self.repository.settings(),
            "runtime_enabled": self.runtime_enabled,
            "email_runtime_enabled": self.channel_flags["EMAIL"],
            "telegram_runtime_enabled": self.channel_flags["TELEGRAM"],
        }

    def channels(self) -> set[str]:
        """Вычисляет разрешённые каналы по пересечению deployment и business flags."""
        settings = self.repository.settings()
        return {
            channel
            for channel in ("EMAIL", "TELEGRAM")
            if self.runtime_enabled
            and self.channel_flags[channel]
            and settings["global_enabled"]
            and settings[f"{channel.lower()}_enabled"]
        }

    def prepare(self, event_id) -> list[str]:
        """Создаёт durable поручения внутри транзакции создания нарушения."""
        return self.repository.prepare(event_id, self.channels())

    def recipients(self, actor: Actor) -> list[dict]:
        """Показывает recipients только администратору."""
        actor.require("ADMINISTRATOR")
        return self.repository.recipients()

    def recipient(self, actor: Actor, data: dict | None, recipient_id=None, delete=False) -> dict:
        """Проверяет адресат и атомарно записывает audit без текста target."""
        actor.require("ADMINISTRATOR")
        if not delete:
            if recipient_id:
                previous = next(
                    (
                        item
                        for item in self.repository.recipients()
                        if item["id"] == str(recipient_id)
                    ),
                    None,
                )
                if not previous:
                    raise BusinessError("recipient_not_found", "Получатель не найден.", 404)
                data = {**previous, **data}
            channel, target = data["channel"], data["target"].strip()
            valid = (channel == "EMAIL" and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", target)) or (
                channel == "TELEGRAM" and re.fullmatch(r"-?\d+|@[A-Za-z][A-Za-z0-9_]{4,}", target)
            )
            if not valid:
                raise BusinessError(
                    "invalid_recipient", "Укажите Email, chat_id или @имя Telegram-канала."
                )
            data = {
                key: data[key]
                for key in ("channel", "target", "display_name", "enabled")
                if key in data
            }
            data["target"] = target
        with self.uow.transaction():
            result = self.repository.recipient(recipient_id, data, delete)
            self.audit.record(
                actor.id, "recipient_delete" if delete else "recipient_save", result["id"]
            )
        return result

    def test(self, actor: Actor) -> dict:
        """Ставит тестовые delivery только при разрешённой deployment отправке."""
        actor.require("ADMINISTRATOR")
        channels = self.channels()
        if not channels:
            raise BusinessError(
                "notifications_disabled", "Отправка отключена конфигурацией или настройками.", 409
            )
        with self.uow.transaction():
            ids = self.repository.prepare(None, channels)
            self.audit.record(actor.id, "notification_test")
        return {"queued": len(ids)}

    def retry(self, actor: Actor, delivery_id) -> dict:
        """Возобновляет только failed/dead/skipped delivery после серверной проверки роли."""
        actor.require("OPERATOR")
        delivery = self.repository.delivery(delivery_id)
        if delivery["channel"] not in self.channels():
            raise BusinessError(
                "notifications_disabled", "Отправка отключена конфигурацией или настройками.", 409
            )
        with self.uow.transaction():
            self.repository.retry(delivery_id)
            self.audit.record(actor.id, "delivery_retry", str(delivery_id))
        return self.repository.delivery(delivery_id)

    def resend(self, actor: Actor, event: dict) -> dict:
        """Повторяет неуспешные доставки события без повторной отправки успешных."""
        actor.require("OPERATOR")
        if not self.channels():
            raise BusinessError("notifications_disabled", "Отправка отключена.", 409)
        count = 0
        for item in event["deliveries"]:
            if item["status"] in ("FAILED", "DEAD", "SKIPPED_DISABLED"):
                self.retry(actor, item["id"])
                count += 1
        return {"queued": count}

    def deliveries(self, actor: Actor, filters: dict) -> dict:
        """Пагинирует историю уведомлений для всех ролей с доступом к нарушениям."""
        items, total = self.repository.deliveries(filters)
        page, size = filters.get("page", 1), filters.get("page_size", 50)
        return {
            "data": items,
            "meta": {
                "page": page,
                "page_size": size,
                "total": total,
                "pages": (total + size - 1) // size,
            },
        }

    def delivery(self, actor: Actor, delivery_id) -> dict:
        """Выдаёт историю attempts без внешних секретных error messages."""
        return self.repository.delivery(delivery_id)


class DispatchNotification:
    """Обрабатывает delivery с row lock и повторной проверкой hard flags перед I/O."""

    def __init__(
        self,
        repository: NotificationRepository,
        settings: NotificationService,
        events: ViolationRepository,
        storage: MediaStorage,
        report_renderer,
        senders: dict[str, NotificationSender],
        max_attempts: int,
        timezone_provider,
    ):
        """Получает адаптеры каналов извне; не инициирует сетевые вызовы при создании."""
        self.repository, self.settings, self.events = repository, settings, events
        self.storage, self.report_renderer, self.senders = storage, report_renderer, senders
        self.max_attempts = max_attempts
        self.timezone_provider = timezone_provider

    @timed("dispatch_notification")
    def execute(self, delivery_id) -> None:
        """Сериализует concurrent задания и сохраняет каждый исход доставки."""
        with self.repository.lock(delivery_id):
            delivery = self.repository.delivery(delivery_id)
            if delivery["status"] not in ("PENDING", "QUEUED", "RETRYING"):
                return
            if delivery["channel"] not in self.settings.channels():
                self.repository.finish(delivery_id, "SKIPPED_DISABLED")
                return
            if delivery["attempt_count"] >= self.max_attempts:
                self.repository.finish(delivery_id, "DEAD", "max_attempts")
                return
            photo, report = None, None
            try:
                message = "Тестовое уведомление Warehouse Perimeter Watch."
                if delivery["violation_id"]:
                    event = self.events.get(delivery["violation_id"])
                    zone = self.timezone_provider()
                    detected = datetime.fromisoformat(event["detected_at"]).astimezone(
                        ZoneInfo(zone)
                    )
                    direction = (
                        "Вход на территорию"
                        if event["direction"] == "ENTRY"
                        else "Выход с территории"
                    )
                    message = (
                        f"Нарушение: {event['camera']['name']}\n"
                        f"{detected:%d.%m.%Y %H:%M:%S} ({zone})\n"
                        f"{direction}\nСобытие {event['id']}"
                    )
                    photo = self.storage.read(event["media_paths"]["annotated"])
                    report = self.report_renderer.pdf([event])
                self.senders[delivery["channel"]].send(delivery["target"], message, photo, report)
            except Exception:
                terminal = delivery["attempt_count"] + 1 >= self.max_attempts
                self.repository.finish(
                    delivery_id,
                    "DEAD" if terminal else "FAILED",
                    "send_failed",
                    retry_seconds=0 if terminal else min(3600, 30 * 2 ** delivery["attempt_count"]),
                )
                return
            self.repository.finish(delivery_id, "SENT")
