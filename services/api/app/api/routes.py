import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db.repository import create_task_with_outbox, get_task_by_id
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateTaskRequest(BaseModel):
    qc: str = Field(..., min_length=1)


class CreateTaskResponse(BaseModel):
    task_id: str
    message: str


@router.post("/tasks", status_code=201, response_model=CreateTaskResponse)
def submit_task(body: CreateTaskRequest, request: Request, db: Session = Depends(get_db)):
    if len(body.qc.encode("utf-8")) > settings.max_qc_size_bytes:
        raise HTTPException(status_code=413, detail="QASM3 payload too large.")

    task = create_task_with_outbox(db, body.qc)
    logger.info("task_created task_id=%s", task.id)
    return CreateTaskResponse(task_id=str(task.id), message="Task submitted successfully.")


@router.get("/tasks/{task_id}")
def get_task(task_id: uuid.UUID, db: Session = Depends(get_db)):
    task = get_task_by_id(db, task_id)
    if task is None:
        return {"status": "error", "message": "Task not found."}

    if task.status == "completed":
        return {"status": "completed", "result": task.result_json}

    if task.status == "failed":
        return {
            "status": "error",
            "message": "Task failed.",
            "details": task.error_message or "Unknown error.",
        }

    # queued or processing
    return {"status": "pending", "message": "Task is still in progress."}


@router.get("/healthz")
def healthz(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"ok": True}
