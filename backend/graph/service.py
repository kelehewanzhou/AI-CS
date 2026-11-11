"""Read-only graph query service and response DTO construction."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session

from common.errors import AppException

from .repository import GraphRepository, normalize_text
from .schemas import (
    EdgeView,
    EvidenceOverview,
    GraphNode,
    NodeContent,
    SubgraphMeta,
    SubgraphQuery,
    SubgraphResult,
)


RELATION_DISPLAY = {
    "prerequisite": {
        "display_mode": "directed",
        "label_template": "{source} 是 {target} 的前置知识",
    },
    "implements": {
        "display_mode": "directed",
        "label_template": "{source} 实现/支撑 {target}",
    },
    "contrast": {
        "display_mode": "symmetric",
        "label_template": "{source} vs {target}",
    },
    "boundary": {
        "display_mode": "symmetric",
        "label_template": "{source} 与 {target} 的边界",
    },
}

RELATION_TYPES = tuple(RELATION_DISPLAY)
EVIDENCE_STATUSES = ("已核验", "部分定位", "待补充")
NODE_LIMIT = 60
EDGE_LIMIT = 120


def compute_node_evidence_status(edges: Iterable[object]) -> dict:
    """Compute the weakest evidence state among a node's active edges."""

    edge_list = list(edges)
    if not edge_list:
        return {
            "status": "待补充",
            "reason": "no_relations",
            "counts": {"verified": 0, "partial": 0, "pending": 0},
            "edge_ids": [],
        }

    counts = {"verified": 0, "partial": 0, "pending": 0}
    edge_ids: list[str] = []
    for edge in edge_list:
        edge_ids.append(edge.edge_id)
        if edge.evidence_status == "已核验":
            counts["verified"] += 1
        elif edge.evidence_status == "部分定位":
            counts["partial"] += 1
        else:
            counts["pending"] += 1

    if counts["pending"]:
        status = "待补充"
    elif counts["partial"]:
        status = "部分定位"
    else:
        status = "已核验"
    return {
        "status": status,
        "reason": "incident_edges",
        "counts": counts,
        "edge_ids": edge_ids,
    }


class GraphService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = GraphRepository(db)

    def get_subgraph(self, query: SubgraphQuery, seed_checksum: str) -> SubgraphResult:
        self._validate_query(query)

        if query.node_id is not None:
            seed_node = self.repo.get_node_by_id(query.node_id)
            if not seed_node or not seed_node.is_active:
                raise AppException("NOT_FOUND", f"节点{query.node_id}不存在", 404)
            if query.course_code and seed_node.course_code != query.course_code:
                raise AppException("VALIDATION_ERROR", "中心节点不属于指定课程", 422)
            seed_nodes = [seed_node]
            mode = "centered"
        elif query.course_code is not None or query.q is not None:
            seed_nodes = self.repo.find_nodes(query.course_code, query.q)
            if not seed_nodes:
                return self._empty_subgraph(query, seed_checksum)
            mode = "filtered"
        else:
            all_nodes = self.repo.get_all_active_nodes()
            filtered_edges = self._active_endpoint_edges(
                self.repo.get_filtered_edges(query.relation_type, query.evidence_status),
                {node.node_id for node in all_nodes},
            )
            return self._build_subgraph_result(
                all_nodes, filtered_edges, "overview", [], 0, query, seed_checksum
            )

        # Apply edge filters before the BFS, as required by §3.3.
        filtered_edges = self.repo.get_filtered_edges(
            query.relation_type, query.evidence_status
        )
        active_node_ids = {node.node_id for node in self.repo.get_all_active_nodes()}
        filtered_edges = self._active_endpoint_edges(filtered_edges, active_node_ids)

        visited_nodes = {node.node_id: node for node in seed_nodes}
        current_layer = [node.node_id for node in seed_nodes]
        for _ in range(query.hops):
            next_layer: set[str] = set()
            for node_id in current_layer:
                for neighbor_id in self.repo.get_neighbors(node_id, filtered_edges):
                    if neighbor_id in visited_nodes or neighbor_id not in active_node_ids:
                        continue
                    neighbor = self.repo.get_node_by_id(neighbor_id)
                    if neighbor and neighbor.is_active:
                        visited_nodes[neighbor_id] = neighbor
                        next_layer.add(neighbor_id)
            current_layer = sorted(next_layer)

        result_edges = [
            edge
            for edge in filtered_edges
            if edge.source_id in visited_nodes and edge.target_id in visited_nodes
        ]
        self._ensure_within_limits(len(visited_nodes), len(result_edges))
        return self._build_subgraph_result(
            list(visited_nodes.values()),
            result_edges,
            mode,
            [node.node_id for node in seed_nodes],
            query.hops,
            query,
            seed_checksum,
        )

    def get_node(self, node_id: str) -> NodeContent:
        node = self.repo.get_node_by_id(node_id)
        if not node or not node.is_active:
            raise AppException("NOT_FOUND", f"节点{node_id}不存在", 404)

        edges = self.repo.get_incident_edges(node_id)
        incoming = [edge for edge in edges if edge.target_id == node_id]
        outgoing = [edge for edge in edges if edge.source_id == node_id]
        return NodeContent(
            node_id=node.node_id,
            title=node.title,
            course_code=node.course_code,
            chapter_scope=node.chapter_scope,
            description=node.description,
            aliases=list(node.aliases or []),
            scope_tags=list(node.scope_tags or []),
            evidence_overview=EvidenceOverview.model_validate(
                compute_node_evidence_status(edges)
            ),
            incoming_edges=[self._build_edge_view(edge) for edge in incoming],
            outgoing_edges=[self._build_edge_view(edge) for edge in outgoing],
        )

    def get_edge(self, edge_id: str) -> EdgeView:
        edge = self.repo.get_edge_by_id(edge_id)
        if not edge or not edge.is_active:
            raise AppException("NOT_FOUND", f"关系{edge_id}不存在", 404)
        source = self.repo.get_node_by_id(edge.source_id)
        target = self.repo.get_node_by_id(edge.target_id)
        if not source or not source.is_active or not target or not target.is_active:
            raise AppException("NOT_FOUND", "关系端点已下线", 404)
        return self._build_edge_view(edge, source.title, target.title)

    @staticmethod
    def _validate_query(query: SubgraphQuery) -> None:
        if query.node_id is not None and query.q is not None:
            raise AppException("VALIDATION_ERROR", "node_id不能与q同时使用", 422)
        if query.q is not None and not normalize_text(query.q):
            raise AppException("VALIDATION_ERROR", "q归一化后不能为空", 422)

    @staticmethod
    def _active_endpoint_edges(edges, active_node_ids: set[str]):
        return [
            edge
            for edge in edges
            if edge.source_id in active_node_ids and edge.target_id in active_node_ids
        ]

    @staticmethod
    def _ensure_within_limits(node_count: int, edge_count: int) -> None:
        if node_count > NODE_LIMIT or edge_count > EDGE_LIMIT:
            raise AppException(
                "VALIDATION_ERROR",
                "子图超过限制（60节点/120边），请缩小查询范围",
                422,
                {"reason": "subgraph_limit"},
            )

    def _empty_subgraph(self, query: SubgraphQuery, seed_checksum: str) -> SubgraphResult:
        return self._build_subgraph_result(
            [], [], "filtered", [], query.hops, query, seed_checksum
        )

    def _build_subgraph_result(
        self, nodes, edges, mode, seed_node_ids, applied_hops, query, seed_checksum
    ) -> SubgraphResult:
        sorted_nodes = sorted(nodes, key=lambda node: node.node_id)
        sorted_edges = sorted(edges, key=lambda edge: edge.edge_id)
        self._ensure_within_limits(len(sorted_nodes), len(sorted_edges))
        return SubgraphResult(
            nodes=[self._build_graph_node(node) for node in sorted_nodes],
            edges=[self._build_edge_view(edge) for edge in sorted_edges],
            meta=SubgraphMeta(
                mode=mode,
                seed_node_ids=seed_node_ids,
                applied_hops=applied_hops,
                filters=self._filters(query),
                node_count=len(sorted_nodes),
                edge_count=len(sorted_edges),
                seed_checksum=seed_checksum,
            ),
        )

    @staticmethod
    def _filters(query: SubgraphQuery) -> dict:
        return {
            "node_id": query.node_id,
            "course_code": query.course_code,
            "q": query.q,
            "relation_types": list(query.relation_type or RELATION_TYPES),
            "evidence_statuses": list(query.evidence_status or EVIDENCE_STATUSES),
        }

    def _build_graph_node(self, node) -> GraphNode:
        evidence = compute_node_evidence_status(self.repo.get_incident_edges(node.node_id))
        return GraphNode(
            node_id=node.node_id,
            title=node.title,
            course_code=node.course_code,
            evidence_status=evidence["status"],
        )

    def _build_edge_view(self, edge, source_title: str | None = None, target_title: str | None = None) -> EdgeView:
        source_title = source_title or getattr(edge, "source_title", None)
        target_title = target_title or getattr(edge, "target_title", None)
        if not source_title:
            source = self.repo.get_node_by_id(edge.source_id)
            source_title = source.title if source else edge.source_id
        if not target_title:
            target = self.repo.get_node_by_id(edge.target_id)
            target_title = target.title if target else edge.target_id

        display = RELATION_DISPLAY.get(edge.relation_type)
        if display is None:
            raise AppException("INTERNAL_ERROR", "关系类型未配置展示规则", 500)
        return EdgeView(
            edge_id=edge.edge_id,
            source_id=edge.source_id,
            source_title=source_title,
            target_id=edge.target_id,
            target_title=target_title,
            relation_type=edge.relation_type,
            display_mode=display["display_mode"],
            display_label=display["label_template"].format(
                source=source_title, target=target_title
            ),
            mechanism=edge.mechanism,
            abc_grade=edge.abc_grade,
            boundary_note=edge.boundary_note or "",
            evidence_status=edge.evidence_status,
            evidence_summary=edge.evidence_summary,
            evidence_detail=edge.evidence_detail,
        )

    def _generate_display_label(self, edge) -> str:
        """Generate a label for callers that already provide endpoint titles."""

        display = RELATION_DISPLAY[edge.relation_type]
        source_title = getattr(edge, "source_title", None)
        target_title = getattr(edge, "target_title", None)
        if not source_title:
            source = self.repo.get_node_by_id(edge.source_id)
            source_title = source.title if source else edge.source_id
        if not target_title:
            target = self.repo.get_node_by_id(edge.target_id)
            target_title = target.title if target else edge.target_id
        return display["label_template"].format(
            source=source_title,
            target=target_title,
        )

    _compute_evidence_overview = staticmethod(compute_node_evidence_status)
