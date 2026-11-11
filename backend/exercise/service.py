"""Exercise listing, judging, idempotency, and attempt history."""

from __future__ import annotations

import hashlib
import threading
from contextlib import contextmanager
from datetime import timezone
from typing import Any, Iterator
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from common.errors import AppException

from .models import Exercise, ExerciseAttempt
from .repository import ExerciseRepository
from .schemas import AttemptView, ExerciseStudent


_LOCAL_LOCKS: dict[int, threading.RLock] = {}
_LOCAL_LOCKS_GUARD = threading.Lock()


class ExerciseService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = ExerciseRepository(db)

    def list_exercises(
        self,
        node_id: str | None = None,
        question_id: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[list[ExerciseStudent], int]:
        if node_id is not None and not self._node_exists(node_id):
            raise AppException("NOT_FOUND", f"节点{node_id}不存在", 404)
        if question_id is not None and not self.repo.get_by_id(question_id):
            raise AppException("NOT_FOUND", f"题目{question_id}不存在", 404)

        exercises, total = self.repo.list_active(node_id, question_id, limit, offset)
        return [self._student_view(exercise) for exercise in exercises], total

    def submit_attempt(
        self,
        user_id: UUID,
        question_id: str,
        answer: Any,
        client_submission_id: UUID,
    ) -> tuple[AttemptView, bool]:
        # An existing idempotency key wins even when the question was later retired.
        existing = self.repo.get_by_submission_id(user_id, client_submission_id)
        if existing is not None:
            if existing.question_id != question_id:
                raise AppException("CONFLICT", "相同提交ID配了不同题目或答案", 409)
            exercise = self.repo.get_by_id(existing.question_id, include_inactive=True)
            if (
                exercise is not None
                and self._answers_equal(
                    existing.answer, self._normalize_answer(exercise.type, answer)
                )
            ):
                return self._build_attempt_view(existing, exercise), False
            raise AppException("CONFLICT", "相同提交ID配了不同题目或答案", 409)

        exercise = self.repo.get_by_id(question_id)
        if exercise is None:
            raise AppException("NOT_FOUND", f"题目{question_id}不存在", 404)
        normalized_answer = self._normalize_answer(exercise.type, answer)
        is_correct = self._judge(exercise, normalized_answer)

        lock_key = self._compute_lock_key(user_id, question_id)
        with self._submission_lock(lock_key):
            # The first check can race with another request using the same UUID.
            existing = self.repo.get_by_submission_id(user_id, client_submission_id)
            if existing is not None:
                if existing.question_id != question_id:
                    raise AppException("CONFLICT", "相同提交ID配了不同题目或答案", 409)
                existing_exercise = self.repo.get_by_id(
                    existing.question_id, include_inactive=True
                )
                if (
                    existing_exercise is not None
                    and self._answers_equal(existing.answer, normalized_answer)
                ):
                    return self._build_attempt_view(existing, existing_exercise), False
                raise AppException("CONFLICT", "相同提交ID配了不同题目或答案", 409)

            attempt = ExerciseAttempt(
                user_id=user_id,
                question_id=question_id,
                client_submission_id=client_submission_id,
                answer=normalized_answer,
                is_correct=is_correct,
                is_evaluation=not self.repo.has_evaluation(user_id, question_id),
            )
            self.db.add(attempt)
            try:
                self.db.commit()
            except IntegrityError as exc:
                # A different question can use the same client UUID, so the
                # UUID unique constraint remains the final cross-key guard.
                self.db.rollback()
                existing = self.repo.get_by_submission_id(user_id, client_submission_id)
                if existing is not None:
                    if existing.question_id != question_id:
                        raise AppException(
                            "CONFLICT", "相同提交ID配了不同题目或答案", 409
                        ) from exc
                    existing_exercise = self.repo.get_by_id(
                        existing.question_id, include_inactive=True
                    )
                    if (
                        existing_exercise is not None
                        and self._answers_equal(existing.answer, normalized_answer)
                    ):
                        return self._build_attempt_view(existing, existing_exercise), False
                    raise AppException(
                        "CONFLICT", "相同提交ID配了不同题目或答案", 409
                    ) from exc
                raise
            self.db.refresh(attempt)
            return self._build_attempt_view(attempt, exercise), True

    def get_attempts(
        self,
        user_id: UUID,
        question_id: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[AttemptView], int]:
        if question_id is not None and not self.repo.get_by_id(
            question_id, include_inactive=True
        ):
            raise AppException("NOT_FOUND", f"题目{question_id}不存在", 404)

        attempts, total = self.repo.list_attempts(user_id, question_id, limit, offset)
        views: list[AttemptView] = []
        for attempt in attempts:
            exercise = self.repo.get_by_id(attempt.question_id, include_inactive=True)
            if exercise is not None:
                views.append(self._build_attempt_view(attempt, exercise))
        return views, total

    def _node_exists(self, node_id: str) -> bool:
        from graph.models import KnowledgeNode
        from sqlalchemy import select

        return (
            self.db.execute(
                select(KnowledgeNode.node_id).where(
                    KnowledgeNode.node_id == node_id,
                    KnowledgeNode.is_active.is_(True),
                )
            ).scalar_one_or_none()
            is not None
        )

    @staticmethod
    def _normalize_answer(q_type: str, answer: Any) -> Any:
        if q_type == "choice":
            if not isinstance(answer, str):
                raise AppException("VALIDATION_ERROR", "choice答案必须为字符串", 422)
            return answer.strip().upper()
        if q_type == "judge":
            if type(answer) is not bool:
                raise AppException("VALIDATION_ERROR", "judge答案必须为boolean", 422)
            return answer
        raise AppException("VALIDATION_ERROR", f"不支持的题型{q_type}", 422)

    @staticmethod
    def _judge(exercise: Exercise, answer: Any) -> bool:
        return answer == exercise.answer_key

    @staticmethod
    def _answers_equal(left: Any, right: Any) -> bool:
        return type(left) is type(right) and left == right

    @staticmethod
    def _compute_lock_key(user_id: UUID, question_id: str) -> int:
        digest = hashlib.sha256(f"{user_id}:{question_id}".encode()).digest()
        return int.from_bytes(digest[:8], "big", signed=True)

    @contextmanager
    def _submission_lock(self, lock_key: int) -> Iterator[None]:
        if self.db.bind is not None and self.db.bind.dialect.name == "postgresql":
            self.db.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": lock_key},
            )
            yield
            return

        with _LOCAL_LOCKS_GUARD:
            lock = _LOCAL_LOCKS.setdefault(lock_key, threading.RLock())
        with lock:
            yield

    def _student_view(self, exercise: Exercise) -> ExerciseStudent:
        return ExerciseStudent(
            question_id=exercise.question_id,
            type=exercise.type,
            content=exercise.content,
            options=exercise.options,
            difficulty=exercise.difficulty,
            related_node_ids=self.repo.get_related_node_ids(exercise.question_id),
            is_active=exercise.is_active,
        )

    def _build_attempt_view(
        self, attempt: ExerciseAttempt, exercise: Exercise
    ) -> AttemptView:
        submitted_at = attempt.submitted_at
        if submitted_at.tzinfo is None:
            submitted_at = submitted_at.replace(tzinfo=timezone.utc)
        submitted_at = submitted_at.astimezone(timezone.utc)
        return AttemptView(
            attempt_id=attempt.attempt_id,
            client_submission_id=str(attempt.client_submission_id),
            question=self._student_view(exercise),
            answer=attempt.answer,
            is_correct=attempt.is_correct,
            is_evaluation=attempt.is_evaluation,
            submitted_at=submitted_at.isoformat().replace("+00:00", "Z"),
            feedback=(
                "本次回答正确"
                if attempt.is_correct
                else "本次回答有误，请复习关联知识节点"
            ),
        )
