import json
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


@pytest.fixture
def rmq():
    with patch("app.rabbitmq_client.settings") as mock_settings:
        mock_settings.rabbitmq_url = "amqp://user:pass@localhost:5672/"
        mock_settings.tasks_exchange = "tasks.exchange"
        mock_settings.tasks_queue = "tasks.queue"
        mock_settings.tasks_routing_key = "tasks.queued"
        from app.rabbitmq_client import RabbitMQClient
        client = RabbitMQClient()
        yield client, mock_settings


class TestConnect:
    @patch("app.rabbitmq_client.pika")
    def test_declares_topology(self, mock_pika, rmq):
        client, _ = rmq
        mock_conn = MagicMock()
        mock_ch = MagicMock()
        mock_pika.BlockingConnection.return_value = mock_conn
        mock_conn.channel.return_value = mock_ch

        client.connect()

        # Main exchange declared
        assert mock_ch.exchange_declare.call_count == 2  # tasks.exchange + tasks.dlx
        # Main queue + DLQ declared
        assert mock_ch.queue_declare.call_count == 2
        # Bindings
        assert mock_ch.queue_bind.call_count == 2


class TestPublish:
    @patch("app.rabbitmq_client.pika")
    def test_publish_healthy_channel(self, mock_pika, rmq):
        client, _ = rmq
        mock_conn = MagicMock()
        mock_ch = MagicMock()
        mock_ch.is_closed = False
        mock_pika.BlockingConnection.return_value = mock_conn
        mock_conn.channel.return_value = mock_ch

        client.connect()
        client.publish("task-123")

        mock_ch.basic_publish.assert_called_once()
        call_kwargs = mock_ch.basic_publish.call_args
        body = call_kwargs[1]["body"] if "body" in call_kwargs[1] else call_kwargs[0][2]
        assert json.loads(body) == {"task_id": "task-123"}

    @patch("app.rabbitmq_client.pika")
    def test_publish_reconnects_closed_channel(self, mock_pika, rmq):
        client, _ = rmq
        mock_conn = MagicMock()
        mock_conn.is_closed = False
        mock_ch = MagicMock()
        mock_ch.is_closed = True  # Channel closed
        mock_pika.BlockingConnection.return_value = mock_conn
        mock_conn.channel.return_value = mock_ch

        client._connection = mock_conn
        client._channel = mock_ch

        # On reconnect, new channel is open
        new_ch = MagicMock()
        new_ch.is_closed = False
        mock_conn.channel.return_value = new_ch
        mock_pika.BlockingConnection.return_value = mock_conn

        client.publish("task-456")

        # Should have reconnected and published
        new_ch.basic_publish.assert_called_once()

    @patch("app.rabbitmq_client.pika")
    def test_publish_reconnects_none_channel(self, mock_pika, rmq):
        client, _ = rmq
        mock_conn = MagicMock()
        mock_ch = MagicMock()
        mock_ch.is_closed = False
        mock_pika.BlockingConnection.return_value = mock_conn
        mock_conn.channel.return_value = mock_ch

        client._channel = None  # No channel

        client.publish("task-789")
        mock_ch.basic_publish.assert_called_once()


class TestCloseSilently:
    def test_handles_exception(self, rmq):
        client, _ = rmq
        mock_conn = MagicMock()
        mock_conn.is_closed = False
        mock_conn.close.side_effect = Exception("close failed")
        client._connection = mock_conn
        client._channel = MagicMock()

        # Should not raise
        client._close_silently()
        assert client._connection is None
        assert client._channel is None


class TestClose:
    def test_close_open_connection(self, rmq):
        client, _ = rmq
        mock_conn = MagicMock()
        mock_conn.is_closed = False
        client._connection = mock_conn

        client.close()
        mock_conn.close.assert_called_once()

    def test_close_already_closed(self, rmq):
        client, _ = rmq
        mock_conn = MagicMock()
        mock_conn.is_closed = True
        client._connection = mock_conn

        client.close()
        mock_conn.close.assert_not_called()
