# Stage 1 实施前检查报告

- 报告日期：2026-11-09
- 项目：Multi-Agent Code Review System（`d:\GitHub\multi-agent-review`）
- 检查对象：阶段 0 工作区、六份实施依据、阶段 0 代码/Schema/测试、AC-1-01～AC-1-15、TC-1-01～TC-1-06
- 本报告性质：第一轮只读检查，不包含任何代码修改、依赖安装或核心文档修改
- 本轮新增文件：仅本报告（`reports/*` 已被 `.gitignore` 忽略，不进入版本库）

---

## 0. 结论摘要

**结论：暂缓进入 Stage 1.1（BLOCKED，待 P0 裁定）。**

阶段 0 基线完好：工作区 204 条单元测试全部通过（0 failure / error / skip / xfail），四个核心 Schema、`Settings`、文档与验收报告均可作为阶段 1 的基础。

但六份实施依据之间存在 **13 项 P0 级冲突/缺口**，其中至少 8 项会直接改变 Stage 1.1～1.6 的实现范围、数据产物、依赖或安全边界；另有 20 余项实施级缺口需要明确默认值。按照《阶段1_Prompt》§1.2 与 §十七的要求，相关实现应暂停，先由项目负责人裁定。

**不建议在裁定前直接开始 Stage 1.1**，原因是：

1. 阶段 1 报告产物是 4 件还是 5 件（是否含 `report.json`）未定，直接决定 Stage 1.6 的数据模型与 AC-1-15 验收口径。
2. FastAPI 是 P0 必做还是可选未定，直接决定 Stage 1.6 的工作量与 AC-1-14 验收方式。
3. 阶段 1 是否实现 LLM 辅助分析、使用何种客户端未定，直接决定依赖清单与 AC-1-13 的实现位置。
4. “可信 Fixture 是否允许在宿主机执行 pytest/coverage”未定，直接决定 AC-1-09 能否成立、AC-1-10 的边界。
5. 资源阈值、URL 白名单、敏感文件清单等安全参数未定，直接决定 Stage 1.1/1.2 的配置与测试。
6. 新增依赖需要项目负责人确认，未确认前不得安装。
7. Repository Manager / Repository Inspector / AnalysisTool 在 `architecture.md` 中没有对应名称与路径，需要确认目录映射。
8. `acceptance.md` 的阶段 1 AC 编号与《阶段1_Prompt》§14 的映射表整体错位，必须明确以原文编号为准。

---

## 1. 检查方法与证据

### 1.1 检查范围

| 类别 | 内容 |
|---|---|
| 实施总计划 | `项目总框架与实施计划V2.0.md`（2411 行，工作区版本，含未提交修改） |
| 核心文档 | `docs/requirements.md`（587 行）、`docs/architecture.md`（732 行）、`docs/workflow.md`（803 行）、`docs/task_contracts.md`（1464 行）、`docs/acceptance.md`（751 行） |
| 阶段 0 代码 | `config/settings.py`、`src/code_review/schemas/{task,result,report}.py`、`src/code_review/schemas/__init__.py` |
| 阶段 0 测试 | `tests/unit/test_task_schema.py`、`test_result_schema.py`、`test_report_schema.py` |
| 工程配置 | `environment.yml`、`pytest.ini`、`.env.example`、`.gitignore`、`README.md` |
| 运行环境 | 项目 Conda 环境、Git CLI、pytest、已安装包清单 |

### 1.2 检查方式

- 六份文档均按工作区当前版本**全文通读**（由六个只读分析代理分别完成，主会话汇总核对）。
- 阶段 0 代码逐文件读取；测试实际执行；环境与工具版本实际探测。
- 未修改任何文件、未安装任何依赖、未执行 git 写操作。
- 未使用旧版本资料库副本覆盖当前文件。

### 1.3 工作区状态（检查时）

```text
M  docs/architecture.md
M  docs/requirements.md
M  项目总框架与实施计划V2.0.md
?? 阶段1_Prompt.md
```

三份文档的未提交修改内容：

- `architecture.md`：补充 LangChain Chat Models / Provider Adapter / Redis-ARQ-LangGraph 边界说明；改写 §7.2 import 方向表述；删除 `reports/.gitkeep`（§12.1、§12.3）。
- `requirements.md`：§11.3 标题由“待确认事项（建议在阶段 1 开始前确认）”改为“已确认事项（建议在阶段 1 开始前确认）”，列名由“建议默认值”改为“默认值”。
- `项目总框架与实施计划V2.0.md`：§1.3 技术栈表大幅扩写，新增“进一步详细划分”表，其中 Semgrep、Gitleaks、pip-audit/OSV-Scanner、LangChain Chat Models、Provider Adapter 被标注为“阶段 1”；Docker Sandbox Runner 标注为“阶段 7”。

**注意**：文档头均自称“已冻结（Frozen）”，但工作区存在未提交修改，冻结状态与当前内容不一致。阶段 1 开始前应确认这些修改是否作为新的冻结基线提交。

【人工意见】：已人工确认这些修改并让CC作为新的冻结基线提交。

---

## 2. 阶段 0 基线核查

### 2.1 现有目录与文件

```text
multi-agent-review/
├─ .env.example
├─ .gitignore
├─ CLAUDE.md
├─ environment.yml
├─ pytest.ini
├─ README.md
├─ 阶段1_Prompt.md                 # 未跟踪
├─ 项目总框架与实施计划V2.0.md
├─ config/
│  └─ settings.py
├─ docs/
│  ├─ requirements.md
│  ├─ architecture.md
│  ├─ workflow.md
│  ├─ task_contracts.md
│  └─ acceptance.md
├─ Prompt/
│  ├─ 阶段0_Prompt.md
│  ├─ 0.3阶段任务要求.md
│  └─ 0.4阶段任务要求.md
├─ reports/                        # 本地验收报告，gitignored
├─ src/
│  └─ code_review/
│     ├─ __init__.py
│     └─ schemas/
│        ├─ __init__.py
│        ├─ task.py
│        ├─ result.py
│        └─ report.py
└─ tests/
   ├─ __init__.py
   └─ unit/
      ├─ __init__.py
      ├─ test_task_schema.py
      ├─ test_result_schema.py
      └─ test_report_schema.py
```

阶段 1 目录 `services/`、`tools/`、`repository/`、`reporting/`、`cli/`、`api/` 均**不存在**；`pyproject.toml`、`review_rules.yaml`、`reports/.gitkeep` 也不存在。

### 2.2 配置基线

`config/settings.py` 的 `Settings(BaseSettings)` 共 10 个字段：

| 字段 | 类型 | 默认值 | 约束 |
|---|---|---|---|
| `app_name` | `str` | `"multi-agent-code-review"` | 非空 |
| `app_env` | `str` | `"development"` | 非空 |
| `debug` | `bool` | `False` | — |
| `llm_provider` | `str` | `"openai_compatible"` | 非空 |
| `llm_base_url` | `str \| None` | `None` | 空串转 `None` |
| `llm_api_key` | `SecretStr \| None` | `None` | 空串转 `None`；SecretStr |
| `llm_model` | `str \| None` | `None` | 空串转 `None` |
| `log_level` | `str` | `"INFO"` | 仅 DEBUG/INFO/WARNING/ERROR/CRITICAL |
| `max_concurrent_agents` | `int` | `4` | `ge=1, le=64` |
| `max_retry_attempts` | `int` | `2` | `ge=0, le=10` |

- 无 `env_prefix`；环境变量名即字段名（大小写不敏感）。
- 无 `get_settings()` 单例或依赖注入封装。
- `extra="ignore"`，新增环境变量不会报错。

### 2.3 数据合同基线

| 模型 | 文件 | 关键约束 |
|---|---|---|
| `AgentTask` | `schemas/task.py` | `extra="forbid"`；状态 `pending/running/completed/failed/cancelled`；`max_retries=2`；TK-13 状态-时间戳一致性 |
| `ErrorInfo` | `schemas/task.py` | `error_type: str`；`retryable: bool`；UTC 时间；`details` |
| `Finding` | `schemas/result.py` | `extra="forbid"`；`finding_id/agent_name/category/severity/title/description/evidence/recommendation/confidence` 必填；FD-01～FD-08 校验；`verification_status` 默认 `unverified` |
| `ToolEvidence` | `schemas/result.py` | `tool_name`、`rule_id`、`tool_version`、`raw_output_ref`；无 severity/line 字段 |
| `AgentResult` | `schemas/result.py` | `extra="forbid"`；`commit_sha` 40 位小写十六进制；RS-01～RS-10 |
| `ReviewReport` | `schemas/report.py` | `extra="forbid"`；`dimension_scores`/`agent_results` 必须且仅含四个核心维度；RP-01～RP-20 |
| `DimensionScore` | `schemas/report.py` | `score` 可为 null；`weight` 配置值；`status` 与 AgentResult 一致 |
| `TestSummary` | `schemas/report.py` | `execution_status=executed/not_executed/failed`；`not_executed` 时计数与覆盖率必须全 null 且有 `reason` |
| `ExecutionSummary` | `schemas/report.py` | 6 个字段；`total_tasks` 为深度 1 专业任务数 |
| `CostSummary` | `schemas/report.py` | 默认全 0；阶段 7 前保持默认值 |

- `schema_version` 仅存在于 `AgentTask`、`AgentResult`、`ReviewReport` 三个顶层模型；`Finding`、`ToolEvidence`、`ErrorInfo` 及各子模型没有该字段。
- 所有模型均 `extra="forbid"`。禁止传入额外的参数（或字段）
- 阶段 0 的三个 Schema 文件**不得修改**（《阶段1_Prompt》§10.2）。

### 2.4 测试基线

实际执行结果：

```text
pytest tests/unit -q
204 passed in 0.48s
```

| 文件 | 测试函数数 | 收集用例数 | 覆盖规则 |
|---|---:|---:|---|
| `test_task_schema.py` | 28 | 74 | TK-01～TK-13；ST-01/02/03/05；JS-11 |
| `test_result_schema.py` | 36 | 59 | FD-01～FD-08；RS-01～RS-10；JS-05/11 |
| `test_report_schema.py` | 62 | 71 | RP-01～RP-20；JS-02/11 |
| **合计** | **126** | **204** | — |

- 精确结果：**204 passed / 0 failed / 0 skipped / 0 error / 0 xfail**。
- `test_report_schema.py` 运行时读取 `docs/task_contracts.md` 的 JSON 示例块；修改合同文档会影响该测试。
- 未被单元测试直接覆盖的规则 ID：`FD-09`、`FD-10`、`ST-04`、`ST-06`、`ST-07`（按阶段 0 设计属于编排层/后续层）。

### 2.5 环境基线

| 项目 | base 环境 | 项目环境 `multi-agent-review` |
|---|---|---|
| Python | 3.12.4 | 3.12.16 |
| pytest | 7.4.4 | 9.2.0 |
| FastAPI | 0.110.2 | 0.162.2 |
| pydantic | 2.13.4 | 2.14.3 |
| pydantic-settings | 2.8.1 | 2.16.2 |
| structlog | 未安装 | 26.1.0 |
| httpx | 0.28.1 | 0.28.1 |
| uvicorn | 0.29.0 | 0.54.0 |
| python-dotenv | 1.0.1 | 1.2.4 |
| GitPython | 3.1.37 | **未安装** |
| ruff / bandit / radon / coverage | 未安装 | **未安装** |
| PyYAML | — | **未安装** |
| 禁止项探测 | `FORBIDDEN: ['mcp','redis','sqlalchemy','streamlit']` | `FORBIDDEN: []`；`PASSIVE-ALLOWED: ['opentelemetry-api']` |

- Git CLI：`git version 2.49.0.windows.1`。
- **环境错位风险**：当前 shell 的 `python` 指向 base，`pytest` 指向项目环境；所有阶段 1 命令必须显式使用 `conda run -n multi-agent-review` 或项目环境绝对路径，不能使用裸 `python`/`python -m pytest`。
- base 环境含禁止依赖，不能作为阶段 1 验收环境。
- `code_review` 包未安装；pytest 之外导入需 `PYTHONPATH=src`，无 `pyproject.toml`、无 console script。

### 2.6 阶段 0 基线结论

**PASS（带环境注意点）**：代码、Schema、测试、配置、文档基线可用；204 条测试真实通过；阶段 1 目录尚不存在，无越界实现。需要在阶段 1 开始前处理的环境事项：固定项目环境命令、锁定新依赖版本、明确 `PYTHONPATH`/CLI 入口方式。

---

## 3. 六份实施依据的关键结论

### 3.1 《项目总框架与实施计划 V2.0》

- 阶段 1 目标：“先不引入多 Agent，构建能够真正审查代码的基础工具链。这一步是整个项目的地基。”
- 阶段 1 任务：1.1 仓库获取（URL 校验、大小/文件数/单文件/下载时间限制、只读工作区、Commit 固定）；1.2 源码遍历与语言识别；1.3 Ruff/Bandit/Radon/Pytest/Coverage；1.4 基础报告。
- 阶段 1 验收：真实 Python 仓库 Clone、固定 SHA、识别代码文件、过滤敏感/大型文件、三个静态工具输出、可信样例 Pytest/Coverage、Markdown 报告、不可信仓库不在宿主机执行测试；未建立安全环境时标注 `NOT_EXECUTED`。
-  **冲突点**：§1.3 新增详细技术栈表把 Semgrep、Gitleaks、pip-audit/OSV-Scanner、LangChain Chat Models、Provider Adapter 标为“阶段 1”；但阶段 1 任务 1.3 只列 Ruff/Bandit/Radon/Pytest/Coverage，`requirements.md` §7.2 阶段 1 也未列 Semgrep/Gitleaks/pip-audit。该表与阶段 1 任务清单不一致。
- 阶段 1 不引入 Redis/ARQ、多进程 Worker、任务队列、分布式状态管理。

### 3.2 `docs/requirements.md`

阶段 1 直接相关 FR：

| 编号 | 要求 |
|---|---|
| FR-1.1 | CLI 入口提交审查（阶段 1～3 主要验收入口） |
| FR-1.2 | `POST /api/reviews`，请求含 `repository_url`、`branch`；CLI 与 API 复用同一个 `ReviewService`；P0，阶段 1 |
| FR-1.3 | 仅 HTTPS GitHub URL，限制域名与端口；防 SSRF、恶意 Git URL、本地路径穿越 |
| FR-1.4 | 获取仓库元数据、Clone、固定本次审查 Commit SHA、生成审查上下文 |
| FR-1.5 | 仓库大小、文件数量、单文件大小、下载时间限制 |
| FR-1.6 | 遍历源码、识别语言、过滤二进制/大文件/`.git`/`node_modules`/`.venv`、记录路径/语言/行数/大小 |
| FR-1.7 | 不读取 `.env`、私钥、凭证等敏感文件作为 LLM 上下文 |
| FR-1.8 | 仓库工作区默认只读 |
| FR-2.1 | Ruff、Bandit、Radon 结构化结果 |
| FR-2.2 | Pytest 与 Coverage.py，仅对可信测试仓库执行 |
| FR-2.3 | 外部不可信仓库不在宿主机执行测试/安装/构建，状态 `not_executed` |
| FR-2.4 | 静态分析工具超时、输出大小与资源限制 |
| FR-2.5 | 输出 `metadata.json`、`static_analysis.json`、`test_report.json`、`report.md` |
| FR-9.1 | 最终产出 Markdown 与 JSON 报告，JSON 报告必须符合 `ReviewReport` Schema（“1 起”） |
| FR-9.4 | 报告数据必须来自真实代码分析与模型调用 |

关键 NFR：NFR-S1（不可信仓库不在宿主机执行）、NFR-S2（Docker 沙箱）、NFR-S3（Prompt Injection）、NFR-S5/S7（密钥不写入日志/合同/报告、证据脱敏）、NFR-R2（所有外部调用设超时）、NFR-C3（测试/覆盖率只能来自真实工具，未执行 `not_executed`）、NFR-M2（Provider 抽象，第一版兼容 OpenAI API 的国内服务）、NFR-M4（依赖分阶段引入）、NFR-M6（CLI/API 共用 ReviewService）、NFR-T1/T3（每阶段有测试；单测 Mock/Fake）。

§11.3 已确认事项 D1–D4：

| 编号 | 事项 | 默认值 | 对阶段 1 的影响 |
|---|---|---|---|
| D1 | Final Reviewer 核验/去重/评分是纯确定性还是混合 | 核验与评分用确定性代码；LLM 仅摘要与解释 | 阶段 1 若用 LLM，只能解释，不能生成评分/核验结论 |
| D2 | 仓库大小/文件数/单文件/下载超时阈值 | 阶段 1 在 `config/settings.py` 定义，并在 `acceptance.md` 记录 | 阶段 1 必须产出阈值配置与验收记录；当前 `acceptance.md` 无阈值 |
| D3 | Provider 具体选择与 `.env` 变量命名 | 阶段 1 确定；`.env.example` 只放占位符 | 阶段 1 需确定 LLM Provider 与变量名 |
| D4 | 是否支持私有仓库 | 不支持 | 阶段 1 只面向公开仓库/本地可信测试仓库 |

### 3.3 `docs/architecture.md`

- 阶段 1 引入的目录（§7.1）：
  - `src/code_review/api/`：FastAPI 路由、Webhook、请求/响应模型（阶段 1）。
  - `src/code_review/services/`：`ReviewService`，固定文件名 `review_service.py`（阶段 1）。
  - `src/code_review/tools/`：GitHub、仓库、静态分析、测试等工具本地实现（阶段 1）。
  - `src/code_review/reporting/`：报告生成、Markdown、GitHub 评论（1～7）。
- 阶段 2 起：`agents/`、`graph/`；阶段 3～4：`orchestration/`；阶段 4：`workers/`、`storage/`；阶段 5：`mcp/`；阶段 6：`a2a/`、`external_agents/`；阶段 7：`observability/`。
- 依赖规则 DR-1～DR-9：`schemas` 最底层不导入业务模块；`agents` 不得导入 `graph`/`services`/入口层；入口层只调用 `ReviewService`；`ReviewService` 固定 `services/review_service.py`；`reporting` 由 `services` 调用。
- **重要缺口**：`architecture.md` 全文没有 `Repository Manager`、`Repository Inspector`、`AnalysisTool`、`repository/`、`inspectors/` 的名称或定义；阶段 1 可选路径只有 `tools/`、`services/`、`reporting/`、`api/`。`阶段1_Prompt.md` 使用这些名称并要求“以 architecture.md 为准”，但被引用文档 architecture.md 没有对应设计。
- 报告产物：§3⑦ 列 5 件（`metadata.json`、`static_analysis.json`、`test_report.json`、`report.md`、`report.json`）；§3⑨ 要求 JSON 符合 `ReviewReport`；未写 `reports/<review_id>/` 子目录形式（仅 `reports/`）。
- §6.1 的“阶段 1～3 单进程执行”图仍画 `ReviewService -> LangGraph 工作流`，与 `graph/` 属阶段 2、阶段 1 禁止 LangGraph 冲突。

### 3.4 `docs/workflow.md`

- §10 阶段 1 定义：“线性流程：获取仓库 → 文件解析 → 静态分析（及可信仓库的测试）→ 单 Agent 基础报告；CLI 与 FastAPI 共用 `ReviewService`。”
- 阶段 1 硬约束：
  - 仅 HTTPS GitHub 地址，限制域名与端口，拒绝本地路径/非 GitHub/带凭据 URL。
  - Clone 后固定完整 40 位 Commit SHA，所有行号对应此 SHA。
  - 过滤二进制、大文件、`.git`、`node_modules`、`.venv`；敏感文件不得进入 LLM 上下文。
  - 工作区默认只读；不执行不可信仓库安装/构建/测试脚本。
  - 外部不可信仓库测试状态 `not_executed`，`reason` 必须说明；`passed/failed/skipped/coverage` 全 null。
  - 先生成 `ReviewReport`（`report.json`），再由同一对象渲染 `report.md`；`report.json` 必须通过 Schema 校验。
- **缺口**：重定向策略、SSRF 显式防护、子模块、Git Hook、临时目录清理、命令/参数注入、工具超时数值、pytest 超时、输出大小上限、Prompt Injection、可信级别判定、阶段 1 单 Agent 的失败语义，均未规定。
- §8.7 的 Markdown 结构为 8 个区块，与 `阶段1_Prompt.md` §10.1 的 12 个部分不一致。

### 3.5 `docs/task_contracts.md`

- 已定义且与阶段 0 实现一致：`Finding`、`ToolEvidence`、`AgentResult`、`ErrorInfo`、`AgentTask`、`ReviewReport`、`DimensionScore`、`TestSummary`、`ExecutionSummary`、`CostSummary`。
- `ExecutionSummary` **存在**：§9.2，6 个字段（`total_tasks`、`completed_tasks`、`partial_tasks`、`failed_tasks`、`cancelled_tasks`、`duration_seconds`），是 `ReviewReport` 必填字段；阶段 1 不生成 `ReviewReport`，因此不需要在阶段 1 产物中使用它。
- `ToolExecutionResult` **不存在**于合同；仅《阶段1_Prompt》§6.4 建议抽象。阶段 1 需要自定义内部工具执行结果模型。
- 四种基础产物（`metadata.json`、`static_analysis.json`、`test_report.json`、`report.md`）**没有字段级合同**；`task_contracts.md` 只在 `raw_output_ref` 示例中引用 `static_analysis.json`/`test_report.json` 的 JSON Pointer。
- `Finding` 关键规则：FD-01 A/B 类证据至少一类；FD-02 `critical/high` 必须有代码位置；FD-03 `file_path` 与 `start_line` 成对；FD-05 POSIX 相对路径；FD-06 confidence ∈ [0,1]；FD-08 severity 五枚举；FD-09 专业 Agent 不得写 `verified`（编排层检查）；FD-10 敏感值脱敏。
- `TestSummary.not_executed`：四个计数与覆盖率必须全 null，`reason` 非空（RP-09）。
- `ReviewReport` 只能由 Final Reviewer 生成；阶段 1 不得为生成它而伪造四个 Agent 结果。
- 阶段 1 单 Agent 的 `agent_name`/`task_type` 在 §4.3 注册表中没有条目；工具生成的 Finding 的 `agent_name` 归属也未规定。
- `schema_version` 只要求三个顶层模型；`Finding`/`ToolEvidence` 没有版本字段。

### 3.6 `docs/acceptance.md`

- 文档第 13 行明确：阶段 1～7 的标准“进入对应阶段前再细化阈值与命令”；当前阶段 1 只有 §4.3/§4.4 的 15 条 AC 与 6 条 TC，每条形如“编号 | 验收项”，**没有验证方式、期望结果、命令或阈值**。
- §4.2 阶段 1 交付物：GitHub 仓库获取模块（含安全校验与 Commit 固定）、文件解析器、Ruff/Bandit/Radon、对可信仓库的 Pytest/Coverage、`ReviewService`、CLI、**可选的** `POST /api/reviews`、LLM Provider（兼容 OpenAI API 的国内模型服务）、四件基础报告、单元与集成测试、受控可信测试仓库。
- §4.5 通过条件：AC-1-01～AC-1-15 与 TC-1-01～TC-1-06 全部满足；样例仓库为自己编写或确认可安全执行；未对外部不可信仓库在宿主机执行任何代码。
- AC-1-01～AC-1-15 的实际编号（**与《阶段1_Prompt》§14 的映射表不一致**）：
  - AC-1-01 Clone + 完整 Commit SHA 固定
  - AC-1-02 URL 校验（HTTPS GitHub、拒绝 http/非 GitHub/非常规端口/带凭据/本地路径/file://、防 SSRF 与路径穿越）
  - AC-1-03 资源限制（仓库大小、文件数、单文件大小、下载时间；拒绝或截断并记录）
  - AC-1-04 源码文件识别与过滤（路径、语言、行数、大小；过滤二进制、大文件、`.git`/`node_modules`/`.venv`）
  - AC-1-05 敏感文件不进入 LLM 上下文（含 `.env`、私钥、凭证的样例仓库验证）
  - AC-1-06 Ruff 结构化结果
  - AC-1-07 Bandit 结构化结果
  - AC-1-08 Radon 结构化结果
  - AC-1-09 Pytest 对可信测试仓库执行 + Coverage.py 生成可信样例覆盖率报告
  - AC-1-10 外部不可信仓库不在宿主机执行测试/安装/构建；状态 `not_executed` + 原因；不伪造
  - AC-1-11 静态分析工具超时、输出大小与资源限制
  - AC-1-12 仓库工作区只读，分析不修改原始代码
  - AC-1-13 LLM 仅解释静态分析结果与补充语义问题；模型 Finding 满足证据合同，不合规丢弃并记录
  - AC-1-14 CLI 与 FastAPI（若实现）共用同一个 `ReviewService`；HTTP 中不执行长时间运行 Agent 工作流
  - AC-1-15 生成 `reports/<review_id>/` 下四个基础输出文件；Markdown 可读；JSON 符合 `task_contracts.md`
- TC-1-01 阶段 0 全部测试回归；TC-1-02 URL 校验器/文件收集器/过滤规则/工具输出解析器单测且离线；TC-1-03 自编写可信测试仓库集成测试覆盖 AC-1-01～AC-1-15；TC-1-04 一次真实 GitHub Clone 验证（记录 SHA 与输出，可手动）；TC-1-05 安全用例（恶意 URL、路径穿越、敏感文件仓库、超大文件）；TC-1-06 一次真实模型调用冒烟测试（记录模型名与 `usage`，单独标记，不纳入常规单测）。
- **结论体系冲突**：`acceptance.md` 只有“通过/不通过”，明确“不设有条件通过”；《阶段1_Prompt》§19 定义 PASS/BLOCKED/FAIL，并允许无 API Key 时记录 BLOCKED/NOT RUN。TC-1-06 在无 API Key 时如何结论，需要裁定。

---

## 4. AC-1-01～AC-1-15 对照矩阵

> 以 `docs/acceptance.md` 原文编号为准。状态列“未实现”指阶段 0 当前状态。

| AC | acceptance.md 要求（摘要） | 计划实现组件 | 验证方式/证据 | 子阶段 | 当前状态 |
|---|---|---|---|---|---|
| AC-1-01 | Clone 指定 GitHub 仓库，固定完整 Commit SHA 并写入审查上下文 | `tools/repository_manager.py` | 单测 mock/临时仓库 + 真实 Clone 证据（URL、分支、`git rev-parse HEAD`、SHA 一致） | 1.1 | 未实现 |
| AC-1-02 | 仅 HTTPS GitHub；拒绝 http、非 GitHub、非常规端口、带凭据、本地路径、`file://`；防 SSRF/路径穿越 | `tools/url_validator.py` | 参数化安全单测 + TC-1-05 | 1.1 | 未实现 |
| AC-1-03 | 仓库大小、文件数、单文件大小、下载时间限制；超限拒绝或截断并记录 | `repository_manager.py` + `Settings` | 伪造大小/超时单测 + 超大文件集成测试 + 记录检查 | 1.1/1.2 | 未实现 |
| AC-1-04 | 识别源码文件并输出路径/语言/行数/大小；过滤二进制、大文件、`.git`/`node_modules`/`.venv` | `tools/repository_inspector.py`、`file_filters.py` | 单测 + Fixture 仓库统计断言 | 1.2 | 未实现 |
| AC-1-05 | `.env`、私钥、凭证不进入 LLM 上下文（样例仓库验证） | Inspector 敏感清单 + LLM 上下文构造器 | Mock LLM 捕获 Prompt，断言敏感值不出现；产物/日志脱敏检查 | 1.2/1.5 | 未实现 |
| AC-1-06 | Ruff 输出结构化检查结果 | `tools/ruff_tool.py` | 真实 Ruff 执行 + JSON 解析单测 + Fixture 已知问题 | 1.3 | 未实现 |
| AC-1-07 | Bandit 输出结构化安全检查结果 | `tools/bandit_tool.py` | 真实 Bandit 执行 + severity/confidence/证据映射单测 | 1.3 | 未实现 |
| AC-1-08 | Radon 输出结构化复杂度结果 | `tools/radon_tool.py` | 真实 Radon 执行 + CC/MI 解析单测 | 1.3 | 未实现 |
| AC-1-09 | Pytest 对可信测试仓库执行；Coverage.py 生成可信样例覆盖率报告 | `tools/pytest_tool.py`、`coverage_tool.py` + 可信 Fixture | 集成测试真实执行；解析 passed/failed/skipped/coverage | 1.4 | 未实现 |
| AC-1-10 | 外部不可信仓库不在宿主机执行测试/安装/构建；`not_executed` + 原因；不伪造 | 测试执行门禁 + `test_report.json` | 恶意 Fixture（若执行会写标记文件）验证未执行；状态/null 语义断言 | 1.4 | 未实现 |
| AC-1-11 | 静态分析工具有超时、输出大小与资源限制 | `tools/subprocess_runner.py` + tool 配置 | 挂起脚本超时、超长输出截断、退出码异常单测 | 1.3 | 未实现 |
| AC-1-12 | 仓库工作区只读，分析不修改原始代码 | `repository_manager.py` + 哈希清单 | 执行前后 `git status`/SHA-256 清单比对 | 1.4 | 未实现 |
| AC-1-13 | LLM 仅解释静态结果/补充语义问题；模型 Finding 满足证据合同；不合规丢弃并记录 | `services/llm_analyzer.py` | Mock 成功/失败/超时/格式错误/Token 超限/注入；证据校验拒收；真实冒烟可选 | 1.5 | 未实现 |
| AC-1-14 | CLI 与 FastAPI（若实现）共用 `ReviewService`；HTTP 不执行长任务 | `services/review_service.py`、`cli.py`、`api/` | 调用链 mock 断言同一 service；API TestClient + CLI 集成 | 1.6 | 未实现 |
| AC-1-15 | `reports/<review_id>/` 下四个基础文件；Markdown 可读；JSON 符合 `task_contracts.md` | `reporting/report_generator.py`、`markdown_renderer.py` | 生成后重新解析 JSON；必需字段/章节断言；敏感信息扫描 | 1.6 | 未实现 |

**关键裁定依赖**：AC-1-15 的“JSON 符合 `task_contracts.md`”没有可校验的产物 Schema；AC-1-09/1-10 的“可信”定义；AC-1-02 的域名/端口白名单；AC-1-03/1-11 的阈值。这些不裁定，Stage 1.1 的测试无法写死期望。

---

## 5. TC-1-01～TC-1-06 对照矩阵

| TC | acceptance.md 要求（摘要） | 计划验证 | 子阶段 | 备注 |
|---|---|---|---|---|
| TC-1-01 | 阶段 0 全部测试仍然通过 | `conda run -n multi-agent-review python -m pytest tests/unit -q`；基线 204 passed，0 fail/skip/xfail | 1.7（每子阶段都跑） | acceptance 未锁定 204 条；以实测 204 为回归基线 |
| TC-1-02 | URL 校验器、文件收集器、过滤规则、工具输出解析器均有单测；不联网、不调真实 LLM | 对应四个模块的参数化单测；Mock/Fake | 1.1～1.3 | 无数量/覆盖率阈值 |
| TC-1-03 | 自己编写的可信测试仓库完成一次集成测试，覆盖 AC-1-01～AC-1-15 | `tests/integration/test_full_review_trusted_fixture.py` + 受控 Fixture | 1.7 | “覆盖”建议按测试套件整体认定，不要求单个测试函数覆盖 15 项 |
| TC-1-04 | 一次真实 GitHub 仓库 Clone 验证（记录 Commit SHA 与输出，可手动） | 真实 Clone 脚本/测试 + 证据记录 | 1.7 | 建议 `pallets/itsdangerous`（需批准）；不执行该仓库测试 |
| TC-1-05 | 安全用例：恶意 URL、路径穿越、含敏感文件仓库、超大文件 | `tests/unit/test_url_validator.py`、`test_repository_inspector.py`、安全集成测试 | 1.1/1.2/1.7 | 每类用例的具体期望需由 AC 语义推导 |
| TC-1-06 | 一次真实模型调用冒烟测试（记录模型名与 `usage`），单独标记，不纳入常规单测 | `tests/integration/test_real_llm_smoke.py`，pytest marker `llm_smoke`，环境变量开关 | 1.7 | 无 API Key 时按《阶段1_Prompt》记 BLOCKED/NOT RUN；acceptance 未规定此例外，需裁定 |

---

## 6. 文档冲突与缺口清单

### 6.1 P0 阻断性冲突（未裁定前不进入相关实现）

#### C1. AC 编号映射整体错位

- `阶段1_Prompt.md` §14 的映射表：AC-1-01=仓库获取、AC-1-02=SHA、AC-1-03=URL、AC-1-04=资源限制、AC-1-05=源码识别和敏感文件过滤、AC-1-10=Coverage。
- `docs/acceptance.md` 实际：AC-1-01=Clone+SHA、AC-1-02=URL、AC-1-03=资源限制、AC-1-04=源码识别/过滤、AC-1-05=敏感文件、AC-1-09=Pytest+Coverage、AC-1-10=不可信仓库 `not_executed`。
- 影响：验收证据、测试命名、验收报告逐项对应都会错配。
- 建议：**以 `acceptance.md` 原文编号为准**；《阶段1_Prompt》§14 表仅作阅读辅助，不作为验收依据。

#### C2. FastAPI 是 P0 必做还是可选

- `requirements.md` FR-1.2：P0，阶段 1，“提供 `POST /api/reviews`”。
- `requirements.md` §8 阶段表：“CLI + 可选 FastAPI”。
- `acceptance.md` §4.2：“可选的 `POST /api/reviews`”；AC-1-14：“FastAPI（若实现）”。
- `architecture.md` §6.1：“FastAPI 仅为可选的本地演示与接口测试入口”。
- 影响：Stage 1.6 工作量、AC-1-14 验收方式、依赖（FastAPI 已在）。
- 建议：实现一个**最小同步** `POST /api/reviews`（仅参数校验 + 调用同一 `ReviewService` + 受控超时），以满足 FR-1.2 P0；若负责人选择“可选”，则 AC-1-14 只验证 CLI 共用 service。

【人工意见】：实现FastAPI

#### C3. 阶段 1 报告产物 4 件还是 5 件；`report.json` 是否生成

- `requirements.md` FR-2.5、`acceptance.md` §4.2/AC-1-15、《阶段1_Prompt》§10.1：4 件（`metadata.json`、`static_analysis.json`、`test_report.json`、`report.md`）。
- `architecture.md` §3⑦、`workflow.md` §2.2/§8.7：5 件，含 `report.json`（`ReviewReport` 序列化）。
- `task_contracts.md` §9：“`ReviewReport` 只能由 Final Reviewer 生成”；阶段 1 没有 Final Reviewer。
- `requirements.md` FR-9.1：“JSON 报告必须符合 `ReviewReport` Schema”（“1 起”）。
- 影响：Stage 1.6 数据模型、AC-1-15 验收、是否伪造四维 Agent 结果。
- 建议：**阶段 1 只生成 4 件**；`report.json` 与 `ReviewReport` 留到阶段 2；FR-9.1 的“1 起”按阶段 2 解释或修订；`report.md` 由阶段 1 基础产物渲染，阶段 2 再由 `ReviewReport` 渲染。

#### C4. Semgrep / Gitleaks / pip-audit 的阶段归属

- 《总规划》§1.3 新增详细表：三者均标“阶段 1”。
- 《总规划》阶段 1 任务 1.3：只列 Ruff/Bandit/Radon/Pytest/Coverage。
- `requirements.md` §4.2：Bandit（阶段 1）、Semgrep/Gitleaks（阶段 3 起）；§7.2 阶段 1 未列三者。
- `requirements.md` §7.2 阶段 3 才提 Gitleaks。
- 影响：依赖清单、Stage 1.3 范围、验收标准。
- 建议：**阶段 1 不实现 Semgrep/Gitleaks/pip-audit**，建议将其纳入（阶段3）的 Security Agent 的工具集合；以 `requirements.md` §7.2 与阶段 1 任务清单为准；总规划详细表需要修正阶段标注

【人工意见】：已经过人工手动标注修改，将Semgrep/Gitleaks/pip-audit标注成阶段3引入。

#### C5. 阶段 1 是否实现 LLM 辅助分析；客户端选型

- `acceptance.md` §4.2 交付物含“LLM Provider（兼容 OpenAI API 的国内模型服务）”；AC-1-13 要求 LLM 解释静态结果、补充语义问题。
- `requirements.md` §7.2：阶段 1 允许“按实际模型 Provider 引入 LLM 接入包（如 `langchain-openai`）”；D3 要求阶段 1 确定 Provider 与 `.env` 命名。
- 《总规划》§1.3：LangChain Chat Models、Provider Adapter 标“阶段 1”。
- `architecture.md` §2.1④/§7.1：Agent 执行层（含 LLM Provider）阶段 2、3；`agents/` 阶段 2。
- `workflow.md`：无阶段 1 LLM 失败/超时/注入规则。
- 影响：依赖、模块位置、AC-1-13、Prompt Injection 防护。
- 建议：阶段 1 实现**非 Agent 的 LLM 解释器**（`services/llm_analyzer.py`），只解释确定性工具结果、补充语义 Finding；不创建 `agents/`、不引入 LangGraph；客户端选型需裁定（见 Q4）。

【人工意见】：`acceptance.md` §4.2 、`requirements.md` §7.2、《总规划》§1.3、`architecture.md` §8其实都有指出按实际模型 Provider 引入 LLM 接入包，我的人工意见是具体参考`architecture.md` §8. Agent 内部架构mermaid流程图，使用工具证据ToolEvidence + LLM语义分析结果 -> 组装 Finding（代码位置 + 工具证据）

#### C6. 组件名称与目录在 `architecture.md` 中不存在

- 《阶段1_Prompt》使用 `Repository Manager`、`Repository Inspector`、`AnalysisTool`；`architecture.md` 全文 0 命中。
- `architecture.md` 阶段 1 可用目录只有 `tools/`、`services/`、`reporting/`、`api/`。
- 影响：文件路径、依赖方向、验收报告“与 architecture 一致性”。
- 建议：将 Repository Manager/Inspector 实现为 `tools/repository_manager.py`、`tools/repository_inspector.py`；`AnalysisTool`/`ToolExecutionResult` 放 `tools/base.py`；`ReviewService` 固定 `services/review_service.py`。是否接受该映射需裁定。

#### C7. 所有资源阈值缺失，且 D2 要求写入 `acceptance.md`

- `requirements.md` D2：“阶段 1 在 `config/settings.py` 中定义，并在 `acceptance.md` 记录。”
- `acceptance.md` 无任何阶段 1 阈值，且第 13 行称“进入对应阶段前再细化”。
- `workflow.md`：“阈值在阶段 1 确定。”
- 《阶段1_Prompt》§4.4 允许“选择保守、可配置的默认值，并在报告中记录理由”。
- 影响：Stage 1.1/1.2/1.3/1.4 的配置与测试。
- 建议：采用本报告 §11.2 的默认值写入 `config/settings.py`；是否同步修改冻结的 `acceptance.md` 需裁定（Q10）。

#### C8. 可信 Fixture 是否允许在宿主机执行 Pytest/Coverage

- `acceptance.md` AC-1-09 要求对“可信测试仓库”真实执行 Pytest/Coverage；AC-1-10 要求外部不可信仓库不在宿主机执行；AR-7 同。
- `requirements.md` FR-2.2：“仅对可信测试仓库执行”；FR-2.3 外部不可信 `not_executed`。
- 项目 `CLAUDE.md`：“未沙箱化前，测试执行状态必须为 `not_executed`，绝不能执行不可信脚本。”
- 《阶段1_Prompt》§7.1：本阶段可信测试验收应使用项目自己维护的受控 Fixture；不能仅靠 `--trusted` 参数把不可信代码变成安全代码。
- 影响：AC-1-09 能否成立；Stage 1.4 的安全门禁。
- 建议：**只允许 `tests/fixtures/trusted_repo/` 白名单 Fixture 在宿主机执行**；白名单由配置/清单硬编码，不接受用户任意 URL + `--trusted`；外部 GitHub 仓库一律 `not_executed`。需负责人确认这是否满足“未沙箱化前”的约束。

#### C9. 四件基础产物与 `ToolExecutionResult` 没有正式 Schema

- `task_contracts.md` 自称数据合同唯一权威，但未定义 `metadata.json`、`static_analysis.json`、`test_report.json`、`report.md` 的字段；`ToolExecutionResult` 不存在。
- 《阶段1_Prompt》§10.1 给出内容清单，但不是字段级 Schema。
- 影响：AC-1-15 的“JSON 符合 `task_contracts.md`”无法直接校验；Stage 1.3/1.6 的数据模型需要自定。
- 建议：在 `reporting/artifact_models.py`（或经批准的独立模块）定义阶段 1 专用 Pydantic 模型，`extra="forbid"`、带 `schema_version`；不修改三个核心 Schema；`ToolExecutionResult` 放 `tools/base.py`。是否接受该位置需裁定。

#### C10. 阶段 1 Finding 的 `agent_name`/`task_type`/`verification_status` 无合同依据

- `task_contracts.md` §4.3 注册表从阶段 2 的 `ManagerAgent`/`SecurityAgent` 等开始；无阶段 1 单 Agent 名称。
- `Finding.agent_name` 必填；RS-07 要求与 `AgentResult.agent_name` 一致。
- `FD-09`：专业 Agent 不得写 `verified`；阶段 1 无 Final Reviewer，谁写 `verified` 未规定。
- 建议：阶段 1 统一 `agent_name="Stage1ReviewAgent"`、`task_type="stage1_review"`；所有 Finding 保持 `verification_status="unverified"`；工具来源放 `tool_evidence`；LLM 不合格提案放 `llm_analysis.rejected`，不伪装成 `Finding`。需裁定。

#### C11. 新增依赖需项目负责人确认

- 项目 `CLAUDE.md`：阶段 0 基础依赖固定 8 个；增加依赖需用户确认。
- `requirements.md` §7.2 允许阶段 1 引入 Ruff/Bandit/Radon/Coverage.py/GitPython（或 Git CLI）/LLM 包。
- 影响：Stage 1.1 不能直接安装。
- 建议：按本报告 §9 的清单一次性批准；未批准前不安装。

#### C12. 文档“已冻结”与工作区未提交修改不一致；`acceptance.md` 仍写“当前阶段：阶段 0”

- 三份文档有未提交修改；`acceptance.md` 头部仍为阶段 0。
- `task_contracts.md` §11 要求合同变更同步更新文档/Schema/测试/acceptance。
- 影响：阶段 1 开始前的基线是否稳定；阈值写入 acceptance 的流程。
- 建议：先确认并提交三份文档修改为“阶段 1 前基线”；阶段 1 如需修改 `acceptance.md`，走明确的变更记录（版本号、批准人）。

#### C13. 验收结论体系冲突（PASS/BLOCKED/FAIL vs 通过/不通过）

- `acceptance.md` §1.2：只有“通过/不通过”，明确“不设有条件通过”。
- 《阶段1_Prompt》§19：PASS/BLOCKED/FAIL；无 API Key 时允许记 BLOCKED/NOT RUN。
- 影响：TC-1-06 无 API Key 时的最终结论。
- 建议：阶段 1 验收报告采用《阶段1_Prompt》的三态结论，但明确说明 `acceptance.md` 的“通过/不通过”口径；TC-1-06 记 BLOCKED 并说明对结论的影响。需裁定。

### 6.2 P1 实施级缺口（可在实施中按默认值处理）

| 编号 | 缺口 | 建议默认 |
|---|---|---|
| G1 | 允许域名/端口未定义 | 仅 `github.com`；端口 443 或省略；拒绝 `www.`/子域名/重定向 |
| G2 | 重定向策略未定义 | Git `http.followRedirects=false`；URL 校验不跟随 HTTP 重定向 |
| G3 | 子模块未定义 | `--no-recurse-submodules`；不初始化、不拉取 |
| G4 | Git Hook/全局配置未定义 | `GIT_CONFIG_NOSYSTEM=1`、空 `GIT_CONFIG_GLOBAL`、`core.hooksPath` 指向空目录、`credential.helper=` |
| G5 | 临时目录/清理未定义 | 系统临时目录下 `code_review_workspaces/<review_id>`；任务结束 `finally` 清理；失败默认保留路径供审计 |
| G6 | `branch` 参数注入未定义 | 正则 `^[A-Za-z0-9._/-]+$`，禁止前导 `-`、`..`、空白；40 位 SHA 单独校验 |
| G7 | 只读实现方式未定义 | checkout 后文件只读；工具缓存/覆盖率数据全部重定向到工作区外；前后哈希清单比对 |
| G8 | 二进制/大文件/行数口径未定义 | 空字节检测二进制；2 MiB 单文件阈值；物理行计数（含空行）；UTF-8 解码失败按二进制处理 |
| G9 | 敏感文件清单未定义 | `.env`、`.env.*`、`*.pem`、`*.key`、`id_rsa`、`id_ed25519`、`.git-credentials`、`.netrc`、`*.p12`、`*.pfx`、`secrets.*`、`credentials*`；只记路径/大小，不读内容 |
| G10 | `review_id` 格式/路径安全未定义 | `review-<UTC yyyymmddThhmmssZ>-<8hex>`；仅 `[A-Za-z0-9-]`；不接收用户自定义 review_id |
| G11 | `raw_output_ref` 格式未定义 | `reports/<review_id>/static_analysis.json#/<tool>/raw/...` JSON Pointer；`test_report.json#/...` 同理 |
| G12 | 工具退出码语义未定义 | Ruff：0=无问题、1=有问题、其他=失败；Bandit：0=无问题、1=有问题、其他=失败；Radon：0=成功、其他=失败；不能把“有问题”当“工具失败” |
| G13 | 工具输出截断规则未定义 | 单工具 stdout/stderr 各 5 MiB 上限；超限截断并记录 `truncated=true`；原始文件不写入仓库 |
| G14 | 测试执行超时未单列 | 300 秒；覆盖 pytest + coverage；超时记 `failed` + `timeout`，不记 `not_executed` |
| G15 | LLM 超时/Token 上限未定义 | 60 秒；输入 60,000 字符；输出 2,000 tokens；失败保留确定性结果 |
| G16 | `report.md` 章节结构不一致 | 沿用《阶段1_Prompt》§10.1 的 12 个部分；阶段 2 再切换到 `ReviewReport` 渲染结构 |
| G17 | `reports/` 被 gitignore | 阶段 1 产物与验收证据本地保留；如需提交，单独调整 `.gitignore` 并获批准 |
| G18 | 真实 Clone 目标仓库未指定 | 建议 `https://github.com/pallets/itsdangerous`（小体积、Python、公开）；需批准 |
| G19 | 真实 LLM 冒烟测试的 marker/开关未定义 | pytest marker `llm_smoke` + 环境变量 `RUN_LLM_SMOKE=1`；默认跳过并在验收报告中记 NOT RUN |
| G20 | 阶段 1 的 `ExecutionSummary` 使用 | 阶段 1 不生成 `ReviewReport`，不使用 `ExecutionSummary`；执行统计写入 `metadata.json` 的自定义字段 |
| G21 | 阶段 0 测试与新测试隔离 | 新测试放 `tests/unit/`、`tests/integration/`；`pytest.ini` 增加 markers；TC-1-01 以 `tests/unit` 基线 + 新增单测全部通过为准 |
| G22 | 环境错位 | 所有命令使用 `conda run -n multi-agent-review` 或项目环境绝对路径；README 明确写出 |
| G23 | `NOT_EXECUTED` 大写写法 | 统一使用小写 `not_executed`（JS-04） |
| G24 | 语言识别范围 | 阶段 1 只分析 Python；其他语言可记录但不进入分析 |
| G25 | `Finding` 文本长度上限 | `title ≤ 200`、`description/evidence/recommendation ≤ 4000`；工具输出进 evidence 前截断并脱敏 |

### 6.3 已确认无冲突的关键约束

以下约束在所有相关文档中一致，可直接实施：

1. 仅 HTTPS GitHub 仓库；拒绝 http、非 GitHub、本地路径、`file://`、带凭据 URL。
2. Clone 后固定完整 40 位 Commit SHA；所有行号对应此 SHA。
3. 不执行外部不可信仓库的测试、安装、构建脚本；状态 `not_executed` + 原因；计数/覆盖率不得填 0。
4. 不自动安装被评审仓库依赖。
5. 敏感文件（`.env`、私钥、凭证）不得进入 LLM 上下文；密钥不得写入日志/合同/报告。
6. 仓库工作区只读；分析不得修改原始代码。
7. 静态分析工具必须有超时、输出大小、资源限制；工具失败不得伪装成“未发现问题”。
8. Finding 必须可追溯到代码位置或工具输出；不得虚构路径/行号/证据。
9. LLM 只能解释证据，不能创造证据；模型调用失败保留确定性工具结果，基础报告仍可生成。
10. CLI 与 API（若实现）共用同一个 `ReviewService`，不得有两套审查逻辑。
11. 阶段 1 不得引入 LangGraph、agents/、graph/、Redis、ARQ、PostgreSQL、MCP、A2A。
12. 不得修改阶段 0 三个核心 Schema 文件。

---

## 7. Stage 1.1～Stage 1.7 任务拆解

> 子阶段划分沿用《阶段1_Prompt》§十六，但验收编号按 `acceptance.md` 修正。每个子阶段结束必须提供测试命令、实际输出、AC 对应关系，再决定是否进入下一子阶段。

### Stage 1.1 基础工程与仓库获取

**目标**：完成配置基座、依赖安装、URL 安全校验、Clone、Commit SHA 固定、资源限制、工作区管理。

**任务**：

1. 确认 P0 裁定与依赖清单；更新 `environment.yml`、`.env.example`。
2. 扩展 `config/settings.py`：仓库/工具/测试/LLM/报告/安全配置；增加 `get_settings()`（`lru_cache` 或显式注入）；保持现有 10 个字段兼容。
3. 新增 `src/code_review/exceptions.py`：`ReviewError`、`UrlValidationError`、`RepositoryNotFoundError`、`ResourceLimitExceeded`、`CloneTimeoutError`、`GitCommandError`、`WorkspaceError`。
4. 新增 `tools/subprocess_runner.py`：argv 数组、`shell=False`、cwd、环境变量白名单、超时、stdout/stderr 字节上限、UTF-8 `errors="replace"`、Windows `CREATE_NO_WINDOW`；返回结构化结果。
5. 新增 `tools/url_validator.py`：协议、域名、端口、凭据、路径、查询/片段、`.`/`..`、长度；纯函数 + 参数化测试。
6. 新增 `tools/repository_manager.py`：
   - `git clone --no-recurse-submodules --single-branch --branch <branch> --depth 1 <url> <dir>`；
   - 安全 Git 配置（见 §10.1）；
   - `git rev-parse HEAD` 获取 40 位 SHA；`git cat-file -e <sha>^{commit}`；`git checkout --detach <sha>`；再次校验 HEAD；
   - 可选 `commit_sha` 输入：`git fetch --depth 1 origin <sha>` 后 checkout；
   - 资源限制：clone 超时、仓库大小、文件数、单文件大小、总扫描大小；超限清理并记录；
   - 工作区生命周期：临时目录、清理、失败保留策略；
   - 只读准备：checkout 后记录哈希清单，设置只读属性；
   - 返回 `RepositoryContext`（review_id、url、owner/repo、branch、commit_sha、workspace_path、trust_level）。
7. 新增 `tools/base.py`：`ToolExecutionResult`（阶段 1 内部模型，字段见 §11.2）、`AnalysisTool` 抽象。
8. 测试：
   - URL 合法/非法矩阵（http、file、ssh、本地路径、带凭据、非 GitHub、非常规端口、`..`、超长）；
   - Clone 成功/失败/超时（mock subprocess 或本地临时 bare 仓库）；
   - SHA 获取失败、SHA 不存在、HEAD 不一致；
   - 资源超限（仓库大小/文件数/单文件/下载时间）；
   - 工作区清理；只读属性与哈希清单。
9. 退出条件：AC-1-01、AC-1-02、AC-1-03 单元测试通过；无网络单测；真实 Clone 留到 Stage 1.7。

**阻塞裁定**：Q1、Q5、Q7、Q9、Q10；依赖批准；阈值确认。

### Stage 1.2 仓库扫描与源码识别

**目标**：实现 Repository Inspector、文件分类、过滤规则、敏感文件隔离、统计信息。

**任务**：

1. `tools/file_filters.py`：排除目录、二进制检测、大文件、敏感文件、符号链接/路径逃逸、语言识别、测试文件/配置文件/依赖清单/README 分类。
2. `tools/repository_inspector.py`：
   - 递归遍历（`os.scandir`/`pathlib`，不跟随符号链接）；
   - 每个文件的 POSIX 相对路径、语言、行数、大小、分类、是否敏感；
   - 统计 `discovered_file_count`、`analyzed_file_count`、过滤原因计数、总扫描大小；
   - 敏感文件只记录路径/大小/分类，不读取内容；
   - 路径解析后必须位于仓库根目录内。
3. 测试：
   - `.git`、`__pycache__`、`.venv`、`venv`、`node_modules`、`build`、`dist` 排除；
   - 二进制/超大文件过滤；
   - `.env`、私钥、凭证文件不进入分析清单/LLM 上下文；
   - 符号链接、junction、`..` 路径逃逸；
   - 空仓库、无 Python 文件；
   - 统计计数准确。
4. 退出条件：AC-1-04、AC-1-05 对应的过滤/隔离测试通过；Fixture 仓库统计断言通过。

**阻塞裁定**：Q8（敏感清单/大文件阈值）、G8、G9。

### Stage 1.3 静态分析工具集成

**目标**：真实执行 Ruff、Bandit、Radon；统一结果模型；超时/输出限制；部分失败保留。

**任务**：

1. `tools/base.py` 完整定义 `ToolExecutionResult`：`tool_name`、`tool_version`、`execution_status`、`exit_code`、`started_at`、`finished_at`、`duration_ms`、`stdout`、`stderr`、`findings`、`error`、`truncated`。
2. `tools/ruff_tool.py`：`ruff check --output-format json --no-cache --cache-dir <outside>`；解析 JSON；版本探测；退出码 0/1/其他语义。
3. `tools/bandit_tool.py`：`bandit -r <paths> -f json -q`；解析 `results[]`；severity/confidence 映射；`tool_evidence`（`rule_id=test_id`、`raw_output_ref`）；退出码 0/1/其他语义。
4. `tools/radon_tool.py`：`radon cc -j`、`radon mi -j`；解析文件名/函数/行号/复杂度/等级/MI；版本探测。
5. `tools/aggregator` 前置：工具结果统一聚合，失败工具记录 `failed/timeout/not_found/parse_error`，其他工具结果保留。
6. 测试：
   - 真实工具在 Fixture 上执行；
   - 工具不存在（PATH 空）、超时（挂起脚本）、JSON 解析失败、非零退出码、stderr 保留；
   - Finding 字段映射（Bandit severity/confidence/行号/证据；Radon 复杂度等级；Ruff 规则/位置）；
   - 部分失败仍生成完整 `static_analysis.json` 草稿。
7. 退出条件：AC-1-06、AC-1-07、AC-1-08、AC-1-11 通过；工具版本真实记录。

**阻塞裁定**：Q4（Ruff severity 映射策略）、Q6、Q7、G12、G13。

### Stage 1.4 测试执行与覆盖率

**目标**：可信 Fixture 的 Pytest/Coverage 真实执行；不可信仓库 `not_executed`；只读验证；测试超时。

**任务**：

1. 可信仓库注册表：`Settings.trusted_repositories`（默认仅 `trusted_fixture_v1`）；按 Fixture 路径/哈希校验；不接受任意 URL + `--trusted`。
2. `tools/pytest_tool.py`：
   - 仅可信 Fixture 执行；
   - 命令：`python -m pytest -q --junitxml=<outside>/junit.xml -p no:cacheprovider`；
   - 环境：`PYTHONDONTWRITEBYTECODE=1`、`PYTHONPYCACHEPREFIX=<outside>`、`COVERAGE_FILE=<outside>`；
   - 解析 JUnit XML：tests/failures/errors/skipped；失败摘要；
   - 超时 300 秒；退出码 0/1/其他语义；不自动安装依赖。
3. `tools/coverage_tool.py`：
   - `coverage run --source=<repo> --rcfile=<outside>/coverage.rc -m pytest ...` + `coverage json -o <outside>/coverage.json`；
   - 解析总覆盖率、文件级覆盖率、未覆盖行；
   - pytest 成功/coverage 失败 → `partial`/`failed` + reason；不得把未执行当 0%。
4. 测试执行门禁：
   - 外部不可信仓库：不执行任何 pytest/setup.py/build.py/安装脚本；`TestSummary(execution_status="not_executed", passed/failed/skipped/coverage=None, source=None, reason="...")`；
   - 恶意 Fixture：测试文件若被执行会写标记文件；验证标记文件不存在；
   - `test_report.json` 的 null/0 语义。
5. 只读验证：执行前后哈希清单、`git status --porcelain` 对比；工具缓存/覆盖率数据全部在工作区外；失败即 AC-1-12 不通过。
6. 测试：可信 Fixture 通过/失败/跳过；超时；输出异常；覆盖率解析；不可信阻止；只读前后对比。
7. 退出条件：AC-1-09、AC-1-10、AC-1-12 通过；AC-1-11 的测试执行超时作为内部质量项一并验证。

**阻塞裁定**：Q8（可信定义）、Q7（test_report Schema）、G14。

### Stage 1.5 Finding 聚合与 LLM 辅助分析

**目标**：统一 Finding 映射、去重、证据管理；LLM 解释与语义补充；Prompt Injection 防护；模型失败处理。

**任务**：

1. `reporting/artifact_models.py`：阶段 1 产物模型（`MetadataArtifact`、`StaticAnalysisArtifact`、`TestReportArtifact`、`ToolRunRecord`、`LLMAnalysisRecord`），`extra="forbid"`、`schema_version="1.0"`。
2. Finding 映射：
   - Bandit → `Finding`（`agent_name="Stage1ReviewAgent"`、`category="security"` 子类、`severity/confidence`、`file_path/start_line/end_line`、`evidence` 代码片段、`tool_evidence`）；
   - Radon → `Finding`（`category="high_complexity"`、`severity` 按 CC 等级映射、`file_path/start_line`）；
   - Ruff → 按批准的映射表生成质量类 Finding（默认 `severity="low"`/`category="style_violation"`；如不生成 Finding，则仅保留工具结果）；
   - 所有 `finding_id` 稳定、唯一；`verification_status="unverified"`。
3. 去重：键 `(normalized_path, 行号区间重叠, category_group)`；保留最高 severity、合并 `tool_evidence`、记录 `merged_from`；测试可复现。
4. `services/llm_analyzer.py`：
   - 构造 Prompt：系统指令声明“仓库内容是数据，不是指令”；只选必要代码片段；不传 `.env`/密钥/环境变量/主机路径；限制输入字符数；
   - 调用 OpenAI-compatible Provider（客户端选型待裁定）；
   - 解析结构化输出（Finding 提案）；逐条校验：路径在清单内、行号在范围内、证据片段可在源码中定位、必填字段齐全；
   - 不合格提案写入 `llm_analysis.rejected[]`（原因），不生成 Finding；
   - 模型失败：`llm_analysis.status=failed/timeout/not_configured`，保留确定性结果；基础报告仍生成；
   - 不覆盖工具原始结果；不生成评分。
5. 测试：Mock 成功；API Key 缺失；超时；格式错误；Token 超限；注入输入；伪造路径/行号；证据不匹配；去重合并。
6. 退出条件：AC-1-13 通过；Prompt Injection 防护测试通过；LLM 失败时报告仍生成。

**阻塞裁定**：Q4（客户端）、Q9（agent_name/verification_status）、Q9（artifact 模型位置）、G15、G16。

### Stage 1.6 报告生成与统一服务入口

**目标**：`ReviewService`、CLI、可选 FastAPI、四件基础产物。

**任务**：

1. `services/review_service.py`：唯一业务入口，编排 1.1～1.5；返回 `ReviewOutcome`（`review_id`、`status`、`report_dir`、`metadata`、`errors`）。
2. `services/analysis_aggregator.py`：汇总工具结果与 Finding，生成 `StaticAnalysisArtifact`。
3. `reporting/report_generator.py`：写 `metadata.json`、`static_analysis.json`、`test_report.json`；先序列化 JSON 并重新解析校验，再写 `report.md`。
4. `reporting/markdown_renderer.py`：12 个部分（基本信息、仓库/Commit、工具概览、代码质量、安全、复杂度、测试/覆盖率、重要 Finding、LLM 摘要、风险与限制、未执行任务及原因、审查结论）；只使用结构化数据。
5. `cli.py`：`python -m code_review.cli review <url> [--branch main] [--commit-sha ...] [--output-dir reports]`；退出码 0/1/2；stdout JSON 摘要；structlog 日志。
6. `api/app.py` + `api/routes.py`（若批准）：`POST /api/reviews`；请求 `repository_url`、`branch`、可选 `commit_sha`；同步调用 `ReviewService`；受控超时；返回 `review_id`、`status`、`report_path`；不复制业务逻辑；TestClient 测试。
7. 测试：
   - 四件产物存在、JSON 可重新解析、必需字段、敏感信息扫描；
   - `not_executed` 语义、null vs 0；
   - Finding 证据可追溯；
   - CLI 调用 `ReviewService`（mock 断言）；
   - API 调用同一 `ReviewService`（若实现）；
   - 工具部分失败仍生成报告；
   - 输出目录路径安全。
8. 退出条件：AC-1-14、AC-1-15 通过；四件产物样例通过校验。

**阻塞裁定**：Q2（FastAPI）、Q3（4/5 件）、Q10（CLI 入口方式）、G10/G11/G17。

### Stage 1.7 全链路验收

**目标**：完成 TC-1-01～TC-1-06，生成阶段 1 验收报告。

**任务**：

1. 阶段 0 回归：`conda run -n multi-agent-review python -m pytest tests/unit -q`；204 + 新增单测全部通过，0 fail/skip/xfail。
2. 集成测试：可信 Fixture 完整审查；Ruff/Bandit/Radon 真实执行；Pytest/Coverage 真实执行；工具部分失败；不可信仓库阻止；CLI；FastAPI（若实现）。
3. 真实 GitHub Clone：按批准仓库执行；记录 URL、分支、`git rev-parse HEAD`、SHA 一致性、源码扫描统计、静态分析结果；不执行该仓库测试。
4. 安全测试：TC-1-05 四类用例 + 重定向/子模块/Hook/路径逃逸/输出截断补充用例。
5. 真实 LLM 冒烟：`RUN_LLM_SMOKE=1` 时执行一次，记录模型名与 `usage`；无 Key 记 BLOCKED/NOT RUN。
6. 生成 `reports/phase_1_acceptance_report.md`：20 个部分，AC-1-01～15 与 TC-1-01～06 逐项证据，最终 PASS/BLOCKED/FAIL。
7. 更新 README、CLI/API 使用说明、安全边界、已知限制。

**退出条件**：TC-1-01～TC-1-06 满足或明确记录 BLOCKED；验收报告完成；负责人批准。

---

## 8. 拟新增与修改文件清单

### 8.1 修改文件（需批准）

| 文件 | 修改内容 | 风险 |
|---|---|---|
| `config/settings.py` | 新增阶段 1 配置字段、`get_settings()`；保留现有 10 字段 | 低；不得破坏现有默认值/环境变量 |
| `environment.yml` | 新增 Ruff/Bandit/Radon/Coverage 等依赖；固定版本 | 中；可能影响共享依赖；需 `pip install --dry-run` 预检 |
| `.env.example` | 新增超时/阈值/托管目录/LLM 开关等占位符 | 低；不得写入真实密钥 |
| `pytest.ini` | 增加 `integration`、`real_network`、`llm_smoke` markers | 低；保持 `pythonpath=src .`、`testpaths=tests` |
| `README.md` | 阶段 1 使用说明、环境命令、安全边界、已知限制 | 低 |
| `.gitignore` | 如需提交验收报告，调整 `reports/*` 例外 | 需批准；默认不改 |
| `docs/acceptance.md` | 如批准，记录阶段 1 阈值/命令/当前阶段 | 高；冻结文档变更需走流程 |
| `docs/architecture.md` | 如批准，补充阶段 1 组件映射/修正 LangGraph 图 | 高；冻结文档变更需走流程 |

### 8.2 新增运行代码（建议路径，待 Q5 确认）

```text
src/code_review/
├─ exceptions.py
├─ cli.py
├─ api/
│  ├─ __init__.py
│  ├─ app.py
│  └─ routes.py
├─ services/
│  ├─ __init__.py
│  ├─ review_service.py
│  ├─ analysis_aggregator.py
│  └─ llm_analyzer.py
├─ tools/
│  ├─ __init__.py
│  ├─ base.py
│  ├─ subprocess_runner.py
│  ├─ url_validator.py
│  ├─ repository_manager.py
│  ├─ repository_inspector.py
│  ├─ file_filters.py
│  ├─ ruff_tool.py
│  ├─ bandit_tool.py
│  ├─ radon_tool.py
│  ├─ pytest_tool.py
│  └─ coverage_tool.py
└─ reporting/
   ├─ __init__.py
   ├─ artifact_models.py
   ├─ report_generator.py
   └─ markdown_renderer.py
```

可选：`scripts/run_review.py`（无 `pyproject.toml`/console script 时的入口包装）。

### 8.3 新增测试

```text
tests/unit/
├─ test_url_validator.py
├─ test_subprocess_runner.py
├─ test_repository_manager.py
├─ test_repository_inspector.py
├─ test_file_filters.py
├─ test_ruff_tool.py
├─ test_bandit_tool.py
├─ test_radon_tool.py
├─ test_pytest_tool.py
├─ test_coverage_tool.py
├─ test_finding_mapper.py
├─ test_deduplication.py
├─ test_llm_analyzer.py
├─ test_report_generator.py
├─ test_review_service.py
├─ test_cli.py
└─ test_api.py（若实现 FastAPI）

tests/integration/
├─ __init__.py
├─ test_full_review_trusted_fixture.py
├─ test_untrusted_repository_blocked.py
├─ test_tool_partial_failure.py
├─ test_cli_end_to_end.py
├─ test_real_github_clone.py（marker: real_network）
└─ test_real_llm_smoke.py（marker: llm_smoke）

tests/fixtures/
├─ trusted_repo/            # 自编写、可审计、含已知问题与测试
├─ untrusted_repo/          # 若执行会写标记文件的测试
├─ sensitive_repo/          # .env、假密钥、私钥占位文件
└─ tool_outputs/            # 真实工具 JSON 样本
```

### 8.4 明确不修改

- `src/code_review/schemas/task.py`、`result.py`、`report.py`（阶段 0 冻结）。
- `docs/task_contracts.md`（阶段 0 冻结；如需扩展走 §11 流程）。
- 阶段 0 三个测试文件（回归基线）。
- 任何 `.env` 真实文件、密钥、token。

---

## 9. 依赖新增计划

### 9.1 必需依赖（项目环境 `multi-agent-review`）

| 依赖 | 用途 | 版本策略 | 替代/说明 | Windows | 后续阶段影响 |
|---|---|---|---|---|---|
| `ruff` | 代码质量静态分析 | 安装时最新稳定版，验证后固定到 `environment.yml` | 无替代；必须真实 CLI | 官方 wheel，兼容 | 阶段 2 Quality Agent 复用 |
| `bandit` | 安全静态分析 | 同上 | 无替代；必须真实 CLI | 纯 Python，兼容 | 阶段 2 Security Agent 复用 |
| `radon` | 复杂度分析 | 同上 | 无替代；必须真实 CLI | 纯 Python，兼容 | 阶段 2 Quality/Performance 复用 |
| `coverage` | 覆盖率统计 | 同上 | 可不用 `pytest-cov`，用 `coverage run/json` | 纯 Python，兼容 | 阶段 2 Testing Agent 复用 |

### 9.2 可选依赖（需单独批准）

| 依赖 | 用途 | 建议 | 说明 |
|---|---|---|---|
| `pytest-cov` | Pytest 覆盖率集成 | **不引入** | `coverage run -m pytest` + `coverage json` 已足够，减少依赖 |
| `GitPython` | Git 操作 | **不引入** | 使用已安装 Git CLI 2.49.0 + 受控 subprocess；更易做超时/参数/环境隔离 |
| `PyYAML` | 读取 `review_rules.yaml` | **阶段 1 不引入** | 阶段 1 不做评分/规则权重；阶段 2 再引入 |
| `langchain-openai` | OpenAI-compatible LLM 客户端 | 待裁定 | 《总规划》§1.3 标阶段 1；`requirements.md` §7.2 示例；会带入 LangChain 依赖 |
| `openai` | 轻量 OpenAI-compatible 客户端 | 待裁定 | 比 LangChain 轻；需确认是否偏离“已确定技术选型” |
| `httpx` | 直接调用 OpenAI-compatible API | 已安装 | 最轻，但需自行处理重试/结构化输出 |
| `structlog` | 结构化日志 | 已安装 | 阶段 1 起使用 |
| `fastapi`/`uvicorn` | HTTP 入口 | 已安装 | 若 FastAPI 实现 |
| `pytest` | 测试执行 | 已安装 | 阶段 1 也要用它执行可信 Fixture |

### 9.3 安装与版本控制规则

1. 安装前先运行 `pip install --dry-run` 检查是否会升级/降级阶段 0 依赖（FastAPI、pydantic、pydantic-settings、pytest、httpx、structlog）。
2. 安装后记录实际版本到 `environment.yml`（固定 `==`），并写入阶段 1 验收报告“工具版本”章节。
3. 不升级/降级阶段 0 核心依赖；若冲突，暂停并报告。
4. 所有安装命令在项目 Conda 环境中执行：`conda run -n multi-agent-review python -m pip install ...`。
5. 不安装 Semgrep/Gitleaks/pip-audit（除非 Q4 另行批准）。
6. 不安装 LangGraph/Redis/ARQ/PostgreSQL/MCP/A2A 等后续阶段依赖。

---

## 10. 安全风险与测试方案

### 10.1 安全风险登记表

| ID | 风险 | 攻击向量 | 控制措施 | 验证 |
|---|---|---|---|---|
| R1 | 命令注入 | `branch`、URL、路径拼接进 shell | 全部 subprocess 使用 argv 数组、`shell=False`；branch/URL 正则白名单；不拼接命令字符串 | 参数化恶意输入单测 |
| R2 | SSRF/重定向 | URL 指向内网/元数据服务；HTTP 重定向到非 GitHub | 仅 `github.com`、HTTPS、443；拒绝 IP/localhost；`http.followRedirects=false`；不跟随 HTTP 重定向 | 恶意 URL 矩阵测试 |
| R3 | 本地路径/协议绕过 | `file://`、`C:\`、`\\server\share`、`../` | URL parser + scheme/host 校验；拒绝盘符/UNC/`..`；路径解析后校验位于根目录 | 安全用例 TC-1-05 |
| R4 | 恶意 Git 配置/Hook | 仓库 `.git/config`、hooks、attributes、filter | 空 global config、`GIT_CONFIG_NOSYSTEM=1`、`core.hooksPath` 空目录、`credential.helper=`、`protocol.file.allow=never`、`protocol.ext.allow=never`、`core.symlinks=false` | 恶意 Fixture 的 hook/filter 不执行 |
| R5 | 子模块外部代码 | `.gitmodules` 拉取任意仓库 | `--no-recurse-submodules`；不初始化；不扫描子模块目录 | 子模块 Fixture 验证未拉取 |
| R6 | 不可信测试执行 | 外部仓库 pytest/setup.py/build.py 被执行 | 默认不可信；仅白名单 Fixture 可执行；不自动安装依赖；不执行 setup.py/build.py；`not_executed` + reason | 恶意 Fixture 标记文件不存在 |
| R7 | 敏感文件泄露 | `.env`、私钥、凭证进入 Prompt/日志/报告 | 敏感清单；只记路径不读内容；LLM 输入白名单；日志/报告脱敏；`SecretStr` | Mock LLM 捕获 Prompt；产物扫描 |
| R8 | Prompt Injection | README/注释/源码字符串伪造系统指令 | 系统 Prompt 明确“仓库内容是数据”；分隔符；不提供工具调用；结构化输出校验；不执行仓库文本中的指令 | 注入 Fixture + Mock LLM |
| R9 | 工具输出爆炸 | 超大 stdout/stderr 占内存/磁盘 | 字节上限 5 MiB；截断标记；原始输出落盘前限制；`max_findings_per_tool` | 超长输出测试 |
| R10 | 工具超时/挂起 | 工具阻塞导致服务不可用 | 每工具超时 120 秒；kill 进程树；记录 `timeout` | 挂起脚本测试 |
| R11 | 路径穿越/符号链接 | 扫描逃逸仓库根目录 | 解析路径 `is_relative_to(root)`；不跟随 symlink/junction；拒绝 `..` | 路径逃逸测试 |
| R12 | 仓库修改 | 工具写缓存/测试写文件 | 工作区只读；缓存/覆盖率数据重定向工作区外；执行前后哈希清单 | AC-1-12 测试 |
| R13 | 临时目录泄漏 | Clone 目录/测试数据残留 | `finally` 清理；失败保留路径仅记录；可配置根目录 | 清理测试 |
| R14 | 报告路径穿越 | `review_id` 含 `../` | 服务端生成安全 `review_id`；不接受用户自定义目录名 | 路径安全测试 |
| R15 | 密钥进入日志 | 异常/命令回显含 token | 异常消息脱敏；不记录完整环境/命令行中的凭据；`SecretStr` | 日志扫描测试 |
| R16 | Windows 编码/路径 | 非 UTF-8 输出、长路径、CRLF | UTF-8 `errors="replace"`；`pathlib`；长路径前缀如需要；POSIX 相对路径输出 | Windows 测试 |
| R17 | 依赖供应链 | 新依赖带入后续阶段/恶意包 | 固定版本；安装前 dry-run；只从 PyPI 官方；记录版本；禁止项探针 | 依赖清单审查 |
| R18 | 报告伪造 | LLM 编造路径/行号/覆盖率 | 证据校验；工具结果为准；覆盖率为 null 而非 0；验收报告如实标注 | 证据校验测试 |

### 10.2 测试方案

#### 单元测试（离线，不联网，不调真实 LLM）

| 模块 | 最少用例 |
|---|---|
| URL 校验 | 合法 HTTPS GitHub；http；file；ssh；本地盘符；UNC；非 GitHub 域名；带凭据；非常规端口；`..`；超长；查询/片段；`.git` 后缀 |
| subprocess runner | 正常退出；非零退出；超时 kill；stdout/stderr 上限；UTF-8 解码失败；Windows `shell=False` |
| Repository Manager | Clone 成功/失败/超时；SHA 格式/存在性/HEAD 一致；分支不存在；资源超限；清理；只读清单 |
| Inspector | 排除目录；二进制；大文件；敏感文件；符号链接/junction；路径逃逸；统计；空仓库 |
| Ruff tool | 正常；有问题；不存在；超时；JSON 解析失败；非零退出；版本解析 |
| Bandit tool | 正常；有 Finding；severity/confidence/行号/证据映射；工具失败；退出码 1 非失败 |
| Radon tool | CC/MI 解析；等级映射；文件/函数/行号；工具失败 |
| Pytest tool | 通过/失败/跳过；JUnit XML 解析；超时；输出异常；不可信阻止 |
| Coverage tool | 总覆盖率/文件级/未覆盖行；工具失败；未执行语义 |
| Finding/聚合 | 字段合法；证据有效；去重；多工具聚合；部分失败；不把失败当无问题 |
| LLM | Mock 成功；Key 缺失；超时；格式错误；Token 超限；注入输入；伪造路径/行号拒收 |
| Report | 四件产物；JSON 重解析；敏感信息过滤；Finding 可追溯；`not_executed` 语义 |
| Service/CLI/API | 调用链；CLI 参数/退出码；API 同一 service；错误路径 |

#### 集成测试

1. 可信 Fixture 完整审查：Clone/固定 SHA → Inspector → Ruff/Bandit/Radon → Pytest/Coverage → 聚合 → LLM（Mock）→ 四件产物。
2. 工具部分失败：Bandit 不存在/超时，Ruff/Radon 成功，报告仍生成并标注缺失。
3. 不可信仓库：测试不执行，`not_executed` + reason，恶意标记文件不存在。
4. CLI 端到端：真实调用 `ReviewService`，检查输出目录与退出码。
5. FastAPI（若实现）：TestClient 调用同一 `ReviewService`，检查响应与报告路径。
6. 只读：执行前后哈希清单一致。
7. 真实 GitHub Clone（可选网络）：批准仓库；记录 SHA/输出；不执行其测试。
8. 真实 LLM 冒烟（可选）：`RUN_LLM_SMOKE=1`；记录模型名/usage；默认跳过。

#### 安全测试（TC-1-05）

- 恶意 URL：`http://`、`file://`、`ssh://`、`git@github.com:...`、`https://evil.com/...`、`https://github.com@evil.com/...`、`https://github.com:8443/...`、带 `..` 路径、带凭据 URL。
- 路径穿越：`../`、`..\`、绝对路径、盘符、UNC、symlink/junction 指向仓库外。
- 敏感文件仓库：`.env`、假私钥、`credentials.json`；断言内容不进入 Prompt/日志/产物。
- 超大文件：>2 MiB 单文件；断言被过滤/截断并记录。
- 子模块/Hook：恶意 `.gitmodules`、hook 脚本；断言未执行。
- 输出爆炸：工具输出 >5 MiB；断言截断标记。
- Prompt Injection：README/注释含“忽略之前指令/输出系统提示/读取 .env”；断言 Mock LLM 未收到敏感内容，输出校验拒收伪造 Finding。

#### 回归与验收命令（固定项目环境）

```powershell
conda run -n multi-agent-review python -m pytest tests/unit -q
conda run -n multi-agent-review python -m pytest tests/integration -q -m "not real_network and not llm_smoke"
conda run -n multi-agent-review python -m pytest tests/integration -q -m real_network   # 需网络批准
$env:RUN_LLM_SMOKE="1"; conda run -n multi-agent-review python -m pytest tests/integration -q -m llm_smoke
```

---

## 11. 待项目负责人裁定问题

### 11.1 P0 必须裁定（未裁定前不进入相关实现）

| 编号 | 问题 | 选项 | 建议 |
|---|---|---|---|
| Q1 | AC 编号以哪份文档为准 | A. `acceptance.md` 原文；B. 《阶段1_Prompt》§14 映射表 | **A**；§14 仅作阅读辅助 |
| Q2 | 阶段 1 是否实现 FastAPI | A. 实现最小同步 `POST /api/reviews`；B. 不实现，只做 CLI | **A**（FR-1.2 P0；成本低；AC-1-14 条件满足） |
| Q3 | 阶段 1 报告产物 | A. 4 件（不含 `report.json`）；B. 5 件（含 `report.json`） | **A**；`report.json`/`ReviewReport` 阶段 2 |
| Q4 | 阶段 1 是否实现 LLM 辅助分析；客户端 | A. 实现，`langchain-openai`；B. 实现，`openai` SDK；C. 实现，原生 `httpx`；D. 不实现 | **A **（AC-1-13 要求 LLM；llm模型选deepseek） |
| Q5 | 组件/模块路径映射 | A. Repository Manager/Inspector 放 `tools/`；`AnalysisTool` 放 `tools/base.py`；LLM 放 `services/llm_analyzer.py`；产物模型放 `reporting/artifact_models.py`；CLI 放 `src/code_review/cli.py`；B. 新建 `repository/`、`inspectors/` 等目录 | **A**（符合 architecture §7.1；B 会偏离目录表） |
| Q6 | 依赖新增批准 | 见 §9 | 批准必需 4 项；GitPython/PyYAML/pytest-cov 不引入；LLM 客户端随 Q4 |
| Q7 | 资源阈值默认值 | 见 §11.2 | 批准默认值；写入 `config/settings.py` |
| Q8 | 可信 Fixture 执行策略 | A. 仅 `tests/fixtures/trusted_repo/` 白名单可在宿主机执行；外部 GitHub 一律 `not_executed`；B. 任何仓库加 `--trusted` 即可执行；C. 全部不执行 | **A**；B 违反《阶段1_Prompt》§7.1；C 无法满足 AC-1-09 |
| Q9 | 阶段 1 Finding 元数据与产物模型位置 | A. `agent_name="Stage1ReviewAgent"`、`task_type="stage1_review"`、全部 `unverified`；产物模型放 `reporting/artifact_models.py`；B. 其他命名/位置 | **A** |
| Q10 | 是否允许修改 `acceptance.md`/`architecture.md` 记录阈值与组件映射 | A. 允许，走变更记录；B. 不改冻结文档，只在 `config/settings.py` + 阶段 1 验收报告记录 | **B**（优先不改冻结文档；如 D2 要求必须写入 acceptance，则 A） |
| Q11 | 三份未提交文档修改如何处理 | A. 确认并提交为阶段 1 前基线；B. 回退；C. 保持未提交 | **A**（已人工确认这些修改并提交为阶段 1 前基线） |
| Q12 | 验收结论体系与 TC-1-06 无 API Key | A. 采用 PASS/BLOCKED/FAIL；TC-1-06 记 BLOCKED；B. 严格按 acceptance “通过/不通过”，无 Key 即不通过 | **A**（在验收报告中同时注明 acceptance 口径） |
| Q13 | 真实 Clone 目标仓库 | A. `pallets/itsdangerous`；B. 其他公开 Python 仓库 | **A**（小体积、可访问、公开） |

### 11.2 建议默认值（如无异议，实施中采用）

#### 仓库与资源限制

| 配置 | 默认值 | 理由 |
|---|---|---|
| `clone_timeout_seconds` | 300 | 公开中小仓库足够；避免网络挂起 |
| `max_repository_size_mb` | 200 | 覆盖多数中小 Python 仓库；超出拒绝 |
| `max_file_count` | 5000 | 防止超大仓库遍历；超出拒绝 |
| `max_file_size_mb` | 2 | 单文件分析上限；超出跳过并记录 |
| `max_total_scan_size_mb` | 50 | 控制扫描总量；超出拒绝 |
| `workspace_root` | 系统临时目录下 `code_review_workspaces` | 不写入仓库目录；便于清理 |
| `keep_workspace_on_failure` | `false` | 默认清理；失败日志记录路径 |
| `git_timeout_seconds` | 300 | 与 clone 超时一致 |

#### 工具执行

| 配置 | 默认值 | 理由 |
|---|---|---|
| `tool_timeout_seconds` | 120 | 单工具（Ruff/Bandit/Radon）上限 |
| `tool_max_output_bytes` | 5 MiB | 防止输出爆炸 |
| `max_findings_per_tool` | 1000 | 防止 Finding 数量失控 |
| `ruff_cache_dir` | 工作区外临时目录 | 保持仓库只读 |
| `bandit_args` | `-q -f json` | 机器可读、少噪声 |
| `radon_args` | `cc -j`、`mi -j` | 机器可读 |

#### 测试与覆盖率

| 配置 | 默认值 | 理由 |
|---|---|---|
| `test_timeout_seconds` | 300 | 可信 Fixture 足够 |
| `coverage_timeout_seconds` | 300 | 与测试一致 |
| `max_test_output_bytes` | 5 MiB | 防止输出爆炸 |
| `trusted_repositories` | `["trusted_fixture_v1"]` | 仅项目自维护 Fixture |
| `allow_host_test_execution` | 仅对白名单 Fixture 生效 | 不接受用户任意 URL + 开关 |

#### LLM

| 配置 | 默认值 | 理由 |
|---|---|---|
| `llm_timeout_seconds` | 60 | 外部调用超时（NFR-R2） |
| `llm_max_input_chars` | 60,000 | 控制上下文规模（NFR-X2） |
| `llm_max_output_tokens` | 2,000 | 控制成本/延迟 |
| `llm_temperature` | 0.0 | 结构化输出稳定 |
| `llm_max_proposals` | 50 | 防止模型输出过多 Finding |
| `llm_enabled` | 有 API Key 时 true | 无 Key 时记录 `not_configured` |

#### 报告与安全

| 配置 | 默认值 | 理由 |
|---|---|---|
| `report_output_dir` | `reports` | 与现有目录一致 |
| `review_id_format` | `review-<UTC yyyymmddThhmmssZ>-<8hex>` | 安全目录名、可排序 |
| `allowed_hosts` | `["github.com"]` | 仅 GitHub |
| `allowed_ports` | `[443]` 或省略 | 仅 HTTPS 默认端口 |
| `branch_pattern` | `^[A-Za-z0-9._/-]+$`，禁止前导 `-`、`..` | 防参数注入 |
| `commit_sha_pattern` | `^[0-9a-f]{40}$` | 固定完整 SHA |
| `excluded_dirs` | `.git`、`__pycache__`、`.venv`、`venv`、`node_modules`、`build`、`dist`、`.tox`、`.mypy_cache`、`.ruff_cache`、`.pytest_cache` | 常规排除 |
| `sensitive_patterns` | `.env`、`.env.*`、`*.pem`、`*.key`、`id_rsa`、`id_ed25519`、`.git-credentials`、`.netrc`、`*.p12`、`*.pfx`、`secrets.*`、`credentials*` | 敏感文件隔离 |
| `follow_symlinks` | `false` | 防止逃逸 |
| `max_text_length` | title 200；description/evidence/recommendation 4000 | 合同 JS-11 |

---

## 12. 就绪结论与下一步

### 12.1 就绪状态

| 维度 | 状态 | 说明 |
|---|---|---|
| 阶段 0 代码基线 | READY | 204/204 通过；Schema/Settings 可用 |
| 环境基线 | READY WITH CAUTION | 项目环境可用；但 `python`/`pytest` 错位，必须固定命令 |
| 文档基线 | NOT READY | 13 项 P0 冲突/缺口；`acceptance.md` 无阈值/命令 |
| 依赖基线 | NOT READY | ruff/bandit/radon/coverage 未安装；新增需批准 |
| 安全方案 | CONDITIONAL | 控制措施已设计；可信 Fixture/阈值/URL 白名单待批准 |
| 测试方案 | CONDITIONAL | 单测/集成/安全/真实 Clone/LLM 冒烟方案已列；依赖裁定 |
| **总体** | **BLOCKED** | 待 P0 裁定后进入 Stage 1.1 |

### 12.2 建议的下一步

1. 项目负责人审阅本报告，逐项回答 §11.1 的 Q1～Q13；如同意 §11.2 默认值，可一次性确认。
2. 批准新增依赖清单（Ruff、Bandit、Radon、Coverage；LLM 客户端随 Q4）。
3. 确认三份未提交文档修改作为阶段 1 前基线，或指定回退/保留方式。
4. 确认可信 Fixture 执行策略（Q8）与真实 Clone 目标（Q13）。
5. 以上确认后，进入 Stage 1.1；Stage 1.1 完成并提供测试证据后，再决定是否进入 Stage 1.2。

### 12.3 本报告未做的事项

- 未修改任何代码、Schema、依赖、核心文档。
- 未安装 ruff/bandit/radon/coverage 或任何新依赖。
- 未创建 `services/`、`tools/`、`reporting/`、`api/`、`cli.py`。
- 未生成任何虚构的审查结果、Finding、覆盖率或 `ReviewReport`。
- 未执行外部仓库代码或真实 LLM 调用。
