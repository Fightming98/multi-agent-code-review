# Multi-Agent Code Review System

输入一个 GitHub 仓库 URL，由 Manager Agent 规划任务，Security / Quality / Performance / Testing
四个专业 Agent 并行审查，最终由 Final Reviewer 完成证据核验、去重、评分并生成结构化审查报告。

> 当前进度：**阶段 1（单 Agent 工程基础）**。Stage 1.1～Stage 1.6 已实现，Stage 1.6
> 测试证据待人工验收；尚未进入 Stage 1.7 全链路验收。阶段 1 仍为单进程、非 Agent
> 流水线，不包含 LangGraph、多 Agent、Redis/ARQ 或 ReviewReport 四维评分。

## 技术栈（阶段 1）

- Python 3.12 + Conda（环境名 `multi-agent-review`）
- FastAPI / Uvicorn（阶段 1 受控同步入口）
- Pydantic + pydantic-settings + python-dotenv
- Pytest + HTTPX + structlog
- Ruff / Bandit / Radon / Coverage.py（静态分析与可信 Fixture 覆盖率）

后续阶段按规划逐步引入 LangGraph、Redis/ARQ、PostgreSQL、MCP、A2A、OpenTelemetry 等，
阶段 1 不得提前安装或实现。

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
```

阶段 1 要求阶段 0 回归与新增单元测试全部通过；常规单元测试不联网、不调用真实 LLM。
可信 Fixture 之外的仓库不会在宿主机执行测试。

## CLI 与 API

CLI 是主要执行入口；CLI 与 FastAPI 都只调用 `ReviewService`。由于当前未提供
`pyproject.toml` / 可编辑安装，从仓库根目录运行 CLI 需要把 `src` 加入模块搜索路径：

```powershell
$env:PYTHONPATH = "src"
conda run -n multi-agent-review python -m code_review.cli review https://github.com/pallets/itsdangerous --branch main
```

可选参数：`--commit-sha <40 位 SHA>`、`--output-dir <目录>`、`--json`。
输出目录默认读取 `REVIEW_OUTPUT_ROOT`（缺省 `reports`），每次审查生成：

```
reports/<review_id>/
├── metadata.json
├── static_analysis.json
├── test_report.json
└── report.md
```

阶段 1 不生成 `report.json` 或 `ReviewReport`。FastAPI 入口为
`code_review.api.app:app`，同步 `POST /api/reviews` 只接受 `repository_url`、
`branch`、`commit_sha`，单进程单并发槽位，忙碌时返回 429。

## 安全边界

- 外部 GitHub 仓库只做静态分析，测试状态固定为 `not_executed`。
- 仅 `tests/fixtures/trusted_repo/` 下经人工审查、带哈希清单的 Fixture 可在宿主机
  执行 Pytest / Coverage；不接受任意 URL 提权，不自动安装依赖，不执行安装脚本。
- 仓库内容视为不可信数据；报告与 LLM 输入不包含 `.env`、密钥、令牌或宿主机路径。
- 所有阶段 1 Finding 的 `agent_name` 为 `Stage1Analyzer`，`verification_status` 为
  `unverified`；LLM 不合格提案只进入 `llm_analysis.rejected[]`。

## 当前目录

```
config/settings.py              配置读取（pydantic-settings）
src/code_review/schemas/        AgentTask / Finding / AgentResult / ReviewReport
src/code_review/tools/          仓库获取、扫描、Ruff/Bandit/Radon、测试执行
src/code_review/services/       聚合、证据校验、LLM 分析、统一 ReviewService
src/code_review/reporting/      Artifact Schema、四件产物生成、Markdown 渲染
src/code_review/cli.py          命令行入口
src/code_review/api/            FastAPI 受控同步入口
tests/unit/                     单元测试（Mock / Fake，不联网）
tests/integration/              集成测试（可信 Fixture 可受控执行）
docs/                           需求、架构、工作流、数据合同、验收标准
reports/                        本地审查产物（按 .gitignore 不提交）
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
| 1 | 单 Agent 工程基础：仓库获取、解析、静态分析、报告（当前） |
| 2 | LangGraph Supervisor-Worker 多 Agent 编排 |
| 3 | SubAgent 分层编排与任务生命周期 |
| 4 | Redis + ARQ 异步任务与失败恢复 |
| 5 | MCP 工具接入与权限隔离 |
| 6 | A2A 跨服务协作 |
| 7 | 可观测性、产品化与完整部署 |

每个阶段必须通过 `docs/acceptance.md` 中的验收标准后才能进入下一阶段。
