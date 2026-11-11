"""Transactional PostgreSQL import lifecycle for validated seed packages."""

from __future__ import annotations

import json
import uuid
from collections import Counter
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from common.database import engine
from .validator import (
    FILE_NAMES,
    ImportErrorRecord,
    ImportReport,
    ValidatedPackage,
)


ADVISORY_LOCK_KEY = 123456789
TABLES = {
    "courses": ("courses", "course_code"),
    "nodes": ("knowledge_nodes", "node_id"),
    "edges": ("knowledge_edges", "edge_id"),
    "exercises": ("exercises", "question_id"),
}
MUTABLE_FIELDS = {
    "courses": ("name", "textbook_info"),
    "nodes": ("chapter_scope", "description", "scope_tags", "aliases"),
    "edges": (
        "mechanism",
        "abc_grade",
        "boundary_note",
        "evidence_status",
        "evidence_summary",
        "evidence_detail",
    ),
}
IMMUTABLE_FIELDS = {
    "nodes": ("course_code", "title"),
    "edges": ("source_id", "target_id", "relation_type"),
    "exercises": ("type", "content", "options", "answer_key", "difficulty"),
}
INSERT_COLUMNS = {
    "courses": ("course_code", "name", "textbook_info"),
    "nodes": (
        "node_id", "course_code", "title", "chapter_scope", "description", "aliases", "scope_tags"
    ),
    "edges": (
        "edge_id", "source_id", "target_id", "relation_type", "mechanism", "abc_grade",
        "boundary_note", "evidence_status", "evidence_summary", "evidence_detail"
    ),
    "exercises": ("question_id", "type", "content", "options", "answer_key", "difficulty"),
}


def _empty_counts() -> dict[str, Any]:
    return {
        "current": {name: 0 for name in TABLES} | {"edge_evidence": {}},
        "changes": {
            name: {"inserted": 0, "updated": 0, "retired": 0} for name in TABLES
        },
    }


def _package_counts(package: ValidatedPackage) -> dict[str, Any]:
    counts = _empty_counts()
    for name in TABLES:
        counts["current"][name] = len(package.files.get(name, {}).get("items", []))
    counts["current"]["edge_evidence"] = dict(
        Counter(edge["evidence_status"] for edge in package.files.get("edges", {}).get("items", []))
    )
    return counts


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _source_files(package: ValidatedPackage, operator: str) -> dict[str, Any]:
    return {
        "operator": operator,
        "files": {
            FILE_NAMES[name]: package.raw_hashes.get(name, "")
            for name in ("courses", "nodes", "edges", "exercises")
        },
    }


def _error(
    file_key: str,
    code: str,
    message: str,
    item_index: int | None = None,
    pointer: str | None = None,
) -> ImportErrorRecord:
    return ImportErrorRecord(
        file=FILE_NAMES[file_key],
        item_index=item_index,
        json_pointer=pointer,
        code=code,
        message=message,
    )


def _read_database_state(conn: Connection) -> dict[str, Any]:
    state: dict[str, Any] = {}
    selections = {
        "courses": "SELECT course_code, name, textbook_info, is_active FROM courses",
        "nodes": "SELECT node_id, course_code, title, chapter_scope, description, aliases, scope_tags, is_active FROM knowledge_nodes",
        "edges": "SELECT edge_id, source_id, target_id, relation_type, mechanism, abc_grade, boundary_note, evidence_status, evidence_summary, evidence_detail, is_active FROM knowledge_edges",
        "exercises": "SELECT question_id, type, content, options, answer_key, difficulty, is_active FROM exercises",
    }
    for name, statement in selections.items():
        state[name] = {
            row[TABLES[name][1]]: dict(row)
            for row in conn.execute(text(statement)).mappings().all()
        }
    state["exercise_relations"] = {}
    for row in conn.execute(
        text("SELECT question_id, node_id FROM exercise_related_nodes ORDER BY question_id, node_id")
    ).mappings():
        state["exercise_relations"].setdefault(row["question_id"], set()).add(row["node_id"])
    return state


def _values_equal(field_name: str, left: Any, right: Any) -> bool:
    if field_name in {"aliases", "scope_tags", "related_node_ids"}:
        return set(left or []) == set(right or [])
    if field_name == "options" and left is not None and right is not None:
        return list(left) == list(right)
    return left == right


def _check_existing(
    package: ValidatedPackage, state: dict[str, Any]
) -> list[ImportErrorRecord]:
    errors: list[ImportErrorRecord] = []
    for name, (_, primary_key) in TABLES.items():
        rows = package.files[name]["items"]
        existing_rows = state[name]
        for index, row in enumerate(rows):
            current = existing_rows.get(row[primary_key])
            if current is None:
                continue
            if not current["is_active"]:
                errors.append(
                    _error(
                        name,
                        "RETIRED_ID",
                        f"{primary_key}={row[primary_key]}已下线，不能重新启用",
                        index,
                        f"/items/{index}/{primary_key}",
                    )
                )
                continue
            for field_name in IMMUTABLE_FIELDS.get(name, ()):
                if not _values_equal(field_name, row.get(field_name), current.get(field_name)):
                    errors.append(
                        _error(
                            name,
                            "IMMUTABLE_FIELD",
                            f"{primary_key}={row[primary_key]}的{field_name}字段不可修改",
                            index,
                            f"/items/{index}/{field_name}",
                        )
                    )
            if name == "exercises":
                old_related = state["exercise_relations"].get(row[primary_key], set())
                new_related = set(row["related_node_ids"])
                if old_related != new_related:
                    errors.append(
                        _error(
                            name,
                            "IMMUTABLE_FIELD",
                            f"question_id={row[primary_key]}的related_node_ids字段不可修改",
                            index,
                            f"/items/{index}/related_node_ids",
                        )
                    )

    return errors[:100]


def _active_package_matches(package: ValidatedPackage, state: dict[str, Any]) -> bool:
    for name, (_, primary_key) in TABLES.items():
        desired = {row[primary_key]: row for row in package.files[name]["items"]}
        active = {key: row for key, row in state[name].items() if row["is_active"]}
        if desired.keys() != active.keys():
            return False
        for key, row in desired.items():
            current = active[key]
            for field_name, value in row.items():
                if field_name == "related_node_ids":
                    continue
                if not _values_equal(field_name, value, current.get(field_name)):
                    return False
            if name == "exercises" and set(row["related_node_ids"]) != state["exercise_relations"].get(key, set()):
                return False
    return True


def _insert_row(conn: Connection, name: str, row: dict[str, Any]) -> None:
    columns = INSERT_COLUMNS[name]
    table_name = TABLES[name][0]
    value_expressions = []
    parameters: dict[str, Any] = {}
    for column in columns:
        parameters[column] = row[column]
        if name == "nodes" and column in {"aliases", "scope_tags"}:
            value_expressions.append(f"CAST(:{column} AS text[])")
        elif name == "edges" and column == "evidence_detail":
            value_expressions.append(f"CAST(:{column} AS jsonb)")
        elif name == "exercises" and column in {"options", "answer_key"}:
            value_expressions.append(f"CAST(:{column} AS jsonb)")
        else:
            value_expressions.append(f":{column}")
        if (name == "edges" and column == "evidence_detail") or (
            name == "exercises" and column in {"options", "answer_key"}
        ):
            parameters[column] = _json(row[column])
    conn.execute(
        text(
            f"INSERT INTO {table_name} ({', '.join(columns)}) "
            f"VALUES ({', '.join(value_expressions)})"
        ),
        parameters,
    )


def _update_row(conn: Connection, name: str, row: dict[str, Any], fields: tuple[str, ...]) -> None:
    table_name, primary_key = TABLES[name]
    assignments: list[str] = []
    parameters: dict[str, Any] = {"_id": row[primary_key]}
    for field_name in fields:
        parameters[field_name] = row[field_name]
        if name == "nodes" and field_name in {"aliases", "scope_tags"}:
            assignments.append(f"{field_name} = CAST(:{field_name} AS text[])")
        elif name == "edges" and field_name == "evidence_detail":
            assignments.append(f"{field_name} = CAST(:{field_name} AS jsonb)")
            parameters[field_name] = _json(row[field_name])
        else:
            assignments.append(f"{field_name} = :{field_name}")
    assignments.append("updated_at = clock_timestamp()")
    conn.execute(
        text(
            f"UPDATE {table_name} SET {', '.join(assignments)} "
            f"WHERE {primary_key} = :_id"
        ),
        parameters,
    )


def _apply_changes(
    conn: Connection, package: ValidatedPackage, state: dict[str, Any]
) -> dict[str, Any]:
    counts = _package_counts(package)

    # Retire first so a replacement edge can satisfy active uniqueness rules
    # before the new row is inserted. The order also preserves FK references.
    for name in ("edges", "exercises", "nodes", "courses"):
        table_name, primary_key = TABLES[name]
        desired_ids = {row[primary_key] for row in package.files[name]["items"]}
        for item_id, current in state[name].items():
            if current["is_active"] and item_id not in desired_ids:
                conn.execute(
                    text(
                        f"UPDATE {table_name} SET is_active = false, updated_at = clock_timestamp() "
                        f"WHERE {primary_key} = :item_id AND is_active = true"
                    ),
                    {"item_id": item_id},
                )
                counts["changes"][name]["retired"] += 1

    for name in ("courses", "nodes", "edges", "exercises"):
        primary_key = TABLES[name][1]
        existing_rows = state[name]
        for row in package.files[name]["items"]:
            current = existing_rows.get(row[primary_key])
            if current is None:
                _insert_row(conn, name, row)
                counts["changes"][name]["inserted"] += 1
                if name == "exercises":
                    for node_id in row["related_node_ids"]:
                        conn.execute(
                            text(
                                "INSERT INTO exercise_related_nodes (question_id, node_id) "
                                "VALUES (:question_id, :node_id)"
                            ),
                            {"question_id": row[primary_key], "node_id": node_id},
                        )
                continue
            fields = MUTABLE_FIELDS.get(name, ())
            changed = [
                field_name
                for field_name in fields
                if not _values_equal(field_name, row[field_name], current.get(field_name))
            ]
            if changed:
                _update_row(conn, name, row, tuple(changed))
                counts["changes"][name]["updated"] += 1

    return counts


def _update_run(
    conn: Connection,
    run_id: str,
    status: str,
    counts: dict[str, Any],
    error_summary: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        text(
            "UPDATE import_runs SET status = :status, counts = CAST(:counts AS jsonb), "
            "error_summary = CAST(:error_summary AS jsonb), finished_at = clock_timestamp() "
            "WHERE run_id = CAST(:run_id AS uuid)"
        ),
        {
            "status": status,
            "counts": _json(counts),
            "error_summary": _json(error_summary) if error_summary is not None else None,
            "run_id": run_id,
        },
    )


def _record_failure(
    conn: Connection,
    run_id: str,
    errors: list[ImportErrorRecord],
    total_errors: int,
    counts: dict[str, Any],
) -> bool:
    try:
        conn.rollback()
        with conn.begin():
            _update_run(
                conn,
                run_id,
                "failed",
                counts,
                {
                    "total_errors": total_errors,
                    "errors": [error.model_dump() for error in errors[:100]],
                },
            )
        return True
    except SQLAlchemyError:
        conn.rollback()
        return False


def import_seed_package(
    package: ValidatedPackage,
    operator: str = "system",
    db_engine: Engine = engine,
) -> ImportReport:
    """Import one complete seed package under a PostgreSQL session advisory lock."""
    run_id = str(uuid.uuid4())
    counts = _package_counts(package) if package.total_errors == 0 else _empty_counts()
    errors = list(package.errors)
    total_errors = package.total_errors
    conn: Connection | None = None
    lock_acquired = False
    run_recorded = False

    try:
        conn = db_engine.connect()
        lock_acquired = bool(
            conn.execute(
                text("SELECT pg_try_advisory_lock(:lock_key)"),
                {"lock_key": ADVISORY_LOCK_KEY},
            ).scalar()
        )
        conn.commit()
        if not lock_acquired:
            errors.append(_error("courses", "IMPORT_LOCKED", "另一个导入正在进行"))
            return ImportReport(
                run_id=run_id,
                status="failed",
                checksum=package.checksum,
                counts=counts,
                errors=errors[:100],
                total_errors=total_errors + 1,
            )

        with conn.begin():
            conn.execute(
                text(
                    "UPDATE import_runs SET status = 'failed', finished_at = clock_timestamp(), "
                    "error_summary = CAST(:summary AS jsonb) WHERE status = 'running'"
                ),
                {"summary": _json({"reason": "interrupted", "message": "导入进程未正常结束"})},
            )
            conn.execute(
                text(
                    "INSERT INTO import_runs "
                    "(run_id, checksum, source_files, status, counts, started_at) "
                    "VALUES (CAST(:run_id AS uuid), :checksum, CAST(:source_files AS jsonb), "
                    "'running', CAST(:counts AS jsonb), clock_timestamp())"
                ),
                {
                    "run_id": run_id,
                    "checksum": package.checksum,
                    "source_files": _json(_source_files(package, operator)),
                    "counts": _json(counts),
                },
            )
        run_recorded = True

        if total_errors:
            _record_failure(conn, run_id, errors, total_errors, counts)
            return ImportReport(
                run_id=run_id,
                status="failed",
                checksum=package.checksum,
                counts=counts,
                errors=errors[:100],
                total_errors=total_errors,
            )

        state = _read_database_state(conn)
        database_errors = _check_existing(package, state)
        if database_errors:
            _record_failure(conn, run_id, database_errors, len(database_errors), counts)
            return ImportReport(
                run_id=run_id,
                status="failed",
                checksum=package.checksum,
                counts=counts,
                errors=database_errors[:100],
                total_errors=len(database_errors),
            )
        conn.commit()

        last_checksum = conn.execute(
            text(
                "SELECT checksum FROM import_runs WHERE status = 'succeeded' "
                "ORDER BY finished_at DESC, started_at DESC LIMIT 1"
            )
        ).scalar()
        if last_checksum == package.checksum and _active_package_matches(package, state):
            conn.commit()
            with conn.begin():
                _update_run(conn, run_id, "skipped", counts)
            return ImportReport(
                run_id=run_id,
                status="skipped",
                checksum=package.checksum,
                counts=counts,
            )

        conn.commit()
        with conn.begin():
            counts = _apply_changes(conn, package, state)
            _update_run(conn, run_id, "succeeded", counts)
        return ImportReport(
            run_id=run_id,
            status="succeeded",
            checksum=package.checksum,
            counts=counts,
        )
    except SQLAlchemyError as exc:
        errors.append(_error("courses", "DATABASE_ERROR", f"数据库操作失败（{type(exc).__name__}），请检查数据库与权限"))
        if conn is not None and run_recorded:
            _record_failure(conn, run_id, errors, total_errors + 1, counts)
        return ImportReport(
            run_id=run_id,
            status="failed",
            checksum=package.checksum,
            counts=counts,
            errors=errors[:100],
            total_errors=total_errors + 1,
        )
    finally:
        if conn is not None:
            if lock_acquired:
                try:
                    conn.rollback()
                    conn.execute(
                        text("SELECT pg_advisory_unlock(:lock_key)"),
                        {"lock_key": ADVISORY_LOCK_KEY},
                    )
                    conn.commit()
                except SQLAlchemyError:
                    conn.invalidate()
            conn.close()
