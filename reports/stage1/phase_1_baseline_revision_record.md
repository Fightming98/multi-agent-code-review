# 阶段 1 实施基线修订记录

| 项目 | 内容 |
| --- | --- |
| 记录日期 | 2026-11-10 |
| 修订依据 | `实施决策.md` Q1～Q13；`reports/phase_1_pre_implementation_check_report.md` |
| 修订范围 | `docs/acceptance.md`、`docs/architecture.md`、`docs/requirements.md`、`docs/workflow.md`、`项目总框架与实施计划V2.0.md`、`CLAUDE.md`、`阶段1_Prompt.md` |
| 当前状态 | 修订完成，**尚未提交**；等待项目负责人人工确认 |
| Stage 1.1 | **未开始**；未安装阶段 1 依赖，未创建阶段 1 代码目录 |
| 测试证据 | 阶段 0 单元测试 `204 passed`（2026-11-10，Python 3.12.16） |

> 本记录只记录“实施基线修订”本身，不代表 Stage 1.1 已启动，也不代表阶段 1 已验收。

---

## 1. 修订结论

1. `实施决策.md` 的 Q1～Q13 已落实到文档基线；AC 编号仍以 `docs/acceptance.md` 原文为唯一权威。
2. 阶段 1 的交付边界已统一为：
   - 最小同步 FastAPI `POST /api/reviews` 为**必做**；
   - 只生成 `metadata.json`、`static_analysis.json`、`test_report.json`、`report.md` 四件产物，不生成 `report.json`；
   - 不引入 LangGraph、Semgrep、Gitleaks、pip-audit；
   - LLM 只做非 Agent 的语义解释与补充，证据必须来自真实工具调用；
   - 外部 GitHub 仓库的测试执行状态强制为 `not_executed`；仅 `tests/fixtures/trusted_repo/` 项目自维护 Fixture 可在宿主机执行 Pytest/Coverage。
3. 阶段 1 验收采用 `PASS` / `BLOCKED` / `FAIL` 三态；无合法 API Key 时 TC-1-06 记 `BLOCKED`，阶段 1 整体不得判 `PASS`。
4. 未修改 `docs/task_contracts.md`，未修改阶段 0 三个核心 Schema 文件，未新增任何依赖。
5. 阶段 0 回归测试通过：`204 passed in 1.48s`。

---

## 2. 逐项变更对照（原内容 → 新内容）

> 以下按变更点摘录原始内容与新内容；完整统一 diff 可在仓库根目录执行 `git diff -- <文件路径>` 查看。当前工作区 diff 统计：7 个已跟踪文件，278 insertions / 98 deletions；其中 `.gitignore` 的 2 行改动不是本次修订产生，未纳入提交建议（见 §5）；`项目总框架与实施计划V2.0.md` 包含此前的未提交修改。

### 2.1 Q1：AC 编号权威性

| 文件 | 原内容 | 新内容 |
| --- | --- | --- |
| `阶段1_Prompt.md` §14 | AC-1-01～AC-1-15 映射表与 `acceptance.md` 原文错位（如把 AC-1-09 写成其他含义） | 按 `acceptance.md` 原文重排：AC-1-01 Clone+SHA、AC-1-02 URL、AC-1-03 资源限制、AC-1-04 源码识别/过滤、AC-1-05 敏感信息、AC-1-06 Ruff、AC-1-07 Bandit、AC-1-08 Radon、AC-1-09 可信仓库 Pytest+Coverage、AC-1-10 外部仓库 `not_executed`、AC-1-11 工具限制、AC-1-12 只读、AC-1-13 LLM、AC-1-14 CLI/FastAPI 同一 `ReviewService`、AC-1-15 四件产物 |
| `阶段1_Prompt.md` §14 | 无编号权威性说明 | 增加说明：`acceptance.md` 是唯一验收依据；本文其他章节如出现旧编号，以原文为准 |
| `阶段1_Prompt.md` §16 | Stage 1.1 验收写为 AC-1-01、AC-1-02、AC-1-04 | 改为 AC-1-01、AC-1-02、AC-1-03 |
| `阶段1_Prompt.md` §16 | Stage 1.2 验收写为 AC-1-03、AC-1-05 | 改为 AC-1-04、AC-1-05 |
| `阶段1_Prompt.md` §16 | Stage 1.4 验收与 AC-1-11 混用 | 改为 AC-1-09、AC-1-10、AC-1-12；注明测试执行超时是内部质量项，AC-1-11 只针对静态分析工具 |
| `CLAUDE.md` 注意事项 | 未说明编号权威性 | 增加“AC 编号以 `docs/acceptance.md` 原文为准；`阶段1_Prompt.md` §14 旧映射已修正” |
| `docs/acceptance.md` 头部 | v1.0，阶段 0 | v1.1，阶段 1 实施基线；明确不修改 AC-1-01～AC-1-15 编号与既有语义 |

### 2.2 Q2 / C2：FastAPI 为阶段 1 必做

| 文件 | 原内容 | 新内容 |
| --- | --- | --- |
| `docs/acceptance.md` §4.2 | “可选的 `POST /api/reviews`” | “最小同步的 `POST /api/reviews`（阶段 1 必做）” |
| `docs/acceptance.md` AC-1-14 | “CLI 与 FastAPI（若实现）调用同一个 `ReviewService`” | “CLI 与 FastAPI 调用同一个 `ReviewService`；FastAPI 仅提供受控的同步入口” |
| `docs/architecture.md` §5 / §6.1 / §7.1.1 | “FastAPI 仅为可选的本地演示与接口测试入口” | “FastAPI 为阶段 1 必做的受控同步入口”；§7.1.1 明确 `api/` 落位 |
| `docs/requirements.md` §8 阶段表 | “CLI + 可选 FastAPI” | “CLI + 最小同步 FastAPI（阶段 1 必做）” |
| `docs/workflow.md` §7 | “FastAPI 的 `POST /api/reviews` 为可选演示入口” | “为受控同步入口（阶段 1 必做最小实现，与 CLI 共用 `ReviewService`）” |
| `项目总框架与实施计划V2.0.md` §阶段 1～3 执行模式 | “FastAPI：作为可选的本地演示和接口测试入口”；“可以同步调用” | “受控入口（2026-11-10 修订：阶段 1 为必做的最小同步实现）”；“同步调用 ReviewService（阶段 1 必做的最小实现）” |
| `阶段1_Prompt.md` §9 | “可选 FastAPI 同步演示入口” | “最小同步 FastAPI 入口（阶段 1 必做，与 CLI 共用 `ReviewService`）” |
| `CLAUDE.md` 架构大图 | “FastAPI 只是可选本地演示” | “阶段 1 实现最小同步 FastAPI `POST /api/reviews`（受控本地演示/接口测试）” |

### 2.3 Q3：阶段 1 只生成四件产物

| 文件 | 原内容 | 新内容 |
| --- | --- | --- |
| `docs/acceptance.md` AC-1-15 | “JSON 输出符合 `task_contracts.md`” | 三份 JSON 分别符合阶段 1 专用 Pydantic Artifact Schema；`report.md` 由三份结构化数据渲染；不要求完整 `ReviewReport` |
| `docs/acceptance.md` §4.9 | 无 | 新增：仅四件产物；Artifact Schema 位于 `reporting/artifact_models.py`；不得修改阶段 0 三个核心 Schema 文件；`Stage1Analyzer`/`unverified`/`llm_analysis.rejected[]` 规则 |
| `docs/architecture.md` §3⑦ | 报告目录含 `report.json`，阶段 1 起 | 阶段 1 四件；`report.json` 自阶段 2 起增加 |
| `docs/architecture.md` §6.1 | 阶段 1 流程图直接进入 LangGraph 并输出报告 | 阶段 1：`ReviewService` → 工具链 + 报告模块（无 LangGraph）；阶段 2 起虚线进入 LangGraph |
| `docs/workflow.md` §1.3 / §6 / §8.7 | 报告生成阶段写作“1～2”，目录含 `report.json` | 阶段 1 只生成 `report.md`；`report.json` 自阶段 2 起；§8.7 增加阶段 1 四件产物说明 |
| `docs/requirements.md` FR-9.1 | “JSON 报告必须符合 `ReviewReport` Schema。\| 1 起” | 阶段 1 三份基础 JSON 符合阶段 1 Artifact Schema；完整 `ReviewReport` 自阶段 2 起 |
| `CLAUDE.md` 注意事项 | 未说明 | 增加“阶段 1 只生成四件产物，不生成 `report.json`” |
| `阶段1_Prompt.md` | 原有多处“report.json/完整报告”表述 | 已按四件产物口径修正报告章节与验收章节 |

### 2.4 Q4 / C5：阶段 1 LLM 辅助分析边界

| 文件 | 原内容 | 新内容 |
| --- | --- | --- |
| `docs/architecture.md` §8.1 | 无阶段 1 LLM 分析说明 | 新增非 Agent LLM 分析流程图：工具证据 → LLM Analyzer → Finding 提案 → 确定性证据校验 → 正式 Finding 或 `llm_analysis.rejected[]` |
| `docs/architecture.md` §8.1 | 无 | 明确 LLM 不得创造 `ToolEvidence`、不得伪造路径/行号/代码片段；模型失败时保留确定性工具结果 |
| `docs/acceptance.md` §4.2 | “LLM Provider（兼容 OpenAI API 的国内模型服务）” | “LLM 语义分析模块（兼容 OpenAI API 的国内模型服务，如 DeepSeek；Provider 通过 `config/settings.py` 注入）” |
| `CLAUDE.md` 注意事项 | 未说明阶段 1 LLM 落位 | 增加“阶段 1 使用 `services/llm_analyzer.py` 做非 Agent LLM 分析；`agents/` 仍属阶段 2” |

### 2.5 Q5：组件目录映射

| 文件 | 原内容 | 新内容 |
| --- | --- | --- |
| `docs/architecture.md` §7.1.1 | 无阶段 1 组件映射表 | 新增 13 个组件的精确路径：`tools/repository_manager.py`、`tools/repository_inspector.py`、`tools/url_validator.py`、`tools/file_filters.py`、`tools/base.py`（AnalysisTool + ToolExecutionResult）、`services/review_service.py`、`services/llm_analyzer.py`、`reporting/artifact_models.py`、`reporting/report_generator.py`、`reporting/markdown_renderer.py`、`cli.py`、`api/` |
| `docs/architecture.md` §7.1.1 | 无依赖方向说明 | 增加：`schemas` 不反向依赖 `services`；`tools` 不调用 `ReviewService`；CLI/API 只调用 `ReviewService`；`ReviewService` 调用工具、聚合器与报告模块 |

### 2.6 Q6 / C4：阶段 1 工具范围

- 阶段 1 固定使用 Ruff、Bandit、Radon、Pytest、Coverage。
- 不引入 Semgrep、Gitleaks、pip-audit；这些工具在总体计划详细表中已标注为阶段 3，**本次未修改总体计划的技术选型阶段列**。
- **更正实施前检查报告的 C4 误述**：`reports/phase_1_pre_implementation_check_report.md` 曾称“总体计划把 Semgrep/Gitleaks/pip-audit 标为阶段 1”，经复核该表原文（详细版技术栈表）已标注为阶段 3。该 C4 结论作废，以本节为准。

### 2.7 Q7：资源阈值

| 文件 | 原内容 | 新内容 |
| --- | --- | --- |
| `docs/acceptance.md` §4.7 | 无阶段 1 阈值表 | 新增 18 项阈值：Clone/Git 300s、仓库 200MB、文件数 5,000、单文件 2MB、总扫描 50MB、单工具 120s、stdout/stderr 各 5MiB、Finding 上限 1,000、Pytest/Coverage 300s、LLM 60s / 60,000 字符 / 2,000 tokens / temperature 0.0 / 提案上限 50、可信仓库仅 `trusted_fixture_v1`、GitHub 仅 `github.com`、端口 443/默认 |
| `docs/acceptance.md` §4.7 | 无超限语义 | 增加拒绝 vs 跳过 vs 截断 vs `partial` 的区别；Clone 过程中监控磁盘；终止 Git 进程树；`keep_workspace_on_failure=false` 但保留诊断证据；阈值集中在 `config/settings.py` |

### 2.8 Q8：可信测试 Fixture

| 文件 | 原内容 | 新内容 |
| --- | --- | --- |
| `docs/acceptance.md` §4.8 | 无 | 新增 8 条规则：仅 `tests/fixtures/trusted_repo/`；固定版本/哈希；不接受任意 URL + `--trusted`；不自动安装依赖；不执行 `setup.py`/`build.py`/安装脚本；外部仓库 `not_executed`；报告区分可信 Fixture 与外部数据；阶段 2 起仍按沙箱策略 |
| `CLAUDE.md` 关键不变量 | “未沙箱化前，测试执行状态必须为 `not_executed`” | 改为“外部仓库测试执行状态必须为 `not_executed`”，并新增阶段 1 可信 Fixture 受控例外段落 |

### 2.9 Q9：Finding 来源与产物模型

| 文件 | 原内容 | 新内容 |
| --- | --- | --- |
| `docs/acceptance.md` §4.9 | 无 | `agent_name="Stage1Analyzer"`；`task_type="stage1_review"` 仅在实际创建任务对象时使用；所有阶段 1 Finding `verification_status="unverified"`，工具或 LLM 不得标记 `verified`；LLM 不合格提案进 `llm_analysis.rejected[]`；产物模型在 `reporting/artifact_models.py` |
| `docs/architecture.md` §8.1 | 无 | Finding 节点标注 `agent_name=Stage1Analyzer`、`verification_status=unverified`；拒绝提案进 `llm_analysis.rejected[]` |
| `CLAUDE.md` 数据契约 | 未说明阶段 1 来源标识 | 增加 `Stage1Analyzer`、`unverified`、`llm_analysis.rejected[]`、`reporting/artifact_models.py` 与“不修改三个核心 Schema 文件” |

### 2.10 Q10：冻结文档修改规则

| 文件 | 原内容 | 新内容 |
| --- | --- | --- |
| `docs/acceptance.md` §4.11 | 无 v1.1 变更记录 | 新增 v1.1 变更记录：原因、修改、影响、未修改、测试同步 |
| `docs/architecture.md` 修订记录 | 仅有 v1.0 | 新增 v1.1：修正 LangGraph 提前出现、四件产物、§7.1.1、§8.1 |
| `docs/requirements.md` 修订记录 | 仅有 v1.0 | 新增 v1.1：FR-9.1 与阶段表 FastAPI 口径 |
| `docs/workflow.md` 修订记录 | 仅有 v1.0 | 新增 v1.1：§8.7 四件产物、§10 无 LangGraph、§2/§6/§7 入口口径 |
| `docs/task_contracts.md` | — | **未修改** |

### 2.11 Q11：三份未提交文档

- `docs/architecture.md`、`docs/requirements.md`、`项目总框架与实施计划V2.0.md` 已纳入本次修订范围，拟作为正式基线提交的一部分。
- 由于修订同时涉及 `docs/acceptance.md`、`docs/workflow.md`、`CLAUDE.md`、`阶段1_Prompt.md`，实际提交范围需负责人确认（见 §5）。
- `项目总框架与实施计划V2.0.md` 中已有的历史未提交修改（技术栈详细表、排版整理等）一并保留，未回退。

### 2.12 Q12：三态验收结论

| 文件 | 原内容 | 新内容 |
| --- | --- | --- |
| `docs/acceptance.md` TC-1-06 | “一次真实模型调用的冒烟测试……不纳入常规单元测试” | 增加：无合法 API Key 记 `BLOCKED / NOT RUN`，不得记 PASS；阶段 1 整体同时为 `BLOCKED` |
| `docs/acceptance.md` §4.5 | 只有“全部满足”的通过条件 | 增加三态规则：`PASS` / `BLOCKED` / `FAIL`；`BLOCKED ≠ PASS`，必须保留状态与原因 |
| `docs/acceptance.md` §4.11 | 无 | 变更记录补充三态规则 |
| `阶段1_Prompt.md` TC-1-06 行 | “真实模型调用冒烟测试或明确记录未执行原因” | “无合法 API Key 时记 BLOCKED / NOT RUN，Stage 1 整体不得判 PASS” |
| `CLAUDE.md` 工作规则 | “验收报告必须如实写 PASS/FAIL/BLOCKED” | 保留，并与 acceptance 三态规则一致 |

### 2.13 Q13：真实 Clone 目标

| 文件 | 原内容 | 新内容 |
| --- | --- | --- |
| `docs/acceptance.md` §4.10 | 无阶段 1 验收命令 | 新增：真实 Clone 目标 `https://github.com/pallets/itsdangerous` 的 CLI 命令；明确只验证获取与静态分析，不执行外部仓库 Pytest/安装/构建 |
| `阶段1_Prompt.md` | 未固定目标仓库 | 按 `实施决策.md` Q13 固定为 `pallets/itsdangerous` |

---

## 3. AC / TC 影响矩阵

| 编号 | 是否修改语义 | 影响说明 |
| --- | --- | --- |
| AC-1-01～AC-1-08 | 否 | 编号与语义未变；仅在验收命令/Stage 拆分中对齐 |
| AC-1-09 | 否 | 明确为“可信仓库 Pytest + Coverage” |
| AC-1-10 | 否 | 明确为“外部不可信仓库不执行测试，状态 `not_executed`” |
| AC-1-11 | 否 | 仅补充阈值落点；测试执行超时不归入 AC-1-11 |
| AC-1-12 | 否 | 只读工作区要求不变 |
| AC-1-13 | 否 | 补充阶段 1 非 Agent LLM 分析边界与证据校验 |
| AC-1-14 | 是（表述） | “若实现”改为必做；仍要求 CLI/API 共用 `ReviewService` |
| AC-1-15 | 是（表述） | 三份 JSON 改为阶段 1 Artifact Schema；`report.md` 由三份结构化数据渲染；不要求完整 `ReviewReport` |
| TC-1-01～TC-1-05 | 否 | 验收方式不变 |
| TC-1-06 | 是（结论规则） | 无 API Key 时记 `BLOCKED / NOT RUN`；阶段 1 不得判 PASS |

涉及模块：`tools/`、`services/`、`reporting/`、`cli.py`、`api/`；不涉及 `agents/`、`graph/`、`orchestration/`（阶段 2 起）。

---

## 4. 测试与验证证据

| 项目 | 结果 |
| --- | --- |
| 命令 | `conda run -n multi-agent-review python -m pytest tests/unit -q` |
| 结果 | `204 passed`（两次回归：1.48s / 0.46s） |
| Python | 3.12.16 |
| 阶段 1 依赖安装状态 | `ruff`、`bandit`、`radon`、`coverage` 均**未安装**（`find_spec` 为 `False`） |
| 阶段 1 代码 | 未创建 `tools/`、`services/`、`reporting/`、`api/`、`cli.py` 等实现 |
| 阶段 1 目录 | 未创建 `agents/`、`graph/` 等阶段 2 目录 |
| 网络/LLM | 未联网；未调用真实 LLM |
| 提交状态 | 负责人已确认提交；本记录随基线提交进入版本库，提交哈希见 `git log -1` |

---

## 5. 提交建议与未决事项

### 5.1 已确认的提交范围（2026-11-10）

负责人确认：`reports/*` 提交；以下基线范围提交。

- `docs/acceptance.md`
- `docs/architecture.md`
- `docs/requirements.md`
- `docs/workflow.md`
- `项目总框架与实施计划V2.0.md`
- `CLAUDE.md`
- `阶段1_Prompt.md`（未跟踪，纳入基线）
- `实施决策.md`（未跟踪，纳入基线）
- `.gitignore`（保留 `reports/*` 注释状态，使 `reports/` 可提交）
- `reports/`（阶段 0/1 验收与评审记录，纳入版本控制）

### 5.2 未决事项

1. 是否创建 Git tag（阶段 0 首次提交未创建 tag）。
2. Stage 1.1 的依赖版本固定：`ruff`、`bandit`、`radon`、`coverage` 安装前需确认版本并写入 `environment.yml`。
3. 阶段 1 LLM Provider 的具体模型名、Base URL、环境变量命名，需在 Stage 1.5 前确认。

---

## 6. 明确未做的事情

- 未安装任何新依赖。
- 未创建 `tools/`、`services/`、`reporting/`、`api/`、`cli.py` 等阶段 1 实现。
- 未创建 `agents/`、`graph/` 等阶段 2 目录。
- 未修改 `docs/task_contracts.md`。
- 未修改阶段 0 三个核心 Schema 文件。
- 未执行真实 GitHub Clone。
- 未调用真实 LLM。
- 未提交 Git。
- **Stage 1.1 尚未开始。**

---

## 7. 结论

本次实施基线修订已完成文档层面的 Q1～Q13 落点，阶段 0 回归测试保持 204 条全部通过。负责人已于 2026-11-10 确认提交范围，修订内容随基线提交进入版本库；基线提交完成后仍不进入 Stage 1.1，等待下一步指令。
