import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings

logger = logging.getLogger(__name__)


def _backoff_seconds(attempts: int) -> int:
    """Exponential backoff capped at 60s: 0, 1, 2, 4, 8, 16, 32, 60, 60, ..."""
    if attempts == 0:
        return 0
    return min(2 ** (attempts - 1), 60)


def claim_pending_rows(db: Session, batch_size: int) -> list[dict]:
    """Claim up to batch_size pending outbox rows using FOR UPDATE SKIP LOCKED.
    Rows with previous failures are skipped until their backoff interval has elapsed.
    """
    result = db.execute(
        text(
            "SELECT id, aggregate_id, payload, attempts "
            "FROM outbox "
            "WHERE status = 'pending' "
            "AND (attempts = 0 OR sent_at IS NULL "
            "     OR sent_at + make_interval(secs => LEAST(POWER(2, attempts - 1), 60)) <= now()) "
            "ORDER BY id ASC "
            "LIMIT :batch "
            "FOR UPDATE SKIP LOCKED"
        ),
        {"batch": batch_size},
    )
    return [
        {
            "id": row.id,
            "aggregate_id": str(row.aggregate_id),
            "payload": row.payload,
            "attempts": row.attempts,
        }
        for row in result
    ]


def mark_sent(db: Session, outbox_id: int) -> None:
    db.execute(
        text(
            "UPDATE outbox SET status = 'sent', sent_at = :now "
            "WHERE id = :id"
        ),
        {"id": outbox_id, "now": datetime.now(timezone.utc)},
    )


def mark_attempt_failed(db: Session, outbox_id: int, attempts: int, error: str) -> None:
    new_attempts = attempts + 1
    new_status = "failed" if new_attempts >= settings.outbox_max_attempts else "pending"
    db.execute(
        text(
            "UPDATE outbox SET attempts = :attempts, last_error = :error, status = :status, "
            "sent_at = :now WHERE id = :id"
        ),
        {
            "id": outbox_id,
            "attempts": new_attempts,
            "error": error,
            "status": new_status,
            "now": datetime.now(timezone.utc),
        },
    )
    if new_status == "failed":
        logger.error("outbox_exhausted outbox_id=%s attempts=%s", outbox_id, new_attempts)
