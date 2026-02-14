import uuid
from unittest.mock import MagicMock, call, patch

from app.db.repository import create_task_with_outbox, get_task_by_id


class TestCreateTaskWithOutbox:
    def test_inserts_task_and_outbox(self, mock_db_session):
        db = mock_db_session
        task = create_task_with_outbox(db, "OPENQASM 3;")

        # Two db.add calls: task + outbox event
        assert db.add.call_count == 2
        # Two flushes
        assert db.flush.call_count == 2
        # pg_notify called
        db.execute.assert_called_once()
        sql_text = db.execute.call_args[0][0]
        assert "pg_notify" in str(sql_text)

    def test_returns_queued_task(self, mock_db_session):
        task = create_task_with_outbox(mock_db_session, "OPENQASM 3; qubit q;")
        assert task.qc == "OPENQASM 3; qubit q;"
        assert task.status == "queued"
        assert task.id is not None


class TestGetTaskById:
    def test_delegates_to_session_get(self, mock_db_session):
        task_id = uuid.uuid4()
        mock_db_session.get.return_value = "fake_task"
        result = get_task_by_id(mock_db_session, task_id)
        assert result == "fake_task"
        mock_db_session.get.assert_called_once()
