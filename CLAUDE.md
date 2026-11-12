# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 仓库现状

这是 **Multi-Agent Code Review System**。阶段 0（工程初始化与需求冻结）于 2026-11-09 验收；阶段 1（单 Agent 代码审查基础）于 2026-11-10 完成并提交（`65af76e`）；阶段 2.1（Agent 基础合同、BaseAgent、Prompt 与规则加载）于 2026-11-12 完成，等待负责人确认后进入 Stage 2.2。五份核心文档自阶段 1 基线修订后冻结：`acceptance.md`、`architecture.md`、`requirements.md`、`workflow.md` 为 v1.1，`task_contracts.md` 为 v1.0。

- 已存在：`docs/*.md`、`environment.yml`、`environment.lock.yml`、`.env.example`、`.gitignore`、`README.md`、`pytest.ini`、`config/settings.py`、`config/review_rules.py`、`config/review_rules.yaml`、`src/code_review/{schemas,tools,services,reporting,api}`、`src/code_review/agents/`（仅基础设施）、`src/code_review/prompts/`、`tests/unit/`、`tests/integration/`
- 阶段 0 交付：四个核心 Pydantic Schema 与 204 条单元测试
- 阶段 1 交付：仓库获取/SHA 固定/URL 校验、仓库扫描与文件过滤、Ruff/Bandit/Radon、可信 Fixture Pytest+Coverage、LLM 辅助分析、Finding 聚合、四件报告产物、CLI 与最小同步 FastAPI `POST /api/reviews`
- 阶段 2.1 交付：Agent 内部 DTO/Protocol、`BaseAgent`、安全 Prompt 投影与 JSON/usage 支持、四个专业 Prompt、`review_rules.yaml` 严格加载器、Fake Agent/Fake LLM 测试设施；**未实现任何具体专业 Agent、Manager、Final Reviewer 或 LangGraph**
- 尚未创建（Stage 2.2 及以后）：`graph/`、`orchestration/`、`workers/`、`observability/`、`storage/`、`mcp/`、`a2a/`、`external_agents/`，以及 Security/Quality/Performance/Testing Agent、Manager、Final Reviewer、`report.json`、LangGraph 工作流
- Git：本地 `main` 跟踪 `origin/main`（`Fightming98/multi-agent-code-review`，Public）。`reports/stage0/`、`reports/stage1/`、`reports/stage2_1_acceptance_report.md` 等验收/评审记录纳入版本控制；`reports/stage1-<timestamp>/` 这类真实第三方仓库产物含第三方代码片段与原始工具输出，保留本地并由 `.gitignore` 排除。`Prompt/*` 为本地提示词/裁定记录，不纳入版本控制

阶段 2 按 Stage 2.1 → 2.6 逐步实施：2.1 基础合同；2.2 Manager 与四个专业 Agent；2.3 LangGraph StateGraph 并行扇出/扇入；2.4 Final Reviewer、证据验证、去重与评分；2.5 ReviewService 集成、五件报告、CLI/API；2.6 Fixture、端到端、基线与最终验收。每个子阶段完成并提供测试证据后，经负责人确认再进入下一子阶段；未经确认不得提前安装依赖或实现后续阶段。

阶段 0 未实现、当前仓库仍不存在的内容：

- LangGraph 工作流、Supervisor-Worker、SubAgent、Announce、重试调度、并发控制
- LangGraph、LangChain、Redis、ARQ、PostgreSQL、SQLAlchemy、MCP SDK、A2A SDK、OpenTelemetry、LangSmith、Streamlit、Docker
- 真实多 Agent 评审、外部 A2A Agent、真实 `report.json`

依赖现状：阶段 0 基础依赖 8 个（`fastapi uvicorn pydantic pydantic-settings python-dotenv pytest httpx structlog`）；阶段 1 已固定 `ruff==0.17.4`、`bandit==1.9.4`、`radon==6.0.1`、`coverage==7.17.2`；Stage 2.1 新增 `pyyaml==6.0.3`。Stage 2 已批准仅新增 `langgraph`，且**只能在 Stage 2.3 安装门禁通过后安装**；当前环境未安装 LangGraph，也未安装 `langchain-openai`、`langsmith`、langchain-core 等。被动带入的 `langchain-core`/`langsmith` 可接受，但禁止直接 import、启用 tracing、读取 API Key 或联网上报。其余新增依赖仍需负责人确认。

## 常用命令

```bash
# 环境（Conda，env 名固定为 multi-agent-review）
conda env create -f environment.yml
conda activate multi-agent-review
python --version   # 期望 3.12.x

# Windows 下 pytest 需 UTF-8，否则读取含中文的 pytest.ini 会触发 GBK 解码错误
export PYTHONUTF8=1                # PowerShell: $env:PYTHONUTF8 = "1"

# 当前基线：单元 1028 passed, 4 skipped；全量 1039 passed, 8 skipped
pytest tests/unit -q
pytest -q

# Stage 2.1 专项（208 条）
pytest tests/unit/test_agent_base.py tests/unit/test_stage2_contracts.py \
       tests/unit/test_review_rules.py tests/unit/test_llm_support.py -q

# 单文件 / 单用例
pytest tests/unit/test_agent_base.py -v
pytest tests/unit/test_agent_base.py::test_name -v

# Lint（仅针对本次改动文件，不强制全仓）
ruff check src/code_review/agents config/review_rules.py tests/stage2_helpers.py \
           tests/unit/test_agent_base.py tests/unit/test_stage2_contracts.py \
           tests/unit/test_review_rules.py tests/unit/test_llm_support.py
```

阶段 0 验收探针（定义于 `docs/acceptance.md`，保留用于回归）：

```bash
python -c "import fastapi, uvicorn, pydantic, pydantic_settings, dotenv, pytest, httpx, structlog; print('ok')"

# 禁止项探测：允许被动带入 opentelemetry-api，其余禁止项必须为空
python -c "import importlib.metadata as m; n={(d.metadata['Name'] or '').lower().replace('_','-') for d in m.distributions()}; exact={'langgraph','redis','arq','sqlalchemy','asyncpg','mcp','a2a-sdk','langsmith','streamlit'}; pre=('langchain','langgraph-','psycopg'); print('FORBIDDEN:', sorted(x for x in n if x in exact or x.startswith(pre) or (x.startswith('opentelemetry') and x!='opentelemetry-api'))); print('PASSIVE-ALLOWED:', sorted(x for x in n if x=='opentelemetry-api'))"

python -c "from config.settings import Settings; print(Settings())"
python -c "from code_review.schemas import AgentTask, AgentResult, Finding, ReviewReport; print('ok')"
git check-ignore .env
```

- `pytest.ini` 只含 `pythonpath = src .` 与 `testpaths = tests`；`config/` 位于包外，没有它上述 import 会失败。
- 阶段 1 不使用覆盖率工具做自身测试；阶段 1 的 Coverage 仅用于**可信 Fixture** 的被评审仓库测试。
- 没有规定全仓 lint / format / type-check；Ruff 同时是被评审仓库的分析器。

## 架构大图

分层依赖方向（不得反向）：

```
schemas (仅 Pydantic/stdlib) → tools → agents → graph
orchestration → graph → ReviewService → api / CLI / workers
```

- `schemas/`：数据契约，不依赖任何业务模块。
- `tools/`：确定性的静态分析/扫描/测试执行，提供证据（Stage 1 已实现）。
- `agents/`：角色定义与 LLM 推理；**agents 不得 import graph**。当前仅有 `base.py`、`contracts.py`、`llm_support.py`、`__init__.py` 基础设施；Manager 与四个专业 Agent 在 Stage 2.2 实现。
- `graph/`：LangGraph 工作流编排（Stage 2.3）。
- `orchestration/`：跨节点任务生命周期、事件、重试、并发，与 graph 分离。
- `ReportService`/`ReviewService` 是唯一评审入口；CLI 与 FastAPI 共用同一 `ReviewService`。阶段 1 为单进程同步执行；阶段 4 才引入 Redis + ARQ 并返回 202。
- `services/`：`review_service.py`、`llm_client.py`、`llm_analyzer.py`、`redaction.py`、`evidence_validator.py`、`finding_aggregator.py`。
- `reporting/`：`artifact_models.py`（阶段 1 四件产物模型）、`report_generator.py`、`markdown_renderer.py`。
- `prompts/`：四个专业 Agent Prompt（security/quality/performance/testing），由 `llm_support.load_agent_prompt()` 加载。

评审数据流（Stage 2 目标）：

```
提交请求 → 校验 URL → clone 并固定 40 位 commit SHA → Manager 生成任务计划
→ LangGraph Send 并行扇出 4 个 AgentTask → AgentResult 扇入
→ Final Reviewer（契约校验、证据校验、去重、维度打分、总体分/结论）
→ 先 JSON 后 Markdown 报告 → reports/<review_id>/（五件产物）
```

Stage 1 为线性单 Agent 流程，只生成四件产物（`metadata.json`、`static_analysis.json`、`test_report.json`、`report.md`）；`report.json` 自 Stage 2 起生成。

关键不变量：

- **确定性工具产出证据，LLM 只做解读**；Finding 必须能追溯到代码位置或工具输出。
- 被评审仓库是不可信内容：默认只在宿主机做静态分析；外部仓库测试执行状态必须为 `not_executed`，绝不能执行不可信脚本。仓库内容（源码/README/issue/PR 描述）同样视为不可信数据，防提示注入。
- **阶段 1 可信 Fixture 受控例外**：仅 `tests/fixtures/trusted_repo/` 下由项目维护、经人工审查、固定版本或哈希的 Fixture 可在宿主机执行 Pytest/Coverage；不接受任意 GitHub URL + `--trusted` 提权，不自动安装依赖，不执行 `setup.py`/`build.py`/安装脚本；报告中必须区分可信 Fixture 与外部仓库数据。
- `.env`/密钥/token/主机路径不得写入日志、`input_data`、Prompt、结果或报告。
- LLM Provider 必须可替换，经 `config/settings.py` 注入，禁止在 agent 内硬编码；Stage 2.1 只定义 `LLMClientProtocol`，不创建真实客户端。
- 一致性顺序：先保存结果 → 再更新状态 → 最后发布事件。
- LangGraph 并行 worker 只返回自己的状态键（如 `{"security_result": ...}`）；`completed_tasks`/`failed_tasks` 等列表字段必须使用 `Annotated[list, operator.add]` reducer，否则 `InvalidUpdateError`。
- 单元测试不得联网、不得调用真实 LLM（用 Mock/Fake）。Stage 2.1 不执行真实或 Fake 的 LLM 冒烟测试；真实 LLM 冒烟统一留待 Stage 2.2–2.4。
- `BaseAgent` 只捕获 `Exception`（不捕获 `BaseException`），普通异常转换为合法的 failed `AgentResult`；Stage 2 不重试（`max_retries=0`），失败结果 `retryable=False`；不得把 Finding 标记为 `verified`。
- `UsageSummary` 是内部统计，不等同于冻结的 `CostSummary`；只有真实返回的 token usage 才能累加，禁止伪造 0 token / 0 成本。
- `ArtifactData` 是内存只读证据快照，支持稳定 JSON Pointer；Final Reviewer 必须校验内存对象，不得依赖尚未写盘的报告文件。
- Prompt 投影不得包含完整 `AgentTask.input_data`；只投影允许文件、受限工具输出、规则子集，并执行脱敏、大小限制与提示注入防护。
- 评分权重、扣分、阈值、严重级别映射必须来自 `config/review_rules.yaml`；加载器拒绝非法权重，不做静默归一化。

## 数据契约

四个核心模型：`AgentTask`、`Finding`、`AgentResult`、`ReviewReport`。字段级权威定义在 `docs/task_contracts.md`，实现必须逐字段一致：

- 位置固定：`AgentTask`/`ErrorInfo` → `schemas/task.py`；`Finding`/`ToolEvidence`/`AgentResult` → `schemas/result.py`；`ReviewReport` 及子模型 → `schemas/report.py`。导入顺序 `task.py ← result.py ← report.py`。**没有** `schemas/finding.py`。
- 全部模型 `extra = "forbid"`、`schema_version = "1.0"`；错误信息必须能定位到字段。禁止为通过测试而放宽契约。
- 枚举小写下划线（`not_executed`、`request_changes` 的底层值），仅 `overall_verdict` 用大写 `APPROVE / COMMENT / REQUEST_CHANGES`；时间为带时区 UTC（ISO-8601 `Z`）。
- `Finding.file_path` 为 POSIX 风格仓库相对路径，禁止 `..`、反斜杠、盘符；`start_line ≤ end_line` 且为正。项目级指标（如 `low_coverage`）可仅带工具证据，不得伪造文件/行号，且不能为 critical/high。
- `agent_name` / `task_type` 故意保持 `str`，合法值由注册表约束，不要改成 `Literal` 或裸 `dict` 传递。阶段 1 使用 `Stage1Analyzer`/`stage1_review`；Stage 2 专业 Agent 使用 `SecurityAgent`/`security_review` 等。
- 所有 Agent Finding 在 Final Reviewer 验证前必须保持 `verification_status="unverified"`；BaseAgent 与专业 Agent 不得标记 `verified`/`rejected`。LLM 不合格提案放 `llm_analysis.rejected[]`，不得混入正式 Finding。
- `AgentTask.status` 仅 `pending/running/completed/failed/cancelled`；阶段 4 的 `QUEUED/RETRYING/...` 不得提前塞入。
- `AgentResult.status` 仅 `completed/failed/partial`：completed 无 error；failed 必须有 error、`score=None`、无 findings；partial 必须有 error 且保留已完成证据。
- 评分权重：Security 35%、Quality 25%、Performance 20%、Testing 20%（来自 `review_rules.yaml`，不得硬编码）；报告存储的 `DimensionScore.weight` 始终是配置值，缺失维度只在综合分公式内部归一化。
- 扣分与阈值同样来自 `review_rules.yaml`：critical 25、high 15、medium 5、low 2、info 0；`approve_min_score=80`、`request_changes_below=60`、`min_coverage_percent=80`。
- 任意维度（含外部 A2A Agent）的已核验 `critical` Finding 直接 `REQUEST_CHANGES`；外部结果放在 `external_agent_results`，不参与四个核心维度的加权评分。
- 四个维度均无有效评分时报告仍合法：`overall_score = null`、`report_status = partial`；无已核验 `critical` 为 `COMMENT`，有则为 `REQUEST_CHANGES`。
- `report.json` 存储精确的 schema 要求值；Markdown/CLI 显示一位小数，不得为显示而修改冻结 Schema。
- Bandit 严重级别由工具原始级别经 `review_rules.yaml` 映射；不得预置 B107/B608 为 critical。Stage 2 的 AC-2-12 必须使用单独构造的已核验 critical Finding。

## 文档地图

| 文件 | 内容 |
|---|---|
| `docs/requirements.md` | FR/NFR、目标、阶段划分、安全边界 |
| `docs/architecture.md` | 九层架构、DR 决策、目录树、依赖方向 |
| `docs/workflow.md` | 流水线、并发、超时/重试、错误分类、去重、评分与结论 |
| `docs/task_contracts.md` | **数据契约权威来源**、规则 ID（TK/FD/ST/RS/RT/RP/JS） |
| `docs/acceptance.md` | AC-0-01…33、AC-1-01…15、AC-2-…、TC、可执行验收命令与阶段阈值 |
| `项目总框架与实施计划V2.0.md` | 总体规划基线（阶段 0–7） |
| `Stage2.1-2.6分阶段实施Promp.md` | Stage 2.1–2.6 分阶段执行提示词与验收要求 |
| `阶段2实施前架构审计与实施计划.md` | Stage 2 实施前审计、B-1/B-2 裁定、问题 A–D 与 D-3/4/5/7/11/12 |
| `Prompt/阶段0_Prompt.md` | 阶段 0 的可执行任务边界与交付步骤（本地，不提交） |
| `Prompt/0.3阶段任务要求.md` | 阶段 0.3 Schema 重建与测试要求（本地，不提交） |
| `Prompt/0.4阶段任务要求.md` | 阶段 0.4 文档冲突修复、合同统一与冻结要求（本地，不提交） |
| `Prompt/阶段1_Prompt.md` | 阶段 1 执行提示词（本地，不提交） |
| `Prompt/Stage1实施前人工决策.md` | 阶段 1 实施前裁定记录 Q1～Q13（本地，不提交） |
| `Prompt/阶段2_Prompt.md` | 阶段 2 原始实施提示词（本地，不提交） |
| `未来优化计划方案列表.md` | 未来优化 backlog，**不是任务清单** |
| `reports/stage0/` | 阶段 0 验收报告（纳入版本控制） |
| `reports/stage1/` | 阶段 1 各子阶段证据与验收报告（纳入版本控制） |
| `reports/stage2_1_acceptance_report.md` | Stage 2.1 验收报告（纳入版本控制） |
| `reports/stage1-<timestamp>/` | 真实第三方仓库评审产物（本地，不提交） |

## 已解决的文档冲突与仍需注意的事项

阶段 0.4 已解决 D-1～D-9：

- 全 null 报告语义统一为 RP-16：无已核验 `critical` → `COMMENT`，有 → `REQUEST_CHANGES`。
- `critical` 阻断范围统一为任意维度（含外部 A2A Agent），不再限定为“安全漏洞”。
- 权重存储与计算口径统一：报告存储配置值，仅综合分公式内部对有效维度归一化。
- 任务树最大深度为 2，父任务存在、无环、派生权限属于阶段 3；不新增 `task_depth` / `depth` 字段。
- ST-05 由 `is_transition_allowed()` 真实覆盖；AC-0-24 按实际阶段标注，AC-0-29 区分合法/非法/非模型示例。
- 阶段 0 明确交付 Pydantic Schema 与单元测试；不新增独立 `Evidence` 模型，全 null 报告合法。
- FastAPI 0.142+ 被动带入 `opentelemetry-api` 的问题已由 AC-0-05 区分“被动依赖/主动接入”解决。

Stage 2 已裁定：

- B-1：被动带入 `langchain-core`/`langsmith` 可接受，但禁止直接 import、启用 tracing、读取 API Key 或联网上报；Stage 2.3 安装 LangGraph 前必须重新确认。
- B-2：`report.json` 存储精确 schema 值，Markdown/CLI 显示一位小数，不修改冻结 Schema。
- 问题 A：Final Reviewer 校验内存 `ArtifactData` 与规范化证据，不读取尚未生成的报告文件。
- 问题 B：区分代码位置 Finding 与工具项目级 Finding；`low_coverage` 不得伪造文件/行号。
- 问题 C：不得预置 B107/B608 为 critical；严重级别由工具原始结果 + 配置映射决定。
- 问题 D：真实 LLM 调用不得伪造 0 `cost_summary`；`CostSummary` 无法表达未知成本时不修改 Schema，使用内部 `UsageSummary`。
- D-3：使用确定性的真实临时 Git 仓库 SHA；D-4：生产默认 Stage 2 行为，旧调用显式 `multi_agent=False`；D-5：默认 Fake/Mock，真实 LLM 冒烟独立（负责人 2026-11-12 裁定统一留待 Stage 2.2–2.4）；D-7：Stage 2.1 声明 PyYAML，保持 Stage 1 lock；D-11：工具成功 + LLM 失败 → `partial` 并保留工具证据；D-12：外部 Testing 未执行 → TestingAgent completed、Testing 分数 null、报告 partial。

仍需注意：

- 项目名 `multi-agent-code-review` 与 Conda 环境名/工作目录 `multi-agent-review` 不一致。
- 总体规划中的“七个阶段”措辞与实际阶段 0–7（八个）不一致；以实际阶段表为准。
- 最终目录树中的 `pyproject.toml`、`schemas/finding.py` 不属于当前阶段；`Finding` 固定在 `result.py`。
- `TaskEvent`、`TokenUsage`、A2A 状态映射是后续阶段预留内容。
- `reports/.gitkeep` 未创建；`reports/*` 未被整体忽略，验收记录纳入版本控制。
- `environment.yml` 未固定 FastAPI 版本；当前验证版本为 0.110.2，重建环境前应确认版本。
- 首次提交未创建 Git tag；如正式验收要求 tag，需另行执行。
- AC 编号以 `docs/acceptance.md` 原文为准；`Prompt/阶段1_Prompt.md` §14 的旧映射已修正，其他章节如与原文冲突以原文为准。
- 阶段 1 只生成四件产物；Stage 2 才生成含 `report.json` 的五件产物。
- 阶段 1 阈值记录在 `docs/acceptance.md` §4.7；可信 Fixture 规则见 §4.8；不得在业务代码中散落阈值。
- `services/llm_analyzer.py` 是阶段 1 非 Agent LLM 分析；Stage 2.2 起的专业 Agent 使用 `agents/` + `prompts/`。
- `environment.lock.yml` 是 Stage 1 Windows 环境快照，Stage 2 不得覆盖；依赖变更只改 `environment.yml`。
- 当前测试 3 条 warning 为既有 Starlette/httpx 弃用与 Windows junction 线程解码警告，无 failure/error。

## 工作规则

- 文档与注释用中文，代码标识符/字段名用英文；v1 仅评审 Python。
- 不得覆盖已存在的文件/配置；改动前先读契约与验收标准。
- 不得伪造执行结果；验收报告必须如实写 PASS/FAIL/BLOCKED，失败就是失败。
- 如终端无法 `conda activate`，说明原因并给替代方案，不要修改系统配置。
- 提交前确认 `.env` 未被跟踪；不得提交密钥、token、主机路径或 `reports/stage1-<timestamp>/` 下的真实第三方产物。验收/评审记录（`reports/stage0/`、`reports/stage1/`、`reports/stage2_1_acceptance_report.md`）可以提交。
- 提交使用**显式路径**；禁止 `git add -A` / `git add .`，避免把本地真实产物带入版本控制。
- 阶段 0、1 已完成；Stage 2.1 已完成并等待负责人确认；Stage 2.2 尚未开始。未经确认不推进下一子阶段、不增加依赖、不删除/重写冻结规格文档。
- 冻结文件：三个核心 Schema、五份核心文档、`report_generator.py`、`artifact_models.py`、`markdown_renderer.py`、`finding_aggregator.py`、`tests/fixtures/trusted_repo/`、`environment.lock.yml`。Stage 2.1 另要求不改三个 Schema 与上述报告/聚合文件。
- Stage 2.3 安装 LangGraph 前必须通过提示词中的安装门禁并获得负责人确认；不得安装 `langchain-openai`、`langsmith` 或引入 tracing/API Key/网络上报。
- Stage 2.1 裁定：真实与 Fake LLM 冒烟测试均不在本阶段执行，统一留待 Stage 2.2–2.4；单元测试继续使用 Fake/Mock 且不得联网。
- 阶段 1 的裁定记录现位于 `Prompt/Stage1实施前人工决策.md`（本地）；基线补充以 `docs/acceptance.md` §4.7～§4.11 与 `docs/architecture.md` §7.1.1/§8.1 为准。
