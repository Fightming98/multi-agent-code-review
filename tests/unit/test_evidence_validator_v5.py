"""Stage 2.4：Evidence Validator V1～V7 与两类 Finding 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_review.agents.contracts import ArtifactData
from code_review.agents.evidence import (
    EVENT_CODE_LOCATION,
    EVENT_TOOL_REPORT,
    STATUS_REJECTED,
    STATUS_UNVERIFIED,
    STATUS_VERIFIED,
    Stage2EvidenceValidator,
)
from code_review.agents.manager import AGENT_SPECS
from code_review.schemas.result import Finding, ToolEvidence
from tests.stage2_helpers import make_finding, make_review_rules, make_test_report_block

SOURCE = "\n".join(  # noqa: FLY002 - line-numbered fixture source
    [
        '"""Sample module for evidence validation tests."""',
        "",
        "import os",
        "",
        'api_key = "sample-token-value"',
        "",
        "",
        "def build_query(user_input):",
        '    query = "SELECT * FROM users WHERE name = \'" + user_input',
        "    return query",
        "",
        "",
        "def run(user_input):",
        '    os.system("echo " + user_input)',
        "",
    ]
) + "\n"

TEST_SOURCE = "\n".join(  # noqa: FLY002 - line-numbered fixture source
    [
        '"""Tests for the sample module."""',
        "",
        "def test_ok():",
        "    assert True",
        "",
    ]
) + "\n"

APP_FILE = "pkg/sample.py"
TEST_FILE = "tests/test_app.py"
SQL_EVIDENCE = 'query = "SELECT * FROM users WHERE name = \'" + user_input'
RUN_EVIDENCE = "def run(user_input):"


def make_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "sample.py").write_text(SOURCE, encoding="utf-8")
    (root / "tests").mkdir()
    (root / TEST_FILE).write_text(TEST_SOURCE, encoding="utf-8")
    return root


def tool_record(
    *,
    rule_id: str = "B608",
    file_path: str = APP_FILE,
    line: int = 9,
    message: str = "sample tool finding",
    severity: str = "MEDIUM",
) -> dict:
    return {
        "rule_id": rule_id,
        "file_path": file_path,
        "line": line,
        "end_line": line,
        "severity": severity,
        "message": message,
        "metadata": {},
    }


def tool_block(tool_name: str, records: list[dict]) -> dict:
    return {
        "tool_name": tool_name,
        "tool_version": "1.9.4",
        "execution_status": "findings",
        "findings": records,
    }


def make_artifact(
    *,
    security_records: list[dict] | None = None,
    quality_records: list[dict] | None = None,
    test_report: dict | None = None,
) -> ArtifactData:
    tools: dict[str, dict] = {
        "security": {
            "bandit": tool_block(
                "bandit",
                security_records
                if security_records is not None
                else [tool_record()],
            )
        },
        "quality": {
            "radon": tool_block(
                "radon",
                quality_records
                if quality_records is not None
                else [tool_record(rule_id="RADON_CC", line=9)],
            )
        },
        "performance": {},
        "testing": {},
    }
    agents = {
        dimension: {
            "agent_name": agent_name,
            "result_status": "completed",
            "warnings": [],
            "tools": tools[dimension],
        }
        for dimension, agent_name, _, _ in AGENT_SPECS
    }
    return ArtifactData(
        static_analysis={"schema_version": "1.0", "agents": agents},
        test_report=(
            test_report
            if test_report is not None
            else make_test_report_block()
        ),
    )


def make_validator(
    workspace: Path,
    *,
    artifact: ArtifactData | None = None,
    allowed_files: tuple[str, ...] = (APP_FILE, TEST_FILE),
) -> Stage2EvidenceValidator:
    return Stage2EvidenceValidator(
        workspace_path=workspace,
        allowed_files=allowed_files,
        artifact_data=artifact or make_artifact(),
        rules=make_review_rules(),
    )


def bandit_evidence(
    *,
    rule_id: str = "B608",
    tool_name: str = "bandit",
    ref: str | None = None,
) -> ToolEvidence:
    return ToolEvidence(
        tool_name=tool_name,
        rule_id=rule_id,
        raw_output_ref=(
            ref
            or (
                "static_analysis.json#/agents/security/tools/bandit/"
                "findings/0"
            )
        ),
    )


# ----------------------------------------------------------------------
# V1 / V2 / V3


def test_v1_missing_file_is_rejected(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    validator = make_validator(
        workspace, allowed_files=(APP_FILE, "pkg/missing.py")
    )

    result = validator.validate(
        make_finding(
            file_path="pkg/missing.py",
            start_line=1,
            evidence="anything",
            tool_evidence=[],
        )
    )

    assert result.status == STATUS_REJECTED
    assert any("V1" in reason for reason in result.reasons)


def test_v1_directory_is_rejected(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    validator = make_validator(workspace, allowed_files=("pkg",))

    result = validator.validate(
        make_finding(
            file_path="pkg", start_line=1, evidence="x", tool_evidence=[]
        )
    )

    assert result.status == STATUS_REJECTED
    assert any("V1" in reason for reason in result.reasons)


def test_v2_outside_allowed_set_is_rejected(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    validator = make_validator(workspace, allowed_files=(APP_FILE,))

    result = validator.validate(
        make_finding(
            file_path=TEST_FILE,
            start_line=3,
            evidence="def test_ok():",
            tool_evidence=[],
        )
    )

    assert result.status == STATUS_REJECTED
    assert any("V2" in reason for reason in result.reasons)


def test_v2_symlink_is_rejected_or_skipped(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("def outside():\n    return 1\n", encoding="utf-8")
    link = workspace / "pkg" / "link.py"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is not permitted for this user")
    validator = make_validator(
        workspace, allowed_files=(APP_FILE, "pkg/link.py")
    )

    result = validator.validate(
        make_finding(
            file_path="pkg/link.py",
            start_line=1,
            evidence="def outside():",
            tool_evidence=[],
        )
    )

    assert result.status == STATUS_REJECTED
    assert any("V2" in reason for reason in result.reasons)


def test_v3_line_out_of_range_is_rejected(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    validator = make_validator(workspace)

    result = validator.validate(
        make_finding(
            file_path=APP_FILE,
            start_line=99,
            end_line=99,
            evidence="anything",
            tool_evidence=[],
        )
    )

    assert result.status == STATUS_REJECTED
    assert any("V3" in reason for reason in result.reasons)


# ----------------------------------------------------------------------
# V4


def test_v4_mismatch_is_unverified_for_medium(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    validator = make_validator(workspace)

    result = validator.validate(
        make_finding(
            severity="medium",
            file_path=APP_FILE,
            start_line=9,
            evidence="this snippet does not exist anywhere in the file",
            tool_evidence=[],
        )
    )

    assert result.status == STATUS_UNVERIFIED
    assert any("V4" in reason for reason in result.reasons)


def test_v4_mismatch_rejects_critical_location(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    validator = make_validator(workspace)

    result = validator.validate(
        make_finding(
            severity="critical",
            file_path=APP_FILE,
            start_line=9,
            evidence="this snippet does not exist anywhere in the file",
            tool_evidence=[],
        )
    )

    assert result.status == STATUS_REJECTED
    assert result.finding.verification_status == STATUS_REJECTED


def test_v4_unique_neighborhood_match_adjusts_line(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    validator = make_validator(workspace)

    result = validator.validate(
        make_finding(
            severity="medium",
            file_path=APP_FILE,
            start_line=11,
            end_line=11,
            evidence=RUN_EVIDENCE,
            tool_evidence=[],
        )
    )

    assert result.adjusted is True
    assert result.finding.start_line == 13
    # LLM 自我确认不能产生 verified：没有工具证据只能是 unverified。
    assert result.status == STATUS_UNVERIFIED


def test_v4_tool_record_substantiates_tool_message_evidence(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    artifact = make_artifact(
        security_records=[tool_record(message="Bandit B608 SQL injection")]
    )
    validator = make_validator(workspace, artifact=artifact)

    result = validator.validate(
        make_finding(
            severity="medium",
            file_path=APP_FILE,
            start_line=9,
            evidence="Bandit B608 SQL injection",
            tool_evidence=[bandit_evidence()],
        )
    )

    assert result.status == STATUS_VERIFIED


# ----------------------------------------------------------------------
# V5：内存 ArtifactData


def test_v5_consistent_tool_evidence_is_verified(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    validator = make_validator(workspace)

    result = validator.validate(
        make_finding(
            file_path=APP_FILE,
            start_line=9,
            evidence=SQL_EVIDENCE,
            tool_evidence=[bandit_evidence()],
        )
    )

    assert result.evidence_kind == EVENT_CODE_LOCATION
    assert result.status == STATUS_VERIFIED
    assert result.finding.verification_status == STATUS_VERIFIED


def test_v5_tool_name_mismatch_is_rejected(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    validator = make_validator(workspace)

    result = validator.validate(
        make_finding(
            file_path=APP_FILE,
            start_line=9,
            evidence=SQL_EVIDENCE,
            tool_evidence=[bandit_evidence(tool_name="ruff")],
        )
    )

    assert result.status == STATUS_REJECTED
    assert any("V5" in reason for reason in result.reasons)


def test_v5_rule_mismatch_is_rejected(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    validator = make_validator(workspace)

    result = validator.validate(
        make_finding(
            file_path=APP_FILE,
            start_line=9,
            evidence=SQL_EVIDENCE,
            tool_evidence=[bandit_evidence(rule_id="B999")],
        )
    )

    assert result.status == STATUS_REJECTED


def test_v5_line_mismatch_is_rejected(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    validator = make_validator(workspace)

    result = validator.validate(
        make_finding(
            file_path=APP_FILE,
            start_line=13,
            end_line=13,
            evidence=RUN_EVIDENCE,
            tool_evidence=[bandit_evidence()],
        )
    )

    assert result.status == STATUS_REJECTED
    assert any("V5" in reason for reason in result.reasons)


def test_v5_file_mismatch_is_rejected(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    validator = make_validator(workspace)

    result = validator.validate(
        make_finding(
            file_path=TEST_FILE,
            start_line=3,
            end_line=3,
            evidence="def test_ok():",
            tool_evidence=[bandit_evidence()],
        )
    )

    assert result.status == STATUS_REJECTED
    assert any("V5" in reason for reason in result.reasons)


def test_v5_dimension_mismatch_is_rejected(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    validator = make_validator(workspace)

    result = validator.validate(
        make_finding(
            agent_name="SecurityAgent",
            file_path=APP_FILE,
            start_line=9,
            evidence=SQL_EVIDENCE,
            tool_evidence=[
                ToolEvidence(
                    tool_name="radon",
                    rule_id="RADON_CC",
                    raw_output_ref=(
                        "static_analysis.json#/agents/quality/tools/radon/"
                        "findings/0"
                    ),
                )
            ],
        )
    )

    assert result.status == STATUS_REJECTED
    assert any(
        "dimension" in reason for reason in result.reasons
    )


def test_v5_invalid_pointer_is_rejected(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    validator = make_validator(workspace)

    result = validator.validate(
        make_finding(
            file_path=APP_FILE,
            start_line=9,
            evidence=SQL_EVIDENCE,
            tool_evidence=[
                ToolEvidence(
                    tool_name="bandit",
                    rule_id="B608",
                    raw_output_ref=(
                        "static_analysis.json#/agents/security/tools/bandit/"
                        "findings/99"
                    ),
                )
            ],
        )
    )

    assert result.status == STATUS_REJECTED
    assert any("V5" in reason for reason in result.reasons)


# ----------------------------------------------------------------------
# B 类：工具报告型 Finding


def make_tool_report_finding(
    *,
    category: str = "low_coverage",
    severity: str = "medium",
    tool_name: str = "coverage",
    ref: str = "test_report.json#/coverage",
    evidence: str = "Coverage is below the configured minimum.",
) -> Finding:
    return make_finding(
        finding_id="TST-0001",
        agent_name="TestingAgent",
        category=category,
        severity=severity,
        title=f"Testing issue: {category}",
        description="Report-level testing finding.",
        file_path=None,
        start_line=None,
        end_line=None,
        evidence=evidence,
        tool_evidence=[
            ToolEvidence(tool_name=tool_name, raw_output_ref=ref)
        ],
    )


def test_project_level_finding_with_static_record_is_rejected(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    validator = make_validator(workspace)

    result = validator.validate(
        make_tool_report_finding(
            tool_name="bandit",
            ref="static_analysis.json#/agents/security/tools/bandit/findings/0",
        )
    )

    # 工具报告型 Finding 只能引用测试报告证据，不能引用代码位置型工具记录。
    assert result.evidence_kind == EVENT_TOOL_REPORT
    assert result.status == STATUS_REJECTED


def test_low_coverage_verified_from_memory_report(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    artifact = make_artifact(
        test_report=make_test_report_block(coverage=45.0)
    )
    validator = make_validator(workspace, artifact=artifact)

    result = validator.validate(make_tool_report_finding())

    assert result.status == STATUS_VERIFIED
    assert result.finding.file_path is None
    assert result.finding.start_line is None


def test_low_coverage_above_minimum_is_rejected(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    validator = make_validator(workspace)

    result = validator.validate(make_tool_report_finding())

    assert result.status == STATUS_REJECTED
    assert any("coverage" in reason for reason in result.reasons)


def test_low_coverage_with_null_coverage_is_rejected(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    artifact = make_artifact(
        test_report=make_test_report_block(
            execution_status="not_executed", reason="external repo"
        )
    )
    validator = make_validator(workspace, artifact=artifact)

    result = validator.validate(make_tool_report_finding())

    assert result.status == STATUS_REJECTED


def test_low_coverage_must_not_fake_file_location(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    artifact = make_artifact(
        test_report=make_test_report_block(coverage=45.0)
    )
    validator = make_validator(workspace, artifact=artifact)

    result = validator.validate(
        make_finding(
            agent_name="TestingAgent",
            category="low_coverage",
            file_path=APP_FILE,
            start_line=9,
            evidence=SQL_EVIDENCE,
            tool_evidence=[],
        )
    )

    # 伪造位置不能让它变成 verified；没有工具证据只能是 unverified。
    assert result.status == STATUS_UNVERIFIED
    assert result.evidence_kind == EVENT_CODE_LOCATION


def test_test_failure_counts_drive_verification(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    failed_artifact = make_artifact(
        test_report=make_test_report_block(passed=2, failed=1)
    )
    ok_artifact = make_artifact(
        test_report=make_test_report_block(passed=3, failed=0)
    )
    finding = make_tool_report_finding(
        category="test_failure",
        tool_name="pytest",
        ref="test_report.json#/counts",
    )

    rejected = make_validator(workspace, artifact=ok_artifact).validate(
        finding
    )
    verified = make_validator(
        workspace, artifact=failed_artifact
    ).validate(finding)

    assert rejected.status == STATUS_REJECTED
    assert verified.status == STATUS_VERIFIED


def test_missing_tests_requires_zero_collected(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    empty_artifact = make_artifact(
        test_report=make_test_report_block(passed=0, failed=0, skipped=0)
    )
    populated = make_artifact()
    finding = make_tool_report_finding(
        category="missing_tests",
        tool_name="pytest",
        ref="test_report.json#/counts/total",
    )

    verified = make_validator(
        workspace, artifact=empty_artifact
    ).validate(finding)
    rejected = make_validator(workspace, artifact=populated).validate(
        finding
    )

    assert verified.status == STATUS_VERIFIED
    assert rejected.status == STATUS_REJECTED


def test_located_test_finding_uses_test_record(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    validator = make_validator(workspace)

    result = validator.validate(
        make_finding(
            finding_id="TST-0002",
            agent_name="TestingAgent",
            category="test_failure",
            severity="medium",
            file_path=TEST_FILE,
            start_line=3,
            end_line=3,
            evidence="def test_ok():",
            tool_evidence=[
                ToolEvidence(
                    tool_name="pytest",
                    raw_output_ref="test_report.json#/records/0",
                )
            ],
        )
    )

    assert result.status == STATUS_VERIFIED
    assert result.false_positive is False


# ----------------------------------------------------------------------
# V6 / V7


def test_v6_downgrades_test_code_false_positive(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    artifact = make_artifact(
        security_records=[tool_record(file_path=TEST_FILE, line=3)]
    )
    validator = make_validator(workspace, artifact=artifact)

    result = validator.validate(
        make_finding(
            agent_name="SecurityAgent",
            category="sql_injection",
            file_path=TEST_FILE,
            start_line=3,
            end_line=3,
            evidence="def test_ok():",
            tool_evidence=[
                ToolEvidence(tool_name="bandit", rule_id="B608",
                             raw_output_ref=(
                                 "static_analysis.json#/agents/security/"
                                 "tools/bandit/findings/0"
                             ))
            ],
        )
    )

    assert result.false_positive is True
    assert result.status == STATUS_UNVERIFIED


def test_v7_redacts_secret_evidence_and_description(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    artifact = make_artifact(
        security_records=[tool_record(line=5, rule_id="B105")]
    )
    validator = make_validator(workspace, artifact=artifact)

    result = validator.validate(
        make_finding(
            agent_name="SecurityAgent",
            category="hardcoded_secret",
            severity="high",
            file_path=APP_FILE,
            start_line=5,
            end_line=5,
            evidence='api_key = "sample-token-value"',
            description='password = "supersecret" is committed',
            tool_evidence=[
                ToolEvidence(
                    tool_name="bandit",
                    rule_id="B105",
                    raw_output_ref=(
                        "static_analysis.json#/agents/security/tools/"
                        "bandit/findings/0"
                    ),
                )
            ],
        )
    )

    assert result.status == STATUS_VERIFIED
    assert "sample-token-value" not in result.finding.evidence
    assert "supersecret" not in result.finding.description
    assert "[REDACTED]" in result.finding.evidence


# ----------------------------------------------------------------------
# 自证与不可变性


def test_llm_self_confirmation_never_becomes_verified(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    validator = make_validator(workspace)

    result = validator.validate(
        make_finding(
            file_path=APP_FILE,
            start_line=9,
            evidence=SQL_EVIDENCE,
            tool_evidence=[],
            confidence=1.0,
            verification_status="verified",
        )
    )

    assert result.status == STATUS_UNVERIFIED
    assert result.finding.verification_status == STATUS_UNVERIFIED


def test_original_finding_is_not_mutated(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    validator = make_validator(workspace)
    original = make_finding(
        file_path=APP_FILE,
        start_line=9,
        evidence=SQL_EVIDENCE,
        tool_evidence=[bandit_evidence()],
    )

    validator.validate(original)

    assert original.verification_status == "unverified"
