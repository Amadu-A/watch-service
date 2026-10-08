# src/workers/tasks.py
"""Тонкие Celery transport adapters; зависимости и business operations собирает composition root."""

from core import container
from workers.celery_app import app


@app.task(name="warehouse.send_delivery")
def send_delivery(delivery_id: str) -> None:
    """Передаёт UUID в готовый application use-case; payload секретов в broker отсутствует."""
    container.dispatch_notification().execute(delivery_id)


@app.task(name="warehouse.publish_outbox")
def publish_outbox() -> None:
    """Восстанавливает durable поручения после временного отказа RabbitMQ."""
    container.outbox_publisher().pump()


@app.task(name="warehouse.retention")
def cleanup_retention() -> None:
    """Проверяет TTL каждую минуту; события и отчёты удаляются вместе с evidence."""
    container.retention_cleaner().execute()
