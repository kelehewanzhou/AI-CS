"""Shared cookie POST guards for every module."""
from fastapi import Request

from common.config import settings
from common.errors import AppException


def check_origin(request: Request) -> None:
    if request.method == "POST":
        allowed = {item.strip() for item in settings.allowed_origins.split(",") if item.strip()}
        if request.headers.get("origin") not in allowed:
            raise AppException("FORBIDDEN", "不允许的Origin", 403)


def require_json_content_type(request: Request) -> None:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise AppException("VALIDATION_ERROR", "Content-Type必须为application/json", 422)
