import logging

from alembic import command
from alembic.config import Config
from fastapi import FastAPI

from app.api.routes import router
from app.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


def run_migrations() -> None:
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    logger.info("migrations_applied")


app = FastAPI(title="Quantom Processing API")
app.include_router(router)


@app.on_event("startup")
def on_startup() -> None:
    run_migrations()
    logger.info("api_started")
