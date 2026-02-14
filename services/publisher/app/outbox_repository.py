import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings

logger = logging.getLogger(__name__)


def claim_pending_rows(db: Session, batch_size: int) -> list[dict]:
    """Claim up to batch_size pending outbox rows using FOR UPDATE SKIP LOCKED."""
    result = db.execute(
        text(
            "SELECT id, aggregate_id, payload, attempts "
            "FROM outbox "
            "WHERE status = 'pending' "
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
            "UPDATE outbox SET attempts = :attempts, last_error = :error, status = :status "
            "WHERE id = :id"
        ),
        {"id": outbox_id, "attempts": new_attempts, "error": error, "status": new_status},
    )
    if new_status == "failed":
        logger.error("outbox_exhausted outbox_id=%s attempts=%s", outbox_id, new_attempts)
