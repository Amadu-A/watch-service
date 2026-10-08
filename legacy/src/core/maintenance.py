# src/core/maintenance.py
"""Операционный запуск retention только через watch.sh; metadata и файлы удаляются согласованно."""

import os

import django


def main() -> None:
    """Инициализирует Django и выполняет bounded cleanup через composition root."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()
    from core.container import retention_cleaner

    print(retention_cleaner().execute())


if __name__ == "__main__":
    main()
