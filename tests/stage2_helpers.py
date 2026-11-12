"""Stage 2 测试辅助：内部合同、Fake Agent 与 Fake LLM。

本模块不访问网络、不调用真实 LLM、不执行外部仓库代码。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from code_review.agents.base import BaseAgent
from code_review.agents.contracts import (
    AgentRunOutput,
    ArtifactData,
    UsageSummary,
    WorkerDispatch,
    WorkerEvidence,
    WorkerRuntime,
)
from code_review.schemas.result import AgentResult, Finding, ToolEvidence
from code_review.schemas.task import AgentTask, ErrorInfo
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
