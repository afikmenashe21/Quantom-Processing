import json
import uuid
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
from unittest.mock import MagicMock, patch

import pytest

import app.main  # noqa: F401
from app.main import drain_in_flight, handle_incoming_message, reap_completed_futures


@pytest.fixture
def session_factory():
    mock_session = MagicMock()
    factory = MagicMock()
    factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    factory.return_value.__exit__ = MagicMock(return_value=False)
    factory._mock_session = mock_session
    return factory


@pytest.fixture
def mock_pool():
    pool = MagicMock()
    return pool


@pytest.fixture
def in_flight():
    return {}


class TestHandleIncomingMessage:
    @patch("app.main.try_claim_task")
    def test_invalid_json_nacks(self, mock_claim, session_factory, mock_pool, in_flight,
                                mock_channel, mock_method):
        handle_incoming_message(session_factory, mock_pool, in_flight, mock_channel, mock_method, b"not-json{{{")
        mock_channel.basic_nack.assert_called_once_with(delivery_tag=42, requeue=False)
        mock_claim.assert_not_called()
        assert len(in_flight) == 0

    @patch("app.main.try_claim_task")
    def test_missing_task_id_nacks(self, mock_claim, session_factory, mock_pool, in_flight,
                                   mock_channel, mock_method):
        handle_incoming_message(session_factory, mock_pool, in_flight, mock_channel, mock_method,
                                json.dumps({"foo": "bar"}).encode())
        mock_channel.basic_nack.assert_called_once_with(delivery_tag=42, requeue=False)
        assert len(in_flight) == 0

    @patch("app.main.try_claim_task")
    def test_invalid_uuid_nacks(self, mock_claim, session_factory, mock_pool, in_flight,
                                mock_channel, mock_method):
        handle_incoming_message(session_factory, mock_pool, in_flight, mock_channel, mock_method,
                                json.dumps({"task_id": "not-a-uuid"}).encode())
        mock_channel.basic_nack.assert_called_once_with(delivery_tag=42, requeue=False)
        assert len(in_flight) == 0

    @patch("app.main.try_claim_task")
    def test_not_claimable_acks(self, mock_claim, session_factory, mock_pool, in_flight,
                                mock_channel, mock_method):
        mock_claim.return_value = None
        tid = str(uuid.uuid4())
        handle_incoming_message(session_factory, mock_pool, in_flight, mock_channel, mock_method,
                                json.dumps({"task_id": tid}).encode())
        mock_channel.basic_ack.assert_called_once_with(delivery_tag=42)
        mock_pool.submit.assert_not_called()
        assert len(in_flight) == 0

    @patch("app.main.settings")
    @patch("app.main.try_claim_task")
    def test_claimable_submits_to_pool(self, mock_claim, mock_settings,
                                       session_factory, mock_pool, in_flight,
                                       mock_channel, mock_method):
        tid = str(uuid.uuid4())
        mock_claim.return_value = {"id": tid, "qc": "OPENQASM 3;"}
        mock_settings.shots = 1024
        mock_future = MagicMock()
        mock_pool.submit.return_value = mock_future

        handle_incoming_message(session_factory, mock_pool, in_flight, mock_channel, mock_method,
                                json.dumps({"task_id": tid}).encode())

        mock_pool.submit.assert_called_once_with(
            app.main.execute_qasm3, tid, "OPENQASM 3;", 1024,
        )
        assert 42 in in_flight
        assert in_flight[42][0] is mock_future

    @patch("app.main.mark_failed")
    @patch("app.main.settings")
    @patch("app.main.try_claim_task")
    def test_pool_submit_failure_marks_task_failed(self, mock_claim, mock_settings, mock_mark_failed,
                                                    session_factory, mock_pool, in_flight,
                                                    mock_channel, mock_method):
        tid = str(uuid.uuid4())
        mock_claim.return_value = {"id": tid, "qc": "OPENQASM 3;"}
        mock_settings.shots = 1024
        mock_pool.submit.side_effect = BrokenProcessPool("pool is broken")

        with pytest.raises(BrokenProcessPool):
            handle_incoming_message(session_factory, mock_pool, in_flight, mock_channel, mock_method,
                                    json.dumps({"task_id": tid}).encode())

        mock_mark_failed.assert_called_once()
        mock_channel.basic_nack.assert_called_once_with(delivery_tag=42, requeue=False)
        assert len(in_flight) == 0


class TestReapCompletedFutures:
    @patch("app.main.mark_completed")
    def test_successful_future_acks(self, mock_mark_completed, session_factory, mock_channel):
        tid = uuid.uuid4()
        future = Future()
        future.set_result({"0": 512, "1": 512})
        in_flight = {42: (future, tid, 42)}

        reap_completed_futures(session_factory, mock_channel, in_flight)

        mock_mark_completed.assert_called_once()
        mock_channel.basic_ack.assert_called_once_with(delivery_tag=42)
        assert len(in_flight) == 0

    @patch("app.main.mark_failed")
    def test_failed_future_nacks(self, mock_mark_failed, session_factory, mock_channel):
        tid = uuid.uuid4()
        future = Future()
        future.set_exception(RuntimeError("simulation exploded"))
        in_flight = {42: (future, tid, 42)}

        reap_completed_futures(session_factory, mock_channel, in_flight)

        mock_mark_failed.assert_called_once()
        mock_channel.basic_nack.assert_called_once_with(delivery_tag=42, requeue=False)
        assert len(in_flight) == 0

    def test_pending_future_left_alone(self, session_factory, mock_channel):
        tid = uuid.uuid4()
        future = Future()  # not done
        in_flight = {42: (future, tid, 42)}

        reap_completed_futures(session_factory, mock_channel, in_flight)

        mock_channel.basic_ack.assert_not_called()
        mock_channel.basic_nack.assert_not_called()
        assert 42 in in_flight

    @patch("app.main.mark_completed")
    def test_multiple_futures_mixed_states(self, mock_mark_completed, session_factory, mock_channel):
        tid1 = uuid.uuid4()
        tid2 = uuid.uuid4()

        done_future = Future()
        done_future.set_result({"0": 1024})
        pending_future = Future()

        in_flight = {
            10: (done_future, tid1, 10),
            20: (pending_future, tid2, 20),
        }

        reap_completed_futures(session_factory, mock_channel, in_flight)

        mock_channel.basic_ack.assert_called_once_with(delivery_tag=10)
        assert 10 not in in_flight
        assert 20 in in_flight


class TestDrainInFlight:
    @patch("app.main.mark_completed")
    def test_drain_completes_done_futures(self, mock_mark_completed, session_factory, mock_channel):
        tid = uuid.uuid4()
        future = Future()
        future.set_result({"0": 1024})
        in_flight = {42: (future, tid, 42)}

        drain_in_flight(session_factory, mock_channel, in_flight, timeout=5.0)

        mock_mark_completed.assert_called_once()
        mock_channel.basic_ack.assert_called_once_with(delivery_tag=42)
        assert len(in_flight) == 0

    @patch("app.main.mark_completed")
    def test_drain_skips_ack_when_channel_is_none(self, mock_mark_completed, session_factory):
        tid = uuid.uuid4()
        future = Future()
        future.set_result({"0": 512})
        in_flight = {42: (future, tid, 42)}

        drain_in_flight(session_factory, None, in_flight, timeout=5.0)

        mock_mark_completed.assert_called_once()
        assert len(in_flight) == 0

    @patch("app.main.mark_completed")
    def test_drain_skips_ack_when_channel_closed(self, mock_mark_completed, session_factory, mock_channel):
        mock_channel.is_open = False
        tid = uuid.uuid4()
        future = Future()
        future.set_result({"0": 512})
        in_flight = {42: (future, tid, 42)}

        drain_in_flight(session_factory, mock_channel, in_flight, timeout=5.0)

        mock_mark_completed.assert_called_once()
        mock_channel.basic_ack.assert_not_called()
        assert len(in_flight) == 0

    @patch("app.main.mark_failed")
    def test_drain_handles_failed_future(self, mock_mark_failed, session_factory, mock_channel):
        tid = uuid.uuid4()
        future = Future()
        future.set_exception(RuntimeError("crash"))
        in_flight = {42: (future, tid, 42)}

        drain_in_flight(session_factory, mock_channel, in_flight, timeout=5.0)

        mock_mark_failed.assert_called_once()
        mock_channel.basic_nack.assert_called_once_with(delivery_tag=42, requeue=False)
        assert len(in_flight) == 0

    def test_drain_empty_is_noop(self, session_factory, mock_channel):
        in_flight = {}
        drain_in_flight(session_factory, mock_channel, in_flight, timeout=5.0)
        mock_channel.basic_ack.assert_not_called()
