# 需求文档（Requirements）

| 项目 | 内容 |
| --- | --- |
| 项目名称 | Multi-Agent Code Review System（多 Agent 协作代码审查系统） |
| 文档版本 | v1.1（阶段 1 实施基线修订） |
| 适用范围 | Multi-Agent Code Review System 阶段 0～阶段 7 的工程实施基线 |
| 当前阶段 | 阶段 1：单 Agent 工程基础（实施基线） |
| 最后更新 | 2026-11-10 |
| 状态 | 已冻结（Frozen）；阶段 1 澄清见 FR-9.1、§8、修订记录 |
| 关联文档 | `architecture.md`、`workflow.md`、`task_contracts.md`、`acceptance.md` |

> 本文档回答“系统要做什么、不做什么、做到什么程度”。系统如何搭建见 `architecture.md`，业务如何流转见 `workflow.md`，数据如何约定见 `task_contracts.md`，如何判定完成见 `acceptance.md`。

---

## 1. 项目背景与业务目标

### 1.1 背景

代码审查是软件质量保障的关键环节，但人工审查耗时长、覆盖维度不一致，且高度依赖审查者经验。单一的 LLM 审查工具又存在三个典型问题：

1. 一次性处理所有维度，容易遗漏或相互干扰；
2. 结论往往只是自然语言，缺少代码位置和工具证据，无法核验；
3. 缺少任务管理、失败恢复与可观测能力，难以用于真实工程。

本项目以“多个专业 Agent 分工协作 + 确定性分析工具佐证 + 独立的证据核验节点”的方式解决上述问题，并作为一个可运行、可测试、可演示、可部署的完整 AI Agent 工程项目。

### 1.2 业务目标

> 用户输入一个 GitHub 仓库 URL，系统自动获取代码，由 Manager Agent 负责任务规划和编排，多个专业 Agent 并行完成安全、质量、性能、测试四个维度的审查，通过结构化任务通信、完成事件通知、失败恢复等机制协作，最后由 Final Reviewer 核验证据并生成结构化审查报告，必要时将结果回写到 GitHub PR。

| 编号 | 目标 | 衡量方式（详见 `acceptance.md`） |
| --- | --- | --- |
| G1 | 能对受控 Python 仓库完成端到端审查并产出结构化报告 | 阶段 2 端到端验收 |
| G2 | 每一个审查结论都可追溯到代码位置或工具证据 | Finding 合同校验 + Evidence Validator |
| G3 | 多 Agent 并行执行，单个 Agent 失败不拖垮整体 | 并行时间线 + 故障注入测试 |
| G4 | 工程可靠：任务可排队、可重试、可恢复、可查询 | 阶段 4 验收 |
| G5 | 工具与 Agent 协议标准化（MCP / A2A），权限隔离 | 阶段 5、6 验收 |
| G6 | 全链路可观测：Trace、Token、成本、日志 | 阶段 7 验收 |
| G7 | 作为求职作品，能够完整讲解设计原理与工程取舍 | 文档、测试、演示齐全 |

### 1.3 核心工程原则

1. **先实现可靠的单进程多 Agent 系统，再逐步演进为分布式多 Agent 系统。** 不在第一天同时引入 LangGraph、A2A、MCP、Redis、Docker、Webhook 和多个独立服务，否则出现问题时无法判断是 Agent 推理、任务调度、通信协议还是基础设施导致的。
2. **每个阶段必须先通过验收，再进入下一阶段。** 不得为了提前展示高级技术而跳过前置阶段的基础验收。
3. **确定性工具负责“可重复验证”，LLM 负责“理解与解释”。** 覆盖率、测试结果、静态分析结果必须来自真实工具输出，不得由 LLM 猜测或编造。
4. **仓库内容一律视为不可信输入。** 源码、README、Issue、PR 描述都可能包含 Prompt Injection，不得当作系统指令。
5. **固定四个核心评分维度。** Security、Quality、Performance、Testing 是**固定的四个核心评分维度**；SubAgent 和外部 A2A Agent 是执行扩展，不自动改变核心评分结构（`ReviewReport` 的 `dimension_scores` 与 `agent_results` 始终是这四个维度）。

---

## 2. 项目解决的核心问题

| 编号 | 问题 | 本项目的对策 |
| --- | --- | --- |
| Q1 | 单 Agent 一次处理所有审查维度，质量不稳定 | 按安全、质量、性能、测试四个维度拆分为专业 Agent，通过不同 Prompt、工具与输出 Schema 实现分工。 |
| Q2 | Agent 结论缺少证据，真假难辨 | 统一 `Finding` 合同，强制绑定代码位置或工具证据；Final Reviewer 做证据核验。 |
| Q3 | 多 Agent 之间输入输出格式不一致 | 先定义 `AgentTask / AgentResult / Finding / ReviewReport` 合同，再写 Agent。 |
| Q4 | 并行节点同时改写共享状态导致冲突 | 每个 Worker 只更新自己的结果字段，使用 Reducer 合并列表型状态。 |
| Q5 | 多个 Agent 重复报告同一问题 | 明确职责边界，并由 Final Reviewer 进行 Finding 去重。 |
| Q6 | 长任务、失败、重复执行无法管理 | 异步队列、任务状态机、有限重试、超时、幂等机制、结果持久化（阶段 4）。 |
| Q7 | 工具调用不可控、不可审计 | 通过 MCP 标准化工具接入，并按 Agent 做权限隔离（阶段 5）。 |
| Q8 | 无法知道一次审查花了多少、哪里出错 | 统一 Trace、Token 统计、结构化日志（阶段 7）。 |
| Q9 | 执行不可信仓库代码带来安全风险 | 静态分析优先；测试执行仅限可信仓库，外部仓库须在隔离沙箱中执行，否则标记 `not_executed`。 |

---

## 3. 用户与使用场景

### 3.1 用户角色

| 角色 | 描述 | 主要诉求 |
| --- | --- | --- |
| 开发者 | 提交仓库或 PR 的人 | 快速得到可操作的审查意见，了解问题位置与修复建议。 |
| 代码审查者 / 技术负责人 | 对合并负责的人 | 了解风险等级、是否建议合并，并能核验结论依据。 |
| 项目维护者（本项目作者） | 搭建并演示该系统的人 | 系统可运行、可测试、可追踪、可对外讲解。 |

### 3.2 使用场景

| 编号 | 场景 | 描述 | 引入阶段 |
| --- | --- | --- | --- |
| S1 | 审查指定仓库 | 用户通过 CLI 提交 GitHub 仓库 URL 与分支，系统返回 Markdown / JSON 审查报告。 | 1 |
| S2 | 通过 API 提交审查 | 通过 `POST /api/reviews` 提交审查请求，查询审查结果。 | 1（同步演示）/ 4（异步） |
| S3 | 多维度并行审查 | 同一仓库同时进行安全、质量、性能、测试审查，并看到各 Agent 的并行执行与独立耗时。 | 2 |
| S4 | 局部失败下的降级交付 | 某个 Agent 或子任务失败，系统重试后仍失败时，输出带“部分完成”标记的报告，而不是整体崩溃。 | 3～4 |
| S5 | PR 自动审查 | GitHub PR 触发 Webhook，系统后台审查并把结果回写为 PR 评论。 | 7 |
| S6 | 跨服务扩展审查 | 通过 A2A 接入独立部署的外部架构审查 Agent，与本地 Agent 并行工作。 | 6 |
| S7 | 过程追踪与成本复盘 | 查看一次审查的完整 Trace、每个 Agent 的耗时与 Token 成本。 | 7 |

---

## 4. Agent 职责定义

系统共有 **6 个核心 Agent**。Final Reviewer 在第一版中实现为 LangGraph 工作流中的一个独立 Node，不单独部署服务，也不创建独立运行时。

| Agent | 核心职责 | 主要输入 | 主要输出 |
| --- | --- | --- | --- |
| Manager | 任务规划、任务分配、执行协调、结果收集 | 仓库信息、审查目标 | Task Plan、任务执行状态、Agent 结果集合 |
| Security | 安全审查 | 代码、依赖、配置 | 安全漏洞、风险等级、代码证据 |
| Quality | 代码质量审查 | 源代码、静态检查结果 | 代码异味、复杂度、可维护性问题 |
| Performance | 性能分析 | 源代码、性能分析结果 | 性能瓶颈、性能风险、优化建议 |
| Testing | 测试执行与验证 | 仓库、测试配置、测试环境 | 测试结果、覆盖率、失败原因 |
| Final Reviewer | 证据核验、Finding 去重、综合评分、最终报告生成 | 四个专业 Agent 的结果、工具执行证据 | Final Review Report、审查结论、合并建议 |

### 4.1 Manager Agent

**职责**

1. **任务规划**：接收仓库信息与审查目标，决定本次需要执行哪些审查任务，生成 Task Plan。
2. **任务分发**：把规划出的任务按 `AgentTask` 合同分发给专业 Agent；每个 Worker 只拿到与自己任务相关的最小上下文。
3. **执行协调**：跟踪各任务状态，处理超时、失败与重试决策（具体机制阶段 4 实现）。
4. **结果收集**：收集专业 Agent 返回的 `AgentResult`，交给 Final Reviewer。

**明确不负责**

- **不替代专业 Agent 完成代码审查**：Manager 不自己分析代码、不自己扫描漏洞、不自己执行测试。
- **不直接生成最终审查结论**：评分、结论、最终报告全部由 Final Reviewer 产出。
- 不修改专业 Agent 的 Finding 内容。
- 不拥有仓库写权限。

### 4.2 Security Agent（安全审查）

| 项目 | 内容 |
| --- | --- |
| 关注范围 | 注入类漏洞（SQL、命令注入等）、硬编码密钥与凭证、不安全反序列化、危险函数使用、依赖漏洞、敏感配置。 |
| 证据来源 | Bandit（阶段 1）、Semgrep、Gitleaks（阶段 3 起）、依赖扫描；LLM 负责解释与补充语义层面的风险。 |
| 权限 | 只读代码，执行安全扫描类工具；不执行仓库业务代码。 |
| 子任务（阶段 3） | Dependency Scanner（依赖漏洞）、Secret Scanner（硬编码密钥）、Code Security Reviewer（代码安全风险）。 |
| 不负责 | 代码风格、复杂度、性能优化、测试覆盖率。 |

### 4.3 Quality Agent（代码质量）

| 项目 | 内容 |
| --- | --- |
| 关注范围 | 代码规范、代码异味、圈复杂度、重复代码、可维护性、错误处理缺失。 |
| 证据来源 | Ruff、Radon；LLM 负责解释并补充工具无法发现的可读性与设计问题。 |
| 权限 | 只读代码，执行静态检查类工具。 |
| 不负责 | 安全漏洞判定、性能瓶颈、测试执行。 |

### 4.4 Performance Agent（性能分析）

| 项目 | 内容 |
| --- | --- |
| 关注范围 | 算法复杂度、低效 I/O、N+1 查询、资源泄漏、阻塞调用、热点代码。 |
| 证据来源 | Radon 复杂度、静态模式识别；受控环境下的性能测试（后续阶段）。 |
| 权限 | 只读代码；不对外部不可信仓库做实际性能压测。 |
| 不负责 | 代码风格、安全漏洞、测试覆盖率。 |

### 4.5 Testing Agent（测试执行与验证）

| 项目 | 内容 |
| --- | --- |
| 关注范围 | 测试执行结果、失败用例及原因、测试覆盖率、缺失测试的区域。 |
| 证据来源 | Pytest、Coverage.py 的真实输出。**覆盖率与通过/失败数量不得由 LLM 猜测。** |
| 权限 | 可执行测试，但只能对**自己编写的可信仓库**执行；外部仓库需等 Docker 沙箱建立后才开放，且沙箱必须限制 CPU、内存、时间、网络与文件系统权限。 |
| 外部不可信仓库 | 在沙箱建立之前，测试状态必须标记为 `not_executed`，**不得伪造测试结果**。 |
| 不负责 | 安全漏洞判定、代码风格、性能分析。 |

### 4.6 Final Reviewer Agent（证据核验与最终报告）

| 项目 | 内容 |
| --- | --- |
| 职责 | ① 收集四个专业 Agent 的结果；② 合并重复 Finding；③ 检查文件路径、行号和证据片段；④ 对关键结论进行证据核验；⑤ 计算综合评分；⑥ 给出是否建议合并的结论；⑦ 生成 Markdown / JSON 报告。 |
| 输入 | 全部 `AgentResult`、工具执行证据、固定 Commit 的只读代码快照（用于证据核验）。 |
| 输出 | `ReviewReport`（Markdown + JSON）。 |
| 权限 | 只读审查结果与只读代码快照；**不得获得仓库写权限**；GitHub 评论必须由受控的发布模块执行。 |
| 评分规则 | 维度权重可配置（初始：Security 35%、Quality 25%、Performance 20%、Testing 20%，仅为项目初始配置，不代表行业标准）；每个配置权重必须大于 0 且不超过 1，四个配置权重之和为 1，报告存储的 `DimensionScore.weight` 始终保持原始配置值；缺失维度以 `score = null` 表示、不参与综合评分，仅在综合分计算公式内部对具有有效评分的维度按剩余权重归一化，不使用 `weight = 0`。任意维度中已核验（`verification_status = verified`）的 `critical` Finding 触发硬性阻断（`REQUEST_CHANGES`），不允许被其他维度高分抵消；外部 A2A Agent 的 Finding 经核验后可进入最终 `findings`，其已核验 `critical` 同样触发硬性阻断，但外部结果不进入四个核心维度的加权评分。 |
| 不负责 | 执行新的审查任务、调度子任务。 |

### 4.7 其他角色

| 角色 | 说明 | 引入阶段 |
| --- | --- | --- |
| SubAgent | 专业 Agent 内部的二级执行单元，可以是 LLM 驱动，也可以是确定性工具 Worker。首先在 Security Agent 中实现。 | 3 |
| External Architecture Review Agent | 通过 A2A 接入、独立部署的外部架构审查 Agent，负责模块依赖、架构设计、API 兼容性、跨文件逻辑等四个本地 Agent 的盲区。它**不属于**上述 6 个核心 Agent。 | 6 |

### 4.8 职责边界矩阵（防止重复审查）

| 问题类型 | 主责 Agent | 其他 Agent 的处理 |
| --- | --- | --- |
| 硬编码密钥、SQL 注入、命令注入 | Security | 不重复报告；如在其他维度发现，转交 Security 范畴。 |
| 圈复杂度、代码异味、重复代码、错误处理缺失 | Quality | Performance 不重复报告复杂度问题，只关注其对性能的影响。 |
| 算法复杂度、I/O 效率、资源使用 | Performance | Quality 不重复。 |
| 测试失败、覆盖率、缺失测试 | Testing | 其他 Agent 不得自行声称覆盖率或测试结论。 |
| 跨文件架构问题 | External Architecture Review（阶段 6） | 本地 Agent 不涉及。 |

即使存在边界重叠，也必须由 Final Reviewer 基于（文件路径、行号范围、问题类别）进行去重合并。

---

## 5. 功能需求（FR）

优先级说明：**P0** 核心业务能力（必须完成）；**P1** Agent 工程化与可靠性能力（重点完成）；**P2** 可观测性与产品化能力（逐步完善）。优先级表示交付价值，**不代表开发先后顺序**，开发顺序必须遵循阶段 0～7 的依赖关系。

### 5.1 工程基础（阶段 0）

| 编号 | 需求 | 优先级 | 阶段 |
| --- | --- | --- | --- |
| FR-0.1 | 建立 Conda 环境 `multi-agent-review`（Python 3.12），以 `environment.yml` 记录依赖。 | P0 | 0 |
| FR-0.2 | 建立 Python 工程骨架、`.env.example`、`.gitignore`、`README.md`，以 `pydantic-settings` 管理配置。 | P0 | 0 |
| FR-0.3 | 编写五份核心文档：`requirements.md`、`architecture.md`、`workflow.md`、`task_contracts.md`、`acceptance.md`。 | P0 | 0 |
| FR-0.4 | 实现 `AgentTask`、`AgentResult`、`Finding`、`ReviewReport` 的 Pydantic 数据合同。 | P0 | 0 |
| FR-0.5 | 为数据合同编写 Pytest 单元测试并全部通过。 | P0 | 0 |

### 5.2 接入与仓库获取（阶段 1）

| 编号 | 需求 | 优先级 | 阶段 |
| --- | --- | --- | --- |
| FR-1.1 | 提供 CLI 入口提交审查（阶段 1～3 的主要验收入口）。 | P0 | 1 |
| FR-1.2 | 提供 `POST /api/reviews`，请求包含 `repository_url`、`branch`；CLI 与 API 复用同一个 `ReviewService`，不得出现两套审查逻辑。 | P0 | 1 |
| FR-1.3 | 仅允许 HTTPS 的 GitHub 仓库 URL，限制域名与端口；防止 SSRF、恶意 Git URL、本地路径穿越。 | P0 | 1 |
| FR-1.4 | 获取仓库元数据，Clone 仓库，**固定本次审查的 Commit SHA**，生成审查上下文。 | P0 | 1 |
| FR-1.5 | 设置仓库大小、文件数量、单文件大小、下载时间限制。 | P0 | 1 |
| FR-1.6 | 遍历源码文件，识别语言，过滤二进制、大文件及 `.git`、`node_modules`、`.venv` 等目录，记录路径、语言、行数、大小。 | P0 | 1 |
| FR-1.7 | 不读取 `.env`、私钥、凭证等敏感文件作为 LLM 上下文。 | P0 | 1 |
| FR-1.8 | 仓库工作区默认只读。 | P0 | 1 |

### 5.3 代码分析工具（阶段 1）

| 编号 | 需求 | 优先级 | 阶段 |
| --- | --- | --- | --- |
| FR-2.1 | 接入 Ruff（规范/静态检查）、Bandit（安全）、Radon（复杂度），输出结构化结果。 | P0 | 1 |
| FR-2.2 | 接入 Pytest 与 Coverage.py，**仅对可信测试仓库执行**。 | P0 | 1 |
| FR-2.3 | 对外部不可信仓库，不在宿主机执行其测试、安装与构建脚本，测试状态标记为 `not_executed`。 | P0 | 1 |
| FR-2.4 | 为静态分析工具设置执行超时、输出大小与资源限制。 | P0 | 1 |
| FR-2.5 | 输出基础报告：`metadata.json`、`static_analysis.json`、`test_report.json`、`report.md`。 | P0 | 1 |

### 5.4 多 Agent 编排（阶段 2）

| 编号 | 需求 | 优先级 | 阶段 |
| --- | --- | --- | --- |
| FR-3.1 | 使用 LangGraph 定义 `ReviewState`，并行节点只更新自己的结果字段，列表型状态使用 Reducer 合并。 | P0 | 2 |
| FR-3.2 | Manager 生成 Task Plan 并向四个专业 Agent 分发 `AgentTask`，Worker 输入限制为对应任务合同。 | P0 | 2 |
| FR-3.3 | 实现 Security、Quality、Performance、Testing 四个专业 Agent，统一 `BaseAgent` 接口，统一返回 `AgentResult`。 | P0 | 2 |
| FR-3.4 | 实现并行 Fan-out / Fan-in，记录各 Agent 独立执行时间以证明并行。 | P0 | 2 |
| FR-3.5 | 实现 Final Reviewer：证据核验（Evidence Validator）、Finding 去重、可配置评分、合并建议，以及对任意维度已核验 `critical` Finding（含外部 A2A Agent Finding）的硬性阻断。 | P0 | 2 |
| FR-3.6 | 生成 Markdown 与 JSON 报告，并通过 Schema 校验。 | P0 | 2 |
| FR-3.7 | 所有 Finding 必须带代码位置或工具证据，行号对应固定的 Commit SHA。 | P0 | 2 |
| FR-3.8 | `ReviewReport` 必须包含四个固定维度（security / quality / performance / testing）的 `dimension_scores` 与 `agent_results`，失败的 Agent 也必须有 `failed` 的 `AgentResult`；所有维度均无有效评分时 `overall_score` 为 `null`、`report_status` 为 `partial`，结论在不存在已核验 `critical` Finding 时为 `COMMENT`，存在时为 `REQUEST_CHANGES`（RP-16 与 RP-06）。 | P0 | 2 |

### 5.5 SubAgent 与任务生命周期（阶段 3）

| 编号 | 需求 | 优先级 | 阶段 |
| --- | --- | --- | --- |
| FR-4.1 | Security Agent 内部拆解为三个子任务（依赖扫描、密钥扫描、代码安全审查），子任务有唯一 ID 与 Parent ID。 | P1 | 3 |
| FR-4.2 | 子任务可并行执行，使用 LangGraph SubGraph 或并行节点完成执行与汇合。 | P1 | 3 |
| FR-4.3 | 子任务完成或失败时发布 `TaskEvent`（进程内事件机制）；事件只用于通知与记录，不替代 LangGraph 的流程控制。 | P1 | 3 |
| FR-4.4 | 父任务在所有必需子任务完成或进入明确的部分完成状态之前，不得标记为成功。 | P1 | 3 |
| FR-4.5 | 单个子任务失败时保留其他子任务结果。 | P1 | 3 |
| FR-4.6 | 子任务并发数量受 Semaphore 限制（初始测试配置：Security SubAgent 局部并发 2）；全局并发限制在阶段 3 只做设计。 | P1 | 3 |

### 5.6 异步任务与失败恢复（阶段 4）

| 编号 | 需求 | 优先级 | 阶段 |
| --- | --- | --- | --- |
| FR-5.1 | FastAPI 接收审查任务后返回 `202 Accepted` 与 `review_id`，由 Redis + ARQ Worker 后台执行；FastAPI 不在请求线程中执行完整 Agent 工作流。 | P1 | 4 |
| FR-5.2 | 任务状态机具备合法迁移规则，禁止 `completed → running` 这类无明确重开逻辑的跳转。 | P1 | 4 |
| FR-5.3 | 失败重试：区分可重试与不可重试错误，设置单次超时，指数退避加随机抖动，限制最大重试次数，保存每次失败原因，支持人工重跑。 | P1 | 4 |
| FR-5.4 | 幂等：`review_id`、`delivery_id`（Webhook）、数据库唯一约束、任务状态校验，重复请求不产生重复的审查作业和重复报告。（GitHub 评论发布的幂等见 FR-8.4，属阶段 7。） | P1 | 4 |
| FR-5.5 | 三层并发控制：全局 Worker、Agent 级、工具级（初始测试配置：全局 SubAgent 并发 4；配置见 `architecture.md` §10.2）。 | P1 | 4 |
| FR-5.6 | PostgreSQL 持久化任务与结果；LangGraph Checkpointer 保存工作流状态与断点恢复；任务状态可查询。 | P1 | 4 |
| FR-5.7 | 子任务事件升级为可持久化、可确认消费的机制（Redis Streams 或等价方案，不使用普通 Pub/Sub 作为可靠通知存储）。 | P1 | 4 |
| FR-5.8 | Webhook 接收基础设施：HMAC-SHA256 签名校验、Payload 校验、`delivery_id` 幂等检查（不包含 GitHub PR 触发审查与评论回写，后者见 FR-8.4）。 | P1 | 4 |

### 5.7 MCP 工具接入（阶段 5）

| 编号 | 需求 | 优先级 | 阶段 |
| --- | --- | --- | --- |
| FR-6.1 | 独立构建 Code Analysis MCP Server，提供 `scan_security`、`check_quality`、`analyze_complexity`、`run_tests`、`get_coverage`、`get_file_content`。 | P1 | 5 |
| FR-6.2 | Agent 通过 MCP Client 发现并调用工具，不直接依赖具体工具实现。 | P1 | 5 |
| FR-6.3 | 工具权限隔离：每个 Agent 只能调用被授权的工具；所有工具校验仓库 ID、路径与执行参数。**权限必须由 MCP Server 端独立强制执行**（身份验证 + 服务端权限校验，默认拒绝），Agent 侧白名单仅作辅助。 | P1 | 5 |
| FR-6.4 | `run_tests` 必须在受限容器内执行，MCP Server 不得以高权限直接运行不可信代码。 | P1 | 5 |
| FR-6.5 | 工具返回结果符合 Pydantic Schema。 | P1 | 5 |

### 5.8 A2A 跨服务协作（阶段 6）

| 编号 | 需求 | 优先级 | 阶段 |
| --- | --- | --- | --- |
| FR-7.1 | 独立部署 External Architecture Review Agent，与主系统不共享 Python Runtime。 | P1 | 6 |
| FR-7.2 | 外部 Agent 暴露 Agent Card；主系统通过 A2A 发现能力、创建任务、跟踪长任务状态（轮询或 SSE）、接收 Artifact。 | P1 | 6 |
| FR-7.3 | A2A 的 Task / Message / Part / Artifact 与内部 `AgentTask` / `AgentResult` 有明确映射。 | P1 | 6 |
| FR-7.4 | `external_review_node` 与本地 Agent 并行执行；外部 Agent 不可用时记录失败并按策略重试或降级，输出部分完成报告。 | P1 | 6 |
| FR-7.5 | 外部 Agent 只获得必要的代码上下文。 | P1 | 6 |
| FR-7.6 | 外部 Agent 的结果放入 `external_agent_results`，经同样的证据核验与去重后可进入最终 Findings，但不参与四个核心维度的加权评分。 | P1 | 6 |

### 5.9 可观测性与产品化（阶段 7）

| 编号 | 需求 | 优先级 | 阶段 |
| --- | --- | --- | --- |
| FR-8.1 | 统一 Trace：一次审查对应一个 `trace_id`，Agent、SubAgent、MCP 调用、A2A Task 均关联该 Trace（OpenTelemetry，LangSmith 辅助调试）。 | P2 | 7 |
| FR-8.2 | 记录各 Agent 的 Token 使用量与成本，必须使用模型响应中的真实 `usage`，不得按字符数估算冒充。 | P2 | 7 |
| FR-8.3 | 统一结构化执行日志（structlog）。 | P2 | 7 |
| FR-8.4 | GitHub PR 集成：PR Webhook 触发审查，并将结果以评论形式回写（由受控发布模块执行，具备**独立的评论发布幂等键**，重复触发不产生重复评论）。 | P2 | 7 |
| FR-8.5 | Streamlit Web Dashboard：创建任务、实时查看 Agent 状态、查看各 Agent 结果、查看最终报告与成本。 | P2 | 7 |
| FR-8.6 | Docker Compose 多服务部署。 | P2 | 7 |
| FR-8.7 | Agent 评估体系：测试样例集与 Precision、Recall、False Positive Rate、Task Success Rate、Recovery Rate、Average Latency、Token Cost 等指标。 | P2 | 7 |

### 5.10 报告与交付（贯穿各阶段）

| 编号 | 需求 | 阶段 |
| --- | --- | --- |
| FR-9.1 | 最终产出 Markdown 与 JSON 两种报告，JSON 报告必须符合 `ReviewReport` Schema。阶段 1 仅生成三份基础 JSON，符合阶段 1 专用 Artifact Schema；完整 `ReviewReport` 自阶段 2 起生成。 | 1 起（基础 JSON）/ 2 起（ReviewReport） |
| FR-9.2 | 报告包含：综合评分与结论、各维度评分与 Finding 数量、重点风险（严重级别、文件、行号）、测试摘要、执行统计、成本统计。 | 2 起 |
| FR-9.3 | 部分完成时报告必须明确标注 `partial`，并说明缺失的维度与原因。 | 2 起 |
| FR-9.4 | 报告中的评分、问题与执行数据必须来自真实代码分析与模型调用；示意数据必须标注为示意。 | 全部 |

---

## 6. 非功能需求（NFR）

> 说明：性能类指标（如单次审查耗时目标）在阶段 1、2 完成基线测量后，写入 `acceptance.md`，本文档不预设未经测量的数值。

### 6.1 安全性

| 编号 | 需求 |
| --- | --- |
| NFR-S1 | 被审查仓库代码属于不可信输入：不在宿主机直接执行外部仓库的测试、安装或构建脚本。 |
| NFR-S2 | 外部仓库代码执行必须在 Docker 沙箱中进行，沙箱限制 CPU、内存、执行时间、网络访问与文件系统权限。 |
| NFR-S3 | 仓库内容（源码、README、Issue、PR 描述）作为数据处理，不得当作系统指令，防御 Prompt Injection。 |
| NFR-S4 | 工具与 Agent 最小权限：Security 只能读代码并执行安全扫描；Testing 只能在隔离环境运行测试；External Agent 只获得必要上下文；Final Reviewer 只读结果；GitHub 评论只能由受控发布模块执行。 工具权限必须在服务端强制执行，不能只依赖 Agent 侧的限制（Prompt Injection 或客户端 Bug 都可能绕过客户端）。 |
| NFR-S5 | 密钥、令牌不写入代码仓库、日志、任务合同与报告；`.env` 不入库，仅提供 `.env.example`。 |
| NFR-S6 | 任务输入中只允许工作区内的路径，不开放宿主机任意文件路径，防止路径穿越。 |
| NFR-S7 | 报告与日志中涉及密钥的证据必须脱敏。 |
| NFR-S8 | Webhook 必须校验 HMAC 签名，API 具备基础鉴权。 |

### 6.2 可靠性

| 编号 | 需求 |
| --- | --- |
| NFR-R1 | 单个 Agent 失败不得导致整体崩溃，系统应产出带 `partial` 标记的报告。 |
| NFR-R2 | 所有外部调用（模型、GitHub、工具、A2A）必须设置超时。 |
| NFR-R3 | 重试次数有上限，且仅对可重试错误重试。 |
| NFR-R4 | 任务重复执行（ARQ 在 Worker 中断后可能重复执行）不得产生重复结果，必须有幂等机制。 |
| NFR-R5 | 服务重启后任务状态不丢失、可查询（阶段 4 起）。 |
| NFR-R6 | 资源受限：全局、Agent、工具三级并发限制，防止超出模型限流或机器资源。 |

### 6.3 正确性与可信度

| 编号 | 需求 |
| --- | --- |
| NFR-C1 | 每个 Finding 必须可追溯到代码位置或工具证据；无证据的结论不进入最终报告。 |
| NFR-C2 | 行号必须对应固定的 Commit SHA。 |
| NFR-C3 | 测试结果与覆盖率只能来自真实工具输出；未执行时标记 `not_executed`，不得伪造。 |
| NFR-C4 | 评分与结论规则可配置、可解释；任意维度中已核验的 `critical` Finding（含外部 A2A Agent Finding）必须触发硬性阻断。 |

### 6.4 可维护性与可扩展性

| 编号 | 需求 |
| --- | --- |
| NFR-M1 | 模块化目录：`agents/`（角色与推理）、`graph/`（工作流编排）、`orchestration/`（任务生命周期、事件、重试、并发）分离；禁止把所有逻辑塞进 `manager.py`，禁止把 LangGraph 节点定义、模型调用与工具实现混在一个文件。 |
| NFR-M2 | 模型接入采用可切换的 Provider 抽象，第一版使用兼容 OpenAI API 的国内模型服务，后续可扩展多模型。 |
| NFR-M3 | 代码审查语言可扩展：数据合同中保留 `language` 字段，第一版仅实现 Python。 |
| NFR-M4 | 依赖分阶段引入，不提前安装后续阶段的依赖。 |
| NFR-M5 | 数据合同带版本号，变更遵循“向后兼容扩展、破坏性变更升级主版本”的流程。 |
| NFR-M6 | CLI 与 API 复用同一个 `ReviewService`。 |

### 6.5 可测试性

| 编号 | 需求 |
| --- | --- |
| NFR-T1 | 每个阶段交付必须有可运行的测试与验收记录。 |
| NFR-T2 | 数据合同、状态机、评分规则等纯逻辑必须有单元测试，且不依赖 LLM 与网络。 |
| NFR-T3 | LLM 与外部服务在单元测试中使用 Mock / Fake，端到端测试使用受控的测试仓库。 |
| NFR-T4 | 建立包含已知问题的测试样例仓库（SQL 注入、硬编码密钥、高复杂度函数、性能问题、覆盖率不足、失败测试）。 |

### 6.6 可观测性（阶段 7 前以日志为主）

| 编号 | 需求 |
| --- | --- |
| NFR-O1 | 使用 `structlog` 输出结构化日志，字段至少包含 `review_id`、`task_id`、`agent_name`、`event`、`status`。 |
| NFR-O2 | 阶段 7 起日志与 Trace 统一关联 `trace_id`，记录耗时、Token、重试次数。 |

### 6.7 成本与资源

| 编号 | 需求 |
| --- | --- |
| NFR-X1 | 模型调用成本必须可统计、可复盘（阶段 7）。 |
| NFR-X2 | 控制传入模型的上下文规模：只传任务所需文件与片段，避免把整个仓库和所有敏感上下文交给每个 Agent。 |

---

## 7. 项目技术约束

### 7.1 固定技术选型（不得擅自更改）

| 类别 | 固定技术选型 |
| --- | --- |
| 开发语言 | Python 3.12 |
| 环境管理 | Conda |
| 环境名称 | `multi-agent-review` |
| Web 框架 | FastAPI |
| 数据校验 | Pydantic |
| 配置管理 | pydantic-settings |
| 环境变量 | python-dotenv |
| 测试框架 | Pytest |
| HTTP 测试 | HTTPX |
| 日志 | structlog |
| 模型服务 | 国内兼容 OpenAI API 的模型服务，后续再扩展多模型 Provider |
| 代码管理 | Git + GitHub |

### 7.2 分阶段依赖策略

| 阶段 | 允许引入的依赖 |
| --- | --- |
| 0 | `fastapi`、`uvicorn`、`pydantic`、`pydantic-settings`、`python-dotenv`、`pytest`、`httpx`、`structlog` |
| 1 | 按实际模型 Provider 引入 LLM 接入包（如 `langchain-openai`）；Ruff、Bandit、Radon、Coverage.py 等分析工具；GitPython（或受控 Git CLI） |
| 2 | LangGraph |
| 3 | 基于 `asyncio` 与 LangGraph SubGraph，不新增基础设施依赖；按需引入 Gitleaks 等扫描工具 |
| 4 | Redis、ARQ、PostgreSQL、SQLAlchemy、LangGraph Checkpointer |
| 5 | MCP Python SDK |
| 6 | A2A Python SDK |
| 7 | OpenTelemetry、LangSmith、Streamlit |

**阶段 0 禁止提前安装或实现**：LangChain、LangGraph、Redis、ARQ、PostgreSQL、SQLAlchemy、MCP SDK、A2A SDK、OpenTelemetry（主动安装 `opentelemetry-sdk`、Exporter，或实际接入 Trace）、LangSmith、Streamlit。

> 例外说明：依赖解析可能经由 FastAPI 技术栈的强制传递依赖带入 `opentelemetry-api`，这属于被动依赖，允许存在；但不得在 `environment.yml` 中显式声明，也不得在项目代码中使用。

### 7.3 开发与部署环境

| 项目 | 约定 |
| --- | --- |
| 开发环境（阶段 0～3） | Windows 11 本地 + Conda 环境 + VS Code + Claude Code + Git |
| 阶段 4 | 引入 WSL2 Ubuntu + Docker Desktop，用 Docker Compose 管理 Redis 与 PostgreSQL；FastAPI 与 ARQ Worker 暂在本地运行 |
| 阶段 5～6 | 按 MCP / A2A 的实际服务需求逐步增加独立服务 |
| 阶段 7 | FastAPI、Worker、Redis、PostgreSQL、MCP Server、External A2A Agent、Dashboard、Sandbox Runner 完整 Docker Compose 部署 |
| 阶段 0～3 执行模式 | 单进程：CLI 与 FastAPI 通过同一个 `ReviewService` 执行，不引入 Redis 与 ARQ |

### 7.4 审查语言

第一版仅支持 **Python**，后续再扩展 JavaScript、TypeScript 等语言。

### 7.5 开发节奏

每个阶段统一采用：**架构设计 → 编写开发任务 → 交给 Claude Code 实现 → 运行测试 → 检查实际代码 → 修复问题 → 阶段验收 → 更新项目文档。**

---

## 8. 八个阶段（阶段 0～7）的功能范围

项目共八个阶段（阶段 0～7）：阶段 0 为工程初始化与需求冻结，阶段 1～7 为渐进式架构演进路线。

| 阶段 | 名称 | 范围（做什么） | 明确不做 |
| --- | --- | --- | --- |
| 0 | 工程初始化与需求冻结 | 工程骨架、Conda 环境、配置、五份核心文档、数据合同 Schema 与单元测试 | 任何 Agent、LLM 调用、GitHub 获取、分析工具、LangGraph、Redis 等 |
| 1 | 单 Agent 工程基础 | GitHub 仓库获取与安全校验、固定 Commit、文件解析与过滤、Ruff/Bandit/Radon、对可信仓库的 Pytest/Coverage、`ReviewService`、CLI + 最小同步 FastAPI（阶段 1 必做）、基础 Markdown/JSON 报告 | 多 Agent、LangGraph、异步队列、对外部仓库执行测试 |
| 2 | LangGraph Supervisor-Worker | `ReviewState`、Manager、四个专业 Agent、并行 Fan-out/Fan-in、Agent 异常捕获与 `partial` 报告、Final Reviewer（汇总节点，不创建 `AgentTask`；Evidence Validator、去重、评分、阻断规则）、报告 | SubAgent、Agent 重试与退避、任务持久化与恢复、Redis/ARQ、MCP、A2A |
| 3 | SubAgent 分层编排 | Security Agent 的三个子任务、父子任务关系、进程内 `TaskEvent`、并发限制、父任务汇总规则 | 重试与退避（阶段 4）、跨进程事件、持久化、其他 Agent 的 SubAgent（可选） |
| 4 | 异步任务与失败恢复 | Redis + ARQ、状态机、重试/超时/退避、幂等、三层并发控制、PostgreSQL 持久化、Checkpointer、Redis Streams 事件、Webhook 接收基础设施（HMAC 校验、`delivery_id` 幂等）、Docker Compose 管理基础设施 | MCP、A2A、完整 Compose 部署 |
| 5 | MCP 工具接入 | Code Analysis MCP Server、MCP Client、工具权限隔离、受限容器执行测试 | A2A、可观测性平台 |
| 6 | A2A 跨服务协作 | External Architecture Review Agent、Agent Card、A2A 任务与 Artifact、`external_review_node`、失败降级 | 完整可观测性、Dashboard |
| 7 | 可观测性与产品化 | Trace、Token 成本、结构化日志、GitHub PR 集成（PR 触发、评论回写与评论发布幂等）、Streamlit Dashboard、完整 Docker Compose、评估体系 | 新的审查维度、新语言 |

里程碑对应：

| 里程碑 | 阶段 | 建议投入（规划估算，实际取决于模型接口、环境和调试） | 主要成果 |
| --- | --- | --- | --- |
| M1 | 0～1 | 3～4 天 | 单 Agent 代码审查 |
| M2 | 2～3 | 4～6 天 | 多 Agent + SubAgent |
| M3 | 4～6 | 5～7 天 | 异步任务 + MCP + A2A |
| M4 | 7 | 2～4 天 | 可观测性 + 产品化 |

---

## 9. MVP 与后续扩展范围

### 9.1 MVP（P0，阶段 0～2）

**目标**：输入一个受控的 Python 测试仓库，系统能够获取代码、并行分析不同维度的问题，并生成结构化审查报告。

MVP 包含：

- 工程骨架、五份核心文档、统一数据合同；
- GitHub 仓库获取（带安全限制）、固定 Commit SHA、源码解析；
- Ruff、Bandit、Radon 静态分析，对可信仓库执行 Pytest + Coverage.py；
- Manager、四个专业 Agent 的 Supervisor-Worker 并行编排；
- Final Reviewer：证据核验、去重、评分、`critical` 阻断；
- Markdown + JSON 报告，Finding 全部带可追溯证据。

### 9.2 增强版（P1，阶段 3～6）

SubAgent 与父子任务管理、Announce 事件、并发控制、超时与重试、Redis + ARQ、PostgreSQL 与 Checkpointer、MCP 工具与权限控制、A2A 外部 Agent。

### 9.3 产品化版（P2，阶段 7）

OpenTelemetry Trace、LangSmith 调试、Token 成本统计、GitHub PR Webhook 与评论、Streamlit Dashboard、Docker Compose 完整部署、Agent Benchmark 与效果对比报告。

### 9.4 后续扩展（本规划之外的备选方向）

- 支持 JavaScript、TypeScript 等更多语言；
- 多模型 Provider 灵活切换与对比；
- 更多外部 A2A Agent；
- 私有仓库与细粒度权限（需先完成密钥管理与权限模型设计）。

---

## 10. 明确的非目标（Out of Scope）

### 10.1 阶段 0 的非目标

阶段 0 **不是**开发一个能够工作的 Agent 系统，而是为后续阶段建立可靠的工程基础。因此阶段 0 不包含：

- 任何 Agent 的实现、Prompt、LLM 调用；
- GitHub 仓库获取、文件解析、静态分析工具接入；
- LangGraph、LangChain、Redis、ARQ、PostgreSQL、SQLAlchemy、MCP SDK、A2A SDK、OpenTelemetry（SDK、Exporter 与 Trace 接入；被动传递依赖 `opentelemetry-api` 除外）、LangSmith、Streamlit 的安装与使用；
- Docker 与 Docker Compose；
- 创建 `agents/`、`graph/`、`services/`、`tools/`、`mcp/`、`a2a/`、`orchestration/`、`workers/`、`observability/`、`storage/`、`reporting/`、`external_agents/` 等后续阶段的目录。

### 10.2 项目级非目标

| 编号 | 非目标 | 说明 |
| --- | --- | --- |
| OOS-1 | 自动修复代码、自动提交或推送代码 | 系统只读，只给出建议；Final Reviewer 不获得仓库写权限。 |
| OOS-2 | 在宿主机上执行外部不可信仓库的测试、安装或构建脚本 | 必须在隔离沙箱中执行，沙箱建立前标记 `not_executed`。 |
| OOS-3 | Python 以外的语言审查（第一版） | 后续阶段之外再扩展。 |
| OOS-4 | 用户账号体系、多租户、计费系统 | 仅提供基础鉴权与 Webhook 签名校验。 |
| OOS-5 | 私有仓库访问与企业级权限管理（第一版） | 第一版面向公开仓库或本地受控测试仓库。 |
| OOS-6 | 模型训练、微调 | 仅调用现有模型服务。 |
| OOS-7 | 生产级大规模分布式部署（Kubernetes、自动扩缩容） | 目标是 Docker Compose 级别的可演示部署。 |
| OOS-8 | 取代人工审查的最终决策 | 系统输出为辅助审查意见与合并建议，最终合并决定权在人。 |
| OOS-9 | 在单元测试中调用真实 LLM 或访问外部网络 | 单元测试必须稳定、可重复。 |
| OOS-10 | 一次性提前接入所有高级技术 | 违反“渐进式演进”原则。 |

---

## 11. 假设、风险与待确认事项

### 11.1 假设

| 编号 | 假设 |
| --- | --- |
| A1 | 阶段 1～3 的审查对象是公开 GitHub 仓库或自己编写的可信测试仓库。 |
| A2 | 国内兼容 OpenAI API 的模型服务可稳定提供 JSON / 结构化输出能力，且返回 `usage` 信息。 |
| A3 | 开发机为 Windows 11，阶段 4 起可使用 WSL2 与 Docker Desktop。 |

### 11.2 主要风险

| 编号 | 风险 | 缓解措施 |
| --- | --- | --- |
| R1 | LLM 产生无证据或误报的结论 | 合同强制证据；Evidence Validator；评估体系度量误报率。 |
| R2 | 并行节点写共享状态冲突（`InvalidUpdateError`） | 节点只返回自己负责的字段；列表使用 Reducer。 |
| R3 | ARQ 任务重复执行产生重复结果 | 幂等键、数据库唯一约束、状态校验。 |
| R4 | 不可信仓库代码带来宿主机风险 | 默认不执行；沙箱隔离；`not_executed`。 |
| R5 | Prompt Injection | 仓库内容视为数据；Agent 权限最小化；工具参数校验。 |
| R6 | 模型限流与成本不可控 | 退避重试、并发限制、上下文裁剪、Token 统计。 |
| R7 | 过早引入多项技术导致问题难以定位 | 严格分阶段，验收通过后再前进。 |
| R8 | 评分权重缺乏依据 | 设计为可配置规则，并通过测试样例集迭代校准。 |

### 11.3 已确认事项（建议在阶段 1 开始前确认）

| 编号 | 事项 | 默认值 |
| --- | --- | --- |
| D1 | Final Reviewer 的“证据核验、去重、评分”是纯确定性代码，还是确定性 + LLM 混合？ | 核验与评分用确定性代码；LLM 仅用于生成摘要与解释。 |
| D2 | 仓库大小、文件数量、单文件大小、下载超时的具体阈值。 | 阶段 1 在 `config/settings.py` 中定义，并在 `acceptance.md` 记录。 |
| D3 | 模型 Provider 的具体选择与 `.env` 变量命名。 | 阶段 1 确定；阶段 0 的 `.env.example` 只放占位符。 |
| D4 | 是否在阶段 1 支持私有仓库。 | 不支持。 |

---

## 12. 术语表

| 术语 | 含义 |
| --- | --- |
| Agent | 具有明确职责、输入输出与工具权限的执行单元。 |
| SubAgent | 专业 Agent 内部的二级执行单元，可以是确定性工具 Worker。 |
| Task Plan | Manager 生成的审查任务计划。 |
| Finding | 一条带证据的具体审查发现。 |
| Evidence Validator | 校验文件、行号、证据片段与工具佐证的核验节点（Final Reviewer 的一部分）。 |
| Fan-out / Fan-in | 并行分发任务 / 汇合并行结果。 |
| Announce | 子任务完成或失败的事件通知机制，不替代工作流控制。 |
| Checkpointer | LangGraph 的工作流状态保存与断点恢复机制。 |
| MCP | Model Context Protocol，标准化工具接入协议。 |
| A2A | Agent2Agent，跨服务 Agent 通信协议。 |
| 幂等 | 同一请求重复执行不会产生重复的副作用或结果。 |

---

## 修订记录

| 项目 | 内容 |
| --- | --- |
| 修订日期 | 2026-11-09 |
| 修订类型 | v1.0 冻结前跨文档一致性修订（D-1、D-2、D-3） |
| 修订内容 | ① 明确所有维度无有效评分时，结论在不存在已核验 `critical` Finding 时为 `COMMENT`，存在时为 `REQUEST_CHANGES`（与 RP-16 一致）；② 将硬性阻断范围统一为任意维度已核验 `critical` Finding（含外部 A2A Agent Finding），不再限定为“critical 安全漏洞”（与 RP-06、EX-4 一致）；③ 明确四个维度配置权重始终保持原始配置值，仅在综合分计算公式内部对有效维度权重归一化（与 RP-11、RP-16 一致）。 |
| 修订日期 | 2026-11-10 |
| 修订类型 | v1.1 阶段 1 实施基线修订 |
| 修订内容 | ① FR-9.1 明确阶段 1 只生成三份基础 JSON（阶段 1 Artifact Schema），完整 `ReviewReport` 自阶段 2 起生成；② §8 阶段 1 范围明确 FastAPI 为最小同步入口（阶段 1 必做）；③ 依据 `实施决策.md` Q2、Q3 裁定，不改变阶段 0 需求与 AC 编号。 |
| 影响 | AC-1-14、AC-1-15；Stage 1.6；不改变阶段 2 起的 ReviewReport 合同。 |
| 数据合同权威顺序 | `task_contracts.md` 是数据合同唯一权威；本文档不得与其冲突。 |
| 阶段归属 | 任务树深度、父子存在性与环检测属于阶段 3 编排层；失败重试、持久化与调度属于阶段 4。 |
| 架构影响 | 未改变整体系统架构、阶段划分与核心业务方向。 |
