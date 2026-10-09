# src/workers/celery_app.py
"""Celery project worker/beat используют отдельные vhost, user и queue shared RabbitMQ."""

import os
from urllib.parse import quote

from celery import Celery

from core.config import Settings

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
config = Settings()
user = quote(config.rabbitmq_user, safe="")
password = quote(config.rabbitmq_password.get_secret_value(), safe="")
vhost = quote(config.rabbitmq_vhost, safe="")
broker = f"amqp://{user}:{password}@{config.rabbitmq_host}:{config.rabbitmq_port}/{vhost}"
app = Celery("warehouse_watch", broker=broker, include=["workers.tasks"])
app.conf.update(
    task_default_queue="warehouse.notifications",
    task_default_exchange="warehouse.notifications",
    task_default_routing_key="warehouse.notifications",
    worker_enable_remote_control=False,
    worker_send_task_events=False,
    worker_hijack_root_logger=False,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"confirm_publish": True},
    task_reject_on_worker_lost=True,
    beat_schedule={
        "outbox": {"task": "warehouse.publish_outbox", "schedule": 5.0},
        "retention": {"task": "warehouse.retention", "schedule": 60.0},
    },
)
