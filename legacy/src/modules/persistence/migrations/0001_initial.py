# src/modules/persistence/migrations/0001_initial.py
"""Создаёт связи камер, событий, evidence, outbox, deliveries и reports."""

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Начальная business схема с UUID, constraints и индексами истории."""

    initial = True

    dependencies = [
        ("accounts", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Camera",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("name", models.CharField(max_length=150)),
                ("location", models.CharField(blank=True, max_length=250)),
                ("enabled", models.BooleanField(default=True)),
                ("status", models.CharField(default="CONNECTING", max_length=16)),
                ("rtsp_url", models.CharField(max_length=1000)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("last_seen", models.DateTimeField(null=True)),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="ControlSchedule",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(default=1, primary_key=True, serialize=False),
                ),
                ("timezone", models.CharField(default="Europe/Moscow", max_length=64)),
                ("enabled", models.BooleanField(default=True)),
            ],
        ),
        migrations.CreateModel(
            name="MonitoringLayout",
            fields=[
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        serialize=False,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("camera_ids", models.JSONField(default=list)),
                ("grid", models.CharField(default="auto", max_length=8)),
            ],
        ),
        migrations.CreateModel(
            name="NotificationDelivery",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("channel", models.CharField(max_length=16)),
                ("target", models.CharField(max_length=250)),
                ("status", models.CharField(db_index=True, default="PENDING", max_length=24)),
                ("attempt_count", models.PositiveSmallIntegerField(default=0)),
                ("last_error_code", models.CharField(blank=True, max_length=64)),
                ("sent_at", models.DateTimeField(null=True)),
                ("next_attempt_at", models.DateTimeField(null=True)),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="NotificationSettings",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(default=1, primary_key=True, serialize=False),
                ),
                ("global_enabled", models.BooleanField(default=False)),
                ("email_enabled", models.BooleanField(default=False)),
                ("telegram_enabled", models.BooleanField(default=False)),
            ],
        ),
        migrations.CreateModel(
            name="AuditEvent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("operation", models.CharField(max_length=64)),
                ("object_id", models.CharField(blank=True, max_length=64)),
                (
                    "actor",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="CameraCredential",
            fields=[
                (
                    "camera",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        serialize=False,
                        to="persistence.camera",
                    ),
                ),
                ("ciphertext", models.TextField()),
            ],
        ),
        migrations.CreateModel(
            name="ControlScheduleInterval",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("weekday", models.PositiveSmallIntegerField()),
                ("start", models.CharField(max_length=5)),
                ("end", models.CharField(max_length=5)),
                (
                    "schedule",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="intervals",
                        to="persistence.controlschedule",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="GeneratedReport",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("format", models.CharField(max_length=8)),
                ("filters", models.JSONField(default=dict)),
                ("path", models.CharField(max_length=500)),
                ("status", models.CharField(default="READY", max_length=16)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="GuardLineRecord",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("configuration", models.JSONField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "camera",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="guard_line",
                        to="persistence.camera",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="NotificationDeliveryAttempt",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("status", models.CharField(max_length=24)),
                ("error_code", models.CharField(blank=True, max_length=64)),
                (
                    "delivery",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attempts",
                        to="persistence.notificationdelivery",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="NotificationOutbox",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("published_at", models.DateTimeField(null=True)),
                (
                    "delivery",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="persistence.notificationdelivery",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="NotificationRecipient",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("channel", models.CharField(max_length=16)),
                ("target", models.CharField(max_length=250)),
                ("display_name", models.CharField(blank=True, max_length=150)),
                ("enabled", models.BooleanField(default=True)),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("channel", "target"), name="recipient_channel_target"
                    )
                ],
            },
        ),
        migrations.AddField(
            model_name="notificationdelivery",
            name="recipient",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="persistence.notificationrecipient",
            ),
        ),
        migrations.CreateModel(
            name="SystemSettings",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(default=1, primary_key=True, serialize=False),
                ),
                ("default_timezone", models.CharField(default="Europe/Moscow", max_length=64)),
                ("media_retention_days", models.PositiveSmallIntegerField(default=30)),
                ("default_confidence", models.FloatField(default=0.65)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            ("media_retention_days__gte", 1), ("media_retention_days__lte", 30)
                        ),
                        name="retention_max_month",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="Violation",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("event_key", models.CharField(max_length=250, unique=True)),
                ("track_id", models.PositiveBigIntegerField()),
                ("direction", models.CharField(max_length=8)),
                ("detected_at", models.DateTimeField(db_index=True)),
                ("confidence", models.FloatField()),
                ("bbox", models.JSONField()),
                ("crossing_point", models.JSONField()),
                ("line_snapshot", models.JSONField()),
                ("camera_snapshot", models.JSONField()),
                (
                    "camera",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="persistence.camera"
                    ),
                ),
                (
                    "guard_line",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="persistence.guardlinerecord",
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="notificationdelivery",
            name="violation",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="deliveries",
                to="persistence.violation",
            ),
        ),
        migrations.CreateModel(
            name="ViolationMedia",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("kind", models.CharField(max_length=16)),
                ("path", models.CharField(max_length=500)),
                (
                    "violation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="media",
                        to="persistence.violation",
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="violation",
            index=models.Index(
                fields=["camera", "-detected_at"], name="persistence_camera__34ec9f_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="violationmedia",
            constraint=models.UniqueConstraint(
                fields=("violation", "kind"), name="event_media_kind"
            ),
        ),
    ]
