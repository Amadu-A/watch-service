# src/accounts_app/management/commands/create_watch_user.py
"""Интерактивное создание пользователя с явной ролью без пароля в argv и логах."""

from getpass import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    """Создаёт новую учётную запись; существующего пользователя не изменяет."""

    help = "Создать пользователя видеоконтроля с явной ролью"

    def add_arguments(self, parser):
        """Принимает только имя и одну из трёх разрешённых ролей."""
        parser.add_argument("username")
        parser.add_argument("role", choices=["ADMINISTRATOR", "OPERATOR", "VIEWER"])

    def handle(self, *args, **options):
        """Проверяет пароль перед созданием, не выводя его и не принимая через shell."""
        model = get_user_model()
        if model.objects.filter(username=options["username"]).exists():
            raise CommandError("Пользователь уже существует")
        password, confirmation = getpass("Пароль: "), getpass("Повтор пароля: ")
        if password != confirmation:
            raise CommandError("Пароли не совпадают")
        user = model(username=options["username"], role=options["role"])
        try:
            user.full_clean(exclude=["password"])
            validate_password(password, user)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from None
        user.set_password(password)
        user.save()
        self.stdout.write("Пользователь создан")
