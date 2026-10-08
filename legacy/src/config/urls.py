# src/config/urls.py
"""Маршруты CBV с явной injection composition-root factories; function views запрещены."""

from django.urls import path
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView
from rest_framework.permissions import IsAuthenticated

from core import container as c
from web import api as a
from web import pages as p
from web import serializers as s

urlpatterns = [
    path("", RedirectView.as_view(url="/monitoring/", permanent=False)),
    path("login/", p.ProjectLoginView.as_view(), name="login"),
    path("logout/", p.ProjectLogoutView.as_view(), name="logout"),
    path("source/", p.SourceDownloadView.as_view(source_provider=c.project_source)),
    path("license/", p.LicenseView.as_view(license_provider=c.project_license)),
    path("health/live", p.LivenessView.as_view()),
    path("health/ready", p.ReadinessView.as_view(readiness_provider=c.readiness)),
    path("metrics", p.MetricsView.as_view(readiness_provider=c.readiness)),
    path("api/schema/", SpectacularAPIView.as_view(permission_classes=[IsAuthenticated])),
    path(
        "api/docs/",
        p.ProjectPage.as_view(template_name="pages/docs.html", page="docs", title="API"),
    ),
    path("monitoring/", p.ProjectPage.as_view(template_name="pages/monitoring.html")),
    path(
        "cameras/",
        p.ProjectPage.as_view(template_name="pages/cameras.html", page="cameras", title="Камеры"),
    ),
    path(
        "cameras/<uuid:pk>/",
        p.ProjectPage.as_view(
            template_name="pages/camera.html", page="camera", title="Настройка камеры"
        ),
    ),
    path(
        "violations/",
        p.ProjectPage.as_view(
            template_name="pages/violations.html", page="violations", title="Нарушения"
        ),
    ),
    path(
        "violations/<uuid:pk>/",
        p.ProjectPage.as_view(
            template_name="pages/violation.html", page="violation", title="Карточка нарушения"
        ),
    ),
    path(
        "reports/",
        p.ProjectPage.as_view(template_name="pages/reports.html", page="reports", title="Отчёты"),
    ),
    path(
        "notifications/",
        p.ProjectPage.as_view(
            template_name="pages/notifications.html", page="notifications", title="Уведомления"
        ),
    ),
    path(
        "settings/",
        p.ProjectPage.as_view(
            template_name="pages/settings.html", page="settings", title="Настройки"
        ),
    ),
    path("api/v1/users/me", a.MeAPI.as_view()),
    path("api/v1/cameras", a.CameraListAPI.as_view(service_factory=c.camera_service)),
    path("api/v1/cameras/<uuid:pk>", a.CameraDetailAPI.as_view(service_factory=c.camera_service)),
    path(
        "api/v1/cameras/<uuid:pk>/guard-line",
        a.GuardLineAPI.as_view(service_factory=c.camera_service),
    ),
    path(
        "api/v1/cameras/<uuid:pk>/test-connection",
        a.CameraConnectionAPI.as_view(service_factory=c.camera_service),
    ),
    path(
        "api/v1/cameras/<uuid:pk>/snapshot",
        a.CameraSnapshotAPI.as_view(service_factory=c.camera_service),
    ),
    path(
        "api/v1/cameras/<uuid:pk>/stream.mjpeg",
        a.CameraStreamAPI.as_view(service_factory=c.camera_service),
    ),
    path(
        "api/v1/users/me/monitoring-layout",
        a.SettingsAPI.as_view(
            service_factory=c.monitoring_service,
            operation="layout",
            serializer_class=s.LayoutSerializer,
            http_method_names=["get", "put", "head", "options"],
        ),
    ),
    path(
        "api/v1/control-schedule",
        a.SettingsAPI.as_view(
            service_factory=c.monitoring_service,
            operation="schedule",
            serializer_class=s.ScheduleSerializer,
            http_method_names=["get", "put", "head", "options"],
        ),
    ),
    path(
        "api/v1/system-settings",
        a.SettingsAPI.as_view(
            service_factory=c.monitoring_service,
            serializer_class=s.SystemSettingsSerializer,
            http_method_names=["get", "patch", "head", "options"],
        ),
    ),
    path("api/v1/timezones", a.TimezonesAPI.as_view(service_factory=c.monitoring_service)),
    path("api/v1/violations", a.ViolationListAPI.as_view(service_factory=c.violation_service)),
    path(
        "api/v1/violations/<uuid:pk>",
        a.ViolationDetailAPI.as_view(service_factory=c.violation_service),
    ),
    path(
        "api/v1/violations/<uuid:pk>/media/<str:kind>",
        a.ViolationMediaAPI.as_view(service_factory=c.violation_service),
    ),
    path(
        "api/v1/violations/<uuid:pk>/report.pdf",
        a.ReportDownloadAPI.as_view(service_factory=c.report_service, single_event=True),
    ),
    path(
        "api/v1/violations/<uuid:pk>/resend",
        a.ViolationResendAPI.as_view(
            service_factory=c.notification_service, event_service_factory=c.violation_service
        ),
    ),
    path(
        "api/v1/statistics/summary",
        a.StatisticsAPI.as_view(
            service_factory=c.violation_service,
            timezone_provider=lambda: c.monitoring_repository().schedule()["timezone"],
        ),
    ),
    path(
        "api/v1/notification-settings",
        a.SettingsAPI.as_view(
            service_factory=c.notification_service,
            serializer_class=s.NotificationSettingsSerializer,
            http_method_names=["get", "patch", "head", "options"],
        ),
    ),
    path(
        "api/v1/notification-recipients",
        a.RecipientListAPI.as_view(service_factory=c.notification_service),
    ),
    path(
        "api/v1/notification-recipients/<uuid:pk>",
        a.RecipientDetailAPI.as_view(service_factory=c.notification_service),
    ),
    path(
        "api/v1/notifications/test",
        a.NotificationTestAPI.as_view(service_factory=c.notification_service),
    ),
    path(
        "api/v1/notification-deliveries",
        a.DeliveryListAPI.as_view(service_factory=c.notification_service),
    ),
    path(
        "api/v1/notification-deliveries/<uuid:pk>",
        a.DeliveryDetailAPI.as_view(service_factory=c.notification_service),
    ),
    path(
        "api/v1/notification-deliveries/<uuid:pk>/retry",
        a.DeliveryRetryAPI.as_view(service_factory=c.notification_service),
    ),
    path("api/v1/reports", a.ReportListAPI.as_view(service_factory=c.report_service)),
    path("api/v1/reports/<uuid:pk>", a.ReportDetailAPI.as_view(service_factory=c.report_service)),
    path(
        "api/v1/reports/<uuid:pk>/download",
        a.ReportDownloadAPI.as_view(service_factory=c.report_service),
    ),
    path("api/v1/<path:unknown>", a.UnknownAPI.as_view()),
]
