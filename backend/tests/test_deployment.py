"""Release guards and failure behavior that do not require Docker."""
import asyncio
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request

from cli.release_seed import verify_package
from common.config import Settings
from common.errors import database_exception_handler, generic_exception_handler
from main import app

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("deployment_manage", ROOT / "scripts/manage.py")
manage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage)


def test_release_requires_actual_expert_approval(tmp_path):
    for source in (ROOT / "fixtures").glob("*.json"):
        (tmp_path / source.name).write_bytes(source.read_bytes())
    package = verify_package(tmp_path, production=False)
    with pytest.raises(OSError):
        verify_package(tmp_path, production=True)
    approval = {"status": "draft", "reviewer": "", "reviewed_at": "2026-11-10", "checksum": package.checksum}
    (tmp_path / "approval.json").write_text(json.dumps(approval))
    with pytest.raises(ValueError, match="教学专家"):
        verify_package(tmp_path, production=True)
    approval.update(status="approved", reviewer="test reviewer", reviewed_at="2020-01-01", checksum="0" * 64)
    (tmp_path / "approval.json").write_text(json.dumps(approval))
    with pytest.raises(ValueError, match="checksum"):
        verify_package(tmp_path, production=True)
    approval["checksum"] = package.checksum
    (tmp_path / "approval.json").write_text(json.dumps(approval))
    assert verify_package(tmp_path, production=True).checksum == package.checksum
    payload = json.loads((tmp_path / "nodes.json").read_text(encoding="utf-8"))
    payload["items"][0]["description"] += " changed"
    (tmp_path / "nodes.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        verify_package(tmp_path, production=True)


def test_production_rejects_short_keys_and_inexact_origins():
    values = dict(database_url="postgresql+psycopg://test:test@localhost/test", environment="production", _env_file=None)
    with pytest.raises(ValueError):
        Settings(**values, allowed_origins="https://example.edu.cn", session_secret_key="short")
    for origin in ("*", "http://example.edu.cn", "https://example.edu.cn/path"):
        with pytest.raises(ValueError):
            Settings(**values, allowed_origins=origin, session_secret_key="a" * 64)


@pytest.mark.parametrize("path", ["/auth/login", "/auth/password", "/auth/logout"])
def test_auth_post_uses_shared_json_guard(client, path):
    response = client.post(path, content="{}", headers={"Origin": "http://localhost:3000", "Content-Type": "text/plain"})
    assert response.status_code == 422 and response.json()["code"] == "VALIDATION_ERROR"


def test_unhandled_exception_is_not_reraised_to_server_or_logged_with_parameters(client, caplog):
    async def broken_route(request):
        raise RuntimeError("sensitive-parameter-from-request")

    from starlette.routing import Route
    route = Route("/temporary-error-contract", broken_route)
    app.router.routes.append(route)
    try:
        response = client.get("/temporary-error-contract")
        assert response.status_code == 500
        assert response.json()["code"] == "INTERNAL_ERROR"
        assert response.json()["request_id"] == response.headers["x-request-id"]
        assert "sensitive-parameter" not in caplog.text + response.text
        assert "Traceback" not in caplog.text
    finally:
        app.router.routes.remove(route)


@pytest.mark.parametrize("handler,error", [(database_exception_handler, SQLAlchemyError("password=secret-value")), (generic_exception_handler, RuntimeError("Cookie=secret-value"))])
def test_error_logs_do_not_disclose_exception_parameters(caplog, handler, error):
    request = Request({"type": "http", "headers": [], "method": "GET", "path": "/"})
    response = asyncio.run(handler(request, error))
    assert "secret-value" not in caplog.text
    assert "Traceback" not in caplog.text
    assert "request_id=" in caplog.text
    assert "secret-value" not in response.body.decode()
    assert response.headers["x-request-id"] == json.loads(response.body)["request_id"]


@pytest.mark.parametrize("failed_service", ["migrate", "seed-import", "backend", "nginx"])
def test_failed_deployment_keeps_maintenance_and_never_downgrades(tmp_path, monkeypatch, failed_service):
    monkeypatch.setattr(manage, "RUNTIME", tmp_path)
    ops = manage.Operations.__new__(manage.Operations)
    ops.version = "vtest"
    ops.tls = False
    ops.check = lambda: None
    ops.backup = lambda kind: "/backup/kglearn_release_test.dump"
    commands = []

    def compose(*args, **kwargs):
        commands.append(args)
        if args[0] == "up" and args[-1] == failed_service:
            raise subprocess.CalledProcessError(1, ["docker", "compose", *args])

    ops.compose = compose
    with pytest.raises(subprocess.CalledProcessError):
        ops.deploy()
    assert (tmp_path / "maintenance").exists()
    assert not (tmp_path / "deploy.lock").exists()
    assert not (tmp_path / "release.env").exists()
    assert commands[-1] == ("stop", "backend")
    assert not any("down" in command or "downgrade" in command for command in commands)
    if failed_service == "migrate":
        assert not any(command[-1] == "seed-import" for command in commands)


def test_successful_deployment_stops_writes_before_backup_and_reopens_last(tmp_path, monkeypatch):
    monkeypatch.setattr(manage, "RUNTIME", tmp_path)
    ops = manage.Operations.__new__(manage.Operations)
    ops.version, ops.tls = "vtest", False
    ops.check = lambda: None
    commands = []
    ops.compose = lambda *args, **kwargs: commands.append(args)

    def backup(kind):
        assert commands[-1] == ("stop", "backend")
        assert (tmp_path / "maintenance").exists()
        return "/backup/kglearn_release_test.dump"

    ops.backup = backup
    ops.deploy()
    assert not (tmp_path / "maintenance").exists()
    assert (tmp_path / "release.env").read_text() == "VERSION=vtest\n"
    assert json.loads((tmp_path / "deployment.json").read_text())["phase"] == "succeeded"
