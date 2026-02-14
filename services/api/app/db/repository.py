import logging
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from shared.constants import EventType, OutboxStatus, TaskStatus

from app.db.models import OutboxEvent, Task

logger = logging.getLogger(__name__)


def create_task_with_outbox(db: Session, qc: str) -> Task:
    """Insert task + outbox event + NOTIFY in a single transaction."""
    task = Task(id=uuid.uuid4(), qc=qc, status=TaskStatus.QUEUED)
    logger.debug("creating_task task_id=%s qc_length=%d", task.id, len(qc))
    with db.begin():
        db.add(task)
        db.flush()

        outbox = OutboxEvent(
            event_type=EventType.TASK_QUEUED,
            aggregate_id=task.id,
            payload={"task_id": str(task.id)},
            status=OutboxStatus.PENDING,
        )
        db.add(outbox)
        db.flush()

        db.execute(text("SELECT pg_notify('outbox_new', :payload)"), {"payload": str(outbox.id)})
        logger.debug("pg_notify_sent outbox_id=%s task_id=%s", outbox.id, task.id)
    return task


def get_task_by_id(db: Session, task_id: uuid.UUID) -> Task | None:
    return db.get(Task, task_id)
