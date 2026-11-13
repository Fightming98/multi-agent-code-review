# Stage 2.5 验收报告：ReviewService 集成、五件报告产物与 CLI/API

- 阶段：Stage 2.5（ReviewService 集成、五件报告产物、CLI/API 响应）
- 日期：2026-11-13
- 基线 HEAD：`ec0afe2`（Stage 2.4 已提交）
- 工作区状态：Stage 2.5 改动未提交，等待负责人验收
- 结论：**PASS WITH CONDITIONS**

本阶段严格按 `Stage2.1-2.6分阶段实施Promp.md` 的 Stage 2.5 边界执行：

- 只修改或新增允许清单内的文件；
- 未修改三个冻结 Schema、五份核心文档、Stage 1 报告模块
  （`report_generator.py`、`artifact_models.py`、`markdown_renderer.py`、
  `finding_aggregator.py`）、`tests/fixtures/trusted_repo/`、
  `environment.lock.yml`；
- 未调用真实 LLM、未联网、未新增依赖、未启用 tracing；
- 未引入 Redis、ARQ、PostgreSQL、Checkpointer、MCP、A2A；
- 未实现 Stage 3 SubAgents；
- 完成后未进入 Stage 2.6，未执行任何 Git 提交。

---

## 1. 结论摘要

| 项目 | 结果 |
|---|---|
| `ReviewService` 集成 LangGraph 工作流 | PASS |
| 生产默认 Stage 2（D-4） | PASS |
| Stage 1 legacy 路径保留且四件产物不回归 | PASS |
| 五件产物完整生成 | PASS |
| `report.json` 通过冻结 `ReviewReport` Schema | PASS |
| `ArtifactData` 内存与落盘 Pointer 一致 | PASS |
| CLI/API 新字段与一位小数展示 | PASS |
| O-1 成本守卫（不伪造零成本） | PASS（默认无 LLM 路径）；真实 LLM 成本口径仍开放 |
| 全量测试与 Ruff | PASS |

结论为 **PASS WITH CONDITIONS**，条件见 §13：

1. O-1（`CostSummary` 无法表达未知成本）在审计计划 §12.5 中仍标记为开放；
   本阶段默认 Fake/无 LLM 路径的零成本是真实值，但不得据此声称“真实 LLM
   成本已准确统计”。
2. Prompt §四.3 要求 Factory 注入 Validator；实际 `graph/nodes.py:437`
   直接构造 `FinalReviewer()`（含默认 `Stage2EvidenceValidator`），
   `graph/nodes.py` 不在本阶段允许修改的文件清单内，因此未做注入改造，
   已在此如实记录并等待裁定。
3. 审计计划 §9.5 与 §1.3/§2.5/§12.5 对 D-4 的表述存在内部差异（见 §4.4）。

---

## 2. 执行前检查

| 检查项 | 结果 |
|---|---|
| 阅读 Stage 2 审计计划与 Stage 2.1～2.4 验收报告 | 已完成 |
| Git 状态与 HEAD | `ec0afe2`；工作区仅包含允许清单内的 Stage 2.5 改动 |
| Stage 2.4 已验收 | 是（`reports/stage2_4_acceptance_report.md`） |
| 全仓 `ReviewService` / `.review()` / `.review_trusted_fixture()` 调用方重扫 | 已执行，见 §4 |
| CLI/API 入口与响应模型（`extra="forbid"`） | 已核对，见 §8 |
| Stage 1 报告生成器与四件产物现有行为 | 已核对，未修改 |

---

## 3. ReviewService 调用链

### 3.1 构造与入口

`ReviewService.__init__`（`src/code_review/services/review_service.py:207`）：

```python
def __init__(
    self,
    settings,
    *,
    ...
    multi_agent: bool = True,                              # :220
    stage2_factory=None,                                   # 默认 build_stage2_dependencies
    stage2_report_generator=None,                          # 默认 Stage2ReportGenerator()
    git_client=None,
) -> None:
```

三个公共入口：

| 入口 | 行为 |
|---|---|
| `review(request)` | 外部 GitHub 仓库；`multi_agent=True`（默认）走 Stage 2，`False` 走 Stage 1 |
| `review_trusted_fixture()` | **始终**走 Stage 1 `_run_review`，四件产物，`commit_sha=None` |
| `review_stage2_fixture(...)` | Stage 2 Fixture 入口，要求 `multi_agent=True`；不通过 CLI/API 暴露 |

### 3.2 `review()` 主链

```text
CLI / API / 测试
→ ReviewService.review(ReviewRequest)                       # review_service.py:262
→ _validate_request()                                       # URL / branch / SHA 校验
→ _new_review_id(started_at, stage2=self._multi_agent)
→ _resolve_output_root()
→ _acquire_repository()                                     # clone + 固定 40 位 commit SHA
→ _ensure_output_outside_workspace()
→ 分支：
   multi_agent=True  → _run_stage2_review()                 # :294
   multi_agent=False → _run_review()                        # :301（Stage 1 legacy）
→ finally: _cleanup_snapshot(snapshot)                      # :341-343
```

### 3.3 `_run_stage2_review()` 内部链

`src/code_review/services/review_service.py:905`：

```text
校验 workspace.commit_sha 为 40 位十六进制                     # :917-925
→ _inspect() 扫描仓库并收集允许文件                            # :928
→ Stage2FactoryContext(settings, tools, test_runner,          # :938-944
                       trusted_fixture, clock)
→ self._stage2_factory(context)                                # :946，默认 build_stage2_dependencies
→ build_initial_state(..., rules=dependencies.rules)          # :963-977
→ run_review_graph(dependencies.graph, initial_state)         # :987，同步包装、进程内执行
→ 校验 state 中的 ReviewReport / ArtifactData / UsageSummary   # :1001-1014
→ Stage2ArtifactInput(report, artifact_data, usage_summary, …) # :1022-1037
→ Stage2ReportGenerator.generate(source, output_root)          # :1039，写五件产物
→ _stage2_outcome(...)                                         # :1059
```

关键约束：

- `run_review_graph()` 为同步包装，拒绝在已运行事件循环中嵌套调用；
  CLI/API 均为同步调用环境。
- 图执行失败、状态不完整、报告生成失败都会抛出显式
  `ReviewServiceError`，不会伪造 partial 报告。
- 工作区清理发生在 `review()` 的 `finally`，即报告生成与数据读取完成之后。

### 3.4 `review_stage2_fixture()` 校验链

`src/code_review/services/review_service.py:462`：

```text
allow_trusted_fixture_review == True                           # :487 → trusted_fixture_disabled
multi_agent == True                                            # :493 → stage2_review_disabled
workspace_path 解析且存在为目录                                # :504-519 → invalid_fixture_workspace
normalize_commit_sha(commit_sha)                               # :521 → invalid_revision
trusted_fixture 在批准名单                                     # :532 → fixture_not_approved
trusted_fixture == settings.trusted_fixture_name               # :539 → fixture_name_mismatch
repository_name 安全命名                                        # :551 → invalid_fixture_name
branch 非空且 ≤255                                             # :562 → invalid_revision
fixture_manifest_sha256 为 64 位十六进制（可选）                # :569 → invalid_fixture_manifest
_verify_fixture_commit(HEAD == commit_sha)                     # :579 → fixture_commit_mismatch 等
_ensure_output_outside_workspace()                             # :584
→ _run_stage2_review(..., trusted_fixture, manifest)           # :607
```

该入口**不清理**调用方提供的工作区，也不通过 CLI/API 暴露。

### 3.5 错误阶段映射

| 场景 | stage | error_type |
|---|---|---|
| Stage 2 缺少固定 SHA | `validation` | `missing_commit_sha` |
| Factory 构建失败或返回类型错误 | `graph` | `graph_setup_failed` |
| 初始状态非法 | `graph` | `graph_setup_failed` |
| LangGraph 执行异常 / 状态不完整 | `graph` | `graph_execution_failed` |
| 报告生成失败 | `reporting` | `report_generation_failed` |
| Fixture 校验失败 | `validation` / `fixture` | 见 §3.4 |
| 未预期异常 | `internal` | 异常类名（不泄露消息） |

Stage 1 legacy 路径（`_run_review`）的错误映射保持原样。

---

## 4. D-4 全调用方迁移清单

### 4.1 生产入口

| 位置 | 调用 | 迁移结果 |
|---|---|---|
| `src/code_review/cli.py:72` | `ReviewService(settings)` | 未传 `multi_agent`，默认 `True` → Stage 2 |
| `src/code_review/cli.py:74` | `service.review(...)` | 生产默认 Stage 2 |
| `src/code_review/api/app.py:69` | `ReviewService(resolved_settings)` | 默认 `True` → Stage 2 |
| `src/code_review/api/app.py:113` | `review_service.review(...)` | 生产默认 Stage 2 |

CLI/API 均未复制评审逻辑，仍只调用同一个 `ReviewService`。

### 4.2 Stage 1 单元测试 harness

`tests/unit/test_review_service.py:137`：

```python
def make_harness(..., multi_agent: bool = False) -> ServiceHarness:
```

`:185-197` 把 `multi_agent` 显式传入 `ReviewService(...)`。该 harness 上的
17 个 `.review()` 调用点全部保持 Stage 1：

| 行号 | 行号 | 行号 | 行号 |
|---:|---:|---:|---:|
| 216 | 270 | 281 | 293 |
| 297 | 311 | 321 | 331 |
| 344 | 359 | 377 | 394 |
| 416 | 438 | 444 | 455 |
| 561 | | | |

`review_trusted_fixture()` 调用 2 处（`:496`、`:522`），同样经由
`make_harness(multi_agent=False)`，保持 Stage 1。

`test_constructor_requires_unique_non_empty_tools`（`:529`、`:541`）在构造
阶段即断言 `ValueError`，不触发任何审查，与 `multi_agent` 取值无关。

### 4.3 集成测试

`tests/integration/test_stage1_6_review.py`：

| 位置 | 调用 | 迁移结果 |
|---|---|---|
| `:111-120` | `build_external_service()` → `ReviewService(..., multi_agent=False)` | 显式 Stage 1 |
| `:130` | `service.review(ReviewRequest(...))` | Stage 1 |
| `:201-210` | `ReviewService(..., multi_agent=False)` | 显式 Stage 1 |
| `:212` | `service.review_trusted_fixture()` | Stage 1 |

### 4.4 审计计划 D-4 表述差异

- 审计计划 §1.3（第 52 行）与 §12.5 D-4 行记载 D-4 **已采纳**；
- 审计计划 §9.5（第 712～719 行）仍把 `multi_agent=True` 默认、
  Stage 1 harness `multi_agent=False`、`review_stage2_fixture()` 命名列为
  “需要负责人确认”；
- Stage 2.5 提示词 §二明确以“已采纳的 D-4”为实施依据。

本阶段按已采纳方案实施，生产默认 Stage 2，未恢复 Stage 1 生产默认行为。

### 4.5 新增 Stage 2 测试调用方

`tests/unit/test_review_service.py` 新增 `make_stage2_harness(...)`
（`:639`，默认 `multi_agent: bool = True`）：

- Stage 2 `.review()` 调用点：`:717`、`:790`、`:812`、`:829`、`:861`；
- `review_stage2_fixture()` 调用点：`:887`、`:930`、`:947`、`:958`、`:976`。

`tests/unit/test_cli.py`、`tests/unit/test_api.py` 的 Fake service
`.review()` 签名保持兼容，Stage 1 默认返回 `make_outcome()`，Stage 2 通过
注入 `make_stage2_outcome()` 验证新字段。

---

## 5. Stage 1 legacy 兼容证据

### 5.1 四件产物不回归

`tests/unit/test_review_service.py:211`
`test_review_runs_full_pipeline_and_writes_four_artifacts` 断言：

```python
{path.name for path in outcome.artifact_paths} == {
    "metadata.json",
    "static_analysis.json",
    "test_report.json",
    "report.md",
}
```

`tests/integration/test_stage1_6_review.py` 的 3 条测试继续断言四件产物、
`not_executed` 与可信 Fixture 执行行为。

### 5.2 `review_trusted_fixture()` 保持原行为

| 证据 | 结果 |
|---|---|
| `tests/unit/test_review_service.py:496` | 四件产物、`commit_sha is None`、执行 Fixture 测试 |
| `tests/unit/test_review_service.py:522` | 默认禁用时 `trusted_fixture_disabled` |
| `tests/unit/test_review_service.py:1020` | **Stage 2 默认服务**上调用 `review_trusted_fixture()`：`review_stage=="stage_1"`、`report_json_path is None`、恰好四件产物、metadata `stage=="stage_1"`、`commit_sha=None`、不清理工作区 |
| `tests/integration/test_stage1_6_review.py:212` | 四件产物、`commit_sha is None`、`test_status=="executed"` |

即使 `ReviewService` 以默认 `multi_agent=True` 构造，
`review_trusted_fixture()` 仍固定调用 `_run_review`（`:421`），不会意外切换到 Stage 2。

### 5.3 冻结文件未改动

`git diff --stat` 针对以下路径为空：

```text
src/code_review/schemas/
docs/
src/code_review/reporting/report_generator.py
src/code_review/reporting/artifact_models.py
src/code_review/reporting/markdown_renderer.py
src/code_review/services/finding_aggregator.py
tests/fixtures/trusted_repo/
environment.lock.yml
```

---

## 6. 五件产物与 Schema 校验

### 6.1 产物清单

Stage 2 默认审查（`multi_agent=True`）生成：

| 文件 | 来源 | 校验模型 |
|---|---|---|
| `metadata.json` | `Stage2ArtifactInput` + 扫描/工具信息 | `Stage2MetadataArtifact` |
| `static_analysis.json` | Manager Aggregate 的同一份 `ArtifactData` | `Stage2StaticAnalysisArtifact` |
| `test_report.json` | 同一份 `ArtifactData` | `Stage2TestReportArtifact` |
| `report.json` | 同一个 `ReviewReport` 对象 | 冻结 `ReviewReport` |
| `report.md` | 同一个 `ReviewReport` 对象 | 文本断言 |

Stage 1（`review_trusted_fixture()` 与显式 `multi_agent=False`）仍只生成
`metadata.json`、`static_analysis.json`、`test_report.json`、`report.md`。

### 6.2 Schema 校验证据

`tests/unit/test_stage2_report_generator.py:98`
`test_generator_writes_five_consistent_artifacts`：

```python
on_disk = ReviewReport.model_validate_json(report_json_text)
assert on_disk == report
assert on_disk.findings[0].verification_status == "verified"

metadata = Stage2MetadataArtifact.model_validate_json(metadata_text)
static_payload = json.loads(static_text)
Stage2StaticAnalysisArtifact.model_validate(static_payload)
test_payload = json.loads(test_text)
Stage2TestReportArtifact.model_validate(test_payload)
```

`tests/unit/test_review_service.py:731` 亦对服务层写出的 `report.json`
执行 `ReviewReport.model_validate_json`，确认 `report_status=="partial"`、
`overall_verdict=="COMMENT"`、testing 维度 `score is None`。

### 6.3 样例（Fake 工具、无网络、无真实 LLM）

> 说明：以下样例由 Fake 工具与 Fake TestRunner 生成，`tool_versions` 为
> Fake 默认值（全部显示 `1.9.4`），不代表真实工具版本；仅用于证明结构、
> 字段与一致性，不作为真实分析结果。

`metadata.json`（节选）：

```json
{
  "schema_version": "1.0",
  "stage": "stage_2",
  "source_type": "github_repository",
  "review_id": "stage2-test-review",
  "repository_url": "https://github.com/example/project",
  "repository_name": "example/project",
  "branch": "main",
  "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "fixture_manifest_sha256": null,
  "review_status": "partial",
  "reviewed_at": "2026-01-02T03:04:05Z",
  "project_language": "python",
  "discovered_file_count": 1,
  "analyzed_file_count": 1,
  "review_duration_seconds": 0.045,
  "warnings": [
    "llm client not configured; deterministic tool results only",
    "llm client not configured; deterministic tool results only",
    "llm client not configured; deterministic tool results only",
    "tests not executed: external repository tests are not executed"
  ]
}
```

`static_analysis.json`（结构）：

```json
{
  "schema_version": "1.0",
  "agents": {
    "security":    {"agent_name": "SecurityAgent",    "result_status": "completed", "tools": ["bandit"]},
    "quality":     {"agent_name": "QualityAgent",     "result_status": "completed", "tools": ["radon", "ruff"]},
    "performance": {"agent_name": "PerformanceAgent", "result_status": "completed", "tools": ["radon"]},
    "testing":     {"agent_name": "TestingAgent",     "result_status": "completed", "tools": []}
  }
}
```

`test_report.json`（节选，外部仓库）：

```json
{
  "execution_status": "not_executed",
  "reason": "external repository tests are not executed",
  "counts": {"total": null, "passed": null, "failed": null, "skipped": null},
  "coverage": null,
  "agent_name": "TestingAgent",
  "result_status": "completed"
}
```

`report.json`（节选）：

```json
{
  "schema_version": "1.0",
  "review_id": "stage2-test-review",
  "report_status": "partial",
  "overall_verdict": "COMMENT",
  "overall_score": 100.0,
  "dimension_scores": {
    "security":    {"score": 100.0, "weight": 0.35, "finding_count": 0, "status": "completed", "reason": null},
    "quality":     {"score": 100.0, "weight": 0.25, "finding_count": 0, "status": "completed", "reason": null},
    "performance": {"score": 100.0, "weight": 0.20, "finding_count": 0, "status": "completed", "reason": null},
    "testing":     {"score": null,  "weight": 0.20, "finding_count": 0, "status": "completed", "reason": "external repository tests are not executed"}
  },
  "cost_summary": {
    "total_input_tokens": 0,
    "total_output_tokens": 0,
    "estimated_cost": 0.0,
    "currency": "CNY"
  },
  "test_summary": {
    "execution_status": "not_executed",
    "passed": null,
    "failed": null,
    "skipped": null,
    "coverage": null,
    "source": null,
    "reason": "external repository tests are not executed"
  }
}
```

`report.md`（节选）：

```markdown
# Stage 2 代码审查报告

- Review ID：`stage2-test-review`
- Commit SHA：`aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`
- 报告状态：`partial`

## 1. 总体结论

- 结论：**COMMENT**
- 综合分：100.0

## 2. 维度评分

| 维度 | 状态 | 评分 | 权重 | Finding 数 | 说明 |
| --- | --- | --- | --- | --- | --- |
| security | completed | 100.0 | 35% | 0 |  |
| quality | completed | 100.0 | 25% | 0 |  |
| performance | completed | 100.0 | 20% | 0 |  |
| testing | completed | N/A | 20% | 0 | external repository tests are not executed |
```

Stage 2 Fixture 样例（`review_stage2_fixture()`，Fake TestRunner）：

```json
{
  "review_stage": "stage_2",
  "review_status": "completed",
  "overall_verdict": "APPROVE",
  "overall_score": 100.0,
  "dimension_scores": {"security": 100.0, "quality": 100.0, "performance": 100.0, "testing": 100.0},
  "test_status": "executed",
  "metadata": {"stage": "stage_2", "source_type": "trusted_fixture", "repository_url": "fixture://trusted_fixture_v1", "commit_sha": "aaaa…", "fixture_manifest_sha256": "cccc…"},
  "test_report": {"execution_status": "executed", "counts": {"total": 3, "passed": 3, "failed": 0, "skipped": 0}, "coverage": 90.0},
  "workspace_still_exists": true
}
```

Fixture 入口的提交校验调用为：

```json
{"args": ["rev-parse", "--verify", "HEAD^{commit}"], "cwd": "<fixture-workspace>", "timeout": 300}
```

---

## 7. ArtifactData 内存/落盘一致性

`Stage2ReportGenerator.generate()`（`stage2_report_generator.py:114`）：

1. 先拒绝真实 LLM usage（`:122`）；
2. `static_analysis.json` / `test_report.json` 由同一份 `ArtifactData`
   经 `model_dump(mode="json")` 写出（`:140-146`、`:336`、`:349`）；
3. 写出前调用 `_verify_pointer_consistency`（`:484`），逐条解析
   内存 `ArtifactData.resolve(pointer)` 与待落盘 payload 的同一 Pointer；
4. 一致性校验通过后才创建输出目录（`:168`）；
5. 写盘完成后再次 `model_validate_json` 回读（`:567-574`）；
6. 任一步失败 `shutil.rmtree(report_dir, ignore_errors=True)`（`:184`），
   不留下看似成功的残缺目录。

测试证据：

- `tests/unit/test_stage2_report_generator.py:149-156` 遍历
  `report.findings + report.rejected_findings` 的所有 `tool_evidence`，
  断言内存 Pointer 与落盘 Pointer 解析结果相同；
- `test_generator_refuses_pointer_missing_from_artifact_data` 证明
  落盘层会拒绝无法在 `ArtifactData` 中解析的 Pointer；
- `test_generator_refuses_existing_output_directory` 证明不会覆盖已有目录；
- `test_new_report_fields_are_sanitized` 证明工作区绝对路径在 metadata、
  report.json、markdown 中被替换为 `<workspace>`；
- `tests/unit/test_review_service.py:866` 证明 O-1 失败时
  `tmp_path / "reports"` 完全未创建。

---

## 8. CLI/API 响应样例

### 8.1 CLI 人类可读输出

```text
阶段 2 审查完成
review_id      : stage2-test-review
审查状态       : partial
仓库           : example/project
Commit SHA     : aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
审查结论       : COMMENT
综合分         : 100.0
维度评分       : security=100.0, quality=100.0, performance=100.0, testing=N/A
Finding 数量   : 0
测试状态       : not_executed
LLM 分析状态   : not_configured
耗时           : 0.04 秒
报告目录       : <output-root>/stage2-test-review
  - metadata.json
  - static_analysis.json
  - test_report.json
  - report.json
  - report.md
```

- 展示综合分与维度分均使用一位小数（`:136`、`:142`）；
- `testing=None` 显示为 `N/A`；
- 样例输出根 `<output-root>` 为证据采集时的临时目录；生产默认
  `review_output_root="reports"`（相对路径），CLI 与 Stage 1 一样回显配置值。

### 8.2 CLI `--json`

```json
{
  "review_id": "stage2-test-review",
  "review_stage": "stage_2",
  "review_status": "partial",
  "overall_verdict": "COMMENT",
  "overall_score": 100.0,
  "dimension_scores": {
    "security": 100.0,
    "quality": 100.0,
    "performance": 100.0,
    "testing": null
  },
  "repository_name": "example/project",
  "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "report_dir": "<output-root>/stage2-test-review",
  "report_json_path": "<output-root>/stage2-test-review/report.json",
  "artifacts": [
    "<output-root>/stage2-test-review/metadata.json",
    "<output-root>/stage2-test-review/static_analysis.json",
    "<output-root>/stage2-test-review/test_report.json",
    "<output-root>/stage2-test-review/report.json",
    "<output-root>/stage2-test-review/report.md"
  ],
  "finding_count": 0,
  "severity_counts": {},
  "test_status": "not_executed",
  "llm_status": "not_configured",
  "warnings": ["…"],
  "duration_seconds": 0.045
}
```

JSON 保留精确分数（`93.75` 在测试中保持 `93.75`，不取整）；五件产物顺序中
`report.json` 位于 `report.md` 之前。

### 8.3 API 响应（默认相对输出根，取值来自 API 单元测试）

```json
{
  "review_id": "stage2-test-review",
  "review_stage": "stage_2",
  "review_status": "partial",
  "overall_verdict": "COMMENT",
  "overall_score": 93.75,
  "dimension_scores": {"security": 100.0, "quality": 95.0, "performance": 90.0, "testing": null},
  "repository_name": "example/project",
  "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "report_path": "reports/stage2-test-review",
  "report_json_path": "reports/stage2-test-review/report.json",
  "finding_count": 2,
  "severity_counts": {"medium": 2},
  "test_status": "not_executed",
  "llm_status": "not_configured",
  "warnings": ["tests not executed"],
  "duration_seconds": 1.5
}
```

- `ReviewResponseModel` 显式新增 `review_stage`、`overall_verdict`、
  `overall_score`、`dimension_scores`、`report_json_path`；
  `extra="forbid"` 保持不变（`api/app.py:37-57`）；
- `report_path` 由配置的输出根 + `review_id` 生成，`report_json_path`
  在其后追加 `/report.json`；不返回宿主机临时路径；
- API 单元测试断言 `str(tmp_path) not in response.text`，
  且 `report_json_path` 不含反斜杠；
- API 请求仍拒绝 `output_root` 等额外字段（422），`GET /api/reviews` 返回 405；
- 新增 `graph` 阶段映射到 HTTP 500（`api/app.py:176-196`）。

---

## 9. O-1 成本守卫

### 9.1 默认 Fake/无 LLM 路径

`build_stage2_dependencies(..., llm_client=None)`（`stage2_factory.py:119`）
默认不配置 LLM 客户端。四个 Agent 只使用确定性工具结果，
`UsageSummary.llm_calls == 0`，因此：

- `report.json.cost_summary` 为真实全零；
- `ReviewOutcome.llm_status == "not_configured"`；
- 不产生任何“0 token / 0 成本”的伪造，因为确实没有调用。

### 9.2 真实 LLM usage 路径

| 防线 | 行为 |
|---|---|
| Final Reviewer `_build_cost_summary` | `usage_summary.llm_calls > 0` 时抛 `FinalReviewError` |
| `Stage2ReportGenerator.generate`（`:122`） | 生成目录前拒绝非零 `llm_calls` |
| `ReviewService` | 图执行异常映射为 `graph_execution_failed`，不写报告 |

测试证据：

- `tests/unit/test_stage2_report_generator.py:209`
  `test_generator_refuses_real_llm_usage_without_cost_semantics`：
  `llm_calls=1` 抛 `Stage2ReportGenerationError`，输出目录不存在；
- `tests/unit/test_review_service.py:837`
  `test_stage2_real_llm_usage_fails_instead_of_fake_zero_cost`：
  整次审查抛 `ReviewServiceError(stage="graph",
  error_type="graph_execution_failed")`，`reports` 目录不存在，工作区被清理。

### 9.3 O-1 状态

审计计划 §12.5 仍标记 O-1 开放。本阶段未调用真实 LLM，也没有获批的
成本计算口径，因此**不能**得出“真实 LLM 成本已准确统计”的验收结论；
本报告不作此声称。默认验收路径的零成本是真实值。

---

## 10. 错误与失败语义

| 场景 | 本阶段行为 | 测试 |
|---|---|---|
| 图执行失败 | `graph` / `graph_execution_failed`，无报告 | `test_stage2_graph_execution_failure_is_explicit`（`:798`） |
| Factory 构建失败 | `graph` / `graph_setup_failed`，无报告 | `test_stage2_factory_failure_is_reported_as_graph_setup_error`（`:781`） |
| Final Reviewer 失败 | 图中异常上抛，整次审查失败，不生成 partial 报告 | Stage 2.4 既有测试 + `graph_execution_failed` |
| 报告写盘失败 | `reporting` / `report_generation_failed`，清理残缺目录 | `test_stage2_report_generation_failure_is_mapped_to_reporting`（`:820`）、生成器 `rmtree` 测试 |
| 单 Agent 失败 | 按 Stage 2.4 规则保留 failed 结果与其他维度，报告 partial | Stage 2.4 既有测试 |
| Stage 1 legacy | 原错误映射不变 | `test_stage1_6_review.py`、Stage 1 单元测试 |

---

## 11. 测试命令与结果

环境：Conda `multi-agent-review`，`PYTHONUTF8=1`，Windows 11。

| 命令 | 结果 |
|---|---|
| `pytest tests/unit/test_review_service.py -q` | **27 passed** in 3.65s |
| `pytest tests/unit/test_stage2_report_generator.py -q` | **6 passed** in 2.56s |
| `pytest tests/unit/test_cli.py tests/unit/test_api.py -q` | **22 passed** in 2.67s |
| `pytest tests/integration/test_stage1_6_review.py -q` | **3 passed** in 5.93s |
| 上述五文件合并 | **58 passed** in 8.70s |
| `pytest tests/unit -q` | **1286 passed, 5 skipped** in 25.50s |
| `pytest -q` | **1303 passed, 9 skipped** in 33.89s |
| `ruff check`（全部 Stage 2.5 改动文件） | **All checks passed!** |

Ruff 覆盖文件：

```text
config/settings.py
src/code_review/services/review_service.py
src/code_review/services/stage2_factory.py
src/code_review/reporting/stage2_models.py
src/code_review/reporting/stage2_report_generator.py
src/code_review/reporting/__init__.py
src/code_review/cli.py
src/code_review/api/app.py
tests/integration/test_stage1_6_review.py
tests/unit/test_cli.py
tests/unit/test_api.py
tests/unit/test_review_service.py
tests/unit/test_stage2_report_generator.py
```

阶段 0 回归探针：

| 探针 | 结果 |
|---|---|
| 基础依赖 import | `imports ok` |
| `Settings(_env_file=None)` | `review_output_root = reports`、`trusted_fixture_name = trusted_fixture_v1`、`review_rules_path = None` |
| 四个核心 Schema import | `schemas ok` |
| `git check-ignore .env` | `.env` |
| 依赖扫描 | 仅存在 Stage 2.3 已批准的 LangGraph 闭包（`langgraph`、`langgraph-checkpoint`、`langgraph-prebuilt`、`langgraph-sdk`）及被动 `langchain-*` / `langsmith`；本阶段未新增依赖、未直接 import、未启用 tracing |

---

## 12. 变更文件与冻结边界

新增：

| 文件 | 职责 |
|---|---|
| `src/code_review/reporting/stage2_models.py` | Stage 2 metadata / static / test 三件产物的严格模型 |
| `src/code_review/reporting/stage2_report_generator.py` | 五件产物生成、Pointer 一致性、脱敏、O-1 守卫、Stage 2 Markdown |
| `src/code_review/services/stage2_factory.py` | `Stage2FactoryContext`、`Stage2Dependencies`、`FixtureManagerAgent`、默认依赖装配 |
| `tests/unit/test_stage2_report_generator.py` | 6 条五件产物与一致性测试 |

修改：

| 文件 | 变更 |
|---|---|
| `src/code_review/services/review_service.py` | 双入口、Stage 2 dispatch、`review_stage2_fixture()`、五件产物 outcome |
| `config/settings.py` | `review_rules_path` |
| `src/code_review/reporting/__init__.py` | 导出 Stage 2 模型与生成器 |
| `src/code_review/cli.py` | Stage 2 字段、一位小数、五件产物展示 |
| `src/code_review/api/app.py` | 响应字段、`report_json_path`、`graph`→500、标题/版本 |
| `tests/unit/test_review_service.py` | 新增 Stage 2 harness 与 10 条 Stage 2 服务测试 |
| `tests/unit/test_cli.py` | 新增 2 条 Stage 2 CLI 测试 |
| `tests/unit/test_api.py` | 新增 1 条 Stage 2 API 测试、`graph`→500 参数 |
| `tests/integration/test_stage1_6_review.py` | 两处 `multi_agent=False` |

未修改（已用 `git diff --stat` 确认）：

```text
src/code_review/schemas/task.py, result.py, report.py
docs/requirements.md, architecture.md, workflow.md, task_contracts.md, acceptance.md
src/code_review/reporting/report_generator.py
src/code_review/reporting/artifact_models.py
src/code_review/reporting/markdown_renderer.py
src/code_review/services/finding_aggregator.py
tests/fixtures/trusted_repo/
environment.lock.yml
```

临时证据脚本 `_stage2_5_samples.py` 与 `.stage2_5_samples.txt` 已删除，
不纳入版本控制。

---

## 13. 未决事项与限制

1. **O-1 开放**：`CostSummary` 不能表达未知成本。默认无 LLM 路径的零成本
   真实可信；真实 LLM usage 会使整次审查显式失败。若需真实 LLM 冒烟，
   须先获负责人单独批准并解决成本口径，不能静默写 0。
2. **Validator 注入限制**：Prompt §四.3 要求 Factory 注入 Validator。
   当前 `graph/nodes.py:437` 直接构造 `FinalReviewer()`，使用默认真实
   `Stage2EvidenceValidator`；`graph/nodes.py` 不在 Stage 2.5 允许修改的
   文件清单内，未获批准前不做改造。默认路径安全性不受影响，但无法在
   Service 层替换 Validator 测试替身。
3. **审计计划 D-4 表述差异**：§9.5 仍写“需要负责人确认”，与 §1.3、§2.5、
   §12.5 的“已采纳”不一致；本阶段按已采纳方案实施，见 §4.4。
4. **样例为 Fake 数据**：`tool_versions` 全部为 Fake 默认 `1.9.4`，
   `execution_environment` 来自证据采集主机；不代表真实工具输出。
5. **重复警告**：三个可调用 LLM 的 Agent 各自追加同一条
   `llm client not configured; deterministic tool results only`，样例中
   出现 3 次。不影响功能，记录以便后续去重。
6. **路径回显**：CLI `report_dir`/`artifacts` 与 API `report_path` 继续遵循
   Stage 1 行为，回显配置的输出根；默认配置为相对 `reports`，
   生产 API 返回 `reports/<review_id>`。证据采集脚本使用临时绝对根，
   因此样例中以 `<output-root>` 代替。

---

## 14. §十一 十项验收点逐条证明

| 编号 | 要求 | 证据 | 结果 |
|---:|---|---|---|
| 1 | 生产默认 Stage 2 | `ReviewService.multi_agent: bool = True`（`:220`）；CLI `:72`、API `:69` 不传参；`test_stage2_review_is_the_default_and_writes_five_artifacts` | PASS |
| 2 | Stage 1 测试显式 legacy | `make_harness(multi_agent=False)`（`:149`、`:196`）；集成 `multi_agent=False`（`:119`、`:209`）；17 个 Stage 1 `.review()` 调用点 | PASS |
| 3 | `review_trusted_fixture()` 保持原行为 | `:421` 固定 `_run_review`；`:496`、`:522`、`:1020`、集成 `:212`；四件产物、`commit_sha=None` | PASS |
| 4 | 新 Stage 2 Fixture 入口与旧入口隔离 | `review_stage2_fixture()`（`:462`）校验链；`:870`–`:986` 共 5 条测试；不清理工作区；不暴露 CLI/API | PASS |
| 5 | 五件产物完整 | `test_stage2_review_is_the_default_and_writes_five_artifacts`；生成器 `test_generator_writes_five_consistent_artifacts`；样例 §6.3 | PASS |
| 6 | `report.json` 通过冻结 Schema | `ReviewReport.model_validate_json` 且 `on_disk == report`（生成器测试 `:119-122`）；服务测试 `:731` | PASS |
| 7 | JSON/Markdown 内容一致 | 同一 `ReviewReport` 序列化与渲染；`test_markdown_shows_one_decimal_while_json_keeps_exact_score`（`93.75` / `93.8`） | PASS |
| 8 | Stage 1 四件产物不回归 | `test_review_runs_full_pipeline_and_writes_four_artifacts`；集成 3 条测试；`test_review_trusted_fixture_keeps_stage1_behavior_on_stage2_service` | PASS |
| 9 | CLI/API 响应符合模型 | `extra="forbid"` 响应模型、Stage 2 字段测试、绝对路径不泄露测试、422/405 测试 | PASS |
| 10 | O-1 不伪造零成本 | 生成器 O-1 拒绝测试；服务层 `graph_execution_failed` 且无报告目录；见 §9 | PASS（真实 LLM 成本口径仍开放） |

---

## 15. 停止状态

- 本报告生成后立即停止，**未进入 Stage 2.6**；
- 未执行 `git add`、`git commit`、`git reset`、`git clean`；
- 当前分支 `main`，HEAD 仍为 `ec0afe2`；
- 等待负责人验收。

