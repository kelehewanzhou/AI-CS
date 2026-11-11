"""Task 6 learning events, state rules, cursor, summary, and composition tests."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from auth.models import User
from auth.service import AuthService, ph
from exercise.models import Exercise, ExerciseRelatedNode
from graph.models import Course, ImportRun, KnowledgeEdge, KnowledgeNode


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
ORIGIN = "http://localhost:3000"


def _load(name: str) -> list[dict]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["items"]


def _seed_learning_content(db_session, *, with_import_run: bool = False) -> None:
    db_session.add_all([Course(**item) for item in _load("courses")])
    db_session.add_all([KnowledgeNode(**item) for item in _load("nodes")])
    db_session.add_all([KnowledgeEdge(**item) for item in _load("edges")])
    for item in _load("exercises"):
        exercise = Exercise(
            question_id=item["question_id"],
            type=item["type"],
            content=item["content"],
            options=item["options"],
            answer_key=item["answer_key"],
            difficulty=item["difficulty"],
        )
        db_session.add(exercise)
        db_session.add_all(
            ExerciseRelatedNode(question_id=item["question_id"], node_id=node_id)
            for node_id in item["related_node_ids"]
        )
    if with_import_run:
        db_session.add(
            ImportRun(
                checksum="a" * 64,
                source_files={},
                status="succeeded",
                finished_at=datetime.now(timezone.utc),
                counts={
                    "current": {
                        "courses": 4,
                        "nodes": 5,
                        "edges": 3,
                        "exercises": 5,
                    }
                },
            )
        )
    db_session.commit()


def _create_user(db_session, username: str, role: str = "student") -> User:
    user = User(
        username=username,
        password_hash=ph.hash("password123"),
        role=role,
        must_change_password=False,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _login(client, db_session, username: str, role: str = "student") -> User:
    user = _create_user(db_session, username, role)
    response = client.post(
        "/auth/login",
        json={"username": username, "password": "password123"},
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )
    assert response.status_code == 200
    return user


def _submit(client, question_id: str, answer: str, submission_id: uuid.UUID | None = None):
    return client.post(
        "/exercises/attempts",
        json={
            "question_id": question_id,
            "answer": answer,
            "client_submission_id": str(submission_id or uuid.uuid4()),
        },
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )


def _state(client, node_id: str = "CO03") -> dict:
    response = client.get(f"/learning/status?node_id={node_id}")
    assert response.status_code == 200
    return response.json()["data"]["items"][0]


def test_learning_event_contract_and_state_priority(client, db_session):
    _seed_learning_content(db_session)
    _login(client, db_session, "learning01")

    assert _state(client)["state"] == "未学习"
    assert _state(client)["reason"] == "no_activity"

    viewed = client.post(
        "/learning/events",
        json={"event_type": "view_node", "resource_type": "node", "resource_id": "CO03"},
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )
    assert viewed.status_code == 201
    assert viewed.json()["data"]["resource_type"] == "node"
    assert _state(client)["state"] == "学习中"

    started = client.post(
        "/learning/events",
        json={"event_type": "start_exercise", "resource_type": "exercise", "resource_id": "Q001"},
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )
    assert started.status_code == 201
    assert started.json()["data"]["resource_type"] == "exercise"

    invalid_pair = client.post(
        "/learning/events",
        json={"event_type": "view_node", "resource_type": "edge", "resource_id": "E001"},
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )
    assert invalid_pair.status_code == 422
    assert invalid_pair.json()["code"] == "VALIDATION_ERROR"

    removed_event = client.post(
        "/learning/events",
        json={"event_type": "submit_exercise", "resource_type": "exercise", "resource_id": "Q001"},
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )
    assert removed_event.status_code == 422

    edge_only_user = _create_user(db_session, "edgeonly01")
    edge_token = AuthService(db_session).login("edgeonly01", "password123")[1]
    client.cookies.set("kglearn_session", edge_token)
    edge_event = client.post(
        "/learning/events",
        json={"event_type": "view_edge", "resource_type": "edge", "resource_id": "E001"},
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )
    assert edge_event.status_code == 201
    assert _state(client)["state"] == "未学习"
    assert edge_only_user.user_id != uuid.UUID(int=0)

    start_only = _create_user(db_session, "startonly01")
    start_token = AuthService(db_session).login(start_only.username, "password123")[1]
    client.cookies.set("kglearn_session", start_token)
    started_only = client.post(
        "/learning/events",
        json={"event_type": "start_exercise", "resource_type": "exercise", "resource_id": "Q001"},
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )
    assert started_only.status_code == 201
    assert _state(client)["reason"] == "viewed_or_started"

    no_exercise = _create_user(db_session, "noexercise01")
    no_exercise_token = AuthService(db_session).login(no_exercise.username, "password123")[1]
    client.cookies.set("kglearn_session", no_exercise_token)
    viewed_isolated = client.post(
        "/learning/events",
        json={"event_type": "view_node", "resource_type": "node", "resource_id": "DS04"},
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )
    assert viewed_isolated.status_code == 201
    isolated_state = _state(client, "DS04")
    assert isolated_state["state"] == "学习中"
    assert isolated_state["reason"] == "no_exercises"
    assert isolated_state["can_evaluate_mastery"] is False


def test_learning_state_mastery_boundary_and_latest_wrong(client, db_session):
    _seed_learning_content(db_session)

    _login(client, db_session, "mastery01")
    for question_id in ("Q001", "Q002", "Q003"):
        assert _submit(client, question_id, "A").status_code == 201
    mastery = _state(client)
    assert mastery["state"] == "已掌握"
    assert mastery["reason"] == "mastery_rule_met"
    assert mastery["evaluation_count"] == 3
    assert mastery["recent_accuracy"] == 1.0
    assert mastery["latest_evaluation_correct"] is True
    both_nodes = client.get("/learning/status?node_id=CO03&node_id=OS02")
    assert [item["evaluation_count"] for item in both_nodes.json()["data"]["items"]] == [3, 3]

    user = _create_user(db_session, "boundary01")
    token = AuthService(db_session).login(user.username, "password123")[1]
    client.cookies.set("kglearn_session", token)
    for question_id, answer in zip(("Q001", "Q002", "Q003", "Q004", "Q005"), ("B", "A", "A", "A", "A")):
        assert _submit(client, question_id, answer).status_code == 201
    boundary = _state(client)
    assert boundary["state"] == "已掌握"
    assert boundary["recent_accuracy"] == 0.8
    assert 4 * 5 >= 5 * 4
    assert not (3 * 5 >= 4 * 4)

    user = _create_user(db_session, "latestwrong01")
    token = AuthService(db_session).login(user.username, "password123")[1]
    client.cookies.set("kglearn_session", token)
    for question_id, answer in zip(("Q001", "Q002", "Q003", "Q004", "Q005"), ("A", "A", "A", "A", "B")):
        assert _submit(client, question_id, answer).status_code == 201
    latest_wrong = _state(client)
    assert latest_wrong["state"] == "练习中"
    assert latest_wrong["reason"] == "latest_evaluation_wrong"
    assert latest_wrong["recent_accuracy"] == 0.8

    user = _create_user(db_session, "belowthreshold01")
    token = AuthService(db_session).login(user.username, "password123")[1]
    client.cookies.set("kglearn_session", token)
    for question_id, answer in zip(("Q001", "Q002", "Q003", "Q004"), ("A", "A", "A", "B")):
        assert _submit(client, question_id, answer).status_code == 201
    below_threshold = _state(client)
    assert below_threshold["state"] == "练习中"
    assert below_threshold["reason"] == "accuracy_below_threshold"
    assert below_threshold["recent_accuracy"] == 0.75


def test_learning_state_recent_window_and_same_question_redo(client, db_session):
    _seed_learning_content(db_session)
    db_session.add(
        Exercise(
            question_id="Q006",
            type="choice",
            content="补充测试题",
            options=[{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}],
            answer_key="A",
            difficulty=1,
        )
    )
    db_session.add(ExerciseRelatedNode(question_id="Q006", node_id="CO03"))
    db_session.commit()
    user = _login(client, db_session, "window01")
    for question_id, answer in zip(
        ("Q001", "Q002", "Q003", "Q004", "Q005", "Q006", "Q001"),
        ("B", "A", "A", "A", "A", "A", "A"),
    ):
        assert _submit(client, question_id, answer).status_code == 201
    state = _state(client)
    assert state["state"] == "已掌握"
    assert state["evaluation_count"] == 6
    assert state["recent_window_size"] == 5
    assert state["recent_accuracy"] == 1.0

    submission_id = uuid.uuid4()
    first = _submit(client, "Q001", "A", submission_id)
    retry = _submit(client, "Q001", "A", submission_id)
    retry_again = _submit(client, "Q001", "A", submission_id)
    assert first.status_code == 201
    assert retry.status_code == 200
    assert retry_again.status_code == 200
    assert retry.json()["data"]["attempt_id"] == first.json()["data"]["attempt_id"]
    assert user.user_id is not None

    redo_user = _create_user(db_session, "redo01")
    redo_token = AuthService(db_session).login(redo_user.username, "password123")[1]
    client.cookies.set("kglearn_session", redo_token)
    for _ in range(3):
        assert _submit(client, "Q001", "A").status_code == 201
    redo_state = _state(client)
    assert redo_state["total_attempt_count"] == 3
    assert redo_state["evaluation_count"] == 1
    assert redo_state["state"] == "练习中"


def test_learning_event_cursor_is_signed_and_bound(client, db_session):
    _seed_learning_content(db_session)
    _login(client, db_session, "cursor01")
    for _ in range(30):
        response = client.post(
            "/learning/events",
            json={"event_type": "view_node", "resource_type": "node", "resource_id": "CO03"},
            headers={"Origin": ORIGIN, "Content-Type": "application/json"},
        )
        assert response.status_code == 201

    first = client.get("/learning/events?limit=20")
    assert first.status_code == 200
    assert len(first.json()["data"]["items"]) == 20
    cursor = first.json()["data"]["next_cursor"]
    second = client.get(f"/learning/events?limit=20&cursor={cursor}")
    assert second.status_code == 200
    assert len(second.json()["data"]["items"]) == 10
    assert second.json()["data"]["next_cursor"] is None

    envelope = json.loads(base64.urlsafe_b64decode(cursor).decode("utf-8"))
    envelope["data"]["user_id"] = str(uuid.uuid4())
    tampered = base64.urlsafe_b64encode(json.dumps(envelope).encode("utf-8")).decode("ascii")
    bad = client.get(f"/learning/events?limit=20&cursor={tampered}")
    assert bad.status_code == 422
    assert bad.json()["code"] == "VALIDATION_ERROR"

    other_user = _create_user(db_session, "cursor02")
    other_token = AuthService(db_session).login(other_user.username, "password123")[1]
    client.cookies.set("kglearn_session", other_token)
    cross_user = client.get(f"/learning/events?limit=20&cursor={cursor}")
    assert cross_user.status_code == 422
    assert cross_user.json()["code"] == "VALIDATION_ERROR"


def test_learning_summary_permissions_and_node_composition(client, db_session):
    _seed_learning_content(db_session, with_import_run=True)
    _login(client, db_session, "summary_student")
    forbidden = client.get("/learning/summary")
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN"

    teacher = _create_user(db_session, "summary_teacher", "teacher")
    token = AuthService(db_session).login(teacher.username, "password123")[1]
    client.cookies.set("kglearn_session", token)
    summary = client.get("/learning/summary")
    assert summary.status_code == 200
    data = summary.json()["data"]
    assert data["seed_checksum"] == "a" * 64
    assert data["counts"] == {"courses": 4, "nodes": 5, "edges": 3, "exercises": 5}
    assert data["edge_evidence_counts"] == {"verified": 1, "partial": 1, "pending": 1}
    assert "user_id" not in json.dumps(data, ensure_ascii=False)

    node = client.get("/nodes/CO03")
    assert node.status_code == 200
    assert node.json()["data"]["exercise_count"] == 5
    assert node.json()["data"]["learning"]["state"] == "未学习"
