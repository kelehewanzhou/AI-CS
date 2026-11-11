"""Exercise DTOs used by the service and HTTP adapter."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ExerciseStudent(BaseModel):
    """Public exercise view. The answer key is intentionally absent."""

    model_config = ConfigDict(extra="forbid")

    question_id: str
    type: str
    content: str
    options: list[dict[str, str]] | None
    difficulty: int
    related_node_ids: list[str]
    is_active: bool


class ExerciseInternal(ExerciseStudent):
    """Private service view used for judging only."""

    answer_key: Any


class AttemptView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: int
    client_submission_id: str
    question: ExerciseStudent
    answer: Any
    is_correct: bool
    is_evaluation: bool
    submitted_at: str
    feedback: str


class AttemptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(pattern=r"^Q[0-9]{3,8}$")
    answer: Any
    client_submission_id: UUID
