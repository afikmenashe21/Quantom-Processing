import logging
from contextlib import asynccontextmanager

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    logger.info("api_started")
    yield


app = FastAPI(title="Quantom Processing API", lifespan=lifespan)
app.include_router(router)
