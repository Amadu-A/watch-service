<!-- docs/OPERATIONS.md: Единая инструкция эксплуатации через scripts/watch.sh. -->
# Эксплуатация

Все операции ниже выполняются из корня checkout через единственный `scripts/watch.sh`.
Скрипт читает `.env.example`, затем sparse `.env`; содержимое `.env` не исполняется shell.
Для PowerShell команда имеет вид `& "C:\Program Files\Git\bin\bash.exe" scripts/watch.sh <операция>`.
Прямые команды migration, Docker networks или pytest вручную не требуются.

## Рабочая станция: проверка, коммит и push

Нужны Git Bash, `uv`, Node.js. Первый запуск скачивает Python 3.12 и Chromium.
Коммит и push выполняет только владелец репозитория `Amadu-A/watch-service`.

    & "C:\Program Files\Git\bin\bash.exe" scripts/watch.sh browsers
    & "C:\Program Files\Git\bin\bash.exe" scripts/watch.sh local-check
    git status --short
    & "C:\Program Files\Git\bin\bash.exe" scripts/watch.sh commit "refactor: complete architecture migration"
    & "C:\Program Files\Git\bin\bash.exe" scripts/watch.sh push

`local-check` проверяет Ruff, Django, отсутствие новых миграций, Node, Python
и Chromium E2E. `commit` повторно выполняет проверки и добавляет только
явно перечисленные project paths. `push` отправляет только `origin main`.

## Первое развёртывание

Checkout публичного проекта должен уже существовать и иметь чистый main.
На Linux нужны Docker Engine/Compose plugin, `uv` и доступ к shared RabbitMQ.
Production vision требует NVIDIA Container Toolkit; host не устанавливает YOLO.

```bash
bash scripts/watch.sh init
bash scripts/watch.sh discover
```

Отредактировать созданный `.env`, сохраняя сгенерированные индивидуальные secrets:

```dotenv
# Реальные значения вместо примера домена/IP; не публиковать этот файл.
APP_ENV=production
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,watch.example.org
DJANGO_CSRF_TRUSTED_ORIGINS=https://watch.example.org
DJANGO_SECURE_COOKIES=true
SHARED_NETWORK=ai-shared
RABBITMQ_HOST=rabbitmq
VISION_DEVICE=0
VISION_GPU_ID=0
CAMERA_1_IP=10.0.0.25
CAMERA_1_USERNAME=warehouse-reader
CAMERA_1_PASSWORD='реальный пароль камеры'
CAMERA_2_IP=10.0.0.26
CAMERA_2_USERNAME=warehouse-reader
CAMERA_2_PASSWORD='реальный пароль камеры'
```

Этот блок дополняет `.env`, а не заменяет сгенерированные ключи/пароли.
После выбора реальных сетей и имени shared контейнера:

```bash
bash scripts/watch.sh rabbit ИМЯ_SHARED_RABBITMQ_CONTAINER
bash scripts/watch.sh model
WATCH_GPU=true bash scripts/watch.sh deploy
bash scripts/watch.sh admin
bash scripts/watch.sh import-cameras
```

`rabbit` создаёт отсутствующую project/shared network, при необходимости добавляет
shared RabbitMQ в неё с alias. Не отключает существующие сети и не перезапускает shared сервис.
Если контейнер уже в сети без нужного alias, нужно указать его настоящее имя в `RABBITMQ_HOST`.
Создаёт/обновляет только `warehouse*` user/vhost и permissions `^warehouse\..*`.
В проектном Compose нет отдельного RabbitMQ. У worker/beat отключены remote control/events,
чтобы они не требовали ресурсов за пределами этого namespace.

`model` скачивает baseline `yolo11n.pt` из официального Ultralytics assets release,
показывает SHA256 и сохраняет existing файл. Для другой совместимой модели задайте
`VISION_MODEL` и положите проверенный файл туда самостоятельно; имя каталога по умолчанию `models/`.
Weights и `.env` исключены из Git и build context; models подключается к vision read-only.

`deploy`: проверяет чистоту checkout → `pull --ff-only origin main` → проверяет конфигурацию/сети →
собирает образы → выполняет тесты в отдельной test PostgreSQL/Redis и project RabbitMQ namespace →
поднимает project DB/cache → применяет migration → пересоздаёт web/vision/worker/beat → проверяет web ready.
Static assets и архив исходников собираются внутри Docker build. Тесты не очищают production DB/media.
Ошибка проверок до migration останавливает deployment. Shared сервисы и чужие volumes не удаляются.

Web слушает `127.0.0.1:8086` по умолчанию: нужен HTTPS reverse proxy.
Для теста без HTTPS явно используйте `APP_ENV=development`, `DJANGO_SECURE_COOKIES=false`,
`VISION_DEVICE=cpu` и запускайте `bash scripts/watch.sh deploy` без GPU overlay.
Для доступа с другого компьютера настройте proxy либо согласованный `WEB_BIND_IP` и firewall.
DB/cache ports наружу не публикуются. Для MJPEG proxy должен отключать buffering
и разрешать соединения длительнее минуты; каждому показанному stream требуется web thread.

## Следующие обновления и диагностика

```bash
# Pull, пересборка, контейнерные тесты и миграции одной командой:
WATCH_GPU=true bash scripts/watch.sh deploy
# Самостоятельная проверка образов без обновления production сервисов:
WATCH_GPU=true bash scripts/watch.sh test-containers
bash scripts/watch.sh status
bash scripts/watch.sh logs vision
bash scripts/watch.sh logs notification-worker
bash scripts/watch.sh logs scheduler
bash scripts/watch.sh retention
# Дополнительные пользователи; пароль вводится интерактивно:
bash scripts/watch.sh user warehouse-operator OPERATOR
bash scripts/watch.sh user warehouse-viewer VIEWER
```

`watch.sh stop` останавливает только четыре процесса приложения. Volumes и shared infrastructure сохраняются.
Health web проверяет DB/Redis; offline камера не делает весь web неготовым.
Vision health проверяет короткий heartbeat после загрузки модели. Worker/beat connection видно в logs.

## Уведомления, хранение, восстановление

До включения каналов все три notification flags остаются false.
Настроить SMTP TLS/пароль/from и/или Telegram bot token в `.env`, реальные получатели — в UI.
Для частного пользователя Telegram нужен chat_id; `@username` подходит для канала.
Включение runtime флагов требует пересоздания web/worker; `deploy` делает это вместе с тестами.
Потом включить нужные business switches и нажать тестовую отправку для своих адресатов.
Наблюдать delivery/attempt states и фактическое получение JPEG/PDF.

Автоматический retry: максимум `NOTIFICATION_MAX_ATTEMPTS`, backoff от 30 секунд до часа;
после лимита DEAD. Ручной retry открывает новый ограниченный цикл, сохраняя attempts.
Outbox возвращает потерянный QUEUED UUID в очередь через 5 минут. SENT UUID повторно не отправляется.
Если внешний провайдер принял сообщение, а worker упал до DB commit, возможна повторная доставка.

Очистка по расписанию beat происходит раз в минуту. При недоступности shared broker
запускать `retention` вручную/внешним расписанием и контролировать очередь очистки.
30 дней — максимальный настроенный срок; остановленная инфраструктура может задержать фактическое удаление.
Бэкапы и внешние log archives тоже ограничить 30 днями. Fernet key сохранять в управляемом
secret хранилище: без него существующие credentials восстановить нельзя.

Изменения схемы применяются автоматически в deploy. Автоматический откат migration
не выполняется; перед обновлениями существующих данных требуется актуальный backup.
Объём disk media и количество MJPEG clients контролировать при приёмке реальной нагрузки.
