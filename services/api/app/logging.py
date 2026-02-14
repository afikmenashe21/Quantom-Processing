from shared.logging import setup_logging as _setup_logging


def setup_logging() -> None:
    _setup_logging(suppress_uvicorn=True)
