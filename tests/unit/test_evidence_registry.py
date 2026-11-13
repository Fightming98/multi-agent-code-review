"""Stage 2.4：内存 ``ArtifactData`` 证据注册表测试（§四）。

验证：

- JSON Pointer 只索引内存 ArtifactData 的稳定记录；
- 未注册指针、非法文件名与越界索引被明确拒绝；
- 同一 Pointer 在内存与落盘 JSON 中解析到同一内容。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_review.agents.evidence import (
    EvidenceReferenceError,
    EvidenceRegistry,
)
from tests.stage2_helpers import make_stage24_artifact_data

STATIC_POINTER = "static_analysis.json#/agents/security/tools/bandit/findings/0"
COVERAGE_POINTER = "test_report.json#/coverage"
COUNT_POINTER = "test_report.json#/counts/passed"
RECORD_POINTER = "test_report.json#/records/0"


def resolve_disk_pointer(document: object, pointer: str) -> object:
    """最小 JSON Pointer 解析器，模拟报告落盘后的解析行为。"""

    fragment = pointer.split("#", 1)[1]
    node = document
    for raw_token in fragment[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = node[int(token)]
        elif isinstance(node, dict):
            node = node[token]
        else:
            raise TypeError(f"pointer cannot descend into {type(node)}")
    return node


def test_registry_indexes_static_tool_findings() -> None:
    registry = EvidenceRegistry(make_stage24_artifact_data())

    record = registry.resolve(STATIC_POINTER)
    assert record.kind == "static_tool_finding"
    assert record.file_name == "static_analysis.json"
    assert record.dimension == "security"
    assert record.tool_name == "bandit"
    assert record.index == 0
    assert record.value["rule_id"] == "B608"
    assert record.value["line"] == 12


def test_registry_indexes_test_report_fields_and_records() -> None:
    registry = EvidenceRegistry(make_stage24_artifact_data())

    coverage = registry.resolve(COVERAGE_POINTER)
    assert coverage.kind == "test_report_field"
    assert coverage.value == 91.0

    count = registry.resolve(COUNT_POINTER)
    assert count.kind == "test_report_field"
    assert count.value == 3

    record = registry.resolve(RECORD_POINTER)
    assert record.kind == "test_record"
    assert record.value["file_path"] == "tests/test_app.py"
    assert record.value["line"] == 3

    pointers = registry.pointers()
    assert STATIC_POINTER in pointers
    assert COVERAGE_POINTER in pointers
    assert COUNT_POINTER in pointers
    assert RECORD_POINTER in pointers


def test_registry_rejects_unregistered_or_unknown_pointers() -> None:
    registry = EvidenceRegistry(make_stage24_artifact_data())

    # ArtifactData 可以解析，但注册表没有把它当作证据记录。
    with pytest.raises(EvidenceReferenceError):
        registry.resolve("static_analysis.json#/agents/security/agent_name")

    # 非报告文件名。
    with pytest.raises(EvidenceReferenceError):
        registry.resolve("metadata.json#/review_id")

    # 不存在的数组下标。
    with pytest.raises(EvidenceReferenceError):
        registry.resolve(
            "static_analysis.json#/agents/security/tools/bandit/findings/9"
        )

    # 非指针字符串。
    with pytest.raises(EvidenceReferenceError):
        registry.resolve("not-a-pointer")


def test_registry_reads_memory_without_touching_disk(
    tmp_path: Path,
) -> None:
    artifact = make_stage24_artifact_data()
    registry = EvidenceRegistry(artifact)

    assert not (tmp_path / "static_analysis.json").exists()
    assert not (tmp_path / "test_report.json").exists()
    assert registry.resolve(STATIC_POINTER).value["rule_id"] == "B608"


def test_same_pointer_resolves_identically_in_memory_and_on_disk(
    tmp_path: Path,
) -> None:
    artifact = make_stage24_artifact_data()
    registry = EvidenceRegistry(artifact)

    static_path = tmp_path / "static_analysis.json"
    report_path = tmp_path / "test_report.json"
    static_path.write_text(
        json.dumps(artifact.static_analysis_dict(), ensure_ascii=False),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(artifact.test_report_dict(), ensure_ascii=False),
        encoding="utf-8",
    )

    static_document = json.loads(static_path.read_text(encoding="utf-8"))
    report_document = json.loads(report_path.read_text(encoding="utf-8"))

    for pointer, document in (
        (STATIC_POINTER, static_document),
        (COVERAGE_POINTER, report_document),
        (COUNT_POINTER, report_document),
        (RECORD_POINTER, report_document),
    ):
        memory_record = registry.resolve(pointer)
        assert resolve_disk_pointer(document, pointer) == memory_record.value


def test_reports_and_artifact_data_are_copies() -> None:
    artifact = make_stage24_artifact_data()
    first = artifact.static_analysis_dict()
    first["agents"]["security"]["tools"]["bandit"]["findings"][0][
        "rule_id"
    ] = "MUTATED"

    second = artifact.static_analysis_dict()
    assert (
        second["agents"]["security"]["tools"]["bandit"]["findings"][0][
            "rule_id"
        ]
        == "B608"
    )
    registry = EvidenceRegistry(artifact)
    assert registry.resolve(STATIC_POINTER).value["rule_id"] == "B608"
