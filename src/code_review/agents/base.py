"""Stage 2 统一 Agent 生命周期与合同校验。"""

from __future__ import annotations

import json
import tempfile
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from code_review.agents.contracts import (
    AgentExecution,
    AgentRunOutput,
    ContractValidationError,
    UsageSummary,
    WorkerDispatch,
    WorkerEvidence,
    WorkerTiming,
)
from code_review.schemas.result import AgentResult, ErrorInfo, Finding
from code_review.schemas.task import AgentTask, utc_now
from code_review.services.redaction import redact_sensitive_text

LOGGER = structlog.get_logger(__name__)

_ALLOWED_TASK_STATUSES = frozenset({"pending", "running"})


class AgentContractError(ContractValidationError):
    """Agent 输入或输出不符合内部/冻结合同。"""


class BaseAgent(ABC):
    """所有 Stage 2 Worker 的统一异步执行基类。

    子类只需实现 ``_run``；本类负责 running/completed/partial/failed 生命周期、
    普通异常转换、合同校验、脱敏与 timing。本类不创建 LLM 客户端，不重试，
    不读取完整 Graph State，不写仓库。
    """

    agent_name: str = ""
    task_type: str = ""

    def __init__(
        self,
        *,
        agent_name: str | None = None,
        task_type: str | None = None,
        clock: Callable[[], datetime] = utc_now,
        timer: Callable[[], float] = time.perf_counter,
        redactor: Callable[..., str] = redact_sensitive_text,
    ) -> None:
        resolved_name = agent_name if agent_name is not None else type(self).agent_name
        resolved_type = task_type if task_type is not None else type(self).task_type
        if not isinstance(resolved_name, str) or not resolved_name.strip():
            raise ValueError("agent_name must be a non-empty string")
        if not isinstance(resolved_type, str) or not resolved_type.strip():
            raise ValueError("task_type must be a non-empty string")
        self.agent_name = resolved_name
        self.task_type = resolved_type
        self._clock = clock
        self._timer = timer
        self._redactor = redactor

    @abstractmethod
    async def _run(self, dispatch: WorkerDispatch) -> AgentRunOutput:
        """执行具体维度分析并返回结果与证据。"""

    async def execute(self, dispatch: WorkerDispatch) -> AgentExecution:
        """执行 Agent，保证普通异常转换为合法 failed AgentResult。"""
        self._validate_dispatch(dispatch)
        started_at = self._clock()
        started_counter = self._timer()
        running_task = self._task_running(dispatch.task, started_at)
        running_dispatch = WorkerDispatch(
            task=running_task,
            runtime=dispatch.runtime,
        )

        LOGGER.info(
            "agent_started",
            agent_name=self.agent_name,
            task_id=running_task.task_id,
        )

        try:
            output = await self._run(running_dispatch)
            if not isinstance(output, AgentRunOutput):
                raise AgentContractError(
                    "agent _run must return AgentRunOutput"
                )
            duration = max(0.0, self._timer() - started_counter)
            result = self._validate_and_sanitize_result(
                output.result,
                running_task,
                dispatch,
            )
            result = AgentResult.model_validate(
                result.model_copy(
                    update={"execution_time": duration}
                ).model_dump()
            )
            evidence = self._validate_evidence(output.evidence)
            finished_at = self._clock()
            final_task = self._task_finished(
                running_task,
                result.status,
                finished_at,
                result.error,
            )
            timing = WorkerTiming(
                agent_name=self.agent_name,
                task_id=running_task.task_id,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                status=result.status,
            )
            LOGGER.info(
                "agent_finished",
                agent_name=self.agent_name,
                task_id=running_task.task_id,
                status=result.status,
                duration_seconds=round(duration, 6),
            )
            return AgentExecution(
                task=final_task,
                result=result,
                evidence=evidence,
                timing=timing,
            )
        except Exception as exc:  # noqa: BLE001 - 普通异常必须隔离为该维度失败
            duration = max(0.0, self._timer() - started_counter)
            finished_at = self._clock()
            failed_result = self._failed_result(
                running_task,
                exc,
                duration,
                finished_at,
                dispatch.runtime.workspace_path,
                dispatch.runtime.commit_sha,
            )
            failed_evidence = WorkerEvidence(
                agent_name=self.agent_name,
                warnings=("agent execution failed",),
            )
            final_task = self._task_finished(
                running_task,
                "failed",
                finished_at,
                failed_result.error,
            )
            timing = WorkerTiming(
                agent_name=self.agent_name,
                task_id=running_task.task_id,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                status="failed",
            )
            LOGGER.warning(
                "agent_failed",
                agent_name=self.agent_name,
                task_id=running_task.task_id,
                error_type=failed_result.error.error_type
                if failed_result.error is not None
                else "unknown",
            )
            return AgentExecution(
                task=final_task,
                result=failed_result,
                evidence=failed_evidence,
                timing=timing,
            )

    # ------------------------------------------------------------------
    # 输入合同

    def _validate_dispatch(self, dispatch: WorkerDispatch) -> None:
        if not isinstance(dispatch, WorkerDispatch):
            raise AgentContractError("dispatch must be a WorkerDispatch")
        task = dispatch.task
        if task.agent_name != self.agent_name:
            raise AgentContractError(
                "task.agent_name does not match this agent"
            )
        if task.task_type != self.task_type:
            raise AgentContractError("task.task_type does not match this agent")
        if task.review_id != dispatch.runtime.review_id:
            raise AgentContractError(
                "task.review_id does not match WorkerRuntime.review_id"
            )
        if task.max_retries != 0:
            raise AgentContractError(
                "Stage 2 AgentTask.max_retries must be 0"
            )
        if task.status not in _ALLOWED_TASK_STATUSES:
            raise AgentContractError(
                "agent dispatch requires a pending or running task"
            )

    # ------------------------------------------------------------------
    # 结果合同与脱敏

    def _validate_and_sanitize_result(
        self,
        result: AgentResult,
        task: AgentTask,
        dispatch: WorkerDispatch,
    ) -> AgentResult:
        if not isinstance(result, AgentResult):
            raise AgentContractError("agent result must be AgentResult")
        if result.task_id != task.task_id:
            raise AgentContractError("result.task_id does not match task")
        if result.parent_task_id != task.parent_task_id:
            raise AgentContractError(
                "result.parent_task_id does not match task"
            )
        if result.review_id != task.review_id:
            raise AgentContractError("result.review_id does not match task")
        if result.agent_name != self.agent_name:
            raise AgentContractError(
                "result.agent_name does not match this agent"
            )
        if result.commit_sha != dispatch.runtime.commit_sha:
            raise AgentContractError(
                "result.commit_sha does not match WorkerRuntime"
            )

        if result.status == "failed":
            if result.score is not None:
                raise AgentContractError("failed result must have score=None")
            if result.findings:
                raise AgentContractError("failed result must not contain findings")
            if result.error is None:
                raise AgentContractError("failed result must contain error")
        if result.error is not None and result.error.retryable:
            raise AgentContractError(
                "Stage 2 AgentResult.error.retryable must be False"
            )

        for finding in result.findings:
            if not isinstance(finding, Finding):
                raise AgentContractError("result.findings contains invalid object")
            if finding.agent_name != self.agent_name:
                raise AgentContractError(
                    "finding.agent_name does not match result agent"
                )
            if finding.verification_status != "unverified":
                raise AgentContractError(
                    "Agent must not mark findings as verified/rejected"
                )

        if not _is_json_safe(result.metadata):
            raise AgentContractError("result.metadata must be JSON-serializable")

        payload = result.model_dump()
        payload["summary"] = self._sanitize_text(
            result.summary,
            max_chars=4000,
            workspace_path=dispatch.runtime.workspace_path,
        )
        payload["findings"] = [
            self._sanitize_finding(
                finding,
                dispatch.runtime.workspace_path,
            ).model_dump()
            for finding in result.findings
        ]
        payload["metadata"] = self._sanitize_json(
            result.metadata,
            dispatch.runtime.workspace_path,
        )
        if result.error is not None:
            payload["error"] = self._sanitize_error(
                result.error,
                dispatch.runtime.workspace_path,
            ).model_dump()
        return AgentResult.model_validate(payload)

    def _validate_evidence(self, evidence: WorkerEvidence) -> WorkerEvidence:
        if not isinstance(evidence, WorkerEvidence):
            raise AgentContractError("evidence must be WorkerEvidence")
        if evidence.agent_name != self.agent_name:
            raise AgentContractError(
                "evidence.agent_name does not match this agent"
            )
        if not isinstance(evidence.usage, UsageSummary):
            raise AgentContractError("evidence.usage is invalid")
        return evidence

    def _sanitize_finding(
        self,
        finding: Finding,
        workspace_path: Path,
    ) -> Finding:
        payload = finding.model_dump()
        payload["title"] = self._sanitize_text(
            finding.title,
            max_chars=200,
            workspace_path=workspace_path,
        )
        payload["description"] = self._sanitize_text(
            finding.description,
            max_chars=4000,
            workspace_path=workspace_path,
        )
        payload["evidence"] = self._sanitize_text(
            finding.evidence,
            max_chars=4000,
            workspace_path=workspace_path,
        )
        payload["recommendation"] = self._sanitize_text(
            finding.recommendation,
            max_chars=4000,
            workspace_path=workspace_path,
        )
        return Finding.model_validate(payload)

    def _sanitize_error(
        self,
        error: ErrorInfo,
        workspace_path: Path,
    ) -> ErrorInfo:
        payload = error.model_dump()
        payload["message"] = self._sanitize_text(
            error.message,
            max_chars=2000,
            workspace_path=workspace_path,
        )
        payload["details"] = self._sanitize_json(
            error.details,
            workspace_path,
        )
        return ErrorInfo.model_validate(payload)

    def _sanitize_json(
        self,
        value: Any,
        workspace_path: Path,
    ) -> Any:
        if isinstance(value, str):
            return self._sanitize_text(
                value,
                max_chars=4000,
                workspace_path=workspace_path,
            )
        if isinstance(value, Mapping):
            return {
                key: self._sanitize_json(item, workspace_path)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [
                self._sanitize_json(item, workspace_path) for item in value
            ]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        raise AgentContractError(
            f"metadata/details is not JSON-serializable: {type(value).__name__}"
        )

    def _sanitize_text(
        self,
        text: str,
        *,
        max_chars: int,
        workspace_path: Path,
    ) -> str:
        if not isinstance(text, str):
            return ""
        cleaned = self._replace_host_paths(text, workspace_path)
        cleaned = self._redactor(cleaned, max_chars=max_chars)
        return cleaned

    @staticmethod
    def _replace_host_paths(text: str, workspace_path: Path) -> str:
        replacements: list[tuple[str, str]] = []
        try:
            replacements.append((str(workspace_path), "<workspace>"))
            replacements.append(
                (str(workspace_path).replace("\\", "/"), "<workspace>")
            )
        except (OSError, ValueError):
            pass
        replacements.extend(
            [
                (str(Path.home()), "<home>"),
                (str(Path.home()).replace("\\", "/"), "<home>"),
                (tempfile.gettempdir(), "<temp>"),
                (tempfile.gettempdir().replace("\\", "/"), "<temp>"),
            ]
        )
        # 先替换较长前缀，避免 workspace 位于 home 下时被部分替换。
        for source, target in sorted(
            {
                item
                for item in replacements
                if item[0]
                and item[0] not in {".", "./"}
                and Path(item[0]).is_absolute()
            },
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            text = text.replace(source, target)
            text = text.replace(source.replace("\\", "\\\\"), target)
        return text

    # ------------------------------------------------------------------
    # 任务生命周期与失败结果

    def _task_running(
        self,
        task: AgentTask,
        started_at: datetime,
    ) -> AgentTask:
        payload = task.model_dump()
        payload["status"] = "running"
        payload["started_at"] = task.started_at or started_at
        payload["finished_at"] = None
        payload["last_error"] = None
        return AgentTask.model_validate(payload)

    def _task_finished(
        self,
        task: AgentTask,
        result_status: str,
        finished_at: datetime,
        error: ErrorInfo | None,
    ) -> AgentTask:
        task_status = "failed" if result_status == "failed" else "completed"
        payload = task.model_dump()
        payload["status"] = task_status
        payload["started_at"] = task.started_at
        payload["finished_at"] = max(
            finished_at,
            task.started_at or task.created_at,
        )
        payload["last_error"] = error if task_status == "failed" else None
        return AgentTask.model_validate(payload)

    def _failed_result(
        self,
        task: AgentTask,
        exc: Exception,
        duration: float,
        finished_at: datetime,
        workspace_path: Path,
        commit_sha: str,
    ) -> AgentResult:
        error_type = (
            "agent_contract_error"
            if isinstance(exc, ContractValidationError)
            else "agent_execution_error"
        )
        raw_message = str(exc).strip() or type(exc).__name__
        message = self._sanitize_text(
            raw_message,
            max_chars=2000,
            workspace_path=workspace_path,
        )
        error = ErrorInfo(
            error_type=error_type,
            message=message or type(exc).__name__,
            retryable=False,
            occurred_at=finished_at,
            details={"exception_type": type(exc).__name__},
        )
        summary = self._sanitize_text(
            f"{self.agent_name} execution failed",
            max_chars=4000,
            workspace_path=workspace_path,
        )
        return AgentResult(
            task_id=task.task_id,
            parent_task_id=task.parent_task_id,
            review_id=task.review_id,
            agent_name=self.agent_name,
            status="failed",
            commit_sha=commit_sha,
            score=None,
            findings=[],
            summary=summary,
            execution_time=duration,
            error=error,
            metadata={},
        )


def _is_json_safe(value: Any) -> bool:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        return False
    return True
