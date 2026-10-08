# src/core/container.py
"""Composition root: только здесь собираются concrete repositories, clients и use-cases."""

from contextlib import suppress
from functools import cache
from pathlib import Path

from redis import Redis

from core.config import ROOT, Settings
from core.infrastructure import (
    DjangoAudit,
    DjangoUnitOfWork,
    FernetCredentialCipher,
    LocalMediaStorage,
    RedisLiveFrameCache,
)
from modules.cameras.application.service import CameraService
from modules.cameras.infrastructure.repository import DjangoCameraRepository
from modules.dashboard.application.service import MonitoringService
from modules.dashboard.infrastructure.repository import DjangoMonitoringRepository
from modules.notifications.application.service import DispatchNotification, NotificationService
from modules.notifications.infrastructure.repository import DjangoNotificationRepository
from modules.notifications.infrastructure.senders import SMTPEmailSender, TelegramBotSender
from modules.reports.application.service import ReportService
from modules.reports.infrastructure.renderer import EvidenceReportRenderer
from modules.reports.infrastructure.repository import DjangoReportRepository
from modules.violations.application.service import CreateViolation, ViolationService
from modules.violations.infrastructure.repository import DjangoViolationRepository


@cache
def configuration() -> Settings:
    """Загружает process конфигурацию один раз; тесты могут очищать cache."""
    return Settings()


def monitoring_repository():
    """Собирает repository с safe defaults объекта."""
    config = configuration()
    return DjangoMonitoringRepository(config.default_timezone, config.media_retention_days)


def storage():
    """Подключает project-owned volume через абсолютный корень адаптера."""
    return LocalMediaStorage(ROOT / Path(configuration().media_root))


@cache
def frames():
    """Разделяет Redis connection pool внутри процесса с конечными timeout."""
    config = configuration()
    return RedisLiveFrameCache(
        Redis.from_url(config.redis_url, socket_connect_timeout=2, socket_timeout=2),
        config.vision_frame_ttl_seconds,
    )


def cipher():
    """Создаёт crypto adapter по secret environment key."""
    return FernetCredentialCipher(configuration().camera_credentials_key.get_secret_value())


def probe(connection: dict) -> bool:
    """Открывает отдельный короткий RTSP decoder только для явного test-connection."""
    from modules.surveillance.infrastructure.vision import probe_rtsp

    return probe_rtsp(connection)


def vision_detector():
    """Создаёт единственную модель в процессе vision без автоматической замены GPU на CPU."""
    from modules.surveillance.infrastructure.vision import UltralyticsPersonDetector

    config = configuration()
    return (
        UltralyticsPersonDetector(config.vision_model, config.vision_device)
        if config.vision_enabled
        else None
    )


def camera_source(connection):
    """Собирает отдельный RTSP decoder для одной камеры."""
    from modules.surveillance.infrastructure.vision import RTSPCameraSource

    return RTSPCameraSource(connection)


def frame_renderer():
    """Собирает Unicode renderer кадров независимо от загрузки detector."""
    from modules.surveillance.infrastructure.vision import OpenCVFrameRenderer

    return OpenCVFrameRenderer(configuration().report_font_path)


def camera_pipeline(camera, line, detector, renderer):
    """Внедряет отдельный tracker и общие model/cache в пайплайн одной камеры."""
    from modules.surveillance.application.pipeline import CameraPipeline
    from modules.surveillance.domain.geometry import LineCrossingPolicy
    from modules.surveillance.infrastructure.vision import ByteTrackTracker

    config = configuration()
    return CameraPipeline(
        camera=camera,
        line=line,
        detector=detector,
        tracker=ByteTrackTracker(config.vision_fps),
        renderer=renderer,
        cache=frames(),
        crossing_policy=LineCrossingPolicy(
            min_age=config.vision_min_track_frames,
            stable_frames=config.vision_stable_frames,
            hysteresis=config.vision_hysteresis,
        ),
        schedule_provider=monitoring_repository().schedule,
        create_violation=create_violation(),
        fps=config.vision_fps,
        before_seconds=config.evidence_before_seconds,
        after_seconds=config.evidence_after_seconds,
        track_ttl=config.vision_track_ttl_seconds,
        clip_enabled=config.event_clip_enabled,
        clip_before=config.clip_before_seconds,
        clip_after=config.clip_after_seconds,
    )


def camera_service():
    """Внедряет dependencies в camera use-cases без service locator в view."""
    return CameraService(
        DjangoCameraRepository(), cipher(), DjangoUnitOfWork(), DjangoAudit(), frames(), probe
    )


def monitoring_service():
    """Собирает проверки раскладки, расписания и retention."""
    config = configuration()
    return MonitoringService(
        monitoring_repository(),
        DjangoCameraRepository(),
        DjangoUnitOfWork(),
        DjangoAudit(),
        config.monitoring_max_visible_cameras,
        config.media_retention_days,
    )


def notification_service():
    """Передаёт immutable hard flags в application gate."""
    config = configuration()
    return NotificationService(
        DjangoNotificationRepository(),
        DjangoUnitOfWork(),
        DjangoAudit(),
        config.notifications_enabled,
        {
            "EMAIL": config.email_notifications_enabled,
            "TELEGRAM": config.telegram_notifications_enabled,
        },
    )


def violation_service():
    """Собирает read use-cases истории и evidence."""
    return ViolationService(DjangoViolationRepository(), storage())


def create_violation():
    """Связывает evidence, transaction и durable notification preparation."""
    return CreateViolation(
        DjangoViolationRepository(), storage(), DjangoUnitOfWork(), notification_service()
    )


def renderer():
    """Создаёт русскоязычный report renderer с timezone provider объекта."""
    return EvidenceReportRenderer(
        storage(),
        lambda: monitoring_repository().schedule()["timezone"],
        configuration().report_font_path,
    )


def report_service():
    """Собирает generation и защищённую историю файлов пользователя."""
    return ReportService(
        DjangoViolationRepository(), DjangoReportRepository(), storage(), renderer()
    )


def dispatch_notification():
    """Создаёт sender adapters, которые вызываются только после application hard gate."""
    config = configuration()
    return DispatchNotification(
        DjangoNotificationRepository(),
        notification_service(),
        DjangoViolationRepository(),
        storage(),
        renderer(),
        {
            "EMAIL": SMTPEmailSender(config),
            "TELEGRAM": TelegramBotSender(
                config.telegram_bot_token.get_secret_value(), config.notification_timeout_seconds
            ),
        },
        config.notification_max_attempts,
        lambda: monitoring_repository().schedule()["timezone"],
    )


def outbox_publisher():
    """Подключает только Celery client к shared RabbitMQ."""
    from modules.notifications.infrastructure.outbox import CeleryOutboxPublisher
    from workers.tasks import send_delivery

    return CeleryOutboxPublisher(send_delivery)


def retention_cleaner():
    """Ограничивает срок хранения deployment потолком не более 30 дней."""
    from modules.persistence.retention import RetentionCleaner

    return RetentionCleaner(
        storage(), monitoring_repository().settings, configuration().media_retention_days
    )


def readiness() -> dict:
    """Проверяет критичные DB/Redis; offline камеры не влияют на web readiness."""
    from django.db import connection

    result = {"postgresql": False, "redis": False}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            result["postgresql"] = cursor.fetchone()[0] == 1
    except Exception:
        pass
    with suppress(Exception):
        result["redis"] = bool(frames().client.ping())
    return result


def project_source():
    """Внедряет безопасную выдачу исходников текущего образа для страницы лицензии."""
    from core.source_archive import running_source

    return running_source()


def project_license():
    """Читает только статический LICENSE проекта без пользовательского пути."""
    return (ROOT / "LICENSE").read_bytes()
