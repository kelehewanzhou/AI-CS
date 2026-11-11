"""Authenticated template question answering, sharing the existing API envelope."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from api.routers.auth import check_origin, require_password_changed
from common.request_security import require_json_content_type
from common.database import get_db
from common.errors import get_request_id
from qa.schemas import AskRequest, AskResponse
from qa.service import QAService


router = APIRouter()


@router.post(
    "/ask", response_model=AskResponse,
    dependencies=[Depends(check_origin), Depends(require_json_content_type)],
)
def ask_question(
    req: AskRequest,
    request: Request,
    user=Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> dict:
    request_id = get_request_id(request)
    result = QAService(db).ask(user.user_id, req.question, request_id)
    return {"data": result, "request_id": request_id}
