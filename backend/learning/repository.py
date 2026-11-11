"""Explicit learning-module queries and writes."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from exercise.models import Exercise, ExerciseAttempt, ExerciseRelatedNode
from graph.models import KnowledgeEdge

from .models import LearningEvent


class LearningRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_event(
        self,
        user_id: UUID,
        event_type: str,
        *,
        node_id: str | None = None,
        edge_id: str | None = None,
        question_id: str | None = None,
    ) -> LearningEvent:
        event = LearningEvent(
            user_id=user_id,
            event_type=event_type,
            node_id=node_id,
            edge_id=edge_id,
            question_id=question_id,
        )
        self.db.add(event)
        self.db.flush()
        self.db.refresh(event)
        return event

    def list_events(
        self,
        user_id: UUID,
        event_type: str | None,
        limit: int,
        after_created_at: datetime | None = None,
        after_event_id: int | None = None,
    ) -> list[LearningEvent]:
        filters = [LearningEvent.user_id == user_id]
        if event_type is not None:
            filters.append(LearningEvent.event_type == event_type)
        if after_created_at is not None and after_event_id is not None:
            if self.db.bind is not None and self.db.bind.dialect.name == "sqlite":
                # SQLite's DateTime adapter may serialize a zero-microsecond
                # value with different padding than CURRENT_TIMESTAMP. Compare
                # its canonical second precision text so equal timestamps use
                # event_id as the deterministic tie breaker.
                if after_created_at.microsecond == 0:
                    created_at_text = func.strftime("%Y-%m-%d %H:%M:%S", LearningEvent.created_at)
                    cursor_text = after_created_at.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    created_at_text = LearningEvent.created_at
                    cursor_text = after_created_at
                filters.append(
                    or_(
                        created_at_text < cursor_text,
                        and_(created_at_text == cursor_text, LearningEvent.event_id < after_event_id),
                    )
                )
            else:
                filters.append(
                    or_(
                        LearningEvent.created_at < after_created_at,
                        and_(
                            LearningEvent.created_at == after_created_at,
                            LearningEvent.event_id < after_event_id,
                        ),
                    )
                )
        return list(
            self.db.execute(
                select(LearningEvent)
                .where(*filters)
                .order_by(LearningEvent.created_at.desc(), LearningEvent.event_id.desc())
                .limit(limit)
            ).scalars()
        )

    def has_learning_activity(self, user_id: UUID, node_id: str) -> bool:
        view_node = select(LearningEvent.event_id).where(
            LearningEvent.user_id == user_id,
            LearningEvent.event_type == "view_node",
            LearningEvent.node_id == node_id,
        )
        start_exercise = (
            select(LearningEvent.event_id)
            .join(
                ExerciseRelatedNode,
                ExerciseRelatedNode.question_id == LearningEvent.question_id,
            )
            .where(
                LearningEvent.user_id == user_id,
                LearningEvent.event_type == "start_exercise",
                ExerciseRelatedNode.node_id == node_id,
            )
        )
        return bool(
            self.db.execute(
                select(or_(exists(view_node), exists(start_exercise)))
            ).scalar_one()
        )

    def count_available_exercises(self, node_id: str) -> int:
        return int(
            self.db.execute(
                select(func.count(func.distinct(Exercise.question_id)))
                .join(
                    ExerciseRelatedNode,
                    ExerciseRelatedNode.question_id == Exercise.question_id,
                )
                .where(
                    ExerciseRelatedNode.node_id == node_id,
                    Exercise.is_active.is_(True),
                )
            ).scalar_one()
        )

    def list_evaluations(self, user_id: UUID, node_id: str) -> list[tuple[bool, datetime, int]]:
        rows = self.db.execute(
            select(
                ExerciseAttempt.is_correct,
                ExerciseAttempt.submitted_at,
                ExerciseAttempt.attempt_id,
            )
            .join(
                ExerciseRelatedNode,
                ExerciseRelatedNode.question_id == ExerciseAttempt.question_id,
            )
            .where(
                ExerciseAttempt.user_id == user_id,
                ExerciseRelatedNode.node_id == node_id,
                ExerciseAttempt.is_evaluation.is_(True),
            )
            .order_by(
                ExerciseAttempt.submitted_at.desc(),
                ExerciseAttempt.attempt_id.desc(),
            )
        ).all()
        return [(bool(row.is_correct), row.submitted_at, int(row.attempt_id)) for row in rows]

    def count_attempts(self, user_id: UUID, node_id: str) -> int:
        return int(
            self.db.execute(
                select(func.count())
                .select_from(ExerciseAttempt)
                .join(
                    ExerciseRelatedNode,
                    ExerciseRelatedNode.question_id == ExerciseAttempt.question_id,
                )
                .where(
                    ExerciseAttempt.user_id == user_id,
                    ExerciseRelatedNode.node_id == node_id,
                )
            ).scalar_one()
        )

    def list_edge_evidence_counts(self) -> dict[str, int]:
        counts = {"verified": 0, "partial": 0, "pending": 0}
        rows = self.db.execute(
            select(KnowledgeEdge.evidence_status, func.count())
            .where(KnowledgeEdge.is_active.is_(True))
            .group_by(KnowledgeEdge.evidence_status)
        ).all()
        for evidence_status, count in rows:
            if evidence_status == "已核验":
                counts["verified"] = int(count)
            elif evidence_status == "部分定位":
                counts["partial"] = int(count)
            else:
                counts["pending"] += int(count)
        return counts
