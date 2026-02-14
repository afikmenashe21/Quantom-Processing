import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

# Ensure app.main is imported so patch targets resolve
import app.main  # noqa: F401
from app.main import handle_message


@pytest.fixture
def session_factory():
    mock_session = MagicMock()
    factory = MagicMock()
    factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    factory.return_value.__exit__ = MagicMock(return_value=False)
    factory._mock_session = mock_session
    return factory


class TestHandleMessage:
    @patch("app.main.mark_failed")
    @patch("app.main.mark_completed")
    @patch("app.main.execute_qasm3")
    @patch("app.main.try_claim_task")
    def test_invalid_json_nacks(self, mock_claim, mock_exec, mock_complete, mock_fail,
                                 session_factory, mock_channel, mock_method):
        handle_message(session_factory, mock_channel, mock_method, b"not-json{{{")
        mock_channel.basic_nack.assert_called_once_with(delivery_tag=42, requeue=False)
        mock_claim.assert_not_called()

    @patch("app.main.mark_failed")
    @patch("app.main.mark_completed")
    @patch("app.main.execute_qasm3")
    @patch("app.main.try_claim_task")
    def test_missing_task_id_nacks(self, mock_claim, mock_exec, mock_complete, mock_fail,
                                    session_factory, mock_channel, mock_method):
        handle_message(session_factory, mock_channel, mock_method, json.dumps({"foo": "bar"}).encode())
        mock_channel.basic_nack.assert_called_once_with(delivery_tag=42, requeue=False)

    @patch("app.main.mark_failed")
    @patch("app.main.mark_completed")
    @patch("app.main.execute_qasm3")
    @patch("app.main.try_claim_task")
    def test_invalid_uuid_nacks(self, mock_claim, mock_exec, mock_complete, mock_fail,
                                 session_factory, mock_channel, mock_method):
        handle_message(session_factory, mock_channel, mock_method, json.dumps({"task_id": "not-a-uuid"}).encode())
        mock_channel.basic_nack.assert_called_once_with(delivery_tag=42, requeue=False)

    @patch("app.main.mark_failed")
    @patch("app.main.mark_completed")
    @patch("app.main.execute_qasm3")
    @patch("app.main.try_claim_task")
    def test_not_claimable_acks(self, mock_claim, mock_exec, mock_complete, mock_fail,
                                 session_factory, mock_channel, mock_method):
        mock_claim.return_value = None
        tid = str(uuid.uuid4())
        handle_message(session_factory, mock_channel, mock_method, json.dumps({"task_id": tid}).encode())
        mock_channel.basic_ack.assert_called_once_with(delivery_tag=42)
        mock_exec.assert_not_called()

    @patch("app.main.mark_failed")
    @patch("app.main.mark_completed")
    @patch("app.main.execute_qasm3")
    @patch("app.main.try_claim_task")
    def test_execution_success_acks(self, mock_claim, mock_exec, mock_complete, mock_fail,
                                     session_factory, mock_channel, mock_method):
        tid = str(uuid.uuid4())
        mock_claim.return_value = {"id": tid, "qc": "OPENQASM 3;"}
        mock_exec.return_value = {"0": 512, "1": 512}

        handle_message(session_factory, mock_channel, mock_method, json.dumps({"task_id": tid}).encode())
        mock_complete.assert_called_once()
        mock_channel.basic_ack.assert_called_once_with(delivery_tag=42)
        mock_fail.assert_not_called()

    @patch("app.main.mark_failed")
    @patch("app.main.mark_completed")
    @patch("app.main.execute_qasm3")
    @patch("app.main.try_claim_task")
    def test_execution_failure_nacks(self, mock_claim, mock_exec, mock_complete, mock_fail,
                                      session_factory, mock_channel, mock_method):
        tid = str(uuid.uuid4())
        mock_claim.return_value = {"id": tid, "qc": "bad circuit"}
        mock_exec.side_effect = RuntimeError("simulation exploded")

        handle_message(session_factory, mock_channel, mock_method, json.dumps({"task_id": tid}).encode())
        mock_fail.assert_called_once()
        mock_channel.basic_nack.assert_called_once_with(delivery_tag=42, requeue=False)
        mock_complete.assert_not_called()
