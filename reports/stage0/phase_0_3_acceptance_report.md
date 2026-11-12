# 阶段 0.3 验收报告

> 验收日期：2026-11-09
> 项目：Multi-Agent Code Review System
> 阶段：阶段 0.3 — 五份核心文档最终冻结、Pydantic Schema 重建与单元测试同步
> 依据：`0.3阶段任务要求.md`、`docs/task_contracts.md`（v1.0，`schema_version = "1.0"`）
> 执行环境：Windows 11 Pro 10.0.26100；Conda 环境 `multi-agent-review`；Python 3.12.16；Pydantic 2.14.3；pytest 9.2.0
> 代码版本：无 Git commit（工作区文件均未跟踪；本阶段禁止 commit / push / tag）
> 最终结论：**BLOCKED（Schema 与测试交付完成；文档冻结因跨文档冲突暂停，等待用户确认）**

---

## 0. 结论摘要

| 项目 | 结果 |
| --- | --- |
| 五份核心文档冻结 | **BLOCKED**：发现直接跨文档冲突，按 `0.3阶段任务要求.md` §3.2(4) 暂停冻结，未保留冻结标注 |
| `task.py` / `result.py` / `report.py` 重建 | 完成（以最新 `task_contracts.md` 为唯一数据合同依据） |
| 单元测试 | **203 passed**，0 failure / 0 error / 0 skip / 0 xfail |
| 规则编号追溯 | 输出恰好为 `['FD-09', 'FD-10', 'ST-04', 'ST-05', 'ST-06', 'ST-07']` |
| 文档 JSON 示例 | 15 个代码块全部可解析；13 个合法模型示例全部通过；1 个非法示例按预期被拒；2 个非模型片段仅做解析 |
| 阶段 0 边界 | 未发现越界目录或后续阶段依赖；AC-0-05 按修订后的四分项判定通过 |
| 阶段 0 正式验收 | **BLOCKED**：文档尚未冻结；Git commit / push / tag 未执行且本阶段被禁止 |

说明：本报告不把“测试全部通过”等同于“阶段 0.3 通过”。Schema 与测试层已经形成闭环，但五份文档仍存在需要用户裁定的直接冲突，因此不能判定 PASS，也不能擅自冻结。

---

## 1. 五份核心文档冻结状态

### 1.1 当前状态

| 文档 | 路径 | 版本 | 当前状态 | 冻结结果 |
| --- | --- | --- | --- | --- |
| 需求文档 | `docs/requirements.md` | v1.0 | 待评审，评审通过后冻结 | **未冻结（BLOCKED）** |
| 架构文档 | `docs/architecture.md` | v1.0 | 待评审，评审通过后冻结 | **未冻结（BLOCKED）** |
| 工作流文档 | `docs/workflow.md` | v1.0 | 待评审，评审通过后冻结 | **未冻结（BLOCKED）** |
| 任务数据合同 | `docs/task_contracts.md` | v1.0（合同版本 `schema_version = "1.0"`） | 待评审，评审通过后冻结 | **未冻结（BLOCKED）** |
| 验收文档 | `docs/acceptance.md` | v1.0 | 待评审，评审通过后冻结 | **未冻结（BLOCKED）** |

五份文档均未建立修订历史章节，头部只有“文档版本 / 当前阶段 / 状态 / 关联文档”等字段。

### 1.2 为什么暂停冻结

`0.3阶段任务要求.md` §3.2(4) 规定：“如果发现实际存在的重大冲突，不得擅自冻结，应单独报告并等待确认。”本次交叉核对发现以下直接冲突，均影响“五份文档作为统一基线”的语义，但不影响已实现的 Schema 代码：

| 编号 | 冲突 | 文档位置 | 影响 |
| --- | --- | --- | --- |
| D-1 | 全维度无评分时的结论：需求文档写“结论为 COMMENT”，合同 RP-16 写“COMMENT，唯一例外是存在已核验 critical 时为 REQUEST_CHANGES” | `requirements.md:242` vs `task_contracts.md:922` | 业务结论口径不一致；Schema 按合同实现 |
| D-2 | 硬性阻断范围：需求文档写“critical 安全漏洞”，合同 RP-06 写“任意维度的已核验 critical Finding”，EX-4 还覆盖外部 Agent Finding | `requirements.md:170`、`requirements.md:239` vs `task_contracts.md:912`、`task_contracts.md:1322` | 阻断范围口径不一致；Schema 按合同实现 |
| D-3 | 权重重新归一化：需求文档写“剩余维度的权重重新归一化”，合同 RP-11 规定报告中的 `weight` 始终是配置权重、不随缺失维度改变，只有综合分计算公式内部重新归一化 | `requirements.md:170` vs `task_contracts.md:917`、`task_contracts.md:922` | 存储权重与计算权重语义易混淆；Schema 按合同实现 |
| D-4 | 最大任务深度与“子任务不得再创建子任务”：任务要求把它列为 `task.py` 必须实现并测试的 Schema 约束，但合同没有 `task_depth` / `depth` 字段，TK-11 又禁止额外字段；深度是任务树属性 | `0.3阶段任务要求.md` §4.1 / §5.2 vs `task_contracts.md:63`、`task_contracts.md:100`、`task_contracts.md:123`、`task_contracts.md:218` | 单模型 Pydantic 无法在不新增字段的前提下校验；本次未发明字段 |
| D-5 | ST-05 归属：合同 ST-05 要求阶段 0 提供状态迁移纯函数并配套单元测试；验收文档 §3.4.3 的期望输出又把 ST-05 列为“阶段 0 测试中不存在”的编号 | `task_contracts.md:562` vs `acceptance.md:253` | 功能已实现并测试，但测试名不写 ST-05，以保持追溯输出符合验收口径 |
| D-6 | AC-0-24 的“后五项明确标注为设计”：`workflow.md` §3 标注为“阶段 2 实现”，并用 §3.0 区分阶段 2 实现与阶段 4 设计预留，并非字面上的“设计” | `acceptance.md:188` vs `workflow.md:263`、`workflow.md:265-280` | 验收措辞与文档实际标注不一致 |
| D-7 | AC-0-29 的“每个完整示例通过 model_validate”：合同 §5.6 明确包含一个“非法示例（必须被拒绝）”；合同 §14 又写“§5.6、§8.3 示例通过校验” | `acceptance.md:193`、`task_contracts.md:1436` vs `task_contracts.md:502-522` | 合法示例与非法示例的判定口径不严谨；测试按“合法示例通过、非法示例预期失败”执行 |
| D-8 | `workflow.md:23` 写“阶段 0 不要求任何代码”，但阶段 0 的交付物明确包含 `src/code_review/schemas/` 与测试 | `workflow.md:23` vs `acceptance.md:169-179`、`task_contracts.md:7-8` | 阶段 0 范围表述自相矛盾；不影响现有 Schema 实现 |
| D-9 | 任务要求中的 `Evidence` 模型、有效权重总和为零必须拒绝：合同没有 `Evidence` 类（只有 `Finding.evidence: str` 与 `ToolEvidence`），且 RP-16 规定全维度 null 是合法报告 | `0.3阶段任务要求.md` §4.1 / §5.4 vs `task_contracts.md:351`、`task_contracts.md:358-365`、`task_contracts.md:922` | 本次按“合同为唯一依据、不得自行增加业务规则”处理，未发明 `Evidence` 类，未把全 null 报告判为非法 |

处理方式：

1. 本次曾按任务 0.2 在五份文档头部写入 `已冻结（Frozen）`、最后更新、适用范围、冻结依据与修订记录；发现上述冲突后，已按 `0.3阶段任务要求.md` §3.2(4) 与 §十 的要求**回退**这些标注，文档头部恢复为“待评审，评审通过后冻结”。
2. 未修改任何已审核的业务需求、架构设计或合同规则；未删除、重写规格文档。
3. 以下冲突需要用户确认后再冻结：D-1～D-9。建议的裁定原则见第 10.4 节。

---

## 2. Schema 修改前后差异

### 2.1 差异基线说明

仓库没有任何 Git commit，无法从版本库取得旧代码 diff。本节的“修改前”基线来自上一轮验收报告 `reports/phase_0_acceptance_report.md` §6 记录的旧实现摘要、“修改后”为当前工作区文件。旧版测试总数为 138（`test_task_schema.py` 58、`test_result_schema.py` 51、`test_report_schema.py` 29）。

### 2.2 任务 0.1 差异清单（简短版）

| 文件 | 修改前（旧验收报告基线） | 修改后（当前） | 差异性质 |
| --- | --- | --- | --- |
| `schemas/task.py` | TK-01～TK-12；`finished_at` 只校验不早于 `created_at` | 增加 TK-13 状态与时间戳一致性；`finished_at` 同时校验不早于 `started_at`；保留 `is_transition_allowed` / `can_transition_to` | 新增校验 |
| `schemas/result.py` | `ToolEvidence`、`Finding`（15 字段）、`AgentResult`（13 字段），FD-01～FD-08、RS-01～RS-09 | 按最新合同逐条复核并重建；字段集合保持一致；强化 `ToolEvidence` 非空、`end_line` 依赖、文本长度、`verification_status` 枚举、可选字段 null 序列化等边界 | 重建 + 测试补强 |
| `schemas/report.py` | `ReviewReport` 21 字段；`overall_score` 必填且非空；`DimensionScore` 无 `reason`；`weight` 允许 0～1；无 `external_agent_results` | `ReviewReport` 22 字段，新增 `external_agent_results`；`overall_score` 必填但可为 `null`；`DimensionScore` 新增 `reason`；`weight` 收紧为 `(0, 1]`；补齐 RP-04、RP-11、RP-15、RP-16、RP-17、RP-19、RP-20 | 新增字段 + 新增一致性规则 |
| `tests/unit/` | 3 个文件、138 条用例 | 3 个文件、203 条用例；按最新合同重建并补充正反向测试 | 测试同步 |
| 规则追溯 | 旧文档规则缺 `FD-09`、`FD-10`、`ST-04`、`ST-05` | 最新文档新增 `ST-06`、`ST-07`；当前输出恰好为 6 个排除项 | 文档规则增加 |

### 2.3 逐文件差异

**`task.py`**

- 新增 `AgentTask._check_status_timestamps()`，实现 TK-13：
  - `pending`：`finished_at` 必须为 `null`；
  - `running`：`started_at` 必须非空、`finished_at` 必须为 `null`；
  - `completed` / `cancelled`：`finished_at` 必须非空；
  - `failed`：若 `last_error.retryable = true` 且 `retry_count < max_retries`，`finished_at` 必须为 `null`；否则必须非空。
- TK-10 由“`finished_at >= created_at`”扩展为“`finished_at >= created_at` 且 `finished_at >= started_at`”。
- 其余字段、默认值、状态迁移函数保持不变。

**`result.py`**

- 字段集合与旧版一致：`ToolEvidence`（4 字段）、`Finding`（15 字段）、`AgentResult`（13 字段）。
- 按最新合同保留并复核：FD-01～FD-08、RS-01～RS-09。
- 新增测试覆盖：可选字段序列化为 `null` 不省略（JS-05）、所有字段名为 snake_case（JS-02）、`end_line` 缺少 `start_line` 被拒、`verification_status` 非法值被拒、`ToolEvidence` 非空、默认列表不共享。
- 未实现 FD-09、FD-10：合同明确 FD-09 在编排层检查，FD-10 属脱敏处理，均不属于 Schema 层。

**`report.py`**

- 新增 `external_agent_results: dict[str, AgentResult]`（默认空字典）。
- `overall_score` 由“必填非空 float”改为“必填 `float | null`”，并实现 RP-16 的三种语义。
- `DimensionScore` 新增 `reason: str | null`；`weight` 由 `ge=0, le=1` 收紧为 `gt=0, le=1`。
- 补齐以下一致性校验：
  - RP-04：`completed` 当且仅当四维评分非空且所有核心/外部结果均为 `completed`；
  - RP-05、RP-06、RP-07、RP-08、RP-14；
  - RP-11：四维权重均 `> 0` 且总和为 1（容差 `1e-6`）；
  - RP-15：`dimension_scores` 与 `agent_results` 必须且只能包含四个核心键；
  - RP-16：全 null、部分 null、全部非 null 的综合分语义与部分维度权重重归一化；
  - RP-17：`ExecutionSummary` 与核心/外部结果集合逐项一致；
  - RP-18：`score = null` 必须有 `reason`，`failed` 维度不得有评分；
  - RP-19：维度状态必须等于对应 Agent 结果状态；
  - RP-20：外部结果键非空、不得复用核心键、值必须是合法 `AgentResult`、不得进入 `dimension_scores`。

---

## 3. 新增、修改的 Schema 字段和校验规则

### 3.1 `schemas/task.py`

| 模型 | 字段/规则 | 实现 |
| --- | --- | --- |
| `ErrorInfo` | `error_type`、`message` 非空；`retryable` 必填；`occurred_at` UTC；`details` 默认空字典 | 与合同 §7.1 一致 |
| `AgentTask` | 19 个字段：`schema_version`、`task_id`（uuid4）、`parent_task_id`、`review_id`、`agent_name`、`task_type`、`description`（≤4000）、`input_data`、`expected_output`、`priority`、`required`、`status`、`retry_count`、`max_retries`、`timeout_seconds`、`created_at`、`started_at`、`finished_at`、`last_error` | 与合同 §4.1 一致 |
| 校验 | TK-01～TK-13；`extra="forbid"`；JSON 往返一致 | 全部实现 |
| 状态迁移 | `is_transition_allowed()` / `can_transition_to()` 实现 ST-01～ST-03；ST-05 的纯函数要求由同一函数满足 | 运行时持久化不在 Schema 层 |

### 3.2 `schemas/result.py`

| 模型 | 字段/规则 | 实现 |
| --- | --- | --- |
| `ToolEvidence` | `tool_name`、`raw_output_ref` 非空；`rule_id`、`tool_version` 可空但提供时非空 | 与合同 §5.2 一致 |
| `Finding` | 15 个字段；`severity` 五级；`title ≤ 200`、`description ≤ 4000`、`evidence ≤ 4000`；`file_path` POSIX 相对路径；`start_line/end_line ≥ 1`；`confidence ∈ [0,1]`；`verification_status ∈ {unverified, verified, rejected}` | 与合同 §5.1 一致 |
| `Finding` 校验 | FD-01～FD-08；A 类代码位置证据或 B 类工具证据至少一类；`critical/high` 必须有代码位置；`file_path` 与 `start_line` 同时提供/缺省；`end_line ≥ start_line`；路径禁止 `/` 开头、`..`、反斜杠、盘符；`extra="forbid"` | 全部实现 |
| `AgentResult` | 13 个字段；`status ∈ {completed, failed, partial}`；`commit_sha` 40 位小写十六进制；`score` 0～100 或 null；`execution_time ≥ 0`；`findings` 默认空列表；`error` 可空；`metadata` 默认空字典 | 与合同 §8.1 一致 |
| `AgentResult` 校验 | RS-01～RS-09；`completed` 不得有 `error`；`failed` 必须有 `error` 且 `score=null`、`findings=[]`；`partial` 必须有 `error`；`finding_id` 唯一；Finding 的 `agent_name` 与结果一致；`extra="forbid"` | 全部实现 |

### 3.3 `schemas/report.py`

| 模型 | 字段/规则 | 实现 |
| --- | --- | --- |
| `DimensionScore` | `score`（0～100 或 null）、`weight`（`0 < w ≤ 1`）、`finding_count ≥ 0`、`status`、`reason` | RP-18：`score=null` 必须有 `reason`；`failed` 不得有评分 |
| `TestSummary` | `execution_status ∈ {executed, not_executed, failed}`；`passed/failed/skipped/coverage` 可空；`source`、`reason` | RP-09：`not_executed` 时四个测试数字全为 null 且 `reason` 非空；`failed` 时 `reason` 非空；RP-10：`coverage` 非空时必须有 `source` 且在 0～100 |
| `ExecutionSummary` | `total_tasks`、`completed_tasks`、`partial_tasks`、`failed_tasks`、`cancelled_tasks`、`duration_seconds` | RP-03：四项计数之和等于 `total_tasks`，各项 ≥ 0 |
| `CostSummary` | Token、成本、币种（`CNY` / `USD`） | 默认 0 / 0 / 0 / CNY |
| `ReviewReport` | 22 个字段，新增 `external_agent_results`；`overall_score` 必填可空 | RP-01～RP-20 全部实现 |

### 3.4 明确未在 Schema 层实现的规则

| 规则/要求 | 不实现原因 |
| --- | --- |
| 最大任务深度 2、子任务不得再创建子任务、父任务必须存在、任务树不得有环 | 合同没有 `task_depth`/`depth` 字段，TK-11 禁止额外字段；这些是任务树/编排层属性，需由阶段 3 的 Manager/任务树校验，或先修订合同增加字段后再进 Schema |
| FD-09（专业 Agent 的 Finding 不得为 verified） | 合同明确该规则在编排层检查，Schema 不强制 |
| FD-10（敏感值脱敏） | 属扫描/日志/报告脱敏流程，不是数据结构约束 |
| ST-04、ST-06、ST-07 | 状态迁移的运行时行为（更新 `started_at`、写入最终 `finished_at`、重试迁移计数），由阶段 3～4 执行层实现；Schema 只做 TK-13 的静态一致性校验 |
| RT-04、RT-06 | 失败历史持久化与幂等键由阶段 4 存储层实现 |
| TT-1～TT-5 | 任务树拓扑与 Final Reviewer 的编排约束；TT-3 的“只统计深度 1 任务”由 RP-17 的 `total_tasks = 4 个核心 + 外部结果` 间接体现 |
| EX-3 的 `ARC-` 前缀与 `ExternalArchitectureReviewAgent` 命名 | 合同把 `agent_name` 保持为 `str`，命名是注册表/编排约定，不是 Schema 枚举 |
| JS-12（敏感信息不得出现在合同对象/日志/报告） | 属脱敏与日志治理，不是 Schema 可判定的结构约束 |
| `Evidence` 模型 | 合同没有该模型；只有 `Finding.evidence: str` 与 `ToolEvidence`，不发明未经文档定义的模型 |
| “有效权重总和为零时拒绝” | 合同 RP-16 规定全维度 null 是合法报告（`overall_score = null`、`partial`、`COMMENT`）；拒绝的是 RP-11 的非法配置权重（`weight = 0`、总和不为 1），不是全 null 报告 |

### 3.5 关键实现说明

- `ExecutionSummary` 放在 `report.py`：`0.3阶段任务要求.md` 在 `result.py` 段落提到它，但合同 §9.2 把它定义为 `ReviewReport` 子模型；按“最新合同为唯一依据”，本次只定义一次，位于 `report.py`。
- `AgentResult.status` 没有 `cancelled`：取消映射为 `status = failed` + `error.error_type = "cancelled"`；RP-17 的 `cancelled_tasks` 按该组合计数。
- `agent_name` / `task_type` 保持 `str`，未改为 `Literal`；合法值由注册表约束。
- `schema_version` 保持 `str = "1.0"`，未改为严格 `Literal`，以支持合同 §11 的向后兼容次版本升级。
- `TestSummary` 类名以 `Test` 开头，已设置 `__test__: ClassVar[bool] = False`，避免 pytest 误收集。

---

## 4. 单元测试数量与覆盖范围

### 4.1 数量

| 测试文件 | 用例数（collect） | `def test_` 函数数 | 参数化装饰器数 |
| --- | --- | --- | --- |
| `tests/unit/test_task_schema.py` | 73 | 27 | 11 |
| `tests/unit/test_result_schema.py` | 59 | 36 | 11 |
| `tests/unit/test_report_schema.py` | 71 | 62 | 4 |
| **合计** | **203** | **125** | **26** |

### 4.2 覆盖范围

| 规则族 | 覆盖情况 |
| --- | --- |
| TK-01～TK-13 | 13/13；含默认值、ID 唯一、非法状态/优先级、重试与超时边界、空字段、失败必带错误、UTC、额外字段、JSON 往返、TK-13 状态/时间戳正反向矩阵 |
| ST-01～ST-03 | 状态迁移矩阵、失败重试配额、`can_transition_to` 使用 `last_error`；ST-05 纯函数由同一测试覆盖 |
| FD-01～FD-08 | 8/8；A/B 类证据、无证据拒绝、critical/high 必须有代码位置、路径/行号/置信度/空白/严重级别边界 |
| RS-01～RS-10 | 10/10；三种结果状态、错误/评分/Finding 约束、重复 ID、Agent 名称一致、commit_sha、默认列表、JSON 往返 |
| RP-01～RP-20 | 20/20；含 §9.4 完整报告、§9.5 全 null 报告、RP-04 双向 iff、RP-11 权重和、RP-15 键集合、RP-16 三种 null 语义与重归一化、RP-17 计数、RP-19 状态一致、RP-20 外部结果 |
| JS-02/03/05/06/07/08/09/10/11 | 字段 snake_case、UTC、可选字段 null 不省略、序列化/反序列化、`extra="forbid"`、POSIX 路径、`default_factory`、JSON 无损、文本长度 |
| 文档示例 | 3 个 AgentTask、3 个合法 Finding、3 个 AgentResult、2 个 ReviewReport、1 个 TestSummary；1 个非法 Finding 按预期失败 |

### 4.3 明确不在 Schema 测试范围

- FD-09、FD-10（编排层核验、脱敏）；
- ST-04、ST-06、ST-07（运行时状态写入与重试迁移）；
- RT-04、RT-06（持久化、幂等）；
- TT-1～TT-5（任务树拓扑、Final Reviewer 编排）；
- JS-12（敏感信息治理）；
- 任何 Agent、LLM、网络、LangGraph、MCP、A2A、Redis、ARQ 行为。

---

## 5. 原有测试保留情况

| 项目 | 结果 |
| --- | --- |
| 旧测试总数 | 138（58 / 51 / 29） |
| 新测试总数 | 203（73 / 59 / 71） |
| 旧规则覆盖 | TK、ST、FD、RS、RP 的既有规则编号全部仍出现在测试文件中；追溯输出没有新增缺失编号 |
| 删除有效测试 | 未发现；旧用例的规则意图均保留，部分因合同新增约束而调整断言或合并 |
| 必须调整的旧假设 | 旧版“partial 报告 `overall_score = 80.0`”“completed 报告允许维度评分为 null”等与最新 RP-04/RP-16 冲突，已改为合同要求的 `partial` + 重归一化分数或 `null` |
| 新增回归测试 | 覆盖 TK-13、RP-04 双向 iff、RP-11 权重和、RP-15 精确键集合、RP-16 null 语义、RP-17 计数、RP-18 reason、RP-19 状态一致、RP-20 外部结果、JS-02/JS-05 |

结论：原有 138 条测试所覆盖的规则没有被删除或放宽；测试数量增加来自最新合同新增/细化的规则与边界用例。

---

## 6. 完整测试执行结果

### 6.1 静态编译

```text
python -m compileall src/code_review
```

结果：退出码 0，`compileall OK`。

### 6.2 单元测试

```text
pytest tests/unit -v
```

结果：

```text
203 passed in 0.69s
```

- failure：0
- error：0
- skip：0
- xfail：0
- 测试未联网、未调用真实 LLM、未启动外部服务。

### 6.3 完整测试

```text
pytest -v
```

结果：

```text
203 passed in 0.48s
```

项目中只有 `tests/unit/`，无其他测试目录。

### 6.4 规则编号追溯

```text
python -c "import re,pathlib; ids=set(re.findall(r'\b(?:TK|ST|FD|RS|RP)-\d{2}\b', pathlib.Path('docs/task_contracts.md').read_text(encoding='utf-8'))); t=''.join(p.read_text(encoding='utf-8') for p in pathlib.Path('tests/unit').glob('test_*.py')); print(sorted(i for i in ids if i not in t))"
```

实际输出：

```text
['FD-09', 'FD-10', 'ST-04', 'ST-05', 'ST-06', 'ST-07']
```

与 `docs/acceptance.md` §3.4.3 的期望完全一致（这六条均为非 Schema 层或按验收口径不进阶段 0 测试的规则）。

### 6.5 阶段 0 边界与依赖探测

目录检查：

```text
src/code_review 下仅有 schemas/（另有 Python 自动生成的 __pycache__/，已被 .gitignore 忽略）
ABSENT agents
ABSENT graph
ABSENT tools
ABSENT mcp
ABSENT a2a
ABSENT orchestration
ABSENT workers
ABSENT observability
ABSENT storage
ABSENT reporting
ABSENT external_agents
```

依赖探测（按修订后的 AC-0-05 四分项）：

```text
FORBIDDEN: []
PASSIVE-ALLOWED: ['opentelemetry-api']
OTEL-IN-CODE: []
OTEL-IN-ENV: False
opentelemetry-api 1.45.2  Required-by: fastapi
```

结论：AC-0-05 (a)(b)(c)(d) 均通过；`opentelemetry-api` 是 FastAPI 的被动传递依赖，代码与 `environment.yml` 均未接入 OpenTelemetry。

导入检查：`src/code_review/` 仅导入标准库与 Pydantic；依赖方向为 `task.py ← result.py ← report.py`。

### 6.6 Ruff

项目未配置 Ruff，环境也未安装 Ruff；按任务要求“如果项目已经配置 Ruff”才执行，故本次不运行，也不新增依赖。

---

## 7. 合同规则追溯表

说明：
- “文档位置”均指 `docs/task_contracts.md` 的 v1.0 行号。
- “测试位置”省略统一前缀 `tests/unit/`。
- 结果为 `N/A` 的规则表示已明确判定不属于 Schema 层，不是“未实现”。

### 7.1 任务规则（TK / ST）

| 合同规则 | 文档位置 | Schema 实现位置 | 测试位置 | 结果 |
| --- | --- | --- | --- | --- |
| TK-01 | §4.3 L212 | `task.py` `AgentTask._required_non_empty` | `test_task_schema.py::test_empty_required_strings_rejected_TK_01` | PASS |
| TK-02 | §4.3 L213 | `task.py` `_check_consistency` | `test_parent_task_id_cannot_reference_itself_TK_02`、`test_depth_two_subtask_record_is_valid_TK_02` | PASS（仅自引用；深度/存在性见 §3.4） |
| TK-03 | §4.3 L214 | `task.py` `TaskStatus` | `test_invalid_status_rejected_TK_03` | PASS |
| TK-04 | §4.3 L215 | `task.py` `TaskPriority` | `test_invalid_priority_rejected_TK_04` | PASS |
| TK-05 | §4.3 L216 | `task.py` `retry_count`/`max_retries` + 校验 | `test_retry_count_must_not_exceed_max_retries_TK_05`、`test_negative_retry_fields_rejected_TK_05` | PASS |
| TK-06 | §4.3 L217 | `task.py` `timeout_seconds` `gt=0` | `test_timeout_must_be_positive_TK_06`、`test_timeout_accepts_positive_or_null_TK_06` | PASS |
| TK-07 | §4.3 L218 | `task.py` typed `dict` 字段 | `test_input_and_expected_output_must_be_dicts_TK_07` | PASS |
| TK-08 | §4.3 L219 | `task.py` `task_id` uuid4 默认 | `test_minimal_task_defaults_and_unique_ids_TK_08` | PASS |
| TK-09 | §4.3 L220 | `task.py` `_check_consistency` | `test_failed_status_requires_last_error_TK_09` | PASS |
| TK-10 | §4.3 L221 | `task.py` `_utc_datetimes` + `finished_at` 比较 | `test_created_at_must_be_utc_TK_10`、`test_finished_at_must_not_precede_created_at_TK_10`、`test_finished_at_must_not_precede_started_at_TK_10` | PASS |
| TK-11 | §4.3 L222 | `ConfigDict(extra="forbid")` | `test_extra_fields_rejected_TK_11` | PASS |
| TK-12 | §4.3 L223 | Pydantic 模型 | `test_json_roundtrip_TK_12` | PASS |
| TK-13 | §4.3 L224 | `task.py` `_check_status_timestamps` | `test_status_timestamp_consistency_valid_TK_13`、`test_status_timestamp_consistency_invalid_TK_13`、`test_retry_after_failure_clears_finished_at_TK_13` | PASS |
| ST-01 | §6 L560 | `task.py` `_ALLOWED_STATUS_TRANSITIONS` | `test_status_transition_matrix_ST_01_ST_02` | PASS |
| ST-02 | §6 L561 | 同上 | 同上 | PASS |
| ST-03 | §6 L562 | `task.py` `is_transition_allowed` | `test_failed_to_pending_requires_retryable_and_quota_ST_03`、`test_task_can_transition_to_uses_last_error_ST_03` | PASS |
| ST-04 | §6 L563 | 运行时更新 `started_at` | — | N/A（编排层） |
| ST-05 | §6 L566 | `task.py` `is_transition_allowed` 纯函数 | 由 ST-01～ST-03 测试覆盖；按 `acceptance.md` §3.4.3 不写 ST-05 编号 | PASS（功能实现；编号按验收口径排除） |
| ST-06 | §6 L564 | 运行时写入最终 `finished_at` | — | N/A（编排层） |
| ST-07 | §6 L565 | 运行时重试迁移 | — | N/A（编排层） |

### 7.2 Finding / 结果规则（FD / RS）

| 合同规则 | 文档位置 | Schema 实现位置 | 测试位置 | 结果 |
| --- | --- | --- | --- | --- |
| FD-01 | §5.3 L384 | `result.py` `Finding._check_traceability` | `test_code_location_evidence_passes_FD_01_FD_02`、`test_tool_evidence_only_passes_FD_01`、`test_finding_without_any_evidence_rejected_FD_01` | PASS |
| FD-02 | §5.3 L385 | 同上 | `test_high_severity_requires_code_location_FD_02` | PASS |
| FD-03 | §5.3 L386 | 同上 | `test_file_path_and_start_line_must_be_provided_together_FD_03` | PASS |
| FD-04 | §5.3 L387 | 同上 + `ge=1` | `test_end_line_before_start_line_rejected_FD_04`、`test_line_numbers_must_be_positive_FD_04`、`test_end_line_requires_start_line_FD_04` | PASS |
| FD-05 | §5.3 L388 | `result.py` `_relative_posix_path` | `test_invalid_file_paths_rejected_FD_05` | PASS |
| FD-06 | §5.3 L389 | `Finding.confidence` | `test_confidence_bounds_FD_06` | PASS |
| FD-07 | §5.3 L390 | `Finding._required_non_empty` | `test_blank_text_fields_rejected_FD_07` | PASS |
| FD-08 | §5.3 L391 | `result.py` `Severity` | `test_invalid_severity_rejected_FD_08` | PASS |
| FD-09 | §5.3 L392 | — | — | N/A（编排层，合同明确不强制） |
| FD-10 | §5.3 L393 | — | — | N/A（脱敏流程） |
| RS-01 | §8.2 L666 | `result.py` `AgentResult._check_consistency` | `test_completed_result_with_error_rejected_RS_01` | PASS |
| RS-02 | §8.2 L667 | 同上 | `test_failed_result_requires_error_RS_02`、`test_failed_result_must_not_have_score_RS_02`、`test_failed_result_must_not_have_findings_RS_02` | PASS |
| RS-03 | §8.2 L668 | 同上 | `test_partial_result_requires_error_RS_03`、`test_partial_result_with_error_is_valid_RS_03` | PASS |
| RS-04 | §8.2 L669 | `AgentResult.score` | `test_score_bounds_RS_04` | PASS |
| RS-05 | §8.2 L670 | `AgentResult.execution_time` | `test_negative_execution_time_rejected_RS_05` | PASS |
| RS-06 | §8.2 L671 | `_check_consistency` 唯一性 | `test_duplicate_finding_ids_rejected_RS_06` | PASS |
| RS-07 | §8.2 L672 | `_check_consistency` 名称一致 | `test_finding_agent_name_must_match_result_RS_07` | PASS |
| RS-08 | §8.2 L673 | `_valid_commit_sha` | `test_invalid_commit_sha_rejected_RS_08` | PASS |
| RS-09 | §8.2 L674 | `Field(default_factory=list)` | `test_default_findings_lists_not_shared_RS_09`、`test_finding_mutable_defaults_not_shared_RS_09` | PASS |
| RS-10 | §8.2 L675 | Pydantic 模型 | `test_agent_result_json_roundtrip_RS_10` | PASS |

### 7.3 报告规则（RP）

| 合同规则 | 文档位置 | Schema 实现位置 | 测试位置 | 结果 |
| --- | --- | --- | --- | --- |
| RP-01 | §9.3 L907 | `report.py` `ReviewReport.overall_score` | `test_overall_score_bounds_RP_01` | PASS |
| RP-02 | §9.3 L908 | `report.py` `Verdict` | `test_invalid_verdict_rejected_RP_02` | PASS |
| RP-03 | §9.3 L909 | `ExecutionSummary._check_task_counts` | `test_execution_task_counts_must_sum_RP_03` | PASS |
| RP-04 | §9.3 L910 | `ReviewReport._check_report_status` | `test_completed_report_requires_all_results_completed_RP_04`、`test_completed_report_requires_all_dimension_scores_RP_04`、`test_completed_report_requires_external_results_completed_RP_04`、`test_partial_report_with_partial_result_is_valid_RP_04`、`test_partial_report_when_everything_completed_rejected_RP_04` | PASS |
| RP-05 | §9.3 L911 | `_check_verdict_rules` | `test_partial_report_must_not_approve_RP_05` | PASS |
| RP-06 | §9.3 L912 | `_check_verdict_rules` | `test_verified_critical_requires_request_changes_RP_06` | PASS |
| RP-07 | §9.3 L913 | `_check_findings` | `test_rejected_findings_only_in_rejected_list_RP_07` | PASS |
| RP-08 | §9.3 L914 | `_check_findings` | `test_duplicate_finding_ids_rejected_RP_08` | PASS |
| RP-09 | §9.3 L915 | `TestSummary._check_consistency` | `test_not_executed_summary_rejects_test_numbers_RP_09`、`test_not_executed_summary_requires_reason_RP_09` | PASS |
| RP-10 | §9.3 L916 | `TestSummary._check_consistency` | `test_coverage_requires_source_RP_10`、`test_coverage_bounds_RP_10` | PASS |
| RP-11 | §9.3 L917 | `_check_weights` + `DimensionScore.weight` | `test_dimension_weight_bounds_RP_11`、`test_dimension_weights_must_sum_to_one_RP_11`、`test_dimension_weights_accept_tolerance_RP_11` | PASS |
| RP-12 | §9.3 L918 | `_check_commit_shas` | `test_agent_commit_sha_must_match_report_RP_12`、`test_external_commit_sha_must_match_report_RP_12`、`test_report_commit_sha_format` | PASS |
| RP-13 | §9.3 L919 | Pydantic 模型 | `test_report_json_roundtrip_RP_13` | PASS |
| RP-14 | §9.3 L920 | `_check_verdict_rules` | `test_missing_dimension_score_must_not_approve_RP_14` | PASS |
| RP-15 | §9.3 L921 | `_check_dimension_keys` | `test_dimension_scores_missing_key_rejected_RP_15`、`test_dimension_scores_unknown_key_rejected_RP_15`、`test_empty_dimension_scores_rejected_RP_15`、`test_agent_results_keys_must_match_RP_15`、`test_failed_agent_result_is_retained_RP_15` | PASS |
| RP-16 | §9.3 L922 | `_check_score_semantics` | `test_all_dimensions_null_report_valid_RP_16`、`test_all_dimensions_null_requires_null_overall_RP_16`、`test_all_dimensions_null_must_not_approve_RP_16`、`test_all_dimensions_null_requires_reasons_RP_16`、`test_partial_dimensions_require_renormalized_overall_RP_16`、`test_partial_dimensions_require_non_null_overall_RP_16`、`test_partial_dimensions_renormalized_average_RP_16`、`test_all_dimensions_scored_reject_null_overall_RP_16` | PASS |
| RP-17 | §9.3 L923 | `_check_execution_summary` | `test_execution_summary_total_tasks_mismatch_RP_17`、`test_execution_summary_completed_mismatch_RP_17`、`test_execution_summary_cancelled_rule_RP_17`、`test_execution_summary_includes_external_tasks_RP_17` | PASS |
| RP-18 | §9.3 L924 | `DimensionScore._check_consistency` | `test_dimension_null_score_requires_reason_RP_18`、`test_failed_dimension_must_not_have_score_RP_18`、`test_dimension_null_score_with_reason_valid_RP_18` | PASS |
| RP-19 | §9.3 L925 | `_check_dimension_statuses` | `test_dimension_status_must_match_agent_result_RP_19` | PASS |
| RP-20 | §9.3 L926 | `_check_external_results` | `test_external_result_key_must_not_reuse_core_dimension_RP_20`、`test_external_result_key_must_not_be_empty_RP_20`、`test_external_agent_result_valid_RP_20`、`test_external_failure_is_retained_RP_20` | PASS |

### 7.4 其他规则族（TT / RT / JS / EX）

| 规则族 | 处理结果 |
| --- | --- |
| TT-1～TT-5 | N/A（任务树与 Final Reviewer 编排）；TT-3 由 RP-17 间接体现：`total_tasks` 只统计四个核心结果 + 外部结果，不含 Manager 根任务与 Final Reviewer |
| RT-01、RT-02 | N/A（重试语义说明）；TK-05 约束 `retry_count`/`max_retries` 取值 |
| RT-03 | PASS（由 TK-05 拒绝 `retry_count > max_retries`） |
| RT-04、RT-06 | N/A（持久化与幂等，阶段 4） |
| RT-05 | PASS（由 ST-03 的 `retryable` 判断覆盖） |
| JS-01 | N/A（UTF-8 编码由序列化工具保证，无 Schema 校验点） |
| JS-02 | PASS（`test_all_contract_field_names_are_snake_case_JS_02`） |
| JS-03 | PASS（TK-10、`generated_at`、`occurred_at` 的 UTC 校验） |
| JS-04 | PASS（所有状态/严重级别/结论均用 `Literal`，测试覆盖非法大小写） |
| JS-05 | PASS（`test_optional_fields_serialize_as_null_JS_05`） |
| JS-06 | PASS（roundtrip 测试使用 `model_dump_json` / `model_validate_json`） |
| JS-07 | PASS（TK-11 及各模型 `extra="forbid"`） |
| JS-08 | PASS（FD-05 与行号约束） |
| JS-09 | PASS（RS-09、默认字典/列表 `default_factory`） |
| JS-10 | PASS（TK-12、RS-10、RP-13） |
| JS-11 | PASS（title/description/evidence/summary 长度测试） |
| JS-12 | N/A（脱敏与日志治理） |
| EX-1 | PASS（RP-15 固定四键，外部结果不改变核心维度） |
| EX-2 | PASS（RP-20：外部结果只在 `external_agent_results`，不在 `dimension_scores`） |
| EX-3 | 部分 PASS：证据合同由 FD-01～FD-08/RP-20 覆盖；`ARC-` 前缀与 Agent 名称是命名约定，`agent_name` 按合同保持 `str`，Schema 不强制 |
| EX-4 | PASS（RP-06 可被外部 verified critical 触发；RP-20 不允许外部结果进入核心加权维度） |
| EX-5 | PASS（RP-04/RP-17/RP-20：外部失败保留、报告 partial、`total_tasks` 计入外部任务） |

---

## 8. 文档 JSON 示例验证结果

### 8.1 总览

对五份文档中所有以 `json` 标记的围栏代码块执行 `json.loads`，并按内容分类校验：

```text
json_blocks = 15
failures = []
```

| 文档 | 代码块数 | 说明 |
| --- | --- | --- |
| `docs/requirements.md` | 0 | 无 JSON 代码块 |
| `docs/architecture.md` | 0 | 无 JSON 代码块 |
| `docs/workflow.md` | 1 | `{repository_url, branch}` 片段，仅解析，不是完整模型示例 |
| `docs/task_contracts.md` | 14 | 3 个 AgentTask、4 个 Finding（3 合法 + 1 非法）、3 个 AgentResult、1 个 TestSummary、2 个 ReviewReport、1 个非模型片段 |
| `docs/acceptance.md` | 0 | 无 JSON 代码块 |

### 8.2 逐块结果

| 文档/块 | 类型 | 结果 |
| --- | --- | --- |
| `workflow.md` 块 1 | 非模型片段 | JSON 解析通过；缺少完整模型必填字段，不作为 Schema 示例 |
| `task_contracts.md` 块 1 | 非模型片段 | JSON 解析通过 |
| `task_contracts.md` 块 2～4 | AgentTask（根任务、专业任务、深度 2 子任务） | 3/3 通过 `AgentTask.model_validate` |
| `task_contracts.md` 块 5～7 | Finding 合法示例 A/B/C | 3/3 通过 `Finding.model_validate` |
| `task_contracts.md` 块 8 | Finding 非法示例（SEC-099） | **按预期失败**：无代码位置且无工具证据，违反 FD-01/FD-02 |
| `task_contracts.md` 块 9～11 | AgentResult（completed / partial / failed） | 3/3 通过 `AgentResult.model_validate` |
| `task_contracts.md` 块 12 | ReviewReport §9.4 完整示例 | 通过 `ReviewReport.model_validate` |
| `task_contracts.md` 块 13 | TestSummary（`not_executed`） | 通过 `TestSummary.model_validate` |
| `task_contracts.md` 块 14 | ReviewReport §9.5 全维度 null 示例 | 通过 `ReviewReport.model_validate`；`overall_score = null`、`partial`、`COMMENT` |

### 8.3 与验收口径的差异

`docs/acceptance.md` AC-0-29 写“每个完整示例在测试中都有对应用例并通过 `model_validate`”，但 `task_contracts.md` §5.6 明确包含一个“非法示例（必须被拒绝）”。本次按 `0.3阶段任务要求.md` §7.4 的口径执行：

- 合法完整示例 → 必须通过；
- 仅用于展示非法输入的示例 → 明确标注预期失败。

因此块 8 的“失败”是预期结果，不是文档示例缺陷。建议后续把 AC-0-29 与合同 §14 的措辞改为“每个合法完整示例”，以消除 D-7。

---

## 9. 未解决问题与风险

### 9.1 阻断项（导致本次不能 PASS / 不能冻结）

| 编号 | 问题 | 影响 | 建议处理 |
| --- | --- | --- | --- |
| B-1 | D-1：`requirements.md:242` 未同步 RP-16 的“已核验 critical 例外” | 五份文档作为统一基线时，全 null 报告的结论口径不一致 | 以 `task_contracts.md` 为准，修订 FR-3.8 增加例外说明，走合同变更记录 |
| B-2 | D-2：`requirements.md:170/239` 把硬性阻断限定为“critical 安全漏洞” | 与 RP-06“任意维度 verified critical”及外部 Finding 的范围不一致 | 以合同为准，修订需求文档措辞 |
| B-3 | D-3：权重重新归一化的表述容易与“存储权重不变”混淆 | 读者可能误以为要修改 `DimensionScore.weight` | 明确“只有综合分计算公式内部归一化，存储的四个权重始终为配置值且和为 1” |
| B-4 | D-4：最大任务深度/子任务不得再创建子任务无法在单模型 Schema 中实现 | 任务要求 §5.2 要求的“超出最大任务深度”“子任务继续创建子任务”测试无法在不新增字段的前提下编写 | 二选一：① 接受为编排层规则，阶段 3 用任务树校验；② 修订合同增加深度字段后再进 Schema。不得静默加字段 |
| B-5 | D-5：ST-05 的功能要求与验收追溯口径冲突 | 功能已实现并测试，但测试名不能写 ST-05，否则追溯输出多于期望 | 明确 ST-05 是否属于阶段 0 Schema 测试范围；当前按验收口径排除 |
| B-6 | D-6：AC-0-24 的“后五项明确标注为设计”与 `workflow.md` §3 的“阶段 2 实现 + §3.0 设计边界”措辞不一致 | 文档冻结时无法同时满足字面验收项与文档实际写法 | 修订 AC-0-24 的措辞，或补充 §3 的“设计”标注 |
| B-7 | D-7：AC-0-29 / 合同 §14 的“每个完整示例通过”与 §5.6 非法示例冲突 | 验收口径自相矛盾 | 改为“每个合法完整示例通过；非法示例预期失败” |
| B-8 | D-8：`workflow.md:23` “阶段 0 不要求任何代码”与阶段 0 Schema 交付物矛盾 | 阶段 0 范围表述不一致 | 改为“阶段 0 不要求运行时 Agent 代码；Schema 与测试仍是阶段 0 交付物” |
| B-9 | D-9：任务要求中的 `Evidence` 模型、“有效权重总和为零必须拒绝”与合同不一致 | 若按任务文字实现，会发明合同外的模型/规则 | 以合同为准：不新增 `Evidence` 类；全维度 null 是合法报告，拒绝的是 RP-11 的非法权重 |

### 9.2 非阻断实现说明

1. `ExecutionSummary` 只定义在 `report.py`，未在 `result.py` 重复定义；依据合同 §9.2。
2. `TestSummary.execution_status = failed` 时要求 `reason` 非空，来自合同 §9.2 的字段说明；该约束没有独立 RP 编号，但有测试。
3. `AgentResult.status` 不含 `cancelled`；取消按 `failed` + `error.error_type = "cancelled"` 表达，RP-17 按该组合计数。
4. `AgentTask` 不新增 `task_depth` 字段；深度 2 的记录可以作为合法 `AgentTask` 存在，但“是否超过深度 2”“子任务是否再创建子任务”必须由任务树上下文校验。
5. `Finding` 的 `verification_status = verified` 不检查“是否由 Final Reviewer 核验”；FD-09 明确该规则在编排层。
6. `Category`、`agent_name`、`task_type`、`error_type`、`language` 保持 `str`，未改为 `Literal`；这是合同的有意设计。
7. `schema_version` 保持 `str`，默认 `"1.0"`；未用 `Literal["1.0"]` 锁死，以支持次版本升级。

### 9.3 阶段 0 正式验收风险

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 文档冻结（通过条件 5） | BLOCKED | 本次因 D-1～D-9 暂停冻结；文档仍为“待评审，评审通过后冻结” |
| AC-0-30 / AC-0-31 / AC-0-32 / AC-0-33 | BLOCKED | 无 Git 远端、无 commit、无 push、无 tag；本阶段明确禁止 commit / push / tag |
| AC-0-24 / AC-0-29 | 口径冲突 | 见 B-6、B-7；不是代码问题 |
| AC-0-05 | PASS | 修订后的四分项全部通过；`opentelemetry-api` 为 FastAPI 被动依赖 |
| 规则追溯 | PASS | 输出恰好为 6 个排除项 |
| 测试 | PASS | 203 passed，无 skip / xfail |

### 9.4 其他风险

- 仓库无 commit，无法用 Git diff 证明“旧代码到新代码”的逐行差异；本报告 §2 的基线来自上一轮验收报告，属于文档证据而非版本库证据。
- `.gitignore` 规则 `reports/*` + `!reports/.gitkeep` 会忽略本报告；若需入库，应由用户决定是否调整规则或另存到 `docs/acceptance_records/`。
- 本次未做真实 Conda 环境重建；环境验证沿用现有 `multi-agent-review` 环境。
- 本次未实际渲染 Mermaid 图；只做了代码围栏成对闭合的静态检查。若冻结前要求渲染验收，需要在 GitHub/VS Code 中人工确认。

---

## 10. 阶段 0.3 最终验收结论

### 10.1 结论

**BLOCKED。**

不是 FAIL，因为 Schema 层与测试层的交付已经完成且全部通过：
- `compileall` 通过；
- 203 条单元测试全部通过，0 failure / 0 error / 0 skip / 0 xfail；
- 规则追溯输出与验收期望完全一致；
- 15 个文档 JSON 块全部可解析，13 个合法模型示例全部通过，1 个非法示例按预期失败；
- 未发现阶段 0 越界目录或后续阶段依赖。

也不是 PASS，因为任务要求明确规定：存在关键 Schema 规则未实现、关键测试未通过或文档合同仍有冲突时不得判定 PASS。本次存在 D-1～D-9 的直接冲突，其中 D-1、D-2 涉及业务结论口径，D-4 涉及任务要求与合同的可实现性冲突；在这些问题由用户裁定之前，不能冻结五份文档，也不能给出 PASS。

### 10.2 本次实际完成

| 项目 | 结果 |
| --- | --- |
| 任务 0.1：现状与差异检查 | 完成；差异清单见 §2 |
| 任务 0.2：文档冻结 | **未完成（BLOCKED）**；发现冲突后按规则回退冻结标注 |
| 任务 0.4：Schema 重建 | 完成；`task.py`、`result.py`、`report.py` 均以最新合同为准 |
| 任务 0.5：测试重写/补充 | 完成；203 条用例，覆盖全部 Schema 层规则 |
| 任务 0.6：三方一致性检查 | 完成；追溯表见 §7，冲突见 §9 |
| 任务 0.7：自动化验收 | 完成；结果见 §6、§8 |
| 交付报告 | `reports/phase_0_2_acceptance_report.md`（本文件） |

### 10.3 本次未做（遵守阶段 0.3 禁令）

- 未执行 Git commit、push、tag；
- 未实现 Agent、LLM 调用、LangGraph、Manager、专业 Agent、MCP、A2A、Redis、ARQ；
- 未修改项目总体架构；
- 未删除原有有效测试；
- 未通过放宽 Schema 约束规避失败；
- 未 clone 目标仓库、未执行目标仓库脚本、未生成真实评审报告。

### 10.4 需要用户确认的裁定

建议按以下顺序裁定；确认后即可完成冻结并复验：

1. **文档权威顺序**：确认以 `docs/task_contracts.md` 为数据合同唯一权威（`acceptance.md` AC-0-26 已给出该原则）。若确认，D-1、D-2、D-3 按合同修订需求文档措辞，不改 Schema。
2. **最大任务深度**：确认 D-4 采用“编排层规则”而非 Schema 字段；阶段 0.3 报告记录为不在 Schema 层实现，阶段 3 由任务树校验。或者，确认修订合同新增深度字段后再实现。
3. **ST-05 归属**：确认 ST-05 的功能已由 `is_transition_allowed` + 现有测试满足，但按 `acceptance.md` §3.4.3 不写 ST-05 编号；或调整验收期望输出。
4. **验收措辞**：修订 AC-0-24（设计标注）、AC-0-29（合法示例）、`workflow.md:23`（阶段 0 代码范围）与合同 §14 的示例措辞。
5. **冻结**：上述 1～4 确认并完成文档变更记录后，再由项目负责人执行五份文档的 `已冻结（Frozen）` 标注；随后重跑本报告 §6～§8，结论才可能改为 PASS。
6. **阶段 0 正式验收**：文档冻结、Git 远端/commit/push/tag、AC-0-30～33 均完成后再单独出具阶段 0 最终验收报告；本报告不能替代阶段 0 正式验收。

---

## 附录 A：本次修改文件清单

| 文件 | 修改类型 | 说明 |
| --- | --- | --- |
| `src/code_review/schemas/task.py` | 重建/补强 | TK-13、`finished_at >= started_at` |
| `src/code_review/schemas/result.py` | 重建/补强 | FD-01～FD-08、RS-01～RS-09、ToolEvidence/Finding/AgentResult |
| `src/code_review/schemas/report.py` | 重建/补强 | `external_agent_results`、nullable `overall_score`、`DimensionScore.reason`、RP-01～RP-20 一致性校验 |
| `tests/unit/test_task_schema.py` | 重写 | 73 条用例 |
| `tests/unit/test_result_schema.py` | 重写/补充 | 59 条用例，含 JS-02/JS-05 |
| `tests/unit/test_report_schema.py` | 重写 | 71 条用例，含 §9.4/§9.5 文档示例 |
| `reports/phase_0_2_acceptance_report.md` | 新增 | 本报告 |
| `docs/*.md` | 未保留修改 | 曾写入冻结标注，因冲突按 §3.2(4) 回退；当前业务内容与冻结前一致 |

未修改：`environment.yml`、`.env.example`、`.gitignore`、`config/settings.py`、`pytest.ini`、`README.md`。

## 附录 B：关键命令原始输出

```text
$ python -m compileall src/code_review
compileall OK

$ pytest tests/unit -v
203 passed in 0.69s

$ pytest -v
203 passed in 0.48s

$ python -c "...规则追溯..."
['FD-09', 'FD-10', 'ST-04', 'ST-05', 'ST-06', 'ST-07']

$ python ...（文档 JSON 检查）
json_blocks= 15
failures= []

$ python -c "...AC-0-05 (a)..."
FORBIDDEN: []
PASSIVE-ALLOWED: ['opentelemetry-api']

$ python -c "...AC-0-05 (b)..."
OTEL-IN-CODE: []

$ python -c "...AC-0-05 (c)..."
OTEL-IN-ENV: False

$ pip show opentelemetry-api
Name: opentelemetry-api
Version: 1.45.2
Required-by: fastapi
```

## 附录 C：验收签署

| 项目 | 内容 |
| --- | --- |
| 验收执行 | Claude Code（自动化命令 + 文档交叉核对） |
| 验收日期 | 2026-11-09 |
| 最终结论 | **BLOCKED** |
| 项目负责人确认 | 待确认（D-1～D-9 的裁定、文档冻结、Git 版本管理均需负责人决定） |
