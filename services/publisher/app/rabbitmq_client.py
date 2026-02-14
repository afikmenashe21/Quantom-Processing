import json
import logging

import pika

from app.config import settings

logger = logging.getLogger(__name__)


class RabbitMQClient:
    def __init__(self) -> None:
        self._connection: pika.BlockingConnection | None = None
        self._channel: pika.adapters.blocking_connection.BlockingChannel | None = None

    def connect(self) -> None:
        params = pika.URLParameters(settings.rabbitmq_url)
        params.heartbeat = 60
        self._connection = pika.BlockingConnection(params)
        self._channel = self._connection.channel()

        # Declare exchange
        self._channel.exchange_declare(
            exchange=settings.tasks_exchange, exchange_type="direct", durable=True
        )

        # Declare DLX + DLQ
        self._channel.exchange_declare(
            exchange="tasks.dlx", exchange_type="direct", durable=True
        )
        self._channel.queue_declare(queue="tasks.dlq", durable=True)
        self._channel.queue_bind(
            queue="tasks.dlq", exchange="tasks.dlx", routing_key=settings.tasks_routing_key
        )

        # Declare main queue with DLQ binding
        self._channel.queue_declare(
            queue=settings.tasks_queue,
            durable=True,
            arguments={
                "x-dead-letter-exchange": "tasks.dlx",
                "x-dead-letter-routing-key": settings.tasks_routing_key,
            },
        )
        self._channel.queue_bind(
            queue=settings.tasks_queue,
            exchange=settings.tasks_exchange,
            routing_key=settings.tasks_routing_key,
        )
        logger.info("rabbitmq_connected")

    def publish(self, task_id: str) -> None:
        if self._channel is None or self._channel.is_closed:
            self.connect()
        self._channel.basic_publish(
            exchange=settings.tasks_exchange,
            routing_key=settings.tasks_routing_key,
            body=json.dumps({"task_id": task_id}),
            properties=pika.BasicProperties(
                delivery_mode=pika.DeliveryMode.Persistent,
                content_type="application/json",
            ),
        )

    def close(self) -> None:
        if self._connection and not self._connection.is_closed:
            self._connection.close()
