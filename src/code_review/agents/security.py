"""SecurityAgent：Bandit 确定性证据 + 受限 LLM 语义补充。

安全维度的严重级别只来自 Bandit 原始级别经 ``review_rules.yaml`` 映射；
LLM 只能提出带真实代码位置的补充意见，且 LLM 意见不得是 high/critical，
也不得把任何 Bandit 规则预设为 critical。
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
    describe_llm_error,
    load_agent_prompt,
    request_json,
    validate_json_fields,
)
from code_review.schemas.result import AgentResult, Finding, ToolEvidence
from code_review.schemas.task import ErrorInfo, utc_now
from code_review.services.redaction import redact_sensitive_text
from code_review.tools.bandit_tool import BanditTool
from code_review.tools.base import (
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolFinding,
)
from config.review_rules import ReviewRules
from config.settings import Settings

__all__ = ["SECURITY_CATEGORIES", "SecurityAgent"]

SECURITY_CATEGORIES = frozenset(
    {
        "hardcoded_secret",
        "sql_injection",
        "command_injection",
        "insecure_deserialization",
        "weak_crypto",
        "path_traversal",
        "unsafe_network",
    }
)

_BANDIT_CATEGORY_BY_RULE: Mapping[str, str] = {
    "B102": "command_injection",
    "B103": "path_traversal",
    "B104": "unsafe_network",
    "B105": "hardcoded_secret",
    "B106": "hardcoded_secret",
    "B107": "hardcoded_secret",
    "B108": "path_traversal",
    "B201": "unsafe_network",
    "B301": "insecure_deserialization",
    "B302": "insecure_deserialization",
    "B303": "weak_crypto",
    "B304": "weak_crypto",
    "B305": "weak_crypto",
    "B306": "path_traversal",
    "B307": "command_injection",
    "B310": "unsafe_network",
    "B311": "weak_crypto",
    "B312": "unsafe_network",
    "B313": "insecure_deserialization",
    "B314": "insecure_deserialization",
    "B315": "insecure_deserialization",
    "B316": "insecure_deserialization",
    "B317": "insecure_deserialization",
    "B318": "insecure_deserialization",
    "B319": "insecure_deserialization",
    "B320": "insecure_deserialization",
    "B321": "unsafe_network",
    "B323": "unsafe_network",
    "B324": "weak_crypto",
    "B325": "unsafe_network",
    "B401": "unsafe_network",
    "B402": "unsafe_network",
    "B403": "insecure_deserialization",
    "B404": "command_injection",
    "B501": "unsafe_network",
    "B502": "unsafe_network",
    "B503": "unsafe_network",
    "B504": "unsafe_network",
    "B505": "weak_crypto",
    "B506": "insecure_deserialization",
    "B507": "unsafe_network",
    "B601": "command_injection",
    "B602": "command_injection",
    "B603": "command_injection",
    "B604": "command_injection",
    "B605": "command_injection",
    "B606": "command_injection",
    "B607": "command_injection",
    "B608": "sql_injection",
    "B609": "command_injection",
    "B610": "command_injection",
    "B611": "sql_injection",
    "B612": "command_injection",
    "B613": "command_injection",
    "B614": "insecure_deserialization",
    "B615": "insecure_deserialization",
}

_RECOMMENDATIONS: Mapping[str, str] = {
    "hardcoded_secret": (
        "Remove the hardcoded credential and load it from a secret manager or "
        "environment variable; rotate the exposed value."
    ),
    "sql_injection": (
        "Use parameterized queries or an ORM instead of string-built SQL."
    ),
    "command_injection": (
        "Avoid shell=True and validate or allowlist every dynamic argument."
    ),
    "insecure_deserialization": (
        "Do not deserialize untrusted data with unsafe loaders; use a safe "
        "format and validate the payload."
    ),
    "weak_crypto": (
        "Replace weak hash/cipher primitives with a current, reviewed "
        "cryptographic library and configuration."
    ),
    "path_traversal": (
        "Resolve the path against the allowed root and reject traversal or "
        "untrusted absolute paths."
    ),
    "unsafe_network": (
        "Disable plaintext or unverified transport and validate the remote "
        "endpoint."
    ),
}

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


class _LLMResponseRejected(Exception):
    """LLM 返回的顶层 JSON 结构不可用。"""


class SecurityAgent(BaseAgent):
    """安全维度专业 Agent。"""

    agent_name = "SecurityAgent"
    task_type = "security_review"

    def __init__(
        self,
        *,
        settings: Settings,
        llm_client: LLMClientProtocol | None = None,
        bandit_tool: BanditTool | None = None,
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
        self._tool = bandit_tool if bandit_tool is not None else BanditTool(settings)

    async def _run(self, dispatch: Any) -> AgentRunOutput:
        runtime = dispatch.runtime
        warnings: list[str] = []

        tool_result: ToolExecutionResult | None = None
        try:
            tool_result = await asyncio.to_thread(
                self._tool.run,
                runtime.workspace_path,
                list(runtime.allowed_files),
            )
        except Exception:  # noqa: BLE001 - 工具异常降级为缺失证据
            tool_result = None

        if tool_result is None:
            warnings.append("bandit execution failed")
        else:
            warnings.extend(self._tool_warnings(tool_result))

        block = self._tool_block(tool_result)
        tool_findings, finding_warnings = self._deterministic_findings(
            tool_result, runtime.rules
        )
        warnings.extend(finding_warnings)

        completion: JsonCompletion | None = None
        usage = UsageSummary()
        llm_error: Exception | None = None
        if self._llm_client is not None:
            completion, usage, llm_error, llm_warnings = await asyncio.to_thread(
                self._call_llm,
                dispatch,
                {"bandit": _tool_output_text(block)},
            )
            warnings.extend(llm_warnings)
            if llm_error is not None:
                warnings.append(
                    "llm semantic supplement failed: "
                    f"{describe_llm_error(llm_error)}"
                )
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
            tool_result,
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
                status,
                tool_result,
                tool_findings,
                llm_findings,
            ),
            error=error,
            metadata={
                "dimension": "security",
                "tool_status": {
                    "bandit": (
                        str(tool_result.execution_status)
                        if tool_result is not None
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
        evidence = self._build_evidence(
            block,
            usage,
            warnings,
        )
        return AgentRunOutput(result=result, evidence=evidence)

    # ------------------------------------------------------------------
    # Tool execution and evidence

    @staticmethod
    def _tool_warnings(result: ToolExecutionResult) -> list[str]:
        warnings: list[str] = []
        if result.execution_status not in {
            ToolExecutionStatus.SUCCESS,
            ToolExecutionStatus.FINDINGS,
        }:
            warnings.append(
                f"bandit execution status: {result.execution_status}"
            )
        if result.stdout_truncated:
            warnings.append("bandit stdout was truncated")
        if result.stderr_truncated:
            warnings.append("bandit stderr was truncated")
        if result.findings_truncated:
            warnings.append("bandit findings were truncated")
        return warnings

    def _build_evidence(
        self,
        block: Mapping[str, Any],
        usage: UsageSummary,
        warnings: Sequence[str],
    ) -> WorkerEvidence:
        return WorkerEvidence(
            agent_name=self.agent_name,
            static_analysis={"tools": {"bandit": dict(block)}},
            usage=usage,
            warnings=tuple(warnings),
        )

    @staticmethod
    def _tool_block(
        result: ToolExecutionResult | None,
    ) -> dict[str, Any]:
        if result is None:
            return {
                "tool_name": "bandit",
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
                    "message": "bandit execution failed",
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
                _tool_finding_block(finding, redactor=redact_sensitive_text)
                for finding in result.findings
            ],
        }

    # ------------------------------------------------------------------
    # Deterministic Findings

    def _deterministic_findings(
        self,
        result: ToolExecutionResult | None,
        rules: ReviewRules,
    ) -> tuple[list[Finding], list[str]]:
        if result is None:
            return [], ["bandit result unavailable; no security Finding created"]
        findings: list[Finding] = []
        warnings: list[str] = []
        skipped = 0
        for index, item in enumerate(result.findings):
            rule_id = (item.rule_id or "").upper()
            category = _BANDIT_CATEGORY_BY_RULE.get(rule_id)
            if category is None:
                skipped += 1
                continue
            if item.line is None:
                skipped += 1
                continue
            raw_severity = item.severity
            if not isinstance(raw_severity, str) or not raw_severity.strip():
                skipped += 1
                continue
            try:
                severity = rules.map_severity(
                    "bandit", raw_severity.strip().upper()
                )
            except KeyError:
                skipped += 1
                continue
            end_line = item.end_line if item.end_line is not None else item.line
            message = redact_sensitive_text(item.message, max_chars=_MAX_TEXT)
            title = redact_sensitive_text(
                f"Bandit {rule_id}: {item.message}", max_chars=_MAX_TITLE
            )
            findings.append(
                Finding(
                    finding_id=f"SEC-BANDIT-{index:04d}",
                    agent_name=self.agent_name,
                    category=category,
                    severity=severity,
                    title=title,
                    description=(
                        f"Bandit reported {rule_id} at "
                        f"{item.file_path}:{item.line}. Raw severity: "
                        f"{raw_severity}; raw confidence: "
                        f"{item.confidence or 'unknown'}."
                    ),
                    file_path=item.file_path,
                    start_line=item.line,
                    end_line=end_line,
                    evidence=message,
                    tool_evidence=[
                        ToolEvidence(
                            tool_name="bandit",
                            rule_id=item.rule_id,
                            tool_version=result.tool_version,
                            raw_output_ref=(
                                "static_analysis.json#/agents/security/tools/"
                                f"bandit/findings/{index}"
                            ),
                        )
                    ],
                    recommendation=_RECOMMENDATIONS[category],
                    confidence=_bandit_confidence(item.confidence),
                )
            )
        if skipped:
            warnings.append(
                f"bandit: {skipped} finding(s) were not representable as "
                "security Finding (unmapped rule, missing line, or unknown "
                "severity)"
            )
        return findings, warnings

    # ------------------------------------------------------------------
    # LLM supplement

    def _call_llm(
        self,
        dispatch: Any,
        tool_outputs: Mapping[str, str],
    ) -> tuple[
        JsonCompletion | None,
        UsageSummary,
        Exception | None,
        tuple[str, ...],
    ]:
        accumulator = UsageAccumulator()
        projection_warnings: tuple[str, ...] = ()
        try:
            system_prompt = load_agent_prompt("security")
            prompt_budget = self.settings.llm_max_input_chars
            projection = build_prompt_projection(
                dispatch,
                tool_outputs=tool_outputs,
                max_prompt_chars=prompt_budget,
            )
            projection_warnings = projection.warnings
            user_prompt = build_user_prompt(
                projection, max_chars=prompt_budget
            )
            completion = request_json(
                self._llm_client,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_output_tokens=self.settings.llm_max_output_tokens,
                temperature=self.settings.llm_temperature,
                timeout_seconds=self.settings.llm_timeout_seconds,
                accumulator=accumulator,
            )
            return (
                completion,
                accumulator.snapshot(),
                None,
                projection_warnings,
            )
        except Exception as exc:  # noqa: BLE001 - Provider 异常交由状态机处理
            return (
                None,
                accumulator.snapshot(),
                exc,
                projection_warnings,
            )

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
                f"llm proposed {len(raw_findings)} security findings; "
                f"only the first {limit} were considered"
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
                f"llm: {rejected} security proposal(s) were rejected by "
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
        if category not in SECURITY_CATEGORIES:
            raise LLMResponseError("category is outside the security whitelist")
        if severity not in _LLM_ALLOWED_SEVERITIES:
            raise LLMResponseError(
                "llm security findings may only be info, low or medium"
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
                "llm security finding must reference an allowed file"
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
            finding_id=f"SEC-LLM-{index + 1:04d}",
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
                "LLM semantic analysis failed; deterministic tool results "
                "were preserved",
            )
        if tool_degraded:
            return "partial", _error(
                "tool_degraded",
                "deterministic security tool output was incomplete",
            )
        if llm_ok:
            return "partial", _error(
                "tool_execution_error",
                "deterministic security tool failed; LLM-only findings cannot "
                "form a reliable score",
            )
        return "failed", _error(
            "tool_execution_error",
            "deterministic security tool failed and no reliable analysis is "
            "available",
        )

    @staticmethod
    def _summary(
        status: str,
        result: ToolExecutionResult | None,
        tool_findings: Sequence[Finding],
        llm_findings: Sequence[Finding],
    ) -> str:
        if status == "failed":
            return "Security analysis failed; no reliable security Finding."
        if result is None:
            return (
                "Security analysis is partial; Bandit produced no usable "
                f"result and {len(llm_findings)} LLM finding(s) were recorded."
            )
        return (
            f"Bandit analyzed {result.analyzed_file_count} file(s) and "
            f"reported {len(result.findings)} finding(s); "
            f"{len(tool_findings)} deterministic and {len(llm_findings)} "
            "LLM security finding(s) were recorded."
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


def _tool_finding_block(
    finding: ToolFinding,
    *,
    redactor: Callable[..., str],
) -> dict[str, Any]:
    return {
        "rule_id": finding.rule_id,
        "file_path": finding.file_path,
        "line": finding.line,
        "end_line": finding.end_line,
        "column": finding.column,
        "severity": finding.severity,
        "confidence": finding.confidence,
        "message": redactor(finding.message, max_chars=_MAX_TEXT),
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


def _bandit_confidence(raw: str | None) -> float:
    if raw == "HIGH":
        return 0.9
    if raw == "MEDIUM":
        return 0.7
    if raw == "LOW":
        return 0.5
    return 0.5


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
