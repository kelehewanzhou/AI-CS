"""Contract tests for task 1's common facilities and health endpoints."""

import asyncio
import json
import re

import pytest
from fastapi.testclient import TestClient
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request

from common.database import get_db
from common.errors import validation_exception_handler
from main import app


class _Result:
    def __init__(self, value: bool) -> None:
        self.value = value

    def scalar(self) -> bool:
        return self.value


class _NoSeedSession:
    def execute(self, statement):
        sql = str(statement)
        if "SELECT version_num" in sql:
            return _Result("0001_initial_schema")
        if "alembic_version" in sql:
            return _Result(True)
        if "import_runs" in sql and "information_schema" in sql:
            return _Result(True)
        if "FROM import_runs" in sql:
            return _Result(False)
        if sql.strip() == "SELECT 1":
            return _Result(True)
        raise AssertionError(f"unexpected SQL in readiness test: {sql}")

    def close(self) -> None:
        pass


@pytest.fixture
def client():
    def override_get_db():
        yield _NoSeedSession()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health_live_returns_contract_and_request_id(client):
    response = client.get("/health/live")

    assert response.status_code == 200
    body = response.json()
    assert body["data"] == {"status": "ok"}
    assert re.fullmatch(r"[0-9a-f]{32}", body["request_id"])
    assert response.headers["x-request-id"] == body["request_id"]


def test_request_id_header_is_reused_when_valid(client):
    request_id = "a" * 32

    response = client.get("/health/live", headers={"X-Request-ID": request_id})

    assert response.json()["request_id"] == request_id
    assert response.headers["x-request-id"] == request_id


def test_health_ready_without_seed_returns_unavailable(client):
    response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "UNAVAILABLE"
    assert body["message"] == "未导入种子数据"
    assert re.fullmatch(r"[0-9a-f]{32}", body["request_id"])


def test_unknown_path_uses_unified_not_found_error(client):
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    assert set(response.json()) == {"code", "message", "request_id"}


def test_invalid_method_uses_unified_validation_error(client):
    response = client.post("/health/live", json={})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_validation_handler_uses_unified_error_shape():
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/test",
        "raw_path": b"/test",
        "query_string": b"",
        "headers": [],
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "root_path": "",
    }
    request = Request(scope)
    error = RequestValidationError(
        [{"type": "missing", "loc": ("body", "name"), "msg": "Field required", "input": None}]
    )

    response = asyncio.run(validation_exception_handler(request, error))
    body = json.loads(response.body)

    assert response.status_code == 422
    assert body["code"] == "VALIDATION_ERROR"
    assert body["details"]["errors"]
    assert re.fullmatch(r"[0-9a-f]{32}", body["request_id"])
