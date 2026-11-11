"""Protected learning event, state, and teacher summary endpoints."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from api.routers.auth import check_origin, require_password_changed
from common.database import get_db
from common.errors import AppException, get_request_id
from common.request_security import require_json_content_type

from learning.rules import LearningRules
from learning.schemas import EventCreateRequest
from learning.service import LearningService


router = APIRouter()


@router.post(
    "/learning/events",
    dependencies=[Depends(check_origin), Depends(require_json_content_type)],
)
def record_event(
    req: EventCreateRequest,
    request: Request,
    response: Response,
    user=Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    event = LearningService(db).record_event(
        user.user_id,
        req.event_type,
        req.resource_type,
        req.resource_id,
    )
    response.status_code = 201
    return {"data": event, "request_id": get_request_id(request)}


@router.get("/learning/events")
def get_events(
    request: Request,
    event_type: Literal["view_node", "view_edge", "start_exercise"] | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None, min_length=1),
    user=Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    items, next_cursor = LearningService(db).get_events(
        user.user_id, event_type, limit, cursor
    )
    return {
        "data": {
            "items": items,
            "next_cursor": next_cursor,
        },
        "request_id": get_request_id(request),
    }


@router.get("/learning/status")
def get_status(
    request: Request,
    node_id: list[str] | None = Query(default=None),
    user=Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    unique_node_ids = list(dict.fromkeys(node_id or []))
    if len(unique_node_ids) > 60:
        raise AppException("VALIDATION_ERROR", "node_id最多支持60个", 422)
    service = LearningService(db)
    items = service.get_states(user.user_id, unique_node_ids or None)
    return {
        "data": {
            "items": items,
            "rule_version": LearningRules.RULE_VERSION,
        },
        "request_id": get_request_id(request),
    }


@router.get("/learning/summary")
def get_summary(
    request: Request,
    user=Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    if user.role != "teacher":
        raise AppException("FORBIDDEN", "仅教师可以查看内容摘要", 403)
    summary = LearningService(db).get_content_summary()
    return {"data": summary, "request_id": get_request_id(request)}
