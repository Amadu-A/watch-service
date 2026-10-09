# src/accounts_app/models.py
"""UUID-пользователь Django и явная роль для серверной проверки доступа."""

import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Хранит учётную запись и роль; новые пользователи получают только чтение."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.CharField(
        max_length=16,
        default="VIEWER",
        choices=[
            ("ADMINISTRATOR", "Администратор"),
            ("OPERATOR", "Оператор"),
            ("VIEWER", "Наблюдатель"),
        ],
    )
