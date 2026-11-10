# Stage 1.5 测试证据：Finding 聚合与 LLM 辅助分析

- 执行日期：2026-11-10
- 执行环境：Windows 11、Python 3.12.16、Conda 环境 `multi-agent-review`
- 解释器：`D:/python/Anaconda/envs/multi-agent-review/python.exe`
- 代码状态：**Stage 1.5 已验收；提交记录见 Git 历史**（2026-11-10）
- 阶段目标：AC-1-13；覆盖 Finding 映射、工具结果聚合、去重、证据管理、LLM 辅助分析、Prompt Injection 防护、模型调用失败处理
- 本轮修订：按 2026-11-10 人工审核意见，将 `docs/acceptance.md` §4.7 的 LLM 输出上限由 2,000 上调到 5,000 tokens；实现 Finding 分块调用（15～20 条/次）、跨块汇总与 ID 对账；修复 Ruff `SIM117` 分类。最终裁定（2026-11-10）：主 Provider 为 SiliconFlow `deepseek-ai/DeepSeek-V3`，`llm_timeout_seconds` 保持 60 秒，`llm_max_output_tokens` 默认 8,000；Stage 1.5 验收通过并提交。

## 1. 本阶段完成的功能

1. 把 Ruff / Bandit / Radon 的 `ToolFinding` 映射为合同 `Finding`。
2. 把 Pytest 真实执行摘要映射为 `test_failure` Finding（仅 `executed` 且 `failed > 0`）。
3. 按 `docs/workflow.md` §8.4 实现确定性去重与 `merged_from`、工具证据合并。
4. 实现代码证据校验：仓库相对 POSIX 路径、允许分析文件集合、行号范围、片段唯一匹配、邻近行号调整。
5. 实现敏感文本脱敏：密钥、令牌、密码赋值、Bearer Token、私钥块、URL 凭据。
6. 实现 OpenAI 兼容 LLM 客户端（使用已安装的 `httpx`，未新增依赖）：超时、HTTP 错误、重定向拒绝、响应大小上限、usage 白名单。
7. 实现非 Agent 的 `LLMAnalyzer`：只解释已有工具发现或补充有代码位置的语义问题；模型提案必须通过确定性证据校验。
8. **新增 Finding 分块调用**：每块 15 条（可配置 1～20），跨块汇总提案、语义 ID、用量与计数器；50 条提案上限按整次审查计算；任一块失败时采用 all-or-nothing 语义，保留全部确定性工具结果，不混入部分模型结论。
9. 不合规提案进入 `llm_analysis.rejected[]` 对应结果；真实工具证据只从关联 Finding 复制，模型不能创建 `ToolEvidence`。
10. 模型未配置、超时、失败、输出非法时保留确定性工具结果，不抛出到调用方。
11. Prompt Injection 防护：仓库内容作为不可信数据、定界标记中和、输入长度预算、敏感文件排除、输出脱敏。
12. **修复 Ruff 规则分类**：只有 `S` 后接数字的规则才按 Bandit 规则映射；`SIM117` 等 `SIM*` 规则归为 `style_violation` / `low`。

## 2. 修改与新增文件

### 2.1 新增运行代码

| 文件 | 说明 |
|---|---|
| `src/code_review/services/__init__.py` | 服务层导出 |
| `src/code_review/services/redaction.py` | 敏感文本脱敏 |
| `src/code_review/services/evidence_validator.py` | 代码位置与片段确定性校验 |
| `src/code_review/services/finding_aggregator.py` | 工具结果聚合、合同映射、去重；本轮修复 Ruff `SIM*` 分类 |
| `src/code_review/services/llm_client.py` | OpenAI 兼容客户端 |
| `src/code_review/services/llm_analyzer.py` | LLM 辅助分析、提案校验、拒绝记录；本轮实现分块调用 |

### 2.2 新增测试

| 文件 | 覆盖内容 |
|---|---|
| `tests/unit/test_redaction.py` | 各类敏感值脱敏、URL 凭据、截断、非字符串输入 |
| `tests/unit/test_evidence_validator.py` | 路径/行号/片段校验、邻近调整、歧义、敏感文件、大小限制、配置错误 |
| `tests/unit/test_finding_aggregator.py` | Ruff/Bandit/Radon 映射、测试失败映射、MI 聚合、A 级跳过、去重、统计、脱敏、确定性、`SIM117` 回归 |
| `tests/unit/test_llm_client.py` | 请求结构、超时、HTTP 错误、重定向、非法 JSON、响应上限、usage 清洗、配置校验 |
| `tests/unit/test_llm_analyzer.py` | 未配置/失败/超时/预算、解释、语义补充、关联证据、拒绝规则、提案上限、注入标记、敏感文件、ID 对账；本轮新增分块、全局 ID、全局提案上限、单块失败、跨块去重、剩余预算提示测试 |
| `tests/integration/test_stage1_5_pipeline.py` | 真实 Ruff/Bandit/Radon + 真实样例仓库 + Fake LLM；模型失败保留工具结果 |

### 2.3 修改的既有文件

| 文件 | 修改 | 原因 |
|---|---|---|
| `config/settings.py` | `llm_max_output_tokens` 默认值 2,000 → 5,000 → 8,000（最终裁定）；新增 `llm_max_findings_per_call=15`（1～20） | 落实 `docs/acceptance.md` §4.7 v1.3 基线 |
| `.env.example` | `LLM_MAX_OUTPUT_TOKENS=8000`；新增 `LLM_MAX_FINDINGS_PER_CALL=15` | 与新配置项保持一致 |
| `docs/acceptance.md` | 文档版本 v1.1 → v1.2 → v1.3；§4.7 输出上限 2,000 → 5,000 → 8,000（每次调用）；新增分块上限 20 条（默认 15 条）与分块/失败语义约束；确定主 Provider 为 SiliconFlow `deepseek-ai/DeepSeek-V3`、超时 60 秒；§4.11 增加 v1.2/v1.3 变更记录 | 人工审核批准的基线修订 |
| `tests/unit/test_settings_stage1.py` | 默认值断言更新为 8,000；新增分块配置边界测试 | 与新基线一致 |
| `tests/unit/test_finding_aggregator.py` | 导入根从 `src.code_review` 改为 `code_review`；新增 `SIM117` 回归 | 避免测试与生产模块产生两个不同的 Pydantic 类；修复分类缺陷 |
| `tests/unit/test_llm_analyzer.py` | 导入根从 `src.code_review` 改为 `code_review`；新增 6 条分块测试；更新配置断言 | 同上 |
| `tests/unit/test_test_runner.py` | 1 行导入路径：`src.code_review.schemas.report` → `code_review.schemas.report` | **Stage 1.4 遗留测试问题**：`test_runner.py` 使用顶层 `code_review`，测试合约类型从 `src.code_review` 导入，导致两个不同的 `TestSummary` 类；该用例在提交 `939a5a2` 上单独运行即失败。仅修测试导入，不改生产代码与合同。 |

未修改：`docs/task_contracts.md`、`src/code_review/schemas/` 三个核心 Schema、`environment.yml`、`agents/ graph/ tools/` 结构。

`.env` 为本地文件，未纳入版本控制；本轮将主 Provider 切换为 SiliconFlow，备用 Provider 注释保留 DeepSeek 官方配置。报告与测试输出均不包含 API Key。

## 3. 核心设计决策

1. **所有阶段 1 Finding 统一为 `Stage1Analyzer` + `unverified`**；不创建 `AgentTask` 体系，不做 Final Reviewer 核验。
2. **工具 Finding 的严重级别保守映射**：Bandit 使用原始 HIGH/MEDIUM/LOW；Radon B→low、C→medium、D/E/F→high；Ruff F/B/C90→medium，E9/数字型 `S*`→high，其余→low。不产生工具来源的 `critical`。
3. **Radon A 级不生成 Finding**；低可维护性（MI B/C）按项目汇总为一个无行号 Finding，避免伪造行号；原始工具结果仍保留。
4. **去重键**：已定位 Finding 使用“类别分组 + 文件 + 行号范围重叠”；无位置 Finding 使用“类别 + 工具来源集合”。合并保留最高严重级别、最高置信度描述、工具证据并集与 `merged_from`。
5. **证据校验是模型提案的唯一准入控制**：模型提供的路径、行号、代码片段必须在工作区真实文件中通过校验；只允许在 ±3 行内唯一匹配时修正行号。
6. **模型不能创造工具证据**：独立语义 Finding 使用 A 类代码证据；关联到确定性 Finding 时只复制其真实 `tool_evidence`，且要求位置重叠。
7. **模型解释单独记录**：`tool_explanation` 不修改工具 Finding，进入 `LLMAnalysisResult.explanations`；Stage 1.6 将其写入 `llm_analysis`。
8. **无确定性 Finding 时跳过模型调用**：阶段 1.5 的 LLM 分析以工具发现为上下文，不做无上下文的整仓语义扫描。
9. **输入预算确定性收缩**：先删除片段，再从低优先级 Finding 开始删除；仍无法满足最小请求时状态为 `skipped`，不调用模型。
10. **模型失败不阻断审查**：`not_configured` / `timeout` / `failed` / `skipped` 均返回原确定性 Finding 列表。
11. **分块调用采用 all-or-nothing**：任一块超时、请求失败、响应超限或 JSON 不可解析时，丢弃该次审查的全部模型结果（包括已成功块），返回确定性工具结果，状态为 `timeout` / `failed`。这样避免把部分块的解释与未分析块混在同一份结果中。
12. **全局提案编号与语义 ID**：各块提案按全局 0 起始索引编号；语义 Finding ID 由全局计数器生成（`LLM-0001` 起），跨块去重后统一通过 `_reconcile_final_ids` 对账。
13. **50 条提案上限按整次审查计算**：不是每块 50 条。分块时每块提示词只告知“剩余可用提案数”，块大小取 `min(15, 剩余提案数)`；达到上限后停止继续调用。未进入提示词的确定性 Finding 仍保留在最终结果中，只是没有 LLM 解释。
14. **输出上限 8,000 tokens（最终裁定）按每次调用计算**；`usage`、`input_chars`、`context_finding_count`、`context_snippet_count` 在分块间累加，`input_truncated` / `output_truncated` 取逻辑或。

## 4. 关键实现说明

- `Finding.finding_id` 由工具名与原始输出指针生成（如 `BANDIT-0000`、`RUFF-0001`、`RADON-MI-0001`、`PYTEST-0001`）；LLM 语义补充固定为 `LLM-0001` 起，模型不能指定 ID。
- `ToolEvidence.raw_output_ref` 使用 `static_analysis.json#/tools/<tool>/findings/<index>` 与 `static_analysis.json#/tests/pytest`，为 Stage 1.6 JSON 产物预留可追溯指针。
- 证据校验拒绝绝对路径、反斜杠、盘符、`..`、`.`、非规范路径、符号链接/junction、工作区外路径、超过 2 MiB 的文件与非 Python 可解码文件。
- 允许分析集合会再次剔除 `FileFilterPolicy.is_sensitive_path()` 命中的敏感文件；即使调用方误传 `.env`，LLM 上下文也不会读取。
- Prompt 中仓库数据放在 `<repository_data>` 定界内；数据内的 `repository_data/system/developer/assistant/instructions` 标签会被替换为 `[marker removed]`，避免伪造定界。
- LLM 客户端不跟随重定向，避免 `Authorization` 被转发；错误信息不包含响应正文或 API Key；响应上限默认 2 MiB。
- `_MAX_CONTEXT_FINDINGS = 200`：分块前最多收集 200 条确定性 Finding 上下文；目标仓库 90 条全部在范围内。
- `_is_bandit_ruff_rule(rule)`：仅当规则为 `S` + 数字时视为 Bandit；`SIM117` 不再误判。修复后整仓扫描中 `RUFF-0015`（`SIM117`）为 `style_violation` / `low`。
- 阶段 1.5 仍只产出内存中的类型化结果；四件产物与 `ReviewService` 属于 Stage 1.6。

## 5. 测试命令

```powershell
# Stage 1.5 新增单元测试
D:/python/Anaconda/envs/multi-agent-review/python.exe -m pytest tests/unit/test_redaction.py tests/unit/test_evidence_validator.py tests/unit/test_finding_aggregator.py tests/unit/test_llm_client.py tests/unit/test_llm_analyzer.py -q

# 全量单元测试（含阶段 0 / 1.1～1.4 回归）
D:/python/Anaconda/envs/multi-agent-review/python.exe -m pytest tests/unit -q

# 阶段 0 Schema 回归
D:/python/Anaconda/envs/multi-agent-review/python.exe -m pytest tests/unit/test_task_schema.py tests/unit/test_result_schema.py tests/unit/test_report_schema.py -q

# 非联网、非真实 LLM 全量测试
D:/python/Anaconda/envs/multi-agent-review/python.exe -m pytest tests -q -m "not real_network and not llm_smoke"

# Stage 1.5 集成测试（真实工具 + Fake LLM）
D:/python/Anaconda/envs/multi-agent-review/python.exe -m pytest tests/integration/test_stage1_5_pipeline.py -q

# 变更文件 Ruff
D:/python/Anaconda/envs/multi-agent-review/python.exe -m ruff check config/settings.py src/code_review/services/finding_aggregator.py src/code_review/services/llm_analyzer.py tests/unit/test_settings_stage1.py tests/unit/test_finding_aggregator.py tests/unit/test_llm_analyzer.py

# 安全探针
git check-ignore .env
D:/python/Anaconda/envs/multi-agent-review/python.exe -c "import importlib.metadata as m; n={(d.metadata['Name'] or '').lower().replace('_','-') for d in m.distributions()}; exact={'langgraph','redis','arq','sqlalchemy','asyncpg','mcp','a2a-sdk','langsmith','streamlit'}; pre=('langchain','langgraph-','psycopg'); print('FORBIDDEN:', sorted(x for x in n if x in exact or x.startswith(pre) or (x.startswith('opentelemetry') and x!='opentelemetry-api'))); print('PASSIVE-ALLOWED:', sorted(x for x in n if x=='opentelemetry-api'))"
```

## 6. 实际测试结果

| 命令 | 结果 |
|---|---|
| Stage 1.5 新增单元测试 | **122 passed** |
| 全量单元测试 | **745 passed, 4 skipped** |
| 阶段 0 Schema 回归 | **204 passed** |
| 非联网全量测试（单元 + 集成） | **753 passed, 4 skipped, 3 deselected** |
| Stage 1.5 集成测试 | **2 passed** |
| 变更文件 Ruff | **All checks passed** |
| `git check-ignore .env` | `.env` 被忽略 |
| 禁止依赖探针 | `FORBIDDEN: []`；`PASSIVE-ALLOWED: ['opentelemetry-api']` |

4 个 skip 均为 Windows 主机不允许创建符号链接导致的既有平台跳过：

```text
tests\unit\test_repository_inspector.py:207: symlinks are not available on this platform
tests\unit\test_trusted_fixture.py:224: symbolic links are not permitted on this host
tests\unit\test_trusted_fixture.py:236: symbolic links are not permitted on this host
tests\unit\test_workspace_snapshot.py:102: symbolic links are not permitted on this host
```

阶段 0 的 204 条测试无 skip、无 failure、无 error。

## 7. 尚未完成 / 已知限制

1. **SiliconFlow 主 Provider 的模型可用性不一致**：R1 在账号配置检查后连最小调用都返回 HTTP 503（198 ms），两次整仓复测分别在 0.29 秒和 0.74 秒收到 503；V3.2 最小调用成功（1.73 秒），但 180 秒整仓扫描首块在 180.19 秒超时；Qwen3.5-35B-A3B 最小调用成功（11.14 秒），整仓前 3 块成功（162.25 / 40.28 / 41.73 秒），第 4 块在 180.08 秒超时，all-or-nothing 丢弃全部模型结果；`deepseek-ai/DeepSeek-V3` 最小调用成功（2.08 秒），180 秒整仓扫描完成（4 次调用 44.75 / 30.01 / 25.23 / 16.02 秒，总 116.34 秒，49 条接受、1 条拒绝、47 条解释、2 条语义 Finding，最终 92 条）。**V3 是本次矩阵中唯一完成整仓扫描的 SiliconFlow 模型，最慢单次 44.75 秒低于 60 秒基线，但仍需在 60 秒基线下单独复测确认**；R1/V3.2/Qwen 均未完成。
2. **DeepSeek 备用模型选择**：`deepseek-flash` 是推理模型，15 条 Finding × 5,000 tokens 时 completion 全部用于 reasoning，`finish_reason=length`、内容非 JSON，扫描失败。`deepseek-chat` 在同样 15 条 × 5,000 tokens 下成功（7.7 秒、15 条提案、无截断），并完成了整仓扫描。`.env` 的备用注释已改为 `deepseek-chat`，以便后续切换；这是本地配置，不影响仓库。
3. **50 条提案上限导致部分 Finding 没有 LLM 解释**：目标仓库有 90 条确定性 Finding，按整次审查 50 条提案上限，实际发送 4 块共 50 条上下文（15+15+15+5），接受 50 条解释；其余 40 条保留为确定性 Finding，但没有 LLM 解释。这是契约行为，不是失败。若要覆盖全部 90 条，需要人工批准提高 `llm_max_finding_proposals`（或明确改为按块计数）。
4. **`llm_analysis` 尚未落盘**：当前是 `LLMAnalysisResult` 内存结果；`metadata.json`、`static_analysis.json`、`test_report.json`、`report.md` 与 `ReviewService` 属于 Stage 1.6。
5. **无确定性 Finding 时不做 LLM 整仓扫描**：`LLMAnalyzer` 返回 `skipped`，这是阶段 1.5 的上下文边界，不是模型调用失败。
6. **`tool_explanation` 不新增 Finding、不重复校验位置**：它只解释已经通过工具与合同验证的 Finding；不会创建新的代码位置或工具证据。
7. **仓库整体 Ruff 存在 10 条既有告警**：位于冻结的 Stage 0 `schemas/task.py`、`schemas/result.py`、`schemas/report.py` 与旧测试 `test_report_schema.py`（UP037 / UP017 / FURB167）。为遵守“不得修改冻结核心 Schema”，本次未处理；Stage 1.5 变更文件 Ruff 全通过。
8. **测试导入根**：本轮把 `test_finding_aggregator.py` 与 `test_llm_analyzer.py` 的导入根统一为顶层 `code_review`，避免测试对象与生产对象成为两个不同的 Pydantic 类。其他既有测试仍保留 `src.code_review` 导入；它们当前不混合两类对象，因此全量通过，但属于后续可统一清理的测试卫生问题。
9. **Stage 1.4 回归修复**：`tests/unit/test_test_runner.py` 的导入路径修正属于前置测试修复；生产代码未变。需要在本次审核中确认是否纳入 Stage 1.5 提交范围。

## 8. 与 `docs/acceptance.md` 的对应关系

| 验收项 | 状态 | 证据 |
|---|---|---|
| AC-1-13：LLM 只解释/补充；模型 Finding 满足证据合同；不合规丢弃并记录 | **PASS** | 合法语义补充生成 `LLM-*` 且 `unverified`；伪造路径/行号/片段、非法类别/严重级别、无证据、越界置信度、不同位置关联全部进入 `rejected`；工具解释单独记录；集成测试覆盖真实工具输出 + Fake LLM；分块后语义 ID 全局唯一并对账 |
| AC-1-05：敏感文件不进入 LLM 上下文 | **PASS（Stage 1.5 范围）** | `test_sensitive_file_is_excluded_from_prompt`；集成样例 `.env` 内容不进入提示词；`CodeEvidenceValidator` 再次剔除敏感路径 |
| AC-1-15：四件产物 | **NOT STARTED** | Stage 1.6 |
| TC-1-01：阶段 0 回归 | **PASS** | 204 passed |
| TC-1-02：单元测试不联网、不调用真实 LLM | **PASS（Stage 1.5 新增范围）** | 122 条新增单元测试；`FakeClient` / `ScriptedClient` / `httpx.MockTransport`；无 API Key |
| TC-1-03：可信样例仓库完整集成 | **PARTIAL** | Stage 1.5 只覆盖工具聚合 + LLM 提案；完整 AC-1-01～15 链路在 Stage 1.7 |
| TC-1-06：真实模型冒烟 | **PASS（DeepSeek `deepseek-chat` 备用）/ BLOCKED（SiliconFlow R1 主 Provider）** | 备用 Provider 完成真实整仓扫描：4 次调用、50 提案/50 接受/0 拒绝/0 丢弃、26.26 秒；主 Provider 在 60 秒超时或 HTTP 500，无法完成分析规模请求；不得把主 Provider 记为 PASS |

## 9. 架构偏离

未发现需要暂停实现的架构偏离：

- LLM 代码位于 `services/llm_analyzer.py`，符合 `docs/architecture.md` §7.1.1 / §8.1。
- 未实现 `agents/`、`graph/`、Final Reviewer、LangGraph 或任何多 Agent 编排。
- 未修改阶段 0 核心 Schema、数据契约、依赖清单或目录层级。
- 未新增依赖；LLM 客户端复用 `httpx`。
- 所有阶段 1 Finding 保持 `unverified`，LLM 不合格提案不进入正式 Finding 列表。

## 10. 是否可以进入下一子阶段

- **Stage 1.5 代码目标 AC-1-13：单元/集成证据 PASS；最终配置整仓扫描 PASS（SiliconFlow `deepseek-ai/DeepSeek-V3`、60 秒超时、8,000 tokens）**。
- **人工审核结论（2026-11-10）：Stage 1.5 验收通过并提交。** Provider/模型与输出上限已由负责人裁定；50 条提案上限保持整次审查语义，未修改。
- **Stage 1 整体结论：Stage 1.5 范围内 PASS**；Stage 1.6/1.7 尚未完成。
- 本报告随 Stage 1.5 提交；尚未进入 Stage 1.6。

## 11. 真实模型冒烟与整仓扫描（2026-11-10 补充）

### 11.1 Provider 配置与冒烟

**主 Provider：SiliconFlow**

最终裁定：阶段 1 主 Provider 为 SiliconFlow，模型为 `deepseek-ai/DeepSeek-V3`，请求超时 60 秒，输出上限 8,000 tokens。以下 R1 / V3.2 / Qwen 记录为选型诊断过程。

- Endpoint：`https://api.siliconflow.cn/v1`；初始请求模型：`deepseek-ai/DeepSeek-R1`。
- 最小真实调用：`finish_reason=stop`，usage `{prompt_tokens: 22, completion_tokens: 42, total_tokens: 64}`，耗时 14,559 ms；内容为 `{"ok": true}`（带 Markdown 围栏，`_extract_json_object` 可处理）。
- 分析规模请求：3 / 5 / 8 条 Finding 均在 60 秒超时；将诊断超时放宽到 180 秒后，3 条 Finding 在 54.79 秒收到 HTTP 500。历史探测中 15 条超时，20/30 条返回 503/500；503 原始响应为 `{"code":50508,"message":"System is too busy now. Please try again later.","data":null}`。
- **180 秒整仓扫描复测（2026-11-10）**：诊断脚本仅覆盖本次调用的超时（`DIAGNOSTIC_TIMEOUT_SECONDS=180`，仓库基线仍为 60 秒）。第 1 块 15 条 Finding、17,900 输入字符，在 **181.00 秒超时**，未收到响应；`LLM_STATUS=timeout`、`LLM_CALLS=1`，90 条确定性 Finding 完整保留。放宽到 180 秒未改变分析规模请求不可用的事实。
- **账号配置检查后复测（2026-11-10）**：两次整仓扫描均在 Provider 入口被拒——第 1 次 0.29 秒、第 2 次 0.74 秒返回 HTTP 503；R1 最小调用也在 198 ms 返回 HTTP 503，未收到响应与 usage。90 条确定性 Finding 完整保留。该结果表明 R1 当前在 Provider 侧完全不可用，与超时设置或请求规模无关。
- 结论：主 Provider 在 60 秒与 180 秒超时下均无法完成分析规模请求，账号配置检查后 R1 进一步表现为入口 503，整仓扫描 **BLOCKED**。

**SiliconFlow DeepSeek-V3.2 复测（2026-11-10）**

- 最小真实调用：成功，1.67 秒，`finish_reason=stop`，usage `{prompt_tokens: 21, completion_tokens: 5, total_tokens: 26}`；响应 `model` 标记为 `deepseek-ai/DeepSeek-V3.2`，模型 ID 与 Key 可访问。
- 180 秒整仓扫描：第 1 块 15 条 Finding、17,900 输入字符，在 **180.13 秒超时**，未收到响应；`LLM_STATUS=timeout`、`LLM_CALLS=1`，90 条确定性 Finding 完整保留。
- 结论：V3.2 在最小调用上可用，但同等分析规模请求仍未在 180 秒内返回，整仓扫描 **BLOCKED**。

**SiliconFlow 模型矩阵复测（2026-11-10，180 秒诊断）**

| 模型 | 最小调用 | 180 秒整仓扫描 | 关键细节 |
|---|---|---|---|
| `deepseek-ai/DeepSeek-V3.2` | **OK**，1.73 秒 | **timeout**：第 1 块 180.19 秒超时 | 15 条 Finding、17,900 输入字符；无响应、无 usage；90 条确定性 Finding 保留 |
| `deepseek-ai/DeepSeek-V3` | **OK**，2.08 秒 | **completed**：4 次调用 44.75 / 30.01 / 25.23 / 16.02 秒，总 116.34 秒 | 50 提案、49 接受、1 拒绝（`unsupported or missing category`）、47 条解释、2 条语义 Finding；最终 92 条；最慢单次 44.75 秒 |
| `Qwen/Qwen3.5-35B-A3B` | **OK**，11.14 秒（466 completion tokens） | **timeout**：第 4 块 180.08 秒超时 | 前 3 块成功（162.25 / 40.28 / 41.73 秒），all-or-nothing 丢弃全部模型结果；最终 90 条确定性 Finding、0 条解释 |

结论：**`deepseek-ai/DeepSeek-V3` 是本次矩阵中唯一在 180 秒诊断下完成整仓扫描的 SiliconFlow 模型**，且最慢单次调用 44.75 秒低于冻结的 60 秒基线；仍需在 60 秒基线下单独复测确认。V3.2 与 Qwen 均未完成，R1 当前入口 503。

**备用 Provider：DeepSeek 官方**

- Endpoint：`https://api.deepseek.com`；请求模型：`deepseek-chat`（备用注释中已注明原因）。
- 15 条 Finding × 5,000 tokens：`completed`，7.7 秒，usage `{prompt_tokens: 4,995, completion_tokens: 1,228, total_tokens: 6,223}`，15 条提案全部接受，无截断。
- 对照：`deepseek-flash` 在 15 条 × 5,000 tokens 下 `failed`，completion 5,000，`finish_reason=length`，内容非 JSON；该模型是推理模型，reasoning 与正式输出共享额度。

密钥仅写入本地 `.env`；`git check-ignore .env` 通过，未写入本报告、日志、模型提示词或任何结果对象。

### 11.2 目标仓库确定性扫描

| 项目 | 结果 |
|---|---|
| 仓库 | `pallets/itsdangerous`，`main` |
| Commit SHA | `672971d66a2ef9f85151e53283113f33d642dabd` |
| Python 文件 | 15（`inventory.is_partial=False`） |
| Ruff | 17 条原始 Finding，exit 1 |
| Bandit | 68 条原始 Finding，exit 1 |
| Radon | 155 条原始 Finding，exit 0 |
| 聚合 | 240 原始 → 91 映射 → 90 最终（1 条重复合并，149 条 Radon A 级跳过） |
| 严重级别 | high 2 / medium 3 / low 85 |
| 类别 | security_issue 59、style_violation 14、hardcoded_secret 8、high_complexity 6、code_smell 2、weak_crypto 1 |
| 测试执行 | `not_executed`（外部仓库，未执行任何脚本或测试） |
| `SIM117` | `RUFF-0015` 为 `style_violation` / `low`（修复后） |
| Finding 来源 | 全部 `Stage1Analyzer`，全部 `unverified` |

高严重级别中，`BANDIT-0000`（`src/itsdangerous/signer.py:45`，Bandit B324，弱 SHA1）和 `RUFF-0007`（`src/itsdangerous/timed.py:114`，Ruff S110 + Bandit B110，`try`-`except`-`pass`）是真实工具发现；`RUFF-0015`（`tests/test_itsdangerous/test_timed.py:81`，Ruff SIM117）修复后已降为 `style_violation` / `low`。8 条 Bandit B106 测试口令均已在 `evidence` 中显示为 `[REDACTED]`，未泄露原值。

### 11.3 分块整仓扫描结果（历史诊断：DeepSeek `deepseek-chat` 备用，5,000 tokens）

> 本节记录 5,000 tokens 配置下的历史诊断结果；最终验收配置（V3、60 秒、8,000 tokens）见 §11.7。

| 指标 | 结果 |
|---|---|
| 模型（请求 / 响应标记） | `deepseek-chat` / `deepseek-flash`（服务端路由标签，行为为非推理） |
| 输出上限 | 5,000 tokens / 次调用 |
| 分块大小 | 15 条 / 次 |
| 提案上限 | 50（整次审查） |
| 调用 | 4 / 4 `completed` |
| 输入上下文 | 50 条 Finding，50 个片段（15+15+15+5） |
| 提案 | 50（全部 `tool_explanation`） |
| 接受 / 拒绝 / 丢弃 | 50 / 0 / 0 |
| 工具发现解释 | 50 |
| 新增语义 Finding | 0 |
| Token | 14,636 prompt + 4,036 completion = 18,672 |
| 输入字符 | 53,027（累计） |
| 截断 | 输入 `false`；输出 `false` |
| 总耗时 | 26.26 秒 |
| 最终 Finding | 90（确定性结果完整保留） |
| 全部 `unverified` | `true` |

说明：50 条提案上限按整次审查计算，因此 90 条确定性 Finding 中只有 50 条进入 LLM 上下文并获得解释；其余 40 条保留在最终结果中，但没有 LLM 解释。这不是模型失败，而是 `docs/acceptance.md` §4.7 的契约行为。

### 11.4 分块实现验证（单元测试）

新增测试覆盖：

- 35 条 Finding 按 10 条/块拆为 `[10, 10, 10, 5]`，所有 Finding ID 均出现在提示词中，usage 正确累加，输出截断按块取逻辑或。
- 两块各生成一条同位置语义提案，全局 ID 为 `LLM-0001` / `LLM-0002`，跨块去重后 `LLM-0002` 合并进 `LLM-0001`，接受记录正确对账。
- 全局提案上限 3 跨两块生效：4 条提案中 3 条接受、1 条丢弃并记录 `proposal limit exceeded`。
- 第二块超时：第一块已接受的解释被全部丢弃，状态 `TIMEOUT`，确定性 Finding 完整保留，原因 `chunk 2: model request timed out`。
- 剩余预算提示：第二块提示词只允许 2 条提案，块大小同步收缩为 2，0 条丢弃。

### 11.5 发现的缺陷与处理状态

1. **单次调用规模与 2,000 token 上限不兼容** → **已修复**：`docs/acceptance.md` v1.2 将每次调用输出上限调整为 5,000 tokens；`LLMAnalyzer` 实现 15～20 条/次分块、跨块汇总、全局 ID/提案编号/用量与 all-or-nothing 失败语义。
2. **Ruff `SIM117` 分类错误** → **已修复**：新增 `_is_bandit_ruff_rule()`，仅 `S` + 数字视为 Bandit；`SIM117` 现为 `style_violation` / `low`；回归测试覆盖 `SIM117`、`S603`、`S110`。
3. **Provider/模型选择 → 已由负责人裁定**：最终采用 SiliconFlow `deepseek-ai/DeepSeek-V3`，`llm_timeout_seconds` 保持 60 秒，`llm_max_output_tokens` 默认 8,000。最终整仓扫描 5/5 调用成功（30.65 / 30.08 / 25.46 / 21.93 / 15.34 秒），`LLM_STATUS=completed`。历史诊断中 R1 入口 503、V3.2 首块 180.19 秒超时、Qwen3.5-35B-A3B 第 4 块 180.08 秒超时；DeepSeek 官方 `deepseek-chat` 仍可作为备用。
4. **50 条提案上限与“整仓解释覆盖”的取舍**：当前只解释 50 条。最终扫描中 50 条提案、46 条接受、4 条拒绝（`unsupported or missing category`）、45 条解释、1 条语义 Finding；其余确定性 Finding 保留但无 LLM 解释。如要求覆盖 90 条，需要人工批准提高 `llm_max_finding_proposals` 或改为按块计数。
5. **测试导入根不一致**：本轮已修复两个 Stage 1.5 测试文件的导入根；其他测试仍使用 `src.code_review`，建议后续统一，但不影响当前通过。

### 11.6 当前状态

- Stage 1.5 单元/集成测试：**PASS**（122 条新增单元测试；全量 753 passed / 4 skipped / 3 deselected）。
- 最终真实整仓扫描：**PASS**（SiliconFlow `deepseek-ai/DeepSeek-V3`、60 秒超时、8,000 tokens；5/5 调用成功，最慢 30.65 秒）。
- TC-1-06：**PASS**（最终配置）。
- **Stage 1.5 已验收通过并提交**（2026-11-10）；尚未进入 Stage 1.6。

### 11.7 最终验收配置整仓扫描（2026-11-10）

| 指标 | 结果 |
|---|---|
| Provider / 模型 | SiliconFlow / `deepseek-ai/DeepSeek-V3` |
| 请求超时 | 60 秒（冻结基线不变） |
| 输出上限 | 8,000 tokens / 次调用 |
| 分块大小 / 提案上限 | 15 条 / 50 条（整次审查） |
| 仓库 | `pallets/itsdangerous`，commit `672971d66a2ef9f85151e53283113f33d642dabd` |
| 调用 | 5 / 5 `completed`：30.65 / 30.08 / 25.46 / 21.93 / 15.34 秒 |
| 输入上下文 | 64 条 Finding，64 个片段（15+15+15+15+4） |
| 提案 / 接受 / 拒绝 / 丢弃 | 50 / 46 / 4 / 0 |
| 拒绝原因 | `unsupported or missing category` × 4 |
| 解释 / 新增语义 Finding | 45 / 1 |
| Token | 18,366 prompt + 3,504 completion = 21,870 |
| 输入字符 | 66,869（累计；单次均低于 60,000） |
| 截断 | 输入 `false`；输出 `false` |
| LLM 耗时 | 123.78 秒 |
| 最终 Finding | 91（90 条确定性 + 1 条语义；全部 `Stage1Analyzer` / `unverified`） |
| 测试执行 | `not_executed`（外部仓库未执行任何脚本或测试） |

结论：最终验收配置在 60 秒冻结超时下完成整仓扫描，最慢单次调用 30.65 秒，未发生超时、输入/输出截断；`LLM_STATUS=completed`。
