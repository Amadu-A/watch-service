# src/web/pages.py
"""Server-rendered CBV pages; HTML не выполняет ORM и загружает данные через API."""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.http import HttpResponse, JsonResponse
from django.views import View
from django.views.generic import TemplateView


class ProjectLoginView(LoginView):
    """Штатная Django session authentication с CSRF и русским шаблоном."""

    template_name = "pages/login.html"
    redirect_authenticated_user = True


class ProjectLogoutView(LogoutView):
    """Завершает сессию только POST запросом с CSRF."""


class SourceDownloadView(LoginRequiredMixin, View):
    """Предоставляет пользователям исходники именно запущенной версии проекта."""

    source_provider = None

    def get(self, request):
        """Выдаёт архив явного списка файлов, исключающего приватную конфигурацию."""
        response = HttpResponse(self.source_provider(), content_type="application/gzip")
        response["Content-Disposition"] = (
            'attachment; filename="warehouse-perimeter-watch-source.tar.gz"'
        )
        response["Cache-Control"] = "no-store"
        return response


class LicenseView(View):
    """Показывает полный неизменённый текст лицензии."""

    license_provider = None

    def get(self, request):
        """Возвращает статическую лицензию как текст UTF-8."""
        return HttpResponse(self.license_provider(), content_type="text/plain; charset=utf-8")


class ProjectPage(LoginRequiredMixin, TemplateView):
    """Подготавливает page context без business queries и transport-side ORM."""

    page = "monitoring"
    title = "Мониторинг"

    def get_context_data(self, **kwargs):
        """Передаёт UI role и endpoint identity в декларативные data hooks."""
        context = super().get_context_data(**kwargs)
        context.update(
            page=self.page,
            title=self.title,
            can_configure=self.request.user.is_superuser
            or self.request.user.role == "ADMINISTRATOR",
            can_retry=self.request.user.is_superuser
            or self.request.user.role in ("ADMINISTRATOR", "OPERATOR"),
        )
        return context


class LivenessView(View):
    """Минимальная liveness проверка процесса, независимая от камер и broker."""

    def get(self, request):
        """Возвращает healthy process response без internal configuration."""
        return JsonResponse({"status": "alive"})


class ReadinessView(View):
    """Критичные зависимости web приложения проверяет внедрённый provider."""

    readiness_provider = None

    def get(self, request):
        """Не раскрывает секреты; отсутствие DB/Redis даёт 503."""
        states = self.readiness_provider()
        ready = all(states.values())
        return JsonResponse(
            {"status": "ready" if ready else "not_ready", "dependencies": states},
            status=200 if ready else 503,
        )


class MetricsView(LoginRequiredMixin, View):
    """Защищённые базовые readiness metrics без секретов и high-cardinality labels."""

    readiness_provider = None

    def get(self, request):
        """Выдаёт Prometheus-compatible значения доступности dependencies."""
        content = (
            "\n".join(
                f'warehouse_dependency_up{{dependency="{key}"}} {int(value)}'
                for key, value in self.readiness_provider().items()
            )
            + "\n"
        )
        return HttpResponse(content, content_type="text/plain; version=0.0.4")
