"""Learning event, state, cursor, and content-summary services."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from common.config import settings
from common.errors import AppException
from exercise.repository import ExerciseRepository
from graph.models import Course, ImportRun, KnowledgeEdge, KnowledgeNode
from graph.repository import GraphRepository

from .models import LearningEvent
from .repository import LearningRepository
from .rules import LearningRules
from .schemas import ContentSummary, EVENT_RESOURCE_PAIRS, EVENT_TYPES, EventView


class LearningService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = LearningRepository(db)
        self.graph_repo = GraphRepository(db)
        self.exercise_repo = ExerciseRepository(db)

    def record_event(
        self,
        user_id: UUID,
        event_type: str,
        resource_type: str,
        resource_id: str | None = None,
    ) -> dict[str, Any]:
        # Keep the compact service call from the task example usable while
        # the HTTP contract remains explicit about resource_type.
        if resource_id is None:
            resource_id = resource_type
            resource_type = EVENT_RESOURCE_PAIRS.get(event_type, "")
        expected_type = EVENT_RESOURCE_PAIRS.get(event_type)
        if expected_type is None or resource_type != expected_type:
            raise AppException("VALIDATION_ERROR", "event_type与resource_type不匹配", 422)

        resource_kwargs: dict[str, str] = {}
        if event_type == "view_node":
            node = self.graph_repo.get_node_by_id(resource_id)
            if node is None or not node.is_active:
                raise AppException("NOT_FOUND", f"节点{resource_id}不存在", 404)
            resource_kwargs["node_id"] = resource_id
        elif event_type == "view_edge":
            edge = self.graph_repo.get_edge_by_id(resource_id)
            if edge is None or not edge.is_active:
                raise AppException("NOT_FOUND", f"关系{resource_id}不存在", 404)
            resource_kwargs["edge_id"] = resource_id
        else:
            exercise = self.exercise_repo.get_by_id(resource_id)
            if exercise is None or not exercise.is_active:
                raise AppException("NOT_FOUND", f"题目{resource_id}不存在", 404)
            resource_kwargs["question_id"] = resource_id

        event = self.repo.create_event(user_id, event_type, **resource_kwargs)
        self.db.commit()
        return self._event_view(event)

    def get_events(
        self,
        user_id: UUID,
        event_type: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        if event_type is not None and event_type not in EVENT_TYPES:
            raise AppException("VALIDATION_ERROR", "非法事件类型", 422)

        after_created_at: datetime | None = None
        after_event_id: int | None = None
        if cursor:
            payload = self._verify_cursor(cursor, user_id, "events", event_type)
            after_created_at = self._parse_cursor_datetime(payload["created_at"])
            if self.db.bind is not None and self.db.bind.dialect.name == "sqlite":
                # SQLite stores DateTime values without timezone information;
                # compare using the same naive UTC representation it stores.
                after_created_at = after_created_at.replace(tzinfo=None)
            after_event_id = int(payload["record_id"])

        events = self.repo.list_events(
            user_id,
            event_type,
            limit + 1,
            after_created_at,
            after_event_id,
        )
        has_more = len(events) > limit
        page = events[:limit]
        items = [self._event_view(event) for event in page]
        next_cursor = None
        if has_more and page:
            last = page[-1]
            next_cursor = self._generate_cursor(
                user_id,
                "events",
                event_type,
                last.created_at,
                int(last.event_id),
            )
        return items, next_cursor

    def get_states(self, user_id: UUID, node_ids: list[str] | None = None) -> list[dict[str, Any]]:
        if node_ids:
            # The public contract de-duplicates repeated node_id values while
            # preserving the first occurrence's order.
            target_nodes = list(dict.fromkeys(node_ids))
            if len(target_nodes) > 60:
                raise AppException("VALIDATION_ERROR", "node_id最多支持60个", 422)
            for node_id in target_nodes:
                node = self.graph_repo.get_node_by_id(node_id)
                if node is None or not node.is_active:
                    raise AppException("NOT_FOUND", f"节点{node_id}不存在", 404)
        else:
            target_nodes = [node.node_id for node in self.graph_repo.get_all_active_nodes()]

        return [LearningRules.compute_state(user_id, node_id, self.db) for node_id in target_nodes]

    def get_content_summary(self) -> dict[str, Any]:
        last_import = self.db.execute(
            select(ImportRun)
            .where(ImportRun.status == "succeeded")
            .order_by(ImportRun.finished_at.desc(), ImportRun.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if last_import is None or last_import.finished_at is None:
            raise AppException("UNAVAILABLE", "未导入种子数据", 503)

        counts = {
            "courses": self._active_count(Course),
            "nodes": self._active_count(KnowledgeNode),
            "edges": self._active_count(KnowledgeEdge),
            "exercises": self._active_count_by_table("exercises"),
        }
        finished_at = self._as_utc(last_import.finished_at).isoformat().replace("+00:00", "Z")
        return ContentSummary(
            content_scope="current_seed",
            seed_checksum=last_import.checksum,
            last_import={"run_id": str(last_import.run_id), "finished_at": finished_at},
            counts=counts,
            edge_evidence_counts=self.repo.list_edge_evidence_counts(),
        ).model_dump()

    def _active_count(self, model: type) -> int:
        return int(
            self.db.execute(
                select(func.count()).select_from(model).where(model.is_active.is_(True))
            ).scalar_one()
        )

    def _active_count_by_table(self, table_name: str) -> int:
        # The exercise model is deliberately used for the query rather than
        # exposing a generic table API to callers.
        from exercise.models import Exercise

        if table_name != "exercises":
            raise ValueError("unsupported content table")
        return self._active_count(Exercise)

    @staticmethod
    def _event_view(event: LearningEvent) -> dict[str, Any]:
        if event.event_type == "view_node":
            resource_type, resource_id = "node", event.node_id
        elif event.event_type == "view_edge":
            resource_type, resource_id = "edge", event.edge_id
        else:
            resource_type, resource_id = "exercise", event.question_id
        created_at = LearningService._as_utc(event.created_at).isoformat().replace("+00:00", "Z")
        return EventView(
            event_id=int(event.event_id),
            event_type=event.event_type,
            resource_type=resource_type,
            resource_id=resource_id or "",
            created_at=created_at,
        ).model_dump()

    # Names used by the module-internal §3.8 contract.
    def states(self, user_id: UUID, node_ids: list[str] | None = None) -> list[dict[str, Any]]:
        return self.get_states(user_id, node_ids)

    def content_summary(self) -> dict[str, Any]:
        return self.get_content_summary()

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _parse_cursor_datetime(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid cursor timestamp") from exc
        return LearningService._as_utc(parsed)

    @staticmethod
    def _cursor_signature(payload: dict[str, Any]) -> str:
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hmac.new(
            settings.session_secret_key.encode("utf-8"),
            data.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @classmethod
    def _generate_cursor(
        cls,
        user_id: UUID,
        scope: str,
        filter_val: str | None,
        created_at: datetime,
        record_id: int,
    ) -> str:
        payload = {
            "user_id": str(user_id),
            "scope": scope,
            "filter": filter_val,
            "created_at": cls._as_utc(created_at).isoformat(),
            "record_id": int(record_id),
        }
        envelope = {"data": payload, "sig": cls._cursor_signature(payload)}
        encoded = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(encoded).decode("ascii")

    @classmethod
    def _verify_cursor(
        cls,
        cursor: str,
        expected_user_id: UUID,
        scope: str,
        filter_val: str | None,
    ) -> dict[str, Any]:
        try:
            decoded = base64.urlsafe_b64decode(cursor.encode("ascii"))
            envelope = json.loads(decoded.decode("utf-8"))
            payload = envelope["data"]
            signature = envelope["sig"]
            if not isinstance(payload, dict) or not isinstance(signature, str):
                raise ValueError("malformed cursor")
            if not hmac.compare_digest(signature, cls._cursor_signature(payload)):
                raise ValueError("signature mismatch")
            if payload.get("user_id") != str(expected_user_id):
                raise ValueError("user mismatch")
            if payload.get("scope") != scope or payload.get("filter") != filter_val:
                raise ValueError("cursor scope mismatch")
            if not isinstance(payload.get("created_at"), str):
                raise ValueError("invalid cursor timestamp")
            cls._parse_cursor_datetime(payload["created_at"])
            if not isinstance(payload.get("record_id"), int) or payload["record_id"] < 1:
                raise ValueError("invalid cursor id")
            return payload
        except (ValueError, TypeError, KeyError, UnicodeError, json.JSONDecodeError) as exc:
            raise AppException("VALIDATION_ERROR", "非法游标", 422) from exc
