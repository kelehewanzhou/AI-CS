"""Real PostgreSQL/Nginx acceptance, enabled only by verify_native.py's isolated cluster."""
import copy
import json
import os
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from seed_import.service import ADVISORY_LOCK_KEY, import_seed_package
from seed_import.validator import load_and_validate

pytestmark = pytest.mark.skipif(os.environ.get("KGLEARN_NATIVE_ACCEPTANCE") != "1", reason="requires isolated native acceptance runtime")
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def migration_engine():
    engine = create_engine(os.environ["KGLEARN_TEST_MIGRATION_URL"])
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def runtime_engine():
    engine = create_engine(os.environ["DATABASE_URL"])
    yield engine
    engine.dispose()


def package_at(directory, mutate=None):
    files = {name: json.loads((ROOT / "fixtures" / f"{name}.json").read_text(encoding="utf-8")) for name in ("courses", "nodes", "edges", "exercises")}
    if mutate:
        mutate(files)
    directory.mkdir(exist_ok=True)
    paths = {}
    for name, value in files.items():
        paths[name] = directory / f"{name}.json"
        paths[name].write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return load_and_validate(paths)


@pytest.fixture
def imported(tmp_path, migration_engine):
    with migration_engine.begin() as conn:
        conn.execute(text("TRUNCATE users, sessions, courses, knowledge_nodes, knowledge_edges, exercises, exercise_related_nodes, exercise_attempts, learning_events, qa_records, import_runs RESTART IDENTITY CASCADE"))
    package = package_at(tmp_path)
    report = import_seed_package(package, db_engine=migration_engine)
    assert report.status == "succeeded", report.model_dump()
    return package, report


def test_at01_01_first_import(imported):
    assert imported[1].counts["current"] == {"courses": 4, "nodes": 5, "edges": 3, "exercises": 5, "edge_evidence": {"已核验": 1, "待补充": 1, "部分定位": 1}}


def test_at01_02_repeat_preserves_business_rows(imported, migration_engine):
    with migration_engine.connect() as conn:
        before = conn.execute(text("SELECT node_id,updated_at FROM knowledge_nodes ORDER BY node_id")).all()
    assert import_seed_package(imported[0], db_engine=migration_engine).status == "skipped"
    with migration_engine.connect() as conn:
        assert conn.execute(text("SELECT node_id,updated_at FROM knowledge_nodes ORDER BY node_id")).all() == before


def test_at01_03_mutable_update(imported, tmp_path, migration_engine):
    changed = package_at(tmp_path, lambda files: files["nodes"]["items"][0].update(description="更新后的摘要"))
    assert import_seed_package(changed, db_engine=migration_engine).status == "succeeded"
    with migration_engine.connect() as conn:
        assert conn.execute(text("SELECT description FROM knowledge_nodes WHERE node_id='CO03'")).scalar() == "更新后的摘要"


def test_at01_04_immutable_update_rolls_back(imported, tmp_path, migration_engine):
    changed = package_at(tmp_path, lambda files: files["exercises"]["items"][0].update(content="不可替换的题干"))
    report = import_seed_package(changed, db_engine=migration_engine)
    assert report.status == "failed"
    assert "IMMUTABLE_FIELD" in report.model_dump_json()
    with migration_engine.connect() as conn:
        assert conn.execute(text("SELECT content FROM exercises WHERE question_id='Q001'")).scalar() != "不可替换的题干"


def test_at01_05_soft_delete_keeps_history(imported, tmp_path, migration_engine):
    with migration_engine.begin() as conn:
        user_id = str(uuid.uuid4())
        conn.execute(text("INSERT INTO users(user_id,username,password_hash,role) VALUES(CAST(:id AS uuid),'history_user','unused','student')"), {"id": user_id})
        conn.execute(text("INSERT INTO exercise_attempts(user_id,question_id,client_submission_id,answer,is_correct,is_evaluation) VALUES(CAST(:id AS uuid),'Q001',CAST(:submission AS uuid),'\"A\"'::jsonb,true,true)"), {"id": user_id, "submission": str(uuid.uuid4())})

    def remove(files):
        files["nodes"]["items"] = [row for row in files["nodes"]["items"] if row["node_id"] != "OS03"]
        files["edges"]["items"] = [row for row in files["edges"]["items"] if "OS03" not in (row["source_id"], row["target_id"])]
        for row in files["exercises"]["items"]:
            row["related_node_ids"] = [node for node in row["related_node_ids"] if node != "OS03"]
        files["exercises"]["items"] = [row for row in files["exercises"]["items"] if row["related_node_ids"]]

    report = import_seed_package(package_at(tmp_path, remove), db_engine=migration_engine)
    assert report.status == "succeeded", report.model_dump()
    with migration_engine.connect() as conn:
        assert conn.execute(text("SELECT is_active FROM knowledge_nodes WHERE node_id='OS03'")).scalar() is False
        assert conn.execute(text("SELECT is_active FROM knowledge_edges WHERE edge_id='E002'")).scalar() is False
        assert conn.execute(text("SELECT count(*) FROM exercise_attempts")).scalar() == 1


@pytest.mark.parametrize("number,mutate,error", [
    (6, lambda files: files["edges"]["items"][0].update(target_id="OS99"), "MISSING_REFERENCE"),
    (7, lambda files: files["nodes"]["items"][1].update(aliases=["TLB"]), "ALIAS_CONFLICT"),
    (8, lambda files: files["edges"]["items"][0].update(target_id="CO03"), "SELF_LOOP"),
])
def test_at01_06_to_08_invalid_package_is_atomic(imported, tmp_path, migration_engine, number, mutate, error):
    report = import_seed_package(package_at(tmp_path, mutate), db_engine=migration_engine)
    assert report.status == "failed" and error in report.model_dump_json()
    with migration_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM knowledge_nodes WHERE is_active")).scalar() == 5


def test_at01_09_concurrent_import_lock(imported, migration_engine):
    with migration_engine.connect() as lock:
        lock.execute(text("SELECT pg_advisory_lock(:key)"), {"key": ADVISORY_LOCK_KEY})
        lock.commit()
        try:
            report = import_seed_package(imported[0], db_engine=migration_engine)
            assert report.status == "failed" and "IMPORT_LOCKED" in report.model_dump_json()
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": ADVISORY_LOCK_KEY})
            lock.commit()


def test_at01_10_proxy_ready_and_request_id(imported):
    response = httpx.get(os.environ["KGLEARN_TEST_HTTP_URL"] + "/api/v1/health/ready", headers={"X-Request-ID": "a" * 32})
    assert response.status_code == 200
    assert response.json()["request_id"] == response.headers["x-request-id"] != "a" * 32


def test_runtime_privileges(runtime_engine, imported):
    for sql in ("CREATE TABLE forbidden(id int)", "UPDATE knowledge_nodes SET description='forbidden'", "DELETE FROM exercise_attempts", "UPDATE exercise_attempts SET is_correct=false", "UPDATE users SET role='teacher'"):
        with runtime_engine.connect() as conn:
            with pytest.raises(DBAPIError):
                conn.execute(text(sql))
            conn.rollback()


def test_at09_student_teacher_paths_over_real_nginx(imported, migration_engine):
    from auth.service import ph

    temporary, password = "initial-test-123456", "changed-test-123456"
    with migration_engine.begin() as conn:
        for username, role in (("accept_student", "student"), ("accept_teacher", "teacher"), ("other_student", "student")):
            conn.execute(text("INSERT INTO users(user_id,username,password_hash,role,must_change_password) VALUES(CAST(:id AS uuid),:username,:password,:role,true)"), {"id": str(uuid.uuid4()), "username": username, "password": ph.hash(temporary), "role": role})
    base = os.environ["KGLEARN_TEST_HTTP_URL"]
    with httpx.Client(base_url=base + "/api/v1/", headers={"Origin": base}) as student:
        assert httpx.get(base + "/login/").status_code == 200
        login = student.post("auth/login", json={"username": "accept_student", "password": temporary})
        assert login.status_code == 200 and login.json()["data"]["user"]["must_change_password"]
        assert student.get("graph/subgraph?course_code=CO").status_code == 403
        assert student.post("auth/password", json={"current_password": temporary, "new_password": password}).status_code == 200
        assert student.get("auth/me").status_code == 401
        assert student.post("auth/login", json={"username": "accept_student", "password": password}).status_code == 200
        assert student.get("graph/subgraph?course_code=CO").status_code == 200
        graph = student.get("graph/subgraph?node_id=CO03&hops=1").json()["data"]
        assert {row["node_id"] for row in graph["nodes"]} == {"CO03", "OS02"}
        assert len(student.get("graph/subgraph?node_id=CO03&hops=2").json()["data"]["nodes"]) == 3
        assert [row["edge_id"] for row in student.get("graph/subgraph?course_code=CO&hops=2&relation_type=implements&evidence_status=已核验").json()["data"]["edges"]] == ["E001"]
        assert student.get("nodes/CO03").status_code == 200
        assert student.get("edges/E001").status_code == 200
        assert student.post("learning/events", json={"event_type": "view_node", "resource_type": "node", "resource_id": "CO03"}).status_code == 201
        assert student.post("learning/events", json={"event_type": "start_exercise", "resource_type": "exercise", "resource_id": "Q001"}).status_code == 201
        exercise = student.get("exercises?node_id=CO03").json()["data"]["items"][0]
        assert "answer_key" not in exercise
        submission = {"question_id": "Q001", "answer": "A", "client_submission_id": str(uuid.uuid4())}
        result = student.post("exercises/attempts", json=submission)
        assert result.status_code == 201 and result.json()["data"]["is_correct"]
        assert student.post("exercises/attempts", json=submission).status_code == 200
        assert student.get("exercises/attempts").json()["data"]["total"] == 1
        assert student.get("learning/events").status_code == 200
        assert student.get("learning/status").status_code == 200
        assert student.get("learning/summary").status_code == 403
        assert student.post("ask", json={"question": "什么是TLB"}).json()["data"]["status"] == "answered"
        assert student.post("ask", json={"question": "页表是什么"}).json()["data"]["status"] == "insufficient_evidence"
        assert student.post("ask", json={"question": "量子纠缠是什么"}).json()["data"]["status"] == "not_covered"
        assert student.post("auth/logout", json={}).status_code == 200
        assert student.get("auth/me").status_code == 401
    with httpx.Client(base_url=base + "/api/v1/", headers={"Origin": base}) as teacher:
        assert teacher.post("auth/login", json={"username": "accept_teacher", "password": temporary}).status_code == 200
        assert teacher.post("auth/password", json={"current_password": temporary, "new_password": password}).status_code == 200
        assert teacher.post("auth/login", json={"username": "accept_teacher", "password": password}).status_code == 200
        assert httpx.get(base + "/teacher/acceptance/").status_code == 200
        summary = teacher.get("learning/summary")
        assert summary.status_code == 200
        assert "evidence" in summary.text
        assert teacher.post("auth/logout", json={}).status_code == 200
    for page in ("/node/?id=CO03", "/edge/?id=E001", "/exercise/?id=Q001", "/learning/", "/change-password/"):
        assert httpx.get(base + page).status_code == 200


def test_nginx_post_guards_and_login_rate_limit():
    base = os.environ["KGLEARN_TEST_HTTP_URL"]
    for headers in ({}, {"Origin": "https://untrusted.invalid"}):
        response = httpx.post(base + "/api/v1/auth/logout", json={}, headers=headers)
        assert response.status_code == 403 and response.json()["code"] == "FORBIDDEN"
    response = httpx.post(base + "/api/v1/auth/logout", content="{}", headers={"Origin": base, "Content-Type": "text/plain"})
    assert response.status_code == 422 and response.json()["code"] == "VALIDATION_ERROR"
    responses = [httpx.post(base + "/api/v1/auth/login", json={"username": "unknown", "password": "wrong"}, headers={"Origin": base}) for _ in range(10)]
    assert any(response.status_code == 429 for response in responses)
    for response in responses:
        assert response.status_code in (401, 429)
        assert response.json()["request_id"] == response.headers["x-request-id"]
        if response.status_code == 429:
            assert response.json()["code"] == "RATE_LIMITED" and response.headers["retry-after"] == "12"
    assert httpx.get(base + "/health/ready").status_code == 200
