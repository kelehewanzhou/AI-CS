"""Protected exercise listing and answer submission endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from api.routers.auth import check_origin, require_password_changed
from common.database import get_db
from common.errors import AppException, get_request_id
from common.request_security import require_json_content_type
from exercise.schemas import AttemptRequest
from exercise.service import ExerciseService


router = APIRouter()


@router.get("/exercises")
def list_exercises(
    request: Request,
    node_id: str | None = Query(default=None, pattern=r"^[A-Z]{2}[0-9]{2,4}$"),
    question_id: str | None = Query(default=None, pattern=r"^Q[0-9]{3,8}$"),
    limit: int = Query(default=10, ge=1, le=20),
    offset: int = Query(default=0, ge=0),
    user=Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    del user
    items, total = ExerciseService(db).list_exercises(node_id, question_id, limit, offset)
    return {
        "data": {
            "items": [item.model_dump() for item in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        },
        "request_id": get_request_id(request),
    }


@router.post(
    "/exercises/attempts",
    dependencies=[Depends(check_origin), Depends(require_json_content_type)],
)
def submit_attempt(
    request: Request,
    req: AttemptRequest,
    response: Response,
    user=Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    view, created = ExerciseService(db).submit_attempt(
        user.user_id,
        req.question_id,
        req.answer,
        req.client_submission_id,
    )
    response.status_code = 201 if created else 200
    return {"data": view.model_dump(), "request_id": get_request_id(request)}


@router.get("/exercises/attempts")
def get_attempts(
    request: Request,
    question_id: str | None = Query(default=None, pattern=r"^Q[0-9]{3,8}$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user=Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    items, total = ExerciseService(db).get_attempts(user.user_id, question_id, limit, offset)
    return {
        "data": {
            "items": [item.model_dump() for item in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        },
        "request_id": get_request_id(request),
    }
