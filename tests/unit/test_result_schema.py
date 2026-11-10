"""阶段 0 执行结果合同单元测试。

覆盖 docs/task_contracts.md 中属于 Schema 层的规则：
FD-01, FD-02, FD-03, FD-04, FD-05, FD-06, FD-07, FD-08；
RS-01, RS-02, RS-03, RS-04, RS-05, RS-06, RS-07, RS-08, RS-09, RS-10。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from code_review.schemas import AgentResult, Finding, ToolEvidence

COMMIT_SHA = "9fceb02d0ae598e95dc970b74767f19372d61af8"

TOOL_EVIDENCE = {
    "tool_name": "bandit",
    "rule_id": "B608",
    "tool_version": None,
    "raw_output_ref": "reports/review-001/static_analysis.json#/bandit/results/0",
}


def make_finding(**overrides):
    """构造最小合法 Finding（A 类：代码位置证据）。"""

    data = {
        "finding_id": "SEC-001",
        "agent_name": "SecurityAgent",
        "category": "sql_injection",
        "severity": "high",
        "title": "Potential SQL Injection",
        "description": "SQL 查询直接拼接用户输入 user_id。",
        "file_path": "src/database.py",
        "start_line": 25,
        "end_line": 25,
        "evidence": "query = f'SELECT * FROM users WHERE id={user_id}'",
        "recommendation": "使用参数化查询。",
        "confidence": 0.98,
    }
    data.update(overrides)
    return Finding.model_validate(data)


def make_result(**overrides):
    """构造最小合法 AgentResult。"""

    data = {
        "task_id": "task-security-001",
        "review_id": "review-001",
        "agent_name": "SecurityAgent",
        "status": "completed",
        "commit_sha": COMMIT_SHA,
        "summary": "未发现安全问题。",
        "execution_time": 1.2,
    }
    data.update(overrides)
    return AgentResult.model_validate(data)


# docs/task_contracts.md §5.6 的合法示例 A / B / C。
_DOC_FINDING_EXAMPLES = [
    {
        "finding_id": "SEC-001",
        "agent_name": "SecurityAgent",
        "category": "sql_injection",
        "severity": "critical",
        "title": "Potential SQL Injection",
        "description": "SQL 查询直接拼接用户输入 user_id，攻击者可构造恶意输入篡改查询语义。",
        "file_path": "src/database.py",
        "start_line": 25,
        "end_line": 25,
        "evidence": "query = f'SELECT * FROM users WHERE id={user_id}'",
        "tool_evidence": [
            {
                "tool_name": "bandit",
                "rule_id": "B608",
                "tool_version": None,
                "raw_output_ref": "reports/review-001/static_analysis.json#/bandit/results/0",
            }
        ],
        "recommendation": "使用参数化查询，例如 cursor.execute('SELECT * FROM users WHERE id = %s', (user_id,))。",
        "confidence": 0.98,
        "verification_status": "unverified",
        "merged_from": [],
    },
    {
        "finding_id": "SEC-002",
        "agent_name": "SecurityAgent",
        "category": "hardcoded_secret",
        "severity": "high",
        "title": "Hardcoded API key",
        "description": "配置文件中直接写入了服务访问密钥。",
        "file_path": "src/config.py",
        "start_line": 18,
        "end_line": 18,
        "evidence": 'API_KEY = "sk-****REDACTED"',
        "tool_evidence": [],
        "recommendation": "改为从环境变量读取，并轮换已泄露的密钥。",
        "confidence": 0.9,
        "verification_status": "unverified",
        "merged_from": [],
    },
    {
        "finding_id": "TST-001",
        "agent_name": "TestingAgent",
        "category": "low_coverage",
        "severity": "medium",
        "title": "项目整体测试覆盖率低于阈值",
        "description": "Coverage.py 报告整体覆盖率为 41.2%，低于配置阈值 60%。",
        "file_path": None,
        "start_line": None,
        "end_line": None,
        "evidence": "TOTAL coverage: 41.2%",
        "tool_evidence": [
            {
                "tool_name": "coverage",
                "rule_id": None,
                "tool_version": "7.x",
                "raw_output_ref": "reports/review-001/test_report.json#/coverage/total",
            }
        ],
        "recommendation": "为核心业务模块补充单元测试。",
        "confidence": 1.0,
        "verification_status": "unverified",
        "merged_from": [],
    },
]

# docs/task_contracts.md §5.6 的非法示例：只有自然语言结论。
_ILLEGAL_FINDING_EXAMPLE = {
    "finding_id": "SEC-099",
    "agent_name": "SecurityAgent",
    "category": "sql_injection",
    "severity": "critical",
    "title": "可能存在 SQL 注入",
    "description": "我认为这个项目的数据库层不太安全。",
    "file_path": None,
    "start_line": None,
    "end_line": None,
    "evidence": "感觉不安全",
    "tool_evidence": [],
    "recommendation": "请检查。",
    "confidence": 0.7,
}

# docs/task_contracts.md §8.3 的三个完整示例。
_DOC_RESULT_EXAMPLES = [
    {
        "schema_version": "1.0",
        "task_id": "task-security-001",
        "parent_task_id": "task-main-001",
        "review_id": "review-001",
        "agent_name": "SecurityAgent",
        "status": "completed",
        "commit_sha": COMMIT_SHA,
        "score": 60.0,
        "findings": [
            {
                "finding_id": "SEC-001",
                "agent_name": "SecurityAgent",
                "category": "sql_injection",
                "severity": "critical",
                "title": "Potential SQL Injection",
                "description": "SQL 查询直接拼接用户输入 user_id。",
                "file_path": "src/database.py",
                "start_line": 25,
                "end_line": 25,
                "evidence": "query = f'SELECT * FROM users WHERE id={user_id}'",
                "tool_evidence": [
                    {
                        "tool_name": "bandit",
                        "rule_id": "B608",
                        "tool_version": None,
                        "raw_output_ref": "reports/review-001/static_analysis.json#/bandit/results/0",
                    }
                ],
                "recommendation": "使用参数化查询。",
                "confidence": 0.98,
                "verification_status": "unverified",
                "merged_from": [],
            },
            {
                "finding_id": "SEC-002",
                "agent_name": "SecurityAgent",
                "category": "hardcoded_secret",
                "severity": "high",
                "title": "Hardcoded API key",
                "description": "配置文件中直接写入了服务访问密钥。",
                "file_path": "src/config.py",
                "start_line": 18,
                "end_line": 18,
                "evidence": 'API_KEY = "sk-****REDACTED"',
                "tool_evidence": [],
                "recommendation": "改为从环境变量读取，并轮换已泄露的密钥。",
                "confidence": 0.9,
                "verification_status": "unverified",
                "merged_from": [],
            },
        ],
        "summary": "发现 1 个 critical 与 1 个 high 级别的安全问题。",
        "execution_time": 18.6,
        "error": None,
        "metadata": {"sub_tasks": []},
    },
    {
        "schema_version": "1.0",
        "task_id": "task-testing-001",
        "parent_task_id": "task-main-001",
        "review_id": "review-001",
        "agent_name": "TestingAgent",
        "status": "partial",
        "commit_sha": COMMIT_SHA,
        "score": None,
        "findings": [
            {
                "finding_id": "TST-001",
                "agent_name": "TestingAgent",
                "category": "test_failure",
                "severity": "high",
                "title": "单元测试失败：test_login_invalid_password",
                "description": "pytest 执行结果显示该用例失败。",
                "file_path": "tests/test_auth.py",
                "start_line": 42,
                "end_line": 48,
                "evidence": "AssertionError: assert 200 == 401",
                "tool_evidence": [
                    {
                        "tool_name": "pytest",
                        "rule_id": None,
                        "tool_version": None,
                        "raw_output_ref": "reports/review-001/test_report.json#/pytest/failures/0",
                    }
                ],
                "recommendation": "检查登录接口对错误密码的处理逻辑。",
                "confidence": 1.0,
                "verification_status": "unverified",
                "merged_from": [],
            }
        ],
        "summary": "pytest 已执行，覆盖率统计失败，覆盖率结果缺失。",
        "execution_time": 31.2,
        "error": {
            "error_type": "tool_error",
            "message": "coverage 命令退出码为 1，未生成覆盖率数据文件",
            "retryable": False,
            "occurred_at": "2026-11-08T10:01:40Z",
            "details": {"tool": "coverage", "exit_code": 1},
        },
        "metadata": {},
    },
    {
        "schema_version": "1.0",
        "task_id": "task-performance-001",
        "parent_task_id": "task-main-001",
        "review_id": "review-001",
        "agent_name": "PerformanceAgent",
        "status": "failed",
        "commit_sha": COMMIT_SHA,
        "score": None,
        "findings": [],
        "summary": "性能分析任务超时，重试 2 次后仍未完成。",
        "execution_time": 360.0,
        "error": {
            "error_type": "timeout",
            "message": "单次执行超过 120 秒，已达到最大重试次数",
            "retryable": True,
            "occurred_at": "2026-11-08T10:07:00Z",
            "details": {"retry_count": 2, "max_retries": 2},
        },
        "metadata": {},
    },
]


def test_code_location_evidence_passes_FD_01_FD_02():
    finding = make_finding(severity="critical")
    assert finding.file_path == "src/database.py"
    assert finding.verification_status == "unverified"


def test_tool_evidence_only_passes_FD_01():
    finding = make_finding(
        file_path=None,
        start_line=None,
        end_line=None,
        severity="medium",
        tool_evidence=[TOOL_EVIDENCE],
    )
    assert finding.file_path is None
    assert len(finding.tool_evidence) == 1


def test_finding_without_any_evidence_rejected_FD_01():
    with pytest.raises(ValidationError, match="evidence"):
        make_finding(
            file_path=None,
            start_line=None,
            end_line=None,
            severity="medium",
            tool_evidence=[],
        )


@pytest.mark.parametrize("severity", ["critical", "high"])
def test_high_severity_requires_code_location_FD_02(severity):
    with pytest.raises(ValidationError, match="critical/high"):
        make_finding(
            severity=severity,
            file_path=None,
            start_line=None,
            end_line=None,
            tool_evidence=[TOOL_EVIDENCE],
        )


@pytest.mark.parametrize(
    ("file_path", "start_line"),
    [("src/database.py", None), (None, 25)],
)
def test_file_path_and_start_line_must_be_provided_together_FD_03(
    file_path, start_line
):
    with pytest.raises(ValidationError, match="file_path and start_line"):
        make_finding(file_path=file_path, start_line=start_line)


def test_end_line_before_start_line_rejected_FD_04():
    with pytest.raises(ValidationError, match="end_line"):
        make_finding(start_line=25, end_line=24)


@pytest.mark.parametrize(("start_line", "end_line"), [(0, 1), (-1, 1), (1, 0)])
def test_line_numbers_must_be_positive_FD_04(start_line, end_line):
    with pytest.raises(ValidationError):
        make_finding(start_line=start_line, end_line=end_line)


@pytest.mark.parametrize(
    "file_path",
    [
        "/etc/passwd",
        "../secret.py",
        "src\\database.py",
        "C:/repo/src/database.py",
    ],
)
def test_invalid_file_paths_rejected_FD_05(file_path):
    with pytest.raises(ValidationError):
        make_finding(file_path=file_path)


@pytest.mark.parametrize("confidence", [-0.01, 1.01, 2])
def test_confidence_bounds_FD_06(confidence):
    with pytest.raises(ValidationError):
        make_finding(confidence=confidence)


@pytest.mark.parametrize(
    "field",
    ["title", "description", "evidence", "recommendation"],
)
def test_blank_text_fields_rejected_FD_07(field):
    with pytest.raises(ValidationError):
        make_finding(**{field: "   "})


def test_invalid_severity_rejected_FD_08():
    with pytest.raises(ValidationError):
        make_finding(severity="blocker")


def test_title_length_limit():
    with pytest.raises(ValidationError):
        make_finding(title="x" * 201)


def test_tool_evidence_requires_name_and_reference():
    with pytest.raises(ValidationError):
        ToolEvidence.model_validate(
            {"tool_name": " ", "raw_output_ref": " "}
        )


@pytest.mark.parametrize("example", _DOC_FINDING_EXAMPLES)
def test_document_finding_examples_validate(example):
    finding = Finding.model_validate(example)
    assert finding.finding_id == example["finding_id"]


def test_document_illegal_finding_example_rejected():
    with pytest.raises(ValidationError):
        Finding.model_validate(_ILLEGAL_FINDING_EXAMPLE)


def test_completed_result_with_nested_findings_RS_06_RS_07():
    result = make_result(
        score=60.0,
        findings=[make_finding(severity="critical")],
    )
    assert result.status == "completed"
    assert result.findings[0].agent_name == result.agent_name


def test_completed_result_with_error_rejected_RS_01():
    with pytest.raises(ValidationError, match="completed"):
        make_result(
            status="completed",
            error={
                "error_type": "internal",
                "message": "unexpected",
                "retryable": False,
            },
        )


def test_failed_result_requires_error_RS_02():
    with pytest.raises(ValidationError, match="failed result requires error"):
        make_result(status="failed")


def test_failed_result_must_not_have_score_RS_02():
    with pytest.raises(ValidationError, match="score"):
        make_result(
            status="failed",
            score=50.0,
            error={
                "error_type": "timeout",
                "message": "执行超时",
                "retryable": True,
            },
        )


def test_failed_result_must_not_have_findings_RS_02():
    with pytest.raises(ValidationError, match="findings"):
        make_result(
            status="failed",
            findings=[make_finding(severity="critical")],
            error={
                "error_type": "timeout",
                "message": "执行超时",
                "retryable": True,
            },
        )


def test_partial_result_requires_error_RS_03():
    with pytest.raises(ValidationError, match="partial"):
        make_result(status="partial")


def test_partial_result_with_error_is_valid_RS_03():
    result = make_result(
        status="partial",
        error={
            "error_type": "tool_error",
            "message": "覆盖率工具失败",
            "retryable": False,
        },
    )
    assert result.status == "partial"


@pytest.mark.parametrize("score", [-0.1, 100.1, 101])
def test_score_bounds_RS_04(score):
    with pytest.raises(ValidationError):
        make_result(score=score)


def test_negative_execution_time_rejected_RS_05():
    with pytest.raises(ValidationError):
        make_result(execution_time=-0.1)


def test_duplicate_finding_ids_rejected_RS_06():
    first = make_finding(finding_id="SEC-001")
    second = make_finding(finding_id="SEC-001", title="重复编号")

    with pytest.raises(ValidationError, match="finding_id"):
        make_result(findings=[first, second])


def test_finding_agent_name_must_match_result_RS_07():
    with pytest.raises(ValidationError, match="agent_name"):
        make_result(findings=[make_finding(agent_name="QualityAgent")])


@pytest.mark.parametrize(
    "commit_sha",
    [
        "abc123",
        "9FCEB02D0AE598E95DC970B74767F19372D61AF8",
        "z" * 40,
        "9fceb02d0ae598e95dc970b74767f19372d61af",
    ],
)
def test_invalid_commit_sha_rejected_RS_08(commit_sha):
    with pytest.raises(ValidationError, match="commit_sha"):
        make_result(commit_sha=commit_sha)


def test_default_findings_lists_not_shared_RS_09():
    first = make_result()
    second = make_result()

    first.findings.append(make_finding())
    assert second.findings == []


def test_agent_result_json_roundtrip_RS_10():
    result = make_result(
        score=60.0,
        findings=[make_finding(severity="critical")],
        metadata={"tool_versions": {"bandit": "1.7"}},
    )

    restored = AgentResult.model_validate_json(result.model_dump_json())
    assert restored == result


@pytest.mark.parametrize("example", _DOC_RESULT_EXAMPLES)
def test_document_agent_result_examples_validate(example):
    result = AgentResult.model_validate(example)
    assert result.task_id == example["task_id"]


def test_description_and_evidence_length_limits_JS_11():
    with pytest.raises(ValidationError):
        make_finding(description="x" * 4001)

    with pytest.raises(ValidationError):
        make_finding(evidence="x" * 4001)

    assert len(make_finding(description="x" * 4000).description) == 4000
    assert len(make_finding(evidence="x" * 4000).evidence) == 4000


def test_end_line_requires_start_line_FD_04():
    with pytest.raises(ValidationError, match="end_line requires start_line"):
        make_finding(file_path=None, start_line=None, end_line=25)


@pytest.mark.parametrize("status", ["pending", "VERIFIED", "unknown"])
def test_invalid_verification_status_rejected(status):
    with pytest.raises(ValidationError):
        make_finding(verification_status=status)


def test_tool_evidence_entries_must_be_valid():
    with pytest.raises(ValidationError):
        make_finding(tool_evidence=[{"tool_name": " "}])


def test_finding_mutable_defaults_not_shared_RS_09():
    first = make_finding()
    second = make_finding()

    first.tool_evidence.append(ToolEvidence.model_validate(TOOL_EVIDENCE))
    first.merged_from.append("SEC-000")

    assert second.tool_evidence == []
    assert second.merged_from == []


def test_optional_fields_serialize_as_null_JS_05():
    """可选字段未赋值时序列化为 null，不省略键。"""

    finding = make_finding(
        severity="medium",
        file_path=None,
        start_line=None,
        end_line=None,
        tool_evidence=[TOOL_EVIDENCE],
    )
    dumped = finding.model_dump(mode="json")
    assert "file_path" in dumped and dumped["file_path"] is None
    assert "start_line" in dumped and dumped["start_line"] is None
    assert "end_line" in dumped and dumped["end_line"] is None

    result = make_result().model_dump(mode="json")
    assert "parent_task_id" in result and result["parent_task_id"] is None
    assert "score" in result and result["score"] is None
    assert "error" in result and result["error"] is None
