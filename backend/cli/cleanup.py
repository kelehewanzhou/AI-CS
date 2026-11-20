"""Preview and execute approved retention cleanup with a frozen, checked plan."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from auth.models import Session as UserSession, User
from common.database import engine
from exercise.models import ExerciseAttempt
from learning.models import LearningEvent
from qa.models import QARecord

SHANGHAI = timezone(timedelta(hours=8))
PERSONAL_TABLES = ((UserSession, "session_id"), (LearningEvent, "event_id"),
                   (ExerciseAttempt, "attempt_id"), (User, "user_id"))


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("时间必须包含时区")
    return as_utc(parsed)


def digest(plan: dict) -> str:
    return hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def build_plan(db: Session, kind: str, *, as_of: datetime,
               user_ids: list[str] | None = None, trial_end: str | None = None) -> dict:
    as_of = as_utc(as_of)
    if as_of > datetime.now(timezone.utc):
        raise ValueError("清理基准时间不能在未来")
    plan = {"version": 1, "kind": kind, "as_of": as_of.isoformat(), "rows": {}}
    if kind == "qa":
        cutoff = as_of - timedelta(days=90)
        plan["cutoff"] = cutoff.isoformat()
        plan["rows"]["qa_records"] = list(db.scalars(
            select(QARecord.record_id).where(QARecord.created_at <= cutoff).order_by(QARecord.record_id)))
    elif kind == "users":
        if not user_ids or not trial_end:
            raise ValueError("个人数据清理必须提供试点结束日期和批准的用户 UUID 名单")
        ids = sorted({UUID(value) for value in user_ids}, key=str)
        # The supplied date includes the whole final trial day in Shanghai.
        end = datetime.combine(date.fromisoformat(trial_end) + timedelta(days=1), time(), SHANGHAI)
        due = end + timedelta(days=180)
        if as_of < due:
            raise ValueError("试点结束后尚未满180天，不能清理个人数据")
        users = list(db.scalars(select(User).where(User.user_id.in_(ids)).order_by(User.user_id)))
        if len(users) != len(ids):
            raise ValueError("批准名单含不存在的用户，整次取消")
        if any(as_utc(user.created_at) >= as_utc(end) for user in users):
            raise ValueError("名单包含试点结束后创建的账号，整次取消")
        plan.update(trial_end=trial_end, due=as_utc(due).isoformat(),
                    users=[{"user_id": str(user.user_id), "username": user.username} for user in users])
        for model, key in PERSONAL_TABLES:
            column = getattr(model, key)
            plan["rows"][model.__tablename__] = [str(value) if isinstance(value, UUID) else value for value in
                db.scalars(select(column).where(model.user_id.in_(ids)).order_by(column))]
    else:
        raise ValueError("未知清理类型")
    plan["counts"] = {table: len(ids) for table, ids in plan["rows"].items()}
    return plan


def write_private(path: Path, value: dict, *, append: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if append else os.O_EXCL)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "a" if append else "w", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def execute_plan(db: Session, plan: dict, confirmation: str, *, approval: str, audit_log: Path) -> dict:
    if not approval.strip() or confirmation != digest(plan):
        raise ValueError("必须提供批准单编号并使用预览的完整 SHA256 确认")
    if plan.get("version") != 1:
        raise ValueError("不支持的清理计划版本")
    operation = {"operation_id": str(uuid4()), "approval": approval,
                 "plan_sha256": digest(plan), "kind": plan["kind"], "counts": plan["counts"]}
    # Persist intent before any mutation. A pending entry without a final entry
    # requires operator reconciliation (e.g. a crash immediately after commit).
    write_private(audit_log, operation | {"status": "pending", "at": datetime.now(timezone.utc).isoformat()}, append=True)
    try:
        with db.begin():
            if db.get_bind().dialect.name == "postgresql":
                db.execute(text("SET LOCAL lock_timeout = '5s'"))
                db.execute(text("SET LOCAL statement_timeout = '60s'"))
                tables = "qa_records" if plan["kind"] == "qa" else "users, sessions, learning_events, exercise_attempts"
                db.execute(text(f"LOCK TABLE {tables} IN SHARE ROW EXCLUSIVE MODE"))
            current = build_plan(db, plan["kind"], as_of=timestamp(plan["as_of"]),
                                 user_ids=[row["user_id"] for row in plan.get("users", [])],
                                 trial_end=plan.get("trial_end"))
            if digest(current) != confirmation:
                raise ValueError("待清理数据已变化或计划被修改，请重新预览并确认")
            targets = ((QARecord, "record_id"),) if plan["kind"] == "qa" else PERSONAL_TABLES
            for model, key in targets:
                values = current["rows"][model.__tablename__]
                if not values:
                    continue
                if key in {"user_id", "session_id"}:
                    values = [UUID(value) for value in values]
                # Bound parameter batches also support large approved lists.
                removed = 0
                for start in range(0, len(values), 500):
                    result = db.execute(delete(model).where(getattr(model, key).in_(values[start:start + 500])),
                                        execution_options={"synchronize_session": False})
                    removed += result.rowcount
                if removed != current["counts"][model.__tablename__]:
                    raise ValueError("删除行数与预览不一致，事务已取消")
    except Exception as exc:
        write_private(audit_log, operation | {"status": "failed", "error_type": type(exc).__name__,
                      "at": datetime.now(timezone.utc).isoformat()}, append=True)
        raise
    write_private(audit_log, operation | {"status": "succeeded", "at": datetime.now(timezone.utc).isoformat()}, append=True)
    return operation


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    preview = subs.add_parser("preview", help="只读预览并写入计划，不删除数据")
    preview.add_argument("kind", choices=("qa", "users"))
    preview.add_argument("--plan", type=Path, required=True)
    preview.add_argument("--trial-end", help="Asia/Shanghai 的试点最后一天，YYYY-MM-DD")
    preview.add_argument("--users-file", type=Path, help="批准用户 UUID 的 JSON 数组")
    execute = subs.add_parser("execute", help="验证计划后在单个事务内执行")
    execute.add_argument("--plan", type=Path, required=True)
    execute.add_argument("--confirm", required=True, help="预览输出的完整 SHA256")
    execute.add_argument("--approval", required=True, help="批准单编号")
    execute.add_argument("--audit-log", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        with Session(engine) as db:
            if args.command == "preview":
                ids = json.loads(args.users_file.read_text(encoding="utf-8")) if args.users_file else None
                if ids is not None and (not isinstance(ids, list) or not all(isinstance(value, str) for value in ids)):
                    raise ValueError("批准名单必须为用户 UUID 字符串数组")
                if args.kind == "qa" and (args.users_file or args.trial_end):
                    raise ValueError("问答清理不接受用户名单或试点日期")
                plan = build_plan(db, args.kind, as_of=datetime.now(timezone.utc), user_ids=ids, trial_end=args.trial_end)
                write_private(args.plan, plan)
                print(json.dumps({"mode": "preview", "plan": str(args.plan), "sha256": digest(plan),
                                  "counts": plan["counts"], "cutoff": plan.get("cutoff"),
                                  "users": plan.get("users", [])}, ensure_ascii=False))
            else:
                plan = json.loads(args.plan.read_text(encoding="utf-8"))
                result = execute_plan(db, plan, args.confirm, approval=args.approval, audit_log=args.audit_log)
                print(json.dumps({"status": "succeeded", "counts": result["counts"],
                                  "operation_id": result["operation_id"]}, ensure_ascii=False))
        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
    except Exception:
        # SQLAlchemy diagnostics can contain connection strings or personal rows.
        print("清理未能正常完成；请检查审计日志及数据库状态。若仅有pending，先核对结果再重试。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
