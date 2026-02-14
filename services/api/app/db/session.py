import logging

from shared.db import build_session_factory

from app.config import settings

logger = logging.getLogger(__name__)

SessionLocal = build_session_factory(settings.database_url, pool_size=5)


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        logger.error("db_session_error", exc_info=True)
        raise
    finally:
        db.close()
