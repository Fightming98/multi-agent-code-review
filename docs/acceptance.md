# 验收文档（Acceptance）

| 项目 | 内容 |
| --- | --- |
| 项目名称 | Multi-Agent Code Review System |
| 文档版本 | v1.3（阶段 1 实施基线修订：最终 Provider 与输出上限） |
| 适用范围 | Multi-Agent Code Review System 阶段 0～阶段 7 的工程实施基线 |
| 当前阶段 | 阶段 1：单 Agent 工程基础（实施基线） |
| 最后更新 | 2026-11-10 |
| 状态 | 已冻结（Frozen）；阶段 1 补充条款见 §4.7～§4.11 |
| 关联文档 | `requirements.md`、`architecture.md`、`workflow.md`、`task_contracts.md` |

> 本文档回答“如何证明某个阶段真的完成了”。**阶段 0 的验收标准是本文档的重点，已详细定义；阶段 1～7 的标准依据总规划建立，进入对应阶段前再细化阈值与命令，当前不需要提前实现。**
>
> **阶段 1 实施基线修订（2026-11-10）**：本次仅补充阶段 1 的阈值、验收命令、可信 Fixture 规则与 AC-1-15 产物口径；不修改 AC-1-01～AC-1-15 的编号和既有语义，不降低任何验收标准。变更记录见 §4.11。v1.2 进一步把 LLM 输出上限调整为 5,000 tokens（每次调用），并补充 15～20 条/次的 Finding 分块调用基线。v1.3 将输出上限调整为 8,000 tokens（每次调用），并确定阶段 1 主 Provider 为 SiliconFlow `deepseek-ai/DeepSeek-V3`；LLM 请求超时保持 60 秒。

---

## 1. 验收原则

| 编号 | 原则 |
| --- | --- |
| AR-1 | **以实际运行结果、测试记录和可验证交付物作为验收依据**，不以“代码写了很多”或“报告生成了”作为成功标准。 |
| AR-2 | **每个阶段必须先通过验收，再进入下一阶段。** 不得为了提前展示高级技术而跳过前置阶段的基础验收。 |
| AR-3 | 阶段 P0 / P1 / P2 表示交付价值优先级，不代表开发先后顺序；即使某功能被列入 P2，也不能跳过它所在阶段的基础依赖。 |
| AR-4 | **回归原则**：进入阶段 N 时，阶段 0～N-1 的全部测试必须仍然通过。 |
| AR-5 | **真实性原则**：验收所用的评分、问题与执行数据必须来自真实代码分析与模型调用；测试结果与覆盖率必须来自真实工具输出，未执行时必须标记 `not_executed`，不得伪造。 |
| AR-6 | **文档同步原则**：验收通过前必须更新项目文档；合同变更必须同时更新 `task_contracts.md`、Schema 与测试。 |
| AR-7 | **安全原则**：验收过程中不得在宿主机直接执行外部不可信仓库代码；仓库中不得提交密钥。 |
| AR-8 | **固定四个核心评分维度**：Security、Quality、Performance、Testing 是**固定的四个核心评分维度**；SubAgent 和外部 A2A Agent 是执行扩展，不自动改变核心评分结构（`ReviewReport` 的 `dimension_scores` 与 `agent_results` 始终是这四个维度）。 |

### 1.1 阶段开发与验收节奏

```
架构设计 → 编写开发任务 → 交给 Claude Code 实现 → 运行测试 → 检查实际代码 → 修复问题 → 阶段验收 → 更新项目文档
```

### 1.2 验收结论定义

| 结论 | 含义 |
| --- | --- |
| 通过 | 本阶段所有“必须”项均满足，可以进入下一阶段。 |
| 不通过 | 存在任一“必须”项不满足，必须修复并重新验收，不得进入下一阶段。 |

> 为避免含糊，不设“有条件通过”。“建议”项未满足不影响通过，但应记录为后续待办。

### 1.3 验收记录模板

每个阶段验收结束，需在本阶段的记录中填写（可存放在 PR 描述或 `docs/acceptance_records/` 中，后者由后续阶段按需创建）：

```
阶段：
验收日期：
代码版本（Commit SHA / Tag）：
执行环境：
验收项结果：AC-x-01 通过 / 不通过（证据：命令输出、截图、日志路径）...
测试命令与结果：
未通过项与修复计划：
遗留问题（非阻断）：
结论：通过 / 不通过
验收人：
```

---

## 2. 阶段总览

| 阶段 | 名称 | 优先级 | 里程碑 | 核心验收证据 |
| --- | --- | --- | --- | --- |
| 0 | 工程初始化与需求冻结 | P0 | M1 | 环境、目录、五份文档、数据合同单元测试通过 |
| 1 | 单 Agent 工程基础 | P0 | M1 | 真实仓库获取 → 静态分析 → 结构化报告；不可信仓库不被执行 |
| 2 | LangGraph Supervisor-Worker | P0 | M2 | 四个 Agent 并行（时间线证明）+ Final Reviewer + 报告 |
| 3 | SubAgent 分层编排 | P1 | M2 | 父子任务、事件记录、并发上限、局部失败不丢结果 |
| 4 | 异步任务与失败恢复 | P1 | M3 | 故障注入测试、幂等、状态可查询、并发排队 |
| 5 | MCP 工具接入 | P1 | M3 | 工具发现与调用、权限隔离、Schema 校验 |
| 6 | A2A 跨服务协作 | P1 | M3 | 独立外部 Agent、Agent Card、Artifact、失败降级 |
| 7 | 可观测性与产品化 | P2 | M4 | 完整 Trace、Token 成本、Compose 部署、真实 PR 审查 |

---

## 3. 阶段 0：工程初始化与需求冻结（详细验收）

### 3.1 阶段目标

> 建立可维护、可测试、可扩展的 Python 工程骨架，冻结项目需求，明确整体架构和 Agent 工作流程，建立统一的父子任务数据合同，并通过基础单元测试验证数据结构的正确性。

阶段 0 **不是**开发一个能工作的 Agent 系统，而是为后续阶段 1～7 建立可靠的工程基础。

### 3.2 交付物

| 类别 | 交付物 | 路径 |
| --- | --- | --- |
| 环境 | Conda 环境定义 | `environment.yml` |
| 配置 | 配置管理 | `config/settings.py` |
| 配置 | 环境变量示例 | `.env.example` |
| 工程 | 忽略规则、说明 | `.gitignore`、`README.md` |
| 代码 | 数据合同 | `src/code_review/schemas/{task,result,report}.py` 与 `__init__.py` |
| 测试 | 单元测试 | `tests/unit/{test_task_schema,test_result_schema,test_report_schema}.py` |
| 文档 | 五份核心文档 | `docs/{requirements,architecture,workflow,task_contracts,acceptance}.md` |
| 占位 | 报告目录 | `reports/.gitkeep` |
| 版本 | Git 仓库与首次提交 | GitHub 仓库 `multi-agent-code-review` |

> 允许新增一个**仅含配置的** `pytest.ini`（例如 `pythonpath = src .`、`testpaths = tests`），用于让 `src/` 布局与 `config/` 在不安装包的情况下可被导入。它不是新依赖，也不属于后续阶段目录。

### 3.3 功能验收标准

下表“必须”项全部满足才算通过。验证命令默认在项目根目录、已激活环境 `multi-agent-review` 的终端中执行。

#### A. 环境与依赖

| 编号 | 验收项 | 验证方式 | 期望结果 |
| --- | --- | --- | --- |
| AC-0-01 | Conda 环境可创建并激活 | `conda env create -f environment.yml`，`conda activate multi-agent-review` | 环境名为 `multi-agent-review`，无报错 |
| AC-0-02 | Python 版本为 3.12 | `python --version` | 输出 `Python 3.12.x` |
| AC-0-03 | 阶段 0 基础依赖全部可用 | `python -c "import fastapi, uvicorn, pydantic, pydantic_settings, dotenv, pytest, httpx, structlog; print('ok')"` | 输出 `ok` |
| AC-0-04 | `environment.yml` 仅包含阶段 0 依赖 | 人工检查文件 | 依赖仅为：`fastapi`、`uvicorn`、`pydantic`、`pydantic-settings`、`python-dotenv`、`pytest`、`httpx`、`structlog`（外加 `python=3.12`、`pip`）；**不得显式声明任何 `opentelemetry-*`**（包括 `opentelemetry-api`） |
| AC-0-05 | **未提前引入后续阶段技术**（拆分为 (a) 禁止项、(b) 代码层、(c) 环境文件、(d) 允许的被动依赖，四项都通过才算通过） | 见下方命令 | 见下方期望结果 |

**判定原则：区分“被动传递依赖”与“主动接入”。** 依赖解析可能经由 FastAPI 技术栈的强制传递依赖带入 `opentelemetry-api`，这属于被动依赖，**允许**；阶段 0 **禁止**主动安装 `opentelemetry-sdk`、任何 Exporter 或 instrumentation 包，也**禁止**在项目代码中接入 OpenTelemetry Trace。

| 类别 | 内容 |
| --- | --- |
| 允许项（被动） | `opentelemetry-api`（仅当它由依赖解析被动带入时）及其传递依赖 |
| 禁止项（主动） | `langchain*`、`langgraph*`、`redis`、`arq`、`sqlalchemy`、`psycopg*`、`asyncpg`、`mcp`、`a2a-sdk`、`langsmith`、`streamlit`；除 `opentelemetry-api` 之外的所有 `opentelemetry*` 包（含 `opentelemetry-sdk`、`opentelemetry-exporter-*`、`opentelemetry-instrumentation-*`） |

**(a) 已安装包检查（禁止项探测）**（跨平台，同时列出被动允许项）：

```
python -c "import importlib.metadata as m; n={(d.metadata['Name'] or '').lower().replace('_','-') for d in m.distributions()}; exact={'langgraph','redis','arq','sqlalchemy','asyncpg','mcp','a2a-sdk','langsmith','streamlit'}; pre=('langchain','langgraph-','psycopg'); print('FORBIDDEN:', sorted(x for x in n if x in exact or x.startswith(pre) or (x.startswith('opentelemetry') and x!='opentelemetry-api'))); print('PASSIVE-ALLOWED:', sorted(x for x in n if x=='opentelemetry-api'))"
```

期望：`FORBIDDEN: []`；`PASSIVE-ALLOWED` 为 `[]` 或 `['opentelemetry-api']` 均可。

**(b) 代码层检查（禁止实际接入 Trace）：**

```
python -c "import pathlib; print('OTEL-IN-CODE:', [str(p) for r in ('src','config','tests') for p in pathlib.Path(r).rglob('*.py') if 'opentelemetry' in p.read_text(encoding='utf-8').lower()])"
```

期望：`OTEL-IN-CODE: []`（项目代码中不得出现 OpenTelemetry 的任何导入或配置）。

**(c) 环境文件检查：**

```
python -c "import pathlib; print('OTEL-IN-ENV:', 'opentelemetry' in pathlib.Path('environment.yml').read_text(encoding='utf-8').lower())"
```

期望：`OTEL-IN-ENV: False`（与 AC-0-04 一致）。

**(d) 被动依赖确认**（仅当 (a) 的 `PASSIVE-ALLOWED` 为 `['opentelemetry-api']` 时执行）：

```
pip show opentelemetry-api
```

期望：输出中的 `Required-by` 非空，即该包由其他已安装依赖带入，而不是由项目直接声明。

> 若 (a) 的 `FORBIDDEN` 非空，说明提前安装了后续阶段的依赖，必须清理环境后重新创建。

#### B. 工程结构与配置

| 编号 | 验收项 | 验证方式 | 期望结果 |
| --- | --- | --- | --- |
| AC-0-06 | 目录结构与 `architecture.md` §12.3 一致 | 人工对照；可用脚本检查路径存在 | 所有约定文件/目录存在 |
| AC-0-07 | **没有创建后续阶段目录** | 检查是否存在 `agents/`、`graph/`、`services/`、`tools/`、`mcp/`、`a2a/`、`orchestration/`、`workers/`、`observability/`、`storage/`、`reporting/`、`external_agents/` | 均不存在 |
| AC-0-08 | `.env.example` 已建立且仅含占位符 | 人工检查 | 无任何真实密钥、令牌或真实地址凭据 |
| AC-0-09 | `.env` 被忽略，不会入库 | `git check-ignore .env` | 输出 `.env` |
| AC-0-10 | `.gitignore` 覆盖常见产物 | 人工检查 | 至少包含 `.env`、`__pycache__/`、`*.pyc`、`.pytest_cache/`、`.venv/`、IDE 配置目录，以及 `reports/` 下的生成物（保留 `.gitkeep`） |
| AC-0-11 | 配置可加载 | `python -c "from config.settings import Settings; print(Settings())"`（在没有 `.env` 的情况下） | 正常实例化，不抛异常；字段有安全默认值或为可选；不打印任何密钥 |
| AC-0-12 | 配置使用 `pydantic-settings` 与 `python-dotenv` | 人工检查 `settings.py` | 通过环境变量/`.env` 覆盖默认值；密钥只通过环境变量注入 |
| AC-0-13 | `README.md` 内容基本完整 | 人工检查 | 含项目简介、当前阶段与路线、环境创建与测试命令、文档链接 |

#### C. 数据合同代码

| 编号 | 验收项 | 验证方式 | 期望结果 |
| --- | --- | --- | --- |
| AC-0-14 | 合同模型可导入 | `python -c "from code_review.schemas import AgentTask, AgentResult, Finding, ReviewReport; print('ok')"` | 输出 `ok` |
| AC-0-15 | 合同与 `task_contracts.md` 字段、取值、默认值一致 | 对照 §4、§5、§8、§9 的字段表 | 无缺失、无多余字段；`extra = "forbid"` 生效 |
| AC-0-16 | 任务状态集合为 `pending / running / completed / failed / cancelled`；结果状态为 `completed / failed / partial` | 人工检查 + 测试 | 与文档一致 |
| AC-0-17 | 不使用已弃用的 `datetime.utcnow()`；时间带 UTC 时区 | 搜索代码 | 未出现 `utcnow`；默认时间为带时区的 UTC |
| AC-0-18 | 可变默认值安全 | 人工检查 | 列表、字典默认值使用 `Field(default_factory=...)` |
| AC-0-19 | 依赖方向正确 | 人工检查导入 | `task.py` ← `result.py` ← `report.py`，`schemas` 不导入业务模块 |
| AC-0-20 | 不越界实现 | 人工检查与搜索 | 无 LLM 调用、无网络访问、无 Agent 逻辑、无 FastAPI 路由；`src/code_review` 下仅有 `schemas` |

> 说明：任务树最大深度、父任务存在性、父子关系环检测与子任务派生权限属于多任务对象之间的拓扑/权限约束，不在阶段 0 单个 `AgentTask` Schema 的验收范围内，统一由阶段 3 验收（AC-3-11）；阶段 0 仅校验 TK-02（不得自引用）等单对象约束，且不新增 `task_depth` / `depth` 字段。

#### D. 文档

| 编号 | 验收项 | 期望结果 |
| --- | --- | --- |
| AC-0-21 | 五份文档均已建立于 `docs/` | 文件存在且非空 |
| AC-0-22 | `requirements.md` 完整 | 含背景目标、核心问题、使用场景、六个 Agent 职责、FR、NFR、技术约束、八个阶段（阶段 0～7）的功能范围、MVP 与扩展、非目标 |
| AC-0-23 | `architecture.md` 完整 | 含九层架构、FastAPI/LangGraph/Redis/ARQ/PostgreSQL/Checkpointer/MCP/A2A/OpenTelemetry 的职责与边界、Mermaid 总体架构图，并区分目标架构与当前已实现范围 |
| AC-0-24 | `workflow.md` 完整 | 含主流程与正常流程、Agent 失败、超时重试、SubAgent、MCP、A2A、报告生成七类流程，并有 Mermaid 图；各流程按实际阶段标注：Agent 失败与部分完成标注“阶段 2 实现”，SubAgent 标注“阶段 3 实现”，超时重试与 MCP、A2A 标注“设计预留（阶段 4/5/6）”，主流程与报告生成标注“阶段 1～2”。 |
| AC-0-25 | `task_contracts.md` 完整 | 含父子任务关系、ID 规则、输入输出规范、Finding、AgentResult、ReviewReport、任务状态、失败与重试字段、JSON 序列化规范，并有完整 JSON 示例 |
| AC-0-26 | 关键口径一致 | 见下表 |
| AC-0-27 | 文档中的 JSON 示例可解析 | 每个 JSON 代码块（以 json 标记的围栏代码块）都能被 JSON 解析器解析 |
| AC-0-28 | Mermaid 图可渲染 | 在 GitHub 或 VS Code Markdown 预览中均能正常显示 |
| AC-0-29 | 文档示例与 Schema 一致 | 每个**合法、完整**的模型示例在测试中都有对应用例并通过 `model_validate()`；明确标注为**非法输入**的示例必须被对应 Schema 拒绝；非模型 JSON 片段只要求通过 `json.loads` 语法解析。 |

AC-0-26 的“关键口径”对照：

| 口径 | 必须在所有相关文档中一致 |
| --- | --- |
| Manager 职责 | 任务规划、分发、执行协调、结果收集；不替代专业 Agent 审查，不生成最终审查结论 |
| Final Reviewer 职责 | 证据核验、Finding 去重、综合评分、最终报告生成；第一版为 LangGraph 的独立 Node |
| Redis / ARQ | Redis 负责队列、缓存与必要的消息传递；ARQ 负责 Python 后台任务执行 |
| 三类状态 | PostgreSQL 为业务任务与结果的权威存储；Checkpointer 为工作流执行状态与断点恢复；Redis 为队列与缓存 |
| LangGraph | 阶段 2 先采用进程内编排 |
| MCP / A2A | MCP 负责标准化工具接入；A2A 负责跨服务 Agent 通信 |
| 任务状态 | `pending / running / completed / failed / cancelled` |
| 结果状态 | `completed / failed / partial` |
| 枚举大小写 | 状态类枚举一律小写蛇形（含 `execution_status` 的 `not_executed`）；仅 `overall_verdict` 使用大写常量；文档与代码中不得使用全大写写法（如把 `not_executed` 写成全大写） |
| 报告维度 | `dimension_scores` 与 `agent_results` 必须且仅包含四个固定维度；所有维度均无评分时 `overall_score` 为 `null`、`report_status` 为 `partial`，结论在无已核验 `critical` Finding 时为 `COMMENT`，存在时为 `REQUEST_CHANGES`（RP-16、RP-06） |
| 固定四个核心评分维度 | Security、Quality、Performance、Testing 固定；SubAgent 与外部 A2A Agent 是执行扩展，不改变核心评分结构 |
| 评分权重 | 每个配置权重 `0 < w ≤ 1`，四个配置权重之和为 1；缺失维度用 `score = null`，不用 `weight = 0`；报告存储的 `DimensionScore.weight` 始终保持配置值，仅在综合分计算公式内部对有效维度权重归一化 |
| 阶段数量 | 八个阶段（阶段 0～7） |
| 证据要求 | 每个 Finding 必须有代码位置或工具证据 |

#### E. 版本管理

| 编号 | 验收项 | 期望结果 |
| --- | --- | --- |
| AC-0-30 | Git 仓库已初始化并关联 GitHub 远端 | `git remote -v` 显示 `multi-agent-code-review` |
| AC-0-31 | 阶段 0 成果已提交并推送 | `git status` 工作区干净；远端有对应提交 |
| AC-0-32 | 没有提交敏感或生成文件 | 仓库中无 `.env`、`__pycache__`、`.pytest_cache`、真实密钥 |
| AC-0-33 | 验收通过后打标签 | 如 `stage-0-accepted`，用于回溯与回归 |

### 3.4 测试验收标准

#### 3.4.1 执行命令

```
pytest tests/unit -v
```

期望：所有用例通过；**无失败、无错误、无被跳过（skip）或预期失败（xfail）的用例**；测试不依赖网络、LLM 与外部服务；多次执行结果一致。

> 阶段 0 未安装 Coverage.py，因此**不以覆盖率百分比作为阶段 0 的验收指标**，而以“规则编号与用例的一一对应”作为完整性依据。

#### 3.4.2 用例覆盖要求

三个测试文件必须覆盖 `task_contracts.md` §14 列出的全部用例，概括如下：

| 测试文件 | 必须验证 |
| --- | --- |
| `test_task_schema.py` | 默认值与默认 ID 唯一；父子任务（`parent_task_id` 为空/有值/自引用）；非法状态与优先级；重试字段边界；超时边界；空必填字段；`failed` 必须带错误信息；未声明字段被拒；状态迁移的合法与非法矩阵及状态迁移纯函数（ST-05）；JSON 往返一致；文档示例通过校验 |
| `test_result_schema.py` | Finding 的 A 类 / B 类证据通过；纯自然语言结论被拒；`critical/high` 仅有工具证据被拒；行号、路径、置信度、严重级别边界；`AgentResult` 三种状态与 `error / score / findings` 的约束；重复 `finding_id`、Agent 名称不一致、非法 `commit_sha`；默认列表不共享；JSON 往返一致；文档示例通过校验 |
| `test_report_schema.py` | 完整报告通过；评分与结论取值边界；任务计数一致性；`partial` 与 `report_status` 的一致性；硬性阻断规则（已核验 `critical` ⇒ `REQUEST_CHANGES`）；`rejected` 不得出现在 `findings`；`not_executed` 时测试数字必须为空；覆盖率必须有来源；维度评分缺失时不得 `APPROVE`；`commit_sha` 一致性；默认成本为 0；JSON 往返一致 |

#### 3.4.3 规则编号可追溯检查

`task_contracts.md` 中的校验规则带有编号（TK / ST / FD / RS / RP / RT）。要求每条**属于 Schema 层**的规则至少在一个测试中出现（建议在测试名或 docstring 中写明规则编号）。验证命令：

```
python -c "import re,pathlib; ids=set(re.findall(r'\b(?:TK|ST|FD|RS|RP)-\d{2}\b', pathlib.Path('docs/task_contracts.md').read_text(encoding='utf-8'))); t=''.join(p.read_text(encoding='utf-8') for p in pathlib.Path('tests/unit').glob('test_*.py')); print(sorted(i for i in ids if i not in t))"
```

期望输出恰好为 `['FD-09', 'FD-10', 'ST-04', 'ST-06', 'ST-07']`。这五条分别属于编排层核验（FD-09）、脱敏处理（FD-10）与状态迁移的运行时行为（ST-04、ST-06、ST-07；时间戳的静态一致性由 TK-13 在 Schema 层校验）。ST-05 要求的状态迁移纯函数已由 `task.py` 的 `is_transition_allowed()` 实现，并在 `test_task_schema.py` 中真实覆盖，不再作为排除项。`RT-*` 规则同属运行时规则，不在检查范围内。出现其他编号即表示存在未被测试覆盖的规则。

#### 3.4.4 代码检查清单（“检查实际代码”环节，人工）

| 编号 | 检查项 |
| --- | --- |
| CK-1 | 所有字段有类型标注；使用 `Literal` 约束枚举值。 |
| CK-2 | 校验逻辑使用 Pydantic 的 validator，错误信息清晰、可定位到字段。 |
| CK-3 | 无硬编码的密钥、路径、URL。 |
| CK-4 | 无未使用的导入与死代码。 |
| CK-5 | 测试之间相互独立，不共享可变全局状态。 |
| CK-6 | 测试断言的是“应被拒绝的非法输入确实被拒绝”，而不仅是“合法输入通过”。 |
| CK-7 | 没有为了让测试通过而放宽合同（例如把 `extra` 改回 `ignore`）。 |

### 3.5 通过条件

阶段 0 通过，当且仅当**同时**满足：

1. 3.3 中 AC-0-01 ～ AC-0-33 全部通过；
2. `pytest tests/unit -v` 全部通过，且无 skip / xfail；
3. 3.4.3 的规则追溯检查输出符合期望；
4. 3.4.4 的代码检查清单全部通过；
5. 五份文档经项目负责人评审并确认**冻结为 v1.0**；
6. 阶段 0 成果已提交、推送并打标签。

冻结之后，需求、架构、工作流与数据合同的任何变更都必须按“变更流程”处理（`task_contracts.md` §11）：先修改文档并评审，再改代码与测试。

### 3.6 不通过时需要修复的问题

| 现象 | 需要修复 |
| --- | --- |
| `python --version` 不是 3.12 | 重新创建环境；检查 `environment.yml` 中的 `python=3.12`。 |
| AC-0-05(a) 的 `FORBIDDEN` 非空 | 卸载并重建环境；从 `environment.yml` 与安装命令中去除后续阶段依赖（包括 `opentelemetry-sdk`、Exporter）。 |
| AC-0-05(b) / (c) 发现项目代码或 `environment.yml` 中出现 OpenTelemetry | 删除相关导入、配置与依赖声明，Trace 接入留到阶段 7。 |
| 仅出现 `opentelemetry-api` 且 `Required-by` 非空 | 属于被动传递依赖，允许，不需要处理。 |
| 出现后续阶段目录或代码（如 `agents/`、LangGraph 导入） | 删除越界内容；保持阶段 0 范围。 |
| `.env` 被 Git 跟踪，或 `.env.example` 含真实密钥 | 立即从仓库与历史中移除，**轮换已暴露的密钥**，补充 `.gitignore`。 |
| 单元测试失败 | 以 `task_contracts.md` 为准修复代码；若发现合同本身有误，走变更流程更新文档后再改代码，禁止只改代码。 |
| 存在 skip / xfail 用例 | 补全实现并移除标记。 |
| 规则追溯检查输出多于预期 | 为缺失的规则补充测试。 |
| 文档中的 JSON 无法解析或与 Schema 不一致 | 修正文档或 Schema，并补充对应测试用例。 |
| Mermaid 图无法渲染 | 修正语法（标签含特殊字符时加引号）。 |
| 文档口径不一致（AC-0-26） | 以 `task_contracts.md` 与 `architecture.md` 为准统一其他文档。 |
| 使用了 `datetime.utcnow()` 或共享可变默认值 | 改为 `datetime.now(timezone.utc)` 与 `Field(default_factory=...)`。 |

---

## 4. 阶段 1：单 Agent 工程基础

### 4.1 阶段目标

先不引入多 Agent，构建能够真正获取、解析、静态分析代码并生成结构化报告的基础工具链。**这一步是整个项目的地基。**

### 4.2 交付物

GitHub 仓库获取模块（含安全校验与 Commit 固定）、文件解析器、Ruff / Bandit / Radon 接入、对可信仓库的 Pytest / Coverage.py 执行、`ReviewService`、CLI、最小同步的 `POST /api/reviews`（阶段 1 必做）、LLM 语义分析模块（兼容 OpenAI API 的国内模型服务，如 DeepSeek；Provider 通过 `config/settings.py` 注入）、基础报告输出（`metadata.json`、`static_analysis.json`、`test_report.json`、`report.md`）、单元与集成测试、受控的可信测试仓库。

### 4.3 功能验收标准

| 编号 | 验收项 |
| --- | --- |
| AC-1-01 | 能成功 Clone 指定 GitHub 仓库，并**固定本次审查的完整 Commit SHA**，写入审查上下文。 |
| AC-1-02 | URL 校验：仅接受 HTTPS 的 GitHub 地址；拒绝 `http://`、非 GitHub 域名、非常规端口、带凭据的 URL、本地路径与 `file://`；防 SSRF 与路径穿越。 |
| AC-1-03 | 资源限制生效：仓库大小、文件数量、单文件大小、下载时间超限时明确拒绝或截断并记录。 |
| AC-1-04 | 能正确识别源码文件并输出路径、语言、行数、大小；过滤二进制、大文件及 `.git`、`node_modules`、`.venv`。 |
| AC-1-05 | `.env`、私钥、凭证等敏感文件**不会**进入 LLM 上下文（以含此类文件的样例仓库验证）。 |
| AC-1-06 | Ruff 输出结构化检查结果。 |
| AC-1-07 | Bandit 输出结构化安全检查结果。 |
| AC-1-08 | Radon 输出结构化复杂度结果。 |
| AC-1-09 | Pytest 对**可信测试仓库**执行并输出结果；Coverage.py 生成可信样例的覆盖率报告。 |
| AC-1-10 | **对外部不可信仓库，不在宿主机直接执行其测试、安装或构建脚本**；测试状态标记为 `not_executed`，并说明原因，不伪造结果。 |
| AC-1-11 | 静态分析工具有超时、输出大小与资源限制。 |
| AC-1-12 | 仓库工作区为只读，分析不会修改原始代码。 |
| AC-1-13 | LLM 仅负责解释静态分析结果与补充语义问题；由模型生成的 Finding 必须满足证据合同，不合规的被丢弃并记录。 |
| AC-1-14 | CLI 与 FastAPI 调用**同一个 `ReviewService`**，不存在两套审查逻辑；FastAPI 仅提供受控的同步入口，HTTP 请求中不执行长时间运行的 Agent 工作流。 |
| AC-1-15 | 生成 `reports/<review_id>/` 下的四个基础输出文件，Markdown 报告可读；三份 JSON 分别符合阶段 1 专用 Pydantic Artifact Schema；`report.md` 由三份结构化数据渲染；阶段 1 不要求生成完整 `ReviewReport`。 |

### 4.4 测试验收标准

| 编号 | 验收项 |
| --- | --- |
| TC-1-01 | 阶段 0 的全部测试仍然通过（回归）。 |
| TC-1-02 | URL 校验器、文件收集器、过滤规则、工具输出解析器均有单元测试；单元测试不访问网络、不调用真实 LLM（使用 Mock / Fake / fixtures）。 |
| TC-1-03 | 使用**自己编写**的可信测试仓库完成一次集成测试，覆盖 AC-1-01 ～ AC-1-15。 |
| TC-1-04 | 一次真实 GitHub 仓库 Clone 的验证（可作为手动验收，记录 Commit SHA 与输出）。 |
| TC-1-05 | 安全用例：恶意 URL、路径穿越、含敏感文件的仓库、超大文件，行为符合预期。 |
| TC-1-06 | 一次真实模型调用的冒烟测试（记录模型名与 `usage`），单独标记，不纳入常规单元测试。无合法 API Key 时记为 **BLOCKED / NOT RUN**，不得记为 PASS；阶段 1 整体结论同时为 **BLOCKED**，不得判 PASS。 |

### 4.5 通过条件

AC-1-01 ～ AC-1-15 与 TC-1-01 ～ TC-1-06 全部满足；使用的审查样例仓库为自己编写或经过确认可安全执行；未对外部不可信仓库在宿主机执行任何代码。

**三态结论规则（2026-11-10）**：阶段 1 最终状态只允许 `PASS` / `BLOCKED` / `FAIL`。任一 AC/TC 因环境缺失（如无合法模型 API Key）无法执行时记为 `BLOCKED`，阶段 1 整体不得判 `PASS`；`BLOCKED ≠ PASS`，验收报告必须保留该项的 `BLOCKED` 状态与原因。

### 4.6 不通过时需要修复的问题

| 现象 | 需要修复 |
| --- | --- |
| 外部仓库的测试在宿主机被执行 | 立即停止；改为 `not_executed`；补充安全测试。 |
| Commit SHA 未固定或行号对应的版本不确定 | 在审查上下文中固定 SHA，并贯穿所有结果。 |
| 报告中出现伪造的测试或覆盖率数据 | 改为仅使用工具真实输出。 |
| CLI 与 API 逻辑重复 | 抽取到 `ReviewService`。 |
| 敏感文件进入 LLM 上下文 | 修复过滤规则并补测试。 |

### 4.7 阶段 1 阈值与资源限制（2026-11-10 补充）

| 配置项 | 阈值 | 超限处理 |
| --- | --- | --- |
| Clone 超时 | 300 秒 | 终止 Git 进程树，记录 `timeout`，清理临时目录 |
| Git 命令超时 | 300 秒 | 同上 |
| 仓库大小 | 200 MB | Clone 过程中监控工作区磁盘占用；超限终止并拒绝审查；Clone 完成后复核；记录 `resource_limit_exceeded` |
| 文件数量 | 5,000 | 拒绝本次审查并记录 |
| 单文件大小 | 2 MB | 跳过该文件，记录过滤原因 |
| 总扫描大小 | 50 MB | 停止继续扫描；报告 `partial` 并记录原因，或按明确策略拒绝；不得静默截断，不得把部分结果伪装成完整结果 |
| 单个静态工具超时 | 120 秒 | 终止进程，记录 `timeout` |
| 单工具 stdout/stderr | 各 5 MiB | 截断并标记 `truncated=true` |
| 单工具 Finding 上限 | 1,000 | 截断并记录 |
| Pytest 超时 | 300 秒 | 终止进程，记录 `failed/timeout`；不得记为 `not_executed` |
| Coverage 超时 | 300 秒 | 终止进程，记录 `failed/timeout` |
| LLM 请求超时 | 60 秒 | 记录 `timeout`，保留确定性工具结果 |
| LLM 输入上限 | 60,000 字符 | 只选取必要代码片段，不传敏感内容 |
| LLM 输出上限 | 8,000 tokens（每次调用） | 超出部分截断或拒收 |
| LLM 单次调用 Finding 上下文上限 | 20 条（默认 15 条） | 按块调用，跨块汇总与 ID 对账 |
| LLM temperature | 0.0 | — |
| LLM Finding 提案上限 | 50（整次审查） | 超出部分丢弃并记录 |
| 可信仓库名单 | 仅 `trusted_fixture_v1` | 其他仓库一律视为不可信 |
| GitHub 域名 | 仅 `github.com` | 拒绝其他域名与子域名 |
| GitHub 端口 | 443 或默认端口 | 拒绝非常规端口 |

补充约束：

- 仓库大小限制不是 Clone 完成后的事后统计；Clone 过程中必须监控工作区磁盘占用，超限时终止 Git 进程树。
- `keep_workspace_on_failure=false` 可作为默认值，但必须保留错误信息、资源超限记录和诊断证据；不得因为删除工作区丢失审计信息。
- 阈值实现必须集中在 `config/settings.py`，不得散落在业务代码中。
- LLM 辅助分析按确定性 Finding 分块调用，每块 15～20 条（默认 15 条，`llm_max_findings_per_call`）。各块的提案编号、语义 Finding ID 与用量统计必须全局唯一或累加，跨块统一去重与 ID 对账。
- 分块调用采用 all-or-nothing 失败语义：任一块超时、请求失败或响应不可解析时，保留全部确定性工具结果，LLM 状态标记为 `timeout` / `failed`，不混入任何部分块的模型结论。
- 50 条 Finding 提案上限按整次审查计算，不按单块计算；输出上限 8,000 tokens 按每次调用计算。
- `Stage1实施前人工决策.md` 中记录的 2,000 tokens 是当时的裁定；该文件作为历史记录不重写，阶段 1 实施以本文件 v1.3 为准。

### 4.8 可信测试 Fixture 规则（2026-11-10 补充）

1. 仅 `tests/fixtures/trusted_repo/` 下由项目维护、经人工审查的 Fixture 可在宿主机执行 Pytest/Coverage。
2. 使用固定版本或哈希清单；运行时不接受动态替换。
3. 不接受任意 GitHub URL + `--trusted` 提升信任等级。
4. 不自动安装 Fixture 的第三方依赖。
5. 不执行 Fixture 中的 `setup.py`、`build.py` 或任意安装脚本。
6. 外部 GitHub 仓库一律不可信，测试状态必须为 `not_executed` 并写明原因。
7. 可信 Fixture 与外部仓库的执行数据必须在报告中区分。
8. 该例外仅适用于阶段 1 的项目自维护 Fixture；阶段 2 起仍按沙箱与受控执行策略处理。

### 4.9 阶段 1 产物验收口径（2026-11-10 补充）

- `reports/<review_id>/` 仅生成 `metadata.json`、`static_analysis.json`、`test_report.json`、`report.md` 四件；不生成 `report.json`。
- 三份 JSON 分别通过阶段 1 专用 Pydantic Artifact Schema 校验（`reporting/artifact_models.py`）；不得修改阶段 0 三个核心 Schema 文件。
- `report.md` 由三份结构化数据渲染；不得包含 JSON 中没有的实际审查结果。
- 阶段 1 不生成完整 `ReviewReport`；`report.json` 与 `ReviewReport` 自阶段 2 起由 Final Reviewer 生成。`requirements.md` FR-9.1 的 JSON 报告要求按阶段 2 起解释。
- Finding 的 `agent_name` 使用 `Stage1Analyzer`（单 Agent 基础分析来源标识，不代表已实现阶段 2 专业 Agent）；`task_type="stage1_review"` 仅在实际创建任务对象时使用，不得为填充该值额外创建阶段 1 `AgentTask` 体系；所有阶段 1 Finding 的 `verification_status` 保持 `unverified`，工具或 LLM 不得标记为 `verified`；LLM 不合格提案放 `llm_analysis.rejected[]`，不进入正式 Finding 列表。

### 4.10 阶段 1 验收命令（2026-11-10 补充）

以下命令统一使用项目 Conda 环境，避免 shell 的 `python` 指向 base 环境：

```powershell
# 阶段 0 回归 + 阶段 1 单元测试
conda run -n multi-agent-review python -m pytest tests/unit -q

# 阶段 1 集成测试（不联网、不调用真实 LLM）
conda run -n multi-agent-review python -m pytest tests/integration -q -m "not real_network and not llm_smoke"

# 真实 GitHub Clone（需网络与项目负责人批准）
conda run -n multi-agent-review python -m pytest tests/integration -q -m real_network

# 真实 LLM 冒烟（需 API Key）
$env:RUN_LLM_SMOKE="1"; conda run -n multi-agent-review python -m pytest tests/integration -q -m llm_smoke
```

阶段 1 CLI 的目标命令（Stage 1.6 实现后以此为准）：

```powershell
conda run -n multi-agent-review python -m code_review.cli review https://github.com/pallets/itsdangerous --branch main
```

### 4.11 变更记录

#### v1.3（2026-11-10，阶段 1 实施基线修订：最终 Provider 与输出上限）

- 原因：180 秒诊断确认 SiliconFlow `deepseek-ai/DeepSeek-V3` 可完成整仓扫描（4 次调用 44.75 / 30.01 / 25.23 / 16.02 秒），R1 / V3.2 / Qwen3.5-35B-A3B 均未完成；为最终配置保留足够输出预算，将输出上限提高。
- 修改：§4.7 LLM 输出上限由 5,000 tokens 调整为 8,000 tokens（每次调用）；确定阶段 1 主 Provider 为 SiliconFlow，模型为 `deepseek-ai/DeepSeek-V3`；`llm_timeout_seconds` 保持 60 秒不变。
- 影响：`config/settings.py` 的 `llm_max_output_tokens` 默认值改为 8,000；`.env.example` 同步；阶段 1.5 最终整仓验证使用 V3 + 60 秒 + 8,000 tokens。
- 未修改：LLM 请求超时 60 秒、输入上限 60,000 字符、15～20 条/块、50 条提案上限、temperature 0.0；阶段 0 验收内容；`task_contracts.md`；核心 Schema。
- 测试同步：配置断言更新为 8,000；阶段 0/1 全量回归与最终整仓扫描结果记录于阶段 1.5 证据报告。

#### v1.2（2026-11-10，阶段 1 实施基线修订：LLM 分块调用）

- 原因：真实模型整仓扫描暴露单次调用在 2,000 tokens 输出上限下无法覆盖 90 条确定性 Finding；推理模型的 reasoning token 还会占用输出预算，导致内容为空或 JSON 被截断。
- 修改：§4.7 LLM 输出上限由 2,000 tokens 调整为 5,000 tokens（每次调用）；新增单次调用 Finding 上下文上限 20 条（默认 15 条）；补充分块调用、跨块汇总/ID 对账与 all-or-nothing 失败语义。
- 影响：Stage 1.5 `LLMAnalyzer`；`config/settings.py` 新增 `llm_max_findings_per_call`；50 条提案上限保持整次审查语义。
- 未修改：阶段 0 验收内容；`task_contracts.md`；核心 Schema；LLM 请求超时 60 秒、输入上限 60,000 字符、temperature 0.0。
- 测试同步：新增分块调用、全局提案编号/语义 ID、用量汇总、单块失败与跨块去重测试；阶段 0/1 全量回归通过后记录于阶段 1.5 证据报告。
- 历史记录：`Stage1实施前人工决策.md` 中的 2,000 tokens 条目保留原文，以本文件 v1.2 为实施基线。

#### v1.1（2026-11-10，阶段 1 实施基线修订）

- 原因：完成阶段 1 实施前检查后的负责人裁定，补齐阶段 1 阈值、验收命令、可信 Fixture 规则与 AC-1-15 产物口径。
- 修改：§4.2 交付物、AC-1-14、AC-1-15；新增 §4.7～§4.10；§4.5 与 TC-1-06 补充 `PASS` / `BLOCKED` / `FAIL` 三态规则。
- 影响：AC-1-09、AC-1-10、AC-1-14、AC-1-15；TC-1-01～TC-1-06；Stage 1.1～Stage 1.7。
- 未修改：AC-1-01～AC-1-13 的编号与既有语义；阶段 0 验收内容；`task_contracts.md`。
- 测试同步：阶段 0 204 条单元测试回归通过；阶段 1 测试按子阶段补充。

---

## 5. 阶段 2：LangGraph Supervisor-Worker 多 Agent 编排

### 5.1 阶段目标

把单 Agent 系统改造成 Manager 规划、四个专业 Agent 并行执行、Final Reviewer 核验并汇总的多 Agent 系统（**进程内编排**）。这是整个项目最重要的核心学习阶段。

### 5.2 交付物

`graph/state.py`（`ReviewState`）、Manager、`BaseAgent` 与四个专业 Agent、并行 Fan-out / Fan-in 工作流、Final Reviewer（Evidence Validator、去重、可配置评分、结论与硬性阻断）、Markdown 与 JSON 报告、`review_rules.yaml`（权重与评分规则）、含已知问题的**测试样例仓库**、单元与集成测试。

### 5.3 功能验收标准

准备一个包含以下问题的真实测试仓库：硬编码密钥、SQL 注入风险、高复杂度函数、缺少错误处理、测试覆盖率不足、存在失败测试。

| 编号 | 验收项 |
| --- | --- |
| AC-2-01 | 运行日志可见完整过程：Review Started → Manager: Planning → Task Dispatch → 四个 Agent Running → All Workers Completed → Final Reviewer → Report Generated。 |
| AC-2-02 | Manager 生成 Task Plan，并创建符合合同的四个 `AgentTask`；Manager 不自己分析代码、不生成最终结论。 |
| AC-2-03 | **并行证明**：记录四个 Agent 独立的开始/结束时间，时间窗口重叠，且总耗时明显小于四者耗时之和。 |
| AC-2-04 | Worker 只接收对应的任务合同，不接收完整共享 State 与无关的敏感上下文。 |
| AC-2-05 | 并行节点只更新各自负责的字段，列表状态使用 Reducer；运行中不出现 `InvalidUpdateError`。 |
| AC-2-06 | 每个专业 Agent 返回统一的 `AgentResult`；每个 Finding 满足证据合同。 |
| AC-2-07 | 样例仓库中的已知问题（硬编码密钥、SQL 注入、高复杂度、失败测试、覆盖率不足）被相应 Agent 发现，且职责不重叠。 |
| AC-2-08 | Testing Agent 的测试数量与覆盖率来自真实工具输出，不由 LLM 估算。 |
| AC-2-09 | Final Reviewer 的 Evidence Validator 能拒绝伪造的 Finding（文件不存在、行号越界、片段不匹配）并放入 `rejected_findings`。 |
| AC-2-10 | 重复 Finding 被合并，`merged_from` 记录来源。 |
| AC-2-11 | 评分权重与规则可配置（`review_rules.yaml`），非硬编码；加载配置时校验四个配置权重均满足 `0 < w ≤ 1` 且之和为 1，不合法则报错；缺失维度（`score = null`）不参与综合评分，仅在综合分计算公式内部对有效维度权重归一化，报告存储的 `DimensionScore.weight` 保持配置值，不出现除零。 |
| AC-2-12 | 存在任意维度已核验的 `critical` Finding 时，结论为 `REQUEST_CHANGES`，不被其他维度高分抵消（不限于安全维度；阶段 6 起外部 A2A Agent 的已核验 `critical` Finding 同样适用）。 |
| AC-2-13 | 某个 Agent 失败（可用 Fake Agent 注入）时，异常被捕获并转为 `AgentResult(failed)`，其他结果保留，报告 `report_status = partial`，结论不为 `APPROVE`。**首次失败即终态，不重试**（任务 `max_retries = 0`）。 |
| AC-2-14 | 生成 Markdown 与 JSON 报告，JSON 通过 `ReviewReport` 校验，Markdown 内容与 JSON 一致。 |
| AC-2-15 | Final Reviewer 没有仓库写权限；LangGraph 在进程内运行，不引入 Redis / ARQ / MCP / A2A。 |
| AC-2-16 | **Final Reviewer 不创建 `AgentTask`**：任务树只有根任务与四个专业任务；`ExecutionSummary.total_tasks = 4`。 |
| AC-2-18 | **报告维度完整性**：`dimension_scores` 与 `agent_results` 始终包含四个固定维度；失败的 Agent 保留 `failed` 的 `AgentResult`；所有维度均失败时 `overall_score = null`、`report_status = partial`，结论在无已核验 `critical` Finding 时为 `COMMENT`、存在时为 `REQUEST_CHANGES`，`verdict_reasons` 说明原因（RP-15、RP-16、RP-06）。 |
| AC-2-17 | **不提前实现阶段 4 能力**：代码中没有重试循环、退避、`failed → pending` 的执行逻辑、持久化的失败记录与服务重启恢复。 |

### 5.4 测试验收标准

| 编号 | 验收项 |
| --- | --- |
| TC-2-01 | 阶段 0、1 的全部测试仍然通过。 |
| TC-2-02 | 使用 Fake / Mock LLM 对 Manager、各 Agent、Final Reviewer 进行单元测试，覆盖评分、去重、核验、阻断、部分完成逻辑，以及权重校验（`0 < w ≤ 1`、和为 1）与缺失维度的权重归一化（含全部维度为 `null` 时不除零）。 |
| TC-2-03 | 并行性测试：使用带固定延迟的 Fake Agent，断言总耗时小于串行耗时之和。 |
| TC-2-04 | 端到端“测试 A（正常执行）”通过。 |
| TC-2-05 | 在样例仓库上运行并**记录基线评估数据**（Precision、Recall、误报率、耗时），本阶段不设阈值，阈值在阶段 7 的评估体系中确定。 |

### 5.5 通过条件

AC-2-01 ～ AC-2-18 与 TC-2-01 ～ TC-2-05 全部满足，并留存一次完整运行的日志与报告作为验收证据。

### 5.6 不通过时需要修复的问题

| 现象 | 需要修复 |
| --- | --- |
| 耗时接近串行 | 检查是否真正并行（Fan-out 与异步调用）。 |
| `InvalidUpdateError` | 节点只返回自己负责的字段，列表使用 Reducer。 |
| 报告中的问题没有文件/行号/证据 | 加强 Agent 输出校验与 Final Reviewer 核验。 |
| 评分被硬编码或严重漏洞被抵消 | 改为配置化并补充阻断规则。 |
| Manager 直接生成最终结论 | 移至 Final Reviewer。 |

---

## 6. 阶段 3：SubAgent 两层架构与任务生命周期管理

### 6.1 阶段目标

以 Security Agent 为例，构建“专业 Agent → SubAgent”两层结构，实现二级任务拆解、父子任务管理、完成事件通知与并发限制。

### 6.2 交付物

Security SubGraph 与三个子任务（Dependency Scanner、Secret Scanner、Code Security Reviewer）、父子任务管理、`TaskEvent` 与进程内事件机制、并发限制（Semaphore，并设计全局限制）、事件与任务记录查询能力、测试。

### 6.3 功能验收标准

| 编号 | 验收项 |
| --- | --- |
| AC-3-01 | Security Agent 能创建三个子任务，子任务有唯一 `task_id` 与 `parent_task_id`。 |
| AC-3-02 | 子任务可并行执行；最大深度为 2，子任务不再创建子任务。 |
| AC-3-03 | 可通过 `parent_task_id` 查询某个父任务下的全部子任务。 |
| AC-3-04 | 子任务结束后执行顺序为：保存结构化结果 → 更新状态 → 发布事件。 |
| AC-3-05 | 事件（`task.completed` / `task.failed`）可被记录与查询。 |
| AC-3-06 | LangGraph 负责执行控制与汇合；事件仅用于通知与记录，两者职责不重复，父 Agent 不仅依靠事件监听判断子图完成。 |
| AC-3-07 | 单个子任务失败时，其他子任务的结果被保留。 |
| AC-3-08 | 父任务在所有必需子任务终态之前不会被标记为成功；按 `required` 规则得出 `completed / partial / failed`。 |
| AC-3-09 | **局部并发**：Security SubAgent 通过 `asyncio.Semaphore` 实现局部并发限制，初始测试配置 `security_subagents: 2`，运行期间观测到的最大并发数不超过 2。**全局并发限制在本阶段只完成设计（`global_subagents: 4`），不提前实现完整的全局调度**，全局限制的实现与验收在阶段 4。 |
| AC-3-10 | 汇总后的 Finding 满足证据合同，`agent_name` 统一、来源子任务可追溯。 |
| AC-3-11 | **任务树拓扑与派生权限校验（编排层）**：父任务必须存在且 `review_id` 一致；父子关系不得成环；最大深度为 2（深度 0 根任务、深度 1 专业任务、深度 2 SubAgent，深度 3 禁止创建）；仅 Manager 可创建深度 1 任务、Security Agent 可创建深度 2 任务，深度 2 的 SubAgent 不得再创建子任务。上述规则不由阶段 0 的单个 `AgentTask` Schema 校验，也不新增 `task_depth` / `depth` 字段。 |

### 6.4 测试验收标准

可复现的初始测试配置（数值仅用于测试复现，**不是生产环境的最终性能参数**；与 `architecture.md` §10.2 一致）：

```yaml
concurrency:
  security_subagents: 2
  global_subagents: 4
```

| 编号 | 验收项 |
| --- | --- |
| TC-3-01 | 阶段 0～2 的全部测试仍然通过。 |
| TC-3-02 | 并发上限测试：提交多于阈值的 SubAgent 任务（如 6 个，带固定延迟），**使用计数器记录运行期间观测到的最大并发数**，断言最大并发数 ≤ 2，而不是仅检查配置值；建议同时断言峰值达到 2，以证明并发确实发生。 |
| TC-3-03 | 局部失败测试：注入一个子任务失败，断言其余结果保留、父结果为 `partial`。 |
| TC-3-04 | 父子关系、任务树拓扑（父任务存在、无环、最大深度、派生权限）与事件顺序的单元测试。 |
| TC-3-05 | 端到端“测试 B（局部失败）”的进程内版本通过（重试部分在阶段 4 补全）。 |

### 6.5 通过条件

AC-3-01 ～ AC-3-11 与 TC-3-01 ～ TC-3-05 全部满足。

### 6.6 不通过时需要修复的问题

| 现象 | 需要修复 |
| --- | --- |
| 事件与 LangGraph 重复实现调度 | 事件只做通知与记录，调度交还 LangGraph。 |
| 父任务提前成功 | 加入必需子任务终态检查。 |
| 并发超限 | 修正 Semaphore 作用域，补全局限制。 |
| 一个子任务失败导致全部结果丢失 | 保留已完成子任务结果并改为 `partial`。 |

---

## 7. 阶段 4：Redis + ARQ 异步任务队列与失败恢复

### 7.1 阶段目标

解决三个问题：任务执行时间长怎么办、Agent 执行失败怎么办、服务重启后任务状态怎么办。

### 7.2 交付物

Docker Compose（Redis、PostgreSQL）、FastAPI 入队接口（`202 Accepted`）、ARQ Worker、任务状态机、重试与超时、幂等机制、三层并发控制、PostgreSQL 任务与结果持久化、LangGraph Checkpointer、持久化事件机制（Redis Streams 或等价方案）、Webhook 入口（HMAC 校验）、故障注入测试。

### 7.3 功能验收标准

| 编号 | 验收项 |
| --- | --- |
| AC-4-01 | FastAPI 不在请求线程中执行完整工作流，返回 `202 Accepted` 与 `review_id`，由 ARQ Worker 执行；`ReviewService` 逻辑与阶段 1～3 保持一致，CLI 仍可用。 |
| AC-4-02 | 任务状态机有合法迁移规则，非法迁移（如 `completed → running`）被拒绝。 |
| AC-4-03 | 可重试错误按退避（含抖动）有限重试，不可重试错误直接失败；每次失败原因被保存。 |
| AC-4-04 | 单次执行超时生效，超时按 `timeout` 处理。 |
| AC-4-05 | 同一 `delivery_id` 的 Webhook 重复发送：① 不产生重复的审查作业；② 不产生重复报告；③ 验证 HMAC-SHA256 签名（签名无效的请求被拒绝）。本阶段只验收 Webhook 接收与审查作业幂等，**不验收 GitHub PR 评论发布**（属阶段 7，见 AC-7-09）。 |
| AC-4-06 | 重复执行（Worker 中断后重新执行）不产生重复结果；数据库唯一约束生效。 |
| AC-4-07 | 全局、Agent、工具三层并发控制生效，超过最大并发的任务进入等待。**全局并发限制在本阶段实现**，初始测试配置 `global_subagents: 4`，运行期间观测到的全局最大 SubAgent 并发数不超过 4；Security 局部限制（`security_subagents: 2`）仍然有效。 |
| AC-4-08 | 任务状态、任务树与结果持久化于 PostgreSQL，可按 `review_id` 查询。 |
| AC-4-09 | Redis Worker 重启后，未完成的任务可恢复（Checkpointer 断点或重新入队），已完成的任务不会被重复执行。 |
| AC-4-10 | 子任务事件升级为可持久化、可确认消费的机制，不使用普通 Pub/Sub 作为可靠通知存储。 |
| AC-4-11 | PostgreSQL（业务权威）、Checkpointer（工作流状态）、Redis（队列/缓存）职责未混用。 |
| AC-4-12 | 支持失败任务的人工重跑（创建新任务）。 |

### 7.4 测试验收标准（故障注入）

| 编号 | 场景 | 期望 |
| --- | --- | --- |
| TC-4-01 | Security Agent 执行失败一次，第二次成功 | 最终成功，重试次数 = 1，失败原因被记录 |
| TC-4-02 | Performance Agent 超时 | 超时被检测，按策略重试或标记失败，其他 Agent 不受影响，报告 `partial` |
| TC-4-03 | Redis Worker 重启 | 任务可恢复，无重复结果 |
| TC-4-04 | 同一 `delivery_id` 的 Webhook 重复发送 | 只产生一个审查作业、一份报告；签名无效的请求被拒绝 |
| TC-4-05 | 多个仓库同时提交审查任务（使 SubAgent 总需求超过 4） | **使用计数器记录运行期间观测到的最大并发数**，全局最大并发 ≤ 4（而不是仅检查配置值），超出部分排队等待，全部最终完成 |
| TC-4-06 | 回归 | 阶段 0～3 的全部测试仍然通过 |

### 7.5 通过条件

AC-4-01 ～ AC-4-12 与 TC-4-01 ～ TC-4-06 全部满足，并满足最终要求：**任务不因单个 Agent 失败而使整个系统崩溃；重试次数可控；重复请求不产生重复报告；任务状态可查询；超过最大并发限制的任务必须等待。**

### 7.6 不通过时需要修复的问题

| 现象 | 需要修复 |
| --- | --- |
| 重复审查作业或重复报告 | 补 `delivery_id` 幂等检查与数据库唯一约束。 |
| 无限重试或重试风暴 | 设最大次数、指数退避与抖动，并区分不可重试错误。 |
| 重启后任务丢失或重复执行 | 完善持久化、Checkpointer 与状态校验。 |
| 三类状态职责混乱 | 按 `architecture.md` §5 重新划分。 |

---

## 8. 阶段 5：MCP 接入代码分析工具

### 8.1 阶段目标

验证 Agent 通过 MCP 标准化调用外部工具，并实现工具权限隔离。MCP 不负责 Agent 的任务规划。

### 8.2 交付物

独立运行的 Code Analysis MCP Server（`scan_security`、`check_quality`、`analyze_complexity`、`run_tests`、`get_coverage`、`get_file_content`）、MCP Client、Agent 工具白名单、受限容器测试执行、测试。

### 8.3 功能验收标准

| 编号 | 验收项 |
| --- | --- |
| AC-5-01 | MCP Server 可独立启动。 |
| AC-5-02 | MCP Client 能成功发现工具。 |
| AC-5-03 | Security Agent 能调用安全扫描工具；Testing Agent 能调用测试工具。 |
| AC-5-04 | 工具返回结果符合 Pydantic Schema，不合规视为工具错误。 |
| AC-5-05 | **未授权的 Agent 不能调用不属于自己的工具**，且被拒绝时有记录；客户端白名单生效（Agent 只能看到自己被授权的工具）。 |
| AC-5-06 | 所有工具校验仓库 ID、路径与执行参数；以 `repository_id` 引用仓库，拒绝路径穿越。 |
| AC-5-07 | `run_tests` 在受限容器中执行，MCP Server 不以高权限直接运行不可信代码。 |
| AC-5-08 | 工具调用被统一记录（工具名、参数摘要、耗时、状态）；Finding 的 `tool_evidence.raw_output_ref` 能指向工具原始输出。 |
| AC-5-09 | **服务端身份验证**：MCP Server 对每次调用验证调用方身份，无凭据或凭据无效的请求被拒绝。 |
| AC-5-10 | **服务端权限校验，默认拒绝**：服务端独立持有权限表，未明确授权的（身份、工具）组合一律拒绝；**绕过 MCP Client 直接向 Server 发起的越权请求同样被拒绝**。 |
| AC-5-11 | 服务端以已验证身份判定权限，**不信任请求体中自报的 `agent_name`**；伪造身份的请求被拒绝。 |
| AC-5-12 | 服务端工具发现结果按身份过滤，只返回被授权的工具。 |
| AC-5-13 | 凭据作用域受限（绑定 Agent 身份，并尽量绑定 `review_id` / `repository_id`）；跨审查、跨仓库的调用被拒绝；凭据不出现在 LLM 上下文、日志、任务合同和报告中。 |
| AC-5-14 | 允许与拒绝的调用均写入审计日志，越权尝试被单独标记。 |

### 8.4 测试验收标准

| 编号 | 验收项 |
| --- | --- |
| TC-5-01 | MCP Client 的工具发现与调用测试。 |
| TC-5-02 | 权限矩阵测试：每个 Agent 对每个工具的允许 / 拒绝结果与权限表一致（同时在客户端与服务端两层验证）。 |
| TC-5-03 | 路径穿越与非法仓库 ID 的拒绝测试。 |
| TC-5-04 | 阶段 0～4 的全部测试仍然通过。 |
| TC-5-05 | **绕过客户端的越权测试**：不经过 MCP Client，直接以某 Agent 的身份向 MCP Server 调用不属于它的工具，必须被服务端拒绝并写入审计日志。 |
| TC-5-06 | 身份伪造测试：使用 Testing 的凭据但在请求体中自报 `agent_name = SecurityAgent`，服务端按凭据身份判定，调用被拒绝。 |
| TC-5-07 | 无凭据 / 无效凭据 / 过期凭据的调用均被拒绝。 |
| TC-5-08 | 作用域测试：使用属于 `review-A` 的凭据访问 `review-B` 的 `repository_id`，被拒绝。 |
| TC-5-09 | 模拟客户端 Bug 或 Prompt Injection：故意让客户端白名单失效（放开所有工具），越权调用仍被服务端拦截。 |

### 8.5 通过条件

AC-5-01 ～ AC-5-14 与 TC-5-01 ～ TC-5-09 全部满足；用 MCP 工具跑出的审查结果与阶段 2～4 的本地工具结果在样例仓库上保持一致。

### 8.6 不通过时需要修复的问题

| 现象 | 需要修复 |
| --- | --- |
| 任意 Agent 都可调用所有工具 | 实现客户端白名单与**服务端授权**。 |
| 权限只在 Agent / MCP Client 侧限制，直连 Server 可越权 | 在 MCP Server 端增加身份验证与权限校验（默认拒绝），客户端白名单仅作辅助。 |
| 服务端信任请求体中自报的 Agent 名称 | 改为根据已验证的凭据确定身份。 |
| 凭据出现在 LLM 上下文或日志中 | 改为由客户端代码注入，并从日志与合同中移除。 |
| 工具可接收任意路径 | 改为 `repository_id` 并校验工作区边界。 |
| 测试在高权限环境运行 | 迁入受限容器。 |

---

## 9. 阶段 6：A2A 接入独立部署的外部代码审查 Agent

### 9.1 阶段目标

增加一个真正独立部署、与主系统不共享 Python Runtime 的外部 Agent（External Architecture Review Agent），通过 A2A 完成发现、委派、状态跟踪与 Artifact 接收。

### 9.2 交付物

外部 Agent 服务（`external_agents/code_audit_agent/`）、Agent Card、A2A Client、`external_review_node`、协议映射（A2A ↔ 内部合同）、失败降级策略、测试。

### 9.3 功能验收标准

| 编号 | 验收项 |
| --- | --- |
| AC-6-01 | 外部 Agent 可独立启动（如端口 9000），与主系统不共享运行时。 |
| AC-6-02 | 主系统可读取其 Agent Card（按所选 SDK 版本的 Schema 生成）。 |
| AC-6-03 | 主系统可通过 A2A 创建任务，外部 Agent 接收并执行。 |
| AC-6-04 | 主系统可跟踪任务状态（轮询或 SSE）。 |
| AC-6-05 | 外部 Agent 返回结构化 Artifact，主系统映射为合法的 `AgentResult`，其中 Finding 满足证据合同并经 Final Reviewer 核验。 |
| AC-6-06 | 外部 Agent 只获得必要的代码上下文。 |
| AC-6-07 | `external_review_node` 与四个本地 Agent 并行执行。 |
| AC-6-08 | 外部 Agent 不可用时，主系统记录失败并按策略重试或降级，其他 Agent 正常完成，输出 `partial` 报告。 |
| AC-6-09 | A2A 的 Task / Message / Part / Artifact 与内部 `AgentTask` / `AgentResult` 映射清晰并有文档。 |
| AC-6-10 | 外部 Agent 的结果放入 `external_agent_results`，不改变四个核心评分维度；外部 Finding 经同样的证据核验与去重后可进入最终 `findings`，但不参与四个核心维度的加权评分；外部失败时保留 `failed` 记录且 `report_status = partial`。 |

### 9.4 测试验收标准

| 编号 | 验收项 |
| --- | --- |
| TC-6-01 | 独立服务集成测试（启动外部 Agent，完成一次完整委派）。 |
| TC-6-02 | 端到端“测试 C（跨服务失败）”通过：外部 Agent 不可用 → 超时检测 → 重试或降级 → 其他 Agent 正常 → 部分完成报告。 |
| TC-6-03 | Artifact 不合规时被拒收并记录。 |
| TC-6-04 | 阶段 0～5 的全部测试仍然通过。 |

### 9.5 通过条件

AC-6-01 ～ AC-6-10 与 TC-6-01 ～ TC-6-04 全部满足。

### 9.6 不通过时需要修复的问题

| 现象 | 需要修复 |
| --- | --- |
| 外部 Agent 与主系统耦合（共享代码运行时） | 重新拆分为独立服务。 |
| 外部不可用导致主流程阻塞或崩溃 | 补超时、重试与降级。 |
| Artifact 绕过证据核验 | 经统一的合同校验与 Final Reviewer。 |

---

## 10. 阶段 7：统一 Trace、Token 成本统计和产品化部署

### 10.1 阶段目标

把系统提升为可演示、可追踪、可部署的完整应用：统一 Trace、Token 与成本、结构化日志、GitHub PR 集成、Web 界面与完整 Docker Compose 部署，并建立 Agent 评估体系。

### 10.2 交付物

统一 `trace_id` 与 OpenTelemetry Trace、LangSmith 调试接入、`TokenUsage` 与成本统计、结构化日志、GitHub PR Webhook 与评论回写、Streamlit Dashboard（四个页面）、完整 `docker-compose.yml`（`api`、`redis`、`worker`、`postgres`、`mcp-server`、`external-agent`、`dashboard`、沙箱运行器）、评估测试集与基准报告、`README` 中的四张架构图与演示、`docs/security.md`、`docs/failure_recovery.md`。

### 10.3 功能验收标准

完成一次**真实 PR 审查**后，可以查询：

| 编号 | 验收项 |
| --- | --- |
| AC-7-01 | 本次审查的完整 Trace（一个 `trace_id` 关联 Manager、各 Agent、SubAgent、MCP 调用、A2A Task、Final Reviewer）。 |
| AC-7-02 | 每个 Agent 的执行时间。 |
| AC-7-03 | 每个 Agent 的输入与输出 Token，**来源于模型响应的真实 `usage`**，非字符数估算。 |
| AC-7-04 | 每次 MCP 工具调用记录。 |
| AC-7-05 | 外部 A2A Task 的执行状态。 |
| AC-7-06 | 失败次数与重试记录。 |
| AC-7-07 | 总体模型调用成本，且币种与单价配置明确。 |
| AC-7-08 | 最终 Markdown 与 JSON 报告。 |
| AC-7-09 | GitHub PR 评论由受控发布模块发布，具备**独立的评论发布幂等机制**：同一审查结果被重复触发（如重复投递、Worker 重试）不会产生重复评论；以**评论发布幂等键**验证，相同幂等键的发布请求只产生一条评论。该项独立于阶段 4 的 Webhook 接收与审查作业幂等（AC-4-05）。 |
| AC-7-10 | Streamlit Dashboard 具备：创建审查、实时查看 Agent 状态、查看各 Agent 结果、查看最终报告与成本。 |
| AC-7-11 | `docker compose up` 能启动完整多服务环境，各服务健康。 |
| AC-7-12 | 日志统一为结构化格式并带 `trace_id`。 |
| AC-7-13 | 权限隔离与 Prompt Injection 防护有文档说明和测试证据。 |

### 10.4 测试验收标准

| 编号 | 验收项 |
| --- | --- |
| TC-7-01 | 端到端测试 A、B、C **三个场景全部通过**。 |
| TC-7-02 | 评估测试集至少包含：明确的 SQL 注入、硬编码密钥、高复杂度函数、性能问题、覆盖率不足的样例。 |
| TC-7-03 | 输出评估指标：Precision、Recall、False Positive Rate、Task Success Rate、Recovery Rate、Average Latency、Token Cost，并与单 Agent 基线对比，说明多 Agent 是否带来改进。 |
| TC-7-04 | 阶段 0～6 的全部测试仍然通过。 |
| TC-7-05 | 在全新环境中按 `README` 能够完成部署并跑通一次审查。 |

### 10.5 通过条件

AC-7-01 ～ AC-7-13 与 TC-7-01 ～ TC-7-05 全部满足，并留存真实 PR 审查的演示记录。

### 10.6 不通过时需要修复的问题

| 现象 | 需要修复 |
| --- | --- |
| Trace 断链 | 在所有 Agent、SubAgent、MCP、A2A 调用中传递并关联 `trace_id`。 |
| Token 成本为估算值 | 改用模型响应的 `usage`。 |
| 评论重复发布 | 补发布幂等键。 |
| Compose 部署无法一键启动 | 修正服务依赖、健康检查与配置。 |

---

## 11. 总验收矩阵（跨阶段）

| 验收模块 | 必须验证的内容 | 验收方式 | 阶段 |
| --- | --- | --- | --- |
| 工程基础与合同 | 环境、目录、文档、Schema | 命令与单元测试 | 0 |
| GitHub 接入 | 仓库获取、Commit 固定 | 真实仓库测试 | 1 |
| Manager | 任务规划和分发 | 检查 Task Plan | 2 |
| Supervisor-Worker | 四个 Agent 并行 | Trace / 时间线 | 2 |
| Final Reviewer | 证据核验、去重、评分、阻断 | 伪造 Finding 与样例仓库 | 2 |
| SubAgent | 二级任务创建和汇总 | 检查 Parent ID | 3 |
| Announce | 完成事件通知 | 事件日志 | 3 |
| 失败恢复 | 重试、超时、部分失败 | 故障注入 | 4 |
| 并发控制 | 全局及局部限制 | 并发压力测试 | 3～4 |
| MCP | 工具发现和调用 | MCP Client 测试 | 5 |
| A2A | 远程 Agent 通信 | 独立服务测试 | 6 |
| Token 统计 | 各 Agent 使用量 | 模型 `usage` 记录 | 7 |
| Trace | 全链路追踪 | Trace 查询 | 7 |
| 报告 | Markdown、JSON | Schema 校验 | 1～7 |
| GitHub 集成 | PR 评论 | 真实 PR 验收 | 7 |
| Docker | 多服务部署 | Compose 启动 | 7 |

### 三个必须完成的端到端测试

| 测试 | 流程 | 说明了什么 |
| --- | --- | --- |
| **测试 A：正常执行** | 真实仓库提交 → 多个 Agent 执行 → 结果汇总 → 最终报告 | 主流程闭环 |
| **测试 B：局部失败** | Security Agent 内部一个 SubAgent 失败 → 重试 → 事件通知 → Security Agent 汇总 → 最终报告 | 父子任务与失败恢复 |
| **测试 C：跨服务失败** | 外部 A2A Agent 不可用 → 超时检测 → 重试或降级 → 其他 Agent 正常完成 → 输出部分完成报告 | 跨服务容错 |

> 三种场景全部跑通，才能说明真正掌握了多 Agent 工程编排，而不仅仅是调用了几个 LLM。

### 评估指标定义（阶段 7 建立，阶段 2 起记录基线）

| 指标 | 目的 |
| --- | --- |
| Precision | 检测结果中有多少是真实问题 |
| Recall | 实际问题有多少被检测出来 |
| False Positive Rate | 误报比例 |
| Task Success Rate | Agent 任务成功率 |
| Recovery Rate | 失败恢复成功率 |
| Average Latency | 平均执行耗时 |
| Token Cost | 单次审查成本 |

---

## 修订记录

| 项目 | 内容 |
| --- | --- |
| 修订日期 | 2026-11-09 |
| 修订类型 | v1.0 冻结前跨文档一致性修订（D-1～D-7） |
| 修订内容 | ① 规则追溯排除列表移除 ST-05，ST-05 由 `is_transition_allowed()` 的真实测试覆盖（D-5）；② AC-0-24 按实际阶段标注流程：阶段 2 实现、阶段 3 实现、设计预留，不再笼统写“后五项为设计”（D-6）；③ AC-0-29 区分合法完整示例、明确标注的非法示例与非模型 JSON 片段（D-7）；④ 明确任务树深度/父任务存在性/环检测/派生权限属于阶段 3 验收（AC-3-11），不属于阶段 0 单模型 Schema 验收（D-4）；⑤ 补充全 null 报告的已核验 `critical` 例外、配置权重与计算时归一化口径（D-1～D-3）。 |
| 数据合同权威顺序 | `task_contracts.md` 是数据合同唯一权威；本文档不得与其冲突。 |
| 阶段归属 | 任务树拓扑与派生权限属于阶段 3；失败重试、持久化与调度属于阶段 4。 |
| 架构影响 | 未改变整体系统架构、阶段划分与核心业务方向。 |
