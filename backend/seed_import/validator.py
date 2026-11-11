"""Seed-file parsing, schema validation, cross-reference checks, and checksum."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


FILE_ORDER = ("courses", "edges", "exercises", "nodes")
INPUT_ORDER = ("courses", "nodes", "edges", "exercises")
FILE_NAMES = {name: f"{name}.json" for name in INPUT_ORDER}
PRIMARY_KEYS = {
    "courses": "course_code",
    "nodes": "node_id",
    "edges": "edge_id",
    "exercises": "question_id",
}
MAX_REPORTED_ERRORS = 100


class ImportErrorRecord(BaseModel):
    file: str
    item_index: int | None = None
    json_pointer: str | None = None
    line: int | None = None
    column: int | None = None
    code: str
    message: str


# Keep the public name used by the task contract while retaining a descriptive
# internal name for callers that do not want to shadow Python's built-in error.
ImportError = ImportErrorRecord


class ImportReport(BaseModel):
    run_id: str
    status: str
    checksum: str
    counts: dict[str, Any] = Field(default_factory=dict)
    errors: list[ImportErrorRecord] = Field(default_factory=list)
    total_errors: int = 0


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _trim(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


class CourseItem(_StrictModel):
    course_code: str = Field(pattern=r"^(DS|CO|OS|CN)$")
    name: str = Field(min_length=1, max_length=100)
    textbook_info: str = ""

    @field_validator("name", "textbook_info", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class NodeItem(_StrictModel):
    node_id: str = Field(pattern=r"^[A-Z]{2}[0-9]{2,4}$", max_length=16)
    course_code: str = Field(pattern=r"^(DS|CO|OS|CN)$", min_length=2, max_length=2)
    title: str = Field(min_length=1, max_length=100)
    chapter_scope: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list)
    scope_tags: list[str] = Field(default_factory=list)

    @field_validator("title", "chapter_scope", "description", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("aliases", mode="before")
    @classmethod
    def clean_aliases(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                return value
            item = item.strip()
            if not item:
                continue
            if not 2 <= len(item) <= 100:
                raise ValueError("别名单项长度必须为2-100字")
            normalized = normalize_text(item)
            if not normalized:
                raise ValueError("别名归一化后不能为空")
            if normalized not in seen:
                cleaned.append(item)
                seen.add(normalized)
        return cleaned

    @field_validator("scope_tags", mode="before")
    @classmethod
    def trim_scope_tags(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [_trim(item) for item in value]
        return value

    @field_validator("scope_tags")
    @classmethod
    def validate_scope_tags(cls, value: list[str]) -> list[str]:
        if any(not 1 <= len(tag) <= 50 for tag in value):
            raise ValueError("scope_tags单项长度必须为1-50字")
        return value


class EdgeItem(_StrictModel):
    edge_id: str = Field(pattern=r"^E[0-9]{3,6}$", max_length=16)
    source_id: str = Field(max_length=16)
    target_id: str = Field(max_length=16)
    relation_type: str = Field(pattern=r"^(prerequisite|implements|contrast|boundary)$")
    mechanism: str = Field(min_length=1, max_length=1000)
    abc_grade: str = Field(pattern=r"^[ABC]$", min_length=1, max_length=1)
    boundary_note: str = Field(default="", max_length=1000)
    evidence_status: str = Field(pattern=r"^(已核验|部分定位|待补充)$")
    evidence_summary: str = Field(min_length=1, max_length=1000)
    evidence_detail: dict[str, str] | None = Field(default=None, validate_default=True)

    @field_validator("mechanism", "boundary_note", "evidence_summary", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("evidence_detail")
    @classmethod
    def validate_evidence_detail(
        cls, value: dict[str, str] | None, info: Any
    ) -> dict[str, str] | None:
        if value is None:
            return value
        allowed = {"book_title", "edition", "chapter", "pages"}
        if set(value) - allowed:
            raise ValueError("evidence_detail只允许book_title、edition、chapter、pages")
        value = {key: item.strip() for key, item in value.items()}
        status = info.data.get("evidence_status")
        if status == "已核验" and not all(value.get(key, "") for key in allowed):
            raise ValueError("已核验要求evidence_detail四项均非空")
        if status == "部分定位":
            if not value.get("book_title", ""):
                raise ValueError("部分定位要求book_title非空")
            if not any(value.get(key, "") for key in ("edition", "chapter", "pages")):
                raise ValueError("部分定位要求edition/chapter/pages至少一项非空")
        return value

    @model_validator(mode="after")
    def validate_missing_evidence_detail(self) -> "EdgeItem":
        if self.evidence_detail is None and self.evidence_status in {"已核验", "部分定位"}:
            if self.evidence_status == "已核验":
                raise ValueError("已核验要求evidence_detail四项均非空")
            raise ValueError("部分定位要求book_title非空")
        return self


class ExerciseOption(_StrictModel):
    key: str = Field(pattern=r"^[A-F]$", min_length=1, max_length=1)
    text: str = Field(min_length=1, max_length=500)

    @field_validator("text", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class ExerciseItem(_StrictModel):
    question_id: str = Field(pattern=r"^Q[0-9]{3,8}$", max_length=32)
    type: str = Field(pattern=r"^(choice|judge)$")
    content: str = Field(min_length=1, max_length=2000)
    options: list[ExerciseOption] | None = Field(default=None, validate_default=True)
    answer_key: Any
    difficulty: int = Field(ge=1, le=5)
    related_node_ids: list[str] = Field(min_length=1)

    @field_validator("content", mode="before")
    @classmethod
    def trim_content(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("options")
    @classmethod
    def validate_options(
        cls, value: list[ExerciseOption] | None, info: Any
    ) -> list[ExerciseOption] | None:
        question_type = info.data.get("type")
        if question_type == "choice":
            if value is None or not 2 <= len(value) <= 6:
                raise ValueError("choice题必须包含2-6个选项")
            keys = [option.key for option in value]
            if len(keys) != len(set(keys)):
                raise ValueError("选项key不能重复")
        elif question_type == "judge" and value is not None:
            raise ValueError("judge题的options必须为null")
        return value

    @field_validator("answer_key")
    @classmethod
    def validate_answer_key(cls, value: Any, info: Any) -> Any:
        question_type = info.data.get("type")
        if question_type == "choice":
            if not isinstance(value, str):
                raise ValueError("choice题的answer_key必须为字符串")
            options = info.data.get("options") or []
            if value not in {option.key for option in options}:
                raise ValueError("answer_key必须对应一个选项key")
        elif question_type == "judge" and not isinstance(value, bool):
            raise ValueError("judge题的answer_key必须为boolean")
        return value

    @field_validator("related_node_ids")
    @classmethod
    def validate_related_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("related_node_ids不能重复")
        if any(not node_id for node_id in value):
            raise ValueError("related_node_ids不能包含空ID")
        return value


def normalize_text(value: str) -> str:
    """Normalize title and alias text using the graph matching contract."""
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"[^\w\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _pointer(parts: list[str | int]) -> str:
    escaped = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(escaped) if escaped else ""


@dataclass
class _Issues:
    errors: list[ImportErrorRecord] = field(default_factory=list)
    total: int = 0

    def add(
        self,
        file_key: str,
        code: str,
        message: str,
        pointer: str | None = None,
        item_index: int | None = None,
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        self.total += 1
        if len(self.errors) < MAX_REPORTED_ERRORS:
            self.errors.append(
                ImportErrorRecord(
                    file=FILE_NAMES[file_key],
                    item_index=item_index,
                    json_pointer=pointer,
                    line=line,
                    column=column,
                    code=code,
                    message=message,
                )
            )


class _DuplicateJSONKey(ValueError):
    pass


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey(f"JSON对象包含重复键：{key}")
        result[key] = value
    return result


@dataclass
class ValidatedPackage:
    files: dict[str, dict[str, Any]]
    checksum: str
    raw_hashes: dict[str, str]
    errors: list[ImportErrorRecord]
    total_errors: int


def _raw_checksum(raw_hashes: dict[str, str]) -> str:
    payload = json.dumps(
        {FILE_NAMES[name]: raw_hashes.get(name, "") for name in FILE_ORDER},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_checksum(files_data: Mapping[str, dict[str, Any]]) -> str:
    """Hash canonical JSON without mutating the validated file payloads."""
    normalized: dict[str, Any] = {}
    for name in FILE_ORDER:
        data = files_data[name]
        primary_key = PRIMARY_KEYS[name]
        items = []
        for source_item in data["items"]:
            item = dict(source_item)
            for field_name in ("aliases", "scope_tags", "related_node_ids"):
                if field_name in item:
                    item[field_name] = sorted(item[field_name])
            items.append(item)
        items.sort(key=lambda item: item[primary_key])
        normalized[name] = {
            "schema_version": data["schema_version"],
            "items": items,
        }
    canonical = json.dumps(
        normalized,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _model_errors(
    issues: _Issues,
    file_key: str,
    item_index: int,
    validation_error: ValidationError,
) -> None:
    for error in validation_error.errors(include_url=False):
        location = list(error["loc"])
        pointer = _pointer(["items", item_index, *location])
        error_type = error["type"]
        if error_type == "missing":
            code = "MISSING_FIELD"
        elif error_type == "extra_forbidden":
            code = "UNKNOWN_FIELD"
        elif error_type in {"string_pattern_mismatch", "literal_error"}:
            code = "INVALID_FORMAT"
        elif error_type in {"string_too_short", "string_too_long", "greater_than_equal", "less_than_equal"}:
            code = "INVALID_LENGTH"
        else:
            code = "INVALID_FIELD"
        message = error["msg"].removeprefix("Value error, ")
        issues.add(file_key, code, message, pointer, item_index)


def load_and_validate(paths: Mapping[str, str | Path]) -> ValidatedPackage:
    """Read all four fixed seed files and return normalized, cross-checked data."""
    issues = _Issues()
    raw_hashes: dict[str, str] = {}
    raw_items: dict[str, Any] = {}

    for file_key in INPUT_ORDER:
        path = Path(paths[file_key])
        try:
            raw = path.read_bytes()
        except OSError as exc:
            issues.add(file_key, "FILE_READ_ERROR", f"无法读取文件：{exc}")
            continue
        raw_hashes[file_key] = hashlib.sha256(raw).hexdigest()
        try:
            decoded = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            issues.add(file_key, "INVALID_ENCODING", "文件必须使用UTF-8编码", line=None, column=exc.start + 1)
            continue
        try:
            document = json.loads(decoded, object_pairs_hook=_object_without_duplicate_keys)
        except json.JSONDecodeError as exc:
            issues.add(
                file_key,
                "JSON_SYNTAX_ERROR",
                exc.msg,
                line=exc.lineno,
                column=exc.colno,
            )
            continue
        except _DuplicateJSONKey as exc:
            issues.add(file_key, "DUPLICATE_JSON_KEY", str(exc))
            continue
        raw_items[file_key] = document

    parsed: dict[str, dict[str, Any]] = {}
    model_by_file = {
        "courses": CourseItem,
        "nodes": NodeItem,
        "edges": EdgeItem,
        "exercises": ExerciseItem,
    }
    for file_key in INPUT_ORDER:
        if file_key not in raw_items:
            continue
        document = raw_items[file_key]
        if not isinstance(document, dict):
            issues.add(file_key, "INVALID_STRUCTURE", "文件顶层必须为JSON对象")
            continue
        for key in document.keys() - {"schema_version", "items"}:
            issues.add(file_key, "UNKNOWN_FIELD", f"未知字段：{key}", _pointer([key]))
        for key in {"schema_version", "items"} - document.keys():
            issues.add(file_key, "MISSING_FIELD", f"缺少字段：{key}", _pointer([key]))
        if type(document.get("schema_version")) is not int or document.get("schema_version") != 1:
            issues.add(file_key, "INVALID_SCHEMA_VERSION", "schema_version必须为整数1", "/schema_version")
        items = document.get("items")
        if not isinstance(items, list):
            issues.add(file_key, "INVALID_STRUCTURE", "items必须为数组", "/items")
            continue
        validated_items: list[dict[str, Any]] = []
        primary_key = PRIMARY_KEYS[file_key]
        seen_ids: set[str] = set()
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                issues.add(file_key, "INVALID_STRUCTURE", "数组项必须为JSON对象", _pointer(["items", index]), index)
                continue
            try:
                model = model_by_file[file_key].model_validate(item)
            except ValidationError as exc:
                _model_errors(issues, file_key, index, exc)
                continue
            normalized_item = model.model_dump(mode="python")
            item_id = normalized_item[primary_key]
            if item_id in seen_ids:
                issues.add(
                    file_key,
                    "DUPLICATE_ID",
                    f"{primary_key}重复：{item_id}",
                    _pointer(["items", index, primary_key]),
                    index,
                )
            seen_ids.add(item_id)
            validated_items.append(normalized_item)
        parsed[file_key] = {"schema_version": 1, "items": validated_items}

    if set(parsed) == set(INPUT_ORDER) and issues.total == 0:
        _validate_cross_references(parsed, raw_items, issues)
        if issues.total == 0:
            _normalize_symmetric_edges(parsed)
            checksum = compute_checksum(parsed)
        else:
            checksum = _raw_checksum(raw_hashes)
    else:
        checksum = _raw_checksum(raw_hashes)

    return ValidatedPackage(
        files=parsed,
        checksum=checksum,
        raw_hashes=raw_hashes,
        errors=issues.errors,
        total_errors=issues.total,
    )


def _validate_cross_references(
    files: dict[str, dict[str, Any]], raw_items: dict[str, Any], issues: _Issues
) -> None:
    courses = files["courses"]["items"]
    nodes = files["nodes"]["items"]
    edges = files["edges"]["items"]
    exercises = files["exercises"]["items"]
    course_codes = {course["course_code"] for course in courses}
    node_by_id = {node["node_id"]: node for node in nodes}

    for index, node in enumerate(nodes):
        if node["course_code"] not in course_codes:
            issues.add(
                "nodes", "MISSING_REFERENCE", f"课程{node['course_code']}不存在于本批courses.json",
                _pointer(["items", index, "course_code"]), index,
            )
        if node["node_id"][:2] != node["course_code"]:
            issues.add(
                "nodes", "COURSE_PREFIX_MISMATCH", "node_id前缀必须与course_code一致",
                _pointer(["items", index, "course_code"]), index,
            )

    symbols: dict[str, tuple[str, str]] = {}
    raw_nodes = raw_items.get("nodes", {}).get("items", [])
    for index, node in enumerate(nodes):
        node_id = node["node_id"]
        entries = [(node["title"], _pointer(["items", index, "title"]))]
        raw_node = raw_nodes[index] if index < len(raw_nodes) and isinstance(raw_nodes[index], dict) else {}
        raw_aliases = raw_node.get("aliases", [])
        alias_positions: dict[str, list[int]] = {}
        if isinstance(raw_aliases, list):
            for alias_index, alias in enumerate(raw_aliases):
                if isinstance(alias, str) and alias.strip():
                    alias_positions.setdefault(normalize_text(alias.strip()), []).append(alias_index)
        used_alias_positions: dict[str, int] = {}
        for alias_index, alias in enumerate(node["aliases"]):
            normalized_alias = normalize_text(alias)
            positions = alias_positions.get(normalized_alias, [alias_index])
            occurrence = used_alias_positions.get(normalized_alias, 0)
            source_index = positions[min(occurrence, len(positions) - 1)]
            used_alias_positions[normalized_alias] = occurrence + 1
            entries.append((alias, _pointer(["items", index, "aliases", source_index])))
        for label, pointer in entries:
            normalized = normalize_text(label)
            if not normalized:
                issues.add("nodes", "INVALID_TEXT", "标题或别名归一化后不能为空", pointer, index)
                continue
            previous = symbols.get(normalized)
            if previous is not None and previous[0] != node_id:
                issues.add("nodes", "ALIAS_CONFLICT", f"与节点{previous[0]}的标题或别名冲突", pointer, index)
            else:
                symbols[normalized] = (node_id, pointer)

    relation_keys: set[tuple[str, str, str]] = set()
    edge_id_to_index = {edge["edge_id"]: index for index, edge in enumerate(edges)}
    for index, edge in enumerate(edges):
        if edge["source_id"] == edge["target_id"]:
            issues.add("edges", "SELF_LOOP", "关系两端不能是同一节点", _pointer(["items", index, "target_id"]), index)
        for field_name in ("source_id", "target_id"):
            if edge[field_name] not in node_by_id:
                issues.add(
                    "edges", "MISSING_REFERENCE", f"节点{edge[field_name]}不存在于本批nodes.json",
                    _pointer(["items", index, field_name]), index,
                )
        left, right = edge["source_id"], edge["target_id"]
        if edge["relation_type"] in {"contrast", "boundary"}:
            left, right = sorted((left, right))
        key = (left, right, edge["relation_type"])
        if key in relation_keys:
            issues.add("edges", "DUPLICATE_RELATION", "同类型关系端点组合重复", _pointer(["items", index]), index)
        relation_keys.add(key)
    del edge_id_to_index

    for index, exercise in enumerate(exercises):
        for related_index, node_id in enumerate(exercise["related_node_ids"]):
            if node_id not in node_by_id:
                issues.add(
                    "exercises", "MISSING_REFERENCE", f"节点{node_id}不存在于本批nodes.json",
                    _pointer(["items", index, "related_node_ids", related_index]), index,
                )


def _normalize_symmetric_edges(files: dict[str, dict[str, Any]]) -> None:
    for edge in files["edges"]["items"]:
        if edge["relation_type"] in {"contrast", "boundary"}:
            edge["source_id"], edge["target_id"] = sorted((edge["source_id"], edge["target_id"]))
