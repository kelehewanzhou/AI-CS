"""Small repository objects used by the authentication service."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session as DatabaseSession

from .models import Session as SessionModel
from .models import User


class UserRepository:
    def __init__(self, db: DatabaseSession) -> None:
        self.db = db

    def get_by_username(self, username: str) -> User | None:
        return self.db.execute(
            select(User).where(User.username == username)
        ).scalar_one_or_none()

    def get_by_id(self, user_id: UUID) -> User | None:
        return self.db.execute(
            select(User).where(User.user_id == user_id)
        ).scalar_one_or_none()


class SessionRepository:
    def __init__(self, db: DatabaseSession) -> None:
        self.db = db

    def get_by_token_hash(self, token_hash: str) -> SessionModel | None:
        return self.db.execute(
            select(SessionModel).where(SessionModel.token_hash == token_hash)
        ).scalar_one_or_none()

    def revoke_all_by_user(
        self, user_id: UUID, revoked_at: datetime | None = None
    ) -> None:
        revoked_at = revoked_at or datetime.now(timezone.utc)
        self.db.execute(
            update(SessionModel)
            .where(
                SessionModel.user_id == user_id,
                SessionModel.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )
