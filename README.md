# Quantom Processing — Async QASM3 Task Pipeline

Asynchronous quantum circuit simulation pipeline built with **FastAPI**, **PostgreSQL**, **RabbitMQ**, and **Qiskit/Aer**. Submit QASM3 circuits via a REST API, and retrieve simulation results asynchronously.

## Table of Contents

- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [API Reference](#api-reference)
- [Configuration](#configuration)
- [Project Structure](#project-structure)
- [Testing](#testing)
- [Database Schema](#database-schema)
- [Observability](#observability)
- [Troubleshooting](#troubleshooting)
- [Tech Stack](#tech-stack)
- [Contributing](#contributing)

## Architecture

```
┌────────┐    ┌──────────┐    ┌───────────┐    ┌────────┐
│ Client │───>│   API    │───>│ Postgres  │<───│ Worker │
│        │    │ (FastAPI)│    │ (tasks +  │    │(Qiskit)│
└────────┘    └──────────┘    │  outbox)  │    └───┬────┘
                              └─────┬─────┘        │
                                    │              │
                              ┌─────▼─────┐        │
                              │ Publisher  │───>┌───▼──────┐
                              │ (Outbox)   │   │ RabbitMQ │
                              └────────────┘   └──────────┘
```

### Services

| Service | Role |
|---------|------|
| **API** | REST endpoints. Persists tasks + outbox events in a single DB transaction. Runs Alembic migrations on startup. |
| **Publisher** | Reads outbox table via LISTEN/NOTIFY + poll fallback. Publishes to RabbitMQ. Uses `FOR UPDATE SKIP LOCKED` for safe concurrency. |
| **Worker** | Consumes RabbitMQ queue. Parses QASM3, runs AerSimulator, stores results. Idempotent — ack only after DB commit. |
| **PostgreSQL** | Source of truth for task state, results, and transactional outbox. |
| **RabbitMQ** | Task queue with DLQ for failed messages. |

### Key Design Decisions

- **Transactional Outbox Pattern**: The API never publishes to RabbitMQ directly. Task + outbox event are written in a single DB transaction, guaranteeing no lost tasks even if RabbitMQ is down.
- **LISTEN/NOTIFY + Poll Fallback**: Publisher reacts immediately to new outbox rows via Postgres notifications, with a periodic poll (default 10s) as a safety net.
- **Idempotent Worker**: Atomic `queued -> processing` transition prevents duplicate computation. Already-completed tasks are skipped.
- **DLQ**: Failed messages go to a dead-letter queue instead of infinite requeue loops.
- **Shared Package**: Common code (logging, DB session factory, RabbitMQ topology, constants) lives in `services/shared/` and is imported by all three services.

### Task Lifecycle

```
POST /tasks
    │
    ▼
 ┌──────┐    Publisher    ┌────────────┐    Worker    ┌───────────┐
 │queued│───────────────>│ processing │────────────>│ completed │
 └──────┘                └────────────┘             └───────────┘
                               │
                               ▼ (on error)
                          ┌────────┐
                          │ failed │
                          └────────┘
```

## Prerequisites

- **Docker** >= 20.10
- **Docker Compose** >= 2.0

For running tests locally (outside Docker):

- **Python** >= 3.11
- `pip install -r tests/requirements.txt`

## Quick Start

### 1. Build and run all services

```bash
cd deploy
docker compose up --build
```

This starts all 5 services. Wait for the health checks to pass (usually ~30s for first build).

### 2. Submit a task

```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"qc": "OPENQASM 3;\ninclude \"stdgates.inc\";\nqubit[1] q;\nbit[1] c;\nh q[0];\nc[0] = measure q[0];"}'
```

Response:
```json
{"task_id": "a1b2c3d4-...", "message": "Task submitted successfully."}
```

### 3. Poll for results

```bash
curl http://localhost:8000/tasks/<task_id>
```

### 4. Stop all services

```bash
docker compose down
```

To also remove persisted data:

```bash
docker compose down -v
```

### Access Points

| Service | URL |
|---------|-----|
| API | http://localhost:8000 |
| RabbitMQ Management UI | http://localhost:15672 (user: `user`, pass: `pass`) |
| PostgreSQL | `localhost:5432` (user: `user`, pass: `pass`, db: `quantom`) |

## API Reference

### `POST /tasks`

Submit a QASM3 circuit for asynchronous simulation.

**Request body:**
```json
{
  "qc": "OPENQASM 3; include \"stdgates.inc\"; qubit[1] q; bit[1] c; h q[0]; c[0] = measure q[0];"
}
```

**Validation:**
- `qc` must be a non-empty string.
- Maximum payload size: 1 MB (configurable via `MAX_QC_SIZE_BYTES`). Returns `413` if exceeded.

**Response (201):**
```json
{
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "message": "Task submitted successfully."
}
```

**Error responses:**
| Status | Condition |
|--------|-----------|
| 413 | QASM3 payload exceeds size limit |
| 422 | Missing or empty `qc` field |

### `GET /tasks/{task_id}`

Retrieve the status and result of a submitted task.

**Responses:**

Completed:
```json
{
  "status": "completed",
  "result": {"0": 512, "1": 512}
}
```

Pending (queued or processing):
```json
{
  "status": "pending",
  "message": "Task is still in progress."
}
```

Not found:
```json
{
  "status": "error",
  "message": "Task not found."
}
```

Failed:
```json
{
  "status": "error",
  "message": "Task failed.",
  "details": "RuntimeError: ..."
}
```

### `GET /healthz`

Health check endpoint. Pings the database.

**Response (200):**
```json
{"ok": true}
```

## Configuration

All services are configured via environment variables. Defaults are set for local Docker Compose usage.

### Common (all services)

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+psycopg://user:pass@postgres:5432/quantom` | PostgreSQL connection string (SQLAlchemy format) |
| `RABBITMQ_URL` | `amqp://user:pass@rabbitmq:5672/` | RabbitMQ connection string |
| `TASKS_EXCHANGE` | `tasks.exchange` | RabbitMQ exchange name |
| `TASKS_QUEUE` | `tasks.queue` | RabbitMQ queue name |
| `TASKS_ROUTING_KEY` | `tasks.queued` | RabbitMQ routing key |

### API

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_QC_SIZE_BYTES` | `1048576` | Maximum QASM3 payload size in bytes (1 MB) |

### Publisher

| Variable | Default | Description |
|----------|---------|-------------|
| `OUTBOX_LISTEN_CHANNEL` | `outbox_new` | Postgres LISTEN/NOTIFY channel name |
| `OUTBOX_BATCH_SIZE` | `100` | Max outbox rows claimed per drain cycle |
| `OUTBOX_POLL_INTERVAL_SEC` | `10` | Poll fallback interval in seconds |
| `OUTBOX_MAX_ATTEMPTS` | `20` | Max publish attempts before marking outbox row as failed |

### Worker

| Variable | Default | Description |
|----------|---------|-------------|
| `SHOTS` | `1024` | Number of simulation shots per circuit. Must be a positive integer. |

## Project Structure

```
services/
  shared/           # Shared code imported by all services
    constants.py    # TaskStatus, OutboxStatus, EventType, RMQ constants
    logging.py      # Common structured logging setup
    db.py           # SQLAlchemy session factory builder
    rabbitmq.py     # RabbitMQ topology declaration
  api/              # FastAPI REST API + Alembic migrations
    app/
      api/          # Routes, request/response models
      db/           # SQLAlchemy models, session, repository
      config.py     # Pydantic settings
      main.py       # App entrypoint, lifespan, migrations
    migrations/     # Alembic migration scripts
    Dockerfile
    requirements.txt
  publisher/        # Outbox publisher (LISTEN/NOTIFY + poll)
    app/
      main.py       # Event loop: listen + poll + drain
      outbox_repository.py  # Outbox claim/mark queries
      rabbitmq_client.py    # Persistent publish with reconnect
      config.py
    Dockerfile
    requirements.txt
  worker/           # RabbitMQ consumer + Qiskit/Aer executor
    app/
      main.py       # Consumer loop with reconnect
      task_processor.py     # QASM3 parse + AerSimulator execution
      db_repository.py      # Atomic task claim + result storage
      rabbitmq_client.py    # Connection + channel setup
      config.py
    Dockerfile
    requirements.txt
deploy/
  docker-compose.yml    # All 5 services orchestrated
tests/
  unit/                 # Per-service unit tests (mocked dependencies)
    api/                # Route branches, repository logic
    publisher/          # Outbox drain, backoff, RabbitMQ client
    worker/             # Message handler, DB repo, task processor
  integration/          # End-to-end tests (requires running stack)
  run_unit_tests.py     # Subprocess runner for cross-service isolation
  conftest.py           # Shared fixtures (mock session, channel, method)
  requirements.txt      # Test dependencies
```

## Testing

### Unit Tests

58 unit tests covering all service logic with mocked dependencies.

| Suite | Tests | Coverage |
|-------|-------|----------|
| API (routes, repository) | 14 | ~95% |
| Publisher (drain, outbox repo, RMQ client) | 30 | ~88% |
| Worker (message handler, DB repo, task processor) | 14 | ~90% |

Since all three services share the `app` package name, unit tests run per-service in separate processes:

```bash
# Run all unit tests
python3 tests/run_unit_tests.py

# With coverage
python3 tests/run_unit_tests.py --cov --cov-report=term-missing

# Single service
pytest tests/unit/api/ -v
pytest tests/unit/publisher/ -v
pytest tests/unit/worker/ -v
```

### Integration Tests

End-to-end tests that exercise the full stack. Requires `docker compose up` to be running.

```bash
# Install test dependencies
pip install -r tests/requirements.txt

# Run integration tests
pytest tests/integration/ -v

# With custom API URL
API_BASE_URL=http://localhost:8000 SHOTS=1024 pytest tests/integration/ -v
```

Integration test cases:
1. **Submit and complete** — POST a circuit, poll until completed, verify counts sum equals SHOTS.
2. **Task not found** — GET with random UUID returns not-found response.
3. **Invalid payload** — POST with missing/empty `qc` returns 422.

## Database Schema

Managed by Alembic. Migrations run automatically on API startup.

### `tasks` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | `UUID` (PK) | Task identifier |
| `qc` | `TEXT` | QASM3 circuit string |
| `status` | `TEXT` | One of: `queued`, `processing`, `completed`, `failed` |
| `result_json` | `JSONB` | Simulation counts (when completed) |
| `error_message` | `TEXT` | Error details (when failed) |
| `created_at` | `TIMESTAMPTZ` | Task creation time |
| `updated_at` | `TIMESTAMPTZ` | Last status change |
| `processing_started_at` | `TIMESTAMPTZ` | When worker claimed the task |
| `completed_at` | `TIMESTAMPTZ` | When simulation finished |

Indexes: `status`, `created_at`

### `outbox` table (Transactional Outbox)

| Column | Type | Description |
|--------|------|-------------|
| `id` | `BIGSERIAL` (PK) | Outbox event ID |
| `event_type` | `TEXT` | Event type (e.g. `task_queued`) |
| `aggregate_id` | `UUID` | Associated task ID |
| `payload` | `JSONB` | Event payload (`{"task_id": "..."}`) |
| `status` | `TEXT` | One of: `pending`, `sent`, `failed` |
| `attempts` | `INT` | Number of publish attempts |
| `last_error` | `TEXT` | Last publish error |
| `created_at` | `TIMESTAMPTZ` | Event creation time |
| `sent_at` | `TIMESTAMPTZ` | Last attempt time (used for backoff) |

Indexes: `(status, created_at)`, `aggregate_id`

## Observability

### Logging

All services use structured key-value logging to stdout:

```
2025-01-15T10:30:45 level=INFO logger=app.main task_created task_id=a1b2c3d4-...
```

Key log events:
- **API**: `task_created`, `task_not_found`, `task_failed_response`, `qc_payload_too_large`, `applying_migrations`, `migrations_applied`
- **Publisher**: `outbox_published`, `outbox_publish_failed`, `outbox_exhausted`, `drain_batch_complete`, `notify_received`, `rabbitmq_channel_reconnecting`
- **Worker**: `worker_received`, `task_claimed`, `task_claim_missed`, `task_completed`, `task_failed`, `task_marked_completed`, `task_marked_failed`, `qasm3_executed`

### RabbitMQ Topology

| Component | Name |
|-----------|------|
| Exchange | `tasks.exchange` (direct) |
| Queue | `tasks.queue` (durable) |
| Routing key | `tasks.queued` |
| Dead-letter exchange | `tasks.dlx` |
| Dead-letter queue | `tasks.dlq` |

## Troubleshooting

### Services won't start

```bash
# Check service logs
cd deploy
docker compose logs api
docker compose logs publisher
docker compose logs worker
```

### Tasks stuck in `queued` status

1. Check the publisher is running: `docker compose logs publisher`
2. Verify RabbitMQ is healthy: `docker compose logs rabbitmq`
3. Check the outbox table for failed rows:
   ```sql
   SELECT id, status, attempts, last_error FROM outbox WHERE status != 'sent' ORDER BY id DESC LIMIT 10;
   ```

### Worker errors

- Check worker logs: `docker compose logs worker`
- Inspect the dead-letter queue in RabbitMQ Management UI at http://localhost:15672
- Check task error details:
  ```sql
  SELECT id, status, error_message FROM tasks WHERE status = 'failed' ORDER BY created_at DESC LIMIT 10;
  ```

### Reset everything

```bash
cd deploy
docker compose down -v
docker compose up --build
```

## Tech Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| API framework | FastAPI | 0.115.6 |
| ASGI server | Uvicorn | 0.34.0 |
| ORM | SQLAlchemy | 2.0.36 |
| DB driver | psycopg | 3.2.4 |
| Migrations | Alembic | 1.14.1 |
| Message broker client | pika | 1.3.2 |
| Quantum simulator | Qiskit + Aer | >=1.0,<2.0 / >=0.14,<1.0 |
| Settings | pydantic-settings | 2.7.1 |
| Database | PostgreSQL | 16 |
| Message broker | RabbitMQ | 3.13 |
| Container runtime | Docker + Compose | - |
| Test framework | pytest | 8.3.4 |

## Contributing

1. Fork the repository.
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make changes and add tests.
4. Run unit tests: `python3 tests/run_unit_tests.py`
5. Run integration tests with the stack up: `pytest tests/integration/ -v`
6. Commit and push: `git push origin feature/my-feature`
7. Open a pull request.
