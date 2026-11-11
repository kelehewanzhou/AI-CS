"""DTOs for the learning HTTP and service contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


EVENT_TYPES = {
    "view_node": {"resource_field": "node_id", "resource_table": "knowledge_nodes"},
    "view_edge": {"resource_field": "edge_id", "resource_table": "knowledge_edges"},
    "start_exercise": {"resource_field": "question_id", "resource_table": "exercises"},
}
EVENT_RESOURCE_TYPES = ("node", "edge", "exercise")
EVENT_RESOURCE_PAIRS = {
    "view_node": "node",
    "view_edge": "edge",
    "start_exercise": "exercise",
}


class EventCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal["view_node", "view_edge", "start_exercise"]
    resource_type: Literal["node", "edge", "exercise"]
    resource_id: str = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_resource_pair(self) -> "EventCreateRequest":
        expected = EVENT_RESOURCE_PAIRS[self.event_type]
        if self.resource_type != expected:
            raise ValueError("event_type与resource_type不匹配")
        return self


class EventView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: int
    event_type: str
    resource_type: str
    resource_id: str
    created_at: str


class NodeLearningState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    state: str
    reason: str
    has_viewed: bool
    total_attempt_count: int
    evaluation_count: int
    recent_window_size: int
    recent_accuracy: float | None
    latest_evaluation_correct: bool | None
    available_exercise_count: int
    can_evaluate_mastery: bool
    rule_version: str = "p0-first-distinct-v1"


class ContentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_scope: str = "current_seed"
    seed_checksum: str
    last_import: dict[str, str]
    counts: dict[str, int]
    edge_evidence_counts: dict[str, int]
