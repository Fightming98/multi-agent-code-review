# Stage 2.3 验收报告：LangGraph StateGraph 与并行 Fan-out / Fan-in

- 阶段：Stage 2.3（LangGraph StateGraph、并行 Fan-out / Fan-in）
- 日期：2026-11-12
- 基线 HEAD：`12daa7d`（Stage 2.2 交付内容为未提交工作区变更）
- 结论：**PASS**

本阶段严格按 `Stage2.1-2.6分阶段实施Promp.md` 的 Stage 2.3 边界执行：只新增
`src/code_review/graph/`、三个图单元测试、一个集成测试与 Stage 2.3 测试辅助；
`final_reviewer` 仅为占位节点；未实现证据验证、去重、评分或 `ReviewReport`；
未接入 `ReviewService`；未进入 Stage 2.4。

---

## 1. 文件变更

### 1.1 新增文件

| 文件 | 行数 | 说明 |
|---|---:|---|
| `src/code_review/graph/__init__.py` | 49 | 导出 State、节点与图装配公共名称 |
| `src/code_review/graph/state.py` | 228 | `ReviewState`、`RepositoryContext`、`build_initial_state` |
| `src/code_review/graph/nodes.py` | 473 | Manager、四个 Worker、占位 Final Reviewer 节点 |
| `src/code_review/graph/workflow.py` | 161 | `GraphDependencies`、`build_review_graph`、`run_review_graph` |
| `tests/unit/test_graph_state.py` | 358 | 20 条 State/Reducer 测试 |
| `tests/unit/test_graph_workflow.py` | 578 | 25 条节点、边、异常隔离测试 |
| `tests/unit/test_graph_parallel.py` | 110 | 2 条并行时间窗口证明测试 |
| `tests/integration/test_stage2_pipeline.py` | 335 | 6 条 Fake Agent 全图集成测试 |
| `environment.lock.stage2.yml` | — | Stage 2.3 安装后的 Windows 环境快照 |

### 1.2 修改文件

| 文件 | 变更 |
|---|---|
| `tests/stage2_helpers.py` | 新增 `make_inventory_summary`、`make_repository_context`、`make_review_state`、`make_test_report_block`、`make_dimension_evidence`、`make_agent_run_output`、`make_dimension_factory`、`make_graph_dependencies`；`make_plan_execution` 改用 `make_test_report_block` |
| `environment.yml` | 新增 `langgraph==1.2.19`（安装门禁已批准） |

### 1.3 边界确认

- 三个冻结 Schema、五份核心文档、`report_generator.py`、`artifact_models.py`、
  `markdown_renderer.py`、`finding_aggregator.py`、`tests/fixtures/trusted_repo/`
  未修改。
- `environment.lock.yml` 未修改（`git status` 无该文件，`git diff` 为空）。
- 未创建 Checkpointer，未引入 Redis、ARQ、PostgreSQL、MCP、A2A、Streamlit。
- `src/` 下无 `langsmith`、`langchain`、`LangChainTracer`、`tracing` 引用。
- 本阶段未执行 Git commit；临时探针脚本已删除。

---

## 2. 图拓扑

### 2.1 节点与边

`build_review_graph()` 装配七个节点：

```text
START → manager_plan
      → 条件边 dispatch_workers 返回 4 个 Send
          ├→ security_worker    ─┐
          ├→ quality_worker     ─┤
          ├→ performance_worker ─┼→ manager_aggregate → final_reviewer → END
          └→ testing_worker     ─┘
```

- `manager_plan`：同步节点。调用确定性 `ManagerAgent.plan()`，写入
  `task_plan`、`root_task`、`agent_tasks`。
- 四个 Worker：异步节点，由 `make_worker_node(dimension, agent)` 构造，
  通过 `Send` 接收单个 `WorkerDispatch`。
- `manager_aggregate`：同步节点。只有四个 Worker 全部完成后才执行；
  重建 `AgentExecution`、调用 `ManagerAgent.aggregate()`，构建 `ArtifactData`。
- `final_reviewer`：同步占位节点，只写
  `review_report=None`、`review_statistics={...implemented: False}`、
  `review_status="pending_final_review"`。

测试 `test_graph_has_all_seven_nodes_and_no_checkpointer` 断言节点集合严格为
`{"__start__", "__end__", manager_plan, security_worker, quality_worker,
performance_worker, testing_worker, manager_aggregate, final_reviewer}`，
且 `graph.checkpointer is None`。

### 2.2 图装配实现

- `StateGraph(ReviewState)`；
- 节点通过 `functools.partial` 绑定 `ManagerAgent` 或具体 `BaseAgent`；
- `add_conditional_edges("manager_plan", dispatch_workers, [四个 worker 节点])`；
- 四个 Worker 分别 `add_edge(..., "manager_aggregate")`；
- `manager_aggregate → final_reviewer → END`；
- `compile()` 未传入 Checkpointer。

`GraphDependencies` 在构造时校验四个 Agent 均为 `BaseAgent`，且
`agent_name`/`task_type` 与 `AGENT_SPECS` 一致；不匹配直接 `ValueError`/
`TypeError`，避免把错误角色接进图。

---

## 3. ReviewState 字段及 Reducer

`ReviewState` 为 `TypedDict(total=False)`，共 34 个字段，与审计计划 §5.1
逐项一致（`test_state_declares_every_audit_field`）。

| 分组 | 字段 | 类型 |
|---|---|---|
| 只读上下文 | `review_id`、`trace_id`、`commit_sha`、`workspace_path`、`review_status` | `str` / `str \| None` |
| 只读上下文 | `repository` | `RepositoryContext` |
| 只读上下文 | `allowed_files` | `tuple[str, ...]` |
| 只读上下文 | `inventory` | `InventorySummary` |
| 只读上下文 | `rules` | `ReviewRules` |
| Manager Planning | `task_plan`、`root_task`、`agent_tasks` | `TaskPlan` / `AgentTask` / `list[AgentTask]` |
| 四维任务 | `security_task`、`quality_task`、`performance_task`、`testing_task` | `AgentTask \| None` |
| 四维结果 | `security_result`、`quality_result`、`performance_result`、`testing_result` | `AgentResult \| None` |
| 四维证据 | `security_evidence`、`quality_evidence`、`performance_evidence`、`testing_evidence` | `WorkerEvidence \| None` |
| Reducer 列表 | `completed_tasks`、`failed_tasks`、`worker_timings`、`warnings` | 见下 |
| Manager 单写者 | `agent_results`、`artifact_data`、`usage_summary`、`execution_summary` | `dict` / `ArtifactData` / `UsageSummary` / `ExecutionSummary` |
| Final Reviewer | `review_report`、`review_statistics`、`review_status` | `ReviewReport \| None` / `dict` / `str` |

Reducer 配置（`test_reducer_fields_use_operator_add`）：

```python
completed_tasks: Annotated[list[str], operator.add]
failed_tasks:    Annotated[list[str], operator.add]
worker_timings:  Annotated[list[WorkerTiming], operator.add]
warnings:        Annotated[list[str], operator.add]
```

其余字段均不带 reducer，因此四个 Worker 并行写入不同键时不会触发
`InvalidUpdateError`；若两个 Worker 并行写同一非 reducer 键，LangGraph 会
明确报错（`test_parallel_write_to_non_reducer_raises_invalid_update` 使用
反例图验证了这一行为）。

Reducer 运行时行为由三个测试验证：

- `test_operator_add_merges_parallel_worker_updates`：两个并行 Worker 的
  `completed_tasks`/`warnings` 被合并；
- `test_real_review_state_reducers_merge_parallel_updates`：直接使用真实
  `ReviewState` 建图验证；
- `test_parallel_write_to_non_reducer_raises_invalid_update`：反例证明不配置
  Reducer 会抛 `InvalidUpdateError`，不是只靠代码审查。

`build_initial_state()` 复用 `WorkerRuntime` 的校验逻辑：要求
`workspace_path` 为绝对路径、`commit_sha` 为 40 位小写 hex、`allowed_files`
为安全的仓库相对 POSIX 路径、`repository` 为 `RepositoryContext`；非法输入
抛 `ReviewStateError` / `ContractValidationError`，不静默修正。

---

## 4. 节点输入输出

| 节点 | 输入 | 输出 |
|---|---|---|
| `manager_plan` | 完整 `ReviewState`（读取 `review_id`、`commit_sha`、`repository`） | `task_plan`、`root_task`、`agent_tasks` |
| `dispatch_workers`（条件边） | 完整 `ReviewState`（读取 `task_plan`、`workspace_path`、`allowed_files`、`rules` 等） | `list[Send]`，每个 `Send` 载荷为 `WorkerDispatch(task, runtime)` |
| `security_worker` 等四个 Worker | **仅** `WorkerDispatch`，看不到完整 State | `{dimension}_task`、`{dimension}_result`、`{dimension}_evidence`、`completed_tasks`、`failed_tasks`、`worker_timings`、`warnings` |
| `manager_aggregate` | 完整 `ReviewState`（读取四个维度 task/result/evidence 与 timings） | `agent_results`、`artifact_data`、`usage_summary`、`execution_summary`、`root_task`、`warnings` |
| `final_reviewer` | 完整 `ReviewState`（只读 `agent_results`、`artifact_data`） | `review_report=None`、`review_statistics`、`review_status="pending_final_review"` |

Worker 隔离由结构保证：

- `dispatch_workers` 为每个维度只构造一个 `WorkerDispatch`，`task` 来自
  `TaskPlan.task_for(dimension)`，`runtime` 只含 `workspace_path`、
  `allowed_files`、`commit_sha`、`language`、`review_id`、`rules`、`trace_id`；
- Worker 节点签名接收 `WorkerDispatch`，不是 `ReviewState`；
- `test_one_send_per_dimension_with_isolated_payload` 断言载荷不是 dict、
  不携带完整状态；
- Worker 只返回自己的三个字段与四个 reducer 更新
  （`test_returns_only_its_own_keys`）。

`manager_aggregate` 在 Final Reviewer 之前构建 `ArtifactData`：

- `static_analysis.json`：`schema_version` + 四个维度的 tools 证据块，
  附加 `agent_name`、`result_status`、`warnings`；
- `test_report.json`：TestingAgent 的 `test_report`（缺失时使用
  `not_executed` 默认块）；
- 测试 `test_builds_artifacts_and_execution_summary` 断言
  `static_analysis.json#/agents/security/tools/bandit/findings/0`、
  `static_analysis.json#/agents/testing`、`test_report.json#/coverage`、
  `test_report.json#/counts` 均可通过稳定 JSON Pointer 解析。

---

## 5. Send / Fan-in 设计

### 5.1 Fan-out

`dispatch_workers(state) -> list[Send]` 按固定顺序（security、quality、
performance、testing）返回四个 `Send`：

```python
Send(
    WORKER_NODE_NAMES[dimension],
    WorkerDispatch(task=plan.task_for(dimension), runtime=runtime),
)
```

- `Send` 来自 `langgraph.types`；
- 每个 Worker 只收到自己的任务与最小 `WorkerRuntime`；
- 不使用手写 `asyncio.gather`，并行由 LangGraph 调度；
- 四个 Worker 节点同时拥有指向 `manager_aggregate` 的入边，LangGraph
  等待全部四个分支完成后才执行 fan-in 节点。

### 5.2 Fan-in

`manager_aggregate_node` 从 State 中按维度重建 `AgentExecution`：

- `{dimension}_task`、`{dimension}_result`、`{dimension}_evidence` 任一
  缺失/类型不符 → 该维度 `AgentExecution=None`；
- timing 优先从 `worker_timings` 按 `task_id` 查找，缺失时用真实任务时间戳
  推导，不伪造数值；
- Manager 对缺失/非法结果合成合法 failed `AgentResult`
  （`error_type="missing_agent_result"`、`retryable=False`、`score=None`），
  其他维度结果原样保留；
- `test_missing_worker_is_synthesized_as_failed` 验证该语义。

`test_fan_in_waits_for_the_slowest_worker` 使用 Testing 延迟 0.40 秒、其余
0.05 秒：断言 Testing timing 的 `finished_at` 是四个时间窗口中最晚的、
`agent_results["testing"].status == "completed"`、执行摘要为
4 completed / 0 failed。若 fan-in 提前执行，Testing 会被合成为 failed，
该测试会失败。

---

## 6. 并行时间线与实际耗时

### 6.1 测量方法

使用固定延迟 Fake Agent：

| 维度 | 配置延迟 |
|---|---:|
| Security | 0.30 s |
| Quality | 0.32 s |
| Performance | 0.34 s |
| Testing | 0.36 s |

`BaseAgent` 在 `execute()` 内用 `time.perf_counter()` 记录真实墙钟耗时，
并写入 `WorkerTiming.started_at/finished_at/duration_seconds`。测试读取四个
`WorkerTiming`，不读取配置延迟。

### 6.2 实测结果（2026-11-12，Windows 11，Python 3.12.16）

| Agent | 状态 | start offset | finish offset | duration |
|---|---|---:|---:|---:|
| SecurityAgent | completed | 0.000000 | 0.310506 | 0.309930 |
| QualityAgent | completed | 0.000000 | 0.311504 | 0.310705 |
| PerformanceAgent | completed | 0.000000 | 0.355383 | 0.354561 |
| TestingAgent | completed | 0.001515 | 0.356401 | 0.355580 |

- 图总耗时：**0.394414 s**
- 四个 Worker 耗时之和：**1.330776 s**
- 总耗时占串行和比例：**29.64%**（断言要求 < 75%）
- 公共重叠区间：`latest_start=0.001515` < `earliest_finish=0.310506`，
  重叠 **0.308991 s**

结论：四个时间窗口真实重叠，且图总耗时显著小于串行耗时之和；并行不是
仅凭使用 `Send` 宣称。

### 6.3 计时容差说明

Windows 事件循环计时器可能比请求延迟略早唤醒（本次 QualityAgent 配置
0.32 s，实测 0.310705 s）。因此：

- 测试不做“每个 Worker 的 duration ≥ 其配置延迟”的毫秒级绝对断言；
- 单 Worker 只断言宽松下界 0.25 s；
- 并行证明依赖两个稳健断言：`latest_start < earliest_finish` 与
  `elapsed < 0.75 × serial_sum`。

`test_fan_in_waits_for_the_slowest_worker` 同样使用 0.35 s 宽松下界，
避免脆弱的时间断言。

---

## 7. 单 Worker 失败测试

### 7.1 单元级

```text
$ pytest tests/unit/test_graph_workflow.py \
         -k "single_worker_failure or worker_exception or not_retried" -v

tests/unit/test_graph_workflow.py::TestWorkerNode::test_worker_exception_becomes_failed_result PASSED
tests/unit/test_graph_workflow.py::TestFullGraph::test_single_worker_failure_preserves_other_results PASSED
tests/unit/test_graph_workflow.py::TestFullGraph::test_worker_is_not_retried_after_failure PASSED
3 passed, 22 deselected in 2.08s
```

覆盖：

- Worker 节点捕获普通 `Exception`，生成该维度 failed `AgentResult`
  （`score=None`、`error.retryable=False`）；
- 错误消息中的工作区绝对路径被替换为 `<workspace>`，并经过脱敏；
- 其他三个维度结果完整保留；
- 失败 Worker 只执行一次，不重试、不退避、不执行 `failed→pending`；
- 四个维度全部失败时，图仍到达占位 Final Reviewer，根任务为
  `failed`（`error_type="aggregate_incomplete"`），不抛未捕获异常。

### 7.2 集成级

```text
$ pytest tests/integration/test_stage2_pipeline.py::test_single_worker_failure_keeps_other_results -v
PASSED
1 passed in 2.23s
```

断言：

- `agent_results["performance"].status == "failed"`；
- `error.message` 不含真实工作区路径，包含 `<workspace>`；
- security、quality、testing 均为 `completed`；
- `execution_summary` 为 3 completed / 1 failed；
- `failed_tasks` 只含 performance 任务 ID；
- `static_analysis.json#/agents/performance/result_status == "failed"`，
  其他维度仍为 `completed`；
- 工作区文件清单与内容在运行前后完全一致。

---

## 8. 依赖安装审批材料与批准记录

### 8.1 审批要求

Stage 2.3 提示词 §二、§三要求：安装 LangGraph 前必须通过安装门禁并获得负责人
确认；只允许新增 `langgraph`；`langchain-core`/`langsmith` 只能作为依赖闭包
中的被动存在，禁止源码直接 import、启用 tracing、读取 API Key 或网络上报；
不得安装 `langchain-openai`。

### 8.2 批准记录

- 日期：2026-11-12
- 负责人意见原文：

  > 全部批准，请按照“Stage2.1-2.6分阶段实施Promp.md”提示此指令要求继续执行”Stage 2.3：LangGraph StateGraph、并行 Fan-out / Fan-in“的阶段任务

- 批准范围：Stage 2.3 依赖安装门禁；仅安装 `langgraph`，允许被动带入
  `langchain-core` / `langsmith`，禁止直接使用。

### 8.3 实际安装与固定

- `environment.yml` 新增：`langgraph==1.2.19`；
- 实际安装版本：`langgraph==1.2.19`；
- `langgraph-checkpoint==4.3.1`、`langgraph-prebuilt==1.1.1`、
  `langgraph-sdk==0.4.14`、`langchain-core==1.8.0`、
  `langchain-protocol==0.0.21`、`langsmith==0.14.17` 为被动依赖；
- 未安装 `langchain-openai`；
- 未设置任何 LangSmith/LangChain API Key 或 tracing 环境变量。

---

## 9. LangSmith 探针结果

### 9.1 环境变量

| 变量 | 值 |
|---|---|
| `LANGSMITH_TRACING` | `None` |
| `LANGCHAIN_TRACING_V2` | `None` |
| `LANGSMITH_API_KEY` | `None` |
| `LANGCHAIN_API_KEY` | `None` |
| `LANGSMITH_ENDPOINT` | `None` |
| `LANGCHAIN_ENDPOINT` | `None` |
| `LANGSMITH_PROJECT` | `None` |
| `LANGCHAIN_PROJECT` | `None` |

### 9.2 代码与运行时

- `src/` 下搜索 `langsmith|langchain|LangChainTracer|tracing`：无匹配；
- 未创建 LangSmith client，未注册 callback，未启用 tracing；
- `graph.checkpointer is None`，未创建任何持久化后端；
- 最小 StateGraph 探针成功：
  `StateGraph(ProbeState)` → `START → probe → END` →
  `ainvoke({"value": "minimal"})` 输出 `{'value': 'minimal!'}`；
- 编译类型为 `CompiledStateGraph`。

### 9.3 被动存在说明

环境中存在 `langsmith==0.14.17`（被动依赖），pytest 启动时会列出
`langsmith-0.14.17` 插件。由于 tracing 环境变量均未设置、源码无 import、
无 API Key，该插件不产生任何上报。此行为符合 B-1 裁定。

---

## 10. 新锁文件及 Stage 1 锁文件对比

### 10.1 锁文件状态

| 文件 | 状态 |
|---|---|
| `environment.lock.yml` | 未修改（`git status` 无记录，`git diff` 为空） |
| `environment.lock.stage2.yml` | 新增，Stage 2.3 实际环境快照 |

`environment.lock.stage2.yml` 头部记录：

```text
# Stage 2 Windows 环境快照（非跨平台锁文件）
# 生成日期: 2026-11-12
# 生成命令: conda env export -n multi-agent-review --no-builds（已移除 prefix 行）
# 适用平台: Windows-11-10.0.26100-SP0 / Python 3.12.16
# LangGraph: 1.2.19（被动依赖 langchain-core 1.8.0 / langsmith 0.14.17）
# 说明: 本文件仅记录 Stage 2.3 完成时的实际环境；不得覆盖 Stage 1 的 environment.lock.yml。
```

### 10.2 与 Stage 1 锁文件的差异

按包条目逐行比较：**新增 25 个，移除 0 个**。

| 类别 | 包 |
|---|---|
| 已批准依赖 | `langgraph==1.2.19` |
| LangGraph 内部依赖 | `langgraph-checkpoint==4.3.1`、`langgraph-prebuilt==1.1.1`、`langgraph-sdk==0.4.14`、`ormsgpack==1.13.1`、`xxhash==4.1.0`、`zstandard==0.25.0`、`uuid-utils==0.19.0`、`orjson==3.13.0`、`jsonpatch==1.47`、`jsonpointer==3.12` |
| LangChain/LangSmith 被动依赖 | `langchain-core==1.8.0`、`langchain-protocol==0.0.21`、`langsmith==0.14.17` |
| 传输/通用依赖 | `charset-normalizer==3.5.2`、`requests==2.34.2`、`requests-toolbelt==1.0.0`、`urllib3==2.8.0`、`truststore==0.10.5`、`distro==1.9.0`、`httpx2==2.16.0`、`httpcore2==2.16.0`、`sniffio==1.3.1`、`tenacity==9.2.1`、`websockets==17.4` |

未出现：`redis`、`arq`、`sqlalchemy`、`asyncpg`、`mcp`、`a2a-sdk`、
`streamlit`、`langchain-openai`、`psycopg*`。

依赖探针输出（区分批准项与被动项）：

```text
FORBIDDEN (Stage 0/1 口径): ['langchain-core', 'langchain-protocol',
'langgraph', 'langgraph-checkpoint', 'langgraph-prebuilt', 'langgraph-sdk',
'langsmith']
PASSIVE-ALLOWED: ['opentelemetry-api']
```

其中 `langgraph` 及 `langgraph-*` 为已批准的 Stage 2.3 依赖；
`langchain-core`、`langchain-protocol`、`langsmith` 按 B-1 被动允许。
其余 Stage 0/1 禁止项仍为空。

---

## 11. 测试结果

### 11.1 Stage 2.3 三个单元测试文件

```text
$ pytest tests/unit/test_graph_state.py tests/unit/test_graph_workflow.py \
         tests/unit/test_graph_parallel.py -v
47 passed in 2.38s
```

分布：`test_graph_state.py` 20、`test_graph_workflow.py` 25、
`test_graph_parallel.py` 2。

### 11.2 Stage 2.3 集成测试

```text
$ pytest tests/integration/test_stage2_pipeline.py -v
6 passed in 1.49s
```

覆盖：完整四维流水线、D-11 partial 保留工具证据、D-12 外部 Testing
`not_executed` 仍为 completed、单 Worker 失败隔离、连续两次执行不共享状态、
同步入口 `run_review_graph`。

### 11.3 全量单元测试

```text
$ pytest tests/unit -q
1188 passed, 4 skipped in 23.64s
```

对比 Stage 2.2 基线（1141 passed, 4 skipped）：新增 47 条，全部通过。

### 11.4 全量测试

```text
$ pytest -q
1205 passed, 8 skipped in 36.02s
```

对比 Stage 2.2 全量基线（1152 passed, 8 skipped）：新增 53 条
（47 条单元 + 6 条集成），全部通过，无 failure / error。

### 11.5 Ruff

```text
$ ruff check src/code_review/graph tests/stage2_helpers.py \
             tests/unit/test_graph_state.py tests/unit/test_graph_workflow.py \
             tests/unit/test_graph_parallel.py \
             tests/integration/test_stage2_pipeline.py
All checks passed!
```

### 11.6 验收重点对照

| 验收重点 | 证据 |
|---|---|
| State 字段和 Reducer 正确 | §3；`test_graph_state.py` 20 条，含 `InvalidUpdateError` 反例 |
| Send 四路 Worker | `test_one_send_per_dimension_with_isolated_payload`；`task_dispatch` 日志 |
| Fan-in 等待四个结果 | `test_fan_in_waits_for_the_slowest_worker` |
| 四个 Worker 时间窗口重叠 | §6；`test_four_worker_windows_overlap_and_beat_serial_sum` |
| 无 `InvalidUpdateError` | 两次真实 `ReviewState` 并行图测试均无异常 |
| 一个 Worker 失败不丢失其他结果 | §7；单元 + 集成各一条 |
| Manager Aggregate 构建 `ArtifactData` | `manager_aggregate` 单写者；JSON Pointer 断言 |
| Final Reviewer 仍只是占位节点 | `test_marks_itself_as_not_implemented`；`review_report is None` |
| 无重试、Checkpointer、Redis/ARQ | `test_worker_is_not_retried_after_failure`；`graph.checkpointer is None`；依赖探针 |
| LangSmith 仅被动存在 | §9 |
| Stage 1 测试无回归 | §11.4 全量通过；Stage 1 工具/报告/服务未修改 |

---

## 12. 结论

**PASS**

Stage 2.3 的图拓扑、ReviewState 与 Reducer、Send 四路 Fan-out、Fan-in、
并行时间窗口证明、单 Worker 异常隔离、无 Checkpointer/无重试、LangSmith
被动边界、锁文件隔离与全量测试回归均满足提示词与审计计划要求。

按阶段边界，以下内容未在本阶段实现（属于后续子阶段，不是本阶段缺陷）：

1. 真实 Final Reviewer：证据验证、Finding 去重、维度评分、总体分与结论
   （Stage 2.4）；当前 `final_reviewer` 只写占位状态，`review_report` 恒为
   `None`。
2. `ReviewService` 集成、五件报告（含 `report.json`）、CLI/API 接线
   （Stage 2.5）。
3. `ReviewState.repository` 的运行时填充（Stage 2.5 由 `ReviewService`
   构造 `RepositoryContext`）。
4. 真实 LLM 冒烟；需负责人单独批准，不纳入默认验收（Stage 2.6）。
5. Fixture 与真实仓库的端到端基线（Stage 2.6）。

本阶段完成后立即停止，不进入 Stage 2.4。
