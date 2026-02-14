import uuid
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def session_factory():
    mock_session = MagicMock()
    factory = MagicMock()
    factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    factory.return_value.__exit__ = MagicMock(return_value=False)
    factory._mock_session = mock_session
    return factory


@pytest.fixture
def rmq_client():
    return MagicMock()


class TestDrainOutboxBatch:
    @patch("app.main.claim_pending_rows", return_value=[])
    def test_drain_empty_batch(self, mock_claim, session_factory, rmq_client):
        from app.main import drain_outbox_batch
        result = drain_outbox_batch(session_factory, rmq_client)
        assert result == 0
        rmq_client.publish.assert_not_called()

    @patch("app.main.mark_sent")
    @patch("app.main.claim_pending_rows")
    def test_drain_single_row_success(self, mock_claim, mock_mark_sent, session_factory, rmq_client):
        from app.main import drain_outbox_batch
        row = {"id": 1, "aggregate_id": str(uuid.uuid4()), "payload": {"task_id": "abc-123"}, "attempts": 0}
        mock_claim.return_value = [row]

        result = drain_outbox_batch(session_factory, rmq_client)
        assert result == 1
        rmq_client.publish.assert_called_once_with("abc-123")
        mock_mark_sent.assert_called_once()
        session_factory._mock_session.commit.assert_called()

    @patch("app.main.mark_attempt_failed")
    @patch("app.main.claim_pending_rows")
    def test_drain_publish_fails(self, mock_claim, mock_mark_failed, session_factory, rmq_client):
        from app.main import drain_outbox_batch
        row = {"id": 1, "aggregate_id": str(uuid.uuid4()), "payload": {"task_id": "abc"}, "attempts": 2}
        mock_claim.return_value = [row]
        rmq_client.publish.side_effect = ConnectionError("rabbitmq down")

        result = drain_outbox_batch(session_factory, rmq_client)
        assert result == 0
        session_factory._mock_session.rollback.assert_called()
        mock_mark_failed.assert_called_once_with(
            session_factory._mock_session, 1, 2, "rabbitmq down"
        )

    @patch("app.main.mark_attempt_failed")
    @patch("app.main.mark_sent")
    @patch("app.main.claim_pending_rows")
    def test_drain_partial_failure(self, mock_claim, mock_mark_sent, mock_mark_failed, session_factory, rmq_client):
        from app.main import drain_outbox_batch
        row1 = {"id": 1, "aggregate_id": "agg1", "payload": {"task_id": "t1"}, "attempts": 0}
        row2 = {"id": 2, "aggregate_id": "agg2", "payload": {"task_id": "t2"}, "attempts": 0}
        mock_claim.return_value = [row1, row2]
        rmq_client.publish.side_effect = [None, ConnectionError("fail")]

        result = drain_outbox_batch(session_factory, rmq_client)
        assert result == 1
        mock_mark_sent.assert_called_once()
        mock_mark_failed.assert_called_once()

    @patch("app.main.claim_pending_rows")
    def test_drain_uses_payload_task_id(self, mock_claim, session_factory, rmq_client):
        """When payload has task_id, it's used instead of aggregate_id."""
        from app.main import drain_outbox_batch
        tid = str(uuid.uuid4())
        row = {"id": 1, "aggregate_id": "should-not-use", "payload": {"task_id": tid}, "attempts": 0}
        mock_claim.return_value = [row]
        with patch("app.main.mark_sent"):
            drain_outbox_batch(session_factory, rmq_client)
        rmq_client.publish.assert_called_once_with(tid)


class TestGetListenDsn:
    def test_strips_psycopg(self):
        from app.main import get_listen_dsn
        with patch("app.main.settings") as mock_settings:
            mock_settings.database_url = "postgresql+psycopg://user:pass@host:5432/db"
            result = get_listen_dsn()
        assert result == "postgresql://user:pass@host:5432/db"

    def test_no_psycopg(self):
        from app.main import get_listen_dsn
        with patch("app.main.settings") as mock_settings:
            mock_settings.database_url = "postgresql://user:pass@host:5432/db"
            result = get_listen_dsn()
        assert result == "postgresql://user:pass@host:5432/db"
