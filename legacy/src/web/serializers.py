# src/web/serializers.py
"""Transport validation и OpenAPI schemas; бизнес-правила остаются в application/domain."""

from datetime import datetime

from rest_framework import serializers as s


class StrictSerializer(s.Serializer):
    """Отклоняет неизвестные поля вместо молчаливого игнорирования настроек и опечаток."""

    def to_internal_value(self, data):
        """Применяет allow-list полей на внешней JSON границе."""
        if not isinstance(data, dict):
            raise s.ValidationError("Ожидается JSON-объект.")
        unknown = set(data) - set(self.fields)
        if unknown:
            raise s.ValidationError({key: "Неизвестное поле." for key in unknown})
        return super().to_internal_value(data)


class AwareDateTime(s.DateTimeField):
    """Требует timezone в ISO 8601 строке, чтобы фильтры не зависели от локального host."""

    def to_internal_value(self, value):
        """Отклоняет naïve datetime перед стандартным parsing DRF."""
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise s.ValidationError("Укажите ISO 8601 дату с часовым поясом.") from None
        return super().to_internal_value(value)


class RTSPSerializer(StrictSerializer):
    """Принимает credentials только на write boundary; они никогда не отражаются response."""

    url = s.CharField(max_length=1000)
    username = s.CharField(max_length=250, allow_blank=True, required=False, default="")
    password = s.CharField(
        max_length=500, allow_blank=True, required=False, default="", write_only=True
    )


class CameraSerializer(StrictSerializer):
    """Схема создания/patch камеры; обязательность create проверяет application."""

    name = s.CharField(max_length=150, required=False)
    location = s.CharField(max_length=250, allow_blank=True, required=False)
    enabled = s.BooleanField(required=False)
    rtsp = RTSPSerializer(required=False, write_only=True)


class PointSerializer(StrictSerializer):
    """Нормализованные координаты исключают зависимость UI от resolution."""

    x = s.FloatField(min_value=0, max_value=1)
    y = s.FloatField(min_value=0, max_value=1)


class GuardLineSerializer(StrictSerializer):
    """Полная конфигурация контрольной линии."""

    start = PointSerializer()
    end = PointSerializer()
    inside_side = s.ChoiceField(choices=["left", "right"], default="left")
    direction = s.ChoiceField(choices=["ENTRY", "EXIT", "BOTH"], default="ENTRY")
    min_confidence = s.FloatField(min_value=0, max_value=1, default=0.65)
    enabled = s.BooleanField(default=True)


class LayoutSerializer(StrictSerializer):
    """Сохраняет упорядоченный массив UUID камер."""

    camera_ids = s.ListField(child=s.UUIDField())
    grid = s.ChoiceField(choices=["auto", "1", "2", "3", "4"], default="auto")


class ScheduleSerializer(StrictSerializer):
    """Неделя далее валидируется domain SchedulePolicy."""

    timezone = s.CharField(max_length=64)
    week = s.DictField()
    enabled = s.BooleanField(default=True)


class NotificationSettingsSerializer(StrictSerializer):
    """Бизнес-флаги; runtime flags менять через API невозможно."""

    global_enabled = s.BooleanField(required=False)
    email_enabled = s.BooleanField(required=False)
    telegram_enabled = s.BooleanField(required=False)


class RecipientSerializer(StrictSerializer):
    """Адресат одного канала, без runtime credentials."""

    channel = s.ChoiceField(choices=["EMAIL", "TELEGRAM"])
    target = s.CharField(max_length=250)
    display_name = s.CharField(max_length=150, allow_blank=True, required=False)
    enabled = s.BooleanField(required=False)


class FiltersSerializer(s.Serializer):
    """Параметризованные filters и конечный размер страницы истории."""

    page = s.IntegerField(min_value=1, default=1)
    page_size = s.IntegerField(min_value=1, max_value=100, default=50)
    camera_id = s.UUIDField(required=False)
    date_from = AwareDateTime(required=False)
    date_to = AwareDateTime(required=False)
    direction = s.ChoiceField(choices=["ENTRY", "EXIT"], required=False)
    notification_status = s.ChoiceField(
        choices=["PENDING", "QUEUED", "SENT", "FAILED", "RETRYING", "SKIPPED_DISABLED", "DEAD"],
        required=False,
    )
    violation_id = s.UUIDField(required=False)
    recipient_id = s.UUIDField(required=False)
    channel = s.ChoiceField(choices=["EMAIL", "TELEGRAM"], required=False)
    status = s.CharField(max_length=24, required=False)
    period = s.ChoiceField(choices=["today", "7d", "30d", "custom"], required=False)

    def validate(self, attrs):
        """Отклоняет пустой/обратный период до обращения к persistence."""
        if (
            attrs.get("date_from")
            and attrs.get("date_to")
            and attrs["date_from"] >= attrs["date_to"]
        ):
            raise s.ValidationError("Начало периода должно предшествовать концу.")
        return attrs


class ReportFiltersSerializer(FiltersSerializer):
    """Расширяет filters списка несколькими cameras для period report."""

    camera_ids = s.ListField(child=s.UUIDField(), required=False)


class ReportSerializer(StrictSerializer):
    """Запрос синхронного отчёта до 2000 событий."""

    type = s.ChoiceField(choices=["VIOLATIONS"], default="VIOLATIONS")
    format = s.ChoiceField(choices=["PDF", "CSV"])
    filters = ReportFiltersSerializer(required=False)


class SystemSettingsSerializer(StrictSerializer):
    """Разрешённые UI settings; дополнительный deployment потолок проверяет use-case."""

    default_timezone = s.CharField(max_length=64, required=False)
    media_retention_days = s.IntegerField(min_value=1, max_value=30, required=False)
    default_confidence = s.FloatField(min_value=0, max_value=1, required=False)
