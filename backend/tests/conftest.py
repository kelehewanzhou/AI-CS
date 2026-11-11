"""Test environment setup for tests that do not require a live PostgreSQL server."""

import os
import sys
from pathlib import Path


os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test_kglearn"
)
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:3000")
os.environ.setdefault("SESSION_SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "development")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from auth.models import Session as SessionModel  # noqa: F401
from auth.models import User  # noqa: F401
from exercise.models import Exercise, ExerciseAttempt, ExerciseRelatedNode  # noqa: F401
from graph.models import Course, KnowledgeEdge, KnowledgeNode  # noqa: F401
from learning.models import LearningEvent  # noqa: F401
from common.database import Base, get_db
from main import app


@pytest.fixture
def db_engine():
    """Create an isolated in-memory database for authentication contract tests."""

    test_engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(test_engine)
    try:
        yield test_engine
    finally:
        Base.metadata.drop_all(test_engine)
        test_engine.dispose()


@pytest.fixture
def db_session(db_engine):
    session_factory = sessionmaker(bind=db_engine, autoflush=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
