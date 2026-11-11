"""Pydantic DTOs exposed by the graph API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


RELATION_TYPES = ("prerequisite", "implements", "contrast", "boundary")
EVIDENCE_STATUSES = ("已核验", "部分定位", "待补充")


class SubgraphQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str | None = None
    course_code: str | None = Field(default=None, pattern=r"^(DS|CO|OS|CN)$")
    q: str | None = Field(default=None, min_length=1, max_length=100)
    hops: int = Field(default=1, ge=1, le=2)
    relation_type: list[str] = Field(default_factory=list)
    evidence_status: list[str] = Field(default_factory=list)

    @field_validator("relation_type")
    @classmethod
    def validate_relation_types(cls, values: list[str]) -> list[str]:
        return _validate_filter_values(values, RELATION_TYPES, "relation_type")

    @field_validator("evidence_status")
    @classmethod
    def validate_evidence_statuses(cls, values: list[str]) -> list[str]:
        return _validate_filter_values(values, EVIDENCE_STATUSES, "evidence_status")


def _validate_filter_values(
    values: list[str], allowed: tuple[str, ...], field_name: str
) -> list[str]:
    invalid = [value for value in values if value not in allowed]
    if invalid:
        raise ValueError(f"{field_name}包含不支持的值")
    return list(dict.fromkeys(values))


class GraphNode(BaseModel):
    node_id: str = Field(pattern=r"^[A-Z]{2}\d{2,4}$")
    title: str = Field(min_length=1, max_length=100)
    course_code: str = Field(pattern=r"^(DS|CO|OS|CN)$")
    evidence_status: Literal["已核验", "部分定位", "待补充"]


class EvidenceOverview(BaseModel):
    status: Literal["已核验", "部分定位", "待补充", "无证据"]
    reason: str
    counts: dict[str, int]
    edge_ids: list[str]


class EdgeView(BaseModel):
    edge_id: str = Field(pattern=r"^E\d{3,}$")
    source_id: str = Field(pattern=r"^[A-Z]{2}\d{2,4}$")
    source_title: str
    target_id: str = Field(pattern=r"^[A-Z]{2}\d{2,4}$")
    target_title: str
    relation_type: Literal["prerequisite", "implements", "contrast", "boundary"]
    display_mode: Literal["directed", "symmetric"]
    display_label: str
    mechanism: str = Field(min_length=1)
    abc_grade: str = Field(pattern=r"^[ABC]$")
    boundary_note: str
    evidence_status: Literal["已核验", "部分定位", "待补充"]
    evidence_summary: str
    evidence_detail: dict[str, Any] | None


class NodeContent(BaseModel):
    node_id: str = Field(pattern=r"^[A-Z]{2}\d{2,4}$")
    title: str
    course_code: str = Field(pattern=r"^(DS|CO|OS|CN)$")
    chapter_scope: str
    description: str
    aliases: list[str]
    scope_tags: list[str]
    evidence_overview: EvidenceOverview
    incoming_edges: list[EdgeView]
    outgoing_edges: list[EdgeView]


class SubgraphMeta(BaseModel):
    mode: str
    seed_node_ids: list[str]
    applied_hops: int
    filters: dict[str, Any]
    node_count: int
    edge_count: int
    limits: dict[str, int] = Field(default_factory=lambda: {"nodes": 60, "edges": 120})
    truncated: bool = False
    seed_checksum: str


class SubgraphResult(BaseModel):
    nodes: list[GraphNode]
    edges: list[EdgeView]
    meta: SubgraphMeta
