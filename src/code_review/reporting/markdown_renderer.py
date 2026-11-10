"""阶段 1 Markdown 报告渲染。

``render_markdown`` 只接收已通过 Pydantic 校验的三份产物模型，不读取工具
运行时对象。因此 ``report.md`` 中出现的所有审查结果都能在
``metadata.json``、``static_analysis.json`` 或 ``test_report.json`` 中找到。
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from code_review.reporting.artifact_models import (
    Finding,
    MetadataArtifact,
    StaticAnalysisArtifact,
    TestReportArtifact,
    ToolRunArtifact,
)

_SEVERITY_RANK = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
    "info": 0,
}
_SECURITY_CATEGORIES = frozenset(
    {
        "sql_injection",
        "command_injection",
        "hardcoded_secret",
        "hardcoded_password",
        "insecure_deserialization",
        "path_traversal",
        "weak_crypto",
        "security_issue",
    }
)
_COMPLEXITY_CATEGORIES = frozenset({"high_complexity", "low_maintainability"})
_TESTING_CATEGORIES = frozenset({"test_failure", "testing_gap"})
_QUALITY_TOOL_NAMES = frozenset({"ruff"})
_COMPLEXITY_TOOL_NAMES = frozenset({"radon"})


def render_markdown(
    metadata: MetadataArtifact,
    static: StaticAnalysisArtifact,
    tests: TestReportArtifact,
) -> str:
    """由三份结构化产物生成可读的 Markdown 报告。"""

    findings = list(static.findings)
    lines: list[str] = [
        "# 代码审查基础报告",
        "",
        (
            "> 本报告由 `metadata.json`、`static_analysis.json` 与 "
            "`test_report.json` 渲染生成。阶段 1 只提供基础分析产物，"
            "不包含四维评分或最终审查裁定；所有 Finding 均为 "
            "`unverified`，需要人工复核。"
        ),
        "",
        f"- review_id：{_code(metadata.review_id)}",
        f"- 产物 schema 版本：{_code(metadata.schema_version)}",
        f"- 审查状态：{_code(metadata.review_status)}",
        "",
        "## 1. 审查基本信息",
        "",
        "| 项目 | 值 |",
        "| --- | --- |",
        f"| review_id | {_code(metadata.review_id)} |",
        f"| 审查状态 | {_code(metadata.review_status)} |",
        f"| 数据源类型 | {_code(metadata.source_type)} |",
        f"| 审查开始时间（UTC） | {_code(_format_dt(metadata.reviewed_at))} |",
        f"| 审查耗时 | {metadata.review_duration_seconds:.2f} 秒 |",
        f"| 项目语言 | {_code(metadata.project_language)} |",
        f"| 扫描文件数 | {metadata.discovered_file_count} |",
        f"| 分析 Python 文件数 | {metadata.analyzed_file_count} |",
        "",
        "工具版本：",
        "",
        "| 工具 | 版本 |",
        "| --- | --- |",
    ]
    for name, version in metadata.tool_versions.items():
        lines.append(f"| {_escape_cell(name)} | {_escape_cell(version or '未知')} |")
    lines.extend(
        [
            "",
            "执行环境：",
            "",
            "| 项目 | 值 |",
            "| --- | --- |",
            f"| Python | {_code(metadata.execution_environment.python_version)} |",
            (
                "| Python 实现 | "
                f"{_code(metadata.execution_environment.python_implementation)} |"
            ),
            f"| 操作系统 | {_escape_cell(metadata.execution_environment.platform_system)} |",
            f"| OS 版本 | {_escape_cell(metadata.execution_environment.platform_release)} |",
            f"| 架构 | {_escape_cell(metadata.execution_environment.platform_machine)} |",
            "",
            "## 2. 仓库和 Commit 信息",
            "",
            "| 项目 | 值 |",
            "| --- | --- |",
            f"| 数据源类型 | {_code(metadata.source_type)} |",
            f"| 仓库 | {_escape_cell(metadata.repository_name)} |",
            f"| 仓库 URL | {_code(metadata.repository_url)} |",
            f"| 分支 | {_code(metadata.branch)} |",
            (
                "| Commit SHA | "
                f"{_code(metadata.commit_sha) if metadata.commit_sha else '未提供（受控 Fixture，不伪造 Git Commit）'} |"
            ),
        ]
    )
    if metadata.fixture_manifest_sha256:
        lines.append(
            f"| Fixture 清单 SHA-256 | {_code(metadata.fixture_manifest_sha256)} |"
        )
    if metadata.inventory is not None:
        inventory = metadata.inventory
        lines.extend(
            [
                f"| 文件总数 | {inventory.total_files} |",
                f"| Python 源文件 | {inventory.python_source_files} |",
                f"| Python 测试文件 | {inventory.python_test_files} |",
                f"| 被过滤文件 | {inventory.filtered_files} |",
                f"| 扫描字节数 | {inventory.scanned_bytes} |",
                f"| 代码总行数 | {inventory.total_line_count} |",
            ]
        )
        if inventory.is_partial:
            lines.append(
                f"| 扫描完整性 | 部分扫描：{_escape_cell(inventory.partial_reason)} |"
            )
        else:
            lines.append("| 扫描完整性 | 完整 |")
    lines.extend(
        [
            "",
            "## 3. 工具执行概览",
            "",
            "| 工具 | 版本 | 执行状态 | 分析文件 | 耗时(ms) | 原始发现 | 截断 | 错误 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for tool in static.tools.values():
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape_cell(tool.tool_name),
                    _escape_cell(tool.tool_version or "未知"),
                    _code(tool.execution_status),
                    str(tool.analyzed_file_count),
                    str(tool.duration_ms),
                    str(tool.finding_count),
                    _yes_no(_tool_truncated(tool)),
                    _escape_cell(tool.error.message if tool.error else "—"),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "| 组件 | 状态 | 说明 |",
            "| --- | --- | --- |",
            (
                "| Pytest / Coverage | "
                f"{_code(tests.execution_status)} | "
                f"{_escape_cell(tests.reason or tests.data_source)} |"
            ),
            (
                "| LLM 辅助分析 | "
                f"{_code(static.llm_analysis.status)} | "
                f"{_escape_cell(static.llm_analysis.reason or '已完成')} |"
            ),
            "",
        ]
    )
    if static.error_summary:
        lines.extend(
            [
                "### 错误与异常摘要",
                "",
                "| 来源 | 类型 | 可重试 | 信息 |",
                "| --- | --- | --- | --- |",
            ]
        )
        for error in static.error_summary:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _escape_cell(error.source),
                        _code(error.error_type),
                        _yes_no(error.retryable),
                        _escape_cell(error.message),
                    ]
                )
                + " |"
            )
        lines.append("")
    if static.warnings:
        lines.extend(["### 警告", ""])
        lines.extend(f"- {_escape_text(item)}" for item in static.warnings)
        lines.append("")

    _append_analysis_section(
        lines,
        title="## 4. 代码质量分析",
        findings=_quality_findings(findings),
        tools=[static.tools[name] for name in _QUALITY_TOOL_NAMES if name in static.tools],
        empty_message="未发现代码质量类 Finding。",
        failed_message=(
            "代码质量工具未成功执行，不能据此判断不存在代码质量问题。"
        ),
    )
    _append_analysis_section(
        lines,
        title="## 5. 安全分析",
        findings=_security_findings(findings),
        tools=[static.tools[name] for name in ("bandit",) if name in static.tools],
        empty_message="未发现安全类 Finding。",
        failed_message="Bandit 未成功执行，不能据此判断不存在安全问题。",
    )
    _append_analysis_section(
        lines,
        title="## 6. 复杂度分析",
        findings=_complexity_findings(findings),
        tools=[
            static.tools[name]
            for name in _COMPLEXITY_TOOL_NAMES
            if name in static.tools
        ],
        empty_message="未发现复杂度类 Finding。",
        failed_message="Radon 未成功执行，不能据此判断复杂度正常。",
    )

    lines.extend(["## 7. 测试与覆盖率", ""])
    lines.extend(_render_test_section(tests, _testing_findings(findings)))
    lines.extend(["", "## 8. 重要 Finding", ""])
    lines.extend(_render_findings_section(findings))
    lines.extend(["", "## 9. LLM 分析摘要", ""])
    lines.extend(_render_llm_section(static))
    lines.extend(["", "## 10. 风险与限制", ""])
    lines.extend(_render_risks(metadata, static, tests))
    lines.extend(["", "## 11. 未执行任务及原因", ""])
    lines.extend(_render_not_executed(static, tests))
    lines.extend(["", "## 12. 审查结论", ""])
    lines.extend(_render_conclusion(metadata, static, tests))
    lines.append("")
    return "\n".join(lines)


def _append_analysis_section(
    lines: list[str],
    *,
    title: str,
    findings: list[Finding],
    tools: list[ToolRunArtifact],
    empty_message: str,
    failed_message: str,
) -> None:
    lines.extend([title, ""])
    if tools:
        for tool in tools:
            lines.append(
                f"- 工具 {_code(tool.tool_name)}：状态 "
                f"{_code(tool.execution_status)}，原始发现 "
                f"{tool.finding_count} 条，耗时 {tool.duration_ms} ms。"
            )
        lines.append("")
    if findings:
        counts = Counter(finding.severity for finding in findings)
        lines.append(
            "按严重度统计："
            + "，".join(
                f"{severity} {counts.get(severity, 0)}"
                for severity in ("critical", "high", "medium", "low", "info")
            )
            + "。"
        )
        lines.extend(["", "| Finding | 严重度 | 位置 | 标题 |", "| --- | --- | --- | --- |"])
        for finding in findings[:10]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _code(finding.finding_id),
                        _code(finding.severity),
                        _escape_cell(_location(finding)),
                        _escape_cell(finding.title),
                    ]
                )
                + " |"
            )
        if len(findings) > 10:
            lines.append(
                f"\n仅展示前 10 条；该分类共有 {len(findings)} 条 Finding，"
                "完整列表见 `static_analysis.json`。"
            )
    elif any(
        tool.execution_status
        not in {"success", "findings", "partial"}
        for tool in tools
    ):
        lines.append(failed_message)
    else:
        lines.append(empty_message)
    lines.append("")


def _render_test_section(
    tests: TestReportArtifact,
    test_findings: list[Finding],
) -> list[str]:
    lines = [
        "| 项目 | 值 |",
        "| --- | --- |",
        f"| 执行状态 | {_code(tests.execution_status)} |",
        f"| 数据来源 | {_code(tests.data_source)} |",
        f"| 是否可信 Fixture | {_yes_no(tests.trusted_fixture)} |",
        f"| 执行耗时(ms) | {tests.duration_ms} |",
    ]
    if tests.fixture is not None:
        lines.extend(
            [
                f"| Fixture 名称 | {_escape_cell(tests.fixture.name)} |",
                f"| Fixture 版本 | {_escape_cell(tests.fixture.version or '未知')} |",
                (
                    "| Fixture 清单 SHA-256 | "
                    f"{_code(tests.fixture.manifest_sha256 or '未知')} |"
                ),
            ]
        )
    lines.extend(
        [
            f"| Pytest 版本 | {_escape_cell(tests.tool_versions.get('pytest') or '未知')} |",
            (
                "| Coverage 版本 | "
                f"{_escape_cell(tests.tool_versions.get('coverage') or '未知')} |"
            ),
            f"| 只读校验 | {_read_only_value(tests.read_only_verified)} |",
        ]
    )
    if tests.reason:
        lines.append(f"| 原因 | {_escape_cell(tests.reason)} |")
    lines.append("")

    if tests.execution_status == "not_executed":
        lines.extend(
            [
                (
                    "本次未执行 Pytest / Coverage，因此没有测试数量或"
                    "覆盖率数据；这**不代表测试通过**。原因见上表。"
                ),
                "",
            ]
        )
        lines.extend(_render_test_findings(test_findings))
        return lines

    counts = tests.counts
    lines.extend(
        [
            "| 测试计数 | 值 |",
            "| --- | --- |",
            f"| 收集 | {_fmt_int(counts.collected)} |",
            f"| 通过 | {_fmt_int(counts.passed)} |",
            f"| 失败（包含 error） | {_fmt_int(counts.failed)} |",
            f"| 跳过 | {_fmt_int(counts.skipped)} |",
            f"| error | {_fmt_int(counts.errors)}{_errors_note(counts.errors_complete)} |",
            "",
            f"- 总体覆盖率：{_fmt_percent(tests.coverage.percent_covered)}",
            f"- 测试耗时：{_fmt_seconds(tests.test_duration_seconds)}",
            f"- Pytest 退出码：{_fmt_int(tests.exit_code)}",
            f"- Coverage 退出码：{_fmt_int(tests.coverage_exit_code)}",
            "",
        ]
    )
    if tests.modified_paths:
        lines.append(
            "只读校验发现工作区被修改："
            + "，".join(_code(item) for item in tests.modified_paths)
        )
        lines.append("")
    if tests.coverage.files:
        files = sorted(
            tests.coverage.files, key=lambda item: item.percent_covered
        )
        lines.extend(
            [
                "| 文件 | 覆盖率 | 语句数 | 未覆盖行数 |",
                "| --- | --- | --- | --- |",
            ]
        )
        for item in files[:50]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _code(item.file_path),
                        f"{item.percent_covered:.1f}%",
                        str(item.num_statements),
                        str(len(item.missing_lines)),
                    ]
                )
                + " |"
            )
        if len(files) > 50 or tests.coverage.files_truncated:
            lines.append(
                "\n文件覆盖率列表已截断；完整数据以 "
                "`test_report.json` 为准。"
            )
        lines.append("")
    if tests.records:
        lines.extend(
            [
                "| 测试 | 结果 | 文件 | 耗时(s) |",
                "| --- | --- | --- | --- |",
            ]
        )
        for record in tests.records[:50]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _escape_cell(record.name),
                        _code(record.outcome),
                        _escape_cell(record.file_path or "—"),
                        _fmt_seconds(record.duration_seconds),
                    ]
                )
                + " |"
            )
        if len(tests.records) > 50 or tests.records_truncated:
            lines.append(
                "\n测试记录列表已截断；完整数据以 `test_report.json` 为准。"
            )
        lines.append("")
    if tests.error is not None:
        lines.append(
            f"测试执行错误：{_code(tests.error.error_type)} — "
            f"{_escape_cell(tests.error.message)}"
        )
        lines.append("")
    lines.extend(_render_test_findings(test_findings))
    return lines


def _render_test_findings(test_findings: list[Finding]) -> list[str]:
    if not test_findings:
        return []
    lines = [
        "| Finding | 严重度 | 位置 | 标题 |",
        "| --- | --- | --- | --- |",
    ]
    for finding in test_findings[:20]:
        lines.append(
            "| "
            + " | ".join(
                [
                    _code(finding.finding_id),
                    _code(finding.severity),
                    _escape_cell(_location(finding)),
                    _escape_cell(finding.title),
                ]
            )
            + " |"
        )
    if len(test_findings) > 20:
        lines.append(
            f"\n仅展示前 20 条；共有 {len(test_findings)} 条测试相关 Finding，"
            "完整列表见 `static_analysis.json`。"
        )
    lines.append("")
    return lines


def _render_findings_section(findings: list[Finding]) -> list[str]:
    if not findings:
        return ["本次审查未产生 Finding。"]
    ordered = sorted(findings, key=_finding_sort_key)
    important = [
        finding
        for finding in ordered
        if finding.severity in {"critical", "high", "medium"}
    ]
    remainder = [
        finding
        for finding in ordered
        if finding.severity not in {"critical", "high", "medium"}
    ]
    shown = important + remainder[:10]
    lines = [
        (
            f"本次共产生 {len(findings)} 条 Finding。以下展示全部 "
            "critical / high / medium Finding，以及按严重度排序的前 10 条 "
            "low / info Finding；完整列表见 `static_analysis.json`。"
        ),
        "",
    ]
    for finding in shown:
        lines.extend(
            [
                f"### {finding.severity.upper()} · {_code(finding.finding_id)}",
                "",
                f"- 标题：{_escape_text(finding.title)}",
                f"- 类别：{_code(finding.category)}",
                f"- 位置：{_escape_cell(_location(finding))}",
                f"- 置信度：{finding.confidence:.2f}",
                f"- 验证状态：{_code(finding.verification_status)}",
                f"- 建议：{_escape_text(finding.recommendation)}",
            ]
        )
        if finding.tool_evidence:
            lines.append("- 工具证据：")
            for evidence in finding.tool_evidence:
                rule = evidence.rule_id or "无规则 ID"
                lines.append(
                    "  - "
                    f"{_code(evidence.tool_name)} {_code(rule)} → "
                    f"{_code(evidence.raw_output_ref)}"
                )
        else:
            lines.append("- 工具证据：无（由代码位置与逐字证据支撑）")
        lines.extend(["", "证据：", ""])
        for evidence_line in finding.evidence.splitlines() or [""]:
            lines.append(f"> {evidence_line}" if evidence_line else ">")
        lines.append("")
    return lines


def _render_llm_section(static: StaticAnalysisArtifact) -> list[str]:
    llm = static.llm_analysis
    lines = [
        "| 项目 | 值 |",
        "| --- | --- |",
        f"| 状态 | {_code(llm.status)} |",
        f"| 模型 | {_escape_cell(llm.model or '未配置')} |",
        f"| 调用次数 | {llm.call_count} |",
        f"| 耗时(ms) | {llm.duration_ms} |",
        f"| 输入字符数 | {llm.input_chars} |",
        f"| Finding 上下文条数 | {llm.context_finding_count} |",
        f"| 代码片段条数 | {llm.context_snippet_count} |",
        f"| 提案数 | {llm.proposal_count} |",
        f"| 已接受提案 | {len(llm.accepted)} |",
        f"| 已拒绝提案 | {len(llm.rejected)} |",
        f"| 丢弃提案 | {llm.dropped_proposal_count} |",
        f"| 输入截断 | {_yes_no(llm.input_truncated)} |",
        f"| 输出截断 | {_yes_no(llm.output_truncated)} |",
    ]
    if llm.reason:
        lines.append(f"| 原因 | {_escape_cell(llm.reason)} |")
    lines.append("")
    if llm.usage:
        lines.extend(
            [
                "Token 用量：",
                "",
                "| 项目 | 数量 |",
                "| --- | --- |",
            ]
        )
        for key in sorted(llm.usage):
            lines.append(f"| {_escape_cell(key)} | {llm.usage[key]} |")
        lines.append("")
    if llm.status != "completed":
        lines.extend(
            [
                (
                    "LLM 分析未成功完成。确定性工具结果与 Finding 仍然保留，"
                    "报告中未混入模型结论。"
                ),
                "",
            ]
        )
    if llm.accepted:
        lines.extend(
            [
                "已接受提案：",
                "",
                "| Finding | 提案序号 | 来源 | 关联 Finding | 已合并 |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for item in llm.accepted:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _code(item.finding_id),
                        str(item.proposal_index),
                        _code(item.source),
                        _code(item.related_finding_id or "—"),
                        _yes_no(item.merged),
                    ]
                )
                + " |"
            )
        lines.append("")
    if llm.rejected:
        lines.extend(
            [
                (
                    "已拒绝提案（仅记录在 `llm_analysis.rejected[]`，"
                    "不作为正式 Finding）："
                ),
                "",
                "| 提案序号 | 类型 | 类别 | 标题 | 原因 |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for item in llm.rejected:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(item.proposal_index),
                        _escape_cell(item.kind or "—"),
                        _escape_cell(item.category or "—"),
                        _escape_cell(item.title or "—"),
                        _escape_cell(item.reason),
                    ]
                )
                + " |"
            )
        lines.append("")
    if llm.explanations:
        lines.extend(
            [
                f"模型解释共 {len(llm.explanations)} 条；以下展示前 10 条：",
                "",
            ]
        )
        for item in llm.explanations[:10]:
            lines.append(
                f"- {_code(item.related_finding_id)}："
                f"{_escape_text(item.description)}"
            )
        lines.append("")
    return lines


def _render_risks(
    metadata: MetadataArtifact,
    static: StaticAnalysisArtifact,
    tests: TestReportArtifact,
) -> list[str]:
    risks: list[str] = [
        (
            "阶段 1 不计算 Security / Quality / Performance / Testing "
            "四维评分，也不生成 `ReviewReport` 或 `APPROVE` / `COMMENT` / "
            "`REQUEST_CHANGES` 最终裁定。"
        ),
        (
            "所有 Finding 的 `verification_status` 均为 `unverified`，"
            "结论需要人工复核。"
        ),
    ]
    for tool in static.tools.values():
        if tool.execution_status not in {"success", "findings"}:
            risks.append(
                f"工具 {tool.tool_name} 的执行状态为 {tool.execution_status}，"
                "相关分析可能不完整。"
            )
        if _tool_truncated(tool):
            risks.append(
                f"工具 {tool.tool_name} 的输出或 Finding 被截断，"
                "报告只反映已保存的数据。"
            )
    if metadata.inventory is not None and metadata.inventory.is_partial:
        risks.append(
            "仓库扫描未完成："
            f"{metadata.inventory.partial_reason or '达到扫描上限'}"
        )
    if tests.execution_status == "not_executed":
        risks.append(
            "本次未执行测试，不能根据本报告判断测试是否通过。"
        )
    elif tests.execution_status in {"failed", "timeout"}:
        risks.append(
            f"测试执行状态为 {tests.execution_status}，测试结果不完整。"
        )
    if tests.read_only_verified is False:
        risks.append("测试执行后的只读校验失败，工作区可能已被修改。")
    if tests.records_truncated:
        risks.append("测试记录列表被截断，error 计数可能不完整。")
    if tests.coverage.files_truncated:
        risks.append("文件级覆盖率列表被截断。")
    if static.llm_analysis.status == "not_configured":
        risks.append("LLM 未配置，报告中没有任何模型语义分析结果。")
    elif static.llm_analysis.status in {"timeout", "failed"}:
        risks.append(
            f"LLM 分析状态为 {static.llm_analysis.status}，"
            "报告中只保留确定性工具结果。"
        )
    if static.llm_analysis.input_truncated:
        risks.append("LLM 输入被截断，模型只看到部分上下文。")
    if static.llm_analysis.output_truncated:
        risks.append("LLM 输出被截断，模型结论可能不完整。")
    if metadata.review_status == "partial":
        risks.append("本次审查状态为 partial，存在未完成或失败的组件。")
    if metadata.source_type == "trusted_fixture":
        risks.append(
            "本次审查对象为项目自维护可信 Fixture；Pytest / Coverage 仅在"
            "该 Fixture 上执行，不代表对外部仓库执行了测试。"
        )
    if len(risks) == 2:
        risks.append("未发现额外风险；阶段 1 的固有限制仍然适用。")
    return [f"- {item}" for item in risks]


def _render_not_executed(
    static: StaticAnalysisArtifact,
    tests: TestReportArtifact,
) -> list[str]:
    rows: list[tuple[str, str, str]] = []
    for tool in static.tools.values():
        if tool.execution_status not in {"success", "findings"}:
            rows.append(
                (
                    f"静态分析：{tool.tool_name}",
                    tool.execution_status,
                    tool.error.message if tool.error else "工具未成功完成",
                )
            )
    if tests.execution_status != "executed":
        rows.append(
            (
                "Pytest / Coverage",
                tests.execution_status,
                tests.reason or (tests.error.message if tests.error else "未执行"),
            )
        )
    if static.llm_analysis.status != "completed":
        rows.append(
            (
                "LLM 辅助分析",
                static.llm_analysis.status,
                static.llm_analysis.reason or "未完成",
            )
        )
    rows.extend(
        [
            (
                "四维评分与最终裁定",
                "阶段 1 范围外",
                "阶段 1 不实现专业 Agent、Final Reviewer 与 ReviewReport。",
            ),
            (
                "report.json / ReviewReport",
                "阶段 1 不生成",
                "按验收口径自阶段 2 起生成。",
            ),
            (
                "多 Agent 工作流",
                "阶段 1 范围外",
                "阶段 1 为单进程、非 Agent 的确定性分析流水线。",
            ),
        ]
    )
    lines = [
        "| 任务 | 状态 | 原因 |",
        "| --- | --- | --- |",
    ]
    for task, status, reason in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape_cell(task),
                    _code(status),
                    _escape_cell(reason),
                ]
            )
            + " |"
        )
    return lines


def _render_conclusion(
    metadata: MetadataArtifact,
    static: StaticAnalysisArtifact,
    tests: TestReportArtifact,
) -> list[str]:
    counts = Counter(finding.severity for finding in static.findings)
    failed_tools = [
        tool.tool_name
        for tool in static.tools.values()
        if tool.execution_status not in {"success", "findings"}
    ]
    lines = [
        (
            "阶段 1 不输出最终审查裁定。以下仅为基于真实工具结果与已校验 "
            "Finding 的事实摘要："
        ),
        "",
        f"- 审查状态：{_code(metadata.review_status)}",
        f"- Finding 总数：{len(static.findings)}",
        (
            "- 严重度分布："
            + "，".join(
                f"{severity} {counts.get(severity, 0)}"
                for severity in ("critical", "high", "medium", "low", "info")
            )
        ),
        (
            "- 静态分析工具失败："
            + ("无" if not failed_tools else "，".join(_code(item) for item in failed_tools))
        ),
        f"- 测试执行状态：{_code(tests.execution_status)}",
        f"- LLM 分析状态：{_code(static.llm_analysis.status)}",
        "",
    ]
    if counts.get("critical", 0) or counts.get("high", 0):
        lines.append(
            "存在 critical / high Finding，建议优先人工核验。按照阶段 2 "
            "的合同，已核验的 critical Finding 将直接影响最终裁定；"
            "阶段 1 不作此裁定。"
        )
    else:
        lines.append(
            "未产生 critical / high Finding；这不等于审查通过，"
            "仍需结合未执行项与人工复核判断。"
        )
    lines.extend(
        [
            "",
            (
                "阶段 1 不输出 `APPROVE`、`COMMENT` 或 "
                "`REQUEST_CHANGES`。最终结论必须由阶段 2 的 Final Reviewer "
                "在核验 Finding、计算四维评分后生成。"
            ),
        ]
    )
    return lines


def _quality_findings(findings: list[Finding]) -> list[Finding]:
    return [
        finding
        for finding in findings
        if finding.category not in _SECURITY_CATEGORIES
        and finding.category not in _COMPLEXITY_CATEGORIES
        and finding.category not in _TESTING_CATEGORIES
    ]


def _security_findings(findings: list[Finding]) -> list[Finding]:
    return [
        finding
        for finding in findings
        if finding.category in _SECURITY_CATEGORIES
    ]


def _complexity_findings(findings: list[Finding]) -> list[Finding]:
    return [
        finding
        for finding in findings
        if finding.category in _COMPLEXITY_CATEGORIES
    ]


def _testing_findings(findings: list[Finding]) -> list[Finding]:
    return [
        finding
        for finding in findings
        if finding.category in _TESTING_CATEGORIES
    ]


def _finding_sort_key(finding: Finding) -> tuple[object, ...]:
    return (
        -_SEVERITY_RANK.get(finding.severity, 0),
        -finding.confidence,
        finding.file_path or "",
        finding.start_line or 0,
        finding.finding_id,
    )


def _tool_truncated(tool: ToolRunArtifact) -> bool:
    return (
        tool.stdout_truncated
        or tool.stderr_truncated
        or tool.findings_truncated
    )


def _location(finding: Finding) -> str:
    if finding.file_path is None:
        return "未定位（由工具证据支撑）"
    if finding.start_line is None:
        return finding.file_path
    if finding.end_line is not None and finding.end_line != finding.start_line:
        return f"{finding.file_path}:{finding.start_line}-{finding.end_line}"
    return f"{finding.file_path}:{finding.start_line}"


def _format_dt(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _fmt_int(value: int | None) -> str:
    return "null" if value is None else str(value)


def _fmt_seconds(value: float | None) -> str:
    return "null" if value is None else f"{value:.3f}"


def _fmt_percent(value: float | None) -> str:
    return "null" if value is None else f"{value:.1f}%"


def _errors_note(complete: bool) -> str:
    return "" if complete else "（记录被截断，可能不完整）"


def _read_only_value(value: bool | None) -> str:
    if value is None:
        return _code("null")
    return _yes_no(value)


def _yes_no(value: bool) -> str:
    return "是" if value else "否"


def _code(value: object) -> str:
    text = str(value).replace("\n", " ")
    if "`" in text:
        return f"``{text}``"
    return f"`{text}`"


def _escape_cell(value: object) -> str:
    text = str(value).replace("\r\n", "\n").replace("\n", "<br>")
    return text.replace("|", "\\|")


def _escape_text(value: object) -> str:
    return str(value).replace("\r\n", "\n").replace("\n", " ")
