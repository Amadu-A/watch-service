# src/persistence_app/models.py
"""Persistence-модели модульного монолита; ORM доступен только инфраструктурным адаптерам."""

import uuid

from django.conf import settings
from django.db import models


class UUIDRecord(models.Model):
    """Общие UUID и дата создания для технических записей проекта."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Отключает самостоятельную таблицу базового класса."""

        abstract = True


class Camera(UUIDRecord):
    """Несекретная конфигурация камеры; endpoint никогда не содержит userinfo."""

    name = models.CharField(max_length=150)
    location = models.CharField(max_length=250, blank=True)
    enabled = models.BooleanField(default=True)
    status = models.CharField(max_length=16, default="CONNECTING")
    rtsp_url = models.CharField(max_length=1000)
    updated_at = models.DateTimeField(auto_now=True)
    last_seen = models.DateTimeField(null=True)


class CameraCredential(models.Model):
    """Зашифрованные login/password камеры, отдельные от API-представления."""

    camera = models.OneToOneField(Camera, primary_key=True, on_delete=models.CASCADE)
    ciphertext = models.TextField()


class GuardLineRecord(UUIDRecord):
    """Версия контрольной линии; событие дополнительно хранит её snapshot."""

    camera = models.OneToOneField(Camera, on_delete=models.CASCADE, related_name="guard_line")
    configuration = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)


class MonitoringLayout(models.Model):
    """Персональный порядок камер и плотность сетки текущего пользователя."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, primary_key=True, on_delete=models.CASCADE
    )
    camera_ids = models.JSONField(default=list)
    grid = models.CharField(max_length=8, default="auto")


class ControlSchedule(models.Model):
    """Единое недельное расписание объекта; singleton хранится под ключом 1."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    timezone = models.CharField(max_length=64, default="Europe/Moscow")
    enabled = models.BooleanField(default=True)


class ControlScheduleInterval(UUIDRecord):
    """Интервал дня начала; ночной остаток вычисляет domain SchedulePolicy."""

    schedule = models.ForeignKey(
        ControlSchedule, on_delete=models.CASCADE, related_name="intervals"
    )
    weekday = models.PositiveSmallIntegerField()
    start = models.CharField(max_length=5)
    end = models.CharField(max_length=5)


class Violation(UUIDRecord):
    """Неизменяемое событие crossing с уникальным ключом дедупликации."""

    camera = models.ForeignKey(Camera, on_delete=models.PROTECT)
    guard_line = models.ForeignKey(GuardLineRecord, null=True, on_delete=models.SET_NULL)
    event_key = models.CharField(max_length=250, unique=True)
    track_id = models.PositiveBigIntegerField()
    direction = models.CharField(max_length=8)
    detected_at = models.DateTimeField(db_index=True)
    confidence = models.FloatField()
    bbox = models.JSONField()
    crossing_point = models.JSONField()
    line_snapshot = models.JSONField()
    camera_snapshot = models.JSONField()

    class Meta:
        """Ускоряет историю камеры в порядке обнаружения."""

        indexes = [models.Index(fields=["camera", "-detected_at"])]


class ViolationMedia(UUIDRecord):
    """Ссылки на защищённые доказательства в project storage."""

    violation = models.ForeignKey(Violation, on_delete=models.CASCADE, related_name="media")
    kind = models.CharField(max_length=16)
    path = models.CharField(max_length=500)

    class Meta:
        """Запрещает два одинаковых вида evidence у одного события."""

        constraints = [
            models.UniqueConstraint(fields=["violation", "kind"], name="event_media_kind")
        ]


class NotificationSettings(models.Model):
    """Бизнес-переключатели; deployment hard flags имеют больший приоритет."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    global_enabled = models.BooleanField(default=False)
    email_enabled = models.BooleanField(default=False)
    telegram_enabled = models.BooleanField(default=False)


class NotificationRecipient(UUIDRecord):
    """Получатель одного канала; токены и пароли здесь не хранятся."""

    channel = models.CharField(max_length=16)
    target = models.CharField(max_length=250)
    display_name = models.CharField(max_length=150, blank=True)
    enabled = models.BooleanField(default=True)

    class Meta:
        """Предотвращает дублирование адресата внутри одного канала."""

        constraints = [
            models.UniqueConstraint(fields=["channel", "target"], name="recipient_channel_target")
        ]


class NotificationDelivery(UUIDRecord):
    """Текущее состояние доставки; все попытки сохраняются отдельно."""

    violation = models.ForeignKey(
        Violation, null=True, on_delete=models.CASCADE, related_name="deliveries"
    )
    recipient = models.ForeignKey(NotificationRecipient, null=True, on_delete=models.SET_NULL)
    channel = models.CharField(max_length=16)
    target = models.CharField(max_length=250)
    status = models.CharField(max_length=24, default="PENDING", db_index=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    last_error_code = models.CharField(max_length=64, blank=True)
    sent_at = models.DateTimeField(null=True)
    next_attempt_at = models.DateTimeField(null=True)


class NotificationDeliveryAttempt(UUIDRecord):
    """История одной попытки без внешнего error payload и секретов."""

    delivery = models.ForeignKey(
        NotificationDelivery, on_delete=models.CASCADE, related_name="attempts"
    )
    status = models.CharField(max_length=24)
    error_code = models.CharField(max_length=64, blank=True)


class NotificationOutbox(UUIDRecord):
    """Durable поручение, записанное в одной транзакции с нарушением."""

    delivery = models.OneToOneField(NotificationDelivery, on_delete=models.CASCADE)
    published_at = models.DateTimeField(null=True)


class GeneratedReport(UUIDRecord):
    """История PDF/CSV пользователя; TTL ограничивает размер файлового хранилища."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    format = models.CharField(max_length=8)
    filters = models.JSONField(default=dict)
    path = models.CharField(max_length=500)
    status = models.CharField(max_length=16, default="READY")


class SystemSettings(models.Model):
    """Несекретные настройки объекта с жёстким потолком retention на application boundary."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    default_timezone = models.CharField(max_length=64, default="Europe/Moscow")
    media_retention_days = models.PositiveSmallIntegerField(default=30)
    default_confidence = models.FloatField(default=0.65)

    class Meta:
        """Защищает политику хранения также на уровне базы."""

        constraints = [
            models.CheckConstraint(
                condition=models.Q(media_retention_days__gte=1, media_retention_days__lte=30),
                name="retention_max_month",
            )
        ]


class AuditEvent(UUIDRecord):
    """Аудит изменений с allow-list metadata; credentials никогда не записываются."""

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    operation = models.CharField(max_length=64)
    object_id = models.CharField(max_length=64, blank=True)
