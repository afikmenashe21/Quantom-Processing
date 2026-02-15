import json
import logging
import signal
import time
import traceback
import uuid
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

import pika

from shared.db import build_session_factory

from app.config import settings
from app.db_repository import mark_completed, mark_failed, try_claim_task
from app.logging import setup_logging
from app.rabbitmq_client import create_connection, setup_channel
from app.task_processor import execute_qasm3

setup_logging()
logger = logging.getLogger(__name__)

# Type alias for in-flight tracking
InFlightEntry = tuple[Future, uuid.UUID, int]  # (future, task_id, delivery_tag)


def _init_child_process() -> None:
    """Initializer for ProcessPoolExecutor child processes."""
    setup_logging()


def handle_incoming_message(
    session_factory,
    pool: ProcessPoolExecutor,
    in_flight: dict[int, InFlightEntry],
    channel: pika.adapters.blocking_connection.BlockingChannel,
    method: pika.spec.Basic.Deliver,
    body: bytes,
) -> None:
    """Parse message, claim task in DB, submit to pool. Main thread only."""
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

    try:
        future = pool.submit(execute_qasm3, task["qc"], settings.shots)
    except (BrokenProcessPool, RuntimeError) as e:
        logger.error("pool_submit_failed task_id=%s error=%s", task_id, e)
        with session_factory() as db:
            mark_failed(db, task_id, f"pool_submit_failed: {e}")
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        raise

    in_flight[method.delivery_tag] = (future, task_id, method.delivery_tag)
    logger.info(
        "task_submitted_to_pool task_id=%s delivery_tag=%s in_flight=%d",
        task_id, method.delivery_tag, len(in_flight),
    )


def reap_completed_futures(
    session_factory,
    channel: pika.adapters.blocking_connection.BlockingChannel,
    in_flight: dict[int, InFlightEntry],
) -> None:
    """Check for completed futures, persist results, ACK/NACK. Main thread only."""
    completed_tags = []
    for delivery_tag, (future, task_id, _) in in_flight.items():
        if not future.done():
            continue
        completed_tags.append(delivery_tag)

        try:
            counts = future.result()
            with session_factory() as db:
                mark_completed(db, task_id, counts)
            logger.info("task_completed task_id=%s counts_keys=%s", task_id, list(counts.keys()))
            channel.basic_ack(delivery_tag=delivery_tag)
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            logger.error(
                "task_failed task_id=%s error=%s\n%s",
                task_id, error_msg, traceback.format_exc(),
            )
            with session_factory() as db:
                mark_failed(db, task_id, error_msg)
            channel.basic_nack(delivery_tag=delivery_tag, requeue=False)

    for tag in completed_tags:
        del in_flight[tag]


def drain_in_flight(
    session_factory,
    channel: pika.adapters.blocking_connection.BlockingChannel | None,
    in_flight: dict[int, InFlightEntry],
    timeout: float = 300.0,
) -> None:
    """Wait for all in-flight futures, persist DB state, ACK if channel available."""
    if not in_flight:
        return

    logger.info("draining_in_flight count=%d timeout=%.0fs", len(in_flight), timeout)
    deadline = time.monotonic() + timeout

    while in_flight and time.monotonic() < deadline:
        completed_tags = []
        for delivery_tag, (future, task_id, _) in in_flight.items():
            if not future.done():
                continue
            completed_tags.append(delivery_tag)

            try:
                counts = future.result()
                with session_factory() as db:
                    mark_completed(db, task_id, counts)
                logger.info("drain_task_completed task_id=%s", task_id)
                if channel is not None and channel.is_open:
                    channel.basic_ack(delivery_tag=delivery_tag)
            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                logger.error("drain_task_failed task_id=%s error=%s", task_id, error_msg)
                with session_factory() as db:
                    mark_failed(db, task_id, error_msg)
                if channel is not None and channel.is_open:
                    channel.basic_nack(delivery_tag=delivery_tag, requeue=False)

        for tag in completed_tags:
            del in_flight[tag]

        if in_flight:
            time.sleep(0.1)

    if in_flight:
        logger.warning("drain_timeout remaining=%d", len(in_flight))


def run() -> None:
    concurrency = settings.worker_concurrency
    session_factory = build_session_factory(
        settings.database_url,
        pool_size=concurrency + 2,
    )

    logger.info(
        "worker_starting shots=%s concurrency=%d rabbitmq_url=%s tasks_queue=%s",
        settings.shots, concurrency, settings.rabbitmq_url, settings.tasks_queue,
    )

    shutting_down = False

    def _signal_handler(signum, frame):
        nonlocal shutting_down
        logger.info("shutdown_signal_received signal=%s", signum)
        shutting_down = True

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    pool = ProcessPoolExecutor(
        max_workers=concurrency,
        initializer=_init_child_process,
    )

    while not shutting_down:
        in_flight: dict[int, InFlightEntry] = {}
        channel = None

        try:
            connection = create_connection()
            channel = setup_channel(connection, prefetch_count=concurrency)

            def on_message(ch, method, properties, body):
                handle_incoming_message(session_factory, pool, in_flight, ch, method, body)

            channel.basic_consume(queue=settings.tasks_queue, on_message_callback=on_message)
            logger.info("worker_consuming queue=%s concurrency=%d", settings.tasks_queue, concurrency)

            while not shutting_down:
                connection.process_data_events(time_limit=1)
                reap_completed_futures(session_factory, channel, in_flight)

        except pika.exceptions.AMQPConnectionError as e:
            logger.warning("rabbitmq_connection_lost error=%s", e)
        except BrokenProcessPool:
            logger.error("process_pool_broken — recreating pool")
            pool.shutdown(wait=False)
            pool = ProcessPoolExecutor(
                max_workers=concurrency,
                initializer=_init_child_process,
            )
        except Exception as e:
            logger.error("worker_error error=%s\n%s", e, traceback.format_exc())
        finally:
            # Drain in-flight futures — DB writes still possible even if channel is gone
            drain_in_flight(session_factory, channel, in_flight)

        if not shutting_down:
            logger.info("worker_reconnecting in 2s")
            time.sleep(2)

    logger.info("worker_shutdown_start pool_shutdown")
    pool.shutdown(wait=True, cancel_futures=False)
    logger.info("worker_shutdown_complete")


if __name__ == "__main__":
    run()
