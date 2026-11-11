"""Create the complete task 1 storage schema."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.CheckConstraint("role IN ('student', 'teacher')", name="users_role_check"),
        sa.CheckConstraint(
            "username ~ '^[a-z0-9_]{3,64}$'",
            name="username_format",
        ),
    )

    op.create_table(
        "sessions",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("session_id"),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.user_id"], name="fk_sessions_user_id_users", ondelete="RESTRICT"
        ),
        sa.CheckConstraint("expires_at > created_at", name="expires_after_created"),
    )
    op.create_index("idx_sessions_token_hash", "sessions", ["token_hash"])
    op.create_index("idx_sessions_expires_at", "sessions", ["expires_at"])

    op.create_table(
        "courses",
        sa.Column("course_code", sa.String(length=2), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("textbook_info", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("course_code"),
        sa.CheckConstraint(
            "course_code IN ('DS', 'CO', 'OS', 'CN')",
            name="courses_course_code_check",
        ),
    )

    op.create_table(
        "knowledge_nodes",
        sa.Column("node_id", sa.String(length=16), nullable=False),
        sa.Column("course_code", sa.String(length=2), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("chapter_scope", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column(
            "aliases",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "scope_tags",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("node_id"),
        sa.ForeignKeyConstraint(
            ["course_code"], ["courses.course_code"], name="fk_nodes_course_code_courses", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "node_id ~ '^[A-Z]{2}[0-9]{2,4}$'",
            name="node_id_format",
        ),
    )
    op.create_index("idx_nodes_course_active", "knowledge_nodes", ["course_code", "is_active"])

    op.create_table(
        "knowledge_edges",
        sa.Column("edge_id", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.String(length=16), nullable=False),
        sa.Column("relation_type", sa.Text(), nullable=False),
        sa.Column("mechanism", sa.String(length=1000), nullable=False),
        sa.Column("abc_grade", sa.CHAR(length=1), nullable=False),
        sa.Column("boundary_note", sa.String(length=1000), server_default=sa.text("''"), nullable=False),
        sa.Column("evidence_status", sa.Text(), nullable=False),
        sa.Column("evidence_summary", sa.String(length=1000), nullable=False),
        sa.Column("evidence_detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("edge_id"),
        sa.ForeignKeyConstraint(
            ["source_id"], ["knowledge_nodes.node_id"], name="fk_edges_source_id_nodes", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["target_id"], ["knowledge_nodes.node_id"], name="fk_edges_target_id_nodes", ondelete="RESTRICT"
        ),
        sa.CheckConstraint("edge_id ~ '^E[0-9]{3,6}$'", name="knowledge_edges_edge_id_check"),
        sa.CheckConstraint(
            "relation_type IN ('prerequisite', 'implements', 'contrast', 'boundary')",
            name="knowledge_edges_relation_type_check",
        ),
        sa.CheckConstraint("abc_grade IN ('A', 'B', 'C')", name="knowledge_edges_abc_grade_check"),
        sa.CheckConstraint(
            "evidence_status IN ('已核验', '部分定位', '待补充')",
            name="knowledge_edges_evidence_status_check",
        ),
        sa.CheckConstraint("source_id != target_id", name="no_self_loop"),
    )
    op.create_index("idx_edges_source_active", "knowledge_edges", ["source_id", "is_active"])
    op.create_index("idx_edges_target_active", "knowledge_edges", ["target_id", "is_active"])

    op.create_table(
        "exercises",
        sa.Column("question_id", sa.String(length=32), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("content", sa.String(length=2000), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("answer_key", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("difficulty", sa.SmallInteger(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("question_id"),
        sa.CheckConstraint("question_id ~ '^Q[0-9]{3,8}$'", name="question_id_format"),
        sa.CheckConstraint("type IN ('choice', 'judge')", name="exercises_type_check"),
        sa.CheckConstraint("difficulty BETWEEN 1 AND 5", name="exercises_difficulty_check"),
    )

    op.create_table(
        "exercise_related_nodes",
        sa.Column("question_id", sa.String(length=32), nullable=False),
        sa.Column("node_id", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("question_id", "node_id"),
        sa.ForeignKeyConstraint(
            ["question_id"], ["exercises.question_id"], name="fk_related_question_id_exercises", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["node_id"], ["knowledge_nodes.node_id"], name="fk_related_node_id_nodes", ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "idx_related_nodes_node",
        "exercise_related_nodes",
        ["node_id", "question_id"],
    )

    op.create_table(
        "exercise_attempts",
        sa.Column("attempt_id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_id", sa.String(length=32), nullable=False),
        sa.Column("client_submission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("answer", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("is_evaluation", sa.Boolean(), nullable=False),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.UniqueConstraint(
            "user_id", "client_submission_id", name="unique_client_submission"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.user_id"], name="fk_attempts_user_id_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["question_id"], ["exercises.question_id"], name="fk_attempts_question_id_exercises", ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "idx_attempts_evaluation",
        "exercise_attempts",
        ["user_id", "question_id"],
        unique=True,
        postgresql_where=sa.text("is_evaluation = true"),
    )
    op.create_index(
        "idx_attempts_user_time",
        "exercise_attempts",
        [sa.text("user_id"), sa.text("submitted_at DESC"), sa.text("attempt_id DESC")],
    )

    op.create_table(
        "learning_events",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("node_id", sa.String(length=16), nullable=True),
        sa.Column("edge_id", sa.String(length=16), nullable=True),
        sa.Column("question_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("event_id"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.user_id"], name="fk_events_user_id_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["node_id"], ["knowledge_nodes.node_id"], name="fk_events_node_id_nodes", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["edge_id"], ["knowledge_edges.edge_id"], name="fk_events_edge_id_edges", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["question_id"], ["exercises.question_id"], name="fk_events_question_id_exercises", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "event_type IN ('view_node', 'view_edge', 'start_exercise')",
            name="learning_events_event_type_check",
        ),
        sa.CheckConstraint(
            "(event_type = 'view_node' AND node_id IS NOT NULL AND edge_id IS NULL AND question_id IS NULL) OR "
            "(event_type = 'view_edge' AND edge_id IS NOT NULL AND node_id IS NULL AND question_id IS NULL) OR "
            "(event_type = 'start_exercise' AND question_id IS NOT NULL AND node_id IS NULL AND edge_id IS NULL)",
            name="event_resource_check",
        ),
    )
    op.create_index(
        "idx_events_user_node",
        "learning_events",
        ["user_id", "node_id", "event_type"],
    )
    op.create_index(
        "idx_events_user_time",
        "learning_events",
        [sa.text("user_id"), sa.text("created_at DESC"), sa.text("event_id DESC")],
    )

    op.create_table(
        "import_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("checksum", sa.CHAR(length=64), nullable=False),
        sa.Column("source_files", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("counts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("run_id"),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'skipped', 'failed')",
            name="import_runs_status_check",
        ),
    )

    op.create_table(
        "qa_records",
        sa.Column("record_id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("question_text", sa.String(length=500), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("used_node_ids", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("used_edge_ids", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("uncertainty_flag", sa.Boolean(), nullable=False),
        sa.Column("boundary_note", sa.Text(), nullable=False),
        sa.Column("actor_key", sa.CHAR(length=64), nullable=False),
        sa.Column("request_id", sa.CHAR(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("record_id"),
        sa.CheckConstraint(
            "status IN ('answered', 'not_covered', 'insufficient_evidence')",
            name="qa_records_status_check",
        ),
    )
    op.create_index("idx_qa_created_at", "qa_records", ["created_at"])
    op.create_index("idx_qa_status_time", "qa_records", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_qa_status_time", table_name="qa_records")
    op.drop_index("idx_qa_created_at", table_name="qa_records")
    op.drop_table("qa_records")

    op.drop_table("import_runs")

    op.drop_index("idx_events_user_time", table_name="learning_events")
    op.drop_index("idx_events_user_node", table_name="learning_events")
    op.drop_table("learning_events")

    op.drop_index("idx_attempts_user_time", table_name="exercise_attempts")
    op.drop_index("idx_attempts_evaluation", table_name="exercise_attempts")
    op.drop_table("exercise_attempts")

    op.drop_index("idx_related_nodes_node", table_name="exercise_related_nodes")
    op.drop_table("exercise_related_nodes")
    op.drop_table("exercises")

    op.drop_index("idx_edges_target_active", table_name="knowledge_edges")
    op.drop_index("idx_edges_source_active", table_name="knowledge_edges")
    op.drop_table("knowledge_edges")

    op.drop_index("idx_nodes_course_active", table_name="knowledge_nodes")
    op.drop_table("knowledge_nodes")
    op.drop_table("courses")

    op.drop_index("idx_sessions_expires_at", table_name="sessions")
    op.drop_index("idx_sessions_token_hash", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("users")
