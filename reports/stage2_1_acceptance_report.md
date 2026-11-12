# Stage 2.1 验收报告：Agent 基础合同、BaseAgent、Prompt 与规则加载

- 报告生成日期：2026-11-12
- 当前分支：`main`
- 当前 HEAD：`65af76e feat(stage1): complete single-agent code review foundation`
- 实现范围：Stage 2.1（仅基础设施；未实现具体 Agent、Manager、Final Reviewer、LangGraph、ReviewService 改造）
- 结论：**PASS WITH CONDITIONS**（实现与测试通过；`CLAUDE.md` 的审计 G-2 过时文档问题尚未修改，见 §12）

---

## 1. 实际新增/修改文件

### 1.1 新增文件

| 文件 | 职责 |
|---|---|
| `src/code_review/agents/__init__.py` | 导出 Agent 基础设施公开类型与函数；不包含具体专业 Agent。 |
| `src/code_review/agents/contracts.py` | Agent 内部 DTO/Protocol、只读证据快照、JSON Pointer 解析、usage 汇总。 |
| `src/code_review/agents/base.py` | `BaseAgent` 统一异步生命周期、合同校验、异常转换、脱敏与 timing。 |
| `src/code_review/agents/llm_support.py` | 安全 Prompt 投影、四个 Prompt 文件加载、JSON 解析/字段校验、真实 usage 汇总、注入式 JSON 请求。 |
| `src/code_review/prompts/security.md` | SecurityAgent 职责、类别、证据、提示注入防护与结构化输出约束。 |
| `src/code_review/prompts/quality.md` | QualityAgent 职责与类别；禁止越权安全/性能/测试分析。 |
| `src/code_review/prompts/performance.md` | PerformanceAgent 职责；明确静态推断不等于 Benchmark 实测。 |
| `src/code_review/prompts/testing.md` | TestingAgent 职责；测试数量、失败数、覆盖率只能来自真实工具。 |
| `config/review_rules.yaml` | 评分权重、扣分、结论阈值、覆盖率阈值、复杂度等级、工具严重级别映射。 |
| `config/review_rules.py` | 严格 YAML 加载、字段/类型/权重校验、不可变 `ReviewRules` 访问。 |
| `tests/stage2_helpers.py` | `FakeAgent`、`FakeLLMClient`、AgentTask/WorkerRuntime/Dispatch/Evidence/ArtifactData 工厂。 |
| `tests/unit/test_agent_base.py` | BaseAgent 生命周期、异常、合同、脱敏测试（28 条）。 |
| `tests/unit/test_stage2_contracts.py` | DTO、只读快照、ArtifactData 指针测试（58 条）。 |
| `tests/unit/test_review_rules.py` | 规则加载成功/失败、权重/阈值/严重级别校验测试（58 条）。 |
| `tests/unit/test_llm_support.py` | 安全投影、Prompt 文件、JSON 解析、usage、注入式请求测试（64 条）。 |

### 1.2 修改文件

| 文件 | 修改内容 |
|---|---|
| `environment.yml` | **仅新增** `- pyyaml==6.0.3`；未修改其他依赖或版本。 |

### 1.3 明确未修改的文件

以下文件均通过 `git diff --quiet` 验证为未变化：

- `environment.lock.yml`
- `src/code_review/schemas/task.py`
- `src/code_review/schemas/result.py`
- `src/code_review/schemas/report.py`
- `docs/requirements.md`
- `docs/architecture.md`
- `docs/workflow.md`
- `docs/task_contracts.md`
- `docs/acceptance.md`
- `src/code_review/reporting/report_generator.py`
- `src/code_review/reporting/artifact_models.py`
- `src/code_review/reporting/markdown_renderer.py`
- `src/code_review/services/finding_aggregator.py`
- `tests/fixtures/trusted_repo/`
- `CLAUDE.md`

未创建 `graph/`、`agents/manager.py`、`agents/security.py`、`agents/quality.py`、`agents/performance.py`、`agents/testing.py`、Final Reviewer 或任何 LangGraph 文件。

---

## 2. 内部 DTO/Protocol 设计

### 2.1 `UsageSummary`

字段：

| 字段 | 类型 | 语义 |
|---|---|---|
| `llm_calls` | `int` | 实际发起的客户端调用次数。 |
| `reported_usage_calls` | `int` | 返回了可拆分 usage 的调用次数。 |
| `input_tokens` | `int` | 真实返回的 `prompt_tokens` 累加。 |
| `output_tokens` | `int` | 真实返回的 `completion_tokens` 累加。 |

约束：

- 所有字段必须是非负整数，布尔值不算整数。
- `reported_usage_calls <= llm_calls`。
- 提供 `total_tokens` 与 `__add__`，便于 Manager 后续汇总。
- 与冻结的 `CostSummary` 完全独立；不改 Schema、不伪造 0 成本或 0 token 的真实调用。

### 2.2 `WorkerRuntime` 与 `WorkerDispatch`

`WorkerRuntime`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `workspace_path` | `Path` | 受控工作区路径；字符串会转为 `Path`。 |
| `allowed_files` | `tuple[str, ...]` | 仅允许仓库相对 POSIX 路径；拒绝绝对路径、盘符、反斜杠、`..`、`./`。 |
| `commit_sha` | `str` | 40 位小写十六进制。 |
| `language` | `str` | v1 固定 `python`。 |
| `review_id` | `str` | 与任务 `review_id` 一致。 |
| `rules` | `ReviewRules` | 只读规则对象。 |
| `trace_id` | `str \| None` | 可选追踪 ID。 |

`WorkerDispatch` 只包含 `task: AgentTask` 与 `runtime: WorkerRuntime`，不包含完整 Graph State、环境变量、密钥或父级上下文。

### 2.3 `WorkerEvidence`、`WorkerTiming`、`AgentExecution`

`WorkerEvidence`：

- `agent_name`
- `static_analysis: Mapping[str, Any]`
- `test_report: Mapping[str, Any] | None`
- `usage: UsageSummary`
- `warnings: tuple[str, ...]`

`WorkerTiming`：

- `agent_name`
- `task_id`
- `started_at`
- `finished_at`
- `duration_seconds`
- `status`：仅 `completed` / `partial` / `failed`

`AgentExecution`：

- `task: AgentTask`（终态任务）
- `result: AgentResult`
- `evidence: WorkerEvidence`
- `timing: WorkerTiming`

`AgentRunOutput` 为子类 `_run` 的返回值，仅承载 `result` 与 `evidence`；BaseAgent 补充任务终态、timing 与最终 `AgentExecution`。

所有证据字段在构造时递归冻结为 `MappingProxyType` / `tuple`；`ArtifactData.resolve()` 返回副本，后续 Reviewer 或报告生成器不能通过返回值修改原始证据。

### 2.4 `ArtifactData`

字段：

- `static_analysis: Mapping[str, Any]`
- `test_report: Mapping[str, Any]`

能力：

- `resolve(pointer)`：只解析内存对象，不读取磁盘文件。
- 支持 `static_analysis.json` / `test_report.json` 前缀。
- 支持空 fragment（根对象）与 JSON Pointer 转义 `~1`、`~0`。
- 数组索引拒绝负数、非数字、越界及前导零。
- 未知文件、缺少 `#`、fragment 不以 `/` 开头、缺少键、穿越非容器值均抛出 `ArtifactPointerError`。
- `static_analysis_dict()` / `test_report_dict()` 返回深拷贝。
- 顶层与嵌套映射均为只读；非 JSON 值、非有限浮点数在构造时拒绝。

示例指针：

```text
static_analysis.json#/agents/security/tools/bandit/findings/0
test_report.json#/coverage
```

这直接对应审计问题 A：Final Reviewer 的 V5 将在 Stage 2.4 使用同一内存 `ArtifactData` 校验，而不是读取尚未写盘的文件。

### 2.5 Protocols

- `CompletionLike`：`content: str`、`finish_reason: str | None`、`usage: Mapping[str, int] | None`。
- `LLMClientProtocol`：与现有 `OpenAICompatibleClient.complete()` 结构兼容，支持测试 Fake 注入；`llm_support` 不创建客户端、不导入 `langchain-openai`。

`llm_support` 额外提供：

- `PromptProjection`
- `JsonCompletion`
- `UsageAccumulator`
- `load_agent_prompt`、`build_prompt_projection`、`build_user_prompt`、`parse_json_object`、`validate_json_fields`、`request_json`

---

## 3. BaseAgent 生命周期与异常处理

统一接口：

```python
async def execute(dispatch: WorkerDispatch) -> AgentExecution
```

子类实现：

```python
async def _run(dispatch: WorkerDispatch) -> AgentRunOutput
```

### 3.1 输入合同

`execute()` 在进入生命周期前校验：

- `dispatch` 必须是 `WorkerDispatch`。
- `task.agent_name == self.agent_name`。
- `task.task_type == self.task_type`。
- `task.review_id == runtime.review_id`。
- `task.max_retries == 0`（Stage 2 不重试）。
- `task.status` 仅允许 `pending` / `running`。

输入合同失败直接抛出 `AgentContractError`，不伪造执行结果；这是调用方编排错误，不是 Worker 运行失败。

### 3.2 生命周期

1. 构造 `running` 任务：使用 `AgentTask.model_validate()` 而不是绕过校验的 `model_copy(update=...)`。
2. 调用 `_run()`。
3. 校验 `AgentRunOutput`、`AgentResult`、每个 `Finding` 与 `WorkerEvidence`。
4. 成功结果：
   - `completed` / `partial` → 任务 `completed`。
   - `failed` → 任务 `failed`，并写入脱敏后的 `last_error`。
5. 普通异常：
   - 转换为合法 `AgentResult(status="failed")`。
   - `error.error_type` 为 `agent_execution_error` 或 `agent_contract_error`。
   - `score = None`、`findings = []`、`retryable = False`。
   - 任务 `failed`，`WorkerTiming.status = "failed"`。
   - 证据为最小 `WorkerEvidence`，仅含安全 warning。
6. `BaseException`（如 `KeyboardInterrupt`、`asyncio.CancelledError`）不捕获，不被伪装成 failed 结果。
7. 不执行重试、退避或 `failed -> pending` 迁移。
8. `execution_time` 由 BaseAgent 计时覆盖，子类不能伪造。
9. 不读取完整 Graph State，不写仓库，不执行命令，不隐式创建真实 LLM 客户端。

### 3.3 结果合同校验

BaseAgent 强制检查：

- `task_id`、`parent_task_id`、`review_id`、`agent_name`、`commit_sha` 与任务/运行时一致。
- `failed` 结果必须 `score=None`、无 findings、有 error。
- `error.retryable` 必须为 `False`（Stage 2 不重试）。
- Finding 的 `agent_name` 与结果一致。
- Finding `verification_status` 必须为 `unverified`；Agent 不能自证 `verified` 或 `rejected`。
- metadata 必须可 JSON 序列化。

### 3.4 脱敏

成功与失败路径均对以下文本执行：

- 现有 `services.redaction.redact_sensitive_text()`。
- 工作区绝对路径替换为 `<workspace>`。
- 用户 home 路径替换为 `<home>`。
- 临时目录替换为 `<temp>`。
- summary 限 4000 字符；错误 message 限 2000 字符；Finding 的 title/description/evidence/recommendation 按 Schema 长度限制处理。
- 不把绝对工作区路径、密钥、token 或密码写入 `AgentResult` / `last_error`。
- 失败结果不读取完整 `input_data`。

---

## 4. Prompt 安全投影策略

`build_prompt_projection(dispatch, ...)` 的设计：

- 不把完整 `AgentTask.input_data` 放入投影。
- 仅包含 `agent_name`、`task_id`、`task_type`、`review_id`、`commit_sha`、`language`、受限的任务描述、`allowed_files`、源码、工具输出、规则子集和 warning。
- `source_files` 未提供时，只按 `runtime.allowed_files` 读取；路径必须位于工作区内，越界或符号链接逃逸报错。
- 提供映射时，只接受 `allowed_files` 中的路径；未知/绝对路径直接报错。
- 单文件最多 6000 字符；最多 20 个文件；工具输出最多 10 项、每项最多 4000 字符；user prompt 最多 30000 字符。
- 源码和工具输出先取代仓库相对路径，再脱敏，再替换工作区/home 路径与明显的绝对路径。
- 空源码/空工具输出允许，但超限拒绝或截断并留下 warning。
- `build_user_prompt()` 使用 JSON 序列化并附带 `PROMPT_INJECTION_NOTICE`，明确仓库内容是待分析不可信数据。
- 四个 `prompts/*.md` 均包含职责边界、类别、证据来源、不可信输入/提示注入防护、结构化 JSON 输出要求。
- Performance Prompt 明确“静态分析推断不是 Benchmark 实测”。
- Testing Prompt 明确“测试数量、失败数、覆盖率只能来自真实工具结果”。

### JSON 解析与 usage

`parse_json_object()`：

- 输入必须是非空字符串且不超过 64000 字符。
- 支持单层 ` ```json ` / ` ``` ` 围栏，拒绝其他围栏或前后额外文本。
- 顶层必须是 JSON 对象。
- 拒绝 NaN / Infinity、非法 JSON、超深嵌套。
- `validate_json_fields()` 严格检查缺失字段和未知字段。

`UsageAccumulator` / `request_json()`：

- `request_json()` 只接受注入的客户端，不创建客户端、不访问网络。
- 客户端异常记为失败调用，不产生 usage。
- 只有客户端返回 `prompt_tokens` 与 `completion_tokens` 时才累加真实 token。
- 没有 usage 或只有 `total_tokens` 时，不虚构输入/输出 token。
- 本阶段测试全部使用 `FakeLLMClient`，没有真实 LLM 调用。

---

## 5. 规则配置与校验结果

`config/review_rules.yaml` 实际值：

| 项目 | 值 |
|---|---|
| weights | security 0.35、quality 0.25、performance 0.20、testing 0.20 |
| deductions | critical 25、high 15、medium 5、low 2、info 0 |
| verdict | approve_min_score 80；request_changes_below 60 |
| testing | min_coverage_percent 80 |
| complexity | high_rank `D`；very_high_rank `E` |
| severity mapping | bandit HIGH/MEDIUM/LOW → high/medium/low；radon A-F；testing 三类；ruff error/warning/fatal |

加载器行为：

- 使用 `yaml.safe_load`，UTF-8 读取。
- 根映射必须有且仅有 `schema_version`、`weights`、`deductions`、`verdict`、`testing`、`complexity`、`severity_mapping`。
- 四个维度权重必须齐全、`0 < w <= 1`、总和在 `1e-6` 容差内为 1；不合法直接抛 `ReviewRulesError`，不静默归一化。
- 扣分等级必须齐全、非负整数。
- 结论阈值为 0–100，且 `request_changes_below <= approve_min_score`。
- 覆盖率阈值 0–100。
- 复杂度只允许 A–F 且 high/very_high 不同。
- 必需 severity mapping 工具：`bandit`、`radon`、`testing`；映射值只允许 info/low/medium/high/critical。
- 不在代码中硬编码 B107/B608 为 critical；Bandit 映射没有规则 ID 键，严重级别只能来自工具原始级别与配置映射。
- 规则对象使用 frozen dataclass + `MappingProxyType`，嵌套映射只读；`to_dict()` 返回独立拷贝。
- 浮点容差只用于判断，不修改配置值。

---

## 6. 测试命令与真实结果

测试环境：

- Python 3.12.16
- pytest 9.2.0
- PyYAML 6.0.3
- 未安装 `pytest-asyncio`；异步用例统一用 `asyncio.run()`。

Windows 默认代码页读取含中文注释的 `pytest.ini` 会触发 GBK 解码错误；本会话通过 `PYTHONUTF8=1` 运行。命令示例（Bash 语法）：

```bash
PYTHONUTF8=1 python -m pytest \
  tests/unit/test_agent_base.py \
  tests/unit/test_stage2_contracts.py \
  tests/unit/test_review_rules.py \
  tests/unit/test_llm_support.py -v
```

### 6.1 Stage 2.1 专项测试

```text
collected 208 items
208 passed in 2.94s
```

分类：

| 测试文件 | 数量 | 结果 |
|---|---:|---|
| `tests/unit/test_agent_base.py` | 28 | 全部通过 |
| `tests/unit/test_stage2_contracts.py` | 58 | 全部通过 |
| `tests/unit/test_review_rules.py` | 58 | 全部通过 |
| `tests/unit/test_llm_support.py` | 64 | 全部通过 |

### 6.2 全量单元测试

```text
1028 passed, 4 skipped, 3 warnings in 15.11s
```

### 6.3 全量测试

```text
1039 passed, 8 skipped, 3 warnings in 33.28s
```

### 6.4 失败项

Stage 2.1 专项测试与全量测试：**0 failure / 0 error**。

### 6.5 Lint

```text
ruff check src/code_review/agents config/review_rules.py \
  tests/stage2_helpers.py tests/unit/test_agent_base.py \
  tests/unit/test_stage2_contracts.py tests/unit/test_review_rules.py \
  tests/unit/test_llm_support.py
All checks passed!
```

### 6.6 警告说明

全量测试的 3 条 warning 均为既有环境/测试警告：

- FastAPI/Starlette 对 httpx testclient 的弃用提示。
- 两个 Windows junction 测试的读取线程 UTF-8 解码 warning（既有 Stage 1 测试，非本阶段代码新增失败）。

### 6.7 提交前复跑与导入路径修正

提交前复跑发现 Stage 2.1 的四个测试/辅助文件使用了 `from src.code_review...`，而实现内部使用 `from code_review...`，形成两个模块命名空间，导致 `WorkerDispatch` 与 `AgentTask` 的 `isinstance` 校验失败（25 条失败）。已统一改为 `from code_review...`，并重新执行：

- Stage 2.1 专项：**208 passed**
- `pytest tests/unit -q`：**1028 passed, 4 skipped**
- `pytest -q`：**1039 passed, 8 skipped**

该修正仅涉及测试导入路径，不改变业务实现。

---

## 7. Stage 1 回归情况

| 指标 | Stage 1 基线（本阶段前记录） | Stage 2.1 后 | 变化 |
|---|---:|---:|---:|
| 单元测试 passed | 820 | 1028 | +208 |
| 单元测试 skipped | 4 | 4 | 0 |
| 全量测试 passed | 831 | 1039 | +208 |
| 全量测试 skipped | 8 | 8 | 0 |

结论：

- 既有 Stage 1 测试无回归。
- 新增 208 条测试全部通过。
- 既有 4/8 条 skip 未变化。
- 没有修改 Stage 1 工具、报告生成器、聚合器、Fixture 或 ReviewService。

---

## 8. 依赖变化

`environment.yml` diff 只有一行：

```diff
       - coverage==7.17.2
+      - pyyaml==6.0.3
```

- 实际环境已安装 PyYAML 6.0.3。
- 未执行 `git add`、`git commit`、依赖安装、环境重建。
- 未修改 `environment.lock.yml`。
- 未安装或导入 LangGraph、langchain-core、langsmith、langchain-openai、Redis、ARQ、MCP、A2A、Streamlit、OpenTelemetry、LangSmith、PostgreSQL/SQLAlchemy。
- `src/code_review/agents` 与新增测试中无上述库的 import。

---

## 9. 安全与范围检查

| 检查项 | 结果 |
|---|---|
| 冻结 Schema 未修改 | PASS |
| 五份核心文档未修改 | PASS |
| `environment.lock.yml` 未修改 | PASS |
| 未修改 Stage 1 报告生成器/聚合器/Fixture | PASS |
| 未实现具体专业 Agent | PASS |
| 未实现 Manager/Final Reviewer | PASS |
| 未创建 `graph/` | PASS |
| 未安装 LangGraph 或其他禁止依赖 | PASS |
| 未修改 ReviewService | PASS |
| 未执行真实 LLM 网络调用 | PASS |
| 未执行外部仓库代码 | PASS |
| Agent Finding 保持 `unverified` | PASS |
| 未把完整 `input_data` 送入 Prompt | PASS |
| 未在报告中写入密钥/token/主机绝对路径 | PASS |
| 未执行 Git 写操作 | PASS |

`git status` 中仍存在本阶段开始前已有的已删除/未跟踪文件（Stage 1 报告迁移、Stage 2 计划文档等）；本阶段未清理、覆盖或提交这些文件。

---

## 10. 已知限制与风险

1. **`CLAUDE.md` 已更新（审计 G-2 关闭）**：2026-11-12 按负责人要求更新，已反映阶段 1 完成、Stage 2.1 完成、Stage 2.2 尚未开始、测试基线 1028 unit / 1039 full、`PYTHONUTF8=1` 命令、当前依赖与目录状态。
2. **LLM 冒烟测试未执行**：按负责人 2026-11-12 裁定，真实 LLM 冒烟测试与 Fake 冒烟测试均留待 Stage 2.2–2.4；本阶段单元测试继续使用 Fake/Mock 作为测试替身，不发起真实网络调用。
3. **无具体 Agent/Manager**：Prompt 文件与合同已就绪，但 `SecurityAgent` 等未实现；Stage 2.2 才创建。
4. **无 V5 证据校验**：`ArtifactData.resolve()` 已实现，但 Final Reviewer 的 V5 校验和“内存/落盘一致性”测试属于 Stage 2.4。
5. **BaseAgent 未实现超时**：Stage 2.3 的图节点/调度层负责超时与并发；本阶段只做生命周期与异常隔离。
6. **Prompt 投影的文件选择由调用方提供**：Stage 2.2 Manager 必须提供受控 `allowed_files`；尚未做全仓库自动选择。
7. **Windows 下 pytest 需 UTF-8**：默认 GBK 读取 `pytest.ini` 失败，需设置 `PYTHONUTF8=1` 或使用 UTF-8 终端；这不是本阶段引入的代码问题，但会影响命令可复现性。
8. **既有 warning**：FastAPI/Starlette 弃用提示与 Windows junction 测试线程 warning 仍存在；无 failure/error。

---

## 11. 验收结论

**PASS**

已满足：

- Stage 2.1 规定的内部 DTO/Protocol；
- BaseAgent 生命周期、异常转换、合同校验与脱敏；
- 四个专业 Prompt 文件；
- 严格规则 YAML 加载与校验；
- 安全 LLM Prompt 投影、JSON 解析与真实 usage 汇总；
- Fake Agent/Fake LLM 测试设施；
- 208 条专项测试全部通过；
- Stage 1 既有测试零回归；
- 依赖声明与安全边界检查通过。

负责人裁定（2026-11-12）：

- `CLAUDE.md` 已更新，审计 G-2 关闭；
- 真实与 Fake LLM 冒烟测试统一留待 Stage 2.2–2.4；
- 继续遵守 Stage 2.2 前不安装 LangGraph、不开始 Manager/专业 Agent 实现的边界。

---

## 12. 是否进入 Stage 2.2

**Stage 2.1 已于 2026-11-12 获负责人验收；Stage 2.2 尚未启动，需负责人另行确认后进入。**

Stage 2.2 的前置条件是：

- 接受本阶段 208 条测试与 Stage 1 零回归证据；
- `CLAUDE.md` 已更新至 Stage 2.1 基线；
- 保持 `environment.lock.yml` 不变；
- 明确 `allowed_files` 与 `WorkerRuntime` 的 Manager 构造策略；
- 不在 Stage 2.2 引入 LangGraph，不修改冻结 Schema/五份核心文档；
- 真实与 Fake LLM 冒烟测试按负责人裁定留待 Stage 2.2–2.4，不在 Stage 2.2 强制启动真实网络调用。

本阶段到此停止，未执行 Stage 2.2。

---

## 13. 负责人裁定与 Git 整理（2026-11-12）

负责人对 Stage 2.1 交付提出并确认以下处理：

1. **更新 `CLAUDE.md`**：已完成；当前阶段、测试基线、依赖、目录、文档地图与工作规则均已同步至 Stage 2.1。
2. **LLM 冒烟测试**：真实 LLM 冒烟测试与 Fake 冒烟测试均不在 Stage 2.1 执行，统一留待 Stage 2.2–2.4；单元测试中的 Fake/Mock 仅作为测试替身保留。
3. **Git 整理**：将阶段 0/1 报告归档到 `reports/stage0/`、`reports/stage1/`，纳入 Stage 2.1 验收报告、Agent 基础设施、Prompt、规则与测试；使用显式路径提交，排除 `reports/stage1-<timestamp>/` 真实第三方产物，并为其增加忽略规则。未使用 `git add -A` / `git add .`。

上述整理不改变本报告 §1–§9 的实现与测试证据。
