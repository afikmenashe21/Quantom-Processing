"""Shared logging setup used by all services."""

import logging
import sys


def setup_logging(suppress_uvicorn: bool = False) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s level=%(levelname)s logger=%(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    if suppress_uvicorn:
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
