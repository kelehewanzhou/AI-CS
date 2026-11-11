"""Unit coverage for seed validation, canonicalization, and import policy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from seed_import.validator import (
    EdgeItem,
    ExerciseItem,
    NodeItem,
    compute_checksum,
    load_and_validate,
    normalize_text,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = PROJECT_ROOT / "fixtures"


def _fixture_paths() -> dict[str, Path]:
    return {name: FIXTURES / f"{name}.json" for name in ("courses", "nodes", "edges", "exercises")}


def _copy_payloads(tmp_path: Path) -> tuple[dict[str, Path], dict[str, dict]]:
    paths = {}
    payloads = {}
    for name, source in _fixture_paths().items():
        payloads[name] = json.loads(source.read_text(encoding="utf-8"))
        target = tmp_path / f"{name}.json"
        target.write_text(json.dumps(payloads[name], ensure_ascii=False), encoding="utf-8")
        paths[name] = target
    return paths, payloads


def test_fixture_package_validates_and_normalizes(tmp_path):
    paths, payloads = _copy_payloads(tmp_path)
    payloads["edges"]["items"][0]["relation_type"] = "contrast"
    payloads["edges"]["items"][0]["source_id"] = "OS02"
    payloads["edges"]["items"][0]["target_id"] = "CO03"
    paths["edges"].write_text(json.dumps(payloads["edges"], ensure_ascii=False), encoding="utf-8")

    package = load_and_validate(paths)

    assert package.total_errors == 0
    edge = package.files["edges"]["items"][0]
    assert (edge["source_id"], edge["target_id"]) == ("CO03", "OS02")
    assert len(package.checksum) == 64


def test_normalize_text_uses_nfkc_casefold_and_space_folding():
    assert normalize_text("TLB") == normalize_text("ｔｌｂ")
    assert normalize_text("快表") == normalize_text("  快表  ")
    assert normalize_text("A-B") == "a b"


def test_node_aliases_are_trimmed_deduplicated_and_length_checked():
    valid = {
        "node_id": "CO03",
        "course_code": "CO",
        "title": " TLB ",
        "chapter_scope": "第3章",
        "description": "快速地址转换",
        "aliases": [" 快表 ", "快表"],
        "scope_tags": [],
    }
    node = NodeItem.model_validate(valid)
    assert node.title == "TLB"
    assert node.aliases == ["快表"]
    with pytest.raises(ValueError, match="2-100"):
        NodeItem.model_validate({**valid, "aliases": ["x"]})


def test_edge_evidence_status_requires_complete_verified_detail():
    edge = {
        "edge_id": "E001",
        "source_id": "CO03",
        "target_id": "OS02",
        "relation_type": "implements",
        "mechanism": "测试机制",
        "abc_grade": "A",
        "boundary_note": "",
        "evidence_status": "已核验",
        "evidence_summary": "测试摘要",
        "evidence_detail": {"book_title": "教材", "edition": "", "chapter": "", "pages": ""},
    }
    with pytest.raises(ValueError, match="四项均非空"):
        EdgeItem.model_validate(edge)
    with pytest.raises(ValueError, match="四项均非空"):
        EdgeItem.model_validate({key: value for key, value in edge.items() if key != "evidence_detail"})


def test_exercise_question_type_contracts_are_enforced():
    exercise = {
        "question_id": "Q001",
        "type": "choice",
        "content": "题目",
        "options": [{"key": "A", "text": "答案"}, {"key": "B", "text": "干扰项"}],
        "answer_key": "C",
        "difficulty": 1,
        "related_node_ids": ["CO03"],
    }
    with pytest.raises(ValueError, match="对应一个选项"):
        ExerciseItem.model_validate(exercise)
    with pytest.raises(ValueError, match="不能重复"):
        ExerciseItem.model_validate({**exercise, "answer_key": "A", "related_node_ids": ["CO03", "CO03"]})

    judge = {
        "question_id": "Q006",
        "type": "judge",
        "content": "判断题",
        "options": None,
        "answer_key": True,
        "difficulty": 1,
        "related_node_ids": ["CO03"],
    }
    assert ExerciseItem.model_validate(judge).answer_key is True
    with pytest.raises(ValueError, match="必须为boolean"):
        ExerciseItem.model_validate({**judge, "answer_key": "true"})
    with pytest.raises(ValueError, match="必须为null"):
        ExerciseItem.model_validate(
            {**judge, "options": [{"key": "A", "text": "对"}]}
        )
    with pytest.raises(ValueError):
        ExerciseItem.model_validate({**judge, "type": "short_answer"})


def test_alias_conflict_reports_original_json_pointer(tmp_path):
    paths, payloads = _copy_payloads(tmp_path)
    payloads["nodes"]["items"][0]["aliases"] = ["", "快表"]
    payloads["nodes"]["items"][1]["title"] = "快表"
    paths["nodes"].write_text(json.dumps(payloads["nodes"], ensure_ascii=False), encoding="utf-8")

    package = load_and_validate(paths)

    conflict = next(error for error in package.errors if error.code == "ALIAS_CONFLICT")
    assert conflict.file == "nodes.json"
    assert conflict.json_pointer == "/items/1/title"
    assert package.total_errors == 1


def test_missing_node_reference_points_to_exact_field(tmp_path):
    paths, payloads = _copy_payloads(tmp_path)
    payloads["edges"]["items"][0]["source_id"] = "INVALID"
    paths["edges"].write_text(json.dumps(payloads["edges"], ensure_ascii=False), encoding="utf-8")

    package = load_and_validate(paths)

    error = next(error for error in package.errors if error.code == "MISSING_REFERENCE")
    assert error.json_pointer == "/items/0/source_id"


def test_json_syntax_error_includes_line_and_column(tmp_path):
    paths, _ = _copy_payloads(tmp_path)
    paths["nodes"].write_text('{\n  "schema_version": 1,\n  "items": [\n}', encoding="utf-8")

    package = load_and_validate(paths)

    error = next(error for error in package.errors if error.code == "JSON_SYNTAX_ERROR")
    assert error.line == 4
    assert error.column is not None


def test_checksum_ignores_item_and_set_order_but_preserves_options_order(tmp_path):
    paths, payloads = _copy_payloads(tmp_path)
    first = load_and_validate(paths)
    reordered = {name: json.loads(json.dumps(value)) for name, value in payloads.items()}
    reordered["nodes"]["items"].reverse()
    reordered["nodes"]["items"][0]["scope_tags"].reverse()
    reordered["exercises"]["items"].reverse()
    assert compute_checksum(reordered) == first.checksum

    reordered["exercises"]["items"][0]["options"].reverse()
    assert compute_checksum(reordered) != first.checksum


def test_bom_is_accepted_and_unknown_fields_are_rejected(tmp_path):
    paths, payloads = _copy_payloads(tmp_path)
    paths["courses"].write_bytes(
        b"\xef\xbb\xbf" + json.dumps(payloads["courses"], ensure_ascii=False).encode("utf-8")
    )
    package = load_and_validate(paths)
    assert package.total_errors == 0

    payloads["courses"]["items"][0]["unexpected"] = True
    paths["courses"].write_text(json.dumps(payloads["courses"], ensure_ascii=False), encoding="utf-8")
    package = load_and_validate(paths)
    assert any(error.code == "UNKNOWN_FIELD" for error in package.errors)


def test_compute_checksum_does_not_mutate_input():
    payloads = {
        "courses": {"schema_version": 1, "items": [{"course_code": "CO", "name": "测试", "textbook_info": ""}]},
        "nodes": {"schema_version": 1, "items": []},
        "edges": {"schema_version": 1, "items": []},
        "exercises": {"schema_version": 1, "items": []},
    }
    before = json.dumps(payloads, ensure_ascii=False)
    assert compute_checksum(payloads) == compute_checksum(payloads)
    assert json.dumps(payloads, ensure_ascii=False) == before
