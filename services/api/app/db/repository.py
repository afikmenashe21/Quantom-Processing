import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import OutboxEvent, Task


def create_task_with_outbox(db: Session, qc: str) -> Task:
    """Insert task + outbox event + NOTIFY in a single transaction."""
    task = Task(id=uuid.uuid4(), qc=qc, status="queued")
    with db.begin():
        db.add(task)
        db.flush()

        outbox = OutboxEvent(
            event_type="task_queued",
            aggregate_id=task.id,
            payload={"task_id": str(task.id)},
            status="pending",
        )
        db.add(outbox)
        db.flush()

        db.execute(text("SELECT pg_notify('outbox_new', :payload)"), {"payload": str(outbox.id)})
    return task


def get_task_by_id(db: Session, task_id: uuid.UUID) -> Task | None:
    return db.get(Task, task_id)
