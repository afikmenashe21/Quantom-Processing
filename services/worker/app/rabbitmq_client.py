import logging

import pika

from app.config import settings

logger = logging.getLogger(__name__)


def create_connection() -> pika.BlockingConnection:
    params = pika.URLParameters(settings.rabbitmq_url)
    params.heartbeat = 60
    return pika.BlockingConnection(params)


def setup_channel(connection: pika.BlockingConnection) -> pika.adapters.blocking_connection.BlockingChannel:
    channel = connection.channel()
    channel.basic_qos(prefetch_count=1)

    # Declare exchange
    channel.exchange_declare(
        exchange=settings.tasks_exchange, exchange_type="direct", durable=True
    )

    # Declare DLX + DLQ
    channel.exchange_declare(exchange="tasks.dlx", exchange_type="direct", durable=True)
    channel.queue_declare(queue="tasks.dlq", durable=True)
    channel.queue_bind(queue="tasks.dlq", exchange="tasks.dlx", routing_key=settings.tasks_routing_key)

    # Declare main queue with DLQ
    channel.queue_declare(
        queue=settings.tasks_queue,
        durable=True,
        arguments={
            "x-dead-letter-exchange": "tasks.dlx",
            "x-dead-letter-routing-key": settings.tasks_routing_key,
        },
    )
    channel.queue_bind(
        queue=settings.tasks_queue,
        exchange=settings.tasks_exchange,
        routing_key=settings.tasks_routing_key,
    )
    return channel
