# src/config/urls.py
"""
Корневая маршрутизация Django.

Регистрирует только подготовленные маршруты. Маршруты legacy
подключаются поэтапно после переноса и проверки соответствующих CBV.

Пользовательские endpoints используют только class-based views.
"""

from __future__ import annotations

from django.contrib import admin
from django.urls import path

from watch_app.views import LivenessView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/live", LivenessView.as_view(), name="health-live"),
]
