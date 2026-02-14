# Quantom Processing — Async QASM3 Task Pipeline

Asynchronous quantum circuit simulation pipeline built with **FastAPI**, **PostgreSQL**, **RabbitMQ**, and **Qiskit/Aer**.

## Architecture

```
┌────────┐    ┌──────────┐    ┌───────────┐    ┌────────┐
│ Client │───▶│   API    │───▶│ Postgres  │◀───│ Worker │
│        │    │ (FastAPI)│    │ (tasks +  │    │(Qiskit)│
└────────┘    └──────────┘    │  outbox)  │    └───┬────┘
                              └─────┬─────┘        │
                                    │              │
                              ┌─────▼─────┐        │
                              │ Publisher  │───▶┌───▼──────┐
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
- **Idempotent Worker**: Atomic `queued → processing` transition prevents duplicate computation. Already-completed tasks are skipped.
- **DLQ**: Failed messages go to a dead-letter queue instead of infinite requeue loops.

## Quick Start

### Prerequisites

- Docker & Docker Compose

### Run

```bash
cd deploy
docker compose up --build
```

This starts all 5 services. The API is available at `http://localhost:8000`.

RabbitMQ Management UI is at `http://localhost:15672` (user/pass).

### Submit a Task

```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"qc": "OPENQASM 3;\ninclude \"stdgates.inc\";\nqubit[1] q;\nbit[1] c;\nh q[0];\nc[0] = measure q[0];"}'
```

Response:
```json
{"task_id": "...", "message": "Task submitted successfully."}
```

### Check Task Status

```bash
curl http://localhost:8000/tasks/<task_id>
```

Responses:
- Pending: `{"status": "pending", "message": "Task is still in progress."}`
- Completed: `{"status": "completed", "result": {"0": 512, "1": 512}}`
- Not found: `{"status": "error", "message": "Task not found."}`
- Failed: `{"status": "error", "message": "Task failed.", "details": "..."}`

### Health Check

```bash
curl http://localhost:8000/healthz
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+psycopg://user:pass@postgres:5432/quantom` | PostgreSQL connection string |
| `RABBITMQ_URL` | `amqp://user:pass@rabbitmq:5672/` | RabbitMQ connection string |
| `SHOTS` | `1024` | Number of simulation shots |
| `TASKS_EXCHANGE` | `tasks.exchange` | RabbitMQ exchange name |
| `TASKS_QUEUE` | `tasks.queue` | RabbitMQ queue name |
| `TASKS_ROUTING_KEY` | `tasks.queued` | RabbitMQ routing key |

## Tests

### Unit Tests

58 unit tests covering all service logic with mocked dependencies.

| Service | Tests | Line Coverage |
|---------|-------|---------------|
| API (routes, repository) | 14 | 95% |
| Publisher (drain, outbox repo, RMQ client) | 30 | 88% |
| Worker (message handler, DB repo, task processor) | 14 | 90% |

Since all three services share the `app` package name, unit tests must run per-service in separate processes:

```bash
# Run all unit tests (subprocess isolation per service)
python3 tests/run_unit_tests.py

# With coverage
python3 tests/run_unit_tests.py --cov --cov-report=term-missing

# Single service
pytest tests/unit/api/ -v
pytest tests/unit/publisher/ -v
pytest tests/unit/worker/ -v
```

### Integration Tests

5 end-to-end tests that exercise the full stack (requires `docker compose up`):

```bash
pip install -r tests/requirements.txt
pytest tests/integration/ -v
```

Or with custom settings:

```bash
API_BASE_URL=http://localhost:8000 SHOTS=1024 pytest tests/integration/ -v
```

## Project Structure

```
services/
  api/            # FastAPI REST API + Alembic migrations
  publisher/      # Outbox publisher (LISTEN/NOTIFY + poll)
  worker/         # RabbitMQ consumer + Qiskit/Aer executor
deploy/
  docker-compose.yml
tests/
  unit/           # Per-service unit tests (mocked dependencies)
    api/          # Route branches, repository logic
    publisher/    # Outbox drain, backoff, RabbitMQ client
    worker/       # Message handler, DB repo, task processor
  integration/    # End-to-end integration tests
  run_unit_tests.py  # Subprocess runner for cross-service isolation
```
