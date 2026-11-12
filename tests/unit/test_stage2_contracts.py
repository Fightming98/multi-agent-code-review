"""Stage 2 内部合同与 ArtifactData 单元测试。"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from types import MappingProxyType

import pytest

from code_review.agents.contracts import (
    AgentExecution,
    AgentRunOutput,
    ArtifactData,
    ArtifactPointerError,
    ContractValidationError,
    UsageSummary,
    WorkerDispatch,
    WorkerEvidence,
    WorkerRuntime,
    WorkerTiming,
)
from code_review.schemas.result import AgentResult
from tests.stage2_helpers import (
    COMMIT_SHA,
    NOW,
    REVIEW_ID,
    make_agent_result,
    make_agent_task,
    make_finding,
    make_review_rules,
    make_worker_evidence,
)


class TestUsageSummary:
    def test_defaults_are_zero(self) -> None:
        usage = UsageSummary()
        assert usage.llm_calls == 0
        assert usage.reported_usage_calls == 0
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.total_tokens == 0

    def test_total_tokens_and_add(self) -> None:
        first = UsageSummary(
            llm_calls=2,
            reported_usage_calls=1,
            input_tokens=10,
            output_tokens=4,
        )
        second = UsageSummary(
            llm_calls=1,
            reported_usage_calls=1,
            input_tokens=7,
            output_tokens=3,
        )
        combined = first + second
        assert combined.llm_calls == 3
        assert combined.reported_usage_calls == 2
        assert combined.input_tokens == 17
        assert combined.output_tokens == 7
        assert combined.total_tokens == 24

    def test_add_rejects_other_type(self) -> None:
        with pytest.raises(TypeError):
            UsageSummary() + 1  # type: ignore[operator]

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("llm_calls", -1),
            ("reported_usage_calls", -1),
            ("input_tokens", -1),
            ("output_tokens", -1),
            ("llm_calls", True),
            ("input_tokens", 1.5),
        ],
    )
    def test_rejects_invalid_counts(self, field: str, value: object) -> None:
        with pytest.raises(ContractValidationError):
            UsageSummary(**{field: value})  # type: ignore[arg-type]

    def test_reported_usage_cannot_exceed_calls(self) -> None:
        with pytest.raises(ContractValidationError):
            UsageSummary(llm_calls=1, reported_usage_calls=2)


class TestWorkerRuntime:
    def test_accepts_valid_runtime_and_normalizes_paths(
        self, tmp_path: Path
    ) -> None:
        runtime = WorkerRuntime(
            workspace_path=tmp_path,
            allowed_files=("pkg/app.py", "README.md"),
            commit_sha=COMMIT_SHA,
            language="python",
            review_id=REVIEW_ID,
            rules=make_review_rules(),
        )
        assert runtime.workspace_path == tmp_path
        assert runtime.allowed_files == ("pkg/app.py", "README.md")

    def test_workspace_can_be_string(self, tmp_path: Path) -> None:
        runtime = WorkerRuntime(
            workspace_path=str(tmp_path),  # type: ignore[arg-type]
            allowed_files=(),
            commit_sha=COMMIT_SHA,
            language="python",
            review_id=REVIEW_ID,
            rules=make_review_rules(),
        )
        assert runtime.workspace_path == tmp_path

    @pytest.mark.parametrize(
        "allowed",
        [
            ("/abs/path.py",),
            ("C:/repo/app.py",),
            ("pkg\\app.py",),
            ("../app.py",),
            ("./app.py",),
            ("",),
        ],
    )
    def test_rejects_unsafe_allowed_file(
        self, tmp_path: Path, allowed: tuple[str, ...]
    ) -> None:
        with pytest.raises(ContractValidationError):
            WorkerRuntime(
                workspace_path=tmp_path,
                allowed_files=allowed,
                commit_sha=COMMIT_SHA,
                language="python",
                review_id=REVIEW_ID,
                rules=make_review_rules(),
            )

    @pytest.mark.parametrize(
        "commit_sha",
        ["a" * 39, "A" * 40, "g" * 40, ""],
    )
    def test_rejects_invalid_commit(
        self, tmp_path: Path, commit_sha: str
    ) -> None:
        with pytest.raises(ContractValidationError):
            WorkerRuntime(
                workspace_path=tmp_path,
                allowed_files=(),
                commit_sha=commit_sha,
                language="python",
                review_id=REVIEW_ID,
                rules=make_review_rules(),
            )

    def test_rejects_empty_language_review_id_and_trace_id(
        self, tmp_path: Path
    ) -> None:
        rules = make_review_rules()
        for updates in (
            {"language": ""},
            {"review_id": ""},
            {"trace_id": ""},
        ):
            payload = {
                "workspace_path": tmp_path,
                "allowed_files": (),
                "commit_sha": COMMIT_SHA,
                "language": "python",
                "review_id": REVIEW_ID,
                "rules": rules,
            }
            payload.update(updates)
            with pytest.raises(ContractValidationError):
                WorkerRuntime(**payload)

    def test_rejects_allowed_files_string(self, tmp_path: Path) -> None:
        with pytest.raises(ContractValidationError):
            WorkerRuntime(
                workspace_path=tmp_path,
                allowed_files="pkg/app.py",  # type: ignore[arg-type]
                commit_sha=COMMIT_SHA,
                language="python",
                review_id=REVIEW_ID,
                rules=make_review_rules(),
            )

    def test_rejects_invalid_workspace_path(self) -> None:
        with pytest.raises(ContractValidationError):
            WorkerRuntime(
                workspace_path=None,  # type: ignore[arg-type]
                allowed_files=(),
                commit_sha=COMMIT_SHA,
                language="python",
                review_id=REVIEW_ID,
                rules=make_review_rules(),
            )

    def test_rejects_invalid_rules(self, tmp_path: Path) -> None:
        with pytest.raises(ContractValidationError):
            WorkerRuntime(
                workspace_path=tmp_path,
                allowed_files=(),
                commit_sha=COMMIT_SHA,
                language="python",
                review_id=REVIEW_ID,
                rules=object(),  # type: ignore[arg-type]
            )


class TestWorkerDispatchAndEvidence:
    def test_dispatch_requires_contract_types(self) -> None:
        with pytest.raises(ContractValidationError):
            WorkerDispatch(task=object(), runtime=object())  # type: ignore[arg-type]

    def test_evidence_freezes_nested_json(self) -> None:
        evidence = WorkerEvidence(
            agent_name="SecurityAgent",
            static_analysis={"agents": {"security": {"findings": [1]}}},
        )
        assert isinstance(evidence.static_analysis, MappingProxyType)
        assert isinstance(evidence.static_analysis["agents"], MappingProxyType)
        with pytest.raises(TypeError):
            evidence.static_analysis["agents"] = {}  # type: ignore[index]

    def test_evidence_rejects_non_json_values(self) -> None:
        with pytest.raises(ContractValidationError):
            WorkerEvidence(
                agent_name="SecurityAgent",
                static_analysis={"bad": {1, 2}},
            )
        with pytest.raises(ContractValidationError):
            WorkerEvidence(
                agent_name="SecurityAgent",
                static_analysis={"bad": float("nan")},
            )

    def test_evidence_rejects_empty_agent_and_warning(self) -> None:
        with pytest.raises(ContractValidationError):
            WorkerEvidence(agent_name="")
        with pytest.raises(ContractValidationError):
            WorkerEvidence(agent_name="SecurityAgent", warnings=("",))

    def test_evidence_rejects_non_mapping_json(self) -> None:
        with pytest.raises(ContractValidationError):
            WorkerEvidence(
                agent_name="SecurityAgent",
                static_analysis=None,  # type: ignore[arg-type]
            )
        with pytest.raises(ContractValidationError):
            WorkerEvidence(
                agent_name="TestingAgent",
                test_report=[],  # type: ignore[arg-type]
            )

    def test_evidence_accepts_test_report(self) -> None:
        evidence = WorkerEvidence(
            agent_name="TestingAgent",
            test_report={"coverage": 81.5},
        )
        assert evidence.test_report is not None
        assert evidence.test_report["coverage"] == 81.5


class TestWorkerTiming:
    def test_valid_timing_converts_duration(self) -> None:
        timing = WorkerTiming(
            agent_name="SecurityAgent",
            task_id="task-1",
            started_at=NOW,
            finished_at=NOW + timedelta(seconds=1),
            duration_seconds=1,
            status="completed",
        )
        assert timing.duration_seconds == 1.0

    def test_rejects_finished_before_started(self) -> None:
        with pytest.raises(ContractValidationError):
            WorkerTiming(
                agent_name="SecurityAgent",
                task_id="task-1",
                started_at=NOW,
                finished_at=NOW - timedelta(seconds=1),
                duration_seconds=1,
                status="completed",
            )

    @pytest.mark.parametrize("duration", [-1, True, "1"])
    def test_rejects_invalid_duration(self, duration: object) -> None:
        with pytest.raises(ContractValidationError):
            WorkerTiming(
                agent_name="SecurityAgent",
                task_id="task-1",
                started_at=NOW,
                finished_at=NOW,
                duration_seconds=duration,  # type: ignore[arg-type]
                status="completed",
            )

    def test_rejects_invalid_status(self) -> None:
        with pytest.raises(ContractValidationError):
            WorkerTiming(
                agent_name="SecurityAgent",
                task_id="task-1",
                started_at=NOW,
                finished_at=NOW,
                duration_seconds=0,
                status="running",
            )

    def test_rejects_non_datetime(self) -> None:
        with pytest.raises(ContractValidationError):
            WorkerTiming(
                agent_name="SecurityAgent",
                task_id="task-1",
                started_at="now",  # type: ignore[arg-type]
                finished_at=NOW,
                duration_seconds=0,
                status="completed",
            )


class TestArtifactData:
    def test_resolves_nested_mapping_and_array(self) -> None:
        data = ArtifactData(
            static_analysis={
                "agents": {
                    "security": {
                        "tools": {
                            "bandit": {
                                "findings": [
                                    {"rule_id": "B608"},
                                ]
                            }
                        }
                    }
                }
            }
        )
        assert data.resolve(
            "static_analysis.json#/agents/security/tools/bandit/findings/0/rule_id"
        ) == "B608"

    def test_resolves_test_report_root_and_field(self) -> None:
        data = ArtifactData(test_report={"coverage": 80.0, "counts": {"passed": 3}})
        assert data.resolve("test_report.json#/coverage") == 80.0
        assert data.resolve("test_report.json#")["counts"] == {"passed": 3}

    def test_decodes_json_pointer_escapes(self) -> None:
        data = ArtifactData(static_analysis={"a/b": {"x~y": 1}})
        assert data.resolve("static_analysis.json#/a~1b/x~0y") == 1

    def test_resolved_values_are_copies(self) -> None:
        data = ArtifactData(static_analysis={"nested": {"value": 1}})
        node = data.resolve("static_analysis.json#/nested")
        node["value"] = 2
        assert data.resolve("static_analysis.json#/nested/value") == 1
        root = data.static_analysis_dict()
        root["nested"]["value"] = 3
        assert data.resolve("static_analysis.json#/nested/value") == 1

    def test_mapping_is_read_only(self) -> None:
        data = ArtifactData(static_analysis={"value": 1})
        with pytest.raises(TypeError):
            data.static_analysis["value"] = 2  # type: ignore[index]

    @pytest.mark.parametrize(
        "pointer",
        [
            "static_analysis.json",
            "other.json#/x",
            "static_analysis.json#x",
            "static_analysis.json#/missing",
            "static_analysis.json#/items/2",
            "static_analysis.json#/items/x",
            "static_analysis.json#/value/x",
            "static_analysis.json#/items/01",
        ],
    )
    def test_rejects_invalid_pointer(self, pointer: str) -> None:
        data = ArtifactData(
            static_analysis={"items": [1, 2], "value": 3}
        )
        with pytest.raises(ArtifactPointerError):
            data.resolve(pointer)

    def test_rejects_non_json_and_non_finite(self) -> None:
        with pytest.raises(ContractValidationError):
            ArtifactData(static_analysis={"bad": object()})
        with pytest.raises(ContractValidationError):
            ArtifactData(static_analysis={"bad": float("inf")})
        with pytest.raises(ContractValidationError):
            ArtifactData(static_analysis=None)  # type: ignore[arg-type]
        with pytest.raises(ContractValidationError):
            ArtifactData(test_report=[])  # type: ignore[arg-type]

    def test_root_fragment_returns_copy(self) -> None:
        data = ArtifactData(static_analysis={"x": [1, 2]})
        root = data.resolve("static_analysis.json#")
        root["x"].append(3)
        assert data.resolve("static_analysis.json#/x") == [1, 2]


class TestExecutionContracts:
    def test_agent_run_output_requires_contract_types(self) -> None:
        task = make_agent_task()
        result = make_agent_result(task)
        evidence = make_worker_evidence()
        with pytest.raises(ContractValidationError):
            AgentRunOutput(result=object(), evidence=evidence)  # type: ignore[arg-type]
        with pytest.raises(ContractValidationError):
            AgentRunOutput(result=result, evidence=object())  # type: ignore[arg-type]

    def test_agent_execution_requires_contract_types(self) -> None:
        task = make_agent_task()
        result = make_agent_result(task)
        evidence = make_worker_evidence()
        timing = WorkerTiming(
            agent_name="SecurityAgent",
            task_id=task.task_id,
            started_at=NOW,
            finished_at=NOW,
            duration_seconds=0,
            status="completed",
        )
        execution = AgentExecution(
            task=task,
            result=result,
            evidence=evidence,
            timing=timing,
        )
        assert execution.result is result
        with pytest.raises(ContractValidationError):
            AgentExecution(
                task=task,
                result=result,
                evidence=evidence,
                timing=object(),  # type: ignore[arg-type]
            )

    def test_finding_default_is_unverified(self) -> None:
        finding = make_finding()
        assert finding.verification_status == "unverified"
        assert isinstance(finding.tool_evidence, list)

    def test_agent_result_factory_is_valid(self) -> None:
        task = make_agent_task()
        result = make_agent_result(task)
        assert isinstance(result, AgentResult)
        assert result.task_id == task.task_id
        assert result.commit_sha == COMMIT_SHA
        assert result.status == "completed"
