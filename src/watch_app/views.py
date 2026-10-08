# src/watch_app/views.py
"""
Базовые HTTP представления приложения.

Содержит минимальную liveness проверку, не зависящую от базы данных,
Redis, RabbitMQ или камер. Прикладная логика будет вынесена в use-cases.
"""

from __future__ import annotations

from django.http import JsonResponse
from django.views import View


class LivenessView(View):
    """Подтверждает доступность процесса Django без проверки внешних систем."""

    def get(self, request, *args, **kwargs) -> JsonResponse:
        """Возвращает стабильный JSON ответ для базовой проверки HTTP."""
        return JsonResponse({"status": "alive"})
