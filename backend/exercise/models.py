"""SQLAlchemy models for exercises and immutable answer attempts."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    Uuid,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from common.database import Base


JSON_OBJECT = JSONB().with_variant(JSON(), "sqlite")
ATTEMPT_ID = BigInteger().with_variant(Integer, "sqlite")


class Exercise(Base):
    """An imported, student-visible exercise with a private answer key."""

    __tablename__ = "exercises"

    question_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(String(2000), nullable=False)
    options: Mapped[list[dict[str, str]] | None] = mapped_column(JSON_OBJECT, nullable=True)
    answer_key: Mapped[object] = mapped_column(JSON_OBJECT, nullable=False)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExerciseRelatedNode(Base):
    """Immutable exercise-to-knowledge-node association."""

    __tablename__ = "exercise_related_nodes"

    question_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("exercises.question_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    node_id: Mapped[str] = mapped_column(
        String(16),
        ForeignKey("knowledge_nodes.node_id", ondelete="RESTRICT"),
        primary_key=True,
    )

    __table_args__ = (Index("idx_related_nodes_node", "node_id", "question_id"),)


class ExerciseAttempt(Base):
    """An append-only answer submission."""

    __tablename__ = "exercise_attempts"

    attempt_id: Mapped[int] = mapped_column(
        ATTEMPT_ID, primary_key=True, autoincrement=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    question_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("exercises.question_id", ondelete="RESTRICT"),
        nullable=False,
    )
    client_submission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    answer: Mapped[object] = mapped_column(JSON_OBJECT, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_evaluation: Mapped[bool] = mapped_column(Boolean, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "client_submission_id", name="unique_client_submission"
        ),
        Index(
            "idx_attempts_evaluation",
            "user_id",
            "question_id",
            unique=True,
            postgresql_where=text("is_evaluation = true"),
            sqlite_where=text("is_evaluation = 1"),
        ),
        Index(
            "idx_attempts_user_time",
            "user_id",
            text("submitted_at DESC"),
            text("attempt_id DESC"),
        ),
    )
