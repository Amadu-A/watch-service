<!-- docs/ARCHITECTURE.md: Фактическая архитектура с независимым CPU-захватом. -->
# Архитектура Warehouse Perimeter Watch

## Правила и границы

Приоритет имеют актуальные требования пользователя, затем
`docs-specification.md` и рабочие контракты, далее
[shared_infrasktructure/docs](https://github.com/Amadu-A/shared_infrasktructure/tree/main/docs).
Структура Django-приложений ориентируется на [Megano](https://github.com/Amadu-A/Megano).
Документация, комментарии и docstrings — на русском.

    interface / workers → application → domain
                              ↓
                            ports ← repositories / infrastructure

Transport содержит CBV, DRF, сериализацию и права HTTP; application координирует
порты и транзакции, domain проверяет геометрию и расписание. ORM сосредоточен в
repositories. Concrete adapters создаются в `core/container.py`.

## Захват и распознавание

`workers.capture` запускается всегда. Отдельный CPU-декодер каждой камеры читает
RTSP через OpenCV/FFmpeg TCP с timeout и backoff. Очередь декодера содержит только
последний кадр. `PublishCameraFrame` публикует подписанный JPEG с линией в
`warehouse:frame:<camera_id>`, затем исходный JPEG с camera session/sequence/time
в `warehouse:capture:<camera_id>`. Оба ключа имеют конечный TTL. DB status
обновляется захватом; API не показывает LIVE после истечения JPEG.

`workers.vision` запускается только в профиле `inference` при `VISION_ENABLED=true`.
Он читает исходники из Redis, отбрасывает повторные и просроченные кадры и
обращается к явному `VISION_INFERENCE_URL`. Состояние каждого camera pipeline
изолировано; reconnect, изменения камеры/линии и большой перерыв сбрасывают
сессию трекинга. Отказ внешнего CV API не влияет на публикацию live JPEG.
Этот процесс не открывает RTSP, не расшифровывает реквизиты камеры и не пишет
live-cache. Доменные события и pending evidence по-прежнему обрабатывает
`CameraPipeline`, включая гистерезис, направление, возраст трека и расписание.

В проекте нет локального model runtime, весов, Ultralytics, PyTorch или CUDA.
Расположение GPU, модель и tracker принадлежат shared-infrastructure.
[Контракт CV API](SHARED_CV_API.md) описывает реализованный клиент и требования
к будущему совместимому провайдеру. Наличие такого провайдера не подтверждено;
`shared-vlm` Chat Completions не является автоматической заменой person tracking.
Распознавание остаётся выключенным до согласования и benchmark.

Это изменение требования пользователя заменяет положения исходного ТЗ о
проектной модели YOLO и локальном GPU. Правила нарушений, история, отчёты,
аутентификация и контракты существующего HTTP API сохранены.

## Данные и уведомления

`accounts_app` сохраняет label `accounts`, `persistence_app` — `persistence`.
Таблицы, миграции и `AUTH_USER_MODEL=accounts.User` не меняются.
Нарушение и outbox записываются в одной DB-транзакции, доказательства находятся
в private media. Ключ события обеспечивает идемпотентность. Флаги внешних
уведомлений имеют приоритет над настройками кабинета.

Celery использует проектные vhost/user и ресурсы `warehouse.*`. Gossip, mingle,
worker event heartbeat и remote control выключены, чтобы не обращаться к
`celery.pidbox`/`celeryev` за пределами разрешённого namespace. AMQP heartbeat
транспорта сохраняется. Временный consumer проверяется контейнерным integration
тестом на отдельной очереди, не читая рабочую очередь уведомлений.

## Контейнеры и сеть

Один Dockerfile: `source`, `base`, `ops`, `testing`. Один Compose:
web, camera-capture, notification-worker, scheduler, PostgreSQL, Redis,
необязательный inference; профили `ops`, `tests`, `inference`.
GPU reservation и bind model weights удалены. CPU-зависимости входят в base.

Web/capture и данные работают в private network. Только потребители внешних
сервисов и одноразовые проверки подключаются к `ai-shared`. RabbitMQ/CV runtime
в Compose проекта отсутствуют. `preflight` проверяет AMQP из общей сети,
`rabbit` настраивает только проектные credentials/права уже работающего брокера.
Shared lifecycle остаётся у общей инфраструктуры.

Проверки, команды развёртывания и ручная приёмка:
[OPERATIONS.md](OPERATIONS.md), [VALIDATION.md](VALIDATION.md).
