"""Database reads used by the graph service."""

from __future__ import annotations

import re
import unicodedata

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased

from .models import KnowledgeEdge, KnowledgeNode


def normalize_text(value: str) -> str:
    """Normalize graph search text using the seed import contract."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


class GraphRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_node_by_id(self, node_id: str) -> KnowledgeNode | None:
        return self.db.execute(
            select(KnowledgeNode).where(KnowledgeNode.node_id == node_id)
        ).scalar_one_or_none()

    def get_all_active_nodes(self) -> list[KnowledgeNode]:
        return list(
            self.db.execute(
                select(KnowledgeNode)
                .where(KnowledgeNode.is_active.is_(True))
                .order_by(KnowledgeNode.node_id)
            ).scalars()
        )

    def find_nodes(
        self, course_code: str | None = None, q: str | None = None
    ) -> list[KnowledgeNode]:
        statement = select(KnowledgeNode).where(KnowledgeNode.is_active.is_(True))
        if course_code:
            statement = statement.where(KnowledgeNode.course_code == course_code)
        candidates = list(
            self.db.execute(statement.order_by(KnowledgeNode.node_id)).scalars()
        )
        if not q:
            return candidates
        needle = normalize_text(q)
        if not needle:
            return []
        return [
            node
            for node in candidates
            if needle in normalize_text(node.title)
            or any(needle in normalize_text(alias) for alias in (node.aliases or []))
        ]

    def get_filtered_edges(
        self,
        relation_types: list[str] | None = None,
        evidence_statuses: list[str] | None = None,
    ) -> list[KnowledgeEdge]:
        statement = select(KnowledgeEdge).where(KnowledgeEdge.is_active.is_(True))
        if relation_types:
            statement = statement.where(KnowledgeEdge.relation_type.in_(relation_types))
        if evidence_statuses:
            statement = statement.where(KnowledgeEdge.evidence_status.in_(evidence_statuses))
        return list(
            self.db.execute(statement.order_by(KnowledgeEdge.edge_id)).scalars()
        )

    def get_incident_edges(self, node_id: str) -> list[KnowledgeEdge]:
        source_node = aliased(KnowledgeNode)
        target_node = aliased(KnowledgeNode)
        return list(
            self.db.execute(
                select(KnowledgeEdge)
                .join(source_node, source_node.node_id == KnowledgeEdge.source_id)
                .join(target_node, target_node.node_id == KnowledgeEdge.target_id)
                .where(
                    KnowledgeEdge.is_active.is_(True),
                    source_node.is_active.is_(True),
                    target_node.is_active.is_(True),
                    or_(
                        KnowledgeEdge.source_id == node_id,
                        KnowledgeEdge.target_id == node_id,
                    ),
                )
                .order_by(KnowledgeEdge.edge_id)
            ).scalars()
        )

    def get_edge_by_id(self, edge_id: str) -> KnowledgeEdge | None:
        return self.db.execute(
            select(KnowledgeEdge).where(KnowledgeEdge.edge_id == edge_id)
        ).scalar_one_or_none()

    @staticmethod
    def get_neighbors(node_id: str, edges: list[KnowledgeEdge]) -> set[str]:
        """Return both incoming and outgoing neighbors for graph traversal."""

        neighbors: set[str] = set()
        for edge in edges:
            if edge.source_id == node_id:
                neighbors.add(edge.target_id)
            elif edge.target_id == node_id:
                neighbors.add(edge.source_id)
        return neighbors
