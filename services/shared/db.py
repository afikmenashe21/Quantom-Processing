"""Shared database session factory builder."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def build_session_factory(database_url: str, pool_size: int = 5) -> sessionmaker:
    engine = create_engine(database_url, pool_pre_ping=True, pool_size=pool_size)
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
