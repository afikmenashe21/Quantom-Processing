import json
import logging
import time
import traceback
import uuid

import pika

from shared.db import build_session_factory

from app.config import settings
from app.db_repository import mark_completed, mark_failed, try_claim_task
from app.logging import setup_logging
from app.rabbitmq_client import create_connection, setup_channel
from app.task_processor import execute_qasm3

setup_logging()
logger = logging.getLogger(__name__)


def handle_message(
    session_factory,
    channel: pika.adapters.blocking_connection.BlockingChannel,
    method: pika.spec.Basic.Deliver,
    body: bytes,
) -> None:
    try:
        payload = json.loads(body)
        task_id = uuid.UUID(payload["task_id"])
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error("invalid_message body=%s error=%s", body, e)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    logger.info("worker_received task_id=%s", task_id)

    with session_factory() as db:
        task = try_claim_task(db, task_id)
        if task is None:
            logger.info("task_skip task_id=%s (not claimable)", task_id)
            channel.basic_ack(delivery_tag=method.delivery_tag)
            return

        logger.info("task_processing task_id=%s", task_id)

        try:
            counts = execute_qasm3(task["qc"])
            mark_completed(db, task_id, counts)
            logger.info("task_completed task_id=%s counts_keys=%s", task_id, list(counts.keys()))
            channel.basic_ack(delivery_tag=method.delivery_tag)
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            logger.error("task_failed task_id=%s error=%s\n%s", task_id, error_msg, traceback.format_exc())
            mark_failed(db, task_id, error_msg)
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def run() -> None:
    session_factory = build_session_factory(settings.database_url, pool_size=2)
    logger.info(
        "worker_starting shots=%s rabbitmq_url=%s tasks_queue=%s tasks_exchange=%s",
        settings.shots, settings.rabbitmq_url, settings.tasks_queue, settings.tasks_exchange,
    )

    while True:
        try:
            connection = create_connection()
            channel = setup_channel(connection)

            def on_message(ch, method, properties, body):
                handle_message(session_factory, ch, method, body)

            channel.basic_consume(queue=settings.tasks_queue, on_message_callback=on_message)
            logger.info("worker_consuming queue=%s", settings.tasks_queue)
            channel.start_consuming()
        except pika.exceptions.AMQPConnectionError as e:
            logger.warning("rabbitmq_reconnect error=%s", e)
            time.sleep(2)
        except Exception as e:
            logger.error("worker_error error=%s\n%s", e, traceback.format_exc())
            time.sleep(2)


if __name__ == "__main__":
    run()
