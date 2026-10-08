# Warehouse Perimeter Watch

## 1. Общая информация

**GitHub repository:** `warehouse-perimeter-watch`

**Рабочее название продукта:** Warehouse Perimeter Watch

**Назначение:** система видеоконтроля складского объекта, предназначенная для автоматического обнаружения пересечения человеком заданной виртуальной линии в контролируемые периоды времени, фиксации нарушения, сохранения доказательных материалов и последующего уведомления ответственных лиц.

Проект разрабатывается как **модульный монолит на Django**.

Один repository содержит:

- Web UI;
- REST API;
- business/domain logic;
- работу с камерами;
- модуль компьютерного зрения;
- обработку нарушений;
- отчёты;
- notification subsystem;
- project workers;
- migrations;
- tests;
- deployment configuration.

Разделение на самостоятельные микросервисы на первом этапе запрещено без отдельного архитектурного решения.

Допускается запуск нескольких процессов из одной codebase:

```text
Django web
Vision worker
Notification worker
```

Они остаются частями одного приложения, используют единые application/domain contracts и одну project database.

---

# 2. Основной пользовательский сценарий

Система получает RTSP-поток от одной или нескольких IP-камер.

Для каждой камеры администратор задаёт виртуальную контрольную линию.

Система должна:

1. получать видеопоток;
2. обнаруживать объекты класса `person`;
3. присваивать человеку устойчивый `track_id`;
4. отслеживать его положение между кадрами;
5. определять пересечение виртуальной линии;
6. определять направление пересечения;
7. проверять активность расписания контроля;
8. при выполнении условий создавать нарушение;
9. сохранять оригинальное изображение;
10. сохранять размеченное изображение;
11. сохранять дату, время, камеру, направление, confidence и технические данные;
12. показывать нарушение в личном кабинете;
13. формировать отчёт;
14. после включения notifications отправлять отчёт и фотографию в Telegram и/или Email;
15. хранить историю всех попыток отправки.

Уведомления при первоначальном развёртывании должны быть аппаратно выключены:

```dotenv
NOTIFICATIONS_ENABLED=false
```

Даже если пользователь включит Email или Telegram через интерфейс, внешняя отправка при `NOTIFICATIONS_ENABLED=false` выполняться не должна.

---

# 3. Лицензирование

Проект создаётся как публичный GitHub repository.

Лицензия проекта:

```text
AGPL-3.0
```

При использовании Ultralytics YOLO весь corresponding source проекта, необходимый для его сборки и запуска, должен оставаться открытым в соответствии с выбранной AGPL-моделью.

В Git не должны попадать:

```text
.env
RTSP passwords
SMTP passwords
Telegram bot token
Django SECRET_KEY
RabbitMQ credentials
production encryption keys
другие runtime secrets
```

В repository находится только безопасный `.env.example`.

---

# 4. Технологический baseline

Backend:

```text
Python 3.12
Django 5.2 LTS
Django REST Framework
PostgreSQL
Pydantic Settings
```

Computer Vision:

```text
Ultralytics YOLO
class = person
ByteTrack
OpenCV
```

Frontend:

```text
Django Templates
HTML5
CSS
Vanilla JavaScript modules
```

Project infrastructure:

```text
Docker Compose
PostgreSQL — project-specific
Redis — project-specific, private
Celery worker — project-specific
RabbitMQ — shared из shared-infrastructure
```

Redis используется только как ephemeral runtime storage:

- последний live-frame камеры;
- краткоживущий stream state;
- технический cache.

Redis не является source of truth для нарушений.

PostgreSQL является source of truth для business state.

---

# 5. Соответствие shared_infrasktructure

Проект MUST соблюдать:

```text
docs/LLM_CONTEXT.md
docs/ENGINEERING_GUIDELINES.md
docs/FRONTEND_GUIDELINES.md
docs/INFRASTRUCTURE_INSTRUCTIONS.md
docs/services.yaml
```

Приоритет требований:

```text
явные требования этого ТЗ
        ↓
актуальный код и project contracts
        ↓
shared engineering guidelines
        ↓
framework defaults
```

Перед изменением кода разработчик/LLM MUST читать актуальные версии затрагиваемых файлов.

---

# 6. Архитектура

Обязательное направление зависимостей:

```text
Transport / Delivery
        │
        ▼
Application
        │
        ▼
Domain

Infrastructure ──implements──> Application Ports
```

## 6.1. Transport

Содержит:

- Django CBV;
- DRF CBV;
- serializers;
- HTML templates;
- URL routing;
- authentication context;
- permissions;
- HTTP validation;
- mapping ошибок в HTTP responses.

Transport НЕ должен:

- выполнять Django ORM queries;
- содержать line-crossing algorithm;
- запускать YOLO непосредственно;
- отправлять Telegram сообщения;
- отправлять Email;
- создавать repositories;
- создавать infrastructure clients;
- реализовывать business rules.

## 6.2. Application

Содержит:

- use cases;
- DTO;
- application services;
- ports/interfaces;
- orchestration;
- transaction boundaries.

Примеры use cases:

```text
CreateCamera
UpdateCamera
ConfigureGuardLine
UpdateMonitoringLayout

ProcessCameraFrame
RegisterLineCrossing
CreateViolation
GetViolation
ListViolations

GenerateViolationReport
GenerateViolationsReport

UpdateNotificationSettings
CreateNotificationRecipient
SendTestNotification
DispatchViolationNotifications
RetryNotificationDelivery
```

## 6.3. Domain

Содержит чистые правила:

```text
Camera
GuardLine
TrackedPerson
Violation
ControlSchedule
NotificationRecipient

LineCrossingPolicy
SchedulePolicy
Direction
ViolationState
DeliveryState
```

Domain не импортирует:

```text
django
rest_framework
celery
redis
opencv
ultralytics
requests
httpx
SMTP libraries
```

## 6.4. Infrastructure

Содержит реализации ports:

```text
Django ORM repositories
DjangoUnitOfWork
RTSPCameraSource
UltralyticsPersonDetector
ByteTrackTracker
RedisLiveFrameCache
LocalMediaStorage
RabbitMQ/Celery publisher
SMTPEmailSender
TelegramBotSender
PDF renderer
```

---

# 7. Dependency Injection

DI является обязательным архитектурным требованием.

Application use-case не создаёт infrastructure dependency самостоятельно.

Запрещено:

```python
repository = DjangoViolationRepository()
sender = TelegramBotSender()
detector = UltralyticsPersonDetector()
```

внутри use-case.

Interfaces располагаются у потребителя:

```text
application/ports/
```

Основные ports:

```text
CameraRepository
ViolationRepository
NotificationRepository
ReportRepository
UnitOfWork

CameraSource
PersonDetector
ObjectTracker
LiveFrameCache
MediaStorage

EmailSender
TelegramSender
NotificationTaskPublisher

Clock
ReportRenderer
```

Composition Root располагается явно:

```text
src/core/container.py
```

или в согласованном эквиваленте.

HTTP CBV получает **provider/factory готового use-case через injection**.

Предпочтительный принцип:

```text
urls.py
   ↓
Composition Root
   ↓
APIView.as_view(use_case_factory=...)
```

View не должна получать глобальный container через service locator.

Application/domain не должны знать о container.

---

# 8. Обязательное использование Class-Based Views

**Все HTTP views проекта MUST быть class-based.**

Запрещены project-defined function based views.

Запрещено:

```text
def monitoring_view(...)
def camera_stream(...)
@api_view(...)
@require_http_methods(...)
```

Разрешено:

```text
django.views.View
TemplateView
DetailView
FormView
LoginView
LogoutView

rest_framework.views.APIView
GenericAPIView
другие class-based DRF views
```

При этом DRF generics не должны использоваться как оправдание для размещения ORM/business logic в controller.

Все API CBV остаются thin transport adapters.

Это требование должно контролироваться **architecture test**.

---

# 9. Предлагаемая модульная структура

```text
src/
├── config/
│   ├── settings/
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
│
├── core/
│   ├── container.py
│   ├── config.py
│   ├── logging.py
│   └── timing.py
│
├── modules/
│   ├── accounts/
│   ├── cameras/
│   ├── surveillance/
│   ├── violations/
│   ├── notifications/
│   ├── reports/
│   ├── dashboard/
│   └── audit/
│
├── web/
│   ├── templates/
│   └── static/
│
└── workers/
    ├── vision/
    └── notifications/
```

Каждый значимый module SHOULD внутри сохранять разделение:

```text
domain/
application/
infrastructure/
transport/
```

---

# 10. Камеры

Система должна поддерживать произвольное количество зарегистрированных камер.

Камера содержит:

```text
id
name
location
enabled
connection status
RTSP endpoint
encrypted credentials
created_at
updated_at
```

RTSP username/password не возвращаются через API.

В UI отображается только безопасное представление endpoint.

Camera status:

```text
CONNECTING
ONLINE
OFFLINE
DEGRADED
DISABLED
```

Vision worker должен:

- переподключаться после разрыва RTSP;
- использовать bounded exponential backoff;
- не завершать весь worker из-за отказа одной камеры;
- обновлять camera state;
- не логировать RTSP credentials;
- не создавать INFO-log на каждый кадр.

---

# 11. Компьютерное зрение

Для первичного implementation используется pretrained YOLO detector класса:

```text
person
```

Конкретный вес модели должен задаваться configuration и не прошиваться в domain/application.

Model instance загружается **один раз при старте vision worker**.

Запрещено:

```text
load model
→ process frame
→ unload model
```

для каждого кадра или камеры.

Одна resident model SHOULD обслуживать несколько camera streams.

---

# 12. Tracking

После detection применяется ByteTrack.

Для каждого человека должен поддерживаться:

```text
track_id
bbox
confidence
current position
previous stable side of line
track age
last crossing state
```

Событие создаётся на основании trajectory, а не только наличия человека возле линии.

---

# 13. Алгоритм пересечения линии

Контрольная точка человека:

```text
bottom-center bounding box
```

То есть условное положение ног человека.

Виртуальная линия задаётся двумя нормализованными точками:

```json
{
  "start": {"x": 0.23, "y": 0.71},
  "end": {"x": 0.81, "y": 0.70}
}
```

Диапазон координат:

```text
0.0 <= x <= 1.0
0.0 <= y <= 1.0
```

Это обязательное требование, чтобы изменение resolution камеры не ломало line configuration.

Пересечение считается подтверждённым только если:

```text
class == person
confidence >= configured threshold
track существует не менее N frames
person имел стабильное положение с одной стороны
контрольная точка пересекла line segment
person оказался стабильно с другой стороны
направление соответствует configured direction
schedule активен
для этого crossing ещё не создано событие
```

Должен использоваться hysteresis, исключающий дрожание объекта непосредственно на линии.

Один track не должен генерировать десятки событий при колебании bbox около линии.

Если человек реально пересёк линию обратно, это MAY считаться новым crossing в зависимости от configured direction.

---

# 14. Guard line configuration

Для каждой камеры UI позволяет:

- увидеть snapshot;
- мышкой поставить две точки линии;
- изменить линию;
- определить внутреннюю/наружную сторону;
- выбрать контролируемое направление;
- задать confidence threshold;
- включить/выключить line monitoring.

Direction:

```text
ENTRY
EXIT
BOTH
```

---

# 15. Расписание контроля

Система должна поддерживать произвольные intervals по дням недели.

Например:

```text
Пн–Пт 19:00 → 08:00
Сб–Вс 00:00 → 24:00
```

Intervals, пересекающие полночь, должны поддерживаться корректно.

Schedule содержит:

```text
timezone
weekday
start_time
end_time
enabled
```

Также архитектура должна позволять добавить date overrides/holidays без изменения domain model.

Дата и время события всегда сохраняются timezone-aware.

В database основной timestamp хранится в UTC.

В UI и reports он отображается в timezone объекта.

---

# 16. Фиксация нарушения

При подтверждённом crossing создаётся `Violation`.

Violation содержит минимум:

```text
id
camera_id
guard_line_id
track_id
direction
detected_at
confidence
bbox
crossing_point
original_image
annotated_image
optional_clip
created_at
```

Event ID должен быть UUID.

Обязательно сохраняются:

1. оригинальный frame;
2. annotated frame.

Annotated frame содержит:

```text
camera name
date/time
person bbox
confidence
virtual line
crossing direction
```

---

# 17. Выбор лучшего кадра

Vision worker должен иметь короткий ring buffer вокруг crossing.

Configurable baseline:

```text
до crossing: 1 секунда
после crossing: 1 секунда
```

Для evidence image выбирается frame с наилучшим сочетанием:

```text
confidence
bbox area
отсутствие обрезания человека краем frame
близость ко времени crossing
```

Сам момент пересечения сохраняется отдельно как timestamp и не меняется из-за выбора лучшего изображения.

---

# 18. Event clip

Архитектура должна предусматривать сохранение короткого ролика вокруг нарушения.

Первоначально:

```dotenv
EVENT_CLIP_ENABLED=false
```

После включения рекомендуемый interval:

```text
5 секунд до crossing
5 секунд после crossing
```

Отсутствие clip не должно мешать созданию нарушения или изображения.

---

# 19. Monitoring Dashboard

Основной экран должен соответствовать согласованному render.

Desktop layout:

```text
┌──────────────────────────────────────┬───────────────────┐
│                                     │ Управление        │
│            Camera grid              │ камерами          │
│                                     │                   │
│                                     │ Notifications     │
│                                     │                   │
│                                     │ Schedule          │
│                                     │                   │
│                                     │ Statistics        │
├──────────────────────────────────────┴───────────────────┤
│ Последние нарушения                                    │
└─────────────────────────────────────────────────────────┘
```

---

# 20. Camera Grid

В верхней части располагается selector существующих камер.

Пользователь может выбрать произвольное количество камер.

Выбранные camera IDs сохраняются как personal monitoring layout.

Grid автоматически перестраивается:

```text
1 camera  → 1×1
2 cameras → 2×1
3–4       → 2×2
5–6       → 3×2
...
```

Жёсткая привязка к четырём камерам запрещена.

Допускается configurable operational limit для защиты browser/GPU, например:

```dotenv
MONITORING_MAX_VISIBLE_CAMERAS=16
```

Каждая card показывает:

```text
camera name
ONLINE/OFFLINE status
live stream
timestamp
optional person bbox
virtual line
fullscreen button
```

Пользователь может:

- добавить camera в layout;
- удалить camera из layout;
- изменить порядок drag-and-drop;
- выбрать grid density;
- открыть stream на весь экран.

Fullscreen — client-side действие.

Layout и порядок камер сохраняются через API.

---

# 21. Live Stream

RTSP credentials никогда не передаются browser.

Первоначальный browser streaming protocol:

```text
MJPEG over authenticated HTTP
```

Vision worker публикует latest annotated frames в ephemeral frame cache.

Django CBV выдаёт:

```text
Content-Type: multipart/x-mixed-replace
```

Предусматривается abstraction:

```text
LiveFrameCache
StreamProvider
```

чтобы впоследствии MJPEG можно было заменить на WebRTC/HLS без изменения application/domain.

---

# 22. Правая панель управления

Правая колонка Monitoring screen содержит четыре блока.

## Управление камерами

Показывает:

```text
dropdown доступных камер
Add button
selected cameras
online status
drag handle
remove button
```

Создание новой физической камеры выполняется через отдельный раздел `Камеры`.

На Monitoring screen кнопка «Добавить камеру» означает **добавить уже зарегистрированную камеру в dashboard layout**.

## Настройки уведомлений

Показывает:

```text
global notification switch
Email switch
Email recipients
Telegram switch
Telegram recipients
Test notification
runtime disabled state
```

## Расписание контроля

Показывает:

```text
timezone
active intervals
start/end
add interval
```

## Статистика

Period selector:

```text
today
7d
30d
custom
```

Карточки:

```text
Нарушений
Отправлено Email
Отправлено Telegram
Ошибок отправки
```

---

# 23. Последние нарушения

Таблица содержит:

```text
Дата и время
Камера
Направление
Фото
Email status
Telegram status
Actions
```

Actions:

```text
Открыть
Скачать отчёт
Повторить отправку
```

При клике на violation открывается детальная карточка либо отдельная detail-page.

---

# 24. Violation Detail

Пользователь должен видеть:

```text
Event ID
camera
location
date
time
timezone
direction
confidence
original photo
annotated photo
optional clip
notification recipients
notification delivery history
```

Доступны:

```text
download original image
download annotated image
download PDF report
retry failed notifications — при наличии permission
```

---

# 25. Reports

Раздел `Отчёты` должен поддерживать:

```text
single violation report
report за период
filter by camera
filter by direction
filter by notification status
PDF
CSV
```

Single violation PDF включает:

```text
номер события
название камеры
местоположение
дату
время
timezone
направление
confidence
annotated image
event ID
notification summary
```

---

# 26. Notification subsystem

Поддерживаются каналы:

```text
EMAIL
TELEGRAM
```

External send MUST происходить только после успешного сохранения violation.

Flow:

```text
Violation persisted
        ↓
Outbox event
        ↓
Transaction commit
        ↓
Notification task
        ↓
Generate report
        ↓
Email / Telegram adapter
        ↓
Delivery history
```

---

# 27. Runtime notification feature flag

Обязательный hard flag:

```dotenv
NOTIFICATIONS_ENABLED=false
```

При `false`:

- Email external call запрещён;
- Telegram external call запрещён;
- test notification запрещена;
- UI отображает «Отключено конфигурацией»;
- API изменения recipients/settings разрешены;
- настройки можно подготовить заранее.

После изменения на:

```dotenv
NOTIFICATIONS_ENABLED=true
```

начинают действовать application settings из database.

---

# 28. Email

SMTP configuration только через environment:

```text
SMTP_HOST
SMTP_PORT
SMTP_USERNAME
SMTP_PASSWORD
SMTP_USE_TLS
SMTP_FROM_ADDRESS
```

Email violation notification содержит:

```text
тему нарушения
camera
date/time
direction
Event ID
annotated photo
PDF report
```

---

# 29. Telegram

Secret:

```text
TELEGRAM_BOT_TOKEN
```

находится только в runtime environment.

Telegram notification содержит:

```text
camera
date/time
direction
Event ID
annotated image
PDF report
```

Получатель хранится в database как:

```text
chat_id
или разрешённый channel target
```

Bot token никогда не возвращается API.

---

# 30. Notification delivery history

Для каждого recipient/channel создаётся отдельный delivery record.

Statuses:

```text
PENDING
QUEUED
SENT
FAILED
RETRYING
SKIPPED_DISABLED
DEAD
```

History содержит:

```text
violation_id
channel
recipient
created_at
sent_at
status
attempt_count
last_error_code
```

Секретные payload/credentials в history запрещены.

Каждая попытка retry также должна быть сохранена.

---

# 31. REST API — общие правила

Prefix:

```text
/api/v1/
```

ID:

```text
UUID
```

Datetime:

```text
ISO 8601 with timezone
```

Authentication:

```text
Django session authentication
HttpOnly cookie
CSRF protection
```

Для server-rendered web UI JWT не требуется.

Все JSON errors имеют единый contract:

```json
{
  "error": {
    "code": "camera_not_found",
    "message": "Камера не найдена.",
    "details": {},
    "request_id": "..."
  }
}
```

Pagination:

```json
{
  "data": [],
  "meta": {
    "page": 1,
    "page_size": 50,
    "total": 0,
    "pages": 0
  }
}
```

API contract документируется OpenAPI.

Обязательны:

```text
/api/schema/
/api/docs/
```

---

# 32. API — User

| Method | Path | Назначение |
|---|---|---|
| GET | `/api/v1/users/me` | Текущий пользователь, роль, permissions |

Response содержит:

```text
id
username
display_name
role
permissions[]
```

---

# 33. API — Cameras

| Method | Path | Назначение |
|---|---|---|
| GET | `/api/v1/cameras` | Список камер |
| POST | `/api/v1/cameras` | Создать камеру |
| GET | `/api/v1/cameras/{id}` | Получить камеру |
| PATCH | `/api/v1/cameras/{id}` | Изменить камеру |
| DELETE | `/api/v1/cameras/{id}` | Деактивировать/удалить камеру |
| POST | `/api/v1/cameras/{id}/test-connection` | Проверить RTSP |
| GET | `/api/v1/cameras/{id}/snapshot` | Получить актуальный JPEG |
| GET | `/api/v1/cameras/{id}/stream.mjpeg` | Authenticated live stream |
| GET | `/api/v1/cameras/{id}/guard-line` | Получить line configuration |
| PUT | `/api/v1/cameras/{id}/guard-line` | Создать/полностью изменить line |

Camera create request:

```json
{
  "name": "Главный вход",
  "location": "Склад №1",
  "enabled": true,
  "rtsp": {
    "url": "rtsp://10.0.0.25/stream1",
    "username": "camera_user",
    "password": "secret"
  }
}
```

Camera response MUST NOT возвращать password.

Guard line request:

```json
{
  "start": {"x": 0.17, "y": 0.72},
  "end": {"x": 0.83, "y": 0.71},
  "inside_side": "left",
  "direction": "ENTRY",
  "min_confidence": 0.65,
  "enabled": true
}
```

---

# 34. API — Monitoring layout

| Method | Path | Назначение |
|---|---|---|
| GET | `/api/v1/users/me/monitoring-layout` | Текущий camera layout |
| PUT | `/api/v1/users/me/monitoring-layout` | Сохранить selected cameras/order/grid |

Request:

```json
{
  "camera_ids": [
    "uuid-1",
    "uuid-2",
    "uuid-3"
  ],
  "grid": "auto"
}
```

Порядок UUID соответствует порядку cards.

---

# 35. API — Violations

| Method | Path | Назначение |
|---|---|---|
| GET | `/api/v1/violations` | История нарушений |
| GET | `/api/v1/violations/{id}` | Детальный отчёт |
| GET | `/api/v1/violations/{id}/media/original` | Оригинальная фотография |
| GET | `/api/v1/violations/{id}/media/annotated` | Размеченная фотография |
| GET | `/api/v1/violations/{id}/media/clip` | Event clip |
| GET | `/api/v1/violations/{id}/report.pdf` | PDF отчёт |
| POST | `/api/v1/violations/{id}/resend` | Повторно отправить notifications |

Filters:

```text
camera_id
date_from
date_to
direction
notification_status
page
page_size
```

Violation detail response:

```json
{
  "data": {
    "id": "uuid",
    "camera": {
      "id": "uuid",
      "name": "Главный вход"
    },
    "detected_at": "2026-10-07T23:17:42+03:00",
    "direction": "ENTRY",
    "confidence": 0.91,
    "track_id": 47,
    "media": {
      "original_url": "...",
      "annotated_url": "...",
      "clip_url": null
    },
    "deliveries": []
  }
}
```

---

# 36. API — Schedule

| Method | Path | Назначение |
|---|---|---|
| GET | `/api/v1/control-schedule` | Получить расписание |
| PUT | `/api/v1/control-schedule` | Полностью сохранить расписание |
| GET | `/api/v1/timezones` | Список поддерживаемых timezone |

Пример:

```json
{
  "timezone": "Europe/Moscow",
  "week": {
    "monday": [
      {"start": "19:00", "end": "08:00"}
    ],
    "tuesday": [
      {"start": "19:00", "end": "08:00"}
    ],
    "saturday": [
      {"start": "00:00", "end": "24:00"}
    ]
  }
}
```

Backend обязан самостоятельно корректно интерпретировать interval через полночь.

---

# 37. API — Notification settings

| Method | Path | Назначение |
|---|---|---|
| GET | `/api/v1/notification-settings` | Получить настройки |
| PATCH | `/api/v1/notification-settings` | Изменить настройки |
| GET | `/api/v1/notification-recipients` | Список получателей |
| POST | `/api/v1/notification-recipients` | Добавить получателя |
| PATCH | `/api/v1/notification-recipients/{id}` | Изменить |
| DELETE | `/api/v1/notification-recipients/{id}` | Удалить |
| POST | `/api/v1/notifications/test` | Тестовая отправка |

Settings response должен различать:

```text
runtime_enabled
global_enabled
email_enabled
telegram_enabled
```

Например:

```json
{
  "runtime_enabled": false,
  "global_enabled": true,
  "email_enabled": true,
  "telegram_enabled": true
}
```

В этом состоянии UI показывает configured channels, но внешняя отправка заблокирована runtime feature flag.

Recipient request:

```json
{
  "channel": "EMAIL",
  "target": "security@example.com",
  "display_name": "Служба безопасности",
  "enabled": true
}
```

или:

```json
{
  "channel": "TELEGRAM",
  "target": "123456789",
  "display_name": "Дежурный",
  "enabled": true
}
```

---

# 38. API — Delivery history

| Method | Path | Назначение |
|---|---|---|
| GET | `/api/v1/notification-deliveries` | История отправок |
| GET | `/api/v1/notification-deliveries/{id}` | Detail + attempts |
| POST | `/api/v1/notification-deliveries/{id}/retry` | Retry failed delivery |

Filters:

```text
violation_id
channel
recipient_id
status
date_from
date_to
```

---

# 39. API — Statistics

| Method | Path | Назначение |
|---|---|---|
| GET | `/api/v1/statistics/summary` | Карточки dashboard |

Query:

```text
period=today
period=7d
period=30d
date_from=...
date_to=...
```

Response:

```json
{
  "violations": 14,
  "email_sent": 12,
  "telegram_sent": 12,
  "delivery_errors": 2
}
```

---

# 40. API — Reports

| Method | Path | Назначение |
|---|---|---|
| GET | `/api/v1/reports` | История сформированных reports |
| POST | `/api/v1/reports` | Сформировать report |
| GET | `/api/v1/reports/{id}` | Status/metadata |
| GET | `/api/v1/reports/{id}/download` | Скачать готовый файл |

Request:

```json
{
  "type": "VIOLATIONS",
  "format": "PDF",
  "filters": {
    "camera_ids": [],
    "date_from": "2026-10-01T00:00:00+03:00",
    "date_to": "2026-10-07T23:59:59+03:00",
    "direction": null
  }
}
```

Single-event report может генерироваться синхронно.

Большой period report MAY возвращать:

```text
202 Accepted
```

и формироваться background worker.

---

# 41. API — System settings

| Method | Path | Назначение |
|---|---|---|
| GET | `/api/v1/system-settings` | Несекретные project settings |
| PATCH | `/api/v1/system-settings` | Изменяемые business settings |

Допустимые UI settings:

```text
default timezone
media retention
default confidence
monitoring defaults
```

Через API запрещено изменять:

```text
SECRET_KEY
SMTP password
Telegram token
camera encryption key
RabbitMQ password
database password
```

---

# 42. API — Health

Все endpoints также CBV.

```text
GET /health/live
GET /health/ready
GET /metrics
```

`ready` должен учитывать критичные project dependencies:

```text
PostgreSQL
Redis
```

Недоступность одной камеры не должна делать весь web application `not ready`.

---

# 43. HTML Routes

Основные server-rendered pages:

```text
/                       → redirect to /monitoring/
/monitoring/
/violations/
/violations/{id}/
/reports/
/notifications/
/cameras/
/cameras/{id}/
/settings/
/login/
/logout/
```

Каждый route реализован CBV.

Примеры классов:

```text
MonitoringPageView
ViolationListPageView
ViolationDetailPageView
ReportsPageView
NotificationsPageView
CameraListPageView
CameraDetailPageView
SettingsPageView
```

---

# 44. Frontend architecture

Обязательный base template:

```text
web/templates/base.html
```

Повторяемые элементы:

```text
web/templates/components/
```

Pages:

```text
web/templates/pages/
```

CSS:

```text
web/static/css/
├── style.css
├── variables.css
├── global.css
├── responsive.css
└── blocks/
```

`style.css` является aggregator.

Обязателен BEM.

Не допускаются:

```text
inline onclick
inline business JavaScript
гигантский app.js
гигантский style.css
raw innerHTML с недоверенными данными
```

JS:

```text
web/static/js/
├── api.js
├── app.js
├── components/
└── features/
    ├── monitoring.js
    ├── violations.js
    ├── cameras.js
    ├── notifications.js
    ├── reports.js
    └── schedule.js
```

HTTP requests должны выполняться через единый `api.js`.

---

# 45. UI design

Основная theme соответствует согласованному render:

```text
dark navy / graphite
blue primary accent
red violation accent
green healthy/sent status
orange warning/error accent
rounded cards
compact professional security-dashboard style
```

Design tokens хранятся CSS variables.

Должна поддерживаться desktop width от 1280 px.

Интерфейс должен оставаться функциональным на меньшей ширине посредством responsive layout.

---

# 46. Accessibility

Обязательно:

```text
semantic HTML
keyboard navigation
visible focus
label для inputs
aria-label для icon-only controls
disabled state
aria-live для динамических statuses
button для actions
a для navigation
```

---

# 47. Database models

Минимальный набор persistence entities:

```text
User / Django auth
Camera
CameraCredential
GuardLine

MonitoringLayout

ControlSchedule
ControlScheduleInterval

Violation
ViolationMedia

NotificationSettings
NotificationRecipient
NotificationOutbox
NotificationDelivery
NotificationDeliveryAttempt

GeneratedReport
AuditEvent
```

---

# 48. Camera credentials

Camera credentials являются secret.

Они должны храниться encrypted at rest.

Encryption key:

```text
CAMERA_CREDENTIALS_KEY
```

передаётся через runtime secret/environment.

Запрещено:

- хранить camera passwords plain-text;
- возвращать их через API;
- писать их в logs;
- включать их в exception messages.

---

# 49. Media Storage

Application работает через port:

```text
MediaStorage
```

Первоначальная implementation MAY использовать project-owned filesystem volume.

Структура логически:

```text
events/
└── YYYY/
    └── MM/
        └── DD/
            └── event-id/
                ├── original.jpg
                ├── annotated.jpg
                └── clip.mp4
```

Backend не должен зависеть от абсолютного filesystem path.

Это позволит позже заменить implementation на S3/MinIO без изменения application use-cases.

Media files не должны быть доступны анонимно через static web server.

Получение выполняется только после permission check.

---

# 50. RabbitMQ

Новый RabbitMQ container в project создавать запрещено.

Используется shared RabbitMQ из `shared-infrastructure`.

Для проекта создаются:

```text
project-specific vhost
project-specific runtime user
project-specific queues
```

Bootstrap/admin account RabbitMQ использовать в application запрещено.

Celery worker остаётся частью project repository.

---

# 51. Redis

Redis принимается как **project-specific dependency**.

Причина:

```text
low-latency cross-process latest-frame cache
```

Redis:

- находится только в private project network;
- не публикует host port в production;
- не содержит authoritative business data;
- может быть полностью очищен без потери violation history.

---

# 52. YOLO runtime ownership

YOLO detector является project-specific runtime.

Это не duplicate `shared-vlm`.

Причина:

- YOLO обрабатывает непрерывный realtime RTSP stream;
- tracking state связан с конкретными cameras;
- line-crossing state является частью данного business application;
- shared VLM contract не предназначен для frame-by-frame object detection.

Если в будущем YOLO detector понадобится нескольким независимым business projects, вопрос его переноса в shared infrastructure требует отдельного архитектурного решения.

---

# 53. GPU

GPU placement задаётся deployment configuration.

Application/domain не должны содержать:

```text
cuda:0
конкретную модель GPU
VRAM size
physical device name
```

Silent fallback на CPU в production запрещён.

Если GPU отсутствует либо модель не может загрузиться, vision worker должен завершить readiness с ошибкой либо перейти в явное degraded состояние в соответствии с deployment policy.

Если YOLO планируется размещать на той же physical GPU, что и другой production inference runtime, это должно быть подтверждено benchmark и VRAM feasibility check.

---

# 54. Authentication и роли

Используется Django authentication.

Минимальные роли:

```text
Administrator
Operator
Viewer
```

Administrator:

```text
camera management
line configuration
schedule
notification recipients
notification settings
retry
system settings
view reports
```

Operator:

```text
monitoring
violations
reports
allowed retry operations
```

Viewer:

```text
monitoring
read violations
read reports
```

Permissions проверяются backend, а не только скрытием button во frontend.

---

# 55. Audit

Аудируются минимум:

```text
camera create/update/delete
guard line changes
schedule changes
notification settings
recipient changes
manual resend
system settings changes
```

Audit не должен содержать secret values.

---

# 56. Logging

Логи структурированные.

Основные fields:

```text
event
operation
status
duration_ms
camera_id
violation_id
request_id
```

Запрещено логировать каждый processed frame на INFO.

Для realtime pipeline использовать:

```text
metrics
periodic summaries
state-change logs
```

Примеры значимых events:

```text
camera_connected
camera_disconnected
camera_reconnected
vision_worker_started
violation_created
notification_sent
notification_failed
report_generated
```

Один exception — один traceback.

---

# 57. Timing

Обязательный общий timing decorator для значимых operations.

Минимум:

```text
create_violation
generate_report
send_email_notification
send_telegram_notification
camera_reconnect
```

Нельзя ставить timing decorator на каждый frame/helper.

---

# 58. Log rotation

Docker logs MUST иметь bounded rotation.

Baseline:

```text
driver: local
max-size: 10m
max-file: 5
```

Конкретные production значения могут быть изменены, но бесконечный рост logs запрещён.

---

# 59. Configuration

Используется схема:

```text
.env.example = полный безопасный baseline
.env         = sparse private override
```

`.env` запрещён в Git.

Pydantic Settings должен загружать:

```text
.env.example
      ↓
.env
      ↓
process environment
```

Все новые safe configuration variables добавляются в `.env.example`.

---

# 60. Feature flags

Минимум:

```dotenv
NOTIFICATIONS_ENABLED=false
EMAIL_NOTIFICATIONS_ENABLED=false
TELEGRAM_NOTIFICATIONS_ENABLED=false

EVENT_CLIP_ENABLED=false

VISION_ENABLED=true
```

Business toggle из database не имеет права обходить deployment hard flag.

---

# 61. Testing

Ключевая logic MUST быть покрыта tests.

## Domain tests

Обязательно:

```text
crossing A→B
crossing B→A
movement parallel to line
person stops on line
bbox jitter around line
crossing outside segment
track too young
confidence too low
allowed direction
forbidden direction
deduplication
second legitimate reverse crossing
```

## Schedule tests

```text
inside active interval
outside interval
interval through midnight
weekend
timezone conversion
boundary exact start
boundary exact end
DST transition
```

## Application tests

```text
create violation happy path
storage failure
DB failure
duplicate violation
notifications disabled
notification outbox creation
report generation
retry
permission boundary
```

## Vision tests

Model internals Ultralytics не тестируются.

Тестируется наша integration logic:

```text
detector output mapping
tracker mapping
frame → crossing pipeline
camera reconnect
model loaded once
```

CI должен использовать fake detector и prerecorded synthetic fixtures без GPU.

## API tests

Проверяются:

```text
status codes
schemas
permissions
CSRF/auth
pagination
filters
error mapping
media access
stream authorization
```

## Frontend/E2E

Critical flows:

```text
add camera to dashboard
remove camera
reorder camera cards
open violation
download report
edit notification recipient
edit schedule
runtime notifications disabled UI
camera offline UI
```

---

# 62. Architecture tests

Автоматически должны проверяться границы.

Обязательные invariants:

```text
domain не импортирует Django
domain не импортирует infrastructure
application не импортирует django.http
application не импортирует rest_framework
application не импортирует infrastructure implementations

Django ORM queries отсутствуют в:
    transport
    application
    domain

repositories/clients не создаются внутри use-cases

project HTTP endpoints не являются FBV

@api_view отсутствует

в urlpatterns project endpoints подключаются через .as_view()

concrete adapters собираются только через composition root
```

Для Django ORM отдельно запрещено использование:

```text
Model.objects
QuerySet
select_related
prefetch_related
```

в transport/application/domain.

ORM loading strategy принадлежит repository implementation.

---

# 63. Quality gates

Перед merge обязательно:

```text
pytest
ruff check
ruff format --check
architecture tests
API contract tests
```

При принятом type-checking:

```text
mypy
```

Frontend при наличии Node toolchain:

```text
frontend tests
frontend lint
```

GitHub Actions должен блокировать merge при падении mandatory checks.

---

# 64. Documentation rules

Каждый новый/изменённый source/config/script/template файл должен иметь русское описание назначения.

Python file:

```text
relative path comment
module docstring на русском
```

Каждая созданная function/method/class имеет содержательный русский docstring.

Документация должна объяснять ответственность и ограничения, а не повторять имя функции.

---

# 65. Definition of Done — MVP

MVP считается завершённым, если одновременно выполнены следующие условия.

### Video

Минимум две реальные камеры можно зарегистрировать и вывести одновременно.

Отключение одной камеры не нарушает работу остальных.

### Vision

Человек определяется pretrained model.

ByteTrack выдаёт устойчивые IDs.

Линия задаётся через UI.

### Crossing

Реальное пересечение вызывает ровно одно событие.

Стояние возле линии событие не вызывает.

Jitter bbox не создаёт повторные violations.

### Schedule

События создаются только внутри активного control interval.

### Evidence

Для нарушения сохранены:

```text
original image
annotated image
camera
date
time
direction
confidence
```

### Dashboard

Можно выбрать произвольные камеры.

Cards автоматически перестраиваются.

Порядок сохраняется для пользователя.

### Violation history

Нарушение появляется в таблице без ручного вмешательства.

По клику открывается полный event detail.

### Report

Для нарушения скачивается PDF report.

### Notifications

Весь notification subsystem реализован.

При:

```text
NOTIFICATIONS_ENABLED=false
```

ни один внешний Email/Telegram request не выполняется.

После включения feature flag notification отправляется и появляется в delivery history.

### Architecture

Все project HTTP views — CBV.

Application/domain изолированы от Django transport и concrete infrastructure.

DI используется через explicit ports + composition root.

### Security

Secrets отсутствуют в repository/logs/API responses.

Camera credentials encrypted.

Media требует authentication.

### Quality

Unit, integration, API, architecture и critical UI tests проходят.

---

# 66. Не входит в первый этап

Без отдельного решения не реализовывать:

```text
face recognition
идентификацию личности
биометрию
license plate recognition
Kubernetes
service mesh
отдельные microservices
отдельный RabbitMQ
отдельный n8n
shared YOLO server
mobile application
automatic police/security dispatch
```

---

# 67. Архитектурная схема

```text
                         Browser
                            │
                            ▼
                  ┌──────────────────┐
                  │   Django Web     │
                  │ Templates + API  │
                  │     CBV only     │
                  └────────┬─────────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │   Application    │
                  │ Use Cases/Ports  │
                  └───────┬──────────┘
                          │
                          ▼
                  ┌──────────────────┐
                  │      Domain      │
                  └──────────────────┘


    ┌─────────────────────────────────────────────┐
    │                Infrastructure               │
    │                                             │
    │ Django ORM         PostgreSQL               │
    │ Redis frame cache                           │
    │ Local/S3 media storage                      │
    │ SMTP                                        │
    │ Telegram Bot API                            │
    │ shared RabbitMQ                             │
    └─────────────────────────────────────────────┘


Camera RTSP
    │
    ▼
Vision Worker
    │
    ├── YOLO PersonDetector
    │
    ├── ByteTrack
    │
    ├── LineCrossingPolicy
    │
    ├── SchedulePolicy
    │
    ├── LiveFrameCache ──────────────► Django MJPEG CBV
    │
    └── CreateViolationUseCase
                 │
                 ▼
             PostgreSQL
                 │
                 ▼
          Notification Outbox
                 │
                 ▼
         shared RabbitMQ
                 │
                 ▼
       Notification Worker
           │             │
           ▼             ▼
         Email        Telegram
```

---

# 68. Главный architectural rule проекта

Django, YOLO, PostgreSQL, Redis, RabbitMQ, SMTP и Telegram являются деталями реализации.

Business logic должна зависеть от:

```text
CameraRepository
PersonDetector
ObjectTracker
MediaStorage
NotificationSender
UnitOfWork
Clock
```

а не от конкретных libraries.

Это требование является обязательным на протяжении всей разработки проекта.