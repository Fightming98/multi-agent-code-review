# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 仓库现状

这是 **Multi-Agent Code Review System** 的阶段 0（工程初始化与需求冻结）成果。阶段 0 已于 2026-11-09 通过正式验收，五份核心文档冻结为 v1.0；仓库仍**不含任何 Agent、LLM 调用、工作流或评审业务实现**。

- 已存在：`docs/*.md`（v1.0，已冻结）、`environment.yml`、`.env.example`、`.gitignore`、`README.md`、`config/settings.py`、`src/code_review/schemas/`、`tests/unit/`、`pytest.ini`
- 阶段 0 交付：四个核心 Pydantic Schema 与 204 条单元测试，全部通过（0 failure / error / skip / xfail）
- 尚未创建（阶段 1 及以后）：`agents/`、`graph/`、`tools/` 等目录，以及任何 Agent、LLM、LangGraph 实现
- Git：本地 `main` 分支；远程仓库 `Fightming98/multi-agent-code-review`（Public）。本次首次提交未创建 Git tag；`reports/` 下的验收报告按 `.gitignore` 不提交

阶段 0 已完成。进入阶段 1 及以后，必须先获得用户明确确认；未经确认不得增加依赖、创建后续阶段目录或实现业务逻辑。

阶段 0 未实现、当前仓库仍不存在的内容：

- Agent、LLM 调用、LangGraph、Supervisor-Worker、SubAgent、Announce、重试调度、并发控制
- LangChain、LangGraph、Redis、ARQ、PostgreSQL、SQLAlchemy、MCP SDK、A2A SDK、OpenTelemetry、LangSmith、Streamlit、Docker
- `agents/ graph/ tools/ mcp/ a2a/ orchestration/ workers/ observability/ storage/ reporting/ external_agents/`
- 真实仓库克隆、目标仓库测试/安装脚本执行、真实评审报告生成

阶段 0 基础依赖固定为 8 个：`fastapi uvicorn pydantic pydantic-settings python-dotenv pytest httpx structlog`。增加依赖需用户确认。

## 常用命令

```bash
# 环境（Conda，env 名固定为 multi-agent-review）
conda env create -f environment.yml
conda activate multi-agent-review
python --version   # 期望 3.12.x

# 手动安装基础依赖（与 environment.yml 一致）
python -m pip install fastapi uvicorn pydantic pydantic-settings python-dotenv pytest httpx structlog

# 测试（当前 204 条：零 failure / error / skip / xfail）
pytest tests/unit -v
pytest tests/unit/test_task_schema.py -v                      # 单个文件
pytest tests/unit/test_task_schema.py::test_name -v           # 单个用例
```

阶段 0 验收探针（均定义于 `docs/acceptance.md`）：

```bash
python -c "import fastapi, uvicorn, pydantic, pydantic_settings, dotenv, pytest, httpx, structlog; print('ok')"

# 禁止项探测：允许被动带入 opentelemetry-api，其余禁止项必须为空
python -c "import importlib.metadata as m; n={(d.metadata['Name'] or '').lower().replace('_','-') for d in m.distributions()}; exact={'langgraph','redis','arq','sqlalchemy','asyncpg','mcp','a2a-sdk','langsmith','streamlit'}; pre=('langchain','langgraph-','psycopg'); print('FORBIDDEN:', sorted(x for x in n if x in exact or x.startswith(pre) or (x.startswith('opentelemetry') and x!='opentelemetry-api'))); print('PASSIVE-ALLOWED:', sorted(x for x in n if x=='opentelemetry-api'))"

python -c "from config.settings import Settings; print(Settings())"
python -c "from code_review.schemas import AgentTask, AgentResult, Finding, ReviewReport; print('ok')"
git check-ignore .env
```

- 唯一允许新增的配置辅助文件是 `pytest.ini`（仅含 `pythonpath = src .`、`testpaths = tests`）；`config/` 位于包外，没有它上述 import 会失败。
- 阶段 0 不使用覆盖率工具（Coverage.py 未安装）；完整性靠规则 ID 追溯，检查脚本须恰好输出 `['FD-09', 'FD-10', 'ST-04', 'ST-06', 'ST-07']`；ST-05 由 `is_transition_allowed()` 与 `tests/unit/test_task_schema.py` 真实覆盖。
- 没有规定 lint / format / type-check 工具或配置；Ruff 仅作为**被评审仓库**的分析器出现。

## 架构大图

分层依赖方向（不得反向）：

```
schemas (仅 Pydantic/stdlib) → tools → agents → graph
orchestration → graph → ReviewService → api / CLI / workers
```

- `schemas/`：数据契约，不依赖任何业务模块。
- `tools/`：确定性的静态分析/扫描/测试执行，提供证据。
- `agents/`：角色定义与 LLM 推理（`base.py` + Manager/Security/Quality/Performance/Testing/Reviewer）；**agents 不得 import graph**。
- `graph/`：LangGraph 工作流编排（`state.py`、`nodes.py`、`edges.py`、`workflow.py`）。
- `orchestration/`：跨节点任务生命周期、事件、重试、并发，与 graph 分离。
- `ReviewService` 是唯一评审入口；CLI 是主要开发/验收入口，FastAPI 只是可选本地演示。CLI 与 API 不得各自重复一份评审逻辑。阶段 4 才引入 Redis + ARQ，HTTP 返回 202；此前单进程同步执行。

评审数据流：

```
提交请求 → 校验 URL → clone 并固定 40 位 commit SHA → Manager 生成任务计划
→ LangGraph Send 并行扇出 4 个 AgentTask → AgentResult 扇入
→ Final Reviewer（契约校验、证据校验、去重、维度打分、总体分/结论）
→ 先 JSON 后 Markdown 报告 → reports/<review_id>/
```

关键不变量：

- **确定性工具产出证据，LLM 只做解读**；Finding 必须能追溯到代码位置或工具输出。
- 被评审仓库是不可信内容：默认只在宿主机做静态分析；未沙箱化前，测试执行状态必须为 `not_executed`，绝不能执行不可信脚本。仓库内容（源码/README/issue/PR 描述）同样视为不可信数据，防提示注入。
- `.env`/密钥/token/主机路径不得写入日志、`input_data` 或送给模型。
- LLM Provider 必须可替换，经 `config/settings.py` 注入，禁止在 agent 内硬编码。
- 一致性顺序：先保存结果 → 再更新状态 → 最后发布事件。
- LangGraph 并行 worker 只返回自己的状态键（如 `{"security_result": ...}`）；`completed_tasks`/`failed_tasks` 等列表字段必须使用 `Annotated[list, operator.add]` reducer，否则 `InvalidUpdateError`。
- 单元测试不得联网、不得调用真实 LLM（用 Mock/Fake）。

## 数据契约

四个核心模型：`AgentTask`、`Finding`、`AgentResult`、`ReviewReport`。字段级权威定义在 `docs/task_contracts.md`，实现必须逐字段一致：

- 位置固定：`AgentTask`/`ErrorInfo` → `schemas/task.py`；`Finding`/`ToolEvidence`/`AgentResult` → `schemas/result.py`；`ReviewReport` 及子模型 → `schemas/report.py`。导入顺序 `task.py ← result.py ← report.py`。**没有** `schemas/finding.py`。
- 全部模型 `extra = "forbid"`、`schema_version = "1.0"`；错误信息必须能定位到字段。禁止为通过测试而放宽契约。
- 枚举小写下划线（`not_executed`、`request_changes` 的底层值），仅 `overall_verdict` 用大写 `APPROVE / COMMENT / REQUEST_CHANGES`；时间为带时区 UTC（ISO-8601 `Z`）。
- `Finding.file_path` 为 POSIX 风格仓库相对路径，禁止 `..`、反斜杠、盘符；`start_line ≤ end_line` 且为正。
- `agent_name` / `task_type` 故意保持 `str`，合法值由注册表约束（`SecurityAgent`/`security_review` 等），不要改成 `Literal` 或裸 `dict` 传递。
- `AgentTask.status` 仅 `pending/running/completed/failed/cancelled`；阶段 4 的 `QUEUED/RETRYING/...` 不得提前塞入。
- 评分权重：Security 35%、Quality 25%、Performance 20%、Testing 20%（可配置，但须来自 `review_rules.yaml`，不得硬编码）；报告存储的 `DimensionScore.weight` 始终是配置值，缺失维度只在综合分公式内部归一化。
- 任意维度（含外部 A2A Agent）的已核验 `critical` Finding 直接 `REQUEST_CHANGES`；外部结果放在 `external_agent_results`，不参与四个核心维度的加权评分。
- 四个维度均无有效评分时报告仍合法：`overall_score = null`、`report_status = partial`；无已核验 `critical` 为 `COMMENT`，有则为 `REQUEST_CHANGES`。

## 文档地图

| 文件 | 内容 |
|---|---|
| `docs/requirements.md` | FR/NFR、目标、阶段划分、安全边界 |
| `docs/architecture.md` | 九层架构、DR 决策、目录树、依赖方向 |
| `docs/workflow.md` | 流水线、并发、超时/重试、错误分类、去重、评分与结论 |
| `docs/task_contracts.md` | **数据契约权威来源**、规则 ID（TK/FD/ST/RS/RT/RP/JS） |
| `docs/acceptance.md` | AC-0-01…33、CK-1…7、可执行验收命令 |
| `项目总框架与实施计划V2.0.md` | 总体规划基线（阶段 0–7） |
| `Prompt/阶段0_Prompt.md` | 阶段 0 的可执行任务边界与交付步骤 |
| `Prompt/0.3阶段任务要求.md` | 阶段 0.3 Schema 重建与测试要求 |
| `Prompt/0.4阶段任务要求.md` | 阶段 0.4 文档冲突修复、合同统一与冻结要求 |
| `未来优化计划方案列表.md` | 未来优化 backlog，**不是任务清单** |
| `reports/phase_0_4_final_acceptance_report.md` | 阶段 0.4 最终验收报告（本地生成，按 `.gitignore` 不提交） |

## 已解决的文档冲突与仍需注意的事项

阶段 0.4 已解决 D-1～D-9：

- 全 null 报告语义统一为 RP-16：无已核验 `critical` → `COMMENT`，有 → `REQUEST_CHANGES`。
- `critical` 阻断范围统一为任意维度（含外部 A2A Agent），不再限定为“安全漏洞”。
- 权重存储与计算口径统一：报告存储配置值，仅综合分公式内部对有效维度归一化。
- 任务树最大深度为 2，父任务存在、无环、派生权限属于阶段 3；不新增 `task_depth` / `depth` 字段。
- ST-05 由 `is_transition_allowed()` 真实覆盖；AC-0-24 按实际阶段标注，AC-0-29 区分合法/非法/非模型示例。
- 阶段 0 明确交付 Pydantic Schema 与单元测试；不新增独立 `Evidence` 模型，全 null 报告合法。
- FastAPI 0.142+ 被动带入 `opentelemetry-api` 的问题已由 AC-0-05 区分“被动依赖/主动接入”解决。

仍需注意：

- 项目名 `multi-agent-code-review` 与 Conda 环境名/工作目录 `multi-agent-review` 不一致。
- 总体规划中的“七个阶段”措辞与实际阶段 0–7（八个）不一致；以实际阶段表为准。
- 最终目录树中的 `pyproject.toml`、`schemas/finding.py` 不属于阶段 0；`Finding` 固定在 `result.py`。
- `TaskEvent`、`TokenUsage`、A2A 状态映射是后续阶段预留内容，阶段 0 不实现。
- `reports/.gitkeep` 未创建，`reports/*` 仍被忽略（按用户确认的现有 `.gitignore`）；`docs/acceptance.md` §3.2 仍列出该占位文件，后续如需要应补齐。
- `environment.yml` 未固定 FastAPI 版本；当前验证版本为 0.110.2，重建环境前应确认版本。
- 本次首次提交未创建 Git tag；如正式验收要求 tag，需另行执行。

## 工作规则

- 文档与注释用中文，代码标识符/字段名用英文；v1 仅评审 Python。
- 不得覆盖已存在的文件/配置；改动前先读契约与验收标准。
- 不得伪造执行结果；验收报告必须如实写 PASS/FAIL/BLOCKED，失败就是失败。
- 如终端无法 `conda activate`，说明原因并给替代方案，不要修改系统配置。
- 提交前确认 `.env` 未被跟踪；不得提交密钥、token、主机路径或 `reports/` 下的本地报告。
- 阶段 0 已完成；未经用户明确确认，不进入阶段 1 或实现后续阶段业务逻辑。
- 未经用户确认，不推进到下一阶段，不增加依赖，不删除/重写规格文档。
