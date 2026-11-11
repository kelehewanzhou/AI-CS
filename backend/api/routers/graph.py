"""Protected graph query endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.routers.auth import require_password_changed
from common.database import get_db
from common.errors import AppException, get_request_id
from graph.schemas import SubgraphQuery
from graph.service import GraphService
from exercise.repository import ExerciseRepository
from learning.service import LearningService


router = APIRouter()


def _latest_seed_checksum(db: Session) -> str:
    result = db.execute(
        text(
            "SELECT checksum FROM import_runs "
            "WHERE status = 'succeeded' "
            "ORDER BY finished_at DESC NULLS LAST, started_at DESC LIMIT 1"
        )
    )
    return result.scalar() or ""


@router.get("/graph/subgraph")
def get_subgraph(
    request: Request,
    node_id: str | None = None,
    course_code: str | None = Query(default=None, pattern=r"^(DS|CO|OS|CN)$"),
    q: str | None = Query(default=None, min_length=1, max_length=100),
    hops: int = Query(default=1, ge=1, le=2),
    relation_type: Annotated[list[str], Query()] = [],
    evidence_status: Annotated[list[str], Query()] = [],
    user=Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    del user
    if (
        node_id is None
        and course_code is None
        and q is None
        and "hops" in request.query_params
    ):
        raise AppException("VALIDATION_ERROR", "overview模式不能显式传入hops", 422)

    try:
        query = SubgraphQuery(
            node_id=node_id,
            course_code=course_code,
            q=q,
            hops=hops,
            relation_type=relation_type,
            evidence_status=evidence_status,
        )
    except ValidationError as exc:
        raise AppException("VALIDATION_ERROR", "请求参数验证失败", 422) from exc
    result = GraphService(db).get_subgraph(query, _latest_seed_checksum(db))
    return {
        "data": result.model_dump(),
        "request_id": get_request_id(request),
    }


@router.get("/nodes/{node_id}")
def get_node(
    node_id: str,
    request: Request,
    user=Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    # The three reads share this request-scoped connection. PostgreSQL gets a
    # repeatable read snapshot so graph, exercise count, and learning state do
    # not observe different seed versions during a content switch.
    # Authentication has already read the session through this request-scoped
    # Session, so end that read transaction before opening the business
    # snapshot on PostgreSQL.
    if db.in_transaction():
        db.commit()
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
    node = GraphService(db).get_node(node_id)
    exercise_count = ExerciseRepository(db).count_by_node(node_id)
    learning = LearningService(db).get_states(user.user_id, [node_id])[0]
    return {
        "data": {
            "node": node.model_dump(),
            "exercise_count": exercise_count,
            "learning": learning,
        },
        "request_id": get_request_id(request),
    }


@router.get("/edges/{edge_id}")
def get_edge(
    edge_id: str,
    request: Request,
    user=Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    del user
    edge = GraphService(db).get_edge(edge_id)
    return {
        "data": edge.model_dump(),
        "request_id": get_request_id(request),
    }
