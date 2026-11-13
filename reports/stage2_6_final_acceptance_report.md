# Stage 2.6 最终验收报告

- 报告日期：2026-11-13
- 验收阶段：Stage 2.6（Fixture、端到端、基线与最终验收）
- 环境：Windows-11-10.0.26100-SP0 / Python 3.12.16 / conda env `multi-agent-review`
- 结论：**PASS WITH CONDITIONS**（见 §15）

本报告只记录实际执行结果。所有测试均在本机以 `python -B -X utf8 -m pytest` 运行，
未运行真实 LLM Smoke，未访问真实 GitHub 仓库，未执行外部仓库测试。

---

## 1. Stage 2 实际完成范围

Stage 2 已按 Stage 2.1 → 2.6 完成：

| 子阶段 | 内容 | 状态 |
| --- | --- | --- |
| 2.1 | Agent 合同、`BaseAgent`、Prompt 投影、规则加载、Fake 测试设施 | 已提交 `12daa7d` |
| 2.2 | Manager 与 Security / Quality / Performance / Testing 四个专业 Agent | 已提交 `d8e3cf0` |
| 2.3 | LangGraph StateGraph 并行 Fan-out / Fan-in | 已提交 `d8e3cf0` |
| 2.4 | Final Reviewer、V1～V7 证据校验、去重、维度评分 | 已提交 `ec0afe2` |
| 2.5 | ReviewService 集成、五件报告、CLI/API | 已提交 `ce1bded` |
| 2.6 | 自有 Fixture、真实工具 E2E、基线指标、最终验收 | 本次交付，未提交 |

Stage 2.6 实际完成的验证范围：

- 构建 `stage2_sample_repo_v1` 自有 Fixture，并由真实 Git 生成可重复的 commit SHA；
- Manager 生成 4 个任务，LangGraph 并行执行 4 个专业 Agent；
- 使用真实 Ruff / Bandit / Radon / Pytest / Coverage，不用 Mock 代替工具结果；
- Final Reviewer 完成证据校验、去重、四维评分与结论；
- `Stage2ReportGenerator` 写出五件产物，并校验内存与落盘一致；
- GT-1～GT-7 检测结果、Precision / Recall / FDR 与耗时基线；
- 全量回归、依赖探针与 Stage 2 环境锁。

未实现、也未声称完成的内容：真实 LLM 调用、真实 LLM Smoke、外部 A2A Agent、
Redis/ARQ、Checkpointer 持久化恢复、MCP、PostgreSQL、可观测性接入。以上均属于
Stage 3 及以后。

---

## 2. 所有新增 / 修改文件

### 2.1 新增文件

| 文件 | 说明 |
| --- | --- |
| `src/code_review/tools/stage2_fixture.py` | 466 行；从 Fixture 源目录构建确定性真实 Git 仓库，返回真实 commit SHA |
| `tests/integration/test_stage2_e2e.py` | 1118 行；13 个 Stage 2.6 端到端验收测试 |
| `tests/fixtures/stage2_sample_repo/FIXTURE_MANIFEST.json` | Fixture 哈希清单，11 个文件 |
| `tests/fixtures/stage2_sample_repo/.gitattributes` | 固定换行属性 |
| `tests/fixtures/stage2_sample_repo/README.md` | Fixture 说明 |
| `tests/fixtures/stage2_sample_repo/sample_app/__init__.py` | 应用包 |
| `tests/fixtures/stage2_sample_repo/sample_app/client_defaults.py` | GT-1：Bandit B107 |
| `tests/fixtures/stage2_sample_repo/sample_app/inventory.py` | 库存逻辑 |
| `tests/fixtures/stage2_sample_repo/sample_app/processor.py` | GT-3 / GT-4 / GT-7 |
| `tests/fixtures/stage2_sample_repo/sample_app/reporting.py` | 报表逻辑 |
| `tests/fixtures/stage2_sample_repo/sample_app/repository.py` | GT-2：Bandit B608 |
| `tests/fixtures/stage2_sample_repo/tests/test_inventory.py` | GT-5：1 个预期失败测试 |
| `tests/fixtures/stage2_sample_repo/tests/test_processor.py` | 通过测试 |
| `tests/fixtures/stage2_sample_repo/tests/test_repository.py` | 通过测试 |
| `reports/stage2_6_final_acceptance_report.md` | 本报告 |

### 2.2 修改文件

| 文件 | 变更 |
| --- | --- |
| `src/code_review/tools/trusted_fixture.py` | 仅在白名单新增 `stage2_sample_repo_v1`；校验逻辑、大小限制、链接拒绝、哈希校验均未放宽 |
| `tests/stage2_helpers.py` | 追加 Stage 2.6 测试辅助：Prompt 路由 Fake LLM、LLM Proposal 构造、源码行定位、落盘 JSON Pointer 解析 |
| `environment.lock.stage2.yml` | 由实际 conda 环境重新导出，移除 `prefix`；未覆盖 Stage 1 `environment.lock.yml` |
| `CLAUDE.md` | 更新阶段状态、依赖现状、测试基线、冻结边界与 O-1 说明 |
| `README.md` | 更新阶段状态、技术栈、五件产物、安全边界与已知限制 |

### 2.3 未修改的冻结内容

`git diff --name-only` 对以下路径为空，确认未改动：

- `src/code_review/schemas/task.py`、`result.py`、`report.py`
- `docs/requirements.md`、`architecture.md`、`workflow.md`、`task_contracts.md`、`acceptance.md`
- `src/code_review/reporting/report_generator.py`、`artifact_models.py`、`markdown_renderer.py`
- `src/code_review/services/finding_aggregator.py`
- `tests/fixtures/trusted_repo/`
- `environment.lock.yml`

未引入 Redis、ARQ、PostgreSQL、SQLAlchemy、MCP、A2A、Streamlit、Docker，
未引入 LangGraph Checkpointer 或持久化恢复，未修改 Stage 3～7 代码。

---

## 3. Ground Truth 清单与检测结果

Fixture 源文件行号在测试中动态定位，不硬编码。以下为本次运行的实际行号。

| GT | 目标 | 检测来源 | 归属 Agent | 严重级别 | 位置 | 五件产物中的结果 |
| --- | --- | --- | --- | --- | --- | --- |
| GT-1 | 硬编码密码 | Bandit B107（LOW / MEDIUM） | SecurityAgent | low | `sample_app/client_defaults.py:4-9` | `SEC-BANDIT-0000`，verified |
| GT-2 | SQL 注入 | Bandit B608（MEDIUM / LOW） | SecurityAgent | medium | `sample_app/repository.py:15` | `SEC-BANDIT-0001`，verified |
| GT-3 | 高圈复杂度 | Radon CC 22，rank D | QualityAgent | medium | `sample_app/processor.py:4-49` | `QUA-RADON-0004`，verified；`merged_from=["PERF-RADON-0004"]` |
| GT-4 | 缺少错误处理 | 受控 Fake LLM | QualityAgent | medium | `sample_app/processor.py:54` | 未进入五件产物；Agent 级 `unverified`（V5） |
| GT-5 | 测试失败 | 真实 Pytest / JUnit | TestingAgent | medium | 项目级，无文件/行号 | `TEST-0001`，verified；证据 `test_report.json#/counts` |
| GT-6 | 覆盖率不足 | 真实 Coverage.py（40.48% < 80） | TestingAgent | medium | 项目级，无文件/行号 | `TEST-0002`，verified；证据 `test_report.json#/coverage` |
| GT-7 | O(n²) 风险 | 受控 Fake LLM | PerformanceAgent | medium | `sample_app/processor.py:63` | 未进入五件产物；Agent 级 `unverified`（V5） |

检测结果说明：

- GT-1 / GT-2 的严重级别来自 Bandit 原始 severity 与 `review_rules.yaml` 映射，
  未预置 B107 / B608 为 critical。
- GT-3 由 QualityAgent 与 PerformanceAgent 各自从 Radon 证据提出；Final Reviewer
  去重后保留 QualityAgent 的 Finding，并记录 `merged_from=["PERF-RADON-0004"]`。
  两个 Radon Pointer 都解析到同一真实记录。
- GT-5 / GT-6 是项目级 Finding：`file_path=None`、`start_line=None`、
  `end_line=None`，未伪造文件或行号；证据分别指向 `test_report.json#/counts`
  与 `test_report.json#/coverage`。
- GT-4 / GT-7 由受控 Fake LLM 在 Agent 级检出，因无工具证据，V5 判定为
  `unverified`，不进入五件产物的正式 Finding。该行为是 O-1 与证据规则的预期结果，
  不是检测失败（见 §13、§14）。
- 本次五件产物中共 5 条 Finding，全部为 `verified`；无 critical / high；
  无重复类别与位置；`rejected_findings` 为 0；`external_agent_results` 为 0。

---

## 4. Fixture 构建方式与真实 commit SHA

构建入口：`src/code_review/tools/stage2_fixture.py::build_stage2_fixture_repository()`。

构建步骤：

1. 用 `verify_trusted_fixture()` 校验源 Fixture 的名称、版本、文件集合与逐文件 SHA-256；
2. 复制清单声明的 11 个文件与 `FIXTURE_MANIFEST.json` 到空的临时目录；
3. 对复制后的目录再次执行清单校验；
4. 以固定环境执行真实 Git：
   - `GIT_CONFIG_NOSYSTEM=1`、`GIT_CONFIG_GLOBAL=os.devnull`、`GIT_ATTR_NOSYSTEM=1`；
   - 固定作者/提交者 `Stage 2 Fixture Builder <stage2-fixture@example.invalid>`；
   - 固定提交时间 `2026-01-01T00:00:00+0000`；
   - 固定提交消息 `stage2 sample fixture`；
   - `git init --initial-branch=main --object-format=sha1`；
   - `git add --all`、`git commit --no-verify`；
   - `git rev-parse --verify HEAD^{commit}` 读取真实 SHA；
5. 断言分支为 `main`、`git status --porcelain` 为空、提交后文件哈希仍与清单一致；
6. 构建失败时清理本次新建的目录并显式抛出 `Stage2FixtureBuildError`。

实际结果：

| 项目 | 值 |
| --- | --- |
| commit SHA | `9513a3a0e4d56e0d1f53cecb936cb211cd306c7c` |
| Fixture 名称 / 版本 | `stage2_sample_repo_v1` / `1.0.0` |
| 清单 SHA-256 | `86929343d104daa7b674e1b0bace74585a8e19818bbd53a156bbcb69ab4fb6bf` |
| 声明文件数 | 11 |
| Git 版本 | `git version 2.49.0.windows.1` |
| Python | 3.12.16 |
| 平台 | Windows-11-10.0.26100-SP0 |

该 SHA 由真实 `git commit` 产生，并通过 `git cat-file -t` 验证对象类型为 `commit`；
没有伪造、硬编码或用文件哈希模拟 commit SHA。

---

## 5. 重复 SHA 一致性证据

独立探针在同一平台连续构建两个临时仓库：

```
SHA-A: 9513a3a0e4d56e0d1f53cecb936cb211cd306c7c
SHA-B: 9513a3a0e4d56e0d1f53cecb936cb211cd306c7c
SHA-EQUAL: True
```

测试 `test_fixture_commit_sha_is_repeatable_and_backed_by_git` 同时验证：

- 两次构建 SHA 完全相同，且匹配 `[0-9a-f]{40}`；
- `git rev-parse --verify HEAD^{commit}` 与构建返回值一致；
- `git cat-file -t <sha>` 返回 `commit`；
- `git status --porcelain` 为空；
- 作者、提交者、提交时间、提交消息为固定值；
- 两个仓库的 `fixture_manifest_sha256` 与逐文件哈希完全一致；
- 清单 SHA-256 与磁盘文件实际哈希一致；
- 源 Fixture 仍通过 `verify_trusted_fixture()`，其清单哈希与构建结果一致。

说明：SHA 的稳定性依赖于 Git 版本与固定提交元数据；本报告记录了实际 Git 版本。
若更换 Git 实现或提交规范化行为，需要重新记录基线。

---

## 6. 四个 Agent 执行结果

本次运行（review_id `stage2-20261113T061540Z-0dfd41c7`）：

| Agent | 状态 | Finding 数 | 维度得分 | `execution_time` |
| --- | --- | --- | --- | --- |
| SecurityAgent | completed | 2（B107 low、B608 medium） | 93.0 | 0.6148 s |
| QualityAgent | completed | 1（Radon `high_complexity`，含 2 条证据） | 95.0 | 0.5781 s |
| PerformanceAgent | completed | 1（Radon，去重后并入 Quality） | 100.0 | 0.5837 s |
| TestingAgent | completed | 2（`test_failure`、`low_coverage`） | 90.0 | 2.0044 s |

共同结果：

- 4 个任务全部 `completed`，`failed_tasks=0`、`partial_tasks=0`、`cancelled_tasks=0`；
- `max_retries=0`，未发生重试；
- 所有 AgentResult 的 `score` 为 `None`（维度得分由 Final Reviewer 统一计算）；
- 所有 Agent 级 Finding 在进入 Final Reviewer 前均为 `unverified`；
- PerformanceAgent 的 `PERF-RADON-0004` 被去重合并，未产生第二条正式 Finding；
  Performance 维度因此为 100.0。

失败语义另由 `test_failed_agent_result_is_retained_in_report_and_artifacts` 验证：
Bandit 工具抛错时，SecurityAgent 返回 `failed` + `tool_execution_error`，
Final Reviewer 保留该 failed AgentResult，报告为 `partial` / `COMMENT`，
五件产物仍完整写出。该测试不改变上面的主路径结果。

---

## 7. 并行时间线

主路径运行日志（同一 review）：

```
14:15:40  manager_plan_ready      4 个 task_id
14:15:40  task_dispatch           security / quality / performance / testing
14:15:40  agent_started × 4       四个 Agent 同一秒启动
14:15:41  QualityAgent finished   0.5781 s
14:15:41  PerformanceAgent finished 0.5837 s
14:15:41  SecurityAgent finished  0.6148 s
14:15:42  TestingAgent finished   2.0044 s
14:15:42  workers_aggregated      completed_tasks=4 duration=2.0060 s
14:15:42  final_review_completed  findings=5 score=94.3 verdict=APPROVE
14:15:43  report_generated        five artifacts
```

并行证据：

- 四个 Agent 的 `execution_time` 之和为 **3.7809 s**；
- Manager 聚合节点记录的图内墙钟为 **2.0060 s**；
- 3.7809 > 2.0060，说明四个 Agent 存在时间重叠，不是串行执行；
- 图结束到五件产物写盘为 2.0570 s（含报告生成），总耗时为 2.0570 s。

未使用 Checkpointer、重试调度或跨进程 worker；本次为单进程内 LangGraph 并行 fan-out。

---

## 8. Final Reviewer 验证、去重与评分

### 8.1 证据校验

| Finding | 证据类型 | V1～V7 结果 |
| --- | --- | --- |
| `SEC-BANDIT-0000`（B107） | 工具证据 + 代码位置 | verified |
| `SEC-BANDIT-0001`（B608） | 工具证据 + 代码位置 | verified |
| `QUA-RADON-0004` | 工具证据 + 代码位置 | verified |
| `TEST-0001` | 项目级工具证据 `test_report.json#/counts` | verified |
| `TEST-0002` | 项目级工具证据 `test_report.json#/coverage` | verified |
| GT-4（Fake LLM，Agent 级） | 仅代码位置，无工具证据 | `unverified`，V5 |
| GT-7（Fake LLM，Agent 级） | 仅代码位置，无工具证据 | `unverified`，V5 |

V5 的拒绝原因原文：

```
V5: no tool evidence; the code location alone is not sufficient for verification
```

### 8.2 去重

- QualityAgent 的 Radon `high_complexity` 与 PerformanceAgent 的同一 Radon 记录
  被识别为重复；
- 保留 QualityAgent 的 `QUA-RADON-0004`，Performance 侧记录写入
  `merged_from=["PERF-RADON-0004"]`；
- 两个证据 Pointer 均解析到各自的 Radon 原始记录：
  - `static_analysis.json#/agents/quality/tools/radon/findings/4`
  - `static_analysis.json#/agents/performance/tools/radon/findings/4`
- 无其他重复；`rejected_findings` 为 0。

### 8.3 评分

扣分来自 `config/review_rules.yaml`：

| 维度 | 配置权重 | 扣分明细 | 维度得分 |
| --- | --- | --- | --- |
| security | 0.35 | medium 5 + low 2 | 93.0 |
| quality | 0.25 | medium 5 | 95.0 |
| performance | 0.20 | 无 | 100.0 |
| testing | 0.20 | medium 5 × 2 | 90.0 |

综合分：

```
93.0×0.35 + 95.0×0.25 + 100.0×0.20 + 90.0×0.20 = 94.3
```

结论：

- `overall_score = 94.3`，`overall_verdict = APPROVE`；
- 报告状态 `completed`；无已核验 critical / high；
- 无失败维度，未触发 partial 降级；
- 报告中的 `DimensionScore.weight` 保存配置值 0.35 / 0.25 / 0.20 / 0.20，
  未因计算而改写。

AC-2-12（已核验 critical 直接 `REQUEST_CHANGES`）使用 Stage 2.4 既有单元测试单独
验证，未通过人为拔高本 Fixture 的 severity 来制造 critical：

- `tests/unit/test_final_reviewer.py::test_verified_critical_blocks_in_every_dimension`
- `tests/unit/test_scoring.py::test_verified_critical_forces_request_changes`
- `tests/unit/test_report_schema.py::test_verified_critical_requires_request_changes_RP_06`

上述用例共 6 个参数化用例，全部通过。

---

## 9. 五件报告产物

产物路径模式（由 `ReviewService` / `Stage2ReportGenerator` 生成）：

| 产物 | 路径 | 本次大小 |
| --- | --- | --- |
| 元数据 | `reports/<review_id>/metadata.json` | 1695 B |
| 静态分析 | `reports/<review_id>/static_analysis.json` | 46499 B |
| 测试报告 | `reports/<review_id>/test_report.json` | 4549 B |
| 结构化报告 | `reports/<review_id>/report.json` | 16798 B |
| Markdown 报告 | `reports/<review_id>/report.md` | 4518 B |

Stage 2.6 E2E 在隔离的临时输出目录中生成并校验这些产物，测试结束后与工作区一并
清理；仓库内未保留临时产物。实际业务入口（CLI / `ReviewService`）写入
`reports/<review_id>/`。

验证结果：

- `metadata.json`：`Stage2MetadataArtifact` 校验通过，`stage="stage_2"`、
  `source_type="trusted_fixture"`、`repository_url=fixture://stage2_sample_repo_v1`、
  `commit_sha` 为 40 位真实 SHA、`review_status="completed"`、
  `discovered_file_count=12`、`analyzed_file_count=6`（仅 Python 源文件）、
  工具版本齐全、时间为 UTC；
- `static_analysis.json`：`Stage2StaticAnalysisArtifact` 校验通过，
  四个 Agent key 完整；磁盘 JSON 与内存 `ArtifactData.static_analysis`
  **逐字段完全相等**；
- `test_report.json`：`Stage2TestReportArtifact` 校验通过；磁盘 JSON 与内存
  `ArtifactData.test_report` **逐字段完全相等**；`read_only_verified=True`、
  `modified_paths=[]`；
- `report.json`：可通过冻结的 `ReviewReport.model_validate_json()` 反序列化，
  且与内存中的 `ReviewReport` 相等；四个维度 key 完整；
- `report.md`：从同一 `ReviewReport` 渲染；Review ID、Commit SHA、报告状态、
  结论、综合分、四维权重、Finding 类别、测试计数与覆盖率均与 JSON 一致；
  JSON 中 coverage 为 `40.48`，Markdown 显示 `40.5%`，JSON 中总分 `94.3`，
  Markdown 显示 `94.3`；
- 6 个证据 Pointer 在内存与落盘 JSON 中解析到完全相同的记录；
- 敏感信息：五件产物中均未出现 Fixture 的演示密码原文、绝对工作区路径或用户主目录
  路径；Bandit 的密码消息已显示为 `[REDACTED]`；
- 失败 Agent 场景：`report.json.agent_results.security.status="failed"`、
  `error.error_type="tool_execution_error"`、`dimension_scores.security.score=null`，
  `static_analysis.json` 中 security 的 `result_status="failed"` 且 Bandit
  `execution_status="failed"`；五件产物仍完整。

---

## 10. Precision、Recall、FDR 与耗时基线

Ground Truth 共 7 项。以“类别 + 文件 + 起始行”匹配（项目级 Finding 只匹配类别）：

| 指标 | 值 | 说明 |
| --- | --- | --- |
| TP | 5 | GT-1、GT-2、GT-3、GT-5、GT-6 |
| FP | 0 | 所有正式 Finding 都对应 Ground Truth |
| FN | 2 | GT-4、GT-7（仅 Fake LLM 检出，未进入五件产物） |
| Precision | 1.0 | `TP / (TP + FP)`，分母 5 |
| Recall | 0.714285714… | `TP / (TP + FN)` = 5/7 |
| False Discovery Rate（FDR） | 0.0 | `FP / (TP + FP)`，明确为**错误发现率**，不是 FP rate |

分母为 0 时返回 `null`，不伪造 0：测试同时验证 `_safe_ratio(0, 0) is None`。
以上指标只记录实测值，不设通过阈值。

耗时基线（同一次运行）：

| 指标 | 值 |
| --- | --- |
| 四维图墙钟（`execution_summary.duration_seconds`） | 2.0060 s |
| 服务总耗时（含五件产物生成，`outcome.duration_seconds`） | 2.0570 s |
| SecurityAgent `execution_time` | 0.6148 s |
| QualityAgent `execution_time` | 0.5781 s |
| PerformanceAgent `execution_time` | 0.5837 s |
| TestingAgent `execution_time` | 2.0044 s |
| 四 Agent 时间之和 | 3.7809 s |

耗时随机器负载波动，本报告只记录本次实测值，不作为阈值。

---

## 11. Stage 1 全量回归结果

命令与真实结果：

```text
pytest tests/integration/test_stage2_e2e.py -q
13 passed in 16.42s

pytest tests/unit -q
1286 passed, 5 skipped in 24.75s

pytest -q
1316 passed, 9 skipped in 45.27s
```

补充证据：

```text
pytest tests/unit/test_test_runner.py -q -k "coverage or timeout or crash or error"
8 passed, 16 deselected in 1.69s

pytest 三个 verified-critical 用例
6 passed in 2.93s
```

结论：

- 全量 0 failure、0 error；
- Stage 1 测试全部保留并通过（CLI、API、报告、可信 Fixture、LLM 分析等）；
- 9 个 skip 全部为既有跳过，无新增 skip：
  - 1 个真实 LLM Smoke（未设置 `RUN_LLM_SMOKE=1`）；
  - 3 个真实网络测试（未设置 `RUN_REAL_NETWORK=1`）；
  - 5 个符号链接测试（当前 Windows 用户不允许创建符号链接）。

---

## 12. 依赖锁文件与探针结果

### 12.1 锁文件

- `environment.lock.stage2.yml` 于 2026-11-13 由
  `conda env export -n multi-agent-review --no-builds` 重新生成，并移除 `prefix` 行；
- Stage 1 `environment.lock.yml` 未修改（`git diff` 为空）；
- 记录的关键版本：

| 组件 | 版本 |
| --- | --- |
| Python | 3.12.16 |
| langgraph | 1.2.19 |
| langgraph-checkpoint | 4.3.1 |
| langgraph-prebuilt | 1.1.1 |
| langgraph-sdk | 0.4.14 |
| langchain-core | 1.8.0 |
| langchain-protocol | 被动依赖（随 langchain-core） |
| langsmith | 0.14.17 |

### 12.2 依赖探针

```text
FORBIDDEN: []
PASSIVE-ALLOWED: ['langchain-core', 'langchain-protocol', 'langgraph',
                  'langgraph-checkpoint', 'langgraph-prebuilt', 'langgraph-sdk',
                  'langsmith', 'opentelemetry-api']
TRACING-ENV: none
SOURCE-HITS: none
```

- 未安装 Redis、ARQ、SQLAlchemy/asyncpg/psycopg、MCP SDK、A2A SDK、Streamlit、
  `langchain-openai`、`opentelemetry-sdk`；
- `langsmith` 仅作为 langgraph 的被动依赖存在；
- `LANGCHAIN_TRACING*`、`LANGSMITH_TRACING*`、`LANGCHAIN_API_KEY`、
  `LANGSMITH_API_KEY` 均未设置；
- `src/` 中无 `import langsmith`、`langchain_core`、`langchain_openai`，
  也无 tracing 环境变量读取；
- 未创建 LangSmith client，未发生网络上报；
- LangGraph 图未配置 Checkpointer。

`opentelemetry-api` 是 FastAPI 的既有被动依赖，属于允许项。

---

## 13. O-1 未解决事项

O-1 结论：**仍未解决，且本阶段按裁定不解决**。

事实与边界：

1. 冻结的 `CostSummary` 无法表达“成本未知”。Stage 2.6 未修改 Schema；
2. 默认评审路径不注入 LLM（`llm_client=None`），实际 LLM 调用为 0，
   Token 为 0，`estimated_cost=0` 是真实值，不是伪造；
3. 受控 Fake LLM 的 Agent 级测试记录：
   - `llm_calls=1`；
   - `reported_usage_calls=0`；
   - `input_tokens=0`、`output_tokens=0`；
4. 用 Fake LLM 跑完整图时，Final Reviewer 在构造 `CostSummary` 前抛出：

   ```text
   FinalReviewError: real LLM usage cannot be represented as zero cost in
   CostSummary; cost semantics are deferred to the approved real-LLM smoke
   ```

   因此 Fake LLM 完整图不会写出五件产物；该守卫测试断言异常包含 `zero cost`，
   且未创建报告目录。
5. 本阶段未执行真实 LLM Smoke，也未宣称任何真实 `CostSummary` 验收通过；
6. 真实 LLM Smoke 如后续执行，必须单独批准、单独记录真实 Token usage，
   不得把未知成本填 0，且需先裁定 O-1 的成本语义。

这是 Stage 2.6 的**已知条件**，不是测试失败；但它意味着“带 LLM Finding 的完整
五件产物”尚不可验收。

---

## 14. 未完成项与风险

| 项目 | 状态 / 风险 | 处理 |
| --- | --- | --- |
| GT-4 / GT-7 进入正式报告 | 未完成；仅 Fake LLM Agent 级检出，V5 未核验 | 需 O-1 与证据规则裁定后再设计真实可核验证据 |
| 真实 LLM Smoke | 未执行 | 需负责人单独批准，不纳入默认验收 |
| pytest 成功 + Coverage 失败 | 由 `tests/unit/test_test_runner.py` 的受控假进程覆盖（8 个用例通过）；真实 E2E 只覆盖真实 Coverage 成功 + 真实测试失败 | 若要求真实环境故障注入，需另行批准构造 |
| 外部仓库评审 | Stage 2.6 只使用自有 Fixture | 外部仓库仍只做静态分析，测试 `not_executed` |
| Fixture SHA 可重复性 | 依赖 Git 版本、固定元数据与平台换行属性 | 已记录 Git 2.49.0 / Windows；更换环境需重新记录 |
| Stage 2 运行模型 | 单进程同步、无重试、无 Checkpointer、无可观测性 | 属于 Stage 3/4 范围 |
| `langgraph` 传递依赖 | `langgraph-checkpoint`、`langgraph-prebuilt`、`langchain-core`、`langsmith` 被动存在 | 禁止直接 import / tracing / API Key / 网络上报，已探针验证 |
| 测试基线文档 | `CLAUDE.md` 原基线 1028/1039 已过时 | 已更新为实测 1286/1316 |
| 验收产物留存 | E2E 使用隔离临时目录并清理 | 五件产物路径模式与内容已由测试断言；业务入口写入 `reports/<review_id>/` |

没有发现伪造证据、伪造行号、伪造 SHA 或伪造零成本的情况。

---

## 15. 最终结论

**PASS WITH CONDITIONS**

Stage 2.6 的全部强制验收项均已完成并通过：

- 自有 Fixture 与真实 Git SHA 可重复；
- 四个 Agent 真实工具执行、并行扇出/扇入；
- Final Reviewer 证据校验、去重、四维评分与结论；
- 五件产物完整，内存/落盘一致，Pointer 可解析，敏感信息脱敏；
- GT-1/2/3/5/6 检出且有真实证据，GT-4/7 明确标记未核验；
- Precision 1.0、Recall 5/7、FDR 0.0，无阈值；
- 全量回归 1316 passed / 9 skipped，0 failure / 0 error；
- 依赖探针无阶段外依赖，无 LangSmith tracing；
- Stage 1 锁文件未改，Stage 2 锁文件与实际环境一致。

条件（进入 Stage 3 前需负责人确认接受）：

1. **O-1 保持未解决**：真实 LLM 成本语义未裁定；本阶段没有真实 LLM Smoke，
   也不宣称其 `CostSummary` 通过。任何 LLM 调用（真实或 Fake）都会阻止五件产物生成。
2. **GT-4 / GT-7 仍为未核验**：五件产物路径的 Recall 基线为 5/7；这两项仅能由
   Fake LLM 在 Agent 级检出，尚不能进入正式报告。
3. **Coverage 失败分支**由既有受控假进程单元测试覆盖，不是真实 Coverage 环境故障；
   真实路径只验证了 Coverage 成功与真实测试失败。
4. Stage 2 仍为单进程同步执行，无重试、无 Checkpointer、无可观测性接入；
   这些属于后续阶段。

建议：在负责人接受上述条件、并确认 O-1 继续延后的前提下，可以进入 Stage 3；
否则应先裁定 O-1 与 GT-4/GT-7 的验收口径。

---

## 附：Stage 2.6 测试命令索引

```text
# Stage 2.6 专项
pytest tests/integration/test_stage2_e2e.py -q

# 全量回归
pytest tests/unit -q
pytest -q

# 依赖探针（见 §12 输出）
python -c "<FORBIDDEN / PASSIVE-ALLOWED / TRACING-ENV 探针>"

# AC-2-12（不依赖本 Fixture 的 severity）
pytest tests/unit/test_final_reviewer.py::test_verified_critical_blocks_in_every_dimension \
       tests/unit/test_scoring.py::test_verified_critical_forces_request_changes \
       tests/unit/test_report_schema.py::test_verified_critical_requires_request_changes_RP_06 -q

# Coverage / 错误路径
pytest tests/unit/test_test_runner.py -q -k "coverage or timeout or crash or error"
```
