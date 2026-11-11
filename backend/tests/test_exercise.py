"""Task 5 exercise API, judging, idempotency, and isolation tests."""

from __future__ import annotations

import concurrent.futures
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from auth.models import User
from auth.service import ph
from common.database import Base
from exercise.models import Exercise, ExerciseAttempt, ExerciseRelatedNode
from exercise.service import ExerciseService
from graph.models import Course, KnowledgeNode


ORIGIN = "http://localhost:3000"
QUESTION = "Q001"


def _create_user(db_session, username: str = "exerciseuser") -> User:
    user = User(
        username=username,
        password_hash=ph.hash("password123"),
        role="student",
        must_change_password=False,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _seed_exercises(db_session) -> None:
    db_session.add(
        Course(course_code="CO", name="组成原理", textbook_info="")
    )
    db_session.add(
        KnowledgeNode(
            node_id="CO03",
            course_code="CO",
            title="虚拟内存访问",
            chapter_scope="第3章",
            description="地址转换",
            aliases=[],
            scope_tags=[],
        )
    )
    db_session.add_all(
        [
            Exercise(
                question_id=QUESTION,
                type="choice",
                content="TLB的主要作用是什么？",
                options=[
                    {"key": "A", "text": "加速地址转换"},
                    {"key": "B", "text": "扩大物理内存"},
                ],
                answer_key="A",
                difficulty=1,
            ),
            Exercise(
                question_id="Q006",
                type="judge",
                content="TLB用于缓存地址转换结果。",
                options=None,
                answer_key=True,
                difficulty=1,
            ),
        ]
    )
    db_session.add_all(
        [
            ExerciseRelatedNode(question_id=QUESTION, node_id="CO03"),
            ExerciseRelatedNode(question_id="Q006", node_id="CO03"),
        ]
    )
    db_session.commit()


def _login(client, db_session, username: str = "exerciseuser") -> User:
    user = _create_user(db_session, username)
    response = client.post(
        "/auth/login",
        json={"username": username, "password": "password123"},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200
    return user


def _submit(client, submission_id: uuid.UUID, answer="A", question_id=QUESTION):
    return client.post(
        "/exercises/attempts",
        json={
            "question_id": question_id,
            "answer": answer,
            "client_submission_id": str(submission_id),
        },
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )


def test_list_returns_student_view_and_node_intersection(client, db_session):
    _seed_exercises(db_session)
    _login(client, db_session)

    response = client.get("/exercises?node_id=CO03")

    assert response.status_code == 200
    body = response.json()
    assert [item["question_id"] for item in body["data"]["items"]] == ["Q001", "Q006"]
    assert body["data"]["items"][0]["related_node_ids"] == ["CO03"]
    assert all("answer_key" not in item for item in body["data"]["items"])


def test_first_submission_idempotency_conflict_and_reevaluation(client, db_session):
    _seed_exercises(db_session)
    _login(client, db_session)
    submission_id = uuid.uuid4()

    first = _submit(client, submission_id, " a ")
    retry = _submit(client, submission_id, "A")
    conflict = _submit(client, submission_id, "B")
    redo = _submit(client, uuid.uuid4(), "B")

    assert first.status_code == 201
    assert first.json()["data"]["answer"] == "A"
    assert first.json()["data"]["is_correct"] is True
    assert first.json()["data"]["is_evaluation"] is True
    assert first.json()["data"]["feedback"] == "本次回答正确"
    assert retry.status_code == 200
    assert retry.json()["data"]["attempt_id"] == first.json()["data"]["attempt_id"]
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "CONFLICT"
    assert redo.status_code == 201
    assert redo.json()["data"]["is_correct"] is False
    assert redo.json()["data"]["is_evaluation"] is False
    assert redo.json()["data"]["feedback"] == "本次回答有误，请复习关联知识节点"
    assert db_session.query(ExerciseAttempt).count() == 2


def test_submission_id_conflict_with_different_question_is_409(client, db_session):
    _seed_exercises(db_session)
    _login(client, db_session)
    submission_id = uuid.uuid4()

    assert _submit(client, submission_id, "A", QUESTION).status_code == 201
    response = _submit(client, submission_id, True, "Q006")

    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"


def test_attempt_history_is_private_and_sorted(client, db_session):
    _seed_exercises(db_session)
    _login(client, db_session, "historyuser")
    _submit(client, uuid.uuid4(), "A")
    _submit(client, uuid.uuid4(), "B")

    response = client.get("/exercises/attempts?question_id=Q001")

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert len(items) == 2
    assert items[0]["submitted_at"] >= items[1]["submitted_at"]
    assert all("answer_key" not in item["question"] for item in items)


def test_judge_requires_real_boolean_and_uuid_validation(client, db_session):
    _seed_exercises(db_session)
    _login(client, db_session)

    accepted = _submit(client, uuid.uuid4(), True, "Q006")
    string_answer = _submit(client, uuid.uuid4(), "true", "Q006")
    numeric_answer = _submit(client, uuid.uuid4(), 1, "Q006")
    invalid_uuid = client.post(
        "/exercises/attempts",
        json={"question_id": QUESTION, "answer": "A", "client_submission_id": "bad"},
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )

    assert accepted.status_code == 201
    assert accepted.json()["data"]["is_correct"] is True
    assert string_answer.status_code == numeric_answer.status_code == 422
    assert string_answer.json()["code"] == numeric_answer.json()["code"] == "VALIDATION_ERROR"
    assert invalid_uuid.status_code == 422


def test_concurrent_submissions_only_have_one_evaluation(tmp_path, db_session):
    _seed_exercises(db_session)
    user = _create_user(db_session, "concurrentuser")
    user_id = user.user_id
    username = user.username
    password_hash = user.password_hash
    role = user.role
    db_session.close()

    database_path = tmp_path / "exercise-concurrency.sqlite"
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    setup = factory()
    setup.add(
        User(
            user_id=user_id,
            username=username,
            password_hash=password_hash,
            role=role,
            must_change_password=False,
        )
    )
    setup.add(
        Exercise(
            question_id=QUESTION,
            type="choice",
            content="test",
            options=[{"key": "A", "text": "A"}, {"key": "B", "text": "B"}],
            answer_key="A",
            difficulty=1,
        )
    )
    setup.commit()
    setup.close()

    def submit(index: int):
        session = factory()
        try:
            return ExerciseService(session).submit_attempt(
                user_id, QUESTION, "A", uuid.uuid4()
            )[0].is_evaluation
        finally:
            session.close()

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(submit, range(10)))
        assert results.count(True) == 1
        assert results.count(False) == 9
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
