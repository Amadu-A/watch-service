<!-- docs/OPERATIONS.md: Развёртывание CPU-захвата и необязательного shared inference. -->
# Эксплуатация

Все команды выполняются из корня проекта. В репозитории один Dockerfile,
один compose.yaml и профили `ops`, `tests`, `inference`. `watch.sh` читает
`.env.example`, затем приватный `.env` как данные, без выполнения shell.

## Windows: проверки и публикация владельцем

Нужны Git Bash, uv и Node.js. PowerShell:

```powershell
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
& "C:\Program Files\Git\bin\bash.exe" scripts/watch.sh browsers
& "C:\Program Files\Git\bin\bash.exe" scripts/watch.sh local-check
git status --short
& "C:\Program Files\Git\bin\bash.exe" scripts/watch.sh commit "fix: separate CPU capture from shared inference"
& "C:\Program Files\Git\bin\bash.exe" scripts/watch.sh push
```

`local-check` выполняет Ruff, Django check, проверку миграций, синтаксис JS,
Node, Python tests с branch coverage и Chromium E2E. `commit` повторяет проверки.
Коммит и push выполняет владелец репозитория.

## Сервер: первый запуск и обновление

Нужны Docker Engine с Compose plugin и Git. uv и Python на хосте не нужны.
Стадия `ops` выполняет подготовку в одноразовом контейнере. Только команда
`rabbit` получает Docker socket для проектного provisioning; рабочие сервисы
и `broker-check` доступа к socket не имеют.

```bash
cd /home/main/projects/watch-service
git pull --ff-only origin main
bash scripts/watch.sh init
# init сохраняет существующий .env; новый файл содержит APP_ENV и четыре секрета.
```

Для обновления со старой локальной YOLO-схемы удалите устаревшие флаги и GPU-настройки:

```bash
sed -i '/^VISION_\(ENABLED\|DEVICE\|GPU_ID\|MODEL\)=/d' .env
```

После этого inference выключен по умолчанию, а CPU capture будет запущен.
Другие настройки и секреты сохраняются. Реальные внешние уведомления по
умолчанию выключены; если были включены раньше, их флаги сохраняют силу.

RabbitMQ принадлежит общей инфраструктуре. Если **существующий** контейнер
`shared-rabbitmq-1` остановлен, оператор общей инфраструктуры запускает его:

```bash
docker start shared-rabbitmq-1
```

Затем из watch-service:

```bash
bash scripts/watch.sh rabbit shared-rabbitmq-1
bash scripts/watch.sh test-containers
bash scripts/watch.sh deploy
bash scripts/watch.sh status
curl -fsS http://127.0.0.1:8086/health/live
```

`rabbit` проверяет состояние и ждёт готовности приложения RabbitMQ. Он подключает
выбранный брокер к `ai-shared` при необходимости и настраивает проектные vhost/user
`warehouse-watch` с правами на `warehouse.*`. Если контейнер уже подключён без alias
`rabbitmq`, сообщение укажет точную строку `RABBITMQ_HOST=<имя контейнера>` для `.env`.
Shared контейнеры не запускаются и не пересоздаются скриптом приложения.

`preflight` проверяет настройки, затем DNS и AMQP-вход из общей сети. Отключённые
внешние уведомления не отменяют зависимость scheduler/worker от брокера.
`deploy` собирает сервисы, выполняет контейнерные tests до миграций, запускает
`camera-capture` и пересоздаёт процессы проекта. Старые project vision-контейнеры
удаляются через `--remove-orphans`; рабочая БД и media сохраняются.
Требуется чистый checkout. Перед изменением постоянной БД нужен обычный backup.

Первое создание администратора: `bash scripts/watch.sh admin`.
Импорт настроенных камер: `bash scripts/watch.sh import-cameras`.

## Проверка изображения

```bash
bash scripts/watch.sh status
bash scripts/watch.sh logs camera-capture
docker compose -f compose.yaml exec -T redis redis-cli --scan --pattern 'warehouse:frame:*'
```

В status должен присутствовать здоровый `camera-capture`. Для включённой
доступной камеры появляются ключи JPEG. В кабинете откройте её карточку,
через 5–10 секунд нажмите «Обновить кадр», затем проверьте мониторинг/MJPEG.
Успешная кнопка «Проверить RTSP» подтверждает разовое получение кадра; live
изображение публикует отдельный capture-процесс. При отключении камеры или
обрыве соединения свежесть истекает и LIVE исчезает.

Web публикуется на `127.0.0.1:8086`. Используйте HTTPS proxy либо SSH-туннель
на localhost в Chrome/Firefox для первичной проверки. Для MJPEG отключите
proxy buffering и разрешите длительные соединения. Порты БД/Redis не публикуются.

## Внешнее распознавание

Для картинки VISION_ENABLED включать не требуется. Удалённый inference включают
после подтверждения [CV-контракта](SHARED_CV_API.md) и проверки производительности:
`VISION_ENABLED=true`, реальный `VISION_INFERENCE_URL`, при необходимости
`VISION_INFERENCE_TOKEN`. Затем выполняют `test-containers` и `deploy`.
GPU, веса и модель настраиваются только в shared-infrastructure.
Без согласованного CV API новые нарушения автоматически не создаются.

## Уведомления, хранение и диагностика

```bash
bash scripts/watch.sh logs web
bash scripts/watch.sh logs notification-worker
bash scripts/watch.sh logs scheduler
# При включённом внешнем распознавании:
bash scripts/watch.sh logs inference
```

Gossip/mingle/worker events выключены для соответствия проектным правам RabbitMQ.
Контейнерные tests дополнительно запускают временный Celery consumer на отдельной
`warehouse.test.*` очереди. Рабочую очередь они не читают.

Для Email/Telegram заполните параметры из README, включите серверные флаги и
проверьте собственных получателей. Доставка имеет семантику «как минимум один раз»:
сбой после внешнего приёма может привести к повторной отправке.
Очистка запускается scheduler; при отказе broker доступен `watch.sh retention`.
Хранение ограничено 30 днями, Docker logs — ротацией 10 MB × 5 файлов.
Сохраняйте CAMERA_CREDENTIALS_KEY: без него реквизиты камер не расшифровать.
`watch.sh stop` останавливает только процессы проекта.
