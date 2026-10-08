<!-- docs/VALIDATION.md: Проверенный результат, серверные вопросы и ручная приёмка текущего этапа. -->
# Проверка текущего этапа

Реализован новый Warehouse Perimeter Watch по приложенному ТЗ.
Ветку main и remotes агент не изменял; коммит и push не выполнялись.
В исходной рабочей папке был только `.git`, поэтому существующего application кода для сравнения не было.
Текущий private origin относится к Warehouse Perimeter Watch. Публичный remote ещё нужно подтвердить.

## Автоматические проверки

Локальный baseline: Windows, Python 3.12.13, Django 5.2.18, Chromium Playwright 1.63.
Итоговый запуск выполняется через `watch.sh local-check`:

Результат 07.10.2026: Ruff check/format, Django check и отсутствие migration drift — успешно;
83 Python теста основной группы и 5 Chromium E2E — успешно; 3 Node теста — успешно.
3 внешних integration теста пропущены до серверного запуска. Общее покрытие statements/branches
основной Python группы — 77%; E2E запускается отдельно от измерения coverage.

- Unit/domain: направления, отрезок, jitter, остановка, confidence, возраст, обратный проход.
  Проверяется также настоящее пересечение после отменённого первого candidate.
- Расписание: ночные интервалы, weekend, timezone, точные границы и повторный час DST.
- Пайплайн: лучшие evidence, неизменный timestamp события, isolated state, track TTL, bounded pending.
- Vision adapters: одна загрузка модели на несколько inference вызовов, person output, ByteTrack mapping,
  сохранение counter, reconnect и очередь последнего кадра, реальные JPEG и отрисовка линии/bbox.
- Application/DB: компенсация storage/DB failures, idempotency, event/outbox transaction,
  broker failure, recovery QUEUED, retry/backoff/DEAD, per-channel hard flags.
- Email/Telegram: вложения, TLS certificate verification, finite timeout и отказ Bot API;
  все сетевые sender clients в этих тестах подменены, внешние сообщения не отправлялись.
- API: роли, CSRF, authentication, UUID/errors, filters/pagination, защищённые кадры/media,
  stale LIVE, PDF/CSV, report ownership, recipient CRUD, retention и исходный архив без secrets.
- Архитектура: слои/imports, отсутствие ORM в transport/application/domain,
  class-based endpoints, injected worker adapters, docstrings на русском, head/defer и безопасный DOM.
- Frontend Node: сетка, reorder, нормализация координат.
- Chromium E2E: camera create/line/probe, dashboard select/remove/reorder/grid/fullscreen,
  recipients/gates, overnight schedule/retention, CSV, violation detail/JPEG/PDF, logout.
  Первый рендер даты проверяется отдельно для timezone объекта, отличного от browser timezone.

Конфигурации CPU/GPU Compose и синтаксис `watch.sh` проверены отдельно.
Рабочий Docker daemon локально отсутствует: Linux engine pipe не найден.
Сборка/запуск Docker images здесь не подтверждены. Три проверки внешних services
(PostgreSQL/Redis, RabbitMQ и concurrent PostgreSQL delivery lock) запускаются только
через `watch.sh test-containers`/`deploy` на сервере и локально пропускаются.
YOLO model internals, настоящие RTSP/GPU и фактические Email/Telegram delivery требуют серверной приёмки.

## Команды пользователя

```powershell
& "C:\Program Files\Git\bin\bash.exe" scripts/watch.sh browsers
& "C:\Program Files\Git\bin\bash.exe" scripts/watch.sh local-check
& "C:\Program Files\Git\bin\bash.exe" scripts/watch.sh commit "feat: warehouse perimeter watch"
# Задать подтверждённый public remote перед первым push:
& "C:\Program Files\Git\bin\bash.exe" scripts/watch.sh public-remote "ПОДТВЕРЖДЁННЫЙ_URL"
& "C:\Program Files\Git\bin\bash.exe" scripts/watch.sh push
```

Для сервера последовательность первичной подготовки приведена в [OPERATIONS.md](OPERATIONS.md).
После настройки `.env`, shared RabbitMQ и weights:

```bash
bash scripts/watch.sh discover
bash scripts/watch.sh inspect-rabbit ИМЯ_SHARED_RABBITMQ_CONTAINER
# Pull, сборка, контейнерные тесты, migration и запуск:
WATCH_GPU=true bash scripts/watch.sh deploy
bash scripts/watch.sh status
```

В development/CPU режиме применяется `bash scripts/watch.sh deploy` без GPU overlay.
Все команды уже упакованы в один `.sh`, отдельного набора ручных migration/network/test команд нет.

## Ручная приёмка на сервере

1. Открыть настроенный адрес `/login/`, войти администратором. Убедиться, что стили,
   меню и разделы загружаются, а без входа media/streams недоступны.
2. В «Камеры» импортировать/добавить минимум две реальные камеры. Проверить RTSP,
   получить snapshot, задать две точки линии. Перезагрузить страницу: линия должна сохраниться.
   Пароль и старый логин не должны отображаться; смена реквизитов должна работать.
3. В «Мониторинг» добавить обе камеры, изменить сетку, порядок и полный экран,
   убрать/добавить камеру. После reload сохраняются порядок и выбор текущего пользователя.
   Доступный поток показывает LIVE, bbox/person/confidence, линию и время объекта.
4. Отключить одну камеру/RTSP. Она должна показать offline; вторая продолжает обновляться.
   Восстановить RTSP: reconnect возвращает live без перезапуска web. В logs нет пароля/полного URL.
5. Включить контроль и активный интервал текущего дня. Провести человека через отрезок
   в разрешённом направлении: возникает одно нарушение. Остановка или колебание около линии
   не создаёт серию событий. Обратный законный проход создаёт отдельное событие при BOTH.
   Проход за пределами отрезка и вне расписания не создаёт нарушения.
6. Открыть нарушение: совпадают камера, направление и момент события; есть оригинальное
   и размеченное фото. Скачать PDF: кириллица читается, фото встроено. Изменить название/линию
   камеры: старое событие должно показывать прежние snapshots. При включённом clip проверить MP4.
7. В «Нарушения» проверить фильтры/страницы; в «Отчёты» сформировать PDF и CSV периода,
   скачать их из истории. В «Статистика» проверить today/7d/30d и свой диапазон.
8. При runtime flags=false включить business switches: тестовая отправка остаётся disabled,
   API отвечает notifications_disabled; события сохраняются. Добавить, изменить и удалить recipient.
   Для проверки внешних каналов включить реальные server/channel flags для своих адресатов,
   пересоздать процессы и проверить тестовую отправку, JPEG/PDF, SENT и attempts.
9. Проверить FAILED при тестовом отказе провайдера, bounded retry/DEAD и ручной retry.
   Неуспешное Email не должно отменять успешное Telegram. Успешная delivery не отправляется повторно.
10. Создать operator/viewer через `watch.sh user`: viewer читает и меняет свою раскладку,
    operator повторяет неуспешные deliveries; изменение cameras/recipients/schedule/settings
    доступно только администратору. Выйти: кабинет снова требует login.
11. Установить retention 1–30 дней. Значение 31 отклоняется. На специально подготовленных
    тестовых старых событиях выполнить `watch.sh retention`: просроченные metadata/files удаляются,
    свежие сохраняются. Проверить scheduler heartbeat/logs, disk и реальную GPU нагрузку.

## Данные, которые нужны при появлении доступа

Вывод `discover` и `inspect-rabbit`, имя shared контейнера, network и DNS alias,
NVIDIA/Toolkit и выделяемые ресурсы, домен/HTTPS/proxy, число камер и их разрешения/FPS.
Для публичного зеркала нужен подтверждённый Warehouse Perimeter Watch URL.
Секреты и записи камер отправлять в отчёт не требуется.

До этой приёмки результат считается реализованным и локально проверенным кодом,
а не подтверждённой работающей системой на складском объекте.
