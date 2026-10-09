# src/core/logging.py
"""Структурированные логи с allow-list полей; внешние ошибки не раскрывают RTSP URL."""

import json
import logging
import traceback
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    """Формирует ограниченную запись; произвольные аргументы и payload не включаются."""

    def format(self, record: logging.LogRecord) -> str:
        """Сериализует разрешённые диагностические поля без текста внешних исключений."""
        result = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event", record.name),
            "service": "warehouse-watch",
        }
        for key in (
            "operation",
            "duration_ms",
            "status",
            "camera_id",
            "violation_id",
            "request_id",
        ):
            if hasattr(record, key):
                result[key] = getattr(record, key)
        if record.exc_info:
            result["error_type"] = record.exc_info[0].__name__
            # Сохраняем stack locations, исключая текст exceptions, исходных строк и locals.
            result["traceback"] = [
                {"file": frame.filename, "line": frame.lineno, "function": frame.name}
                for frame in traceback.extract_tb(record.exc_info[2])
            ]
        return json.dumps(result, ensure_ascii=False, default=str)
