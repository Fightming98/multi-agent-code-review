"""QualityAgent：Ruff/Radon 确定性证据 + 受限 LLM 语义补充。

只允许质量类别白名单；Ruff 的 ``S`` 系列安全规则不会在 QualityAgent 中
转成 Finding，避免与 SecurityAgent 的职责重叠。Ruff JSON 通常不携带
severity，因此先按规则族给出确定性的原始标签，再经 ``review_rules.yaml``
映射，不在代码里硬编码最终严重级别。
"""

from __future__ import annotations

import asyncio
import json
import math
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
from code_review.tools.ruff_tool import RuffTool
from config.review_rules import ReviewRules
from config.settings import Settings

__all__ = ["QUALITY_CATEGORIES", "QualityAgent"]

QUALITY_CATEGORIES = frozenset(
    {
        "code_smell",
        "style",
        "high_complexity",
        "error_handling",
        "maintainability",
        "duplication",
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

_MAX_TEXT = 4000
_MAX_TITLE = 200
_MAX_TOOL_OUTPUT_FINDINGS = 20
_MAX_MAINTAINABILITY_FILES = 20

_SEVERITY_ORDER = {
    "info": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}

_RECOMMENDATIONS: Mapping[str, str] = {
    "code_smell": (
        "Simplify the code path, remove dead or duplicated logic, and add a "
        "focused regression test for the behavior."
    ),
    "style": (
        "Apply the project's formatter and linter fixes; keep the change "
        "mechanical and behavior-preserving."
    ),
    "high_complexity": (
        "Split the function into smaller units with explicit inputs and add "
        "tests around each branch."
    ),
    "error_handling": (
        "Handle the failure explicitly, preserve the original cause, and add "
        "a test for the error path."
    ),
    "maintainability": (
        "Reduce module coupling and documentation gaps; split large modules "
        "along cohesive responsibilities."
    ),
    "duplication": (
        "Extract the shared behavior into one reviewed helper and update all "
        "call sites."
    ),
}


class _LLMResponseRejected(Exception):
    """LLM 返回的顶层 JSON 结构不可用。"""


class QualityAgent(BaseAgent):
    """代码质量维度专业 Agent。"""

    agent_name = "QualityAgent"
    task_type = "quality_review"

    def __init__(
        self,
        *,
        settings: Settings,
        llm_client: LLMClientProtocol | None = None,
        ruff_tool: RuffTool | None = None,
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
        self._ruff = ruff_tool if ruff_tool is not None else RuffTool(settings)
        self._radon = radon_tool if radon_tool is not None else RadonTool(settings)

    async def _run(self, dispatch: Any) -> AgentRunOutput:
        runtime = dispatch.runtime
        warnings: list[str] = []

        ruff_result, radon_result = await asyncio.gather(
            self._run_tool(self._ruff, runtime),
            self._run_tool(self._radon, runtime),
        )
        if ruff_result is None:
            warnings.append("ruff execution failed")
        else:
            warnings.extend(_tool_warnings("ruff", ruff_result))
        if radon_result is None:
            warnings.append("radon execution failed")
        else:
            warnings.extend(_tool_warnings("radon", radon_result))

        blocks = {
            "ruff": _tool_block("ruff", ruff_result),
            "radon": _tool_block("radon", radon_result),
        }

        tool_findings, finding_warnings = self._deterministic_findings(
            ruff_result, radon_result, runtime.rules
        )
        warnings.extend(finding_warnings)

        completion: JsonCompletion | None = None
        usage = UsageSummary()
        llm_error: Exception | None = None
        if self._llm_client is not None:
            completion, usage, llm_error = await asyncio.to_thread(
                self._call_llm,
                dispatch,
                {
                    "ruff": _tool_output_text(blocks["ruff"]),
                    "radon": _tool_output_text(blocks["radon"]),
                },
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
            ruff_result,
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
                status, ruff_result, radon_result, tool_findings, llm_findings
            ),
            error=error,
            metadata={
                "dimension": "quality",
                "tool_status": {
                    "ruff": _status_value(ruff_result),
                    "radon": _status_value(radon_result),
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
            static_analysis={"tools": blocks},
            usage=usage,
            warnings=tuple(warnings),
        )
        return AgentRunOutput(result=result, evidence=evidence)

    # ------------------------------------------------------------------
    # Tool execution

    @staticmethod
    async def _run_tool(
        tool: Any,
        runtime: Any,
    ) -> ToolExecutionResult | None:
        try:
            return await asyncio.to_thread(
                tool.run,
                runtime.workspace_path,
                list(runtime.allowed_files),
            )
        except Exception:  # noqa: BLE001 - 工具异常降级为缺失证据
            return None

    # ------------------------------------------------------------------
    # Deterministic Findings

    def _deterministic_findings(
        self,
        ruff_result: ToolExecutionResult | None,
        radon_result: ToolExecutionResult | None,
        rules: ReviewRules,
    ) -> tuple[list[Finding], list[str]]:
        findings: list[Finding] = []
        warnings: list[str] = []
        findings.extend(
            self._ruff_findings(ruff_result, rules, warnings)
        )
        findings.extend(
            self._radon_findings(radon_result, rules, warnings)
        )
        return findings, warnings

    def _ruff_findings(
        self,
        result: ToolExecutionResult | None,
        rules: ReviewRules,
        warnings: list[str],
    ) -> list[Finding]:
        if result is None:
            warnings.append("ruff result unavailable; no quality Finding created")
            return []
        findings: list[Finding] = []
        skipped = 0
        security_skipped = 0
        for index, item in enumerate(result.findings):
            rule_id = (item.rule_id or "").upper()
            category = _ruff_category(rule_id)
            if category is None:
                security_skipped += 1
                continue
            if item.line is None:
                skipped += 1
                continue
            source_severity = _ruff_source_severity(rule_id)
            try:
                severity = rules.map_severity("ruff", source_severity)
            except KeyError:
                skipped += 1
                continue
            end_line = item.end_line if item.end_line is not None else item.line
            message = redact_sensitive_text(item.message, max_chars=_MAX_TEXT)
            findings.append(
                Finding(
                    finding_id=f"QUA-RUFF-{index:04d}",
                    agent_name=self.agent_name,
                    category=category,
                    severity=severity,
                    title=redact_sensitive_text(
                        f"Ruff {rule_id}: {item.message}",
                        max_chars=_MAX_TITLE,
                    ),
                    description=(
                        f"Ruff reported {rule_id} at "
                        f"{item.file_path}:{item.line}. Source severity label: "
                        f"{source_severity}."
                    ),
                    file_path=item.file_path,
                    start_line=item.line,
                    end_line=end_line,
                    evidence=message,
                    tool_evidence=[
                        ToolEvidence(
                            tool_name="ruff",
                            rule_id=item.rule_id,
                            tool_version=result.tool_version,
                            raw_output_ref=(
                                "static_analysis.json#/agents/quality/tools/"
                                f"ruff/findings/{index}"
                            ),
                        )
                    ],
                    recommendation=_RECOMMENDATIONS[category],
                    confidence=0.9,
                )
            )
        if skipped:
            warnings.append(
                f"ruff: {skipped} finding(s) were not representable as "
                "quality Finding"
            )
        if security_skipped:
            warnings.append(
                f"ruff: {security_skipped} security rule(s) were left to "
                "SecurityAgent"
            )
        return findings

    def _radon_findings(
        self,
        result: ToolExecutionResult | None,
        rules: ReviewRules,
        warnings: list[str],
    ) -> list[Finding]:
        if result is None:
            warnings.append("radon result unavailable; no quality Finding created")
            return []
        findings: list[Finding] = []
        maintainability: list[tuple[int, ToolFinding, str, str]] = []
        skipped = 0
        for index, item in enumerate(result.findings):
            rule_id = (item.rule_id or "").upper()
            rank = str(item.metadata.get("rank", "")).upper()
            if rule_id == "RADON_MI":
                if rank in {"B", "C"}:
                    try:
                        severity = rules.map_severity("radon", rank)
                    except KeyError:
                        skipped += 1
                        continue
                    maintainability.append((index, item, rank, severity))
                continue
            if rule_id != "RADON_CC":
                skipped += 1
                continue
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
                    finding_id=f"QUA-RADON-{index:04d}",
                    agent_name=self.agent_name,
                    category="high_complexity",
                    severity=severity,
                    title=redact_sensitive_text(
                        f"Cyclomatic complexity rank {rank}: {item.message}",
                        max_chars=_MAX_TITLE,
                    ),
                    description=(
                        f"Radon reported complexity rank {rank} "
                        f"(complexity: {complexity}) at "
                        f"{item.file_path}:{item.line}."
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
                                "static_analysis.json#/agents/quality/tools/"
                                f"radon/findings/{index}"
                            ),
                        )
                    ],
                    recommendation=_RECOMMENDATIONS["high_complexity"],
                    confidence=1.0,
                )
            )
        if maintainability:
            highest = max(
                (entry[3] for entry in maintainability),
                key=lambda level: _SEVERITY_ORDER[level],
            )
            files = [
                f"{entry[1].file_path} (rank {entry[2]})"
                for entry in maintainability[:_MAX_MAINTAINABILITY_FILES]
            ]
            extra = len(maintainability) - len(files)
            description = (
                "Radon maintainability index ranks below A for "
                f"{len(maintainability)} file(s): " + ", ".join(files)
            )
            if extra:
                description += f"; {extra} more file(s) omitted"
            findings.append(
                Finding(
                    finding_id="QUA-RADON-MI-0001",
                    agent_name=self.agent_name,
                    category="maintainability",
                    severity=highest,
                    title=(
                        "Maintainability index below A in "
                        f"{len(maintainability)} file(s)"
                    ),
                    description=redact_sensitive_text(
                        description, max_chars=_MAX_TEXT
                    ),
                    evidence=redact_sensitive_text(
                        "Radon MI: " + ", ".join(files),
                        max_chars=_MAX_TEXT,
                    ),
                    tool_evidence=[
                        ToolEvidence(
                            tool_name="radon",
                            rule_id="RADON_MI",
                            tool_version=result.tool_version,
                            raw_output_ref=(
                                "static_analysis.json#/agents/quality/tools/"
                                f"radon/findings/{entry[0]}"
                            ),
                        )
                        for entry in maintainability
                    ],
                    recommendation=_RECOMMENDATIONS["maintainability"],
                    confidence=1.0,
                )
            )
        if skipped:
            warnings.append(
                f"radon: {skipped} finding(s) were not representable as "
                "quality Finding"
            )
        return findings

    # ------------------------------------------------------------------
    # LLM supplement

    def _call_llm(
        self,
        dispatch: Any,
        tool_outputs: Mapping[str, str],
    ) -> tuple[JsonCompletion | None, UsageSummary, Exception | None]:
        accumulator = UsageAccumulator()
        try:
            system_prompt = load_agent_prompt("quality")
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
                f"llm proposed {len(raw_findings)} quality findings; only the "
                f"first {limit} were considered"
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
                f"llm: {rejected} quality proposal(s) were rejected by "
                "contract or evidence rules"
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
        if category not in QUALITY_CATEGORIES:
            raise LLMResponseError("category is outside the quality whitelist")
        if severity not in _LLM_ALLOWED_SEVERITIES:
            raise LLMResponseError(
                "llm quality findings may only be info, low or medium"
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

        file_path = proposal.get("file_path")
        start_line = proposal.get("start_line")
        end_line = proposal.get("end_line")
        if not isinstance(file_path, str) or file_path not in allowed_files:
            raise LLMResponseError(
                "llm quality finding must reference an allowed file"
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
            finding_id=f"QUA-LLM-{index + 1:04d}",
            agent_name=self.agent_name,
            category=category,
            severity=severity,
            title=title,
            description=description,
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
        ruff_result: ToolExecutionResult | None,
        radon_result: ToolExecutionResult | None,
        completion: JsonCompletion | None,
        llm_error: Exception | None,
        *,
        llm_configured: bool,
    ) -> tuple[str, ErrorInfo | None]:
        statuses = [
            result.execution_status if result is not None else None
            for result in (ruff_result, radon_result)
        ]
        ok_count = sum(
            1
            for status in statuses
            if status
            in {ToolExecutionStatus.SUCCESS, ToolExecutionStatus.FINDINGS}
        )
        degraded_count = sum(
            1
            for status in statuses
            if status is ToolExecutionStatus.PARTIAL
        )
        hard_fail_count = sum(
            1
            for status in statuses
            if status
            not in {
                ToolExecutionStatus.SUCCESS,
                ToolExecutionStatus.FINDINGS,
                ToolExecutionStatus.PARTIAL,
            }
        )
        all_ok = ok_count == len(statuses)
        llm_ok = (
            llm_configured and completion is not None and llm_error is None
        )
        llm_failed = llm_configured and not llm_ok

        if all_ok and not llm_failed:
            return "completed", None
        if all_ok and llm_failed:
            return "partial", _error(
                "llm_analysis_error",
                "LLM semantic analysis failed; deterministic quality tool "
                "results were preserved",
            )
        if ok_count > 0 or degraded_count > 0:
            if hard_fail_count:
                message = (
                    "one or more deterministic quality tools failed; "
                    "available tool results were preserved"
                )
                return "partial", _error("tool_execution_error", message)
            return "partial", _error(
                "tool_degraded",
                "deterministic quality tool output was incomplete",
            )
        if llm_ok:
            return "partial", _error(
                "tool_execution_error",
                "deterministic quality tools failed; LLM-only findings cannot "
                "form a reliable score",
            )
        return "failed", _error(
            "tool_execution_error",
            "deterministic quality tools failed and no reliable analysis is "
            "available",
        )

    @staticmethod
    def _summary(
        status: str,
        ruff_result: ToolExecutionResult | None,
        radon_result: ToolExecutionResult | None,
        tool_findings: Sequence[Finding],
        llm_findings: Sequence[Finding],
    ) -> str:
        if status == "failed":
            return "Quality analysis failed; no reliable quality Finding."
        ruff_count = len(ruff_result.findings) if ruff_result else 0
        radon_count = len(radon_result.findings) if radon_result else 0
        return (
            f"Ruff reported {ruff_count} finding(s); Radon reported "
            f"{radon_count} finding(s); {len(tool_findings)} deterministic and "
            f"{len(llm_findings)} LLM quality finding(s) were recorded."
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


def _status_value(result: ToolExecutionResult | None) -> str:
    return str(result.execution_status) if result is not None else "failed"


def _is_security_rule(rule_id: str) -> bool:
    return len(rule_id) > 1 and rule_id[0] == "S" and rule_id[1:].isdigit()


def _ruff_category(rule_id: str) -> str | None:
    rule = rule_id.upper()
    if not rule:
        return "code_smell"
    if _is_security_rule(rule):
        return None
    if rule.startswith("C90"):
        return "high_complexity"
    if rule.startswith("TRY"):
        return "error_handling"
    if rule.startswith(
        ("E", "W", "I", "UP", "RUF", "SIM", "D", "Q", "FA", "PIE", "PT")
    ):
        return "style"
    if rule.startswith(("F", "B", "PL", "ARG", "RET", "G", "N")):
        return "code_smell"
    return "code_smell"


def _ruff_source_severity(rule_id: str) -> str:
    rule = rule_id.upper()
    if rule.startswith(("E9", "F82")):
        return "error"
    return "warning"


def _tool_warnings(tool: str, result: ToolExecutionResult) -> list[str]:
    warnings: list[str] = []
    if result.execution_status not in {
        ToolExecutionStatus.SUCCESS,
        ToolExecutionStatus.FINDINGS,
    }:
        warnings.append(f"{tool} execution status: {result.execution_status}")
    if result.stdout_truncated:
        warnings.append(f"{tool} stdout was truncated")
    if result.stderr_truncated:
        warnings.append(f"{tool} stderr was truncated")
    if result.findings_truncated:
        warnings.append(f"{tool} findings were truncated")
    return warnings


def _tool_block(
    tool_name: str,
    result: ToolExecutionResult | None,
) -> dict[str, Any]:
    if result is None:
        return {
            "tool_name": tool_name,
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
                "message": f"{tool_name} execution failed",
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
