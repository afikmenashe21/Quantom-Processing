from shared.logging import setup_logging as _setup_logging


def setup_logging() -> None:
    _setup_logging(service_name="worker")
