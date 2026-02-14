import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def load_task(db: Session, task_id: uuid.UUID) -> dict | None:
    row = db.execute(
        text("SELECT id, status, qc FROM tasks WHERE id = :id"),
        {"id": task_id},
    ).fetchone()
    if row is None:
        return None
    return {"id": row.id, "status": row.status, "qc": row.qc}


def try_transition_to_processing(db: Session, task_id: uuid.UUID) -> bool:
    """Atomically transition queued -> processing. Returns True if successful."""
    result = db.execute(
        text(
            "UPDATE tasks SET status = 'processing', processing_started_at = :now, updated_at = :now "
            "WHERE id = :id AND status = 'queued'"
        ),
        {"id": task_id, "now": datetime.now(timezone.utc)},
    )
    db.commit()
    return result.rowcount > 0


def mark_completed(db: Session, task_id: uuid.UUID, result_json: dict) -> None:
    import json
    db.execute(
        text(
            "UPDATE tasks SET status = 'completed', result_json = CAST(:result AS JSONB), "
            "completed_at = :now, updated_at = :now, error_message = NULL "
            "WHERE id = :id"
        ),
        {"id": task_id, "result": json.dumps(result_json), "now": datetime.now(timezone.utc)},
    )
    db.commit()


def mark_failed(db: Session, task_id: uuid.UUID, error_message: str) -> None:
    db.execute(
        text(
            "UPDATE tasks SET status = 'failed', error_message = :error, updated_at = :now "
            "WHERE id = :id"
        ),
        {"id": task_id, "error": error_message, "now": datetime.now(timezone.utc)},
    )
    db.commit()
