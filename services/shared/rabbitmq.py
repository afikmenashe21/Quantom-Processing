"""Shared RabbitMQ topology declaration."""

import pika

from shared.constants import RMQ_DLX, RMQ_DLQ


def declare_topology(
    channel: pika.adapters.blocking_connection.BlockingChannel,
    exchange: str,
    queue: str,
    routing_key: str,
) -> None:
    """Declare the full RabbitMQ topology: main exchange/queue + DLX/DLQ."""
    # Main exchange
    channel.exchange_declare(
        exchange=exchange, exchange_type="direct", durable=True
    )

    # Dead-letter exchange + queue
    channel.exchange_declare(
        exchange=RMQ_DLX, exchange_type="direct", durable=True
    )
    channel.queue_declare(queue=RMQ_DLQ, durable=True)
    channel.queue_bind(queue=RMQ_DLQ, exchange=RMQ_DLX, routing_key=routing_key)

    # Main queue with DLQ binding
    channel.queue_declare(
        queue=queue,
        durable=True,
        arguments={
            "x-dead-letter-exchange": RMQ_DLX,
            "x-dead-letter-routing-key": routing_key,
        },
    )
    channel.queue_bind(queue=queue, exchange=exchange, routing_key=routing_key)
