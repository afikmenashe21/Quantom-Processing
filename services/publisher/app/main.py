import logging
import time

import psycopg

from shared.db import build_session_factory

from app.config import settings
from app.logging import setup_logging
from app.outbox_repository import claim_pending_rows, mark_attempt_failed, mark_sent
from app.rabbitmq_client import RabbitMQClient

setup_logging()
logger = logging.getLogger(__name__)


def extract_task_id(row: dict) -> str:
    """Extract task_id from outbox row payload with fallback to aggregate_id."""
    task_id = row["payload"].get("task_id", row["aggregate_id"])
    if task_id != row["payload"].get("task_id"):
        logger.warning("task_id_fallback outbox_id=%s using aggregate_id=%s", row["id"], task_id)
    return task_id


def drain_outbox_batch(session_factory, rmq: RabbitMQClient) -> int:
    """Claim and publish pending outbox rows. Returns number published."""
    published = 0
    with session_factory() as db:
        rows = claim_pending_rows(db, settings.outbox_batch_size)
        if rows:
            logger.debug("outbox_rows_claimed count=%d", len(rows))
        for row in rows:
            task_id = extract_task_id(row)
            try:
                rmq.publish(task_id)
                mark_sent(db, row["id"])
                db.commit()
                published += 1
                logger.info("outbox_published outbox_id=%s task_id=%s", row["id"], task_id)
            except Exception as e:
                db.rollback()
                logger.warning(
                    "outbox_publish_failed outbox_id=%s error=%s", row["id"], e
                )
                mark_attempt_failed(db, row["id"], row["attempts"], str(e))
                db.commit()
    if rows:
        logger.info("drain_batch_complete published=%d total=%d", published, len(rows))
    return published


def get_listen_dsn() -> str:
    """Convert SQLAlchemy URL to psycopg DSN for LISTEN."""
    url = settings.database_url
    if "+psycopg" in url:
        url = url.replace("+psycopg", "")
    return url


def run() -> None:
    session_factory = build_session_factory(settings.database_url, pool_size=2)

    rmq = RabbitMQClient()

    # Connect to RabbitMQ with retry
    while True:
        try:
            rmq.connect()
            logger.info("rabbitmq_connected")
            break
        except Exception as e:
            logger.warning("rabbitmq_connect_retry error=%s", e)
            time.sleep(2)

    # Initial drain on startup (may fail if migrations haven't run yet)
    try:
        drain_outbox_batch(session_factory, rmq)
    except Exception as e:
        logger.warning("initial_drain_skipped error=%s", e)

    dsn = get_listen_dsn()
    logger.info("publisher_starting channel=%s poll_interval=%ss", settings.outbox_listen_channel, settings.outbox_poll_interval_sec)

    while True:
        try:
            with psycopg.connect(dsn, autocommit=True) as conn:
                conn.execute(f"LISTEN {settings.outbox_listen_channel}")
                logger.info("listening channel=%s", settings.outbox_listen_channel)

                while True:
                    gen = conn.notifies(timeout=settings.outbox_poll_interval_sec)
                    for notify in gen:
                        logger.debug("notify_received payload=%s", notify.payload)
                        try:
                            drain_outbox_batch(session_factory, rmq)
                        except Exception as e:
                            logger.error("drain_error error=%s", e)
                        break

                    # Poll fallback
                    try:
                        drain_outbox_batch(session_factory, rmq)
                    except Exception as e:
                        logger.error("poll_drain_error error=%s", e)

        except Exception as e:
            logger.error("listen_connection_error error=%s", e)
            time.sleep(2)


if __name__ == "__main__":
    run()
