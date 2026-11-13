# Stage 2.4 验收报告：Final Reviewer、证据验证、去重与评分

- 阶段：Stage 2.4（Final Reviewer、证据验证、去重与评分）
- 日期：2026-11-13
- 基线 HEAD：`d8e3cf0`（Stage 2.2–2.3 已提交）
- 结论：**PASS WITH CONDITIONS**

本阶段严格按 `Stage2.1-2.6分阶段实施Promp.md` 的 Stage 2.4 边界执行：

- 只新增 `src/code_review/agents/evidence.py`、`reviewer.py`、`scoring.py`，
  修改 `src/code_review/graph/nodes.py`（仅把占位 Final Reviewer 替换为真实节点）
  与测试辅助，并新增四个 Stage 2.4 测试文件；
- 未修改三个冻结 Schema、五份核心文档、Stage 1 报告模块
  （`report_generator.py`、`artifact_models.py`、`markdown_renderer.py`、
  `finding_aggregator.py`）、`ReviewService`、`tests/fixtures/trusted_repo/`
  与 `environment.lock.yml`；
- 未实现报告落盘与五件产物（Stage 2.5），未接入 CLI / API；
- 未调用真实 LLM、未联网、未新增依赖、未启用 tracing；
- 未创建 Checkpointer，未引入 Redis、ARQ、PostgreSQL、MCP、A2A。

---

## 1. Final Reviewer 实现

### 1.1 文件变更

新增文件：

| 文件 | 行数 | 职责 |
|---|---:|---|
| `src/code_review/agents/evidence.py` | 1009 | 内存 `ArtifactData` 证据注册表、V1～V7 校验、脱敏 |
| `src/code_review/agents/reviewer.py` | 886 | `FinalReviewer`、请求/结果契约、去重、报告组装 |
| `src/code_review/agents/scoring.py` | 320 | 维度分、综合分、verdict、展示格式化 |
| `tests/unit/test_evidence_registry.py` | 159 | 6 条内存指针与落盘一致性测试 |
| `tests/unit/test_evidence_validator_v5.py` | 811 | 27 条 V1～V7 测试（另 1 条 Windows 符号链接测试跳过） |
| `tests/unit/test_final_reviewer.py` | 961 | 21 条 Final Reviewer 端到端单元测试 |
| `tests/unit/test_scoring.py` | 401 | 24 条评分、权重与 verdict 测试 |

修改文件：

| 文件 | 变更 |
|---|---|
| `src/code_review/graph/nodes.py` | `final_reviewer_node` 由占位改为真实 Final Reviewer；只返回 `review_report`、`review_statistics`、`review_status` |
| `tests/stage2_helpers.py` | 新增 `make_dimension_task`、`make_dimension_result`、`make_static_analysis`、`make_stage24_artifact_data`、`make_final_review_request` 等 |
| `tests/unit/test_graph_workflow.py` | 删除占位节点断言，改为真实节点与报告断言 |
| `tests/integration/test_stage2_pipeline.py` | 删除占位常量引用，改为完整报告断言 |

### 1.2 调用链

`FinalReviewer.review(FinalReviewRequest)` 按固定顺序执行：

```text
FinalReviewRequest（四个 AgentResult + 内存 ArtifactData + ReviewRules）
→ Stage2EvidenceValidator 逐 Finding 执行 V1～V7
→ 分流：rejected_findings（仅 rejected）/ accepted（verified + unverified）
→ 去重（类别组 + 位置重叠 / 项目级稳定键）
→ 四个维度评分（只统计非 rejected Findings）
→ 综合分（只对有效维度在公式内归一化）
→ report_status
→ verdict（精确值比较）
→ TestSummary / CostSummary / ExecutionSummary / Summary
→ ReviewReport（冻结 Schema 校验）
→ ReviewOutcome(report, statistics, review_status="completed")
```

关键契约：

- `FinalReviewRequest` 校验六个文本字段非空、`agent_results` 恰好包含四个维度、
  每个 `AgentResult.agent_name` / `review_id` / `commit_sha` 与请求一致；
  不一致时抛出 `FinalReviewError`，不降级为报告。
- 报告构造失败（`ValidationError` / `ValueError`）统一转换为
  `FinalReviewError`，由节点向上抛出；不伪造 partial 报告。
- `statistics` 记录 `final_reviewer="implemented"`、`stage="2.4"`、
  `agent_task_count=4`、逐维度验证计数、去重统计、各维度分数、展示分
  （`overall_score_display`）与 verdict。
- `_build_cost_summary` 仅在 `UsageSummary.llm_calls == 0` 时写入全零
  `CostSummary`；存在真实 LLM 调用时抛出 `FinalReviewError`，不伪造 0 成本
  （O-1）。

### 1.3 图节点接入

`final_reviewer_node` 从 `ReviewState` 读取 `review_id`、仓库上下文、
`workspace_path`、`allowed_files`、`rules`、`agent_results`、`artifact_data`、
`usage_summary`、`execution_summary`，构造请求并调用 `FinalReviewer`。
缺少 `agent_results`、`ArtifactData`、`UsageSummary` 或传入非法
`ExecutionSummary` 时抛出 `ReviewStateError`。节点只写三个状态键，
不创建 `AgentTask`、不改变四任务计数。

### 1.4 独立性与只读性

- `tests/unit/test_final_reviewer.py::test_final_reviewer_creates_no_agent_task`
  用 AST 扫描 `reviewer.py` 的 `Name` / `Attribute` / 关键字参数，断言不存在
  `AgentTask` 或 `task_id` 代码级引用（文档字符串不计）。
- `test_final_reviewer_has_no_write_capability` 在 monkeypatch
  `builtins.open`（写模式直接失败）、`Path.write_text`、`Path.write_bytes`
  的条件下完整执行评审，证明 Final Reviewer 无写文件能力。
- `test_review_uses_memory_artifacts_only` 断言评审前后工作区文件快照一致，
  且 `static_analysis.json` / `test_report.json` 从未出现在磁盘上。
- Final Reviewer 不调用 LLM、不访问网络、不读取 `.env`。

---

## 2. 两类 Finding 验证逻辑

`Stage2EvidenceValidator` 依据 `file_path` 与 `start_line` 是否同时存在区分两类
Finding：

| 类型 | 判定 | 校验链 | 通过条件 |
|---|---|---|---|
| A 代码位置型 | `file_path` + `start_line` 均存在 | V1 → V2 → V3 → V4 →（有工具证据时）V5 → V6 → V7 | 文件存在、路径安全、行号合法、代码片段匹配或工具记录佐证、工具证据一致 |
| B 工具报告/项目级 | 无文件位置 | V5 → V6 → V7 | 必须引用真实工具报告记录，且类别语义与记录一致 |

关键语义：

- **V4 源码匹配**：证据片段必须出现在指定行的邻域（±3 行）；邻域内唯一匹配时
  修正行号并记录 `adjusted`。确定性工具 Finding 的 `evidence` 是工具消息而非
  源码时，允许由同一位置的真实工具记录佐证文本（`_tool_record_substantiates`），
  工具/规则/行的一致性仍由 V5 复核。
- **V4 失败分级**：`critical` / `high` 直接 rejected；其余降级为 unverified，
  仍进入报告并参与扣分。
- **V5 工具证据**：只解析**内存** `ArtifactData` 注册表中的稳定指针；工具名、
  规则 ID、文件、行号、维度必须与记录一致；项目级 Finding 必须引用
  `test_report.json`；`low_coverage` 必须引用数值覆盖率且低于配置阈值，
  `test_failure` 必须有正失败数，`missing_tests` 必须为零收集；不一致一律 rejected。
- **V6 误报启发**：位于测试/示例路径的 Finding 只降级为 unverified，不 rejected；
  TestingAgent 与 testing 类别豁免。
- **V7 脱敏**：在所有校验完成后执行，标题、描述、证据、建议中的密钥/token
  被替换，避免脱敏改写证据导致 V4 误判。
- **LLM 自我确认无效**：`test_llm_self_confirmation_never_becomes_verified`
  证明输入 Finding 的 `verification_status` 不参与判定，只有确定性证据可使
  Finding 变为 verified。
- **项目级不伪造位置**：`test_low_coverage_must_not_fake_file_location` 覆盖
  `low_coverage` 带文件位置的伪造场景，V5 拒绝；正式 Finding 的
  `file_path` / `start_line` 保持 `None`。

---

## 3. V1～V7 测试

测试文件：`tests/unit/test_evidence_validator_v5.py`。

| 校验 | 覆盖内容 | 代表性测试 |
|---|---|---|
| V1 | 文件不存在、路径是目录 | `test_v1_missing_file_is_rejected`、`test_v1_directory_is_rejected` |
| V2 | 不在允许集合、符号链接（Windows 无权限时跳过） | `test_v2_outside_allowed_set_is_rejected`、`test_v2_symlink_is_rejected_or_skipped` |
| V3 | 行号越界与非法区间 | `test_v3_line_out_of_range_is_rejected` |
| V4 | 片段不匹配（medium 降级 / critical 拒绝）、邻域唯一匹配修正行号、工具记录佐证 | `test_v4_mismatch_is_unverified_for_medium`、`test_v4_mismatch_rejects_critical_location`、`test_v4_unique_neighborhood_match_adjusts_line`、`test_v4_tool_record_substantiates_tool_message_evidence` |
| V5 | 工具名、规则、文件、行号、维度、非法指针不一致；项目级与工具记录不一致 | `test_v5_*` 共 7 条（1 条通过 + 6 条不一致/非法指针）、`test_project_level_finding_with_static_record_is_rejected` |
| V5 项目级 | `low_coverage` / `test_failure` / `missing_tests` 的真实记录语义 | `test_low_coverage_verified_from_memory_report` 等相关 8 条 |
| V6 | 测试代码误报降级、TestingAgent 豁免 | `test_v6_downgrades_test_code_false_positive` |
| V7 | 证据与描述脱敏 | `test_v7_redacts_secret_evidence_and_description` |
| 附加 | LLM 自我确认、原始 Finding 不被修改 | `test_llm_self_confirmation_never_becomes_verified`、`test_original_finding_is_not_mutated` |

执行结果：

```text
pytest tests/unit/test_evidence_registry.py tests/unit/test_evidence_validator_v5.py \
       tests/unit/test_final_reviewer.py tests/unit/test_scoring.py -v
78 passed, 1 skipped in 2.58s
```

跳过项为 `test_v2_symlink_is_rejected_or_skipped`：当前 Windows 环境未授予
创建符号链接权限，测试按设计 skip，不是失败。

---

## 4. ArtifactData 内存指针及落盘一致性测试

测试文件：`tests/unit/test_evidence_registry.py`（6 条）。

- `test_registry_indexes_static_tool_findings`：
  `static_analysis.json#/agents/security/tools/bandit/findings/0` 解析为
  `static_tool_finding` 记录，工具、维度、规则、行号正确。
- `test_registry_indexes_test_report_fields_and_records`：
  `test_report.json#/coverage`、`#/counts/passed`、`#/records/0` 均可解析。
- `test_registry_rejects_unregistered_or_unknown_pointers`：未注册但
  `ArtifactData` 可解析的指针、非报告文件名、越界下标、非指针字符串全部
  抛出 `EvidenceReferenceError`。
- `test_registry_reads_memory_without_touching_disk`：注册表解析成功时，
  临时目录中不存在 `static_analysis.json` / `test_report.json`。
- `test_same_pointer_resolves_identically_in_memory_and_on_disk`：把
  `ArtifactData` 的内容原样写入磁盘后用最小 JSON Pointer 解析器读取，
  四个指针的内存值与磁盘值完全一致，证明“先内存校验、后落盘”不会产生
  证据漂移。
- `test_reports_and_artifact_data_are_copies`：`static_analysis_dict()` 返回
  深拷贝，修改返回值不影响 `ArtifactData` 与注册表。

此外 `test_review_uses_memory_artifacts_only` 证明完整评审不读取、不创建
报告文件；Final Reviewer 不依赖尚未写盘的文件（问题 A 关闭）。

---

## 5. 去重结果

去重规则（`reviewer.py::_can_merge` / `_merge_group`）：

1. 类别先映射到类别组（`hardcoded_password` → `hardcoded_secret`，
   `style_violation` → `style`）；类别组不同不合并。
2. 一条有位置、一条无位置时不合并。
3. 代码位置型：`file_path` 相同且 `[start_line, end_line]` 区间重叠。
4. 项目级：`(类别组, 工具名集合)` 相同；没有工具名的项目级 Finding 不合并。
5. 保留成员按 confidence 最高、严重度最高、维度靠前、finding_id 字典序的
   顺序选出；合并后严重级别取组内最高；描述与标题来自最高 confidence 成员；
   `tool_evidence` 按 `raw_output_ref` 去重合并；`merged_from` 记录其余成员
   ID（排序去重）；`verification_status` 只要有 verified 即为 verified。
6. 最终 ID 唯一；重复 ID 追加 `~2`、`~3` 后缀；原始 `AgentResult` 不被修改。

测试结果：

| 场景 | 结果 |
|---|---|
| Security `hardcoded_secret` + Quality `hardcoded_password`，同文件第 5 行 | 合并为 `SEC-0001`（high），`merged_from=["QUA-0001"]`，两条工具证据保留，`merged_away=1`；Quality 原始结果仍为 unverified |
| Testing `missing_tests` + Quality `missing_tests`，均为项目级、工具均为 pytest | 合并为 `QUA-0001`（medium，confidence 0.8），`merged_from=["TST-0001"]` |
| 两条 Finding 标题相同但类别不同、行号不同（第 9 / 14 行） | 不合并，报告保留 2 条 |

跨维度合并后，`agent_results` 中仍是原始四条结果与原始 Finding，未被就地修改。

---

## 6. 评分计算示例

规则来源：`config/review_rules.yaml`（权重 Security 0.35、Quality 0.25、
Performance 0.20、Testing 0.20；扣分 critical 25、high 15、medium 5、low 2、
info 0；`approve_min_score=80`、`request_changes_below=60`）。

| 示例 | 计算 | 结果 |
|---|---|---|
| 五级 Finding 各一条 | 100 − (25+15+5+2+0) | 53.0 |
| 四条 critical | 100 − 100 → clamp | 0.0 |
| 四维全有效：91 / 90 / 80 / 70 | 0.35×91 + 0.25×90 + 0.20×80 + 0.20×70 | 84.35 |
| Testing 缺失：91 / 90 / 80 / null | (0.35×91 + 0.25×90 + 0.20×80) / 0.80 | 87.9375 |
| 部分维度缺失（如三维有效） | 只对有效维度加权后除以有效权重和 | 有效分 |
| 仅一个维度有效 | 综合分等于该维度分 | 有效分 |
| 四维全缺失 | 无有效维度 | null |
| rejected Finding | 不参与扣分 | 不扣分 |
| 维度的 `DimensionScore.weight` | 始终写入配置权重（如 Testing 缺失仍为 0.20） | 不写回归一化值 |
| 非法权重（总和 ≠ 1） | `load_review_rules` 抛 `ReviewRulesError` | 拒绝加载 |

Final Reviewer 端到端示例（`test_report_keeps_exact_score_and_display_value`）：
Security 98、Quality 95、Performance 98、Testing 不可用，
综合分 `(0.35×98 + 0.25×95 + 0.20×98) / 0.80 = 97.0625`，报告保存 97.0625，
展示值 `97.1`，Testing 权重仍为 0.20，报告 partial、verdict COMMENT。

---

## 7. B-2 精确值验证

| 断言 | 实际结果 |
|---|---|
| `compute_overall_score` 返回 87.9375 | 精确保存 87.9375，`format_score` 为 `"87.9"` |
| 79.96 展示为 `"80.0"` | `format_score(79.96) == "80.0"`，但精确值 79.96 < 80，verdict 为 COMMENT |
| 80.0 精确值 | 满足阈值，verdict 为 APPROVE |
| 97.0625 端到端 | `report.overall_score` 为 97.0625（1e-9 容差），`statistics["overall_score_display"] == "97.1"` |
| 缺失维度权重 | `DimensionScore.weight` 保持 0.20（配置值），重归一化只发生在综合分公式内部 |
| Schema | 未修改冻结 Schema；报告保存精确 float，Markdown/CLI 展示留待 Stage 2.5 使用一位小数 |

verdict 的所有阈值比较均使用精确值，展示格式化函数
`format_score` 只用于报告理由与统计展示，不参与判定。

---

## 8. critical 硬阻断测试

`test_verified_critical_blocks_in_every_dimension` 以
`pytest.mark.parametrize` 分别在 security、quality、performance、testing
四个维度构造一条已核验 `critical` Finding：

- Security：Bandit B608 记录 + 第 9 行 SQL 源码；
- Quality：Radon 记录 + 第 9 行源码；
- Performance：Radon 记录 + 第 9 行源码；
- Testing：pytest 记录 + 测试文件第 3 行源码。

四次执行均断言：Finding 为 verified、报告 `overall_verdict="REQUEST_CHANGES"`、
`verdict_reasons` 含 critical 理由。任一维度的 critical 都可独立硬阻断，
不依赖具体维度或具体工具。

反向验证：

- `test_forged_critical_is_rejected_without_blocking`：伪造 critical（文件不存在、
  证据不匹配）被 rejected，进入 `rejected_findings`，不参与评分；Security 分
  仍为 100，verdict 为 APPROVE。
- critical 由测试独立构造（`severity="critical"`），未预置 B107 / B608 为
  critical；Bandit 原始级别映射仍由 Stage 2.2 的配置决定（问题 C 关闭）。

---

## 9. 失败语义测试

| 场景 | 断言 |
|---|---|
| 单个 Agent failed | 报告 partial、verdict COMMENT、失败维度 `score=None` 且有 reason；其余维度正常评分，综合分只含有效维度 |
| 四个 Agent 全部 failed | 四个维度 `score=None`、`overall_score=None`、报告 partial、verdict COMMENT、`failed_tasks=4`、reasons 非空 |
| pytest 成功 + Coverage 失败 | `TestSummary` 保留真实计数 passed=3 / failed=0，coverage=None，Testing 维度分 None，报告 partial |
| 外部仓库 Testing `not_executed` | TestingAgent 结果 completed，Testing 维度 `score=None` 且有 reason，`test_summary.execution_status="not_executed"`，报告 partial、COMMENT |
| 伪造 / 越界证据 | Finding 进入 `rejected_findings`，不评分、不触发 critical 阻断 |
| Final Reviewer 自身失败 | `usage_summary.llm_calls=1` 或 `ExecutionSummary.total_tasks=5` 等不一致输入均抛 `FinalReviewError`，节点向上抛出，不生成伪造 partial 报告 |
| 请求契约不一致 | `agent_results[security].agent_name` 改为 QualityAgent 时构造请求即抛 `FinalReviewError` |

**需负责人裁定的偏差**：提示词 §十二 期望“pytest 成功 + Coverage 失败”时
TestingAgent 结果为 `partial`；当前上游 Stage 2.2 的 TestingAgent 将该场景标记为
`failed`。Stage 2.4 按“不得修改专业 Agent”的边界保留真实状态，未改写
`AgentResult.status`，报告层面仍做到真实计数保留、Testing 分数 null、报告
partial。核心可见结果一致，但维度 `status`（`failed`）与执行汇总中的
`failed_tasks` / `partial_tasks` 计数会随上游状态不同。是否在后续阶段把
TestingAgent 的 Coverage 失败映射改为 `partial`，需负责人确认。

O-1（`CostSummary` 无法表达未知成本）：Fake 路径 `llm_calls=0` 时写全零
`CostSummary` 是真实值；存在真实 LLM 调用时 `FinalReviewer` 直接失败，
不伪造 0 token / 0 成本。

---

## 10. Stage 1 回归结果

执行命令与结果：

```text
pytest tests/unit -q
1266 passed, 5 skipped in 18.49s

pytest -q
1283 passed, 9 skipped in 39.37s
```

- Stage 1 全部测试继续通过；未修改 `src/code_review/services/`、
  `src/code_review/reporting/`、`src/code_review/tools/`、
  `src/code_review/schemas/` 与 Stage 1 测试。
- 冻结文件检查：
  `git status --porcelain -- src/code_review/schemas docs environment.lock.yml src/code_review/reporting src/code_review/services tests/fixtures`
  输出为空。
- 本阶段未新增依赖，`environment.yml` / `environment.lock.yml` 未改动；
  未安装 `langchain-openai` / `langsmith`，未启用 tracing，未读取 API Key。
- 单元测试不联网、不调用真实 LLM；Fake Agent 与内存 `ArtifactData` 完成全流程。
- Ruff（本次改动文件）：

```text
ruff check src/code_review/agents/evidence.py src/code_review/agents/reviewer.py \
           src/code_review/agents/scoring.py src/code_review/graph/nodes.py \
           tests/stage2_helpers.py tests/unit/test_evidence_registry.py \
           tests/unit/test_evidence_validator_v5.py tests/unit/test_final_reviewer.py \
           tests/unit/test_scoring.py tests/unit/test_graph_workflow.py \
           tests/integration/test_stage2_pipeline.py
All checks passed!
```

全仓测试基线由 Stage 2.3 的 1205 passed / 8 skipped 提升至 1283 passed /
9 skipped（新增 Stage 2.4 测试 78 条，另 1 条符号链接测试跳过）。

---

## 11. PASS / PASS WITH CONDITIONS / BLOCKED

**结论：PASS WITH CONDITIONS。**

Stage 2.4 的功能要求全部实现并通过测试：独立 Final Reviewer、两类 Finding
验证、V1～V7、内存 `ArtifactData` 闭环、去重、维度/综合评分、B-2 精确值、
四维 critical 硬阻断、失败语义与 Stage 1 回归均符合验收要求。

条件与待确认事项：

1. **Testing 覆盖失败的状态值**：提示词 §十二 期望 TestingAgent 为
   `partial`，当前上游 Stage 2.2 实际为 `failed`。Stage 2.4 未改写 Agent
   状态，报告层面（真实计数保留、Testing 分数 null、报告 partial）符合要求；
   是否调整 TestingAgent 状态映射需负责人裁定（本阶段不修改专业 Agent）。
2. **测试文件略超提示词允许清单**：`tests/unit/test_graph_workflow.py` 与
   `tests/integration/test_stage2_pipeline.py` 不在 §三 的文件清单内，但必须
   修改才能删除 Stage 2.3 占位节点断言并验证真实 Final Reviewer。改动仅限
   测试断言，未改动生产代码边界。
3. **`decide_verdict` 新增 `report_status` 参数**：冻结 Schema 明确禁止
   partial 报告使用 APPROVE，Stage 2.4 在 verdict 判定前计算报告状态并在
   APPROVE 分支排除 partial。该调整是满足冻结契约的必要实现，不涉及
   Schema/文档修改。
4. **遗留占位常量**：`graph/__init__.py` 与 `graph/state.py` 仍导出
   `PLACEHOLDER_REVIEW_STATUS`，生产路径已不再使用。由于这两个文件不在
   Stage 2.4 修改范围，未删除；建议 Stage 2.5 清理。

本阶段未执行 Git commit，未进入 Stage 2.5，等待负责人验收。
