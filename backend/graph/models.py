"""SQLAlchemy models for the read-only knowledge graph."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from common.database import Base


# PostgreSQL uses text[]/jsonb. SQLite variants keep the same models usable by
# the isolated unit-test database.
TEXT_ARRAY = ARRAY(Text).with_variant(JSON(), "sqlite")
JSON_OBJECT = JSONB().with_variant(JSON(), "sqlite")


class ImportRun(Base):
    """Import metadata used to identify the graph seed in API responses."""

    __tablename__ = "import_runs"

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    source_files: Mapped[dict] = mapped_column(JSON_OBJECT, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    counts: Mapped[dict] = mapped_column(JSON_OBJECT, nullable=False)
    error_summary: Mapped[dict | None] = mapped_column(JSON_OBJECT, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Course(Base):
    """Course lookup table required by the node foreign key."""

    __tablename__ = "courses"

    course_code: Mapped[str] = mapped_column(String(2), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    textbook_info: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class KnowledgeNode(Base):
    __tablename__ = "knowledge_nodes"

    node_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    course_code: Mapped[str] = mapped_column(
        String(2), ForeignKey("courses.course_code", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    chapter_scope: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(TEXT_ARRAY, nullable=False, default=list)
    scope_tags: Mapped[list[str]] = mapped_column(TEXT_ARRAY, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class KnowledgeEdge(Base):
    __tablename__ = "knowledge_edges"

    edge_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        String(16), ForeignKey("knowledge_nodes.node_id", ondelete="RESTRICT"), nullable=False
    )
    target_id: Mapped[str] = mapped_column(
        String(16), ForeignKey("knowledge_nodes.node_id", ondelete="RESTRICT"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(Text, nullable=False)
    mechanism: Mapped[str] = mapped_column(String(1000), nullable=False)
    abc_grade: Mapped[str] = mapped_column(String(1), nullable=False)
    boundary_note: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    evidence_status: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_summary: Mapped[str] = mapped_column(String(1000), nullable=False)
    evidence_detail: Mapped[dict | None] = mapped_column(JSON_OBJECT, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
