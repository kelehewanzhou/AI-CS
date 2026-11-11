"""Persistence for answer snapshots; the service owns the transaction."""

from sqlalchemy.orm import Session

from .models import QARecord


class QARepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add_record(self, **values) -> None:
        self.db.add(QARecord(**values))
        self.db.flush()
