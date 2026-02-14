"""Shared constants used across services."""


class TaskStatus:
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class OutboxStatus:
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class EventType:
    TASK_QUEUED = "task_queued"


RMQ_DLX = "tasks.dlx"
RMQ_DLQ = "tasks.dlq"
