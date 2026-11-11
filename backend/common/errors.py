"""Stable HTTP error responses and request ID handling."""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import uuid4

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException


logger = logging.getLogger(__name__)
REQUEST_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")

ERROR_STATUS_CODES = {
    "VALIDATION_ERROR": 422,
    "UNAUTHENTICATED": 401,
    "FORBIDDEN": 403,
    "NOT_FOUND": 404,
    "CONFLICT": 409,
    "RATE_LIMITED": 429,
    "INTERNAL_ERROR": 500,
    "UNAVAILABLE": 503,
}


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str
    details: dict[str, Any] | None = None


class AppException(Exception):
    """Application exception with one of the eight public error codes."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        if code not in ERROR_STATUS_CODES:
            raise ValueError(f"unsupported application error code: {code}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def _new_request_id() -> str:
    return uuid4().hex


def get_request_id(request: Request) -> str:
    """Return the request's 32-character lower-case hexadecimal ID.

    A trusted reverse proxy may provide ``X-Request-ID``. Invalid or missing
    values are replaced so direct requests still satisfy the public contract.
    """

    existing = getattr(request.state, "request_id", None)
    if existing:
        return existing

    supplied = request.headers.get("x-request-id", "").strip().lower()
    request_id = supplied if REQUEST_ID_PATTERN.fullmatch(supplied) else _new_request_id()
    request.state.request_id = request_id
    return request_id


def _error_response(
    request: Request,
    *,
    code: str,
    message: str,
    status_code: int,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        code=code,
        message=message,
        request_id=get_request_id(request),
        details=details,
    ).model_dump(exclude_none=True)
    return JSONResponse(status_code=status_code, content=body, headers={"X-Request-ID": body["request_id"]})


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    return _error_response(
        request,
        code=exc.code,
        message=exc.message,
        status_code=exc.status_code,
        details=exc.details,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    details = jsonable_encoder({"errors": exc.errors()})
    return _error_response(
        request,
        code="VALIDATION_ERROR",
        message="请求参数验证失败",
        status_code=422,
        details=details,
    )


def _http_error_mapping(status_code: int) -> tuple[str, int, str]:
    mapping = {
        401: ("UNAUTHENTICATED", 401, "未登录或会话无效"),
        403: ("FORBIDDEN", 403, "无权执行此操作"),
        404: ("NOT_FOUND", 404, "请求资源不存在"),
        409: ("CONFLICT", 409, "请求与当前状态冲突"),
        405: ("VALIDATION_ERROR", 422, "请求方法不允许"),
        422: ("VALIDATION_ERROR", 422, "请求参数验证失败"),
        429: ("RATE_LIMITED", 429, "请求过于频繁"),
        503: ("UNAVAILABLE", 503, "服务暂不可用"),
    }
    return mapping.get(status_code, ("INTERNAL_ERROR", 500, "服务器内部错误"))


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    code, response_status, default_message = _http_error_mapping(exc.status_code)
    message = exc.detail if isinstance(exc.detail, str) else default_message
    details = exc.detail if isinstance(exc.detail, dict) else None
    return _error_response(
        request,
        code=code,
        message=message,
        status_code=response_status,
        details=details,
    )


async def database_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Hide database connection details behind the public unavailable error."""

    logger.error("database error request_id=%s type=%s", get_request_id(request), type(exc).__name__)
    return _error_response(
        request,
        code="UNAVAILABLE",
        message="数据库不可用",
        status_code=503,
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled error request_id=%s type=%s", get_request_id(request), type(exc).__name__)
    return _error_response(
        request,
        code="INTERNAL_ERROR",
        message="服务器内部错误",
        status_code=500,
    )
