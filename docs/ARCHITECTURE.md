<!-- docs/ARCHITECTURE.md -->
# Архитектура Warehouse Perimeter Watch

## Статус

Принята целевая архитектура модульного Django-монолита.

Референс физической организации приложений:
https://github.com/Amadu-A/Megano

Обязательный инженерный стандарт:
https://github.com/Amadu-A/shared_infrasktructure

При противоречии старого Megano и актуального стандарта
приоритет имеет shared_infrasktructure.

## Целевая структура

```text
src/
├── config/
│   ├── settings/
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
├── core/
│   ├── container.py
│   ├── config.py
│   ├── exceptions.py
│   ├── logging.py
│   └── timing.py
├── interface/
├── repositories/
├── application/
│   ├── cameras/
│   ├── surveillance/
│   ├── violations/
│   ├── notifications/
│   └── reports/
├── infrastructure/
│   ├── vision/
│   ├── camera/
│   ├── storage/
│   └── messaging/
├── watch_app/
├── cameras_app/
├── surveillance_app/
├── violations_app/
├── notifications_app/
├── reports_app/
└── accounts_app/

templates/
static/
tests/
legacy/
docs/
```