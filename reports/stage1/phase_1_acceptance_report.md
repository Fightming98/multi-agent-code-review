# 阶段 1 全链路验收报告

- 报告版本：v1.0
- 生成日期：2026-11-10
- 验收范围：Stage 1.1～Stage 1.7
- 验收对象：`multi-agent-review` 阶段 1 单 Agent 工程基础
- 最终结论：**PASS**
- 说明：本报告是 Stage 1.7 的测试与证据记录。Stage 1.7 尚未提交，是否验收通过、是否进入阶段 2 由项目负责人确认。

---

## 1. 阶段 1 目标

阶段 1 的目标是在不引入多 Agent、LangGraph、Redis/ARQ、MCP、A2A 的前提下，建立可真实运行的代码审查地基：

- 安全获取 GitHub 仓库并固定完整 Commit SHA；
- 扫描仓库、识别 Python 源码并过滤敏感/超大/二进制文件；
- 接入 Ruff、Bandit、Radon 产生确定性证据；
- 仅对项目自维护的可信 Fixture 执行 Pytest/Coverage；
- 由 LLM 解释已有证据并补充语义问题，但不替代工具证据；
- 由唯一业务入口 `ReviewService` 编排完整流程；
- CLI 与 FastAPI 共用同一套审查逻辑；
- 生成 `metadata.json`、`static_analysis.json`、`test_report.json`、`report.md` 四件产物。

阶段 1 不实现阶段 2 的多 Agent、Final Reviewer、`ReviewReport` 四维评分，也不生成 `report.json`。

---

## 2. 实际完成范围

| 能力 | 状态 | 主要实现 |
| --- | --- | --- |
| GitHub URL 安全校验 | 已完成 | `src/code_review/tools/url_validator.py` |
| Git Clone、Commit SHA 固定、资源限制、清理 | 已完成 | `src/code_review/tools/repository_manager.py` |
| 仓库遍历、源码识别、统计 | 已完成 | `src/code_review/tools/repository_inspector.py` |
| 文件类型/敏感文件/二进制/大文件过滤 | 已完成 | `src/code_review/tools/file_filters.py` |
| 进程执行、超时、输出上限 | 已完成 | `src/code_review/tools/process_runner.py` |
| Ruff / Bandit / Radon 结构化接入 | 已完成 | `tools/ruff_tool.py`、`tools/bandit_tool.py`、`tools/radon_tool.py` |
| 可信 Fixture 校验与只读保护 | 已完成 | `tools/trusted_fixture.py`、`tools/workspace_snapshot.py` |
| Pytest / Coverage 受控执行 | 已完成 | `tools/test_runner.py` |
| Finding 聚合、去重、ID 对账 | 已完成 | `services/finding_aggregator.py` |
| 证据合同校验 | 已完成 | `services/evidence_validator.py` |
| 非 Agent LLM 辅助分析 | 已完成 | `services/llm_analyzer.py`、`services/llm_client.py` |
| 统一审查服务 | 已完成 | `services/review_service.py` |
| 阶段 1 Artifact Schema 与报告生成 | 已完成 | `reporting/artifact_models.py`、`reporting/report_generator.py` |
| Markdown 渲染 | 已完成 | `reporting/markdown_renderer.py` |
| CLI | 已完成 | `src/code_review/cli.py` |
| FastAPI 同步入口 | 已完成 | `src/code_review/api/app.py` |

---

## 3. 目录结构

```text
multi-agent-review/
├── config/
│   └── settings.py
├── src/code_review/
│   ├── api/
│   │   └── app.py
│   ├── reporting/
│   │   ├── artifact_models.py
│   │   ├── markdown_renderer.py
│   │   └── report_generator.py
│   ├── schemas/
│   │   ├── report.py
│   │   ├── result.py
│   │   └── task.py
│   ├── services/
│   │   ├── evidence_validator.py
│   │   ├── finding_aggregator.py
│   │   ├── llm_analyzer.py
│   │   ├── llm_client.py
│   │   ├── redaction.py
│   │   └── review_service.py
│   ├── tools/
│   │   ├── bandit_tool.py
│   │   ├── base.py
│   │   ├── file_filters.py
│   │   ├── process_runner.py
│   │   ├── radon_tool.py
│   │   ├── repository_inspector.py
│   │   ├── repository_manager.py
│   │   ├── ruff_tool.py
│   │   ├── test_runner.py
│   │   ├── trusted_fixture.py
│   │   ├── url_validator.py
│   │   └── workspace_snapshot.py
│   └── cli.py
├── tests/
│   ├── fixtures/trusted_repo/
│   │   ├── FIXTURE_MANIFEST.json
│   │   ├── README.md
│   │   ├── calc/
│   │   └── tests/
│   ├── integration/
│   ├── unit/
│   ├── fixture_factory.py
│   └── stage1_helpers.py
├── docs/
├── environment.yml
├── pytest.ini
└── README.md
```

未创建 `agents/`、`graph/`、`orchestration/`、`workers/`、`mcp/`、`a2a/` 等后续阶段目录。

---

## 4. 组件实现情况

| 组件 | 实现要点 | 验证 |
| --- | --- | --- |
| URL Validator | 仅允许 `https://github.com/<owner>/<repo>`；拒绝 HTTP、非 GitHub 域名、带凭据、非常规端口、本地路径、`file://`、路径穿越 | `tests/unit/test_url_validator.py`；手工恶意 URL 探针 |
| Repository Manager | Clone 超时、仓库大小监控、文件数限制、固定完整 SHA、失败清理 | `tests/unit/test_repository_manager.py`；3 条真实网络测试 |
| Repository Inspector | POSIX 相对路径、语言、行数、大小、二进制/敏感/大文件过滤、符号链接逃逸防护 | `tests/unit/test_repository_inspector.py`、`test_file_filters.py` |
| AnalysisTool | 统一工具结果、执行状态、超时、stdout/stderr 截断、Finding 上限 | `tests/unit/test_tool_base.py`、`test_process_runner.py` |
| Ruff / Bandit / Radon | 调用真实工具、解析结构化输出、映射严重度与类别 | 三个工具各自单元测试；真实整仓扫描 |
| Trusted Fixture | 固定根目录、SHA-256 清单、路径/符号链接校验、只读快照 | `tests/unit/test_trusted_fixture.py`；`tests/integration/test_trusted_fixture_execution.py` |
| Test Runner | 仅可信 Fixture 执行；Pytest/Coverage 超时；执行后检测工作区变更；外部仓库固定 `not_executed` | `tests/unit/test_test_runner.py`；集成测试 |
| Finding Aggregator | 确定性 Finding 优先、跨工具去重、证据引用、ID 对账、LLM 提案校验/拒绝记录 | `tests/unit/test_finding_aggregator.py`、`test_evidence_validator.py` |
| LLM Analyzer | OpenAI 兼容客户端、分块调用、全局提案上限、all-or-nothing 失败、usage 汇总 | `tests/unit/test_llm_analyzer.py`、`test_llm_client.py`；真实冒烟 |
| ReviewService | 唯一业务入口，串联校验、Clone、扫描、工具、测试、聚合、LLM、报告、清理 | `tests/unit/test_review_service.py`；Stage 1.6 集成测试 |
| Report Generator | 三份 JSON Artifact 校验、路径/密钥净化、失败清理、禁止覆盖已有目录 | `tests/unit/test_report_generator.py`、`test_artifact_models.py` |
| Markdown Renderer | 仅从三份已校验模型渲染，12 个固定章节 | `tests/unit/test_markdown_renderer.py` |
| CLI / FastAPI | 只调用 `ReviewService`，不重复工具或聚合逻辑 | `tests/unit/test_cli.py`、`test_api.py`；同源导入测试 |

---

## 5. 依赖变化

阶段 0 的 8 个基础依赖保持不变：

```text
fastapi uvicorn pydantic pydantic-settings python-dotenv pytest httpx structlog
```

阶段 1 新增并固定版本：

| 依赖 | 版本 | 用途 |
| --- | --- | --- |
| ruff | 0.17.4 | 代码质量静态分析 |
| bandit | 1.9.4 | 安全静态分析 |
| radon | 6.0.1 | 复杂度分析 |
| coverage | 7.17.2 | 可信 Fixture 覆盖率 |

未引入 LangGraph、LangChain、Redis、ARQ、PostgreSQL、SQLAlchemy、MCP、A2A、LangSmith、Streamlit 等依赖。

禁止项探测结果：

```text
FORBIDDEN: []
PASSIVE-ALLOWED: ['opentelemetry-api']
```

`opentelemetry-api` 为 FastAPI 被动带入，按 AC-0-05 口径允许。

---

## 6. 安全设计

- **仓库来源**：仅允许 HTTPS `github.com`，拒绝 HTTP、非 GitHub 域名、子域名、非常规端口、带凭据 URL、本地路径、`file://` 与路径穿越。
- **Git 执行**：固定 Git 可执行文件、参数白名单、超时、进程树终止、仓库大小与文件数限制；执行后清理临时工作区。
- **不可信仓库**：外部仓库只在宿主机做静态分析；不执行测试、安装或构建脚本；`test_report.json` 固定 `execution_status="not_executed"` 并写明原因。
- **可信 Fixture 例外**：仅 `tests/fixtures/trusted_repo/` 可由项目维护并人工审查的 Fixture 执行 Pytest/Coverage；使用 SHA-256 清单；不接受任意 URL 提权；不自动安装依赖；不执行 `setup.py`、`build.py` 或安装脚本。
- **只读**：执行前后对工作区做快照比对；检测到修改即判定失败并记录；可信 Fixture 执行要求 `read_only_verified=true`。
- **敏感文件**：`.env`、私钥、凭证等文件在扫描阶段过滤，不进入 LLM 上下文；LLM 只接收经过文件白名单校验的代码片段。
- **输出净化**：报告生成前替换工作区、用户目录、临时目录路径，并脱敏常见密钥/令牌样式；工具 `stdout/stderr` 中的嵌套 JSON 转义路径也会被替换。
- **证据约束**：所有阶段 1 Finding 的 `agent_name="Stage1Analyzer"`、`verification_status="unverified"`；LLM 不合格提案进入 `llm_analysis.rejected[]`，不进入正式 Finding。
- **日志**：结构化日志记录 `review_id`、阶段、工具、状态与耗时；不记录 API Key、`.env` 内容或完整主机路径。

---

## 7. 测试策略

| 层级 | 策略 | 是否联网/真实模型 |
| --- | --- | --- |
| 阶段 0 回归 | 原有 Schema 单元测试全部重跑 | 否 |
| 阶段 1 单元测试 | Mock/Fake/fixtures；覆盖 URL、过滤、解析、聚合、证据、LLM、报告、CLI、API | 否 |
| 离线集成测试 | 真实 Ruff/Bandit/Radon；Fake 仓库管理；Fake LLM；真实可信 Fixture Pytest/Coverage | 否 |
| 真实网络集成测试 | `pallets/itsdangerous` Clone、扫描、静态分析；仅做静态分析，不执行仓库脚本 | 是 |
| 真实 LLM 冒烟 | 单次最小结构化输出与 usage 记录；`llm_smoke` 标记，默认跳过 | 是 |
| 安全测试 | 恶意 URL、路径穿越、敏感文件、超大文件、符号链接/工作区只读 | 否 |
| 真实整仓审查 | CLI 对 `pallets/itsdangerous` 完整执行四件产物生成 | 是（GitHub + LLM） |

真实网络与真实模型测试默认不运行，必须显式设置 `RUN_REAL_NETWORK=1` / `RUN_LLM_SMOKE=1`。

---

## 8. AC-1-01～AC-1-15 逐项验收

| 编号 | 验收项 | 证据 | 结论 |
| --- | --- | --- | --- |
| AC-1-01 | Clone 并固定完整 Commit SHA | `test_clone_real_repository_and_pin_commit` 通过；真实审查 SHA `672971d66a2ef9f85151e53283113f33d642dabd` 写入 `metadata.json`、`static_analysis.json`、`test_report.json` | PASS |
| AC-1-02 | URL 校验与 SSRF/路径穿越防护 | `test_url_validator.py` 全部通过；手工探针拒绝 HTTP、非 GitHub、带凭据、`file://`、本地路径、非常规端口、仿冒域名、路径穿越共 8 类 | PASS |
| AC-1-03 | 仓库大小、文件数、单文件、下载时间限制 | `test_repository_manager.py`、`test_file_filters.py`、`test_settings_stage1.py` 覆盖；超大文件探针被 `oversized` 过滤 | PASS |
| AC-1-04 | 源码识别与路径/语言/行数/大小输出 | `test_repository_inspector.py`；真实审查识别 48 个文件、9 个 Python 源文件、6 个测试文件、15 个分析文件，`.git`/`node_modules` 排除 | PASS |
| AC-1-05 | 敏感文件不进入 LLM 上下文 | `test_stage1_6_review.py` 断言 `.env` 不在 `allowed_files` 且密钥值不出现在产物；手工探针 `.env`、`secrets/id_rsa` 均被 `sensitive` 过滤 | PASS |
| AC-1-06 | Ruff 结构化结果 | `test_ruff_tool.py`；真实审查 Ruff 17 条 Finding，工具状态 `findings` | PASS |
| AC-1-07 | Bandit 结构化结果 | `test_bandit_tool.py`；真实审查 Bandit 68 条 Finding，工具状态 `findings` | PASS |
| AC-1-08 | Radon 结构化结果 | `test_radon_tool.py`；真实审查 Radon 155 条 Finding，工具状态 `findings` | PASS |
| AC-1-09 | 可信 Fixture Pytest/Coverage | `test_real_trusted_fixture_executes_with_coverage`、`test_trusted_fixture_review_executes_tests_and_marks_source` 通过；断言 `executed`、覆盖率非空、`read_only_verified=true` | PASS |
| AC-1-10 | 外部仓库不执行测试/安装/构建 | `test_external_repository_review_generates_four_artifacts_without_execution` 通过；真实审查 `not_executed`，原因写明无沙箱；断言无 `__pycache__`、`.pytest_cache`、`.pyc` | PASS |
| AC-1-11 | 工具超时与输出/资源限制 | `test_process_runner.py`、`test_tool_base.py` 覆盖超时、stdout/stderr 截断、Finding 上限；`test_settings_stage1.py` 校验阈值集中配置 | PASS |
| AC-1-12 | 工作区只读，不修改原始代码 | `test_workspace_snapshot.py`、`test_test_runner.py`、`test_trusted_fixture.py`；`test_workspace_mutation_is_detected` 通过；真实审查外部仓库不执行 | PASS |
| AC-1-13 | LLM 仅解释证据，提案需满足证据合同 | `test_llm_analyzer.py`、`test_evidence_validator.py`、`test_finding_aggregator.py`；真实审查 90 条确定性 + 1 条语义 Finding，49 条提案接受、1 条拒绝并记录原因 | PASS |
| AC-1-14 | CLI 与 FastAPI 共用 `ReviewService` | `test_cli_and_api_import_the_same_review_service` 通过；`test_cli.py`、`test_api.py`；CLI/API 源码不包含 Ruff/Bandit/Radon/聚合/LLM 实现 | PASS |
| AC-1-15 | 四件产物、Artifact Schema、Markdown 由结构化数据渲染 | `test_generate_writes_exactly_four_artifacts`、`test_artifact_models.py`、`test_markdown_renderer.py`；真实产物三份 JSON 均通过专用模型校验，`report.json` 不存在，`report.md` 12 个章节 | PASS |

---

## 9. TC-1-01～TC-1-06 逐项验收

| 编号 | 验收项 | 证据 | 结论 |
| --- | --- | --- | --- |
| TC-1-01 | 阶段 0 全部测试回归 | `204 passed`，0 failure/error/skip/xfail | PASS |
| TC-1-02 | URL/文件收集/过滤/工具解析单元测试；不联网、不调用真实 LLM | 全量单元测试 `820 passed, 4 skipped`；真实网络与 LLM 用例均由 marker + 环境变量隔离 | PASS |
| TC-1-03 | 自己编写的可信测试仓库集成测试，覆盖阶段 1 链路 | 可信 Fixture `trusted_fixture_v1` 集成执行 Pytest/Coverage；外部仓库 Fake Clone 集成生成四件产物；真实 Clone 由 TC-1-04 补充 | PASS |
| TC-1-04 | 一次真实 GitHub Clone 验证，记录 Commit SHA 与输出 | 真实网络测试 `3 passed`；真实审查 Clone `pallets/itsdangerous@main`，SHA `672971d66a2ef9f85151e53283113f33d642dabd`；`test_real_clone.py` 断言 `.git/HEAD` 与 SHA 一致 | PASS |
| TC-1-05 | 恶意 URL、路径穿越、敏感文件、超大文件安全用例 | 安全相关单元测试 `338 passed, 4 skipped`；8 类恶意 URL 全部拒绝；`.env`/私钥过滤；超大文件过滤；`.git`/`node_modules` 排除 | PASS |
| TC-1-06 | 一次真实模型调用冒烟，记录模型名与 usage，单独标记 | `RUN_LLM_SMOKE=1` 下 `1 passed`；模型 `deepseek-ai/DeepSeek-V3`，usage `prompt=39, completion=15, total=54`，延迟 1,483 ms；默认单元测试不包含该用例 | PASS |

TC-1-06 已真实执行并取得合法 API Key 配置，因此不适用 `BLOCKED / NOT RUN`；阶段 1 整体不存在因环境缺失导致的 BLOCKED 项。

---

## 10. 测试总数

| 范围 | 收集 | 通过 | 失败 | 错误 | 跳过 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 阶段 0 回归 | 204 | 204 | 0 | 0 | 0 |
| 阶段 1 单元测试 | 620 | 616 | 0 | 0 | 4 |
| 阶段 1 集成测试 | 15 | 15 | 0 | 0 | 0 |
| 阶段 1 新增合计 | 635 | 631 | 0 | 0 | 4 |
| 全量单元测试（阶段 0 + 1） | 824 | 820 | 0 | 0 | 4 |
| 项目唯一用例合计 | 839 | 835 | 0 | 0 | 4 |

补充说明：

- 离线集成运行结果为 `11 passed, 4 deselected`；4 条被取消选择的用例分别是 3 条 `real_network` 与 1 条 `llm_smoke`，属于显式门控，不是失败。
- 开启 `RUN_REAL_NETWORK=1 RUN_LLM_SMOKE=1` 后，集成测试为 `15 passed`。
- 安全相关 10 个单元测试文件运行结果为 `338 passed, 4 skipped`，该集合与全量单元测试重叠，不计入总数。
- 4 条跳过均为 Windows 宿主机符号链接限制，原因明确为 `symlinks are not available on this platform` 或 `symbolic links are not permitted on this host`，与阶段 1 功能无关。

---

## 11. 测试通过、失败、跳过数量

- 通过：**835**
- 失败：**0**
- 错误：**0**
- 跳过：**4**（Windows 符号链接平台限制，均有明确原因）
- xfail：**0**
- 未解释的失败/错误/跳过：**0**

阶段 1 单元测试与集成测试没有未解释的失败、错误或跳过。

---

## 12. 真实 GitHub Clone 证据

### 12.1 自动化测试

```text
RUN_REAL_NETWORK=1 pytest tests/integration -q -m real_network
3 passed, 12 deselected in 14.09s
```

覆盖：

- `test_clone_real_repository_and_pin_commit`：Clone `pallets/itsdangerous@main`，断言完整 40 位 SHA、`.git/HEAD` 与 SHA 一致，并按固定 SHA 再次 Clone 验证可复现。
- `test_inspect_real_repository`：真实扫描文件元数据。
- `test_real_repository_static_analysis`：真实 Ruff/Bandit/Radon 静态分析。

### 12.2 真实整仓审查

```text
review_id      : stage1-20261110T120331Z-d8333a8c
仓库           : pallets/itsdangerous
分支           : main
Commit SHA     : 672971d66a2ef9f85151e53283113f33d642dabd
审查状态       : completed
Finding 数量   : 91
严重度分布     : high=2, medium=4, low=85
测试状态       : not_executed
LLM 分析状态   : completed
耗时           : 93.18 秒
报告目录       : reports/stage1-20261110T120331Z-d8333a8c/
```

Commit SHA 同时写入 `metadata.json`、`static_analysis.json`、`test_report.json`。外部仓库测试状态为 `not_executed`，未执行任何仓库脚本。

---

## 13. 工具版本

| 工具/运行时 | 版本 |
| --- | --- |
| Python | 3.12.16 |
| Git | 2.49.0.windows.1 |
| pytest | 9.2.0 |
| Ruff | 0.17.4 |
| Bandit | 1.9.4 |
| Radon | 6.0.1 |
| Coverage.py | 7.17.2 |
| FastAPI | 0.162.2 |
| Pydantic | 2.14.3 |
| pydantic-settings | 2.16.2 |
| httpx | 0.28.1 |
| structlog | 26.1.0 |
| uvicorn | 0.54.0 |
| python-dotenv | 1.2.4 |
| LLM Provider 模型 | `deepseek-ai/DeepSeek-V3` |

真实外部仓库审查的 `metadata.json` 中 `pytest` 与 `coverage` 为 `null`，因为外部仓库测试未执行；可信 Fixture 执行时会记录真实版本与覆盖率。

---

## 14. 四件产物样例及验证结果

样例目录：`reports/stage1-20261110T120331Z-d8333a8c/`

| 文件 | 大小（字节） | SHA-256 |
| --- | ---: | --- |
| `metadata.json` | 1,249 | `5c9b0041e8c3bc143472a5ba574806bea583e0b8d74b26357720f850bf4bfa55` |
| `static_analysis.json` | 397,581 | `253492949299906bcf803f62943ce5e697a806ab618d095d3f88a8e166a9e269` |
| `test_report.json` | 1,149 | `11e1a128df2306af52e922311dd862e001733bc621d0a0029381bc91268ce733` |
| `report.md` | 21,876 | `3aeabdb7e3ff9570bf083570774ab34cd7b9c63b36daa75efc07163321561a9f` |

验证结果：

- 目录中恰好四件产物，`report.json` 不存在。
- `metadata.json` 通过 `MetadataArtifact` 校验。
- `static_analysis.json` 通过 `StaticAnalysisArtifact` 校验。
- `test_report.json` 通过 `TestReportArtifact` 校验。
- 三份 JSON 的 `review_id` 一致。
- `test_report.json`：`execution_status="not_executed"`、`trusted_fixture=false`、`data_source="external_repository"`，`counts` 与覆盖率均为 `null`，原因写明外部仓库无沙箱不执行测试。
- `static_analysis.json`：Ruff 17 条、Bandit 68 条、Radon 155 条原始 Finding；240 条源 Finding → 91 条映射 → 90 条确定性 + 1 条语义；1 条重复、149 条跳过。
- 所有 91 条 Finding 的 `agent_name` 均为 `Stage1Analyzer`，`verification_status` 均为 `unverified`。
- LLM 分析：`completed`，4 次调用，usage `prompt=15,900 / completion=2,900 / total=18,800`，49 条提案接受、1 条拒绝并记录原因。
- `report.md` 包含 12 个固定章节，内容由三份结构化数据渲染。
- 产物中未检出主机路径、工作区临时路径或 `sk-` 样式密钥。

说明：该样例为本地真实运行产物，包含第三方仓库的代码片段与工具原始输出；按项目规则不纳入 Git 提交，以上哈希可用于复核。

---

## 15. 真实模型调用状态

### 15.1 冒烟测试

```text
LLM_SMOKE configured_model=deepseek-ai/DeepSeek-V3
response_model=deepseek-ai/DeepSeek-V3
finish_reason=stop
usage={'prompt_tokens': 39, 'completion_tokens': 15, 'total_tokens': 54}
latency_ms=1483
1 passed in 2.01s
```

该用例标记为 `llm_smoke`，默认不进入单元测试；只有 `RUN_LLM_SMOKE=1` 且配置了 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` 时才运行。

### 15.2 真实整仓审查中的 LLM

- Provider：SiliconFlow（OpenAI 兼容接口）
- 模型：`deepseek-ai/DeepSeek-V3`
- 状态：`completed`
- 调用次数：4（按 Finding 分块）
- 总用量：18,800 tokens
- LLM 耗时：91,535 ms
- 提案：50 条；接受 49 条；拒绝 1 条（`unsupported or missing category`）
- 截断：输入/输出均未截断

结论：TC-1-06 已真实执行，不存在 `BLOCKED / NOT RUN`。

---

## 16. 阶段 0 回归

```text
pytest tests/unit/test_task_schema.py tests/unit/test_result_schema.py tests/unit/test_report_schema.py -q
204 passed in 0.53s
```

- 阶段 0 的 204 条测试全部通过。
- `src/code_review/schemas/task.py`、`result.py`、`report.py` 在 Stage 1.7 期间未修改；`git diff a7d384d -- src/code_review/schemas` 为空。
- 阶段 0 的数据合同、枚举、时间、路径、评分与报告语义未被放宽。
- 阶段 1 仅在测试文件中把导入根统一为顶层 `code_review`，不修改断言语义。

---

## 17. 与 architecture.md 的一致性

| 架构要求 | 实际实现 | 结论 |
| --- | --- | --- |
| `schemas` 不依赖业务模块 | 三个 Schema 仅依赖 Pydantic/stdlib | 一致 |
| `tools` 提供确定性证据 | Ruff/Bandit/Radon/Pytest/Coverage 封装在 `tools/` | 一致 |
| `agents/` 属于阶段 2 | 未创建 `agents/` | 一致 |
| `graph/` 属于阶段 2 及以后 | 未创建 `graph/`，未引入 LangGraph | 一致 |
| `ReviewService` 是唯一业务入口 | CLI 与 FastAPI 只调用 `services/review_service.py` | 一致 |
| 阶段 1 非 Agent LLM 分析放在 `services/llm_analyzer.py` | 已按 §8.1 实现 | 一致 |
| 阶段 1 只生成四件产物 | 未生成 `report.json`，未生成 `ReviewReport` | 一致 |
| 报告目录固定 `reports/<review_id>/` | 由 `review_output_root` 配置，默认 `reports` | 一致 |
| 不提前实现 MCP/A2A/Redis/ARQ | 依赖探测为空，未创建对应目录 | 一致 |
| 不修改五份核心文档 | 本次仅更新 README 与验收报告；`docs/` 无改动 | 一致 |

组件路径与 `docs/architecture.md` §7.1.1 的映射逐项一致。

---

## 18. 未解决问题

### 18.1 Stage 1.7 期间已修正

1. **测试导入根不一致**：Stage 1.6 提交的集成测试使用 `src.code_review.*`，生产模块内部使用顶层 `code_review.*`，导致 `ReviewService` / `ToolExecutionResult` 出现两个类身份，`test_stage1_6_review.py` 单独运行时 3 条失败（`partial` 而非 `completed`）。已将 `tests/` 下 33 个文件的导入统一为顶层 `code_review.*`，并重新排序受影响的 import；修复后该文件 `3 passed`，全量矩阵重新通过。
2. **嵌套工具输出中的主机路径泄漏**：真实 `static_analysis.json` 的工具 `stdout` 是嵌套 JSON 字符串，Windows 路径在产物中被二次转义，原净化逻辑只匹配单反斜杠形式，导致用户目录与临时目录路径残留。已扩展 `_sanitize_text` 处理多层转义变体，新增 `test_artifacts_sanitize_escaped_windows_paths_in_tool_output`，并重新生成真实产物；新产物未检出主机路径。

### 18.2 仍存在但不阻塞验收

1. **Stage 0 冻结文件的 Ruff 提示**：全仓 `ruff check .` 仍有 10 条提示（9 条在 `schemas/` 的 `UP037/UP017`，1 条在 `test_report_schema.py` 的 `FURB167`）。这些是阶段 0 已冻结代码的样式建议，项目未规定 Ruff 作为强制 lint gate；为避免修改冻结 Schema，本次未处理。建议阶段 2 前单独清理。
2. **Windows 符号链接测试跳过**：4 条用例因宿主机不允许创建符号链接而跳过，已记录明确原因；在支持符号链接的环境应重新执行。
3. **真实模型语义结果存在轻微波动**：两次真实整仓审查的确定性工具结果一致（240 源 Finding、91 映射、90 确定性、149 跳过、1 重复），但 LLM 语义补充数量为 1～2 条，最终 Finding 为 91～92 条。temperature 为 0.0，但 Provider 仍可能有非确定性；不影响确定性证据与验收结论。
4. **样例产物未提交**：真实产物包含第三方代码片段与原始工具输出，按项目规则保留在本地 `reports/stage1-20261110T120331Z-d8333a8c/`，未纳入 Git。若验收要求提交产物本体，需要负责人确认。
5. **基础依赖未全部固定版本**：`environment.yml` 仅固定阶段 1 新增的四个分析工具，FastAPI 等基础依赖仍未固定；这是阶段 0 遗留事项，当前验证版本已记录在 §13。
6. **FastAPI 同步单槽位**：阶段 1 的 API 是受控同步入口，忙碌时返回 429；不具备异步队列、重试或横向扩展能力，属于阶段 1 设计边界而非缺陷。

---

## 19. 已知限制

- 阶段 1 是单进程、非 Agent 流水线；不包含 Supervisor-Worker、SubAgent、LangGraph、事件总线、重试调度与并发控制。
- 外部 GitHub 仓库永远不执行测试、安装或构建脚本；`not_executed` 不等于失败，也不等于 0% 覆盖率。
- 仅项目自维护、固定哈希的 `tests/fixtures/trusted_repo/` 可在宿主机执行 Pytest/Coverage；不自动安装第三方依赖。
- 阶段 1 不生成 `report.json`、不生成 `ReviewReport`、不实现四维评分、Final Reviewer、去重后的最终裁定或 `APPROVE / COMMENT / REQUEST_CHANGES` 结论。
- LLM 分析依赖外部 Provider 的可用性；超时/失败时保留确定性工具结果，审查状态标记为 `partial`。
- 产物已做路径与密钥样式净化，但工具 stdout/stderr 仍可能包含被截断的第三方代码片段；使用与外发时应按组织数据分级要求处理。
- 审查对象限定 Python 仓库；v1 不解析其他语言。
- 4 条符号链接测试在 Windows 宿主机跳过；不支持符号链接的平台无法验证该部分防护。
- 真实网络与真实模型测试需要显式开关，默认离线套件不覆盖外部服务可用性。

---

## 20. 最终 PASS / BLOCKED / FAIL 结论

**最终结论：PASS**

判定依据：

- AC-1-01～AC-1-15 全部满足，证据见 §8。
- TC-1-01～TC-1-06 全部满足，证据见 §9。
- 阶段 0 回归 204 条全部通过。
- 全量单元测试 820 passed、4 skipped、0 failed、0 error；集成测试 15 passed。
- 4 条跳过均为 Windows 符号链接平台限制，有明确原因，不影响验收。
- 真实 GitHub Clone、真实静态分析、真实 LLM 冒烟与真实整仓审查均已完成并记录 SHA、模型、usage 与产物。
- 外部不可信仓库未在宿主机执行任何测试、安装或构建脚本。
- 三个核心 Schema 与 `docs/` 未被修改；未引入阶段 2 依赖或目录。
- 未伪造工具结果、测试结果、覆盖率或模型输出；`not_executed` 语义保持正确。

不存在 `BLOCKED` 项：真实模型调用已使用合法配置成功执行，TC-1-06 不是 `NOT RUN`。

Stage 1.7 的提交与阶段 2 的启动仍需项目负责人确认。

---

## 附录 A：验收命令与实际结果

```text
# 阶段 0 回归
pytest tests/unit/test_task_schema.py tests/unit/test_result_schema.py tests/unit/test_report_schema.py -q
204 passed

# 全量单元测试
pytest tests/unit -q
820 passed, 4 skipped

# 离线集成
pytest tests/integration -q -m "not real_network and not llm_smoke"
11 passed, 4 deselected

# 真实网络
RUN_REAL_NETWORK=1 pytest tests/integration -q -m real_network
3 passed, 12 deselected

# 真实 LLM 冒烟
RUN_LLM_SMOKE=1 pytest tests/integration/test_llm_smoke.py -q -s
1 passed

# 全部集成
RUN_REAL_NETWORK=1 RUN_LLM_SMOKE=1 pytest tests/integration -q
15 passed

# 安全相关单元测试
pytest tests/unit/test_url_validator.py tests/unit/test_file_filters.py \
  tests/unit/test_redaction.py tests/unit/test_repository_inspector.py \
  tests/unit/test_tool_base.py tests/unit/test_workspace_snapshot.py \
  tests/unit/test_trusted_fixture.py tests/unit/test_process_runner.py \
  tests/unit/test_evidence_validator.py tests/unit/test_settings_stage1.py -q
338 passed, 4 skipped

# 依赖禁止项
FORBIDDEN: []
PASSIVE-ALLOWED: ['opentelemetry-api']

# 真实整仓审查
python -m code_review.cli review https://github.com/pallets/itsdangerous --branch main
review_status=completed, findings=91, test_status=not_executed, llm_status=completed
```

## 附录 B：证据文件位置

| 证据 | 位置 |
| --- | --- |
| 阶段 1.1 证据 | `reports/phase_1_1_repository_acquisition_evidence.md` |
| 阶段 1.2 证据 | `reports/phase_1_2_inspector_evidence.md` |
| 阶段 1.3 证据 | `reports/phase_1_3_static_analysis_evidence.md` |
| 阶段 1.4 证据 | `reports/phase_1_4_test_execution_evidence.md` |
| 阶段 1.5 证据 | `reports/phase_1_5_finding_llm_evidence.md` |
| 阶段 1.6 证据 | `reports/phase_1_6_review_service_evidence.md` |
| 阶段 1.7 证据 | 本报告 |
| 真实产物样例 | `reports/stage1-20261110T120331Z-d8333a8c/`（本地，未提交） |
