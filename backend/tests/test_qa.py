"""Task 8 / AT-07 matching, evidence, persistence, and HTTP contracts."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError

from auth.models import User
from auth.service import AuthService, ph
from common.config import settings
from graph.models import Course, KnowledgeEdge, KnowledgeNode
from main import app
from qa.models import QARecord
from qa.service import QAService


ORIGIN = {"Origin": "http://localhost:3000"}
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
RESULT_KEYS = {
    "status", "reason", "answer", "used_node_ids", "used_edge_ids",
    "uncertainty_flag", "boundary_note",
}


@pytest.fixture
def qa_context(client, db_session):
    for name, model in (("courses", Course), ("nodes", KnowledgeNode), ("edges", KnowledgeEdge)):
        items = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["items"]
        db_session.add_all(model(**item) for item in items)
    user = User(
        username="qa_student", password_hash=ph.hash("password123"),
        role="student", must_change_password=False,
    )
    db_session.add(user)
    db_session.commit()
    _, token, _ = AuthService(db_session).login("qa_student", "password123")
    client.cookies.set(settings.session_cookie_name, token)
    return user


def _ask(client, question):
    return client.post("/ask", json={"question": question}, headers=ORIGIN)


@pytest.mark.parametrize("question,status,reason", [
    ("什么是TLB", "answered", None),
    ("什么是ｔｌｂ", "answered", None),
    ("解释快表", "answered", None),
    ("TLB和虚拟内存是什么关系", "answered", None),
    ("虚拟内存与TLB的支撑关系", "answered", None),
    ("TLB和虚拟内存的对比", "not_covered", "no_direct_relation"),
    ("页表是什么", "insufficient_evidence", None),
    ("页表与虚拟内存是什么关系", "insufficient_evidence", None),
    ("图遍历与OSPF路由的前置关系", "insufficient_evidence", None),
    ("TLB和页表是什么关系", "not_covered", "no_direct_relation"),
    ("TLB、虚拟内存和页表是什么", "not_covered", "too_many_nodes"),
    ("TLB和虚拟内存的实现与前置关系", "not_covered", "ambiguous_relation"),
    ("量子纠缠是什么", "not_covered", "no_match"),
    ("most important", "not_covered", "no_match"),
], ids=[f"AT07-{index:02}" for index in range(1, 15)])
def test_at07_business_baselines(client, db_session, qa_context, question, status, reason):
    # #14 includes a real legal OS alias, rather than relying on its absence.
    if question == "most important":
        db_session.get(KnowledgeNode, "OS02").aliases = ["OS"]
        db_session.commit()
    response = _ask(client, question)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"data", "request_id"}
    assert re.fullmatch("[0-9a-f]{32}", body["request_id"])
    assert response.headers["X-Request-ID"] == body["request_id"]
    result = body["data"]
    assert set(result) == RESULT_KEYS
    assert (result["status"], result["reason"]) == (status, reason)
    assert result["uncertainty_flag"] is (status != "answered")
    if status == "answered":
        assert result["used_node_ids"] == ["CO03", "OS02"]
        assert result["used_edge_ids"] == ["E001"]
        assert "非教材原文" in result["answer"]
        label = client.get("/edges/E001").json()["data"]["display_label"]
        assert label in result["answer"]
        assert "虚拟内存 实现/支撑 TLB" not in result["answer"]
    else:
        assert result["used_node_ids"] == result["used_edge_ids"] == []
        assert result["boundary_note"]
    record = db_session.scalar(select(QARecord))
    assert record.question_text == question
    assert record.answer_text == result["answer"]
    assert record.status == status
    assert record.reason == (reason or "")
    assert record.used_node_ids == result["used_node_ids"]
    assert record.used_edge_ids == result["used_edge_ids"]
    assert record.request_id == body["request_id"]


@pytest.mark.parametrize("value", ["", " \t\n ", "字" * 501, "!!!", None, 123, True, [], {}])
def test_at07_15_invalid_questions(client, db_session, qa_context, value):
    response = _ask(client, value)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert db_session.scalar(select(func.count()).select_from(QARecord)) == 0


def test_trim_length_and_single_character_contract(client, db_session, qa_context):
    assert _ask(client, "  什么是TLB  ").json()["data"]["status"] == "answered"
    assert db_session.scalar(select(QARecord)).question_text == "什么是TLB"
    assert _ask(client, "字").status_code == 200
    assert _ask(client, " " + "字" * 500 + " ").status_code == 200
    assert client.post("/ask", json={}, headers=ORIGIN).status_code == 422
    assert client.post("/ask", json={"question": "TLB", "user_id": str(uuid4())}, headers=ORIGIN).status_code == 422


def test_at07_16_template_failure_isolated_and_private(client, db_session, qa_context, monkeypatch, caplog):
    private_question = "TLB个人内容不应进入日志"

    def fail(*args):
        raise RuntimeError(private_question)

    with monkeypatch.context() as patch:
        patch.setattr(QAService, "_render_answer", fail)
        response = _ask(client, private_question)
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert response.json()["request_id"] in caplog.text
    assert "RuntimeError" in caplog.text
    assert private_question not in caplog.text
    assert db_session.scalar(select(func.count()).select_from(QARecord)) == 0
    assert client.get("/graph/subgraph").status_code == 200
    assert _ask(client, "TLB").status_code == 200


def test_at07_17_local_database_write_failure_rolls_back(client, db_session, qa_context, caplog):
    db_session.execute(text(
        "CREATE TRIGGER reject_qa_record BEFORE INSERT ON qa_records "
        "BEGIN SELECT RAISE(ABORT, 'local qa write failure'); END"
    ))
    db_session.commit()
    private_question = "什么是TLB？这段内容不得进入日志"
    response = _ask(client, private_question)
    assert response.status_code == 503
    assert response.json()["code"] == "UNAVAILABLE"
    assert private_question not in caplog.text
    assert db_session.scalar(select(func.count()).select_from(QARecord)) == 0
    assert client.get("/graph/subgraph").status_code == 200
    db_session.execute(text("DROP TRIGGER reject_qa_record"))
    db_session.commit()
    assert _ask(client, "TLB").json()["data"]["status"] == "answered"


def test_commit_failure_does_not_return_success(client, db_session, qa_context, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(db_session, "commit", lambda: (_ for _ in ()).throw(OperationalError("commit", {}, Exception())))
        response = _ask(client, "TLB")
    assert response.status_code == 503
    assert db_session.scalar(select(func.count()).select_from(QARecord)) == 0
    assert client.get("/graph/subgraph").status_code == 200


def test_actor_key_uses_monthly_hmac_without_user_foreign_key(client, db_session, qa_context, monkeypatch):
    import qa.service as service_module

    class FixedDateTime:
        month = "203001"

        @classmethod
        def now(cls, tz):
            return datetime.strptime(cls.month, "%Y%m").replace(tzinfo=timezone.utc)

    monkeypatch.setattr(service_module, "datetime", FixedDateTime)
    for _ in range(2):
        assert _ask(client, "TLB").status_code == 200
    expected = hmac.new(
        f"{settings.session_secret_key}:203001".encode(),
        str(qa_context.user_id).encode(), hashlib.sha256,
    ).hexdigest()
    records = list(db_session.scalars(select(QARecord).order_by(QARecord.record_id)))
    assert [record.actor_key for record in records] == [expected, expected]
    assert re.fullmatch("[0-9a-f]{64}", expected)
    FixedDateTime.month = "203002"
    assert _ask(client, "TLB").status_code == 200
    assert db_session.scalars(select(QARecord).order_by(QARecord.record_id.desc())).first().actor_key != expected
    assert "user_id" not in QARecord.__table__.columns
    assert not QARecord.__table__.foreign_keys


def test_auth_origin_content_type_and_teacher_contract(client, db_session, qa_context):
    assert client.post("/ask", json={"question": "TLB"}).status_code == 403
    assert client.post("/ask", json={"question": "TLB"}, headers={"Origin": "https://invalid.example"}).status_code == 403
    assert client.post("/ask", content='{"question":"TLB"}', headers={**ORIGIN, "Content-Type": "text/plain"}).status_code == 422
    qa_context.must_change_password = True
    db_session.commit()
    assert _ask(client, "TLB").status_code == 403
    qa_context.must_change_password = False
    qa_context.role = "teacher"
    db_session.commit()
    assert _ask(client, "TLB").status_code == 200
    client.cookies.clear()
    assert _ask(client, "TLB").status_code == 401


def _node(node_id, title, aliases=()):
    return {
        "node_id": node_id, "normalized_title": QAService._normalize_text(title),
        "aliases": [{"normalized": QAService._normalize_text(alias)} for alias in aliases],
    }


def test_normalization_and_ascii_boundaries():
    qa = QAService(None)
    assert qa._normalize_text("  ＴＬＢ，\n快表！ ") == "tlb 快表"
    assert qa._normalize_text("Straße") == "strasse"
    assert qa._normalize_text("T.L.B") == "t l b"
    nodes = [_node("OS01", "操作系统", ["OS"])]
    for question in ("most important", "xos", "os2"):
        assert qa._match_nodes(qa._normalize_text(question), nodes) == []
    for question in ("OS是什么", "解释OS", "（ｏｓ）", "os_概念"):
        assert qa._match_nodes(qa._normalize_text(question), nodes)[0]["node_id"] == "OS01"


def test_matching_containment_occurrences_ranking_and_deduplication():
    qa = QAService(None)
    nodes = [_node("OS01", "内存"), _node("OS02", "虚拟内存")]
    assert [node["node_id"] for node in qa._match_nodes("虚拟内存", nodes)] == ["OS02"]
    assert [node["node_id"] for node in qa._match_nodes("虚拟内存与内存", nodes)] == ["OS02", "OS01"]
    assert len(qa._match_nodes("虚拟内存与虚拟内存", nodes)) == 1
    # All alias occurrences count; a longer alias can suppress another title.
    nodes = [_node("OS01", "内存"), _node("OS02", "存储机制", ["虚拟内存"])]
    assert [node["node_id"] for node in qa._match_nodes("虚拟内存", nodes)] == ["OS02"]
    nodes = [
        _node("OS03", "三级", ["特别长的别名", "长别名"]),
        _node("OS02", "二级"), _node("OS01", "一级"),
    ]
    assert [node["node_id"] for node in qa._match_nodes("二级 一级 长别名 特别长的别名", nodes)] == ["OS01", "OS02", "OS03"]
    # Longest alias wins even when it appears last in the alias list.
    nodes = [_node("OS01", "目标一", ["短名", "最长的别名"]), _node("OS02", "目标二", ["中等别名"])]
    assert [node["node_id"] for node in qa._match_nodes("短名 中等别名 最长的别名", nodes)] == ["OS01", "OS02"]


def test_dictionary_reloads_after_changes_and_excludes_inactive_content(client, db_session, qa_context):
    assert _ask(client, "新别名").json()["data"]["reason"] == "no_match"
    db_session.get(KnowledgeNode, "CO03").aliases = ["新别名"]
    db_session.commit()
    assert _ask(client, "新别名").json()["data"]["status"] == "answered"
    db_session.get(KnowledgeEdge, "E001").is_active = False
    db_session.commit()
    assert _ask(client, "新别名").json()["data"]["status"] == "insufficient_evidence"
    db_session.get(KnowledgeEdge, "E001").is_active = True
    db_session.get(KnowledgeNode, "OS02").is_active = False
    db_session.commit()
    assert _ask(client, "新别名").json()["data"]["status"] == "insufficient_evidence"
    db_session.get(KnowledgeNode, "CO03").is_active = False
    db_session.commit()
    assert _ask(client, "新别名").json()["data"]["reason"] == "no_match"


def test_selection_limit_relation_order_actual_references_and_boundary(client, db_session, qa_context):
    for edge_id, relation in (("E004", "contrast"), ("E005", "boundary"), ("E006", "prerequisite")):
        db_session.add(KnowledgeEdge(
            edge_id=edge_id, source_id="CO03", target_id="OS02", relation_type=relation,
            mechanism=f"说明{edge_id}", abc_grade="B", boundary_note=f"边界{edge_id}",
            evidence_status="已核验", evidence_summary="测试证据", evidence_detail={},
        ))
    db_session.commit()
    concept = _ask(client, "TLB").json()["data"]
    assert concept["used_edge_ids"] == ["E001", "E004", "E005"]
    assert "说明E006" not in concept["answer"]
    relation = _ask(client, "虚拟内存与TLB是什么关系").json()["data"]
    assert relation["used_edge_ids"] == ["E006", "E001", "E004"]
    assert relation["used_node_ids"] == ["CO03", "OS02"]
    assert relation["boundary_note"] == "边界E006 | 边界E004"
    assert "说明E005" not in relation["answer"]
    assert _ask(client, "TLB与虚拟内存的区别").json()["data"]["used_edge_ids"] == ["E004"]


def test_openapi_has_explicit_frontend_response_contract():
    operation = app.openapi()["paths"]["/ask"]["post"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/AskResponse")
    schema = app.openapi()["components"]["schemas"]["QAResponse"]
    assert set(schema["required"]) == RESULT_KEYS
    assert schema["properties"]["status"]["enum"] == ["answered", "not_covered", "insufficient_evidence"]
