"""Synchronous SQLAlchemy engine and FastAPI database dependency."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    """Base class reserved for SQLAlchemy models added in later tasks."""


def get_db() -> Generator[Session, None, None]:
    """Yield one request-scoped synchronous database session."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
