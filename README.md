# Multi-Agent Code Review System

输入一个 GitHub 仓库 URL，由 Manager Agent 规划任务，Security / Quality / Performance / Testing
四个专业 Agent 并行审查，最终由 Final Reviewer 完成证据核验、去重、评分并生成结构化审查报告。

> 当前进度：**阶段 2（多 Agent 代码审查）**。Stage 2.1～2.6 已完成，
> Stage 2.6 全链路验收证据待人工审核。默认评审路径使用确定性工具、
> 不调用真实 LLM；真实 LLM 通过 `--real-llm` 显式启用，O-1 成本语义
> 已由 `config/llm_pricing.yaml` 的模型价格表解决。

## 技术栈（阶段 2）

- Python 3.12 + Conda（环境名 `multi-agent-review`）
- FastAPI / Uvicorn（受控同步入口）
- Pydantic + pydantic-settings + python-dotenv
- Pytest + HTTPX + structlog
- Ruff / Bandit / Radon / Coverage.py（静态分析与可信 Fixture 覆盖率）
- LangGraph 1.2.19（7 节点并行工作流；被动带入 langchain-core / langsmith，
  未启用 tracing）

阶段 3 以后按规划再引入 Redis/ARQ、PostgreSQL、MCP、A2A、OpenTelemetry 等，
阶段 2 不提前安装或实现。

## 环境创建

```bash
conda env create -f environment.yml
conda activate multi-agent-review
python --version
```

如果环境已存在，可直接激活；重建时使用：

```bash
conda env remove -n multi-agent-review
conda env create -f environment.yml
```

配置通过环境变量或 `.env` 读取，模板见 `.env.example`。不要提交真实密钥。

## 运行测试

```bash
pytest tests/unit -v
pytest tests/integration -q -m "not real_network and not llm_smoke"

# 真实 GitHub Clone（需要网络）
RUN_REAL_NETWORK=1 pytest tests/integration -q -m real_network

# 真实模型冒烟（需要 .env 中配置 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL）
RUN_LLM_SMOKE=1 pytest tests/integration/test_llm_smoke.py -q -s
```

阶段 2 要求阶段 0/1 回归与新增测试全部通过；常规单元测试不联网、不调用真实 LLM。
Stage 2 E2E 使用真实 Ruff/Bandit/Radon/Pytest/Coverage 与自有 Fixture。真实网络与
真实模型测试默认不运行，必须显式设置环境变量。可信 Fixture 之外的仓库不会在宿主机
执行测试。

## CLI 与 API

CLI 是主要执行入口；CLI 与 FastAPI 都只调用 `ReviewService`。由于当前未提供
`pyproject.toml` / 可编辑安装，从仓库根目录运行 CLI 需要把 `src` 加入模块搜索路径：

```powershell
$env:PYTHONPATH = "src"
conda run -n multi-agent-review python -m code_review.cli review https://github.com/pallets/itsdangerous --branch main
```

可选参数：`--commit-sha <40 位 SHA>`、`--output-dir <目录>`、`--json`、`--real-llm`。
输出目录默认读取 `REVIEW_OUTPUT_ROOT`（缺省 `reports`），每次审查生成：

```
reports/<review_id>/
├── metadata.json
├── static_analysis.json
├── test_report.json
├── report.json
└── report.md
```

Stage 2（默认）生成五件产物；显式 `multi_agent=False` 时保留阶段 1 四件产物。
FastAPI 入口为 `code_review.api.app:app`，同步 `POST /api/reviews` 只接受
`repository_url`、`branch`、`commit_sha`，单进程单并发槽位，忙碌时返回 429。

### 真实 LLM（显式可选）

默认不调用真实 LLM。显式传入 `--real-llm` 时，CLI 要求配置
`LLM_PROVIDER=openai_compatible`、`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`，
且 `config/llm_pricing.yaml` 中存在该模型 ID 的精确价格条目。Security / Quality /
Performance 三个 Agent 会执行受限的语义补充；TestingAgent 始终只投影真实工具结果。

真实调用返回的 `usage.prompt_tokens` 与 `usage.completion_tokens` 会经价格表换算为
`report.json.cost_summary`。任一调用缺少 usage、模型缺少价格条目，或报告中的 token
与 usage 不一致时，报告生成会失败，不会伪造 0 成本。`LLM_PRICING_PATH` 可覆盖价格表
路径。真实模型调用默认排除在常规测试与验收之外，需要负责人单独批准。

## 安全边界

- 外部 GitHub 仓库只做静态分析，测试状态固定为 `not_executed`。
- 仅两个白名单 Fixture（`tests/fixtures/trusted_repo/`、
  `tests/fixtures/stage2_sample_repo/`）可在宿主机执行 Pytest / Coverage；
  不接受任意 URL 提权，不自动安装依赖，不执行安装脚本。
- 仓库内容视为不可信数据；报告与 LLM 输入不包含 `.env`、密钥、令牌或宿主机路径。
- Stage 2 的 Finding 由 Security/Quality/Performance/Testing Agent 产生，
  必须经 Final Reviewer 的 V1～V7 证据校验后才能标记 `verified`；Agent 不得自行
  标记 `verified`。

## 已知限制

- Stage 2 仍为单进程同步执行；FastAPI 入口仅用于本地受控演示与接口测试，不适合
  承载长时间或高并发审查。
- 外部 GitHub 仓库只做静态分析，测试与覆盖率状态固定为 `not_executed`；
  不自动安装依赖，不执行 `setup.py`、`build.py` 或任何安装/构建脚本。
- 默认评审路径不调用真实 LLM；`--real-llm` 需显式启用，并要求完整 LLM 配置与
  `config/llm_pricing.yaml` 中的精确价格条目。真实调用缺少 usage 或价格时报告生成
  失败，不会写入伪造的 0 成本；真实 LLM 冒烟仍需负责人单独批准。
- 四个维度均无有效评分时，`overall_score` 为 `null`、报告状态为 `partial`；
  Markdown/CLI 显示一位小数，`report.json` 保留精确值。
- Windows 宿主机默认不允许创建符号链接，5 条符号链接相关测试会跳过；这些跳过
  不影响其他平台的验收结论。
- 产物中的主机路径、工作区路径与密钥样式文本已脱敏；工具 stdout/stderr 仍可能包含
  被截断的代码片段，报告使用前应按组织的数据分级要求处理。

## 当前目录

```
config/settings.py              配置读取（pydantic-settings）
config/review_rules.yaml        评分权重、扣分、阈值与严重级别映射
config/llm_pricing.yaml         真实 LLM 的精确模型价格表（O-1）
config/llm_pricing.py           价格表严格加载与成本估算
src/code_review/schemas/        AgentTask / Finding / AgentResult / ReviewReport
src/code_review/tools/          仓库获取、扫描、Ruff/Bandit/Radon、测试执行、Fixture 构建
src/code_review/agents/         Manager、四个专业 Agent、Final Reviewer、证据校验与评分
src/code_review/graph/          LangGraph 7 节点并行工作流
src/code_review/prompts/        四个专业 Agent Prompt
src/code_review/services/       聚合、证据校验、LLM 分析、统一 ReviewService
src/code_review/reporting/      Stage 1 四件 / Stage 2 五件产物生成与 Markdown 渲染
src/code_review/cli.py          命令行入口
src/code_review/api/            FastAPI 受控同步入口
tests/unit/                     单元测试（Mock / Fake，不联网）
tests/integration/              集成测试（可信 Fixture 可受控执行）
tests/fixtures/                 两个白名单可信 Fixture（含哈希清单）
docs/                           需求、架构、工作流、数据合同、验收标准
reports/                        本地审查产物与验收记录
```

## 文档

- [需求](docs/requirements.md)
- [架构](docs/architecture.md)
- [工作流](docs/workflow.md)
- [数据合同](docs/task_contracts.md)
- [验收标准](docs/acceptance.md)

## 阶段路线

| 阶段 | 目标 |
| --- | --- |
| 0 | 工程初始化与需求冻结 |
| 1 | 单 Agent 工程基础：仓库获取、解析、静态分析、报告 |
| 2 | LangGraph Supervisor-Worker 多 Agent 编排（当前，等待 Stage 2.6 验收） |
| 3 | SubAgent 分层编排与任务生命周期 |
| 4 | Redis + ARQ 异步任务与失败恢复 |
| 5 | MCP 工具接入与权限隔离 |
| 6 | A2A 跨服务协作 |
| 7 | 可观测性、产品化与完整部署 |

每个阶段必须通过 `docs/acceptance.md` 中的验收标准后才能进入下一阶段。
