import logging

import pika

from shared.rabbitmq import declare_topology

from app.config import settings

logger = logging.getLogger(__name__)


def create_connection() -> pika.BlockingConnection:
    params = pika.URLParameters(settings.rabbitmq_url)
    params.heartbeat = 60
    conn = pika.BlockingConnection(params)
    logger.info("rabbitmq_connection_created")
    return conn


def setup_channel(
    connection: pika.BlockingConnection,
    prefetch_count: int = 1,
) -> pika.adapters.blocking_connection.BlockingChannel:
    channel = connection.channel()
    channel.basic_qos(prefetch_count=prefetch_count)

    declare_topology(
        channel,
        exchange=settings.tasks_exchange,
        queue=settings.tasks_queue,
        routing_key=settings.tasks_routing_key,
    )
    logger.info("rabbitmq_channel_ready exchange=%s queue=%s", settings.tasks_exchange, settings.tasks_queue)
    return channel
