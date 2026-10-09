# tests/integration/test_external_services.py
"""Изолированная проверка PostgreSQL, Redis TTL и project vhost shared RabbitMQ."""

import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
from uuid import uuid4

import pytest
from amqp.exceptions import ChannelError
from django.db import close_old_connections, connection
from kombu import Connection, Exchange, Queue
from redis import Redis

from core import container as c
from core.config import Settings
from persistence_app.models import NotificationDelivery

pytestmark = [
    pytest.mark.integration,
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        os.environ.get("TEST_EXTERNAL_SERVICES") != "true", reason="Нужен watch.sh test-containers"
    ),
]


def test_real_postgresql_and_redis_ttl():
    """Container tests используют отдельную БД; Redis keys получают конечный TTL."""
    assert connection.vendor == "postgresql"
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        assert cursor.fetchone()[0].startswith("test_warehouse_tests")
    client = Redis.from_url(Settings().redis_url, socket_connect_timeout=3, socket_timeout=3)
    key = f"warehouse:test:{uuid4()}"
    try:
        client.setex(key, 3, b"jpeg")
        assert client.get(key) == b"jpeg" and 0 < client.ttl(key) <= 3
    finally:
        client.delete(key)


def test_shared_rabbitmq_project_namespace():
    """Проверяет публикацию и чтение во временной exclusive queue проекта."""
    config = Settings()
    name = f"warehouse.test.{uuid4()}"
    with Connection(
        hostname=config.rabbitmq_host,
        port=config.rabbitmq_port,
        userid=config.rabbitmq_user,
        password=config.rabbitmq_password.get_secret_value(),
        virtual_host=config.rabbitmq_vhost,
        connect_timeout=5,
    ) as broker:
        exchange = Exchange(name, type="direct", durable=False, auto_delete=True)
        queue = Queue(
            name,
            exchange=exchange,
            routing_key=name,
            durable=False,
            exclusive=True,
            auto_delete=True,
        )
        with broker.channel() as channel:
            bound = queue(channel)
            bound.declare()
            broker.Producer(channel, exchange=exchange).publish(
                {"probe": "warehouse"}, routing_key=name, serializer="json"
            )
            message = bound.get(no_ack=False)
            assert message is not None and message.payload == {"probe": "warehouse"}
            message.ack()
            bound.delete()


def test_postgresql_serializes_duplicate_delivery_tasks():
    """Два concurrent consumer задания одного UUID вызывают sender ровно один раз."""
    dispatch = c.dispatch_notification()
    dispatch.settings.runtime_enabled = True
    dispatch.settings.channel_flags = {"EMAIL": True, "TELEGRAM": False}
    dispatch.repository.settings({"global_enabled": True, "email_enabled": True})
    sender = Mock()
    dispatch.senders = {"EMAIL": sender}
    delivery = NotificationDelivery.objects.create(channel="EMAIL", target="a@example.com")

    def execute():
        """Выделяет отдельное DB connection для каждого thread consumer."""
        close_old_connections()
        try:
            dispatch.execute(delivery.id)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(execute) for _ in range(2)]
        for future in futures:
            future.result(timeout=10)
    sender.send.assert_called_once()
    delivery.refresh_from_db()
    assert delivery.status == "SENT" and delivery.attempts.count() == 1


def test_celery_consumer_starts_with_project_only_broker_permissions():
    """Worker начинает чтение временной проектной очереди без celery.pidbox и celeryev."""
    config = Settings()
    name = f"warehouse.test.worker.{uuid4()}"
    with (
        Connection(
            hostname=config.rabbitmq_host,
            port=config.rabbitmq_port,
            userid=config.rabbitmq_user,
            password=config.rabbitmq_password.get_secret_value(),
            virtual_host=config.rabbitmq_vhost,
            connect_timeout=5,
        ) as broker,
        tempfile.TemporaryFile() as output,
    ):
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "celery",
                "-A",
                "workers.celery_app",
                "worker",
                "--pool=solo",
                "--concurrency=1",
                "--without-gossip",
                "--without-mingle",
                "--without-heartbeat",
                "--loglevel=WARNING",
                "-Q",
                name,
                "--hostname",
                name,
            ],
            stdout=output,
            stderr=output,
        )
        try:
            deadline = time.monotonic() + 20
            ready = False
            while process.poll() is None and time.monotonic() < deadline:
                with broker.channel() as channel:
                    queue = Queue(name, exchange=Exchange(name), routing_key=name)(channel)
                    queue.declare()
                    result = channel.queue_declare(queue=name, passive=True)
                    if result.consumer_count > 0:
                        ready = True
                        break
                time.sleep(0.2)
            assert ready, "Celery consumer не запустился с проектными правами RabbitMQ"
        finally:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            for operation in ("queue_delete", "exchange_delete"):
                try:
                    with broker.channel() as channel:
                        getattr(channel, operation)(
                            **{"queue" if operation == "queue_delete" else "exchange": name}
                        )
                except ChannelError:
                    pass
