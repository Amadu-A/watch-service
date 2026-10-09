<!-- docs/OPERATIONS.md: Проверки и эксплуатация через единый scripts/watch.sh. -->
# Эксплуатация

Все команды запускаются из корня проекта. В репозитории ровно один `Dockerfile` и
один `compose.yaml`. Профили `gpu`, `cpu` и `tests` находятся в этом же Compose файле.
`watch.sh` читает `.env.example`, затем приватный `.env`; файл не исполняется как shell.

## Рабочая станция Windows

Нужны Git Bash, `uv`, Node.js. Браузер Chromium устанавливается первой командой.
В PowerShell:

```powershell
& "C:\Program Files\Git\bin\bash.exe" scripts/watch.sh browsers
& "C:\Program Files\Git\bin\bash.exe" scripts/watch.sh local-check
git status --short
& "C:\Program Files\Git\bin\bash.exe" scripts/watch.sh commit "refactor: consolidate docker configuration"
& "C:\Program Files\Git\bin\bash.exe" scripts/watch.sh push
```

`local-check` запускает Ruff, Django check, проверку миграций, Node, Python и
Chromium E2E. `commit` повторяет проверки; коммит и push выполняет владелец репозитория.

## Сервер: подготовка

Нужны Docker Engine с Compose plugin, доступ к общей сети RabbitMQ и Git.
`uv` и Python на хосте не нужны: `uv` находится в единственном `Dockerfile`.
Профиль `ops` выполняет подготовку в одноразовом контейнере. Только команда
`rabbit` временно подключает к нему Docker socket для `rabbitmqctl` в выбранном
контейнере; web и workers доступа к socket не имеют.

```bash
cd /home/main/projects/watch-service
git pull --ff-only origin main
bash scripts/watch.sh init
# Команда создала .env с APP_ENV=production и четырьмя секретами.
# При наличии HTTPS proxy добавьте реальные DJANGO_ALLOWED_HOSTS и DJANGO_CSRF_TRUSTED_ORIGINS.
bash scripts/watch.sh rabbit shared-rabbitmq-1
bash scripts/watch.sh test-containers
bash scripts/watch.sh deploy
bash scripts/watch.sh status
curl -fsS http://127.0.0.1:8086/health/live
```

`init` сохраняет уже существующий `.env` без изменений. Пароль PostgreSQL
проверяется `preflight` до запуска БД. Настройки по умолчанию находятся в
`src/core/config.py`; [README](../README.md#что-записать-в-env-на-сервере)
перечисляет все необходимые и условные строки `.env`.

`rabbit` подключает выбранный существующий контейнер к сети `ai-shared` при
необходимости и создаёт/обновляет только проектный vhost/user `warehouse-watch`.
Сервис RabbitMQ не входит в Compose проекта и не перезапускается. Если контейнер
уже в сети без alias `rabbitmq`, задайте его настоящее имя в `RABBITMQ_HOST`.

При начальном `VISION_ENABLED=false` vision-образ не собирается и процесс не
запускается. Камеры пока можно зарегистрировать, но кадры появятся после
включения vision. Для GPU положите веса в `models/` или выполните
`bash scripts/watch.sh model`, задайте `VISION_ENABLED=true`,
`VISION_DEVICE=0` и при необходимости `VISION_GPU_ID`. Затем повторите
`bash scripts/watch.sh deploy`. Серверу нужен NVIDIA Container Toolkit.

`test-containers` проверяет код на временных PostgreSQL/Redis и проектном
namespace RabbitMQ. `deploy` повторяет тесты, применяет миграции и пересоздаёт
только процессы проекта. Он не очищает рабочую БД/media. Перед обновлением
существующей БД нужен актуальный backup. При ошибке тестов развёртывание
останавливается до миграций.

Web по умолчанию доступен только на `127.0.0.1:8086`. Первичную проверку
можно провести через SSH-туннель на `localhost:8086` в Chrome/Firefox. Для
штатного доступа нужен HTTPS reverse proxy; локальное исключение Secure cookies
не одинаково поддерживается браузерами. Для MJPEG отключите buffering
в proxy и разрешите длительные соединения. Порты PostgreSQL
и Redis наружу не публикуются.

## Обновление и диагностика

```bash
cd /home/main/projects/watch-service
git pull --ff-only origin main
bash scripts/watch.sh test-containers
bash scripts/watch.sh deploy
bash scripts/watch.sh status
bash scripts/watch.sh logs web
bash scripts/watch.sh logs vision
bash scripts/watch.sh logs notification-worker
bash scripts/watch.sh logs scheduler
```

При `VISION_ENABLED=false` vision-сервис отсутствует; после включения GPU
смотрите `bash scripts/watch.sh logs vision`.
Команды развёртывания требуют заполненного `.env`; `preflight` проверяет его
до запуска контейнеров. `watch.sh stop` останавливает только процессы проекта.
PostgreSQL, Redis, media и общий RabbitMQ не удаляются. `deploy` повторяет pull,
поэтому после ручного pull возможна строка `Already up to date`.

## Уведомления и хранение

Пока `NOTIFICATIONS_ENABLED=false`, внешняя отправка запрещена независимо от UI.
Для Email/Telegram заполните значения, перечисленные в README, включите нужные
серверные флаги, создайте собственных получателей в кабинете и проверьте тестовую
отправку. Worker хранит попытки и ограничивает повторы. При аварии между приёмом
сообщения провайдером и записью результата в БД возможна повторная доставка.

Очистка запускается scheduler раз в минуту. При недоступном broker выполните
`bash scripts/watch.sh retention` вручную и контролируйте очередь после восстановления.
Срок хранения задаёт `MEDIA_RETENTION_DAYS` (не более 30 дней); бэкапы и внешние
архивы логов нужно ограничивать отдельно. Ключ `CAMERA_CREDENTIALS_KEY` сохраните
в управляемом хранилище: без него нельзя расшифровать уже записанные реквизиты камер.
