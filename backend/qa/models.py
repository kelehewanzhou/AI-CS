"""Anonymous answer snapshots, matching the existing task-one migration."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CHAR, CheckConstraint, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from common.database import Base
from graph.models import TEXT_ARRAY


class QARecord(Base):
    __tablename__ = "qa_records"

    record_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    question_text: Mapped[str] = mapped_column(String(500), nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    used_node_ids: Mapped[list[str]] = mapped_column(TEXT_ARRAY, nullable=False)
    used_edge_ids: Mapped[list[str]] = mapped_column(TEXT_ARRAY, nullable=False)
    uncertainty_flag: Mapped[bool] = mapped_column(Boolean, nullable=False)
    boundary_note: Mapped[str] = mapped_column(Text, nullable=False)
    actor_key: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    request_id: Mapped[str] = mapped_column(CHAR(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('answered', 'not_covered', 'insufficient_evidence')",
            name="qa_records_status_check",
        ),
        Index("idx_qa_created_at", "created_at"),
        Index("idx_qa_status_time", "status", "created_at"),
    )
