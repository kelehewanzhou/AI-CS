"""Authentication endpoints and FastAPI dependencies."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth.service import AuthService, UserContext
from common.config import SESSION_MAX_AGE, settings
from common.database import get_db
from common.errors import AppException, get_request_id
from common.request_security import check_origin, require_json_content_type


router = APIRouter()


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


def _utc_isoformat(value: datetime) -> str:
    value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def current_user(
    request: Request, db: Session = Depends(get_db)
) -> UserContext:
    """Read and validate the HttpOnly session cookie."""

    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise AppException("UNAUTHENTICATED", "未登录或会话已失效", 401)

    user, expires_at = AuthService(db).verify_token_with_expiry(token)
    request.state.session_expires_at = expires_at
    return user


# Keep the descriptive name used by the task specification available too.
get_current_user = current_user


def require_password_changed(
    user: UserContext = Depends(current_user),
) -> UserContext:
    """Require a user to finish the initial password change before business APIs."""

    if user.must_change_password:
        raise AppException("FORBIDDEN", "请先修改初始密码", 403)
    return user


@router.post("/login", dependencies=[Depends(check_origin), Depends(require_json_content_type)])
def login(
    req: LoginRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    user, token, expires_at = AuthService(db).login(req.username, req.password)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.environment.lower() != "development",
        path="/",
        max_age=SESSION_MAX_AGE,
    )
    return {
        "data": {
            "user": {
                "user_id": str(user.user_id),
                "username": user.username,
                "role": user.role,
                "must_change_password": user.must_change_password,
            },
            "expires_at": _utc_isoformat(expires_at),
        },
        "request_id": get_request_id(request),
    }


@router.get("/me")
def get_me(
    request: Request, user: UserContext = Depends(current_user)
) -> dict[str, object]:
    expires_at = getattr(request.state, "session_expires_at", None)
    return {
        "data": {
            "user": {
                "user_id": str(user.user_id),
                "username": user.username,
                "role": user.role,
                "must_change_password": user.must_change_password,
            },
            "expires_at": _utc_isoformat(expires_at) if expires_at else None,
        },
        "request_id": get_request_id(request),
    }


@router.post("/logout", dependencies=[Depends(check_origin), Depends(require_json_content_type)])
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        AuthService(db).logout(token)
    response.delete_cookie(key=settings.session_cookie_name, path="/")
    return {
        "data": {"logged_out": True},
        "request_id": get_request_id(request),
    }


@router.post("/password", dependencies=[Depends(check_origin), Depends(require_json_content_type)])
def change_password(
    req: PasswordChangeRequest,
    request: Request,
    response: Response,
    user: UserContext = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    AuthService(db).change_password(
        user.user_id, req.current_password, req.new_password
    )
    response.delete_cookie(key=settings.session_cookie_name, path="/")
    return {
        "data": {
            "password_changed": True,
            "reauth_required": True,
        },
        "request_id": get_request_id(request),
    }
