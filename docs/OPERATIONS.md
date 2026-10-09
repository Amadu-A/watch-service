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

Нужны Docker Engine с Compose plugin, доступ к общему RabbitMQ и `uv` в `PATH`.
Отсутствие `uv` прерывает `watch.sh init`, поэтому сначала установите его
[официальным установщиком](https://docs.astral.sh/uv/getting-started/installation/):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv --version
```

После pull создайте приватный `.env`. Команда `init` генерирует четыре секрета
без вывода их значений и не перезаписывает существующий файл. Затем заполните
производственные параметры **точно по разделу [README.md](../README.md#что-записать-в-env-на-сервере)**.
Особенно нужны `APP_ENV=production`, `DJANGO_DEBUG=false`,
`DATABASE_ENGINE=postgresql`, `VISION_DEVICE=0`, реальные host/CSRF и камеры.
Без `POSTGRES_PASSWORD` из `.env` Compose намеренно отказывает в запуске.

```bash
cd /home/main/projects/watch-service
git pull --ff-only origin main
bash scripts/watch.sh init
# Отредактировать .env; сохранить уже сгенерированные секреты.
bash scripts/watch.sh rabbit shared-rabbitmq-1
bash scripts/watch.sh model
bash scripts/watch.sh test-containers
bash scripts/watch.sh deploy
bash scripts/watch.sh admin
bash scripts/watch.sh import-cameras
bash scripts/watch.sh status
curl -fsS http://127.0.0.1:8086/health/live
```

`rabbit` подключает выбранный существующий контейнер к сети `ai-shared` при
необходимости и создаёт/обновляет только проектный vhost/user `warehouse-watch`.
Сервис RabbitMQ не входит в Compose проекта и не перезапускается. Если контейнер
уже в сети без alias `rabbitmq`, задайте его настоящее имя в `RABBITMQ_HOST`.
`model` скачивает `models/yolo11n.pt`, если файла ещё нет. Файл модели и `.env`
не входят в Git и Docker build context.

`test-containers` проверяет код на временных PostgreSQL/Redis и проектном namespace
RabbitMQ. `deploy` ещё раз выполняет тесты, применяет миграции и пересоздаёт
`web`, выбранный vision-процесс, worker и scheduler. Он не очищает рабочую БД/media.
Перед обновлением существующей БД нужен актуальный backup. При ошибке тестов
развёртывание останавливается до миграций.

## Выбор GPU или CPU

Для production задайте `VISION_DEVICE=0` и нужный `VISION_GPU_ID` в `.env`.
`watch.sh deploy` выберет профиль `gpu` и сервис `vision`; серверу нужен NVIDIA
Container Toolkit. Для разработки без GPU задайте `APP_ENV=development`,
`DJANGO_SECURE_COOKIES=false`, `VISION_DEVICE=cpu`; скрипт выберет профиль `cpu`
и сервис `vision-cpu`. Альтернативный vision-сервис он останавливает.
Префикс `WATCH_GPU=true` больше не нужен.

Web по умолчанию доступен только на `127.0.0.1:8086`; используйте HTTPS reverse
proxy. Для MJPEG proxy должен отключать buffering и разрешать длительные
соединения. Порты PostgreSQL и Redis наружу не публикуются.

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

При `VISION_DEVICE=cpu` смотрите `bash scripts/watch.sh logs vision-cpu`.
`status` и Compose требуют заполненного `.env` с `POSTGRES_PASSWORD` даже до
запуска контейнеров. `watch.sh stop` останавливает только процессы проекта.
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
