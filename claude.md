# claude.md — Async QASM3 Task Processing Pipeline (FastAPI + Postgres Outbox + RabbitMQ)

## 0) Goal & constraints

Build a system that:

- Accepts async quantum compute tasks via `POST /tasks` with body `{ "qc": "<qasm3 string>" }` and returns `{ task_id, message }`.
- Exposes `GET /tasks/<id>` returning either: completed (with counts), pending, or not found.
- Guarantees **task integrity** (“no lost tasks”), supports **Docker Compose**, robust logging, and integration tests.
- Implemented in **Python 3.9+** using a lightweight framework.

> Non‑negotiables:
> - Must use **Transactional Outbox** (no direct publish to RabbitMQ in the POST handler).
> - Worker must be **idempotent** and **ack only after DB commit**.
> - `docker-compose up` must run end-to-end.

---

## 1) Architecture (monorepo, multi-service)

### Services
1. **api** (FastAPI)
   - Handles REST endpoints.
   - Persists tasks + outbox events in a single DB transaction.
2. **publisher** (Outbox publisher)
   - Uses **Postgres LISTEN/NOTIFY** to react immediately to new outbox rows.
   - Keeps a **poll fallback** to guarantee recovery if notifications are missed.
3. **worker**
   - Consumes the tasks queue from RabbitMQ.
   - Executes QASM3 circuit via Qiskit/Aer.
   - Stores results in Postgres.
4. **postgres** (source of truth)
5. **rabbitmq** (task queue)

### Why this design
- Postgres is the source-of-truth for task state & results.
- RabbitMQ provides classic “task queue” semantics (ack on success, retry/ DLQ on failure).
- **Transactional Outbox** ensures no task is lost between “DB write” and “broker publish”.

---

## 2) Locked implementation decisions

### DB access approach
- Use **sync SQLAlchemy (2.x) + psycopg** across **api / publisher / worker**.
  - Rationale: simplest + most reliable for a home exercise; DB ops are small and background components are separate processes.

### Shots configuration
- Simulation "shots" must be **configurable** via env var:
  - `SHOTS` (default: `1024`)
- Worker must validate `SHOTS` is a positive int.

### Qiskit version pinning
- Use `qiskit>=1.0,<2.0` and `qiskit-aer>=0.14,<1.0` in worker requirements.
- Import path: `from qiskit_aer import AerSimulator` (not the legacy `qiskit.providers.aer` path).
- QASM3 loading: `from qiskit.qasm3 import loads`.

---

## 3) Task lifecycle & API contract

### Task statuses (DB)
- `queued` → created, not yet processed (may or may not already be published)
- `processing` → worker started
- `completed` → result stored
- `failed` → error stored

### REST endpoints

#### `POST /tasks`
Request:
```json
{ "qc": "OPENQASM 3; ..." }
```

Response (200 or 201):
```json
{
  "task_id": "<uuid>",
  "message": "Task submitted successfully."
}
```

Validation rules:
- `qc` must be a non-empty string.
- Optional size guard (e.g., 1MB) to avoid abuse; if exceeded return 413/400.

#### `GET /tasks/{task_id}`
If completed:
```json
{
  "status": "completed",
  "result": { "0": 512, "1": 512 }
}
```

If pending (queued/processing/failed are mapped; see mapping below):
```json
{
  "status": "pending",
  "message": "Task is still in progress."
}
```

If not found:
```json
{
  "status": "error",
  "message": "Task not found."
}
```

**Status mapping for GET:**
- `completed` → completed response with `result`
- `queued` or `processing` → pending response
- `failed` → choose one:
  - Option A (simple): return `pending` (keeps contract minimal)
  - Option B (better UX): return `{status:"error", message:"Task failed", details:"..."}`

Lock decision: **Option B** (return error for failed), but keep response shape consistent:
```json
{ "status":"error", "message":"Task failed.", "details":"<error_message>" }
```

---

## 4) Database schema (Postgres)

Use Alembic migrations.

### `tasks` table
- `id UUID PRIMARY KEY`
- `qc TEXT NOT NULL`
- `status TEXT NOT NULL CHECK (status in ('queued','processing','completed','failed'))`
- `result_json JSONB NULL`  (counts dict when completed)
- `error_message TEXT NULL`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `processing_started_at TIMESTAMPTZ NULL`
- `completed_at TIMESTAMPTZ NULL`

Indexes:
- `tasks(status)`
- `tasks(created_at)`

### `outbox` table (Transactional Outbox)
- `id BIGSERIAL PRIMARY KEY`
- `event_type TEXT NOT NULL` (always `"task_queued"` for now)
- `aggregate_id UUID NOT NULL` (task_id)
- `payload JSONB NOT NULL` (at minimum `{ "task_id": "<uuid>" }`)
- `status TEXT NOT NULL CHECK (status in ('pending','sent','failed')) DEFAULT 'pending'`
- `attempts INT NOT NULL DEFAULT 0`
- `last_error TEXT NULL`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `sent_at TIMESTAMPTZ NULL`

Indexes:
- `(status, created_at)`
- `aggregate_id`

---

## 5) Transactional Outbox semantics (must-follow)

### In `POST /tasks` (single DB transaction)
1. Insert into `tasks` with `status='queued'`.
2. Insert into `outbox` with:
   - `event_type='task_queued'`
   - `aggregate_id=task_id`
   - payload `{ "task_id": "<uuid>" }`
3. **Emit a Postgres NOTIFY** to wake the publisher:
   - `NOTIFY outbox_new, '<outbox_id>'` (payload informational only)
4. Commit.

**Important:** API does **not** publish to RabbitMQ directly.

### Publisher: hybrid LISTEN/NOTIFY + poll fallback (required)

Goal: publish quickly when new outbox rows are inserted, while preserving “no lost tasks” guarantees.

#### Core rules
- **Postgres is the source of truth.** NOTIFY is best-effort wake-up only.
- Publisher must still handle missed notifications by polling periodically.
- Publishing must be **idempotent-safe** (duplicate publishes OK; worker is idempotent).

#### Implementation
Publisher maintains a long-lived DB connection:

1. Run `LISTEN outbox_new`.
2. Event loop:
   - Wait for NOTIFY events.
   - On NOTIFY: call `drain_outbox_batch()` immediately.
3. **Poll fallback**:
   - Every `OUTBOX_POLL_INTERVAL_SEC` (default: 10s), call `drain_outbox_batch()` even if no notifications were received.

#### `drain_outbox_batch()` semantics
- In a DB transaction, claim up to `OUTBOX_BATCH_SIZE` pending rows using:
  - `SELECT ... FROM outbox WHERE status='pending' ORDER BY id ASC LIMIT :batch FOR UPDATE SKIP LOCKED`
- For each claimed row:
  1. Publish `{ "task_id": "<uuid>" }` to RabbitMQ (persistent message).
  2. On success: `UPDATE outbox SET status='sent', sent_at=now() WHERE id=:id`
  3. On failure:
     - `attempts += 1`, `last_error = <err>`
     - keep `status='pending'` until `attempts >= OUTBOX_MAX_ATTEMPTS` (default: 20)
     - after max attempts: set `status='failed'`

#### Backoff & resilience
- If RabbitMQ is down: keep retrying; poll fallback ensures eventual publish.
- Use exponential / capped backoff on consecutive failures (e.g., 1s → 2s → 5s → 10s).
- Multiple publisher instances are safe via `SKIP LOCKED`.

#### Config
- `OUTBOX_LISTEN_CHANNEL=outbox_new`
- `OUTBOX_BATCH_SIZE=100`
- `OUTBOX_POLL_INTERVAL_SEC=10`
- `OUTBOX_MAX_ATTEMPTS=20`

---

## 6) RabbitMQ topology

- Exchange: `tasks.exchange` (type: direct)
- Queue: `tasks.queue` (durable)
- Routing key: `tasks.queued`

Publisher publishes message:
```json
{ "task_id": "<uuid>" }
```

Recommended queue args:
- durable queue + persistent messages
- DLQ:
  - dead-letter-exchange: `tasks.dlx`
  - dead-letter-queue: `tasks.dlq`

---

## 7) Worker processing logic (correctness-first)

### Core rules
- **Ack only after DB commit** of final state update.
- Must be safe if the same message is received multiple times (at-least-once delivery).

### Algorithm (pseudo)
Upon message `{task_id}`:

1. Load task row by id.
   - If not found: ack and log (safe behavior).
2. If `status == 'completed'`: ack and skip.
3. Try to transition to processing atomically:
   - `UPDATE tasks SET status='processing', processing_started_at=now(), updated_at=now()`
   - `WHERE id=:id AND status='queued'`
   - If updated_rows == 0:
     - Another worker already handled it or it’s not queued.
     - Re-read task:
       - completed → ack
       - processing → ack (keep it simple; no lease logic)
       - failed → ack
4. Execute:
   - Parse QASM3 into circuit.
   - Run with Aer simulator with `shots=SHOTS`.
   - Get counts dict `{str: int}`.
5. Persist success:
   - `UPDATE tasks SET status='completed', result_json=:counts, completed_at=now(), updated_at=now(), error_message=NULL`
6. Ack message.

On exception:
- Persist failure:
  - `UPDATE tasks SET status='failed', error_message=:msg, updated_at=now()`
- Nack policy (locked):
  - For this exercise: `nack(requeue=false)` so it ends in DLQ (prevents infinite loops).
- Log stack trace.

### Idempotency guarantee
- The transition `queued → processing` is atomic.
- Duplicate deliveries are safe because:
  - already `completed` or `processing` tasks are not re-processed.

---

## 8) Docker Compose (must work via one command)

`deploy/docker-compose.yml` services:
- `postgres` (volume)
- `rabbitmq` (management UI enabled)
- `api` (expose port 8000)
- `publisher`
- `worker`

Health checks:
- Postgres readiness
- RabbitMQ readiness
- API `/healthz` endpoint

Shared env vars:
- `DATABASE_URL=postgresql+psycopg://user:pass@postgres:5432/db`
- `RABBITMQ_URL=amqp://user:pass@rabbitmq:5672/`
- `TASKS_EXCHANGE=tasks.exchange`
- `TASKS_QUEUE=tasks.queue`
- `TASKS_ROUTING_KEY=tasks.queued`
- `SHOTS=1024`

---

## 9) Observability & robustness

- Structured logging (key-value preferred).
- Log at least:
  - task_id
  - status transitions
  - outbox publish attempts
  - worker start/finish
  - exceptions (with stack traces)
- Correlation:
  - On POST: log generated task_id and include it in responses.

API health endpoint:
- `/healthz`: ping DB; return `{"ok": true}`.

---

## 10) Integration tests (required)

Use `pytest` + `httpx`.

### Test cases
1. `test_submit_task_and_complete`
   - POST /tasks with a minimal QASM3 producing measurable output.
   - Poll GET /tasks/{id} until `completed` or timeout.
   - Assert `result` is dict with string keys and integer values.
   - Assert sum(counts) == SHOTS (read SHOTS from env or assume default 1024 in test env).
2. `test_task_not_found`
   - GET /tasks/{random_uuid} returns not found response.
3. `test_invalid_payload`
   - POST with missing/empty `qc` returns 400/422.

### How to run tests
- Bring up compose.
- Run tests pointing to `http://localhost:8000`.

---

## 11) Repo structure (locked)

```
repo/
  services/
    api/
      app/
        main.py
        api/routes.py
        db/
          models.py
          session.py
          repository.py
        config.py
        logging.py
      Dockerfile
    publisher/
      app/
        main.py
        outbox_repository.py
        rabbitmq_client.py
        config.py
        logging.py
      Dockerfile
    worker/
      app/
        main.py
        task_processor.py
        db_repository.py
        rabbitmq_client.py
        config.py
        logging.py
      Dockerfile
  deploy/
    docker-compose.yml
  migrations/
  tests/
    integration/
  README.md
```

---

## 12) Build plan for Claude (step-by-step)

1. Generate repo skeleton, deps, dockerfiles, docker-compose.
2. Implement DB schema + Alembic migrations.
3. Implement API:
   - POST /tasks inserts into tasks + outbox + NOTIFY in one transaction
   - GET /tasks/{id} returns correct status mapping
   - /healthz
4. Implement publisher:
   - LISTEN/NOTIFY + poll fallback
   - drain_outbox_batch with `FOR UPDATE SKIP LOCKED`
   - publish to RabbitMQ (persistent messages)
   - mark outbox sent / attempts / failed
5. Implement worker:
   - consume queue
   - atomic status transition
   - execute QASM3 with Qiskit Aer
   - store result or error
   - ack after commit
6. Add integration tests + README instructions.

---

## 13) Acceptance checklist

- [ ] `docker-compose up` starts all services cleanly
- [ ] POST returns task_id immediately
- [ ] GET shows pending then completed with counts
- [ ] Tasks aren’t lost if RabbitMQ is down at POST time (they remain in DB and later published)
- [ ] Worker is idempotent; duplicates don’t double-compute
- [ ] Integration tests pass
- [ ] README documents how to run + test
