"""Stage 2 五件报告产物生成。

本模块与 Stage 1 的 ``ReportGenerator`` 并行存在：Stage 1 生成器保持四件
产物且行为冻结，Stage 2 生成器生成：

``metadata.json``、``static_analysis.json``、``test_report.json``、
``report.json``、``report.md``。

关键不变量：

- ``static_analysis.json`` / ``test_report.json`` 必须由 Final Reviewer 使用
  的同一份 ``ArtifactData`` 写出，不重新拼装、不估算；
- ``report.json`` 与 ``report.md`` 必须来自同一个已通过冻结 Schema 校验的
  ``ReviewReport`` 对象；
- 写入前统一净化工作区、主目录、临时目录与敏感文本；净化后重新校验；
- 写入前后校验 ``Finding.tool_evidence.raw_output_ref`` 在内存 ``ArtifactData``
  与落盘 JSON 中解析到相同内容；
- 任一失败都删除本次未完成的报告目录，不留下伪 partial 报告；
- O-1：存在真实 LLM 调用但成本语义未解决时拒绝生成，不能写零成本。
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from code_review.agents.contracts import ArtifactData, UsageSummary
from code_review.reporting.artifact_models import (
    ExecutionEnvironmentArtifact,
    InventorySummaryArtifact,
)
from code_review.reporting.report_generator import (
    InventorySummary,
    ReportGenerationError,
)
from code_review.reporting.stage2_models import (
    STAGE2_CORE_DIMENSIONS,
    Stage2MetadataArtifact,
    Stage2StaticAnalysisArtifact,
    Stage2TestReportArtifact,
)
from code_review.schemas.report import ReviewReport
from code_review.schemas.result import Finding
from code_review.services.redaction import redact_sensitive_text

__all__ = [
    "Stage2ArtifactInput",
    "Stage2ReportArtifacts",
    "Stage2ReportGenerationError",
    "Stage2ReportGenerator",
    "Stage2ReportOutputError",
    "render_stage2_markdown",
]

_REPOSITORY_URL_PREFIX = "https://github.com/"
_FIXTURE_URL_PREFIX = "fixture://"
_POINTER_PREFIXES = ("static_analysis.json", "test_report.json")


class Stage2ReportGenerationError(ReportGenerationError):
    """Stage 2 报告构建、序列化或证据一致性校验失败。"""


class Stage2ReportOutputError(Stage2ReportGenerationError):
    """Stage 2 输出目录不可用或已存在。"""


@dataclass(frozen=True)
class Stage2ArtifactInput:
    """生成 Stage 2 五件产物所需的全部真实输入。"""

    report: ReviewReport
    artifact_data: ArtifactData
    usage_summary: UsageSummary
    source_type: str
    reviewed_at: datetime
    inventory: InventorySummary | None
    review_duration_seconds: float
    warnings: Sequence[str] = ()
    workspace_path: Path | None = None
    fixture_manifest_sha256: str | None = None


@dataclass(frozen=True)
class Stage2ReportArtifacts:
    """已写入磁盘的五件产物及其校验后的模型。"""

    review_id: str
    report_dir: Path
    metadata_path: Path
    static_analysis_path: Path
    test_report_path: Path
    report_json_path: Path
    markdown_path: Path
    metadata: Stage2MetadataArtifact
    static_analysis: Stage2StaticAnalysisArtifact
    test_report: Stage2TestReportArtifact
    report: ReviewReport


class Stage2ReportGenerator:
    """从同一个 ``ArtifactData`` 与 ``ReviewReport`` 生成五件产物。"""

    def generate(
        self,
        source: Stage2ArtifactInput,
        output_root: Path | str,
    ) -> Stage2ReportArtifacts:
        self._validate_source(source)

        # O-1：真实 LLM 调用的成本语义尚未解决，禁止冒充零成本。
        if source.usage_summary.llm_calls:
            raise Stage2ReportGenerationError(
                "stage 2 report generation refused: real LLM usage cannot be "
                "represented by the frozen CostSummary"
            )

        report = _sanitize_report(source.report, source.workspace_path)
        metadata = _sanitize_model(
            self._build_metadata(source, report), source.workspace_path
        )
        static_analysis = _build_static_analysis(
            source.artifact_data, source.workspace_path
        )
        test_report = _build_test_report(
            source.artifact_data, source.workspace_path
        )

        # 先证明内存与落盘内容会在每个真实 Pointer 上保持一致，再写盘。
        _verify_pointer_consistency(
            report=report,
            artifact_data=source.artifact_data,
            static_payload=static_analysis.model_dump(mode="json"),
            test_payload=test_report.model_dump(mode="json"),
        )

        try:
            root = Path(output_root).expanduser().resolve()
            report_dir = root / report.review_id
        except OSError as exc:
            raise Stage2ReportOutputError(
                "stage 2 report output directory is invalid"
            ) from exc
        if report_dir.exists():
            raise Stage2ReportOutputError(
                "stage 2 report output directory already exists"
            )

        paths = {
            "metadata": report_dir / "metadata.json",
            "static": report_dir / "static_analysis.json",
            "test": report_dir / "test_report.json",
            "report": report_dir / "report.json",
            "markdown": report_dir / "report.md",
        }

        try:
            report_dir.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            raise Stage2ReportOutputError(
                "stage 2 report output directory could not be created"
            ) from exc

        try:
            _write_json(paths["metadata"], metadata)
            _write_json(paths["static"], static_analysis)
            _write_json(paths["test"], test_report)
            _write_json(paths["report"], report)

            # Markdown 只读取已校验的同一个 ReviewReport 与已净化 metadata。
            markdown = render_stage2_markdown(report, metadata)
            _write_text(paths["markdown"], markdown)
        except Exception as exc:
            shutil.rmtree(report_dir, ignore_errors=True)
            if isinstance(exc, Stage2ReportGenerationError):
                raise
            raise Stage2ReportGenerationError(
                "stage 2 report generation failed"
            ) from exc

        return Stage2ReportArtifacts(
            review_id=report.review_id,
            report_dir=report_dir,
            metadata_path=paths["metadata"],
            static_analysis_path=paths["static"],
            test_report_path=paths["test"],
            report_json_path=paths["report"],
            markdown_path=paths["markdown"],
            metadata=metadata,
            static_analysis=static_analysis,
            test_report=test_report,
            report=report,
        )

    # ------------------------------------------------------------------
    # Validation and metadata
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_source(source: Stage2ArtifactInput) -> None:
        if not isinstance(source, Stage2ArtifactInput):
            raise Stage2ReportGenerationError(
                "stage 2 report source must be a Stage2ArtifactInput"
            )
        if not isinstance(source.report, ReviewReport):
            raise Stage2ReportGenerationError(
                "stage 2 report must be a validated ReviewReport"
            )
        if not isinstance(source.artifact_data, ArtifactData):
            raise Stage2ReportGenerationError(
                "stage 2 report must use the ArtifactData from the Final Reviewer"
            )
        if not isinstance(source.usage_summary, UsageSummary):
            raise Stage2ReportGenerationError(
                "stage 2 report usage summary is invalid"
            )
        if source.source_type not in {"github_repository", "trusted_fixture"}:
            raise Stage2ReportGenerationError(
                "stage 2 report source_type is invalid"
            )
        if not isinstance(source.reviewed_at, datetime) or (
            source.reviewed_at.tzinfo is None
            or source.reviewed_at.utcoffset() is None
        ):
            raise Stage2ReportGenerationError(
                "stage 2 reviewed_at must be timezone-aware"
            )
        if source.reviewed_at.utcoffset().total_seconds() != 0:
            raise Stage2ReportGenerationError(
                "stage 2 reviewed_at must be UTC"
            )
        agents = source.artifact_data.static_analysis.get("agents")
        if not isinstance(agents, Mapping):
            raise Stage2ReportGenerationError(
                "ArtifactData.static_analysis must contain an agents mapping"
            )
        if set(agents) != STAGE2_CORE_DIMENSIONS:
            raise Stage2ReportGenerationError(
                "ArtifactData.static_analysis must contain exactly the four "
                "core dimensions"
            )
        if (
            source.source_type == "github_repository"
            and not source.report.repository_url.startswith(
                _REPOSITORY_URL_PREFIX
            )
        ):
            raise Stage2ReportGenerationError(
                "github repository URL must use https://github.com"
            )
        if source.source_type == "trusted_fixture" and not (
            source.report.repository_url.startswith(_FIXTURE_URL_PREFIX)
        ):
            raise Stage2ReportGenerationError(
                "trusted fixture URL must use fixture://"
            )

    def _build_metadata(
        self,
        source: Stage2ArtifactInput,
        report: ReviewReport,
    ) -> Stage2MetadataArtifact:
        static_payload = source.artifact_data.static_analysis
        test_payload = source.artifact_data.test_report
        agents = static_payload.get("agents")
        if not isinstance(agents, Mapping):
            raise Stage2ReportGenerationError(
                "ArtifactData.static_analysis must contain an agents mapping"
            )
        missing = STAGE2_CORE_DIMENSIONS.difference(agents)
        if missing:
            raise Stage2ReportGenerationError(
                "ArtifactData.static_analysis is missing core dimensions"
            )

        inventory = (
            None
            if source.inventory is None
            else InventorySummaryArtifact(**asdict(source.inventory))
        )
        return Stage2MetadataArtifact(
            source_type=source.source_type,  # type: ignore[arg-type]
            review_id=report.review_id,
            repository_url=report.repository_url,
            repository_name=report.repository,
            branch=report.branch,
            commit_sha=report.commit_sha,
            fixture_manifest_sha256=source.fixture_manifest_sha256,
            review_status=report.report_status,
            reviewed_at=source.reviewed_at,
            discovered_file_count=(
                source.inventory.total_files if source.inventory else 0
            ),
            analyzed_file_count=(
                source.inventory.python_source_files
                if source.inventory
                else 0
            ),
            tool_versions=_collect_tool_versions(static_payload, test_payload),
            execution_environment=ExecutionEnvironmentArtifact(
                python_version=(
                    f"{sys.version_info.major}.{sys.version_info.minor}."
                    f"{sys.version_info.micro}"
                ),
                python_implementation=platform.python_implementation(),
                platform_system=platform.system() or "unknown",
                platform_release=platform.release() or "unknown",
                platform_machine=platform.machine() or "unknown",
            ),
            inventory=inventory,
            review_duration_seconds=round(source.review_duration_seconds, 3),
            warnings=list(source.warnings),
        )


# ----------------------------------------------------------------------
# Artifact payloads
# ----------------------------------------------------------------------
def _build_static_analysis(
    artifact_data: ArtifactData,
    workspace_path: Path | None,
) -> Stage2StaticAnalysisArtifact:
    payload = _sanitize_value(
        artifact_data.static_analysis, workspace_path
    )
    try:
        return Stage2StaticAnalysisArtifact.model_validate(payload)
    except Exception as exc:
        raise Stage2ReportGenerationError(
            "sanitized static_analysis.json failed validation"
        ) from exc


def _build_test_report(
    artifact_data: ArtifactData,
    workspace_path: Path | None,
) -> Stage2TestReportArtifact:
    payload = _sanitize_value(artifact_data.test_report, workspace_path)
    try:
        return Stage2TestReportArtifact.model_validate(payload)
    except Exception as exc:
        raise Stage2ReportGenerationError(
            "sanitized test_report.json failed validation"
        ) from exc


def _collect_tool_versions(
    static_payload: Mapping[str, Any],
    test_payload: Mapping[str, Any],
) -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    agents = static_payload.get("agents")
    if isinstance(agents, Mapping):
        for block in agents.values():
            if not isinstance(block, Mapping):
                continue
            tools = block.get("tools")
            if not isinstance(tools, Mapping):
                continue
            for name, tool_block in tools.items():
                if not isinstance(name, str) or name in versions:
                    continue
                version = (
                    tool_block.get("tool_version")
                    if isinstance(tool_block, Mapping)
                    else None
                )
                versions[name] = version if isinstance(version, str) else None
    test_versions = test_payload.get("tool_versions")
    if isinstance(test_versions, Mapping):
        for name, version in test_versions.items():
            if not isinstance(name, str) or name in versions:
                continue
            versions[name] = version if isinstance(version, str) else None
    return dict(sorted(versions.items()))


# ----------------------------------------------------------------------
# Sanitization
# ----------------------------------------------------------------------
def _sanitize_report(
    report: ReviewReport,
    workspace_path: Path | None,
) -> ReviewReport:
    payload = report.model_dump(mode="json")
    sanitized = _sanitize_value(payload, workspace_path)
    try:
        return ReviewReport.model_validate(sanitized)
    except Exception as exc:
        raise Stage2ReportGenerationError(
            "sanitized report.json failed validation"
        ) from exc


def _sanitize_model(model: Any, workspace_path: Path | None) -> Any:
    payload = model.model_dump(mode="json")
    sanitized = _sanitize_value(payload, workspace_path)
    try:
        return type(model).model_validate(sanitized)
    except Exception as exc:
        raise Stage2ReportGenerationError(
            f"sanitized artifact failed validation: {type(model).__name__}"
        ) from exc


def _sanitize_value(value: Any, workspace_path: Path | None) -> Any:
    if isinstance(value, str):
        return _sanitize_text(value, workspace_path)
    if isinstance(value, Mapping):
        return {
            key: _sanitize_value(item, workspace_path)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item, workspace_path) for item in value]
    return value


def _add_path_replacement(
    replacements: list[tuple[str, str]], raw: str, replacement: str
) -> None:
    """登记路径替换，同时覆盖 JSON 字符串中转义后的 Windows 路径。"""

    if not raw:
        return
    variants = {raw}
    escaped = raw
    if "\\" in raw:
        for _ in range(3):
            escaped = escaped.replace("\\", "\\\\")
            variants.add(escaped)
    for variant in variants:
        replacements.append((variant, replacement))


def _sanitize_text(text: str, workspace_path: Path | None) -> str:
    replacements: list[tuple[str, str]] = []
    if workspace_path is not None:
        try:
            workspace = Path(workspace_path).expanduser().resolve()
        except OSError:
            workspace = Path(workspace_path)
        _add_path_replacement(replacements, str(workspace), "<workspace>")
        _add_path_replacement(
            replacements, workspace.as_posix(), "<workspace>"
        )
    try:
        _add_path_replacement(replacements, str(Path.home()), "<home>")
        _add_path_replacement(replacements, Path.home().as_posix(), "<home>")
    except (OSError, RuntimeError):
        pass
    try:
        temp_dir = tempfile.gettempdir()
        _add_path_replacement(replacements, str(temp_dir), "<temp>")
        _add_path_replacement(
            replacements, Path(temp_dir).as_posix(), "<temp>"
        )
    except (OSError, RuntimeError):
        pass

    result = text
    for raw, replacement in sorted(
        replacements, key=lambda item: len(item[0]), reverse=True
    ):
        if not raw:
            continue
        flags = re.IGNORECASE if os.name == "nt" else 0
        result = re.sub(re.escape(raw), replacement, result, flags=flags)
    return redact_sensitive_text(result)


# ----------------------------------------------------------------------
# Pointer consistency
# ----------------------------------------------------------------------
def _verify_pointer_consistency(
    *,
    report: ReviewReport,
    artifact_data: ArtifactData,
    static_payload: Mapping[str, Any],
    test_payload: Mapping[str, Any],
) -> None:
    payloads: dict[str, Mapping[str, Any]] = {
        "static_analysis.json": static_payload,
        "test_report.json": test_payload,
    }
    for finding in (*report.findings, *report.rejected_findings):
        for evidence in finding.tool_evidence:
            pointer = evidence.raw_output_ref
            try:
                memory_value = artifact_data.resolve(pointer)
            except Exception as exc:
                raise Stage2ReportGenerationError(
                    "tool evidence pointer cannot be resolved in ArtifactData"
                ) from exc
            disk_value = _resolve_disk_pointer(payloads, pointer)
            if memory_value != disk_value:
                raise Stage2ReportGenerationError(
                    "tool evidence pointer differs between ArtifactData and "
                    "the sanitized report payload"
                )


def _resolve_disk_pointer(
    payloads: Mapping[str, Mapping[str, Any]],
    pointer: str,
) -> Any:
    if not isinstance(pointer, str) or "#" not in pointer:
        raise Stage2ReportGenerationError(
            "tool evidence pointer must contain '#'"
        )
    file_name, fragment = pointer.split("#", 1)
    if file_name not in _POINTER_PREFIXES or file_name not in payloads:
        raise Stage2ReportGenerationError(
            "tool evidence pointer must target static_analysis.json or "
            "test_report.json"
        )
    node: Any = payloads[file_name]
    if fragment == "":
        return node
    if not fragment.startswith("/"):
        raise Stage2ReportGenerationError(
            "tool evidence pointer fragment must start with '/'"
        )
    for raw_token in fragment[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, Mapping):
            if token not in node:
                raise Stage2ReportGenerationError(
                    "tool evidence pointer key is missing from disk payload"
                )
            node = node[token]
            continue
        if isinstance(node, list):
            if not token.isdigit() or (
                len(token) > 1 and token.startswith("0")
            ):
                raise Stage2ReportGenerationError(
                    "tool evidence pointer array index is invalid"
                )
            index = int(token)
            if index >= len(node):
                raise Stage2ReportGenerationError(
                    "tool evidence pointer array index is out of range"
                )
            node = node[index]
            continue
        raise Stage2ReportGenerationError(
            "tool evidence pointer cannot descend into a scalar value"
        )
    return node


# ----------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------
def _write_json(path: Path, model: Any) -> None:
    text = json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=False,
    )
    _write_text(path, text + "\n")
    try:
        type(model).model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise Stage2ReportGenerationError(
            f"report JSON failed validation: {path.name}"
        ) from exc


def _write_text(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


# ----------------------------------------------------------------------
# Markdown
# ----------------------------------------------------------------------
def render_stage2_markdown(
    report: ReviewReport,
    metadata: Stage2MetadataArtifact,
) -> str:
    """仅依据已校验的 ReviewReport 与 metadata 渲染 Markdown。"""

    lines: list[str] = [
        "# Stage 2 代码审查报告",
        "",
        f"- Review ID：`{report.review_id}`",
        f"- 仓库：`{report.repository}`",
        f"- 仓库地址：{report.repository_url}",
        f"- 分支：`{report.branch}`",
        f"- Commit SHA：`{report.commit_sha}`",
        f"- 生成时间：{metadata.reviewed_at.isoformat()}",
        f"- 报告状态：`{report.report_status}`",
        "",
        "## 1. 总体结论",
        "",
        f"- 结论：**{report.overall_verdict}**",
        f"- 综合分：{_format_score(report.overall_score)}",
    ]
    lines.extend(
        f"- 理由：{reason}" for reason in report.verdict_reasons
    )
    if report.summary:
        lines.extend(["", report.summary])
    lines.extend(
        [
            "",
            "## 2. 维度评分",
            "",
            "| 维度 | 状态 | 评分 | 权重 | Finding 数 | 说明 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for dimension, item in report.dimension_scores.items():
        lines.append(
            f"| {dimension} | {item.status} | "
            f"{_format_score(item.score)} | {item.weight:.0%} | "
            f"{item.finding_count} | {_cell(item.reason)} |"
        )

    lines.extend(["", "## 3. 已确认 Finding", ""])
    if not report.findings:
        lines.append("无。")
    else:
        for index, finding in enumerate(report.findings, start=1):
            lines.extend(_render_finding(index, finding))

    lines.extend(["", "## 4. 被拒绝的 Finding", ""])
    if not report.rejected_findings:
        lines.append("无。")
    else:
        for index, finding in enumerate(report.rejected_findings, start=1):
            location = _location(finding)
            lines.append(
                f"{index}. [{finding.severity}] {_one_line(finding.title)}"
                f"（{finding.agent_name}，{location}）"
            )

    test = report.test_summary
    lines.extend(
        [
            "",
            "## 5. 测试摘要",
            "",
            f"- 执行状态：`{test.execution_status}`",
            f"- 通过：{_number(test.passed)}",
            f"- 失败：{_number(test.failed)}",
            f"- 跳过：{_number(test.skipped)}",
            f"- 覆盖率：{_percent(test.coverage)}",
            f"- 数据来源：{test.source or '无'}",
        ]
    )
    if test.reason:
        lines.append(f"- 说明：{test.reason}")

    execution = report.execution_summary
    lines.extend(
        [
            "",
            "## 6. 执行统计",
            "",
            f"- 总任务数：{execution.total_tasks}",
            f"- 完成：{execution.completed_tasks}",
            f"- 部分完成：{execution.partial_tasks}",
            f"- 失败：{execution.failed_tasks}",
            f"- 取消：{execution.cancelled_tasks}",
            f"- 执行耗时：{execution.duration_seconds:.2f} 秒",
        ]
    )

    cost = report.cost_summary
    lines.extend(
        [
            "",
            "## 7. 成本",
            "",
            f"- 输入 Token：{cost.total_input_tokens}",
            f"- 输出 Token：{cost.total_output_tokens}",
            f"- 估算成本：{cost.estimated_cost:.2f} {cost.currency}",
        ]
    )

    lines.extend(["", "## 8. 警告与说明", ""])
    if metadata.warnings:
        lines.extend(f"- {warning}" for warning in metadata.warnings)
    else:
        lines.append("无。")

    lines.append("")
    return "\n".join(lines)


def _render_finding(index: int, finding: Finding) -> list[str]:
    lines = [
        f"### {index}. [{finding.severity}] {_one_line(finding.title)}",
        "",
        f"- Agent：{finding.agent_name}",
        f"- 类别：{finding.category}",
        f"- 位置：{_location(finding)}",
        f"- 验证状态：`{finding.verification_status}`",
        f"- 置信度：{finding.confidence:.2f}",
        "",
        f"{finding.description}",
        "",
        f"- 证据：{finding.evidence}",
        f"- 建议：{finding.recommendation}",
    ]
    if finding.tool_evidence:
        refs = "、".join(
            f"`{evidence.raw_output_ref}`"
            for evidence in finding.tool_evidence
        )
        lines.append(f"- 工具证据：{refs}")
    if finding.merged_from:
        lines.append(
            "- 合并自：" + "、".join(f"`{item}`" for item in finding.merged_from)
        )
    lines.append("")
    return lines


def _location(finding: Finding) -> str:
    if finding.file_path is None:
        return "项目级（无文件位置）"
    if finding.start_line is None:
        return f"`{finding.file_path}`"
    if finding.end_line is None or finding.end_line == finding.start_line:
        return f"`{finding.file_path}:{finding.start_line}`"
    return (
        f"`{finding.file_path}:{finding.start_line}-{finding.end_line}`"
    )


def _format_score(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.1f}"


def _percent(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.1f}%"


def _number(value: int | None) -> str:
    return "N/A" if value is None else str(value)


def _cell(value: str | None) -> str:
    if value is None:
        return ""
    return _one_line(value).replace("|", "\\|")


def _one_line(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ").strip()
