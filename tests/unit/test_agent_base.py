"""Stage 2 BaseAgent 生命周期、合同校验与脱敏测试。"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest

from code_review.agents.base import AgentContractError, BaseAgent
from code_review.agents.contracts import AgentRunOutput, UsageSummary
from tests.stage2_helpers import (
    NOW,
    FakeAgent,
    make_agent_result,
    make_agent_task,
    make_dispatch,
    make_finding,
    make_worker_evidence,
    make_worker_runtime,
)


def _run(coro):
    return asyncio.run(coro)


class TestBaseAgentSuccess:
    def test_completed_lifecycle_and_timing(self, tmp_path: Path) -> None:
        task = make_agent_task()
        runtime = make_worker_runtime(tmp_path, review_id=task.review_id)
        dispatch = make_dispatch(task=task, runtime=runtime)
        agent = FakeAgent(
            clock=lambda: NOW,
            timer=iter([10.0, 10.25]).__next__,
        )
        execution = _run(agent.execute(dispatch))
        assert execution.task.status == "completed"
        assert execution.task.started_at == NOW
        assert execution.task.finished_at == NOW
        assert execution.result.status == "completed"
        assert execution.result.error is None
        assert execution.result.execution_time == 0.25
        assert execution.timing.status == "completed"
        assert execution.timing.duration_seconds == 0.25
        assert execution.evidence.agent_name == "SecurityAgent"

    def test_factory_gets_running_task(self, tmp_path: Path) -> None:
        seen: dict[str, object] = {}

        def factory(dispatch):
            seen["status"] = dispatch.task.status
            seen["started_at"] = dispatch.task.started_at
            return AgentRunOutput(
                result=make_agent_result(dispatch.task),
                evidence=make_worker_evidence(),
            )

        task = make_agent_task()
        dispatch = make_dispatch(
            task=task,
            runtime=make_worker_runtime(tmp_path, review_id=task.review_id),
        )
        agent = FakeAgent(
            result_factory=factory,
            clock=lambda: NOW,
            timer=iter([1.0, 1.5]).__next__,
        )
        execution = _run(agent.execute(dispatch))
        assert seen["status"] == "running"
        assert seen["started_at"] == NOW
        assert execution.task.status == "completed"

    def test_running_task_started_at_is_preserved(self, tmp_path: Path) -> None:
        original_start = NOW - timedelta(seconds=5)
        task = make_agent_task(status="running", created_at=original_start)
        runtime = make_worker_runtime(tmp_path, review_id=task.review_id)
        agent = FakeAgent(clock=lambda: NOW)
        execution = _run(agent.execute(make_dispatch(task=task, runtime=runtime)))
        assert execution.task.started_at == original_start
        assert execution.task.finished_at == NOW

    def test_partial_result_keeps_error_and_completes_task(
        self, tmp_path: Path
    ) -> None:
        def factory(dispatch):
            return AgentRunOutput(
                result=make_agent_result(
                    dispatch.task,
                    status="partial",
                    score=None,
                    summary="Tool evidence preserved.",
                ),
                evidence=make_worker_evidence(
                    warnings=("llm unavailable",),
                ),
            )

        task = make_agent_task()
        agent = FakeAgent(
            result_factory=factory,
            clock=lambda: NOW,
            timer=iter([2.0, 2.1]).__next__,
        )
        execution = _run(
            agent.execute(
                make_dispatch(
                    task=task,
                    runtime=make_worker_runtime(
                        tmp_path, review_id=task.review_id
                    ),
                )
            )
        )
        assert execution.result.status == "partial"
        assert execution.result.error is not None
        assert execution.task.status == "completed"
        assert execution.task.last_error is None
        assert execution.timing.status == "partial"

    def test_execution_time_is_overwritten(self, tmp_path: Path) -> None:
        def factory(dispatch):
            return AgentRunOutput(
                result=make_agent_result(
                    dispatch.task,
                    execution_time=999.0,
                ),
                evidence=make_worker_evidence(),
            )

        task = make_agent_task()
        agent = FakeAgent(
            result_factory=factory,
            clock=lambda: NOW,
            timer=iter([3.0, 3.4]).__next__,
        )
        execution = _run(
            agent.execute(
                make_dispatch(
                    task=task,
                    runtime=make_worker_runtime(
                        tmp_path, review_id=task.review_id
                    ),
                )
            )
        )
        assert execution.result.execution_time == pytest.approx(0.4)
        assert execution.timing.duration_seconds == pytest.approx(0.4)

    def test_evidence_usage_is_preserved(self, tmp_path: Path) -> None:
        usage = UsageSummary(
            llm_calls=1,
            reported_usage_calls=1,
            input_tokens=3,
            output_tokens=2,
        )

        def factory(dispatch):
            return AgentRunOutput(
                result=make_agent_result(dispatch.task),
                evidence=make_worker_evidence(usage=usage),
            )

        task = make_agent_task()
        agent = FakeAgent(result_factory=factory)
        execution = _run(
            agent.execute(
                make_dispatch(
                    task=task,
                    runtime=make_worker_runtime(
                        tmp_path, review_id=task.review_id
                    ),
                )
            )
        )
        assert execution.evidence.usage == usage


class TestBaseAgentFailures:
    def test_ordinary_exception_becomes_failed_result(
        self, tmp_path: Path
    ) -> None:
        agent = FakeAgent(
            error=RuntimeError("boom"),
            clock=lambda: NOW,
            timer=iter([4.0, 4.2]).__next__,
        )
        task = make_agent_task()
        execution = _run(
            agent.execute(
                make_dispatch(
                    task=task,
                    runtime=make_worker_runtime(
                        tmp_path, review_id=task.review_id
                    ),
                )
            )
        )
        assert execution.result.status == "failed"
        assert execution.result.error is not None
        assert execution.result.error.error_type == "agent_execution_error"
        assert execution.result.error.retryable is False
        assert execution.result.score is None
        assert execution.result.findings == []
        assert execution.task.status == "failed"
        assert execution.task.last_error is not None
        assert execution.task.finished_at is not None
        assert execution.timing.status == "failed"
        assert execution.evidence.warnings == ("agent execution failed",)

    def test_contract_error_gets_contract_error_type(
        self, tmp_path: Path
    ) -> None:
        def factory(dispatch):
            result = make_agent_result(dispatch.task)
            result = result.model_copy(update={"commit_sha": "b" * 40})
            return AgentRunOutput(
                result=result,
                evidence=make_worker_evidence(),
            )

        task = make_agent_task()
        agent = FakeAgent(result_factory=factory)
        execution = _run(
            agent.execute(
                make_dispatch(
                    task=task,
                    runtime=make_worker_runtime(
                        tmp_path, review_id=task.review_id
                    ),
                )
            )
        )
        assert execution.result.status == "failed"
        assert execution.result.error is not None
        assert execution.result.error.error_type == "agent_contract_error"

    def test_base_exception_is_not_swallowed(self, tmp_path: Path) -> None:
        class InterruptingAgent(BaseAgent):
            async def _run(self, dispatch):
                raise KeyboardInterrupt()

        task = make_agent_task()
        agent = InterruptingAgent(
            agent_name="SecurityAgent",
            task_type="security_review",
        )
        with pytest.raises(KeyboardInterrupt):
            _run(
                agent.execute(
                    make_dispatch(
                        task=task,
                        runtime=make_worker_runtime(
                            tmp_path, review_id=task.review_id
                        ),
                    )
                )
            )

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda task: task.model_copy(update={"agent_name": "OtherAgent"}),
            lambda task: task.model_copy(update={"task_type": "other_review"}),
            lambda task: task.model_copy(update={"review_id": "other-review"}),
            lambda task: task.model_copy(update={"max_retries": 1}),
        ],
    )
    def test_invalid_dispatch_is_rejected(
        self, tmp_path: Path, mutate
    ) -> None:
        task = mutate(make_agent_task())
        agent = FakeAgent()
        with pytest.raises(AgentContractError):
            _run(
                agent.execute(
                    make_dispatch(
                        task=task,
                        runtime=make_worker_runtime(tmp_path),
                    )
                )
            )

    def test_non_dispatch_is_rejected(self) -> None:
        with pytest.raises(AgentContractError):
            _run(FakeAgent().execute(object()))  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda result: result.model_copy(update={"task_id": "other"}),
            lambda result: result.model_copy(
                update={"parent_task_id": "other"}
            ),
            lambda result: result.model_copy(
                update={"review_id": "other-review"}
            ),
            lambda result: result.model_copy(
                update={"agent_name": "OtherAgent"}
            ),
            lambda result: result.model_copy(
                update={"commit_sha": "b" * 40}
            ),
        ],
    )
    def test_result_identity_mismatch_fails(
        self, tmp_path: Path, mutate
    ) -> None:
        def factory(dispatch):
            return AgentRunOutput(
                result=mutate(make_agent_result(dispatch.task)),
                evidence=make_worker_evidence(),
            )

        task = make_agent_task()
        execution = _run(
            FakeAgent(result_factory=factory).execute(
                make_dispatch(
                    task=task,
                    runtime=make_worker_runtime(
                        tmp_path, review_id=task.review_id
                    ),
                )
            )
        )
        assert execution.result.status == "failed"
        assert execution.result.error is not None
        assert execution.result.error.error_type == "agent_contract_error"

    def test_verified_finding_fails(self, tmp_path: Path) -> None:
        def factory(dispatch):
            finding = make_finding(
                agent_name="SecurityAgent",
                verification_status="verified",
            )
            result = make_agent_result(
                dispatch.task, findings=[finding]
            )
            return AgentRunOutput(
                result=result,
                evidence=make_worker_evidence(),
            )

        task = make_agent_task()
        execution = _run(
            FakeAgent(result_factory=factory).execute(
                make_dispatch(
                    task=task,
                    runtime=make_worker_runtime(
                        tmp_path, review_id=task.review_id
                    ),
                )
            )
        )
        assert execution.result.status == "failed"

    def test_wrong_finding_agent_fails(self, tmp_path: Path) -> None:
        def factory(dispatch):
            finding = make_finding(agent_name="OtherAgent")
            result = make_agent_result(dispatch.task)
            result = result.model_copy(update={"findings": [finding]})
            return AgentRunOutput(
                result=result,
                evidence=make_worker_evidence(),
            )

        task = make_agent_task()
        execution = _run(
            FakeAgent(result_factory=factory).execute(
                make_dispatch(
                    task=task,
                    runtime=make_worker_runtime(
                        tmp_path, review_id=task.review_id
                    ),
                )
            )
        )
        assert execution.result.status == "failed"

    def test_retryable_error_is_rejected(self, tmp_path: Path) -> None:
        def factory(dispatch):
            result = make_agent_result(dispatch.task, status="partial")
            result = result.model_copy(
                update={
                    "error": result.error.model_copy(
                        update={"retryable": True}
                    )
                }
            )
            return AgentRunOutput(
                result=result,
                evidence=make_worker_evidence(),
            )

        task = make_agent_task()
        execution = _run(
            FakeAgent(result_factory=factory).execute(
                make_dispatch(
                    task=task,
                    runtime=make_worker_runtime(
                        tmp_path, review_id=task.review_id
                    ),
                )
            )
        )
        assert execution.result.status == "failed"
        assert execution.result.error is not None
        assert execution.result.error.retryable is False

    def test_non_json_metadata_fails(self, tmp_path: Path) -> None:
        def factory(dispatch):
            result = make_agent_result(dispatch.task)
            result = result.model_copy(
                update={"metadata": {"bad": {1, 2}}}
            )
            return AgentRunOutput(
                result=result,
                evidence=make_worker_evidence(),
            )

        task = make_agent_task()
        execution = _run(
            FakeAgent(result_factory=factory).execute(
                make_dispatch(
                    task=task,
                    runtime=make_worker_runtime(
                        tmp_path, review_id=task.review_id
                    ),
                )
            )
        )
        assert execution.result.status == "failed"

    def test_wrong_evidence_agent_fails(self, tmp_path: Path) -> None:
        def factory(dispatch):
            return AgentRunOutput(
                result=make_agent_result(dispatch.task),
                evidence=make_worker_evidence(agent_name="OtherAgent"),
            )

        task = make_agent_task()
        execution = _run(
            FakeAgent(result_factory=factory).execute(
                make_dispatch(
                    task=task,
                    runtime=make_worker_runtime(
                        tmp_path, review_id=task.review_id
                    ),
                )
            )
        )
        assert execution.result.status == "failed"

    def test_wrong_run_output_type_fails(self, tmp_path: Path) -> None:
        class BadAgent(BaseAgent):
            async def _run(self, dispatch):
                return object()

        task = make_agent_task()
        agent = BadAgent(
            agent_name="SecurityAgent",
            task_type="security_review",
        )
        execution = _run(
            agent.execute(
                make_dispatch(
                    task=task,
                    runtime=make_worker_runtime(
                        tmp_path, review_id=task.review_id
                    ),
                )
            )
        )
        assert execution.result.status == "failed"


class TestRedaction:
    def test_success_text_is_redacted(self, tmp_path: Path) -> None:
        secret_text = f"password = 'hunter2' at {tmp_path / 'pkg' / 'app.py'}"

        def factory(dispatch):
            finding = make_finding(
                agent_name="SecurityAgent",
                title=secret_text,
                description=secret_text,
                evidence=secret_text,
                recommendation=secret_text,
            )
            result = make_agent_result(
                dispatch.task,
                findings=[finding],
                summary=secret_text,
                metadata={"detail": secret_text},
            )
            return AgentRunOutput(
                result=result,
                evidence=make_worker_evidence(),
            )

        task = make_agent_task()
        execution = _run(
            FakeAgent(result_factory=factory).execute(
                make_dispatch(
                    task=task,
                    runtime=make_worker_runtime(
                        tmp_path, review_id=task.review_id
                    ),
                )
            )
        )
        result = execution.result
        assert "hunter2" not in result.summary
        assert "<workspace>" in result.summary
        assert "hunter2" not in result.findings[0].description
        assert "hunter2" not in result.findings[0].evidence
        assert "hunter2" not in result.findings[0].recommendation
        assert "hunter2" not in str(result.metadata)

    def test_failure_text_is_redacted(self, tmp_path: Path) -> None:
        message = f"password = 'hunter2' at {tmp_path / 'pkg' / 'app.py'}"
        task = make_agent_task()
        execution = _run(
            FakeAgent(error=RuntimeError(message)).execute(
                make_dispatch(
                    task=task,
                    runtime=make_worker_runtime(
                        tmp_path, review_id=task.review_id
                    ),
                )
            )
        )
        assert execution.result.error is not None
        assert "hunter2" not in execution.result.error.message
        assert str(tmp_path) not in execution.result.error.message
        assert "<workspace>" in execution.result.error.message
        assert "hunter2" not in str(execution.result.metadata)

    def test_summary_is_bounded(self, tmp_path: Path) -> None:
        def factory(dispatch):
            result = make_agent_result(dispatch.task)
            result = result.model_copy(update={"summary": "x" * 5000})
            return AgentRunOutput(
                result=result,
                evidence=make_worker_evidence(),
            )

        task = make_agent_task()
        execution = _run(
            FakeAgent(result_factory=factory).execute(
                make_dispatch(
                    task=task,
                    runtime=make_worker_runtime(
                        tmp_path, review_id=task.review_id
                    ),
                )
            )
        )
        assert execution.result.status == "completed"
        assert len(execution.result.summary) == 4000
