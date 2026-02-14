from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_db_session():
    """Mock SQLAlchemy Session with common methods."""
    session = MagicMock()
    session.execute.return_value = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    session.flush = MagicMock()
    session.add = MagicMock()
    session.get = MagicMock(return_value=None)
    session.close = MagicMock()
    session.begin.return_value.__enter__ = MagicMock(return_value=session)
    session.begin.return_value.__exit__ = MagicMock(return_value=False)
    return session


@pytest.fixture
def mock_channel():
    """Mock pika BlockingChannel."""
    channel = MagicMock()
    channel.basic_ack = MagicMock()
    channel.basic_nack = MagicMock()
    channel.basic_publish = MagicMock()
    channel.is_closed = False
    return channel


@pytest.fixture
def mock_method():
    """Mock pika Basic.Deliver with a delivery_tag."""
    method = MagicMock()
    method.delivery_tag = 42
    return method
