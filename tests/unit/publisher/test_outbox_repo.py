from unittest.mock import MagicMock, patch

import pytest

from app.outbox_repository import (
    _backoff_seconds,
    claim_pending_rows,
    mark_attempt_failed,
    mark_sent,
)


class TestBackoffSeconds:
    def test_zero_attempts(self):
        assert _backoff_seconds(0) == 0

    @pytest.mark.parametrize(
        "attempts,expected",
        [(1, 1), (2, 2), (3, 4), (4, 8), (5, 16), (6, 32)],
    )
    def test_exponential(self, attempts, expected):
        assert _backoff_seconds(attempts) == expected

    @pytest.mark.parametrize("attempts", [7, 8, 10, 20])
    def test_capped_at_60(self, attempts):
        assert _backoff_seconds(attempts) == 60


class TestClaimPendingRows:
    def test_empty_result(self, mock_db_session):
        mock_db_session.execute.return_value = iter([])
        rows = claim_pending_rows(mock_db_session, 100)
        assert rows == []

    def test_maps_fields(self, mock_db_session):
        mock_row = MagicMock()
        mock_row.id = 7
        mock_row.aggregate_id = "some-uuid"
        mock_row.payload = {"task_id": "t1"}
        mock_row.attempts = 3
        mock_db_session.execute.return_value = iter([mock_row])

        rows = claim_pending_rows(mock_db_session, 50)
        assert len(rows) == 1
        assert rows[0] == {
            "id": 7,
            "aggregate_id": "some-uuid",
            "payload": {"task_id": "t1"},
            "attempts": 3,
        }


class TestMarkSent:
    def test_executes_update(self, mock_db_session):
        mark_sent(mock_db_session, 42)
        mock_db_session.execute.assert_called_once()
        call_args = mock_db_session.execute.call_args
        params = call_args[0][1]
        assert params["id"] == 42
        assert "now" in params


class TestMarkAttemptFailed:
    @patch("app.outbox_repository.settings")
    def test_under_max_stays_pending(self, mock_settings, mock_db_session):
        mock_settings.outbox_max_attempts = 20
        mark_attempt_failed(mock_db_session, 1, 5, "some error")
        call_args = mock_db_session.execute.call_args
        params = call_args[0][1]
        assert params["attempts"] == 6
        assert params["status"] == "pending"
        assert params["error"] == "some error"

    @patch("app.outbox_repository.settings")
    def test_at_max_becomes_failed(self, mock_settings, mock_db_session):
        mock_settings.outbox_max_attempts = 20
        mark_attempt_failed(mock_db_session, 1, 19, "final error")
        call_args = mock_db_session.execute.call_args
        params = call_args[0][1]
        assert params["attempts"] == 20
        assert params["status"] == "failed"
