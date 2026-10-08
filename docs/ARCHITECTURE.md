<!-- docs/ARCHITECTURE.md: Архитектурное решение, последовательность миграции и проверяемые границы проекта. -->
# Warehouse Perimeter Watch — архитектура

## 1. Статус и приоритеты

**Статус:** целевая архитектура утверждена; фактическая миграция выполняется поэтапно.

Источники требований:

1. Техническое задание `docs-specification.md` и явно согласованные требования к `watch-service`.
2. Актуальная структура и работающий код `watch-service` — при переносе существующих контрактов.
3. [shared_infrasktructure/docs](https://github.com/Amadu-A/shared_infrasktructure/tree/main/docs) — обязательные правила инженерии, frontend и инфраструктуры.
4. [Megano](https://github.com/Amadu-A/Megano) — ориентир **физической организации Django-проекта**, но не источник разрешений на нарушение слоёв.

Использовать плоский `src/config/settings.py`, **без** пакета `src/config/settings/` и без кода настроек в `settings/__init__.py`. Не создавать каталоги без функциональной необходимости.

## 2. Принятая целевая структура

```text
watch-service/
├── manage.py
├── pyproject.toml
├── uv.lock
├── .python-version
├── .env.example
├── Dockerfile
├── compose.yaml
├── src/
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py
│   │   ├── runtime.py
│   │   ├── testing.py
│   │   ├── urls.py
│   │   ├── asgi.py
│   │   └── wsgi.py
│   ├── core/
│   │   ├── container.py
│   │   ├── config.py
│   │   ├── exceptions.py
│   │   ├── logging.py
│   │   └── timing.py
│   ├── interface/
│   ├── repositories/
│   ├── application/
│   │   ├── cameras/
│   │   ├── surveillance/
│   │   ├── violations/
│   │   ├── notifications/
│   │   └── reports/
│   ├── infrastructure/
│   │   ├── vision/
│   │   ├── camera/
│   │   ├── storage/
│   │   └── messaging/
│   ├── watch_app/
│   ├── accounts_app/
│   ├── cameras_app/
│   ├── surveillance_app/
│   ├── violations_app/
│   ├── notifications_app/
│   └── reports_app/
├── templates/
├── static/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── architecture/
│   ├── regression/
│   ├── functional/
│   ├── e2e/
│   └── frontend/
├── legacy/
└── docs/
```

Каталоги из целевой структуры появляются **по мере переноса**, а не все сразу. `templates/` и `static/` указаны как целевое расположение, но до отдельного этапа frontend остаются там, где они реально находятся (`src/templates/watch_app/`, `src/static/static/`).

В `tests/` уже перемещены старые тесты. Пока соответствующие модули находятся в `legacy/src`, часть этих тестов **не собирается** из-за импортов `core`, `modules`, `web` и `workers`. Это известный миграционный блокер, а не разрешение пропускать эти проверки при окончательной приёмке.

## 3. Django и DI

- Django приложения отвечают за HTTP transport, регистрацию Django models, migrations и Django-specific интеграцию по функциональной области.
- Все project HTTP views (включая API, health и streaming) — CBV. Function-based project views запрещены.
- Views/serializers не выполняют ORM-запросов, не создают repositories/clients и не содержат бизнес-правил.
- Application содержит use-cases и ports, не импортирует Django HTTP, ORM или infrastructure implementations.
- Domain содержит чистые правила и value objects, не зависит от framework.
- Infrastructure реализует ports, содержит Django ORM repositories, RTSP, YOLO, Redis, хранилище, SMTP, Telegram и broker adapters.
- Concrete dependencies собираются в едином composition root `src/core/container.py`; в CBV внедряются готовые use-case factories/providers.
- Django ORM не передаётся через порты в виде `QuerySet` и не протекает в application/domain.
- Граница транзакции соответствует use-case. Для нарушения и уведомления должна сохраняться атомарность метаданных нарушения и durable outbox.
- Расписание, геометрия пересечения и дедупликация проверяются независимо от БД, Django и YOLO.

## 4. Инфраструктура

- Одна codebase — модульный монолит. Web, vision и notification worker могут работать отдельными процессами/контейнерами из одного репозитория.
- PostgreSQL, Redis и media — project-owned и размещаются в private network.
- Используется существующий shared RabbitMQ через сеть `ai-shared` с отдельным vhost/user проекта. Нельзя поднимать второй общий RabbitMQ или менять lifecycle чужих контейнеров.
- Vision обслуживает несколько камер общей загруженной моделью YOLO при отдельных tracker/decoder state.
- Веб-сервер не выполняет GPU inference в HTTP-request.
- Секреты и реальные RTSP URL не публикуются. `.env.example` — baseline; `.env` — приватный override. Первый `.env` ещё не создан.
- `NOTIFICATIONS_ENABLED=false` и channel hard flags должны запрещать реальные сетевые отправки независимо от UI.
- До согласования migrations и окончательной `AUTH_USER_MODEL` нельзя выполнять `migrate` против постоянной project DB.
- Любые host ports нужно проверять на реальном сервере. По диагностике от 08.10.2026 `8080` используется другим проектом; не считать его свободным.

## 5. Последовательность миграции

1. Django bootstrap, безопасная test configuration, фиксация структуры.
2. Стабилизация тестовой коллекции после переноса файлов из `legacy/tests` в корневой `tests/`; устранение конфликтов имён и импортов тестового bootstrap.
3. Согласование Python/Django/`uv.lock`/Docker/Compose и изолированная smoke-сборка в Docker, без воздействия на чужие сервисы.
4. Django user model, persistence, migration compatibility и регистрация приложений.
5. Ports, repositories, use-cases, явный DI/composition root.
6. RTSP, YOLO/ByteTrack, геометрия, schedules и violation creation.
7. CBV/API/OpenAPI, сохранение URL, методов, response DTO, permissions.
8. Templates/static/UI, live grid, ручные сценарии.
9. Reports, Telegram/Email, outbox, Celery, retention.
10. Полная regression/integration/E2E/runtime проверка и очистка оставшихся legacy файлов.

Порядок может уточняться по графу зависимостей, но любой перенос обязан сохранять работоспособные контракты и историю данных.

## 6. Условие удаления legacy файла

Для **каждого** перенесённого `legacy` файла:

1. прочитать текущую полную версию;
2. определить все import/call/data/API зависимости;
3. создать функциональную замену в утверждённой структуре;
4. перенести/скорректировать тесты, добавить регрессионные проверки при изменении поведения;
5. запустить lint, format, unit, функциональные и архитектурные тесты по затронутой области;
6. согласовать с пользователем явное удаление исходного legacy файла;
7. после commit/push сверить remote HEAD и содержимое реально изменённых файлов;
8. после готовности Docker — выполнить project-specific integration/runtime проверки.

Механическое удаление всех `legacy` файлов ради «чистоты» не допускается. Существующие тесты не удаляются ради зелёной CI.

## 7. Протокол выдачи этапов

Каждое сообщение разработки — один законченный этап:

- проверить актуальные `main`/HEAD и полные версии затрагиваемых файлов в GitHub, а также применимые shared rules;
- показать полное содержимое каждого нового/изменённого исходного файла с относительным путём;
- для Markdown разрешается выдавать готовый файл для скачивания;
- дать Windows PowerShell lint/format/tests и явный staging без `git add .`;
- дать команды commit/push **для пользователя**, не выполнять их от имени ассистента;
- дать Linux pull, безопасную сборку/контейнерные тесты, когда Docker stage готов;
- перечислить конкретные шаги ручной приёмки;
- получить вывод проверок/коммита и проверить фактический remote HEAD до следующего изменения.

## 8. Definition of Done

- HTTP endpoints только через CBV;
- неизменны обязательные API/UI контракты ТЗ;
- архитектурные слои соблюдены и проверены автоматическими тестами;
- все существенные функции покрыты unit/functional/regression/architecture/integration/E2E тестами;
- production secrets не встречаются в Git/логах/HTTP-response;
- при отключённых уведомлениях внешних send calls нет;
- миграции совместимы, данные не теряются;
- отдельные камеры и один worker не валят остальные модули;
- Docker/Compose не вмешиваются в другие работающие проекты;
- полный набор тестов и ручная приёмка пройдены;
- legacy очищен только после подтверждённого переноса всех функций.
