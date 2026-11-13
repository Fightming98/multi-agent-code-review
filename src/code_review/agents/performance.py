"""PerformanceAgent：Radon 圈复杂度 + 受限静态推断。

静态推断不是 Benchmark。LLM 只能提出带真实代码位置的风险推断，且文本中
不得声称已获得运行时耗时、吞吐量、内存或延迟测量值；所有接受的意见都会
被显式标注为静态推断。
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

from code_review.agents.base import BaseAgent
from code_review.agents.contracts import (
    AgentRunOutput,
    LLMClientProtocol,
    UsageSummary,
    WorkerEvidence,
)
from code_review.agents.llm_support import (
    JsonCompletion,
    LLMResponseError,
    UsageAccumulator,
    build_prompt_projection,
    build_user_prompt,
    load_agent_prompt,
    request_json,
    validate_json_fields,
)
from code_review.schemas.result import AgentResult, Finding, ToolEvidence
from code_review.schemas.task import ErrorInfo, utc_now
from code_review.services.redaction import redact_sensitive_text
from code_review.tools.base import (
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolFinding,
)
from code_review.tools.radon_tool import RadonTool
from config.review_rules import ReviewRules
from config.settings import Settings

__all__ = ["PERFORMANCE_CATEGORIES", "PerformanceAgent"]

PERFORMANCE_CATEGORIES = frozenset(
    {
        "high_complexity",
        "algorithmic_complexity",
        "memory_risk",
        "io_efficiency",
    }
)

_LLM_ALLOWED_SEVERITIES = frozenset({"info", "low", "medium"})
_PROPOSAL_REQUIRED = {
    "category",
    "severity",
    "title",
    "description",
    "evidence",
    "recommendation",
    "confidence",
}
_PROPOSAL_OPTIONAL = {
    "file_path",
    "start_line",
    "end_line",
    "tool_evidence",
}

_BENCHMARK_CLAIM_RE = re.compile(
    r"(?i)\b(benchmark(?:ed|ing|s)?|measured|measurement|throughput|"
    r"latency|ops/sec|mb/s|mib/s|ns/op|qps)\b"
)

_MAX_TEXT = 4000
_MAX_TITLE = 200
_MAX_TOOL_OUTPUT_FINDINGS = 20

_RECOMMENDATIONS: Mapping[str, str] = {
    "high_complexity": (
        "Reduce branching and nesting; split the function and add tests "
        "covering the hot branches."
    ),
    "algorithmic_complexity": (
        "Confirm the input distribution and replace the suspected super-linear "
        "path with a data structure or algorithm with a better bound."
    ),
    "memory_risk": (
        "Stream or chunk the data, release references promptly, and add a "
        "memory regression test if the path is critical."
    ),
    "io_efficiency": (
        "Batch or cache repeated I/O, avoid per-item round trips, and measure "
        "the change in a controlled benchmark before claiming a win."
    ),
}


class _LLMResponseRejected(Exception):
    """LLM 返回的顶层 JSON 结构不可用。"""


class PerformanceAgent(BaseAgent):
    """性能风险维度专业 Agent。"""

    agent_name = "PerformanceAgent"
    task_type = "performance_review"

    def __init__(
        self,
        *,
        settings: Settings,
        llm_client: LLMClientProtocol | None = None,
        radon_tool: RadonTool | None = None,
        clock: Callable[[], datetime] = utc_now,
        timer: Callable[[], float] | None = None,
        redactor: Callable[..., str] = redact_sensitive_text,
    ) -> None:
        if timer is None:
            import time as _time

            timer = _time.perf_counter
        super().__init__(clock=clock, timer=timer, redactor=redactor)
        self.settings = settings
        self._llm_client = llm_client
        self._radon = radon_tool if radon_tool is not None else RadonTool(settings)

    async def _run(self, dispatch: Any) -> AgentRunOutput:
        runtime = dispatch.runtime
        warnings: list[str] = []

        try:
            radon_result = await asyncio.to_thread(
                self._radon.run,
                runtime.workspace_path,
                list(runtime.allowed_files),
            )
        except Exception:  # noqa: BLE001 - 工具异常必须降级为缺失证据
            radon_result = None
        if radon_result is None:
            warnings.append("radon execution failed")
        else:
            warnings.extend(_tool_warnings(radon_result))

        block = _tool_block(radon_result)
        tool_findings, finding_warnings = self._deterministic_findings(
            radon_result, runtime.rules
        )
        warnings.extend(finding_warnings)

        completion: JsonCompletion | None = None
        usage = UsageSummary()
        llm_error: Exception | None = None
        if self._llm_client is not None:
            completion, usage, llm_error = await asyncio.to_thread(
                self._call_llm,
                dispatch,
                {"radon": _tool_output_text(block)},
            )
            if llm_error is not None:
                warnings.append("llm semantic supplement failed")
        else:
            warnings.append(
                "llm client not configured; deterministic tool results only"
            )

        llm_findings: list[Finding] = []
        if completion is not None:
            try:
                llm_findings, llm_warnings = self._llm_findings(
                    completion.payload, runtime
                )
                warnings.extend(llm_warnings)
            except Exception:  # noqa: BLE001 - LLM 结构异常降级为分析失败
                llm_error = _LLMResponseRejected(
                    "llm response did not match the required structure"
                )
                warnings.append("llm response was rejected")

        status, error = self._decide_status(
            radon_result,
            completion,
            llm_error,
            llm_configured=self._llm_client is not None,
        )
        findings = tool_findings + llm_findings
        if status == "failed":
            findings = []

        result = AgentResult(
            task_id=dispatch.task.task_id,
            parent_task_id=dispatch.task.parent_task_id,
            review_id=dispatch.task.review_id,
            agent_name=self.agent_name,
            status=status,
            commit_sha=runtime.commit_sha,
            score=None,
            findings=findings,
            summary=self._summary(
                status, radon_result, tool_findings, llm_findings
            ),
            error=error,
            metadata={
                "dimension": "performance",
                "analysis_mode": "static_inference",
                "benchmark_executed": False,
                "tool_status": {
                    "radon": (
                        str(radon_result.execution_status)
                        if radon_result is not None
                        else "failed"
                    )
                },
                "deterministic_finding_count": len(tool_findings),
                "llm_finding_count": len(llm_findings),
                "llm_configured": self._llm_client is not None,
                "llm_succeeded": completion is not None
                and llm_error is None,
            },
        )
        evidence = WorkerEvidence(
            agent_name=self.agent_name,
            static_analysis={"tools": {"radon": block}},
            usage=usage,
            warnings=tuple(warnings),
        )
        return AgentRunOutput(result=result, evidence=evidence)

    # ------------------------------------------------------------------
    # Deterministic Findings

    def _deterministic_findings(
        self,
        result: ToolExecutionResult | None,
        rules: ReviewRules,
    ) -> tuple[list[Finding], list[str]]:
        if result is None:
            return [], [
                "radon result unavailable; no performance Finding created"
            ]
        findings: list[Finding] = []
        warnings: list[str] = []
        skipped = 0
        for index, item in enumerate(result.findings):
            rule_id = (item.rule_id or "").upper()
            if rule_id != "RADON_CC":
                skipped += 1
                continue
            rank = str(item.metadata.get("rank", "")).upper()
            if rank == "A" or item.line is None:
                continue
            try:
                severity = rules.map_severity("radon", rank)
            except KeyError:
                skipped += 1
                continue
            end_line = item.end_line if item.end_line is not None else item.line
            complexity = item.metadata.get("complexity")
            findings.append(
                Finding(
                    finding_id=f"PERF-RADON-{index:04d}",
                    agent_name=self.agent_name,
                    category="high_complexity",
                    severity=severity,
                    title=redact_sensitive_text(
                        f"Static complexity risk (rank {rank}): {item.message}",
                        max_chars=_MAX_TITLE,
                    ),
                    description=(
                        f"Radon cyclomatic complexity rank {rank} "
                        f"(complexity: {complexity}) at "
                        f"{item.file_path}:{item.line}. This is a static "
                        "complexity signal, not a runtime benchmark."
                    ),
                    file_path=item.file_path,
                    start_line=item.line,
                    end_line=end_line,
                    evidence=redact_sensitive_text(
                        item.message, max_chars=_MAX_TEXT
                    ),
                    tool_evidence=[
                        ToolEvidence(
                            tool_name="radon",
                            rule_id=item.rule_id,
                            tool_version=result.tool_version,
                            raw_output_ref=(
                                "static_analysis.json#/agents/performance/"
                                f"tools/radon/findings/{index}"
                            ),
                        )
                    ],
                    recommendation=_RECOMMENDATIONS["high_complexity"],
                    confidence=1.0,
                )
            )
        if skipped:
            warnings.append(
                f"radon: {skipped} finding(s) were outside the performance "
                "dimension or not representable"
            )
        return findings, warnings

    # ------------------------------------------------------------------
    # LLM supplement

    def _call_llm(
        self,
        dispatch: Any,
        tool_outputs: Mapping[str, str],
    ) -> tuple[JsonCompletion | None, UsageSummary, Exception | None]:
        accumulator = UsageAccumulator()
        try:
            system_prompt = load_agent_prompt("performance")
            projection = build_prompt_projection(
                dispatch, tool_outputs=tool_outputs
            )
            user_prompt = build_user_prompt(projection)
            completion = request_json(
                self._llm_client,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_output_tokens=self.settings.llm_max_output_tokens,
                temperature=self.settings.llm_temperature,
                timeout_seconds=self.settings.llm_timeout_seconds,
                accumulator=accumulator,
            )
            return completion, accumulator.snapshot(), None
        except Exception as exc:  # noqa: BLE001 - Provider 异常交由状态机处理
            return None, accumulator.snapshot(), exc

    def _llm_findings(
        self,
        payload: Mapping[str, Any],
        runtime: Any,
    ) -> tuple[list[Finding], list[str]]:
        try:
            validate_json_fields(
                payload,
                required={"findings", "summary"},
                optional={"warnings"},
            )
        except LLMResponseError as exc:
            raise _LLMResponseRejected(str(exc)) from exc

        raw_findings = payload["findings"]
        if not isinstance(raw_findings, list):
            raise _LLMResponseRejected("findings must be a list")
        summary = payload["summary"]
        if not isinstance(summary, str) or not summary.strip():
            raise _LLMResponseRejected("summary must be a non-empty string")

        limit = self.settings.llm_max_finding_proposals
        warnings: list[str] = []
        if len(raw_findings) > limit:
            warnings.append(
                f"llm proposed {len(raw_findings)} performance findings; only "
                f"the first {limit} were considered"
            )
            raw_findings = raw_findings[:limit]

        allowed_files = set(runtime.allowed_files)
        findings: list[Finding] = []
        rejected = 0
        for proposal in raw_findings:
            try:
                findings.append(
                    self._finding_from_proposal(
                        proposal,
                        allowed_files=allowed_files,
                        index=len(findings),
                    )
                )
            except (LLMResponseError, ValueError, TypeError):
                rejected += 1
        if rejected:
            warnings.append(
                f"llm: {rejected} performance proposal(s) were rejected by "
                "contract, evidence or benchmark-claim rules"
            )
        return findings, warnings

    def _finding_from_proposal(
        self,
        proposal: object,
        *,
        allowed_files: set[str],
        index: int,
    ) -> Finding:
        if not isinstance(proposal, Mapping):
            raise LLMResponseError("llm finding proposal must be an object")
        validate_json_fields(
            proposal,
            required=_PROPOSAL_REQUIRED,
            optional=_PROPOSAL_OPTIONAL,
        )
        category = proposal["category"]
        severity = proposal["severity"]
        if category not in PERFORMANCE_CATEGORIES:
            raise LLMResponseError(
                "category is outside the performance whitelist"
            )
        if severity not in _LLM_ALLOWED_SEVERITIES:
            raise LLMResponseError(
                "llm performance findings may only be info, low or medium"
            )

        title = _required_text(proposal["title"], "title", _MAX_TITLE)
        description = _required_text(
            proposal["description"], "description", _MAX_TEXT
        )
        evidence_text = _required_text(
            proposal["evidence"], "evidence", _MAX_TEXT
        )
        recommendation = _required_text(
            proposal["recommendation"], "recommendation", _MAX_TEXT
        )
        confidence = _confidence(proposal["confidence"])
        if _BENCHMARK_CLAIM_RE.search(
            f"{title} {description} {evidence_text} {recommendation}"
        ):
            raise LLMResponseError(
                "performance proposal claims a benchmark or measured runtime"
            )

        file_path = proposal.get("file_path")
        start_line = proposal.get("start_line")
        end_line = proposal.get("end_line")
        if not isinstance(file_path, str) or file_path not in allowed_files:
            raise LLMResponseError(
                "llm performance finding must reference an allowed file"
            )
        if isinstance(start_line, bool) or not isinstance(start_line, int):
            raise LLMResponseError("llm finding start_line must be an integer")
        if start_line < 1:
            raise LLMResponseError("llm finding start_line must be positive")
        if end_line is not None:
            if isinstance(end_line, bool) or not isinstance(end_line, int):
                raise LLMResponseError("end_line must be an integer")
            if end_line < start_line:
                raise LLMResponseError("end_line must be >= start_line")

        return Finding(
            finding_id=f"PERF-LLM-{index + 1:04d}",
            agent_name=self.agent_name,
            category=category,
            severity=severity,
            title=title,
            description=(
                "Static inference (no benchmark executed): " + description
            ),
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            evidence=evidence_text,
            tool_evidence=[],
            recommendation=recommendation,
            confidence=confidence,
        )

    # ------------------------------------------------------------------
    # Status and summary

    def _decide_status(
        self,
        result: ToolExecutionResult | None,
        completion: JsonCompletion | None,
        llm_error: Exception | None,
        *,
        llm_configured: bool,
    ) -> tuple[str, ErrorInfo | None]:
        tool_ok = result is not None and result.execution_status in {
            ToolExecutionStatus.SUCCESS,
            ToolExecutionStatus.FINDINGS,
        }
        tool_degraded = (
            result is not None
            and result.execution_status is ToolExecutionStatus.PARTIAL
        )
        llm_ok = (
            llm_configured and completion is not None and llm_error is None
        )
        llm_failed = llm_configured and not llm_ok

        if tool_ok and not llm_failed:
            return "completed", None
        if tool_ok and llm_failed:
            return "partial", _error(
                "llm_analysis_error",
                "LLM performance inference failed; deterministic tool results "
                "were preserved",
            )
        if tool_degraded:
            return "partial", _error(
                "tool_degraded",
                "deterministic performance tool output was incomplete",
            )
        if llm_ok:
            return "partial", _error(
                "tool_execution_error",
                "deterministic performance tool failed; LLM-only static "
                "inference cannot form a reliable score",
            )
        return "failed", _error(
            "tool_execution_error",
            "deterministic performance tool failed and no reliable analysis "
            "is available",
        )

    @staticmethod
    def _summary(
        status: str,
        result: ToolExecutionResult | None,
        tool_findings: Sequence[Finding],
        llm_findings: Sequence[Finding],
    ) -> str:
        if status == "failed":
            return "Performance analysis failed; no reliable performance Finding."
        if result is None:
            return (
                "Performance analysis is partial; Radon produced no usable "
                f"result and {len(llm_findings)} static-inference finding(s) "
                "were recorded."
            )
        return (
            f"Radon analyzed {result.analyzed_file_count} file(s) and reported "
            f"{len(result.findings)} finding(s); {len(tool_findings)} "
            f"deterministic and {len(llm_findings)} static-inference "
            "performance finding(s) were recorded. No benchmark was executed."
        )


# ----------------------------------------------------------------------
# Shared local helpers


def _error(error_type: str, message: str) -> ErrorInfo:
    return ErrorInfo(
        error_type=error_type,
        message=message,
        retryable=False,
        details={},
    )


def _tool_warnings(result: ToolExecutionResult) -> list[str]:
    warnings: list[str] = []
    if result.execution_status not in {
        ToolExecutionStatus.SUCCESS,
        ToolExecutionStatus.FINDINGS,
    }:
        warnings.append(f"radon execution status: {result.execution_status}")
    if result.stdout_truncated:
        warnings.append("radon stdout was truncated")
    if result.stderr_truncated:
        warnings.append("radon stderr was truncated")
    if result.findings_truncated:
        warnings.append("radon findings were truncated")
    return warnings


def _tool_block(result: ToolExecutionResult | None) -> dict[str, Any]:
    if result is None:
        return {
            "tool_name": "radon",
            "tool_version": None,
            "execution_status": "failed",
            "exit_code": None,
            "duration_ms": None,
            "analyzed_file_count": 0,
            "stdout_truncated": False,
            "stderr_truncated": False,
            "findings_truncated": False,
            "error": {
                "error_type": "tool_execution_error",
                "message": "radon execution failed",
                "retryable": False,
                "details": {},
            },
            "findings": [],
        }
    return {
        "tool_name": result.tool_name,
        "tool_version": result.tool_version,
        "execution_status": str(result.execution_status),
        "exit_code": result.exit_code,
        "duration_ms": result.duration_ms,
        "analyzed_file_count": result.analyzed_file_count,
        "stdout_truncated": result.stdout_truncated,
        "stderr_truncated": result.stderr_truncated,
        "findings_truncated": result.findings_truncated,
        "error": _error_block(result.error),
        "findings": [
            _tool_finding_block(finding) for finding in result.findings
        ],
    }


def _error_block(error: ErrorInfo | None) -> dict[str, Any] | None:
    if error is None:
        return None
    return {
        "error_type": error.error_type,
        "message": redact_sensitive_text(error.message, max_chars=_MAX_TEXT),
        "retryable": error.retryable,
        "occurred_at": error.occurred_at.isoformat(),
        "details": _json_copy(error.details),
    }


def _json_copy(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return redact_sensitive_text(value, max_chars=_MAX_TEXT)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _json_copy(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_copy(item) for item in value]
    return redact_sensitive_text(str(value), max_chars=_MAX_TEXT)


def _tool_finding_block(finding: ToolFinding) -> dict[str, Any]:
    return {
        "rule_id": finding.rule_id,
        "file_path": finding.file_path,
        "line": finding.line,
        "end_line": finding.end_line,
        "column": finding.column,
        "severity": finding.severity,
        "confidence": finding.confidence,
        "message": redact_sensitive_text(
            finding.message, max_chars=_MAX_TEXT
        ),
        "metadata": _json_copy(dict(finding.metadata)),
    }


def _tool_output_text(block: Mapping[str, Any]) -> str:
    findings = block.get("findings") or []
    compact = {
        "tool": block.get("tool_name"),
        "execution_status": block.get("execution_status"),
        "analyzed_file_count": block.get("analyzed_file_count"),
        "finding_count": len(findings),
        "findings": list(findings)[:_MAX_TOOL_OUTPUT_FINDINGS],
    }
    return json.dumps(compact, ensure_ascii=False, allow_nan=False)


def _required_text(value: object, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LLMResponseError(f"llm finding {field} must be non-empty")
    return redact_sensitive_text(value, max_chars=limit)


def _confidence(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LLMResponseError("llm finding confidence must be a number")
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 1:
        raise LLMResponseError("llm finding confidence must be within [0, 1]")
    return number
