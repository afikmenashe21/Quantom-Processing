import os
import time
import uuid

import httpx
import pytest

BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
SHOTS = int(os.environ.get("SHOTS", "1024"))
POLL_TIMEOUT = int(os.environ.get("POLL_TIMEOUT", "60"))
POLL_INTERVAL = 2

# Minimal QASM3 circuit: single qubit, Hadamard, measure
MINIMAL_QASM3 = """
OPENQASM 3;
include "stdgates.inc";
qubit[1] q;
bit[1] c;
h q[0];
c[0] = measure q[0];
""".strip()


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=30) as c:
        yield c


def test_healthz(client: httpx.Client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_submit_task_and_complete(client: httpx.Client):
    # Submit
    resp = client.post("/tasks", json={"qc": MINIMAL_QASM3})
    assert resp.status_code == 201
    data = resp.json()
    assert "task_id" in data
    assert data["message"] == "Task submitted successfully."
    task_id = data["task_id"]

    # Poll until completed or timeout
    deadline = time.time() + POLL_TIMEOUT
    result = None
    while time.time() < deadline:
        resp = client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] == "completed":
            result = body["result"]
            break
        if body["status"] == "error":
            pytest.fail(f"Task failed: {body}")
        time.sleep(POLL_INTERVAL)
    else:
        pytest.fail(f"Task {task_id} did not complete within {POLL_TIMEOUT}s")

    # Validate counts
    assert isinstance(result, dict)
    assert len(result) > 0
    assert all(isinstance(k, str) for k in result.keys())
    assert all(isinstance(v, int) for v in result.values())
    assert sum(result.values()) == SHOTS


def test_task_not_found(client: httpx.Client):
    random_id = str(uuid.uuid4())
    resp = client.get(f"/tasks/{random_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert body["message"] == "Task not found."


def test_invalid_payload_missing_qc(client: httpx.Client):
    resp = client.post("/tasks", json={})
    assert resp.status_code == 422


def test_invalid_payload_empty_qc(client: httpx.Client):
    resp = client.post("/tasks", json={"qc": ""})
    assert resp.status_code == 422
