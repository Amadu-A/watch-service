# src/web/api.py
"""Class-based transport API; controllers получают готовые services через .as_view injection."""

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.http import HttpResponse, StreamingHttpResponse
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from core.domain import Actor, BusinessError
from web import serializers as schemas


def actor_context(request) -> Actor:
    """Преобразует auth identity в framework-independent application context."""
    return Actor(
        request.user.id, "ADMINISTRATOR" if request.user.is_superuser else request.user.role
    )


def validated(serializer_class, data, *, partial=False) -> dict:
    """Проверяет HTTP поля и выдаёт типизированные values для use-case."""
    serializer = serializer_class(data=data, partial=partial)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def json_safe(data):
    """Преобразует UUID/datetime filters перед сохранением report metadata в JSONField."""
    if isinstance(data, dict):
        return {key: json_safe(value) for key, value in data.items()}
    if isinstance(data, list):
        return [json_safe(value) for value in data]
    return data if isinstance(data, (str, bool, float, int, type(None))) else str(data)


class InjectedAPIView(APIView):
    """Общая transport основа; service_factory задаётся только URL composition."""

    service_factory = None

    def service(self):
        """Создаёт готовый use-case через внедрённую factory без поиска global container."""
        return self.service_factory()


class UnknownAPI(APIView):
    """Сохраняет JSON-контракт ошибок также для неверного UUID и неизвестного API пути."""

    @extend_schema(exclude=True)
    def get(self, request, unknown):
        """Возвращает предметную 404 после штатной проверки authentication."""
        raise BusinessError("not_found", "API endpoint не найден.", 404)

    post = put = patch = delete = get


class CameraListAPI(InjectedAPIView):
    """Список и создание физических камер, независимо от dashboard selection."""

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        """Выдаёт безопасные camera DTO."""
        return Response({"data": self.service().list(actor_context(request))})

    @extend_schema(request=schemas.CameraSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        """Передаёт create command после HTTP validation."""
        return Response(
            {
                "data": self.service().save(
                    actor_context(request), validated(schemas.CameraSerializer, request.data)
                )
            },
            status=201,
        )


class CameraDetailAPI(InjectedAPIView):
    """Карточка, patch и безопасная деактивация камеры."""

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, pk):
        """Открывает camera configuration без secrets."""
        return Response({"data": self.service().get(actor_context(request), pk)})

    @extend_schema(request=schemas.CameraSerializer, responses=OpenApiTypes.OBJECT)
    def patch(self, request, pk):
        """Обновляет только переданные поля."""
        return Response(
            {
                "data": self.service().save(
                    actor_context(request),
                    validated(schemas.CameraSerializer, request.data, partial=True),
                    pk,
                )
            }
        )

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def delete(self, request, pk):
        """Отключает stream с сохранением history."""
        return Response({"data": self.service().disable(actor_context(request), pk)})


class GuardLineAPI(InjectedAPIView):
    """Чтение/замена нормализованной геометрии камеры."""

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, pk):
        """Возвращает line или null, если ещё не настроена."""
        return Response({"data": self.service().guard_line(actor_context(request), pk)})

    @extend_schema(request=schemas.GuardLineSerializer, responses=OpenApiTypes.OBJECT)
    def put(self, request, pk):
        """Передаёт валидированный line command в application."""
        return Response(
            {
                "data": self.service().guard_line(
                    actor_context(request), pk, validated(schemas.GuardLineSerializer, request.data)
                )
            }
        )


class CameraConnectionAPI(InjectedAPIView):
    """Явная server-side RTSP проверка для администратора."""

    @extend_schema(request=None, responses=OpenApiTypes.OBJECT)
    def post(self, request, pk):
        """Возвращает только connected boolean, без decoder exceptions."""
        return Response({"data": self.service().test(actor_context(request), pk)})


class CameraSnapshotAPI(InjectedAPIView):
    """Защищённый latest frame endpoint без доступа browser к RTSP credentials."""

    @extend_schema(responses=OpenApiTypes.BINARY)
    def get(self, request, pk):
        """Возвращает свежий JPEG и запрещает cache чувствительных изображений."""
        response = HttpResponse(
            self.service().snapshot(actor_context(request), pk), content_type="image/jpeg"
        )
        response["Cache-Control"] = "no-store"
        return response


class CameraStreamAPI(InjectedAPIView):
    """Authenticated MJPEG; соединения обновляются, чтобы повторно проверять session auth."""

    @extend_schema(responses=OpenApiTypes.BINARY)
    def get(self, request, pk):
        """Проверяет доступ до начала stream и ограничивает соединение одной минутой."""
        service, actor = self.service(), actor_context(request)
        first = service.snapshot(actor, pk)

        def chunks():
            """Передаёт latest JPEG; offline завершает соединение вместо старого кадра."""
            frame, deadline = first, time.monotonic() + 60
            while time.monotonic() < deadline:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                time.sleep(0.2)
                try:
                    frame = service.snapshot(actor, pk)
                except BusinessError:
                    break

        response = StreamingHttpResponse(
            chunks(), content_type="multipart/x-mixed-replace; boundary=frame"
        )
        response["Cache-Control"] = "no-store"
        response["X-Accel-Buffering"] = "no"
        return response


class SettingsAPI(InjectedAPIView):
    """Общий transport для line-independent singleton settings и personal layout."""

    operation = "settings"
    serializer_class = schemas.SystemSettingsSerializer

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        """Читает настройки через внедрённую application operation."""
        return Response({"data": getattr(self.service(), self.operation)(actor_context(request))})

    def _write(self, request, partial):
        """Валидирует command и передаёт данные application service."""
        data = validated(self.serializer_class, request.data, partial=partial)
        return Response(
            {"data": getattr(self.service(), self.operation)(actor_context(request), data)}
        )

    @extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
    def put(self, request):
        """Полностью заменяет singleton settings согласно endpoint schema."""
        return self._write(request, False)

    @extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
    def patch(self, request):
        """Обновляет переданные настройки."""
        return self._write(request, True)


class TimezonesAPI(InjectedAPIView):
    """Список IANA zones для настройки weekly schedule."""

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        """Возвращает список поддерживаемых идентификаторов."""
        return Response({"data": self.service().timezones(actor_context(request))})


class ViolationListAPI(InjectedAPIView):
    """Пагинированная history с фильтрами по времени, камере и статусу."""

    @extend_schema(parameters=[schemas.FiltersSerializer], responses=OpenApiTypes.OBJECT)
    def get(self, request):
        """Передаёт parsed filters без ORM lookup в controller."""
        return Response(
            self.service().list(
                actor_context(request), validated(schemas.FiltersSerializer, request.query_params)
            )
        )


class ViolationDetailAPI(InjectedAPIView):
    """Детальная карточка crossing и delivery history."""

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, pk):
        """Возвращает DTO, исключая internal storage paths из внешнего API."""
        event = self.service().get(actor_context(request), pk)
        return Response(
            {"data": {key: value for key, value in event.items() if key != "media_paths"}}
        )


class ViolationMediaAPI(InjectedAPIView):
    """Защищённый download original/annotated/clip."""

    @extend_schema(responses=OpenApiTypes.BINARY)
    def get(self, request, pk, kind):
        """Проверяет kind через use-case, выставляя безопасный filename."""
        content = self.service().media(actor_context(request), pk, kind)
        response = HttpResponse(
            content, content_type="video/mp4" if kind == "clip" else "image/jpeg"
        )
        response["Content-Disposition"] = (
            f'inline; filename="{pk}-{kind}.{"mp4" if kind == "clip" else "jpg"}"'
        )
        response["Cache-Control"] = "no-store"
        return response


class StatisticsAPI(InjectedAPIView):
    """Краткая статистика за today/7d/30d или явно заданный interval."""

    timezone_provider = None

    @extend_schema(parameters=[schemas.FiltersSerializer], responses=OpenApiTypes.OBJECT)
    def get(self, request):
        """Интерпретирует UI период относительно timezone объекта."""
        filters = validated(schemas.FiltersSerializer, request.query_params)
        now = datetime.now(ZoneInfo(self.timezone_provider()))
        if not filters.get("date_from") and filters.get("period") != "custom":
            period = filters.get("period", "7d")
            filters["date_from"] = (
                now.replace(hour=0, minute=0, second=0, microsecond=0)
                if period == "today"
                else now - timedelta(days=30 if period == "30d" else 7)
            )
        if filters.get("period") == "custom" and not {"date_from", "date_to"} <= filters.keys():
            raise BusinessError("period_required", "Укажите начало и конец периода.")
        return Response({"data": self.service().statistics(actor_context(request), filters)})


class RecipientListAPI(InjectedAPIView):
    """Административное управление получателями."""

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        """Выдаёт registered recipients после application role check."""
        return Response({"data": self.service().recipients(actor_context(request))})

    @extend_schema(request=schemas.RecipientSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        """Создаёт одного адресата канала."""
        return Response(
            {
                "data": self.service().recipient(
                    actor_context(request), validated(schemas.RecipientSerializer, request.data)
                )
            },
            status=201,
        )


class RecipientDetailAPI(InjectedAPIView):
    """Изменение/удаление одного адресата, с сохранением delivery snapshots."""

    @extend_schema(request=schemas.RecipientSerializer, responses=OpenApiTypes.OBJECT)
    def patch(self, request, pk):
        """Изменяет только заданные recipient поля."""
        return Response(
            {
                "data": self.service().recipient(
                    actor_context(request),
                    validated(schemas.RecipientSerializer, request.data, partial=True),
                    pk,
                )
            }
        )

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def delete(self, request, pk):
        """Удаляет recipient, сохраняя target snapshot прошлых доставок."""
        return Response(
            {"data": self.service().recipient(actor_context(request), None, pk, delete=True)}
        )


class NotificationTestAPI(InjectedAPIView):
    """Тестовая отправка также проходит hard deployment gate."""

    @extend_schema(request=None, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        """Ставит отдельные test deliveries, не выполняя external I/O в HTTP request."""
        return Response({"data": self.service().test(actor_context(request))}, status=202)


class DeliveryListAPI(InjectedAPIView):
    """История попыток отправки уведомлений."""

    @extend_schema(parameters=[schemas.FiltersSerializer], responses=OpenApiTypes.OBJECT)
    def get(self, request):
        """Выдаёт историю после проверки query schema."""
        return Response(
            self.service().deliveries(
                actor_context(request), validated(schemas.FiltersSerializer, request.query_params)
            )
        )


class DeliveryDetailAPI(InjectedAPIView):
    """Карточка delivery с attempts."""

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, pk):
        """Возвращает current status и полную историю попыток."""
        return Response({"data": self.service().delivery(actor_context(request), pk)})


class DeliveryRetryAPI(InjectedAPIView):
    """Ручной retry для оператора/администратора."""

    @extend_schema(request=None, responses=OpenApiTypes.OBJECT)
    def post(self, request, pk):
        """Вызывает application state/permission checks перед повторной публикацией."""
        return Response({"data": self.service().retry(actor_context(request), pk)}, status=202)


class ViolationResendAPI(InjectedAPIView):
    """Повторная отправка неуспешных уведомлений одного события."""

    event_service_factory = None

    @extend_schema(request=None, responses=OpenApiTypes.OBJECT)
    def post(self, request, pk):
        """Получает event DTO и передаёт его notification use-case."""
        actor = actor_context(request)
        return Response(
            {"data": self.service().resend(actor, self.event_service_factory().get(actor, pk))},
            status=202,
        )


class ReportListAPI(InjectedAPIView):
    """Персональная история generated reports и синхронная generation."""

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        """Возвращает файлы текущего пользователя."""
        return Response({"data": self.service().list(actor_context(request))})

    @extend_schema(request=schemas.ReportSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        """Передаёт report command; JSON metadata сохраняет canonical ISO strings."""
        return Response(
            {
                "data": self.service().create(
                    actor_context(request),
                    json_safe(validated(schemas.ReportSerializer, request.data)),
                )
            },
            status=201,
        )


class ReportDetailAPI(InjectedAPIView):
    """Metadata готового персонального файла."""

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, pk):
        """Проверяет принадлежность report UUID через application."""
        return Response({"data": self.service().get(actor_context(request), pk)})


class ReportDownloadAPI(InjectedAPIView):
    """Download защищённого generated report либо single-event PDF."""

    single_event = False

    @extend_schema(responses=OpenApiTypes.BINARY)
    def get(self, request, pk):
        """Проверяет permissions до чтения файла, отключает shared cache."""
        if self.single_event:
            content, format_name = self.service().single(actor_context(request), pk), "PDF"
        else:
            content, format_name = self.service().download(actor_context(request), pk)
        response = HttpResponse(
            content,
            content_type="application/pdf" if format_name == "PDF" else "text/csv; charset=utf-8",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="report-{pk}.{format_name.lower()}"'
        )
        response["Cache-Control"] = "no-store"
        return response


class MeAPI(APIView):
    """Текущая identity и permissions без чтения ORM в controller."""

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        """Использует только готовый authentication context Django middleware."""
        actor = actor_context(request)
        return Response(
            {
                "data": {
                    "id": str(actor.id),
                    "username": request.user.username,
                    "display_name": request.user.get_full_name() or request.user.username,
                    "role": actor.role,
                    "permissions": ["read"]
                    + (["retry"] if actor.role != "VIEWER" else [])
                    + (["configure"] if actor.role == "ADMINISTRATOR" else []),
                }
            }
        )
