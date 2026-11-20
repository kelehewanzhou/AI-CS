"""Retention boundaries, approved scope, foreign keys and transaction safety."""
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select, text

from auth.models import Session as UserSession, User
from cli.cleanup import build_plan, digest, execute_plan
from exercise.models import ExerciseAttempt
from learning.models import LearningEvent
from qa.models import QARecord
from test_learning import _seed_learning_content


def qa(at):
    return QARecord(question_text="private question", answer_text="private answer", status="not_covered",
                    reason="test", used_node_ids=[], used_edge_ids=[], uncertainty_flag=True,
                    boundary_note="", actor_key="a" * 64, request_id="b" * 32, created_at=at)


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_qa_preview_is_read_only_and_boundary_is_exact(db_session, tmp_path):
    now = datetime.now(timezone.utc) - timedelta(seconds=1)
    cutoff = now - timedelta(days=90)
    old, boundary, fresh = qa(cutoff - timedelta(seconds=1)), qa(cutoff), qa(cutoff + timedelta(seconds=1))
    db_session.add_all([old, boundary, fresh])
    db_session.commit()
    plan = build_plan(db_session, "qa", as_of=now)
    assert plan["rows"]["qa_records"] == [old.record_id, boundary.record_id]
    assert count(db_session, QARecord) == 3
    db_session.rollback()
    log = tmp_path / "audit.jsonl"
    with pytest.raises(ValueError, match="SHA256"):
        execute_plan(db_session, plan, "wrong", approval="approved", audit_log=log)
    execute_plan(db_session, plan, digest(plan), approval="approval-123", audit_log=log)
    assert count(db_session, QARecord) == 1
    entries = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [entry["status"] for entry in entries] == ["pending", "succeeded"]
    assert "private" not in log.read_text(encoding="utf-8")


def test_users_cleanup_removes_only_approved_users_and_all_dependencies(db_session, db_engine, tmp_path):
    _seed_learning_content(db_session)
    db_session.execute(text("PRAGMA foreign_keys=ON"))
    now = datetime.now(timezone.utc) - timedelta(seconds=1)
    end = (now - timedelta(days=181)).date().isoformat()
    users = [User(username=name, role="student", password_hash="unused", created_at=now - timedelta(days=200))
             for name in ("approved_user", "preserved_user")]
    db_session.add_all(users)
    db_session.flush()
    ids = [str(user.user_id) for user in users]
    for user in users:
        db_session.add_all([
            UserSession(user_id=user.user_id, token_hash=uuid4().hex * 2, expires_at=now),
            LearningEvent(user_id=user.user_id, event_type="view_node", node_id="CO03"),
            ExerciseAttempt(user_id=user.user_id, question_id="Q001", client_submission_id=uuid4(),
                            answer="A", is_correct=True, is_evaluation=True),
        ])
    db_session.add(qa(now))
    db_session.commit()
    plan = build_plan(db_session, "users", as_of=now, user_ids=[ids[0]], trial_end=end)
    assert plan["counts"] == {"sessions": 1, "learning_events": 1, "exercise_attempts": 1, "users": 1}
    db_session.rollback()
    def fail_parent_delete(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("DELETE FROM users"):
            raise RuntimeError("parent deletion failed after child deletions")

    event.listen(db_engine, "before_cursor_execute", fail_parent_delete)
    try:
        with pytest.raises(RuntimeError):
            execute_plan(db_session, plan, digest(plan), approval="approved-list", audit_log=tmp_path / "failed.jsonl")
    finally:
        event.remove(db_engine, "before_cursor_execute", fail_parent_delete)
    for model in (User, UserSession, LearningEvent, ExerciseAttempt):
        assert count(db_session, model) == 2
    db_session.rollback()
    execute_plan(db_session, plan, digest(plan), approval="approved-list", audit_log=tmp_path / "audit.jsonl")
    for model in (User, UserSession, LearningEvent, ExerciseAttempt, QARecord):
        assert count(db_session, model) == 1
    assert db_session.scalar(select(User.username)) == "preserved_user"


def test_personal_retention_guard_and_new_accounts(db_session):
    now = datetime.now(timezone.utc) - timedelta(seconds=1)
    user = User(username="new_account", role="student", password_hash="unused", created_at=now)
    db_session.add(user)
    db_session.commit()
    ids = [str(user.user_id)]
    with pytest.raises(ValueError, match="180"):
        build_plan(db_session, "users", as_of=now, user_ids=ids, trial_end=(now - timedelta(days=180)).date().isoformat())
    with pytest.raises(ValueError, match="试点结束后创建"):
        build_plan(db_session, "users", as_of=now, user_ids=ids, trial_end=(now - timedelta(days=200)).date().isoformat())
    with pytest.raises(ValueError, match="不存在"):
        build_plan(db_session, "users", as_of=now, user_ids=[str(uuid4())], trial_end="2020-01-01")
    with pytest.raises(ValueError, match="未来"):
        build_plan(db_session, "qa", as_of=now + timedelta(days=1))


def test_stale_plan_and_delete_failure_leave_data_intact(db_session, db_engine, tmp_path):
    now = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.add(qa(now - timedelta(days=100)))
    db_session.commit()
    plan = build_plan(db_session, "qa", as_of=now)
    db_session.rollback()
    db_session.add(qa(now - timedelta(days=100)))
    db_session.commit()
    log = tmp_path / "audit.jsonl"
    with pytest.raises(ValueError, match="变化"):
        execute_plan(db_session, plan, digest(plan), approval="approved", audit_log=log)
    assert count(db_session, QARecord) == 2
    plan = build_plan(db_session, "qa", as_of=now)
    db_session.rollback()

    def fail_delete(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("DELETE"):
            raise RuntimeError("injected failure")

    event.listen(db_engine, "before_cursor_execute", fail_delete)
    try:
        with pytest.raises(RuntimeError):
            execute_plan(db_session, plan, digest(plan), approval="approved", audit_log=log)
    finally:
        event.remove(db_engine, "before_cursor_execute", fail_delete)
    assert count(db_session, QARecord) == 2
    assert json.loads(log.read_text(encoding="utf-8").splitlines()[-1])["status"] == "failed"


def test_cli_preview_confirmation_and_private_plan(db_session, db_engine, tmp_path, monkeypatch, capsys):
    from cli import cleanup

    monkeypatch.setattr(cleanup, "engine", db_engine)
    db_session.add(qa(datetime.now(timezone.utc) - timedelta(days=100)))
    db_session.commit()
    plan_file, log = tmp_path / "plan.json", tmp_path / "audit.jsonl"
    assert cleanup.main(["preview", "qa", "--plan", str(plan_file)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "preview" and output["counts"] == {"qa_records": 1}
    assert "private" not in plan_file.read_text(encoding="utf-8")
    assert count(db_session, QARecord) == 1
    db_session.rollback()
    assert cleanup.main(["execute", "--plan", str(plan_file), "--confirm", output["sha256"],
                         "--approval", "approved", "--audit-log", str(log)]) == 0
    assert count(db_session, QARecord) == 0


def test_trial_retention_boundary_uses_end_of_shanghai_day(db_session):
    from cli.cleanup import SHANGHAI

    user = User(username="old_account", role="student", password_hash="unused",
                created_at=datetime(2019, 1, 1, tzinfo=timezone.utc))
    db_session.add(user)
    db_session.commit()
    due = datetime(2020, 1, 2, tzinfo=SHANGHAI) + timedelta(days=180)
    arguments = dict(user_ids=[str(user.user_id)], trial_end="2020-01-01")
    with pytest.raises(ValueError, match="180"):
        build_plan(db_session, "users", as_of=due - timedelta(microseconds=1), **arguments)
    plan = build_plan(db_session, "users", as_of=due, **arguments)
    assert plan["counts"]["users"] == 1
