import uuid
from unittest.mock import MagicMock

from app.db_repository import mark_completed, mark_failed, try_claim_task


class TestTryClaimTask:
    def test_success_returns_dict(self, mock_db_session):
        mock_row = MagicMock()
        mock_row.id = uuid.uuid4()
        mock_row.qc = "OPENQASM 3; qubit q;"
        mock_db_session.execute.return_value.fetchone.return_value = mock_row

        result = try_claim_task(mock_db_session, mock_row.id)
        assert result == {"id": mock_row.id, "qc": "OPENQASM 3; qubit q;"}
        mock_db_session.commit.assert_called_once()

    def test_not_found_returns_none(self, mock_db_session):
        mock_db_session.execute.return_value.fetchone.return_value = None
        result = try_claim_task(mock_db_session, uuid.uuid4())
        assert result is None
        mock_db_session.commit.assert_called_once()


class TestMarkCompleted:
    def test_executes_update_and_commits(self, mock_db_session):
        tid = uuid.uuid4()
        counts = {"0": 512, "1": 512}
        mark_completed(mock_db_session, tid, counts)

        mock_db_session.execute.assert_called_once()
        params = mock_db_session.execute.call_args[0][1]
        assert params["id"] == tid
        assert '"0": 512' in params["result"]
        assert "now" in params
        mock_db_session.commit.assert_called_once()


class TestMarkFailed:
    def test_executes_update_and_commits(self, mock_db_session):
        tid = uuid.uuid4()
        mark_failed(mock_db_session, tid, "RuntimeError: boom")

        mock_db_session.execute.assert_called_once()
        params = mock_db_session.execute.call_args[0][1]
        assert params["id"] == tid
        assert params["error"] == "RuntimeError: boom"
        mock_db_session.commit.assert_called_once()
