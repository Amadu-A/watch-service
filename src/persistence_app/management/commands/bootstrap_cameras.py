# src/persistence_app/management/commands/bootstrap_cameras.py
"""Первичная регистрация камер из environment; реальные credentials остаются encrypted."""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from dotenv import dotenv_values

from core import container as c
from core.config import ROOT
from domain.common import Actor


class Command(BaseCommand):
    """Идемпотентно добавляет камеры по RTSP endpoint после создания администратора."""

    help = "Импорт камер из приватной конфигурации"

    def handle(self, *args, **options):
        """Читает layered env и импортирует только камеры с заданными credentials."""
        values = {
            **dotenv_values(ROOT / ".env.example"),
            **dotenv_values(ROOT / ".env"),
            **os.environ,
        }
        user = get_user_model().objects.filter(is_superuser=True).first()
        if not user:
            raise CommandError("Сначала создайте администратора через watch.sh admin.")
        service = c.camera_service()
        endpoints = {
            item["rtsp_endpoint"] for item in service.list(Actor(user.id, "ADMINISTRATOR"))
        }
        count = 0
        for index in values.get("CAMERA_INDICES", "").split(","):
            prefix = f"CAMERA_{index.strip()}_"
            if not values.get(prefix + "USERNAME") or not values.get(prefix + "PASSWORD"):
                continue
            ip = values.get(prefix + "IP", "")
            if ip.startswith("192.0.2.") or not ip:
                continue
            port, path = values.get(prefix + "PORT", "554"), values.get(prefix + "PATH", "/stream1")
            url = f"rtsp://{ip}:{port}{path}"
            if url in endpoints:
                continue
            service.save(
                Actor(user.id, "ADMINISTRATOR"),
                {
                    "name": values.get(prefix + "NAME", f"Камера {index}"),
                    "rtsp": {
                        "url": url,
                        "username": values[prefix + "USERNAME"],
                        "password": values[prefix + "PASSWORD"],
                    },
                },
            )
            count += 1
        self.stdout.write(f"Добавлено камер: {count}")
