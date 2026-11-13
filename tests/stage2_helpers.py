"""Stage 2 测试辅助：内部合同、Fake Agent 与 Fake LLM。

本模块不访问网络、不调用真实 LLM、不执行外部仓库代码。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from code_review.agents.base import BaseAgent
from code_review.agents.contracts import (
    AgentExecution,
    AgentRunOutput,
    ArtifactData,
    UsageSummary,
    WorkerDispatch,
    WorkerEvidence,
    WorkerRuntime,
    WorkerTiming,
)
from code_review.agents.manager import AGENT_SPECS, ManagerAgent, TaskPlan
from code_review.graph.state import (
    RepositoryContext,
    ReviewState,
    build_initial_state,
)
from code_review.graph.workflow import GraphDependencies
from code_review.reporting.report_generator import InventorySummary
from code_review.schemas.report import TestSummary
from code_review.schemas.result import AgentResult, Finding, ToolEvidence
from code_review.schemas.task import AgentTask, ErrorInfo
from code_review.tools.base import (
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolFinding,
)
from code_review.tools.test_runner import (
    CoverageFileReport,
    TestExecutionResult,
    TestExecutionStatus,
    TestRecord,
)
from config.review_rules import ReviewRules, load_review_rules

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
COMMIT_SHA = "a" * 40
REVIEW_ID = "review-stage2-001"
ROOT_TASK_ID = "task-root"


def make_review_rules() -> ReviewRules:
    """加载仓库真实规则文件，确保测试与配置一致。"""
    return load_review_rules()


def make_agent_task(
    *,
    agent_name: str = "SecurityAgent",
    task_type: str = "security_review",
    review_id: str = REVIEW_ID,
    task_id: str = "task-security",
    parent_task_id: str | None = ROOT_TASK_ID,
    description: str = "Review the repository for security issues.",
    input_data: dict[str, Any] | None = None,
    expected_output: dict[str, Any] | None = None,
    status: str = "pending",
    max_retries: int = 0,
    created_at: datetime = NOW,
) -> AgentTask:
    payload = {
        "task_id": task_id,
        "parent_task_id": parent_task_id,
        "review_id": review_id,
        "agent_name": agent_name,
        "task_type": task_type,
        "description": description,
        "input_data": input_data if input_data is not None else {},
        "expected_output": expected_output if expected_output is not None else {},
        "status": status,
        "max_retries": max_retries,
        "created_at": created_at,
    }
    if status == "running":
        payload["started_at"] = created_at
    return AgentTask.model_validate(payload)


def make_worker_runtime(
    workspace_path: Path,
    *,
    allowed_files: tuple[str, ...] = ("pkg/app.py",),
    commit_sha: str = COMMIT_SHA,
    language: str = "python",
    review_id: str = REVIEW_ID,
    rules: ReviewRules | None = None,
    trace_id: str | None = None,
) -> WorkerRuntime:
    return WorkerRuntime(
        workspace_path=workspace_path,
        allowed_files=allowed_files,
        commit_sha=commit_sha,
        language=language,
        review_id=review_id,
        rules=rules or make_review_rules(),
        trace_id=trace_id,
    )


def make_dispatch(
    *,
    workspace_path: Path | None = None,
    task: AgentTask | None = None,
    runtime: WorkerRuntime | None = None,
) -> WorkerDispatch:
    resolved_task = task or make_agent_task()
    resolved_runtime = runtime or make_worker_runtime(
        workspace_path or Path("."),
        review_id=resolved_task.review_id,
        commit_sha=COMMIT_SHA,
    )
    return WorkerDispatch(task=resolved_task, runtime=resolved_runtime)


def make_tool_evidence(
    *,
    tool_name: str = "bandit",
    rule_id: str | None = "B608",
    tool_version: str | None = "1.9.4",
    raw_output_ref: str = (
        "static_analysis.json#/agents/security/tools/bandit/findings/0"
    ),
) -> ToolEvidence:
    return ToolEvidence(
        tool_name=tool_name,
        rule_id=rule_id,
        tool_version=tool_version,
        raw_output_ref=raw_output_ref,
    )


def make_finding(
    *,
    finding_id: str = "SEC-0001",
    agent_name: str = "SecurityAgent",
    category: str = "sql_injection",
    severity: str = "medium",
    title: str = "Potential SQL injection",
    description: str = "String concatenation is used to build SQL.",
    file_path: str | None = "pkg/app.py",
    start_line: int | None = 12,
    end_line: int | None = 12,
    evidence: str = "cursor.execute('SELECT ... ' + user_input)",
    tool_evidence: list[ToolEvidence] | None = None,
    recommendation: str = "Use parameterized queries.",
    confidence: float = 0.8,
    verification_status: str = "unverified",
) -> Finding:
    if tool_evidence is None:
        tool_evidence = [make_tool_evidence()]
    return Finding(
        finding_id=finding_id,
        agent_name=agent_name,
        category=category,
        severity=severity,
        title=title,
        description=description,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        evidence=evidence,
        tool_evidence=tool_evidence,
        recommendation=recommendation,
        confidence=confidence,
        verification_status=verification_status,
    )


def make_agent_result(
    task: AgentTask,
    *,
    status: str = "completed",
    score: float | None = 85.0,
    findings: list[Finding] | None = None,
    summary: str = "Security analysis completed.",
    commit_sha: str = COMMIT_SHA,
    execution_time: float = 0.0,
    error: ErrorInfo | None = None,
    metadata: dict[str, Any] | None = None,
) -> AgentResult:
    if status == "failed":
        if error is None:
            error = ErrorInfo(
                error_type="agent_execution_error",
                message="simulated failure",
                retryable=False,
                occurred_at=NOW,
            )
        score = None
        findings = []
    elif status == "partial" and error is None:
        error = ErrorInfo(
            error_type="partial_execution",
            message="LLM analysis unavailable",
            retryable=False,
            occurred_at=NOW,
        )
    return AgentResult(
        task_id=task.task_id,
        parent_task_id=task.parent_task_id,
        review_id=task.review_id,
        agent_name=task.agent_name,
        status=status,
        commit_sha=commit_sha,
        score=score,
        findings=findings or [],
        summary=summary,
        execution_time=execution_time,
        error=error,
        metadata=metadata or {},
    )


def make_worker_evidence(
    *,
    agent_name: str = "SecurityAgent",
    static_analysis: dict[str, Any] | None = None,
    test_report: dict[str, Any] | None = None,
    usage: UsageSummary | None = None,
    warnings: tuple[str, ...] = (),
) -> WorkerEvidence:
    return WorkerEvidence(
        agent_name=agent_name,
        static_analysis=static_analysis
        if static_analysis is not None
        else {
            "agents": {
                "security": {
                    "tools": {
                        "bandit": {
                            "findings": [
                                {
                                    "rule_id": "B608",
                                    "severity": "MEDIUM",
                                }
                            ]
                        }
                    }
                }
            }
        },
        test_report=test_report,
        usage=usage or UsageSummary(),
        warnings=warnings,
    )


def make_artifact_data(
    *,
    static_analysis: dict[str, Any] | None = None,
    test_report: dict[str, Any] | None = None,
) -> ArtifactData:
    return ArtifactData(
        static_analysis=static_analysis
        if static_analysis is not None
        else {
            "agents": {
                "security": {
                    "tools": {
                        "bandit": {
                            "findings": [
                                {
                                    "rule_id": "B608",
                                    "severity": "MEDIUM",
                                }
                            ]
                        }
                    }
                }
            }
        },
        test_report=test_report
        if test_report is not None
        else {
            "execution_status": "not_executed",
            "coverage": None,
            "counts": {"passed": None, "failed": None},
        },
    )


@dataclass(frozen=True)
class FakeCompletion:
    content: str
    finish_reason: str | None = "stop"
    usage: dict[str, int] | None = None
    model: str | None = "fake-model"


class FakeLLMClient:
    """按预设返回内容的同步 Fake 客户端，记录全部调用参数。"""

    def __init__(
        self,
        *,
        content: str = '{"findings": [], "summary": "ok"}',
        usage: dict[str, int] | None = None,
        finish_reason: str | None = "stop",
        error: Exception | None = None,
    ) -> None:
        self.content = content
        self.usage = usage
        self.finish_reason = finish_reason
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
        temperature: float,
        timeout_seconds: float,
    ) -> FakeCompletion:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "max_output_tokens": max_output_tokens,
                "temperature": temperature,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.error is not None:
            raise self.error
        return FakeCompletion(
            content=self.content,
            finish_reason=self.finish_reason,
            usage=self.usage,
        )


class FakeAgent(BaseAgent):
    """可配置成功结果、异常或延迟的 BaseAgent 子类。"""

    def __init__(
        self,
        *,
        result_factory: Callable[[WorkerDispatch], AgentRunOutput] | None = None,
        error: Exception | None = None,
        delay: float = 0.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            agent_name=kwargs.pop("agent_name", "SecurityAgent"),
            task_type=kwargs.pop("task_type", "security_review"),
            **kwargs,
        )
        self._result_factory = result_factory
        self._error = error
        self._delay = delay

    async def _run(self, dispatch: WorkerDispatch) -> AgentRunOutput:
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        if self._result_factory is not None:
            return self._result_factory(dispatch)
        return AgentRunOutput(
            result=make_agent_result(dispatch.task),
            evidence=make_worker_evidence(agent_name=self.agent_name),
        )


# ----------------------------------------------------------------------
# Stage 2.2 tool and test-runner fakes


def make_tool_finding(
    *,
    tool_name: str = "bandit",
    rule_id: str = "B608",
    file_path: str = "pkg/app.py",
    line: int | None = 12,
    end_line: int | None = None,
    column: int | None = 5,
    severity: str | None = "MEDIUM",
    confidence: str | None = "HIGH",
    message: str = "possible SQL injection",
    metadata: dict[str, Any] | None = None,
) -> ToolFinding:
    return ToolFinding(
        tool_name=tool_name,
        rule_id=rule_id,
        file_path=file_path,
        message=message,
        line=line,
        end_line=end_line,
        column=column,
        severity=severity,
        confidence=confidence,
        metadata=metadata or {},
    )


def make_tool_result(
    *,
    tool_name: str = "bandit",
    status: str | ToolExecutionStatus = "success",
    findings: tuple[ToolFinding, ...] | None = None,
    tool_version: str | None = "1.9.4",
    stdout: str = "",
    stderr: str = "",
    error: ErrorInfo | None = None,
    analyzed_file_count: int = 1,
    duration_ms: int = 10,
    stdout_truncated: bool = False,
    stderr_truncated: bool = False,
    findings_truncated: bool = False,
) -> ToolExecutionResult:
    execution_status = (
        status
        if isinstance(status, ToolExecutionStatus)
        else ToolExecutionStatus(status)
    )
    return ToolExecutionResult(
        tool_name=tool_name,
        tool_version=tool_version,
        execution_status=execution_status,
        exit_code=0 if execution_status is ToolExecutionStatus.SUCCESS else 1,
        started_at=NOW,
        finished_at=NOW,
        duration_ms=duration_ms,
        stdout=stdout,
        stderr=stderr,
        findings=findings or (),
        error=error,
        analyzed_file_count=analyzed_file_count,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        findings_truncated=findings_truncated,
    )


class FakeAnalysisTool:
    """同步 Fake 静态分析工具，记录 workspace 与 files。"""

    def __init__(
        self,
        *,
        result: ToolExecutionResult | None = None,
        error: Exception | None = None,
        tool_name: str = "bandit",
    ) -> None:
        self.result = result
        self.error = error
        self.tool_name = tool_name
        self.calls: list[dict[str, Any]] = []

    def run(
        self, workspace_path: Path, files: list[str]
    ) -> ToolExecutionResult:
        self.calls.append(
            {
                "workspace_path": workspace_path,
                "files": tuple(files),
            }
        )
        if self.error is not None:
            raise self.error
        if self.result is not None:
            return self.result
        return make_tool_result(tool_name=self.tool_name)


def make_test_execution_result(
    *,
    status: str | TestExecutionStatus | None = None,
    summary: TestSummary | None = None,
    passed: int = 3,
    failed: int = 0,
    skipped: int = 0,
    coverage: float | None = 90.0,
    collected_tests: int | None = None,
    records: tuple[TestRecord, ...] = (),
    coverage_files: tuple[CoverageFileReport, ...] = (),
    fixture_name: str | None = None,
    fixture_version: str | None = None,
    fixture_manifest_sha256: str | None = None,
    read_only_verified: bool | None = True,
    modified_paths: tuple[str, ...] = (),
    pytest_version: str | None = "9.2.0",
    coverage_version: str | None = "7.17.2",
    test_duration_seconds: float | None = 0.1,
    reason: str | None = None,
    error: ErrorInfo | None = None,
) -> TestExecutionResult:
    if status is None:
        execution_status = TestExecutionStatus.EXECUTED
    elif isinstance(status, TestExecutionStatus):
        execution_status = status
    else:
        execution_status = TestExecutionStatus(status)

    if summary is None:
        if execution_status is TestExecutionStatus.EXECUTED:
            summary = TestSummary(
                execution_status="executed",
                passed=passed,
                failed=failed,
                skipped=skipped,
                coverage=coverage,
                source="pytest+coverage" if coverage is not None else "pytest",
            )
        elif execution_status is TestExecutionStatus.NOT_EXECUTED:
            summary = TestSummary(
                execution_status="not_executed",
                reason=reason or "external repository tests are not executed",
            )
        else:
            summary = TestSummary(
                execution_status="failed",
                reason=reason or "test execution failed",
            )

    if collected_tests is None and execution_status is TestExecutionStatus.EXECUTED:
        collected_tests = passed + failed + skipped

    return TestExecutionResult(
        status=execution_status,
        summary=summary,
        fixture_name=fixture_name,
        fixture_version=fixture_version,
        fixture_manifest_sha256=fixture_manifest_sha256,
        collected_tests=collected_tests,
        test_records=records,
        test_records_truncated=False,
        coverage_files=coverage_files,
        coverage_files_truncated=False,
        read_only_verified=read_only_verified,
        modified_paths=modified_paths,
        pytest_version=pytest_version,
        coverage_version=coverage_version,
        exit_code=0,
        coverage_exit_code=0,
        test_duration_seconds=test_duration_seconds,
        started_at=NOW,
        finished_at=NOW + timedelta(seconds=test_duration_seconds or 0.0),
        duration_ms=int((test_duration_seconds or 0.0) * 1000),
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        error=error,
    )


class FakeTestRunner:
    """同步 Fake TestRunner，记录 trusted_fixture 参数。"""

    def __init__(
        self,
        *,
        result: TestExecutionResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[str | None] = []

    def execute(
        self, *, trusted_fixture: str | None = None
    ) -> TestExecutionResult:
        self.calls.append(trusted_fixture)
        if self.error is not None:
            raise self.error
        if self.result is not None:
            return self.result
        return make_test_execution_result()


# ----------------------------------------------------------------------
# Stage 2.2 execution helpers


def make_execution(
    *,
    task: AgentTask,
    status: str = "completed",
    findings: list[Finding] | None = None,
    evidence: WorkerEvidence | None = None,
    score: float | None = 85.0,
    started_at: datetime = NOW,
    duration_seconds: float = 1.0,
    metadata: dict[str, Any] | None = None,
) -> AgentExecution:
    resolved_evidence = evidence or make_worker_evidence(
        agent_name=task.agent_name
    )
    result = make_agent_result(
        task,
        status=status,
        score=score,
        findings=findings,
        metadata=metadata,
    )
    timing = WorkerTiming(
        agent_name=task.agent_name,
        task_id=task.task_id,
        started_at=started_at,
        finished_at=started_at + timedelta(seconds=duration_seconds),
        duration_seconds=duration_seconds,
        status=status,
    )
    return AgentExecution(
        task=task,
        result=result,
        evidence=resolved_evidence,
        timing=timing,
    )


def _evidence_tool_block(tool_name: str, rule_id: str) -> dict[str, Any]:
    return {
        "tool_name": tool_name,
        "tool_version": "1.9.4",
        "execution_status": "findings",
        "findings": [
            {
                "rule_id": rule_id,
                "file_path": "pkg/app.py",
                "line": 12,
                "end_line": 12,
                "severity": "MEDIUM",
                "message": "sample tool finding",
                "metadata": {},
            }
        ],
    }


def make_plan_execution(
    plan: TaskPlan,
    dimension: str,
    *,
    status: str = "completed",
    usage: UsageSummary | None = None,
    started_at: datetime = NOW,
    duration_seconds: float = 1.0,
) -> AgentExecution:
    """为 Manager 测试构造与计划严格对应的 AgentExecution。"""

    task = plan.task_for(dimension)
    if dimension == "security":
        static_analysis = {
            "tools": {"bandit": _evidence_tool_block("bandit", "B608")}
        }
        test_report = None
    elif dimension == "quality":
        static_analysis = {
            "tools": {
                "ruff": _evidence_tool_block("ruff", "E501"),
                "radon": _evidence_tool_block("radon", "RADON_CC"),
            }
        }
        test_report = None
    elif dimension == "performance":
        static_analysis = {
            "tools": {"radon": _evidence_tool_block("radon", "RADON_CC")}
        }
        test_report = None
    else:
        static_analysis = {"tools": {}}
        test_report = make_test_report_block()
    evidence = make_worker_evidence(
        agent_name=task.agent_name,
        static_analysis=static_analysis,
        test_report=test_report,
        usage=usage or UsageSummary(),
    )
    return make_execution(
        task=task,
        status=status,
        evidence=evidence,
        started_at=started_at,
        duration_seconds=duration_seconds,
    )


# ----------------------------------------------------------------------
# Stage 2.3 graph helpers


def make_inventory_summary(
    **overrides: Any,
) -> InventorySummary:
    """构造与真实 Inspector 结果同形的报告摘要，默认是小型非 partial。"""

    values: dict[str, Any] = {
        "total_files": 1,
        "python_source_files": 1,
        "python_test_files": 0,
        "filtered_files": 0,
        "excluded_directories": 0,
        "total_size_bytes": 128,
        "scanned_bytes": 128,
        "total_line_count": 10,
        "is_partial": False,
        "partial_reason": None,
    }
    values.update(overrides)
    return InventorySummary(**values)


def make_repository_context(
    **overrides: Any,
) -> RepositoryContext:
    values: dict[str, Any] = {
        "repository_url": "https://github.com/acme/demo",
        "repository_name": "acme/demo",
        "branch": "main",
        "language": "python",
        "source_type": "github_repository",
    }
    values.update(overrides)
    return RepositoryContext(**values)


def make_review_state(
    workspace_path: Path,
    *,
    review_id: str = REVIEW_ID,
    commit_sha: str = COMMIT_SHA,
    repository: RepositoryContext | None = None,
    allowed_files: tuple[str, ...] = ("pkg/app.py",),
    inventory: InventorySummary | None = None,
    rules: ReviewRules | None = None,
    trace_id: str | None = None,
) -> ReviewState:
    """构造审计计划 §5.1 的完整初始状态。"""

    return build_initial_state(
        review_id=review_id,
        commit_sha=commit_sha,
        repository=repository or make_repository_context(),
        workspace_path=workspace_path,
        allowed_files=allowed_files,
        inventory=inventory,
        rules=rules or make_review_rules(),
        trace_id=trace_id,
    )


def make_test_report_block(
    *,
    execution_status: str = "executed",
    passed: int = 3,
    failed: int = 0,
    skipped: int = 0,
    coverage: float | None = 91.0,
    reason: str | None = None,
) -> dict[str, Any]:
    """构造 TestingAgent 同形的 test_report 证据块。"""

    executed = execution_status == "executed"
    total = passed + failed + skipped if executed else None
    return {
        "schema_version": "1.0",
        "execution_status": execution_status,
        "reason": reason,
        "counts": {
            "total": total,
            "passed": passed if executed else None,
            "failed": failed if executed else None,
            "skipped": skipped if executed else None,
        },
        "coverage": coverage if executed else None,
        "source": (
            "pytest+coverage"
            if executed and coverage is not None
            else ("pytest" if executed else None)
        ),
        "records": [
            {
                "name": "tests/test_app.py::test_ok",
                "outcome": "passed",
                "file_path": "tests/test_app.py",
                "line": 3,
                "duration_seconds": 0.01,
                "message": None,
            }
        ]
        if executed
        else [],
        "records_truncated": False,
        "coverage_files": [],
        "coverage_files_truncated": False,
        "fixture": (
            {
                "name": "trusted_fixture_v1",
                "version": "1.0.0",
                "manifest_sha256": "f" * 64,
            }
            if executed
            else None
        ),
        "tool_versions": (
            {"pytest": "9.2.0", "coverage": "7.17.2"} if executed else {}
        ),
        "read_only_verified": True if executed else None,
        "modified_paths": [],
        "warnings": [],
    }


def make_dimension_evidence(dimension: str) -> dict[str, Any]:
    """按维度构造与真实专业 Agent 同形的 ``WorkerEvidence.static_analysis``。"""

    if dimension == "security":
        return {"tools": {"bandit": _evidence_tool_block("bandit", "B608")}}
    if dimension == "quality":
        return {
            "tools": {
                "ruff": _evidence_tool_block("ruff", "E501"),
                "radon": _evidence_tool_block("radon", "RADON_CC"),
            }
        }
    if dimension == "performance":
        return {"tools": {"radon": _evidence_tool_block("radon", "RADON_CC")}}
    if dimension == "testing":
        return {"tools": {}}
    raise ValueError(f"unknown dimension: {dimension}")


def make_agent_run_output(
    dispatch: WorkerDispatch,
    *,
    dimension: str,
    status: str = "completed",
    score: float | None = None,
    findings: list[Finding] | None = None,
    usage: UsageSummary | None = None,
    test_report: dict[str, Any] | None = None,
    summary: str | None = None,
    warnings: tuple[str, ...] = (),
) -> AgentRunOutput:
    """构造 FakeAgent 的维度化返回，供图与集成测试使用。"""

    resolved_report: dict[str, Any] | None
    if dimension == "testing":
        resolved_report = (
            make_test_report_block()
            if test_report is None
            else test_report
        )
    else:
        resolved_report = None

    result = make_agent_result(
        dispatch.task,
        status=status,
        score=score,
        findings=findings,
        summary=summary or f"{dispatch.task.agent_name} analysis {status}.",
    )
    evidence = WorkerEvidence(
        agent_name=dispatch.task.agent_name,
        static_analysis=make_dimension_evidence(dimension),
        test_report=resolved_report,
        usage=usage or UsageSummary(),
        warnings=warnings,
    )
    return AgentRunOutput(result=result, evidence=evidence)


def make_dimension_factory(
    dimension: str,
    *,
    status: str = "completed",
    score: float | None = None,
    findings: list[Finding] | None = None,
    usage: UsageSummary | None = None,
    test_report: dict[str, Any] | None = None,
) -> Callable[[WorkerDispatch], AgentRunOutput]:
    """生成固定维度、固定状态的 FakeAgent result factory。"""

    def factory(dispatch: WorkerDispatch) -> AgentRunOutput:
        return make_agent_run_output(
            dispatch,
            dimension=dimension,
            status=status,
            score=score,
            findings=findings,
            usage=usage,
            test_report=test_report,
        )

    return factory


def make_graph_dependencies(
    *,
    manager: ManagerAgent | None = None,
    delays: Mapping[str, float] | None = None,
    errors: Mapping[str, Exception] | None = None,
    statuses: Mapping[str, str] | None = None,
    factories: Mapping[str, Callable[[WorkerDispatch], AgentRunOutput]]
    | None = None,
) -> GraphDependencies:
    """构造四个 FakeAgent 组成的图依赖；可按维度配置延迟、异常与状态。"""

    resolved_delays = delays or {}
    resolved_errors = errors or {}
    resolved_statuses = statuses or {}
    resolved_factories = factories or {}

    agents: dict[str, FakeAgent] = {}
    for dimension, agent_name, task_type, _ in AGENT_SPECS:
        factory = resolved_factories.get(dimension)
        if factory is None:
            factory = make_dimension_factory(
                dimension,
                status=resolved_statuses.get(dimension, "completed"),
            )
        agents[dimension] = FakeAgent(
            agent_name=agent_name,
            task_type=task_type,
            result_factory=factory,
            error=resolved_errors.get(dimension),
            delay=resolved_delays.get(dimension, 0.0),
        )

    return GraphDependencies(
        manager=manager or ManagerAgent(),
        security_agent=agents["security"],
        quality_agent=agents["quality"],
        performance_agent=agents["performance"],
        testing_agent=agents["testing"],
    )
