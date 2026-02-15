import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from shared.constants import TaskStatus

logger = logging.getLogger(__name__)


def try_claim_task(db: Session, task_id: uuid.UUID) -> dict | None:
    """Atomically transition queued -> processing and return task data.
    Returns None if task doesn't exist or is not in 'queued' status.
    """
    result = db.execute(
        text(
            "UPDATE tasks SET status = :processing, processing_started_at = :now, updated_at = :now "
            "WHERE id = :id AND status = :queued "
            "RETURNING id, qc"
        ),
        {
            "id": task_id,
            "now": datetime.now(timezone.utc),
            "processing": TaskStatus.PROCESSING,
            "queued": TaskStatus.QUEUED,
        },
    ).fetchone()
    db.commit()
    if result is None:
        return None
    return {"id": result.id, "qc": result.qc}


def mark_completed(db: Session, task_id: uuid.UUID, result_json: dict) -> None:
    db.execute(
        text(
            "UPDATE tasks SET status = :status, result_json = CAST(:result AS JSONB), "
            "completed_at = :now, updated_at = :now, error_message = NULL "
            "WHERE id = :id"
        ),
        {
            "id": task_id,
            "result": json.dumps(result_json),
            "now": datetime.now(timezone.utc),
            "status": TaskStatus.COMPLETED,
        },
    )
    db.commit()
    logger.info("task_marked_completed task_id=%s", task_id)


def mark_failed(db: Session, task_id: uuid.UUID, error_message: str) -> None:
    db.execute(
        text(
            "UPDATE tasks SET status = :status, error_message = :error, updated_at = :now "
            "WHERE id = :id"
        ),
        {
            "id": task_id,
            "error": error_message,
            "now": datetime.now(timezone.utc),
            "status": TaskStatus.FAILED,
        },
    )
    db.commit()
    logger.info("task_marked_failed task_id=%s error=%s", task_id, error_message)
