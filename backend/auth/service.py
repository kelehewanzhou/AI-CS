"""Authentication and session lifecycle service."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from sqlalchemy.orm import Session as DatabaseSession

from common.config import SESSION_MAX_AGE
from common.errors import AppException

from .models import Session as SessionModel
from .repository import SessionRepository, UserRepository


ph = PasswordHasher()


@dataclass(frozen=True)
class UserContext:
    user_id: UUID
    username: str
    role: str
    must_change_password: bool


class AuthService:
    def __init__(self, db: DatabaseSession) -> None:
        self.db = db
        self.user_repo = UserRepository(db)
        self.session_repo = SessionRepository(db)

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _user_context(user) -> UserContext:
        return UserContext(
            user_id=user.user_id,
            username=user.username,
            role=user.role,
            must_change_password=user.must_change_password,
        )

    def login(self, username: str, password: str) -> tuple[UserContext, str, datetime]:
        """Verify credentials and create one non-sliding eight-hour session."""

        user = self.user_repo.get_by_username(username)
        if not user or not user.is_active:
            raise AppException("UNAUTHENTICATED", "账号或密码不正确", 401)

        try:
            ph.verify(user.password_hash, password)
        except (VerifyMismatchError, VerificationError) as exc:
            raise AppException("UNAUTHENTICATED", "账号或密码不正确", 401) from exc

        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=SESSION_MAX_AGE)
        self.db.add(
            SessionModel(
                user_id=user.user_id,
                token_hash=self._token_hash(token),
                expires_at=expires_at,
            )
        )
        self.db.commit()
        return self._user_context(user), token, expires_at

    def _get_valid_session(self, token: str) -> tuple[SessionModel, object]:
        session = self.session_repo.get_by_token_hash(self._token_hash(token))
        if not session:
            raise AppException("UNAUTHENTICATED", "未登录或会话已失效", 401)
        if session.revoked_at:
            raise AppException("UNAUTHENTICATED", "未登录或会话已失效", 401)
        if datetime.now(timezone.utc) >= self._as_utc(session.expires_at):
            raise AppException("UNAUTHENTICATED", "未登录或会话已失效", 401)

        user = self.user_repo.get_by_id(session.user_id)
        if not user or not user.is_active:
            raise AppException("UNAUTHENTICATED", "未登录或会话已失效", 401)
        return session, user

    def verify_token(self, token: str) -> UserContext:
        """Validate a token and return the public user context."""

        _, user = self._get_valid_session(token)
        return self._user_context(user)

    def verify_token_with_expiry(self, token: str) -> tuple[UserContext, datetime]:
        """Validate a token and return its fixed expiry for the ``/auth/me`` contract."""

        session, user = self._get_valid_session(token)
        return self._user_context(user), self._as_utc(session.expires_at)

    def logout(self, token: str) -> None:
        """Revoke one session; an unknown or already revoked token is harmless."""

        session = self.session_repo.get_by_token_hash(self._token_hash(token))
        if session and not session.revoked_at:
            session.revoked_at = datetime.now(timezone.utc)
            self.db.commit()

    def change_password(
        self, user_id: UUID, current_password: str, new_password: str
    ) -> None:
        """Change a password and revoke every session belonging to the user."""

        user = self.user_repo.get_by_id(user_id)
        if not user:
            raise AppException("FORBIDDEN", "当前密码不正确", 403)

        try:
            ph.verify(user.password_hash, current_password)
        except (VerifyMismatchError, VerificationError) as exc:
            raise AppException("FORBIDDEN", "当前密码不正确", 403) from exc

        if current_password == new_password:
            raise AppException("VALIDATION_ERROR", "新密码不能与旧密码相同", 422)
        if not 12 <= len(new_password) <= 128:
            raise AppException("VALIDATION_ERROR", "密码长度必须为12-128字符", 422)

        user.password_hash = ph.hash(new_password)
        user.must_change_password = False
        user.password_changed_at = datetime.now(timezone.utc)
        self.session_repo.revoke_all_by_user(user_id, datetime.now(timezone.utc))
        self.db.commit()
