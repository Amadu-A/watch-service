<!-- docs/DEVELOPMENT.md: Локальные правила продолжения разработки и контроля изменений. -->
# Разработка

Проект следует документам
[shared_infrasktructure/docs](https://github.com/Amadu-A/shared_infrasktructure/tree/main/docs):
`LLM_CONTEXT.md`, `ENGINEERING_GUIDELINES.md`, `FRONTEND_GUIDELINES.md`,
`INFRASTRUCTURE_INSTRUCTIONS.md` и `services.yaml`.
Снимок требований продукта сохранён в `docs-specification.md`.

Перед изменением читать соответствующий код и текущие shared правила. Не коммитить
и не пушить автоматически: пользователь запускает команды `watch.sh commit` и `watch.sh push`.
Изменения сверять через status/diff и тесты. Публикацию в `origin main`
выполняет только владелец репозитория. Репозитории PDRD-validation сюда не подключаются.

## Границы

Transport обрабатывает authentication, serializers и HTTP envelopes. Application
проверяет роли/инварианты и координирует ports. Domain не импортирует framework или infrastructure.
ORM, сетевые clients и rendering принадлежат infrastructure. `core/container.py` — явный
composition root; serializers/views не читают ORM, не создают adapters и не ищут зависимости.
Celery tasks вызывают use-cases; capture управляет CPU-декодерами, inference — camera-local pipelines.

Все HTTP endpoints — CBV; `.as_view()` получает factories и providers в `config/urls.py`.
API v1 использует session authentication/CSRF, UUID, даты с timezone, allow-list фильтров,
единообразные ошибки с `request_id`. Периоды — `[date_from, date_to)`.
OpenAPI доступен после входа: `/api/schema/`, локальная документация: `/api/docs/`.

## Код и frontend

Документация, docstrings и поясняющие комментарии — на русском. В начале файла указан
относительный путь. Значимые use-cases используют общий `@timed`; кадры не пишутся в INFO logs.
Ошибки логируются с типом и stack locations, без credentials, payload, query строки RTSP и токенов.

CSS разбит на BEM blocks; `style.css` импортирует модули. JavaScript — ES modules,
подключённые через `defer` в head после CSS. Нет inline handlers и raw innerHTML;
DOM собирается через безопасный helper. Действия имеют понятные labels и keyboard доступ.
Пароли камер — только write-only поля. Media выдаются через authentication, без публичного volume URL.

## Проверки

`watch.sh local-check` запускает frozen dependency sync, Ruff, проверку синтаксиса JS,
Django check, отсутствие новых миграций, unit/functional/regression/architecture тесты
с branch coverage, Node tests и Playwright E2E. `watch.sh test-containers` дополнительно
проверяет отдельные PostgreSQL/Redis и project namespace shared RabbitMQ.
CI `.github/workflows/checks.yaml` выполняет ту же инструкцию на Python 3.12.

При изменениях добавлять проверки поведения, включая отказ адаптера и права доступа.
Проверки существующих сценариев не удалять ради успешного нового теста.
Capture/inference тесты проверяют публикацию без detector, свежесть, reconnect,
изоляцию камер и валидацию внешнего CV-контракта. Модели, трекинг и физическое
GPU-размещение принадлежат shared runtime; локальные ML-зависимости запрещены
архитектурным тестом. Контракт клиента описан в `SHARED_CV_API.md`.
LiveServer SQLite отключает `cached_statements` для устранения
[известной гонки CPython](https://github.com/python/cpython/issues/118172);
production и контейнерные integration тесты работают на PostgreSQL.

При изменении моделей добавить и проверить миграцию; операция генерации доступна
через `watch.sh make-migrations`, применение — через `watch.sh migrate`/`deploy`.
Не включать `.env`, media, model weights, кэши, IDE файлы или отчёты тестов в Git.
