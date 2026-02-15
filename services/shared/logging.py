"""Shared logging setup used by all services."""

import logging
import re
import sys

_CONFIGURED = False

# Loggers whose internal chatter should be suppressed to WARNING
_NOISY_LOGGERS = ("pika", "alembic")


def _mask_url_password(url: str) -> str:
    """Replace password portion of amqp/postgresql URLs with '***'."""
    return re.sub(r"(://[^:]+:)[^@]+(@)", r"\1***\2", url)


def mask_credentials(msg: str) -> str:
    """Mask credentials in log messages containing connection URLs."""
    return re.sub(r"((?:amqp|postgresql\+?\w*)://[^:]+:)[^@\s]+(@)", r"\1***\2", msg)


class _CredentialMaskingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        result = super().format(record)
        return mask_credentials(result)


def setup_logging(
    service_name: str | None = None,
    suppress_uvicorn: bool = False,
) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    svc = f"[{service_name}] " if service_name else ""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        _CredentialMaskingFormatter(
            fmt=f"%(asctime)s {svc}level=%(levelname)s logger=%(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    if suppress_uvicorn:
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
