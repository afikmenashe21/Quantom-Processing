import json
import logging

import pika

from shared.constants import RMQ_DLX, RMQ_DLQ
from shared.rabbitmq import declare_topology

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

        declare_topology(
            self._channel,
            exchange=settings.tasks_exchange,
            queue=settings.tasks_queue,
            routing_key=settings.tasks_routing_key,
        )
        logger.info("rabbitmq_topology_declared exchange=%s queue=%s", settings.tasks_exchange, settings.tasks_queue)

    def publish(self, task_id: str) -> None:
        if self._channel is None or self._channel.is_closed:
            logger.warning("rabbitmq_channel_reconnecting")
            self._close_silently()
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

    def _close_silently(self) -> None:
        try:
            if self._connection and not self._connection.is_closed:
                self._connection.close()
        except Exception:
            pass
        self._connection = None
        self._channel = None

    def close(self) -> None:
        if self._connection and not self._connection.is_closed:
            self._connection.close()
