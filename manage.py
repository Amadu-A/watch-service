# manage.py
"""
Точка входа команд управления Django.

Добавляет исходный каталог src в путь импорта, чтобы Django находил
пакет config при запуске из корня репозитория на Windows и Linux.
Не создаёт инфраструктурных зависимостей и не обращается к БД.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    """Запускает Django management command с корректным путём импорта."""
    project_root = Path(__file__).resolve().parent
    source_root = project_root / "src"

    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
