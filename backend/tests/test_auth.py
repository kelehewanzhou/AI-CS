"""Task 3 authentication, session, Origin, and account provisioning tests."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from auth.models import Session as SessionModel
from auth.models import User
from auth.service import UserContext, ph
from common.errors import AppException


ORIGIN = "http://localhost:3000"


def _create_user(db_session, username="test01", password="password123", **kwargs):
    user = User(
        username=username,
        password_hash=ph.hash(password),
        role=kwargs.pop("role", "student"),
        **kwargs,
    )
    db_session.add(user)
    db_session.commit()
    return user


def test_login_success_sets_hashed_session_cookie(client, db_session):
    user = _create_user(db_session)

    response = client.post(
        "/auth/login",
        json={"username": user.username, "password": "password123"},
        headers={"Origin": ORIGIN},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["user"]["username"] == "test01"
    assert body["data"]["user"]["must_change_password"] is True
    assert body["request_id"] == response.headers["x-request-id"]
    assert "expires_at" in body["data"]
    token = response.cookies.get("kglearn_session")
    assert token
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]
    stored = db_session.query(SessionModel).one()
    assert stored.token_hash == hashlib.sha256(token.encode()).hexdigest()


def test_wrong_or_unknown_login_has_one_unauthenticated_response(client, db_session):
    _create_user(db_session)
    headers = {"Origin": ORIGIN}

    wrong = client.post(
        "/auth/login",
        json={"username": "test01", "password": "wrong"},
        headers=headers,
    )
    unknown = client.post(
        "/auth/login",
        json={"username": "missing", "password": "wrong"},
        headers=headers,
    )

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["code"] == unknown.json()["code"] == "UNAUTHENTICATED"
    assert wrong.json()["message"] == unknown.json()["message"] == "账号或密码不正确"


def test_origin_is_required_and_exactly_allow_listed(client):
    payload = {"username": "test01", "password": "password123"}

    missing = client.post("/auth/login", json=payload)
    evil = client.post(
        "/auth/login", json=payload, headers={"Origin": "https://evil.com"}
    )

    assert missing.status_code == evil.status_code == 403
    assert missing.json()["code"] == evil.json()["code"] == "FORBIDDEN"


def test_me_validates_cookie_and_active_account(client, db_session):
    user = _create_user(db_session)
    login = client.post(
        "/auth/login",
        json={"username": user.username, "password": "password123"},
        headers={"Origin": ORIGIN},
    )
    assert client.get("/auth/me").status_code == 200
    assert client.get("/auth/me").json()["data"]["expires_at"].endswith("Z")

    user.is_active = False
    db_session.commit()
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"
    assert login.cookies.get("kglearn_session")


def test_expired_session_is_rejected(client, db_session):
    user = _create_user(db_session)
    token = "expired-token"
    db_session.add(
        SessionModel(
            user_id=user.user_id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )
    db_session.commit()
    client.cookies.set("kglearn_session", token)

    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_password_change_revokes_all_sessions_and_requires_reauth(client, db_session):
    user = _create_user(
        db_session,
        password="old-password",
        must_change_password=False,
    )
    for token_hash in ("a" * 64, "b" * 64):
        db_session.add(
            SessionModel(
                user_id=user.user_id,
                token_hash=token_hash,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=8),
            )
        )
    db_session.commit()

    login = client.post(
        "/auth/login",
        json={"username": user.username, "password": "old-password"},
        headers={"Origin": ORIGIN},
    )
    assert login.status_code == 200
    response = client.post(
        "/auth/password",
        json={
            "current_password": "old-password",
            "new_password": "NewPassword123!",
        },
        headers={"Origin": ORIGIN},
    )

    assert response.status_code == 200
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert response.json()["data"] == {
        "password_changed": True,
        "reauth_required": True,
    }
    assert db_session.query(SessionModel).count() == 3
    assert all(
        session.revoked_at is not None
        for session in db_session.query(SessionModel).all()
    )
    assert client.get("/auth/me").status_code == 401

    new_login = client.post(
        "/auth/login",
        json={"username": user.username, "password": "NewPassword123!"},
        headers={"Origin": ORIGIN},
    )
    assert new_login.status_code == 200
    assert new_login.json()["data"]["user"]["must_change_password"] is False


def test_logout_revokes_session_and_is_idempotent(client, db_session):
    user = _create_user(db_session)
    login = client.post(
        "/auth/login",
        json={"username": user.username, "password": "password123"},
        headers={"Origin": ORIGIN},
    )
    assert login.status_code == 200

    first = client.post("/auth/logout", json={}, headers={"Origin": ORIGIN})
    second = client.post("/auth/logout", json={}, headers={"Origin": ORIGIN})

    assert first.status_code == second.status_code == 200
    assert first.json()["data"] == {"logged_out": True}
    assert db_session.query(SessionModel).one().revoked_at is not None
    assert client.get("/auth/me").status_code == 401


def test_require_password_changed_blocks_initial_password(client):
    user = UserContext(
        user_id=uuid.uuid4(),
        username="test01",
        role="student",
        must_change_password=True,
    )

    try:
        from api.routers.auth import require_password_changed

        require_password_changed(user)
    except AppException as exc:
        assert exc.code == "FORBIDDEN"
        assert exc.status_code == 403
    else:
        raise AssertionError("initial-password users must be blocked")


def test_cli_creates_hashed_account_and_credentials_file(
    db_engine, tmp_path, monkeypatch
):
    from cli import accounts

    monkeypatch.setattr(accounts, "engine", db_engine)
    monkeypatch.chdir(tmp_path)

    assert accounts.create_account("student01", "student") == 0
    user = db_engine.connect().execute(
        User.__table__.select().where(User.username == "student01")
    ).mappings().one()
    credentials = next((tmp_path / "tmp").glob("credentials_*.txt"))
    _, role, password = credentials.read_text(encoding="utf-8").strip().split("\t")

    assert role == "student"
    assert user["must_change_password"] is True
    assert user["password_hash"] != password
    assert ph.verify(user["password_hash"], password)
