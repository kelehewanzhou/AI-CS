"""SQLAlchemy models owned by the learning module."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from common.database import Base


# PostgreSQL uses an identity BIGINT. SQLite needs INTEGER for its implicit
# autoincrement behavior in the isolated test database.
EVENT_ID = BigInteger().with_variant(Integer, "sqlite")


class LearningEvent(Base):
    """An append-only event connecting a user to one current resource."""

    __tablename__ = "learning_events"

    event_id: Mapped[int] = mapped_column(EVENT_ID, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    node_id: Mapped[str | None] = mapped_column(
        String(16), ForeignKey("knowledge_nodes.node_id", ondelete="RESTRICT"), nullable=True
    )
    edge_id: Mapped[str | None] = mapped_column(
        String(16), ForeignKey("knowledge_edges.edge_id", ondelete="RESTRICT"), nullable=True
    )
    question_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("exercises.question_id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('view_node', 'view_edge', 'start_exercise')",
            name="learning_events_event_type_check",
        ),
        CheckConstraint(
            "(event_type = 'view_node' AND node_id IS NOT NULL AND edge_id IS NULL AND question_id IS NULL) OR "
            "(event_type = 'view_edge' AND edge_id IS NOT NULL AND node_id IS NULL AND question_id IS NULL) OR "
            "(event_type = 'start_exercise' AND question_id IS NOT NULL AND node_id IS NULL AND edge_id IS NULL)",
            name="event_resource_check",
        ),
        Index("idx_events_user_node", "user_id", "node_id", "event_type"),
        Index("idx_events_user_time", "user_id", "created_at", "event_id"),
    )
