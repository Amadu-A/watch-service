# src/core/timing.py
"""Единое измерение sync/async операций без повторного traceback и логов каждого кадра."""

import inspect
import logging
from functools import wraps
from time import perf_counter


def timed(operation: str):
    """Добавляет одну запись с длительностью и исходом значимой операции."""

    def decorate(function):
        """Сохраняет метаданные функции и выбирает подходящую обёртку."""

        def record(started: float, status: str) -> None:
            """Пишет итог операции без аргументов вызова и секретных payload."""
            logging.getLogger(function.__module__).info(
                "operation_timing",
                extra={
                    "event": "operation_timing",
                    "operation": operation,
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                    "status": status,
                },
            )

        @wraps(function)
        def sync_wrapper(*args, **kwargs):
            """Измеряет синхронный вызов, сохраняя исходное исключение."""
            started, status = perf_counter(), "success"
            try:
                return function(*args, **kwargs)
            except Exception:
                status = "error"
                raise
            finally:
                record(started, status)

        @wraps(function)
        async def async_wrapper(*args, **kwargs):
            """Измеряет асинхронный вызов без блокировки event loop."""
            started, status = perf_counter(), "success"
            try:
                return await function(*args, **kwargs)
            except Exception:
                status = "error"
                raise
            finally:
                record(started, status)

        return async_wrapper if inspect.iscoroutinefunction(function) else sync_wrapper

    return decorate
