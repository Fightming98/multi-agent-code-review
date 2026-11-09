# Multi-Agent Code Review System

输入一个 GitHub 仓库 URL，由 Manager Agent 规划任务，Security / Quality / Performance / Testing
四个专业 Agent 并行审查，最终由 Final Reviewer 完成证据核验、去重、评分并生成结构化审查报告。

> 当前进度：**阶段 0（工程初始化与需求冻结）**。本阶段只建立工程骨架、冻结文档与数据合同，
> 不包含任何 Agent、LLM 调用、代码审查或工作流实现。

## 技术栈（阶段 0 固定）

- Python 3.12 + Conda（环境名 `multi-agent-review`）
- FastAPI / Uvicorn（后续阶段使用）
- Pydantic + pydantic-settings + python-dotenv
- Pytest + HTTPX
- structlog

后续阶段按规划逐步引入 LangGraph、Redis/ARQ、PostgreSQL、MCP、A2A、OpenTelemetry 等，
阶段 0 不得提前安装或实现。

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
```

阶段 0 要求全部用例通过，且没有 skip / xfail 用例。

## 当前目录

```
config/settings.py              配置读取（pydantic-settings）
src/code_review/schemas/        AgentTask / Finding / AgentResult / ReviewReport
tests/unit/                     数据合同单元测试
docs/                           需求、架构、工作流、数据合同、验收标准
reports/                        后续存放审查报告（当前仅占位）
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
| 0 | 工程初始化与需求冻结（当前） |
| 1 | 单 Agent 工程基础：仓库获取、解析、静态分析、报告 |
| 2 | LangGraph Supervisor-Worker 多 Agent 编排 |
| 3 | SubAgent 分层编排与任务生命周期 |
| 4 | Redis + ARQ 异步任务与失败恢复 |
| 5 | MCP 工具接入与权限隔离 |
| 6 | A2A 跨服务协作 |
| 7 | 可观测性、产品化与完整部署 |

每个阶段必须通过 `docs/acceptance.md` 中的验收标准后才能进入下一阶段。
