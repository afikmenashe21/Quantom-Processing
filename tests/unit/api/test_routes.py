import uuid
from unittest.mock import MagicMock, patch

import pytest

# Mock create_engine before session module loads (avoids psycopg dependency)
import sqlalchemy  # noqa: E402

_real_create_engine = sqlalchemy.create_engine
sqlalchemy.create_engine = lambda *a, **kw: MagicMock()

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api.routes import router  # noqa: E402
from app.db.session import get_db  # noqa: E402

# Build a test app without the Alembic migration lifespan
_test_app = FastAPI()
_test_app.include_router(router)

# Restore create_engine
sqlalchemy.create_engine = _real_create_engine


@pytest.fixture
def mock_task():
    task = MagicMock()
    task.id = uuid.uuid4()
    task.qc = "OPENQASM 3; qubit q;"
    task.status = "queued"
    task.result_json = None
    task.error_message = None
    return task


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def client(mock_db):
    """TestClient with overridden get_db dependency."""
    def override_get_db():
        yield mock_db

    _test_app.dependency_overrides[get_db] = override_get_db
    with TestClient(_test_app, raise_server_exceptions=False) as tc:
        yield tc
    _test_app.dependency_overrides.clear()


class TestPostTask:
    @patch("app.api.routes.create_task_with_outbox")
    def test_post_task_success(self, mock_create, client, mock_task):
        mock_create.return_value = mock_task
        resp = client.post("/tasks", json={"qc": "OPENQASM 3; qubit q;"})
        assert resp.status_code == 201
        body = resp.json()
        assert body["task_id"] == str(mock_task.id)
        assert body["message"] == "Task submitted successfully."
        mock_create.assert_called_once()

    @patch("app.api.routes.create_task_with_outbox")
    def test_post_task_payload_too_large(self, mock_create, client):
        huge_qc = "x" * (1_048_576 + 1)
        resp = client.post("/tasks", json={"qc": huge_qc})
        assert resp.status_code == 413
        mock_create.assert_not_called()

    def test_post_task_missing_qc(self, client):
        resp = client.post("/tasks", json={})
        assert resp.status_code == 422

    def test_post_task_empty_qc(self, client):
        resp = client.post("/tasks", json={"qc": ""})
        assert resp.status_code == 422


class TestGetTask:
    @patch("app.api.routes.get_task_by_id")
    def test_get_task_completed(self, mock_get, client, mock_task):
        mock_task.status = "completed"
        mock_task.result_json = {"0": 512, "1": 512}
        mock_get.return_value = mock_task
        resp = client.get(f"/tasks/{mock_task.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        assert body["result"] == {"0": 512, "1": 512}

    @patch("app.api.routes.get_task_by_id")
    def test_get_task_queued(self, mock_get, client, mock_task):
        mock_task.status = "queued"
        mock_get.return_value = mock_task
        resp = client.get(f"/tasks/{mock_task.id}")
        body = resp.json()
        assert body["status"] == "pending"
        assert body["message"] == "Task is still in progress."

    @patch("app.api.routes.get_task_by_id")
    def test_get_task_processing(self, mock_get, client, mock_task):
        mock_task.status = "processing"
        mock_get.return_value = mock_task
        resp = client.get(f"/tasks/{mock_task.id}")
        body = resp.json()
        assert body["status"] == "pending"

    @patch("app.api.routes.get_task_by_id")
    def test_get_task_failed_with_message(self, mock_get, client, mock_task):
        mock_task.status = "failed"
        mock_task.error_message = "Simulation error"
        mock_get.return_value = mock_task
        resp = client.get(f"/tasks/{mock_task.id}")
        body = resp.json()
        assert body["status"] == "error"
        assert body["message"] == "Task failed."
        assert body["details"] == "Simulation error"

    @patch("app.api.routes.get_task_by_id")
    def test_get_task_failed_no_message(self, mock_get, client, mock_task):
        mock_task.status = "failed"
        mock_task.error_message = None
        mock_get.return_value = mock_task
        resp = client.get(f"/tasks/{mock_task.id}")
        body = resp.json()
        assert body["status"] == "error"
        assert body["details"] == "Unknown error."

    @patch("app.api.routes.get_task_by_id")
    def test_get_task_not_found(self, mock_get, client):
        mock_get.return_value = None
        resp = client.get(f"/tasks/{uuid.uuid4()}")
        body = resp.json()
        assert body["status"] == "error"
        assert body["message"] == "Task not found."


class TestHealthz:
    def test_healthz(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
