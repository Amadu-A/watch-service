<!-- docs/ARCHITECTURE.md: Фактическая архитектура завершённой миграции. -->
# Архитектура Warehouse Perimeter Watch

## Источники правил

Приоритет: `docs-specification.md`, рабочие контракты проекта, затем
[shared_infrasktructure/docs](https://github.com/Amadu-A/shared_infrasktructure/tree/main/docs).
Физическая организация Django-приложений ориентируется на
[Megano](https://github.com/Amadu-A/Megano). Все комментарии и docstrings пишутся
по-русски. ТЗ задаёт Python 3.12 и Django 5.2 LTS.

## Слои и направление зависимостей

    interface / workers
            ↓
       application → domain
            ↓
          ports ← repositories / infrastructure

`src/interface` содержит только CBV, DRF, сериализацию, проверку входа и HTTP ответы.
`src/application` реализует операции и объявляет порты. `src/domain` не импортирует
Django, ORM или сетевые адаптеры. `src/repositories` содержит ORM-запросы;
`src/infrastructure` содержит файловое хранилище, криптографию, Redis, RTSP,
YOLO/ByteTrack, PDF, SMTP, Telegram и outbox publisher. Единственный composition root
`src/core/container.py` собирает конкретные реализации. Маршруты передают готовые
factories через `.as_view()`. Worker tasks вызывают use-cases, а не дублируют их.

## Django и миграции

`accounts_app` имеет прежний label `accounts`, `persistence_app` — `persistence`.
Начальные миграции перенесены без смены labels, имён таблиц и связей.
`AUTH_USER_MODEL = accounts.User` сохраняется. При запуске
`makemigrations --check --dry-run` изменений схемы нет. Перед применением миграций
к постоянной базе нужен обычный backup и контейнерные тесты на отдельном PostgreSQL.

`templates/` и `static/` находятся в корне. Внешняя статика собирается командой
`collectstatic`, приватные media отдаются только после проверки прав.
Исходный архив запущенной сборки включает Python, HTML, CSS, JS, тесты, инструкцию
сборки и полный текст AGPL-3.0, исключая секреты и runtime данные.

## Обработка камеры и события

Vision process держит одну модель YOLO и отдельные decoder, tracker и pipeline
для каждой камеры. Последний JPEG имеет TTL в project Redis. Домен проверяет
возраст track, гистерезис, границы отрезка, направление и расписание в timezone
объекта. Нарушение и durable outbox записываются в одной DB-транзакции;
оригинальное и размеченное фото хранятся в private media. Повтор события
с тем же ключом идемпотентен. Отказ одной камеры не останавливает остальные.

## Процессы и сети

Одна codebase запускает web, один выбранный vision-процесс, notification worker
и scheduler. PostgreSQL, Redis и media принадлежат проекту. Рабочие worker и
scheduler подключаются к внешней сети `ai-shared` для project vhost/user общего
RabbitMQ; тестовый контейнер подключается к ней только на время integration тестов.
Web публикуется на `127.0.0.1:8086` по умолчанию; Redis и PostgreSQL наружу не
публикуются. Флаги уведомлений в `.env` имеют приоритет над настройками UI.

## Сборка и профили

В репозитории один `Dockerfile` со стадиями `source`, `base`, `vision` и `testing`.
Один `compose.yaml` описывает рабочие сервисы и изолированные тестовые сервисы.
Профиль `gpu` запускает `vision` с резервированием NVIDIA GPU; профиль `cpu`
запускает `vision-cpu` без доступа к GPU. `watch.sh deploy` выбирает профиль по
`VISION_DEVICE` и останавливает альтернативный vision-процесс.
Профиль `tests` использует отдельные PostgreSQL и Redis; рабочие данные не затрагиваются.
Старый каталог `legacy/` удалён после переноса активного кода.

## Проверки

Архитектурные тесты проверяют запрещённые зависимости, отсутствие ORM
в transport/workers, все project endpoints через CBV, русские docstrings,
расположение script tags и безопасность DOM. Регрессионные тесты сохраняют
labels/таблицы и состав архива. Остальные проверки охватывают domain,
use-cases, HTTP, outbox, отчёты, frontend и браузерные сценарии. Контейнерные
тесты отдельно проверяют PostgreSQL, Redis и namespace RabbitMQ.

Команды проверок, развёртывания и ручной приёмки приведены в
[OPERATIONS.md](OPERATIONS.md) и [VALIDATION.md](VALIDATION.md).
