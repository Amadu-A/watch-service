# src/web/errors.py
"""Единый API error envelope; неизвестные ошибки не раскрывают credentials и filesystem."""

import logging

from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from core.domain import BusinessError


def exception_handler(exc, context):
    """Преобразует validation/auth/domain errors в стабильную схему с request_id."""
    request = context["request"]
    if isinstance(exc, BusinessError):
        code, message, status, details = exc.code, exc.message, exc.status, {}
    else:
        response = drf_exception_handler(exc, context)
        if response is None:
            logging.getLogger(__name__).error(
                "api_failed",
                exc_info=True,
                extra={"event": "api_failed", "request_id": getattr(request, "request_id", "")},
            )
            code, message, status, details = "internal_error", "Внутренняя ошибка сервера.", 500, {}
        else:
            status, details = response.status_code, response.data
            code = {
                400: "validation_error",
                401: "authentication_required",
                403: "permission_denied",
                404: "not_found",
                405: "method_not_allowed",
            }.get(status, "request_error")
            message = "Запрос отклонён. Проверьте поля и права доступа."
    return Response(
        {
            "error": {
                "code": code,
                "message": message,
                "details": details,
                "request_id": getattr(request, "request_id", ""),
            }
        },
        status=status,
    )
