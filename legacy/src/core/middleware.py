# src/core/middleware.py
"""Идентификаторы запросов для единых API errors, без доверия внешним заголовкам."""

import uuid


class RequestIdMiddleware:
    """Назначает независимый UUID каждой HTTP-операции."""

    def __init__(self, get_response):
        """Получает следующий компонент цепочки Django."""
        self.get_response = get_response

    def __call__(self, request):
        """Связывает response и ошибку API через один request_id."""
        request.request_id = str(uuid.uuid4())
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        return response
