"""Request and response contracts for deterministic template answers."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: Annotated[
        str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=500)
    ]


class QAResponse(BaseModel):
    status: Literal["answered", "not_covered", "insufficient_evidence"]
    reason: Literal["no_match", "too_many_nodes", "ambiguous_relation", "no_direct_relation"] | None
    answer: str
    used_node_ids: list[str]
    used_edge_ids: list[str]
    uncertainty_flag: bool
    boundary_note: str


class AskResponse(BaseModel):
    data: QAResponse
    request_id: str
