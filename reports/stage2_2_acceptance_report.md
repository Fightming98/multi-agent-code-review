# Stage 2.2 验收报告：Manager 与四个专业 Agent

- 阶段：Stage 2.2（Manager 与四个专业 Agent）
- 日期：2026-11-12
- 基线 HEAD：`12daa7d`（`阶段 2.1：Agent 基础合同、BaseAgent 与规则加载`）
- 结论：**PASS**

本阶段严格按 `Stage2.1-2.6分阶段实施Promp.md` 的 Stage 2.2 边界执行：未接入
LangGraph、未安装任何新依赖、未修改 `ReviewService`、未实现 Final Reviewer、
未生成 `report.json`、未进入 Stage 2.3。

---

## 1. 文件变更

### 1.1 新增文件

| 文件 | 行数 | 说明 |
|---|---:|---|
| `src/code_review/agents/manager.py` | 558 | 确定性 Manager：`plan()`、`aggregate()`、`TaskPlan`、`AggregatedResults` |
| `src/code_review/agents/security.py` | 697 | SecurityAgent：Bandit + 受限 LLM 语义补充 |
| `src/code_review/agents/quality.py` | 826 | QualityAgent：Ruff + Radon + 受限 LLM 语义补充 |
| `src/code_review/agents/performance.py` | 607 | PerformanceAgent：Radon CC + 静态推断（禁止 Benchmark 冒充） |
| `src/code_review/agents/testing.py` | 429 | TestingAgent：TestRunner/Pytest/Coverage，无 LLM |
| `tests/unit/test_manager_agent.py` | 365 | 33 条 Manager 测试 |
| `tests/unit/test_security_agent.py` | 382 | 21 条 SecurityAgent 测试 |
| `tests/unit/test_quality_agent.py` | 393 | 24 条 QualityAgent 测试 |
| `tests/unit/test_performance_agent.py` | 281 | 19 条 PerformanceAgent 测试 |
| `tests/unit/test_testing_agent.py` | 297 | 16 条 TestingAgent 测试 |

### 1.2 修改文件

| 文件 | 变更 |
|---|---|
| `tests/stage2_helpers.py` | +366 行，新增 `FakeAnalysisTool`、`FakeTestRunner`、`make_tool_finding`、`make_tool_result`、`make_test_execution_result`、`make_execution`、`make_plan_execution` 等 Stage 2.2 测试设施 |

### 1.3 边界确认

- 三个冻结 Schema（`task.py`、`result.py`、`report.py`）未修改。
- 五份核心文档、Stage 1 工具、`finding_aggregator.py`、`report_generator.py`、
  `artifact_models.py`、`markdown_renderer.py`、`tests/fixtures/trusted_repo/`、
  `environment.lock.yml` 均未修改。
- 四个 Prompt（`security.md`、`quality.md`、`performance.md`、`testing.md`）
  沿用 Stage 2.1 版本，本阶段无需修订，未改动。
- `git diff --name-only` 仅显示 `CLAUDE.md`、`reports/stage2_1_acceptance_report.md`
  与 `tests/stage2_helpers.py`；前两项为 Stage 2.2 开始前已存在的未提交修改，
  不是本阶段改动。
- 本阶段未安装任何依赖；未创建 `graph/`、`orchestration/`、`workers/` 等目录。
- 本阶段未执行 Git commit。

---

## 2. Manager.plan 与 aggregate 的实现

Manager 为纯确定性 Python 组件，不持有 `settings`、工具或 LLM 客户端
（测试 `test_no_retries_and_no_manager_prompt` 显式断言不存在这些属性）。
不扫描代码、不执行工具、不评分、不去重、不生成 verdict。

### 2.1 `plan()`

`ManagerAgent.plan(review_id, commit_sha, language="python", timeout_seconds=None)`
返回不可变 `TaskPlan`：

- 1 个根任务：`agent_name="ManagerAgent"`，`task_type="review_orchestration"`；
- 4 个专业子任务，顺序固定：
  - `SecurityAgent` / `security_review`
  - `QualityAgent` / `quality_review`
  - `PerformanceAgent` / `performance_review`
  - `TestingAgent` / `testing_review`
- 每个子任务 `parent_task_id` 指向根任务；`review_id`、`commit_sha` 一致；
- 所有任务 `max_retries=0`、`status="pending"`，不读取
  `settings.max_retry_attempts`；
- 子任务 `input_data` 只含 `{"dimension", "language"}`，不含工作区路径、
  主机路径或完整 `ReviewState`；
- `timeout_seconds` 传入时同时写入根任务和四个子任务；不传则为 `None`；
- `TaskPlan` 构造时校验：恰好四个任务、顺序与维度一致、任务 ID 唯一、
  父任务与 `review_id`/`commit_sha` 一致、`max_retries=0`；非法时抛
  `ValueError`；
- 不创建 Final Reviewer 的 `AgentTask`，Professional Task 总数严格为 4。

### 2.2 `aggregate()`

`ManagerAgent.aggregate(plan, executions: Mapping[str, AgentExecution | None], warnings=())`
返回 `AggregatedResults`：

| 字段 | 行为 |
|---|---|
| `agent_results` | 固定四个 key：`security`、`quality`、`performance`、`testing` |
| `artifact_data` | 内存 `ArtifactData`，包含 `static_analysis` 与 `test_report` |
| `usage_summary` | 四个维度 `UsageSummary` 逐字段相加；不伪造未上报的 token |
| `execution_summary` | `total_tasks=4`；completed/partial/failed/cancelled 之和恒等于 4；duration 取现有 timing 的最大结束时间减最小开始时间 |
| `root_task` | 合法终态 `completed` 或 `failed`；`finished_at` 不早于根任务创建时间与所有 timing |
| `warnings` | 缺失结果、未知 key 等聚合告警 |

缺失或非法执行结果的语义：

- 缺失、类型非法、`task_id`/`agent_name`/`review_id`/`commit_sha` 不匹配时，
  为该维度合成合法的 failed `AgentResult`：
  `error_type="missing_agent_result"`、`retryable=False`、`score=None`、
  `findings=[]`、`metadata={"synthesized": True, "reason": ...}`；
- 其他维度的结果与证据保持不变，单个 Agent 失败不会丢失其他 Agent 的结果；
- 未知 execution key 被忽略并记 warning；
- 四个维度全部 failed 时根任务置为 `failed` 并写
  `last_error.error_type="aggregate_incomplete"`；否则根任务为 `completed`；
- Manager 不改写任何 `AgentResult.score`，不修改 Finding 的
  `verification_status`。

---

## 3. 四个专业 Agent

四个 Agent 在工具链、类别白名单、证据来源和 LLM 策略上均实质不同，不是
共用同一个通用 LLM 函数后替换 Prompt 名称。

| 维度 | 工具链 | Prompt | LLM 策略 | Finding 类别白名单 | 主要证据 Pointer |
|---|---|---|---|---|---|
| Security | Bandit | `security.md` | 允许 info/low/medium 语义补充；LLM 提供的 `tool_evidence` 一律丢弃 | `hardcoded_secret`、`sql_injection`、`command_injection`、`insecure_deserialization`、`weak_crypto`、`path_traversal`、`unsafe_network` | `static_analysis.json#/agents/security/tools/bandit/findings/{index}` |
| Quality | Ruff + Radon | `quality.md` | 允许 info/low/medium；工具结果与 LLM 推断分开记录 | `code_smell`、`style`、`high_complexity`、`error_handling`、`maintainability`、`duplication` | `...#/agents/quality/tools/ruff/findings/{i}`、`...#/tools/radon/findings/{i}` |
| Performance | Radon CC | `performance.md` | 允许 info/low/medium；拒绝 benchmark/吞吐量/延迟等测量断言 | `high_complexity`、`algorithmic_complexity`、`memory_risk`、`io_efficiency` | `static_analysis.json#/agents/performance/tools/radon/findings/{index}` |
| Testing | TestRunner + Pytest + Coverage | 无（不使用 LLM） | 禁止 LLM 估算或补写任何测试统计 | `test_failure`、`low_coverage`、`missing_tests` | `test_report.json#/counts`、`test_report.json#/coverage`、`test_report.json#/records/{i}` |

### 3.1 SecurityAgent

- 只调用 Bandit；工具执行经 `asyncio.to_thread`，异常被隔离为工具失败。
- 规则到类别的映射稳定覆盖 B102–B615；无法映射的规则不生成 Finding，
  但原始工具结果完整保留在证据中并发 warning。
- severity 严格来自 `review_rules.yaml` 的 Bandit 映射：
  `rules.map_severity("bandit", raw.upper())`；测试显式验证 B107/B608 即使
  原始级别为 HIGH 也不会变成 critical。
- LLM 补充只接受 info/low/medium，类别必须在 Security 白名单内，文件必须
  命中 `allowed_files`；LLM 自述的 `tool_evidence` 被丢弃，无法伪造工具证据。
- Finding ID：`SEC-BANDIT-NNNN`、`SEC-LLM-NNNN`；所有 Finding 保持
  `verification_status="unverified"`。

### 3.2 QualityAgent

- Ruff 与 Radon 并行调用（各自独立实例，无共享可变状态）；单个工具失败时
  保留另一个工具的结果。
- Ruff 规则按规则族映射类别：`C90→high_complexity`、`TRY→error_handling`、
  `E/W/I/UP/RUF/SIM/D/Q/FA/PIE/PT→style`、`F/B/PL/ARG/RET/G/N→code_smell`。
- Ruff 的 `S`（安全）规则不由 QualityAgent 生成 Finding，明确留给
  SecurityAgent，避免维度越权；原始结果仍保留。
- Ruff JSON 通常不提供 severity，使用确定性的规则族标签（E9/F82 → `error`，
  其余 → `warning`）再经 `review_rules.yaml` 映射；最终级别仍由配置决定。
- Radon CC 的 A 级不生成 Finding，B–F 经配置映射；Maintainability Index
  聚合为一条项目级 `maintainability` Finding（`file_path=None`、
  `start_line=None`、`end_line=None`，多条工具证据），不伪造文件/行号。
- LLM 补充类别必须属于 Quality 白名单；`sql_injection`、`test_failure` 等
  跨维度类别被拒绝。
- Finding ID：`QUA-RUFF-NNNN`、`QUA-RADON-NNNN`、`QUA-RADON-MI-NNNN`、
  `QUA-LLM-NNNN`。

### 3.3 PerformanceAgent

- 只使用 Radon 的 Cyclomatic Complexity；`RADON_MI` 明确标注为
  “outside the performance dimension” 并跳过。
- Finding 描述明确声明“not a runtime benchmark”；Agent metadata 固定
  `analysis_mode="static_inference"`、`benchmark_executed=False`。
- LLM 补充除类别/级别/位置校验外，额外用正则拒绝 benchmark、measured、
  throughput、latency、ops/sec、MB/s、QPS 等测量断言；接受的描述统一加上
  `Static inference (no benchmark executed): ` 前缀。
- Finding ID：`PERF-RADON-NNNN`、`PERF-LLM-NNNN`。

### 3.4 TestingAgent

- 不使用 LLM；测试数量、失败数、跳过数和覆盖率只来自 `TestRunner` 的真实
  `TestExecutionResult`。
- 可信 Fixture 门禁：只读取 `task.input_data["trusted_fixture"]`，且仅当它与
  `settings.trusted_fixture_name` 完全一致时传给 TestRunner；其他值被忽略并
  发 warning，测试保持 `not_executed`。
- 外部不可信仓库的 `NOT_EXECUTED` 语义（D-12）：AgentResult 为 `completed`，
  Testing 维度可在后续阶段得到 `null` 分数；本阶段 AgentResult 的 `score`
  始终为 `None`，不写虚构统计。
- `test_failure` 使用 `test_report.json#/counts`；`low_coverage` 使用
  `test_report.json#/coverage`；二者均为项目级 Finding，不带伪造的文件/行号；
  `missing_tests` 仅在真实执行且收集到 0 条测试时产生。
- 工具 FAILED/TIMEOUT/异常 → `failed`（`testing_tool_error`），不生成 Finding，
  但保留工具报告块；不执行重试。

---

## 4. ArtifactData 结构与示例 Pointer

`ManagerAgent.aggregate()` 在内存中构建同一份 `ArtifactData`，后续 Stage 2.4
Final Reviewer 与报告生成器必须复用该对象，不得另起一套拼装逻辑。

### 4.1 `static_analysis.json`

```json
{
  "schema_version": "1.0",
  "agents": {
    "security": {
      "agent_name": "SecurityAgent",
      "result_status": "completed",
      "warnings": [],
      "tools": {"bandit": {"execution_status": "findings", "findings": []}}
    },
    "quality": {
      "agent_name": "QualityAgent",
      "result_status": "completed",
      "warnings": [],
      "tools": {"ruff": {}, "radon": {}}
    },
    "performance": {
      "agent_name": "PerformanceAgent",
      "result_status": "completed",
      "warnings": [],
      "tools": {"radon": {}}
    },
    "testing": {
      "agent_name": "TestingAgent",
      "result_status": "completed",
      "warnings": [],
      "tools": {}
    }
  }
}
```

### 4.2 `test_report.json`

包含 `schema_version`、`execution_status`、`reason`、`counts`（total/passed/
failed/skipped）、`coverage`、`source`、`duration_seconds`、`fixture`、
`records`、`records_truncated`、`coverage_files`、`coverage_files_truncated`、
`tool_versions`、`read_only_verified`、`modified_paths`、`warnings`、
`agent_name`、`result_status`。未执行时 counts/coverage 保持 `null`，不写 0。

### 4.3 已验证的稳定 Pointer

| Pointer | 测试验证值 |
|---|---|
| `static_analysis.json#/agents/security/tools/bandit/findings/0/rule_id` | `B608` |
| `static_analysis.json#/agents/quality/tools/ruff/findings/0/rule_id` | `E501` |
| `static_analysis.json#/agents/performance/tools/radon/findings/0/rule_id` | `RADON_CC` |
| `static_analysis.json#/agents/security/agent_name` | `SecurityAgent` |
| `test_report.json#/coverage` | `91.0` |
| `test_report.json#/counts/passed` | `3` |
| `test_report.json#/records/0/name` | `tests/test_app.py::test_ok` |

`ArtifactData.resolve()` 对非法 Pointer 抛合同异常；结构由
`test_artifact_data_has_stable_pointer_structure` 覆盖。

---

## 5. D-11 处理结果

| 情况 | Security / Performance（单工具） | Quality（双工具） | 结果状态 |
|---|---|---|---|
| 工具成功，LLM 成功 | 正常生成 Finding | 两个工具均成功且 LLM 成功 | `completed` |
| 工具成功，LLM 失败 | 保留全部工具 Finding，`llm_analysis_error` | 保留两个工具结果，`llm_analysis_error` | `partial` |
| 工具失败，LLM 成功 | 保留 LLM 补充 Finding，`tool_execution_error`；不形成可靠评分依据 | 至少一个工具可用时保留可用结果；两个工具均硬失败时只保留 LLM 结果并标记 partial | `partial` |
| 工具和 LLM 均失败 | `failed`，无 Finding | `failed`，无 Finding | `failed` |

补充语义：

- `ToolExecutionStatus.PARTIAL` 视为降级证据，返回 `partial` +
  `tool_degraded`，已有 Finding 保留。
- 任何失败结果的 `retryable=False`，Stage 2.2 不重试。
- Agent 不把任何 Finding 标记为 `verified`；所有 Finding 保持 `unverified`。
- TestingAgent 的 D-12：`NOT_EXECUTED` → `completed`，不生成 Finding，
  counts/coverage 为 `null`；工具硬失败 → `failed`。

---

## 6. 测试结果

### 6.1 Stage 2.2 五个测试文件

```text
$ pytest tests/unit/test_manager_agent.py tests/unit/test_security_agent.py \
         tests/unit/test_quality_agent.py tests/unit/test_performance_agent.py \
         tests/unit/test_testing_agent.py -q
113 passed in 2.89s
```

分布：Manager 33、Security 21、Quality 24、Performance 19、Testing 16。

### 6.2 全量单元测试

```text
$ pytest tests/unit -q
1141 passed, 4 skipped, 1 warning in 20.13s
```

对比 Stage 2.1 基线（1028 passed, 4 skipped）：新增 113 条，全部通过，
无跳过、无失败。唯一 warning 为既有的 FastAPI/Starlette `httpx` 弃用提示。

### 6.3 全量测试

```text
$ pytest -q
1152 passed, 8 skipped, 1 warning in 35.19s
```

对比 Stage 2.1 全量基线（1039 passed, 8 skipped）：新增 113 条，全部通过。

### 6.4 Ruff

```text
$ ruff check src/code_review/agents/manager.py src/code_review/agents/security.py \
             src/code_review/agents/quality.py src/code_review/agents/performance.py \
             src/code_review/agents/testing.py tests/stage2_helpers.py \
             tests/unit/test_manager_agent.py tests/unit/test_security_agent.py \
             tests/unit/test_quality_agent.py tests/unit/test_performance_agent.py \
             tests/unit/test_testing_agent.py
All checks passed!
```

所有捕获 `Exception` 的工具/LLM/Provider 边界均按项目约定标注
`# noqa: BLE001` 并说明原因；未放宽任何规则。

### 6.5 依赖与禁用项

```text
langgraph: None
langchain_core: None
langsmith: None
```

- `src/` 下无 `langgraph`、`langchain`、`langsmith` 引用。
- 未安装任何新依赖，未修改 `environment.yml` / `environment.lock.yml`。
- 测试不联网、不调用真实 LLM；所有 LLM 交互使用 `FakeLLMClient`，工具使用
  `FakeAnalysisTool` / `FakeTestRunner`。

---

## 7. Stage 1 回归

- 全量 `pytest -q` 包含 Stage 1 的全部单元与集成测试，结果为
  1152 passed, 8 skipped，无 failure / error。
- Stage 1 的工具层（Bandit/Ruff/Radon/TestRunner）、`finding_aggregator.py`、
  `reporting/`、`services/`、API 与 CLI 均未修改。
- `tests/fixtures/trusted_repo/` 与 `environment.lock.yml` 未修改。
- Stage 1 的四件产物路径与报告行为不受本阶段影响；`report.json` 仍未生成。

---

## 8. 未完成项与风险

### 8.1 按阶段计划未完成（非本阶段缺陷）

1. 未实现 LangGraph StateGraph、并行 fan-out/fan-in（Stage 2.3）。
2. 未实现 Final Reviewer、证据验证、去重、评分与 verdict（Stage 2.4）。
3. 未接入 `ReviewService`，未生成五件报告与 `report.json`（Stage 2.5）。
4. 未做真实工具 + 真实仓库的端到端基线验收（Stage 2.6）。
5. 未执行真实 LLM 冒烟；该动作需负责人单独批准，且不纳入默认验收。

### 8.2 风险与注意事项

1. **聚合接口待接线**：`aggregate()` 接收内存中的
   `Mapping[str, AgentExecution | None]`，Stage 2.3 需要把 LangGraph 状态键
   映射到该结构；当前未提供适配层。
2. **评分始终为 null**：四个 Agent 均不写 `score`，维度评分逻辑属于
   Stage 2.4；下游不能在本阶段把 `score=None` 误判为失败。
3. **超时未在 Agent 层强制**：`plan()` 会传播 `timeout_seconds`，但
   `BaseAgent` 不实现超时取消；执行超时需由 Stage 2.3 编排层负责。
4. **真实工具集成未在本阶段验证**：单元测试使用 Fake 工具；真实 Bandit/
   Ruff/Radon/TestRunner 的 Agent 级组合验证安排在 Stage 2.6。Stage 1 的
   真实工具测试仍然通过，但未经过专业 Agent 包装。
5. **Ruff severity 推导**：Ruff JSON 缺少 severity 时，使用确定性规则族标签
   再经 YAML 映射。该策略已文档化并由测试覆盖，但规则族之外的未知规则统一
   归入 `code_smell`，后续可按需扩展映射表。
6. **小范围代码重复**：为遵守 Stage 2.2 允许文件范围，五个 Agent 之间保留了
   少量相似辅助函数（工具块构造、错误对象构造）；未新增共享模块，后续可在
   允许重构时提取。
7. **工作树状态**：`CLAUDE.md` 与 `reports/stage2_1_acceptance_report.md` 的
   修改在本阶段开始前已存在；本阶段未提交 Git commit，`main` 仍领先
   `origin/main` 1 个提交（远端停留在 `65af76e`），按提示词要求等待负责人
   验收后再决定提交与推送。

---

## 9. 结论

**PASS**

Stage 2.2 要求的确定性 Manager、四个专业 Agent、聚合逻辑、`ArtifactData`、
`UsageSummary`、`ExecutionSummary` 与 Fake/Mock 测试均已实现并通过验收：

- Manager 与四个 Agent 的职责、工具链、类别白名单与证据来源确实不同；
- 工具证据真实、可追溯，Testing 统计不伪造，项目级 Finding 不伪造文件行号；
- D-11 / D-12 的 partial / failed / not_executed 语义符合冻结合同；
- 无 LangGraph 依赖，无 Schema、核心文档或 Stage 1 代码改动；
- Stage 1 与全量测试无回归。

未进入 Stage 2.3，等待负责人验收。
