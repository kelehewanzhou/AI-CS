"""Deterministic matching, verified evidence selection, and template answers."""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from common.config import settings
from common.errors import AppException
from graph.repository import normalize_text
from graph.service import GraphService, RELATION_TYPES

from .repository import QARepository
from .schemas import QAResponse


logger = logging.getLogger(__name__)


class QAService:
    RELATION_KEYWORDS = {
        "prerequisite": ("前置", "先学", "基础"),
        "implements": ("实现", "支撑", "实施"),
        "contrast": ("比较", "对比", "区别", "差异"),
        "boundary": ("边界", "职责", "划分"),
    }

    def __init__(self, db: Session) -> None:
        self.db = db
        self.graph_service = GraphService(db)
        self.repo = QARepository(db)

    def ask(self, user_id: UUID, question: str, request_id: str) -> dict:
        question = question.strip()
        if not 1 <= len(question) <= 500 or not normalize_text(question):
            raise AppException("VALIDATION_ERROR", "问题须为1—500字且包含有效文本", 422)

        try:
            normalized_q = normalize_text(question)
            nodes = self._match_nodes(normalized_q, self._load_qa_dictionary())
            if not nodes:
                result = self._failure(
                    "not_covered", "no_match",
                    "当前知识图谱未覆盖这个问题，请尝试更具体的知识点名称。",
                    "未匹配到当前有效知识点",
                )
            elif len(nodes) > 2:
                result = self._failure(
                    "not_covered", "too_many_nodes",
                    f"问题涉及{len(nodes)}个知识点，请拆分为单个或两个知识点的问题。",
                    "一次最多处理两个知识点",
                )
            elif len(nodes) == 1:
                result = self._answer_concept(nodes[0])
            else:
                result = self._answer_relation(nodes[0], nodes[1], normalized_q)
        except AppException:
            self.db.rollback()
            raise
        except Exception as exc:
            self._log_failure(request_id, exc)
            self.db.rollback()
            is_database_error = isinstance(exc, SQLAlchemyError)
            raise AppException(
                "UNAVAILABLE" if is_database_error else "INTERNAL_ERROR",
                "问答服务暂时不可用", 503 if is_database_error else 500,
            ) from exc

        # A response becomes successful only after its snapshot is committed.
        # Do not log exception messages/SQL parameters: they may contain the question.
        try:
            self.repo.add_record(
                question_text=question,
                answer_text=result.answer,
                status=result.status,
                reason=result.reason or "",
                used_node_ids=result.used_node_ids,
                used_edge_ids=result.used_edge_ids,
                uncertainty_flag=result.uncertainty_flag,
                boundary_note=result.boundary_note,
                actor_key=self._actor_key(user_id),
                request_id=request_id,
            )
            self.db.commit()
        except Exception as exc:
            self._log_failure(request_id, exc)
            self.db.rollback()
            raise AppException("UNAVAILABLE", "问答记录保存失败，请稍后重试", 503) from exc
        return result.model_dump()

    @staticmethod
    def _log_failure(request_id: str, exc: Exception) -> None:
        logger.error("QA failure request_id=%s exception_type=%s", request_id, type(exc).__name__)

    @staticmethod
    def _actor_key(user_id: UUID) -> str:
        month = datetime.now(timezone.utc).strftime("%Y%m")
        return hmac.new(
            f"{settings.session_secret_key}:{month}".encode(),
            str(user_id).encode(), hashlib.sha256,
        ).hexdigest()

    _normalize_text = staticmethod(normalize_text)

    def _load_qa_dictionary(self) -> list[dict]:
        return [
            {
                "node_id": node.node_id,
                "title": node.title,
                "normalized_title": normalize_text(node.title),
                "description": node.description,
                "aliases": [
                    {"normalized": normalized}
                    for alias in (node.aliases or [])
                    if len(normalized := normalize_text(alias)) >= 2
                ],
            }
            for node in self.graph_service.repo.get_all_active_nodes()
        ]

    def _match_nodes(self, normalized_q: str, nodes_dict: list[dict]) -> list[dict]:
        matches = []
        for node in nodes_dict:
            terms = [(node["normalized_title"], 0)]
            terms.extend((alias["normalized"], 1) for alias in node["aliases"])
            for term, priority in terms:
                if not term:
                    continue
                pattern = re.escape(term)
                if priority == 1 and re.fullmatch(r"[a-z0-9]+", term):
                    # ASCII boundaries also allow acronyms adjacent to Chinese.
                    pattern = rf"(?<![a-z0-9]){pattern}(?![a-z0-9])"
                for match in re.finditer(rf"(?=({pattern}))", normalized_q):
                    matches.append((match.start(), match.start() + len(term), priority, node))

        # Keep every occurrence until containment has been resolved. An independent
        # occurrence of a short title must survive a longer phrase elsewhere.
        retained = [
            match for match in matches
            if not any(
                other[0] <= match[0] and match[1] <= other[1]
                and other[1] - other[0] > match[1] - match[0]
                for other in matches
            )
        ]
        retained.sort(key=lambda item: (item[2], -(item[1] - item[0]), item[3]["node_id"]))
        unique = {}
        for _, _, _, node in retained:
            unique.setdefault(node["node_id"], node)
        return list(unique.values())

    @staticmethod
    def _failure(status: str, reason: str | None, answer: str, boundary: str) -> QAResponse:
        return QAResponse(
            status=status, reason=reason, answer=answer,
            used_node_ids=[], used_edge_ids=[], uncertainty_flag=True, boundary_note=boundary,
        )

    def _answer_concept(self, node: dict) -> QAResponse:
        edges = self.graph_service.repo.get_incident_edges(node["node_id"])
        selected = sorted(
            (edge for edge in edges if edge.evidence_status == "已核验"),
            key=lambda edge: edge.edge_id,
        )[:3]
        if not selected:
            return self._failure(
                "insufficient_evidence", None,
                f"知识点“{node['title']}”暂无已核验的关系证据，无法提供可靠解释。",
                "缺少当前有效且已核验的关联关系",
            )
        return self._render_answer(f"{node['title']}：{node['description']}", selected)

    def _answer_relation(self, node1: dict, node2: dict, normalized_q: str) -> QAResponse:
        detected = [
            relation for relation, keywords in self.RELATION_KEYWORDS.items()
            if any(keyword in normalized_q for keyword in keywords)
        ]
        if len(detected) > 1:
            return self._failure(
                "not_covered", "ambiguous_relation",
                "问题同时涉及多种关系类型，请一次只询问一种关系（前置、实现、对比或边界）。",
                "关系类型不明确",
            )
        direct = [
            edge for edge in self.graph_service.repo.get_incident_edges(node1["node_id"])
            if {edge.source_id, edge.target_id} == {node1["node_id"], node2["node_id"]}
            and (not detected or edge.relation_type == detected[0])
        ]
        if not direct:
            return self._failure(
                "not_covered", "no_direct_relation",
                f"{node1['title']}与{node2['title']}之间没有记录的所询类型直接关系。",
                "当前图谱未覆盖所询直接关系，不推断多跳关系",
            )
        selected = sorted(
            (edge for edge in direct if edge.evidence_status == "已核验"),
            key=lambda edge: (RELATION_TYPES.index(edge.relation_type), edge.edge_id),
        )[:3]
        if not selected:
            return self._failure(
                "insufficient_evidence", None,
                f"{node1['title']}与{node2['title']}的关系证据不足，尚未完成教材核验。",
                "候选直接关系仅有部分定位或待补充证据",
            )
        return self._render_answer(f"{node1['title']}与{node2['title']}的关系：", selected)

    def _render_answer(self, heading: str, edges: list) -> QAResponse:
        parts = [heading]
        for edge in edges:
            label = self.graph_service._generate_display_label(edge)
            parts.append(f"- {label}：{edge.mechanism}")
        parts.append("\n（以上内容为基于课程教材关系的自编说明，非教材原文。）")
        return QAResponse(
            status="answered", reason=None, answer="\n".join(parts),
            used_node_ids=sorted({node_id for edge in edges for node_id in (edge.source_id, edge.target_id)}),
            used_edge_ids=[edge.edge_id for edge in edges], uncertainty_flag=False,
            boundary_note=" | ".join(dict.fromkeys(edge.boundary_note for edge in edges if edge.boundary_note)),
        )
