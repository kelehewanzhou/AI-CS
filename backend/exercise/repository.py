"""Database access for the exercise module."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Exercise, ExerciseAttempt, ExerciseRelatedNode


class ExerciseRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(
        self, question_id: str, *, include_inactive: bool = False
    ) -> Exercise | None:
        statement = select(Exercise).where(Exercise.question_id == question_id)
        if not include_inactive:
            statement = statement.where(Exercise.is_active.is_(True))
        return self.db.execute(statement).scalar_one_or_none()

    def get_related_node_ids(self, question_id: str) -> list[str]:
        return list(
            self.db.execute(
                select(ExerciseRelatedNode.node_id)
                .where(ExerciseRelatedNode.question_id == question_id)
                .order_by(ExerciseRelatedNode.node_id)
            ).scalars()
        )

    def count_by_node(self, node_id: str) -> int:
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

    def list_active(
        self,
        node_id: str | None,
        question_id: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Exercise], int]:
        filters = [Exercise.is_active.is_(True)]
        if question_id is not None:
            filters.append(Exercise.question_id == question_id)

        count_statement = select(func.count()).select_from(Exercise).where(*filters)
        statement = select(Exercise).where(*filters)
        if node_id is not None:
            node_filter = ExerciseRelatedNode.node_id == node_id
            count_statement = count_statement.join(
                ExerciseRelatedNode,
                ExerciseRelatedNode.question_id == Exercise.question_id,
            ).where(node_filter)
            statement = statement.join(
                ExerciseRelatedNode,
                ExerciseRelatedNode.question_id == Exercise.question_id,
            ).where(node_filter)

        total = int(self.db.execute(count_statement).scalar_one())
        exercises = list(
            self.db.execute(
                statement.order_by(Exercise.question_id).limit(limit).offset(offset)
            ).scalars()
        )
        return exercises, total

    def get_by_submission_id(
        self, user_id: UUID, client_submission_id: UUID
    ) -> ExerciseAttempt | None:
        return self.db.execute(
            select(ExerciseAttempt).where(
                ExerciseAttempt.user_id == user_id,
                ExerciseAttempt.client_submission_id == client_submission_id,
            )
        ).scalar_one_or_none()

    def has_evaluation(self, user_id: UUID, question_id: str) -> bool:
        return (
            self.db.execute(
                select(ExerciseAttempt.attempt_id)
                .where(
                    ExerciseAttempt.user_id == user_id,
                    ExerciseAttempt.question_id == question_id,
                    ExerciseAttempt.is_evaluation.is_(True),
                )
                .limit(1)
            ).scalar_one_or_none()
            is not None
        )

    def list_attempts(
        self,
        user_id: UUID,
        question_id: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ExerciseAttempt], int]:
        filters = [ExerciseAttempt.user_id == user_id]
        if question_id is not None:
            filters.append(ExerciseAttempt.question_id == question_id)

        total = int(
            self.db.execute(
                select(func.count()).select_from(ExerciseAttempt).where(*filters)
            ).scalar_one()
        )
        attempts = list(
            self.db.execute(
                select(ExerciseAttempt)
                .where(*filters)
                .order_by(
                    ExerciseAttempt.submitted_at.desc(),
                    ExerciseAttempt.attempt_id.desc(),
                )
                .limit(limit)
                .offset(offset)
            ).scalars()
        )
        return attempts, total
