"""Task 4 graph traversal, evidence, and API contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from auth.models import User
from auth.service import ph
from graph.models import Course, KnowledgeEdge, KnowledgeNode
from graph.schemas import SubgraphQuery
from graph.service import GraphService, compute_node_evidence_status


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def _seed_graph(db_session) -> None:
    courses = json.loads((FIXTURES / "courses.json").read_text(encoding="utf-8"))["items"]
    nodes = json.loads((FIXTURES / "nodes.json").read_text(encoding="utf-8"))["items"]
    edges = json.loads((FIXTURES / "edges.json").read_text(encoding="utf-8"))["items"]
    db_session.add_all([Course(**course) for course in courses])
    db_session.add_all([KnowledgeNode(**node) for node in nodes])
    db_session.add_all([KnowledgeEdge(**edge) for edge in edges])
    db_session.commit()


def _login(client, db_session) -> None:
    user = User(
        username="graphuser",
        password_hash=ph.hash("password123"),
        role="student",
        must_change_password=False,
    )
    db_session.add(user)
    db_session.commit()
    response = client.post(
        "/auth/login",
        json={"username": "graphuser", "password": "password123"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code == 200


@pytest.fixture
def seeded_graph(db_session):
    _seed_graph(db_session)
    return db_session


def test_subgraph_centered_queries_and_filters(client, seeded_graph):
    _login(client, seeded_graph)

    one_hop = client.get("/graph/subgraph?node_id=CO03&hops=1")
    assert one_hop.status_code == 200
    one_data = one_hop.json()["data"]
    assert {node["node_id"] for node in one_data["nodes"]} == {"CO03", "OS02"}
    assert [edge["edge_id"] for edge in one_data["edges"]] == ["E001"]
    assert one_data["meta"]["mode"] == "centered"
    assert one_data["meta"]["seed_node_ids"] == ["CO03"]
    assert one_data["meta"]["applied_hops"] == 1
    assert one_data["meta"]["seed_checksum"] == ""
    assert one_data["meta"]["filters"]["relation_types"] == [
        "prerequisite",
        "implements",
        "contrast",
        "boundary",
    ]
    assert one_data["meta"]["filters"]["evidence_statuses"] == [
        "已核验",
        "部分定位",
        "待补充",
    ]

    two_hop = client.get("/graph/subgraph?node_id=CO03&hops=2")
    assert {node["node_id"] for node in two_hop.json()["data"]["nodes"]} == {
        "CO03",
        "OS02",
        "OS03",
    }
    assert [edge["edge_id"] for edge in two_hop.json()["data"]["edges"]] == [
        "E001",
        "E002",
    ]

    filtered = client.get(
        "/graph/subgraph?course_code=CO&hops=2&relation_type=implements&"
        "evidence_status=%E5%B7%B2%E6%A0%B8%E9%AA%8C"
    )
    filtered_data = filtered.json()["data"]
    assert {node["node_id"] for node in filtered_data["nodes"]} == {"CO03", "OS02"}
    assert [edge["edge_id"] for edge in filtered_data["edges"]] == ["E001"]
    assert filtered_data["meta"]["filters"] == {
        "node_id": None,
        "course_code": "CO",
        "q": None,
        "relation_types": ["implements"],
        "evidence_statuses": ["已核验"],
    }

    keyword = client.get("/graph/subgraph?q=TLB&hops=1")
    assert [node["node_id"] for node in keyword.json()["data"]["nodes"]] == [
        "CO03",
        "OS02",
    ]


def test_node_and_edge_details_include_evidence_and_display_fields(
    client, seeded_graph
):
    _login(client, seeded_graph)

    node_response = client.get("/nodes/CO03")
    assert node_response.status_code == 200
    node = node_response.json()["data"]["node"]
    assert node["evidence_overview"] == {
        "status": "已核验",
        "reason": "incident_edges",
        "counts": {"verified": 1, "partial": 0, "pending": 0},
        "edge_ids": ["E001"],
    }
    assert [edge["edge_id"] for edge in node["outgoing_edges"]] == ["E001"]
    assert node_response.json()["data"]["exercise_count"] == 0
    assert node_response.json()["data"]["learning"]["state"] == "未学习"
    assert node_response.json()["data"]["learning"]["reason"] == "no_activity"

    edge_response = client.get("/edges/E001")
    assert edge_response.status_code == 200
    edge = edge_response.json()["data"]
    assert edge["display_mode"] == "directed"
    assert "实现/支撑" in edge["display_label"]
    assert edge["evidence_detail"]["book_title"] == "计算机组成原理"


def test_evidence_weakest_rule_and_isolated_node(seeded_graph):
    service = GraphService(seeded_graph)
    assert compute_node_evidence_status([]) == {
        "status": "待补充",
        "reason": "no_relations",
        "counts": {"verified": 0, "partial": 0, "pending": 0},
        "edge_ids": [],
    }
    overview = service._compute_evidence_overview(
        [
            type("Edge", (), {"edge_id": "E1", "evidence_status": "已核验"})(),
            type("Edge", (), {"edge_id": "E2", "evidence_status": "待补充"})(),
        ]
    )
    assert overview["status"] == "待补充"
    assert overview["counts"] == {"verified": 1, "partial": 0, "pending": 1}


def test_symmetric_relation_is_reachable_from_both_endpoints(seeded_graph):
    seeded_graph.add(
        KnowledgeEdge(
            edge_id="E004",
            source_id="CN05",
            target_id="DS04",
            relation_type="contrast",
            mechanism="测试对比",
            abc_grade="B",
            boundary_note="",
            evidence_status="已核验",
            evidence_summary="测试证据",
            evidence_detail={"book_title": "测试", "edition": "1", "chapter": "1", "pages": "1"},
        )
    )
    seeded_graph.commit()
    service = GraphService(seeded_graph)
    for node_id in ("CN05", "DS04"):
        result = service.get_subgraph(SubgraphQuery(node_id=node_id, hops=1), "")
        assert {node.node_id for node in result.nodes} >= {"CN05", "DS04"}
        assert result.edges[-1].display_mode == "symmetric"


def test_invalid_combination_and_limit_are_rejected(seeded_graph):
    service = GraphService(seeded_graph)
    from common.errors import AppException

    with pytest.raises(AppException) as invalid:
        service.get_subgraph(SubgraphQuery(node_id="CO03", q="TLB"), "")
    assert invalid.value.status_code == 422

    for index in range(61):
        seeded_graph.add(
            KnowledgeNode(
                node_id=f"DS{100 + index}",
                course_code="DS",
                title=f"扩展节点{index}",
                chapter_scope="测试",
                description="测试",
                aliases=[],
                scope_tags=[],
            )
        )
        seeded_graph.add(
            KnowledgeEdge(
                edge_id=f"E{1000 + index}",
                source_id="DS04",
                target_id=f"DS{100 + index}",
                relation_type="implements",
                mechanism="测试",
                abc_grade="C",
                boundary_note="",
                evidence_status="待补充",
                evidence_summary="测试",
                evidence_detail=None,
            )
        )
    seeded_graph.commit()
    with pytest.raises(AppException) as limited:
        service.get_subgraph(SubgraphQuery(node_id="DS04", hops=1), "")
    assert limited.value.status_code == 422
    assert limited.value.details == {"reason": "subgraph_limit"}


def test_missing_graph_resources_use_not_found(client, seeded_graph):
    _login(client, seeded_graph)
    assert client.get("/nodes/INVALID").json()["code"] == "NOT_FOUND"
    assert client.get("/edges/INVALID").json()["code"] == "NOT_FOUND"


def test_graph_query_validation_returns_unified_422(client, seeded_graph):
    _login(client, seeded_graph)
    invalid_relation = client.get("/graph/subgraph?relation_type=unknown")
    assert invalid_relation.status_code == 422
    assert invalid_relation.json()["code"] == "VALIDATION_ERROR"

    invalid_q = client.get("/graph/subgraph?q=!&hops=1")
    assert invalid_q.status_code == 422
    assert invalid_q.json()["code"] == "VALIDATION_ERROR"

    invalid_overview = client.get("/graph/subgraph?hops=1")
    assert invalid_overview.status_code == 422
    assert invalid_overview.json()["code"] == "VALIDATION_ERROR"
