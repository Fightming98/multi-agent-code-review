# Stage 1.6 测试证据：报告生成和统一服务入口

- 执行日期：2026-11-10
- 执行环境：Windows 11、Python 3.12.16、Conda 环境 `multi-agent-review`
- 解释器：`D:/python/Anaconda/envs/multi-agent-review/python.exe`
- 代码状态：**Stage 1.6 已验收（2026-11-10 人工审核），提交记录见 Git 历史**
- 阶段目标：AC-1-14、AC-1-15；交付 `ReviewService`、CLI、受控同步 FastAPI 与四件基础产物
- 结论：**Stage 1.6 范围内 PASS**（AC-1-14、AC-1-15 均有自动化证据）；阶段 1 整体结论待 Stage 1.7

## 1. 本阶段完成的功能

1. 实现 `ReviewService`，作为 CLI、FastAPI 与后续 Worker 的唯一审查业务入口。
2. 固定阶段 1 流水线顺序：参数校验 → 仓库获取并固定 40 位 Commit SHA → 文件扫描 →
   Ruff / Bandit / Radon 静态分析 → 测试执行决策 → Finding 聚合 → LLM 辅助分析 →
   四件产物生成 → 资源清理。
3. 实现 CLI `review` 子命令：人类可读摘要与 `--json` 机器可读摘要，退出码 0/1，
   错误信息不含 traceback、密钥或宿主机路径。
4. 实现 FastAPI 受控同步入口 `POST /api/reviews`：单进程单并发槽位，忙碌返回 429，
   参数错误、仓库错误与内部错误按阶段映射为 400 / 502 / 500。
5. CLI 与 FastAPI 只做参数校验、调用服务与响应转换，不包含第二套审查逻辑。
6. 实现阶段 1 专用 Artifact Schema（`schema_version="1.0"`）：
   `MetadataArtifact`、`StaticAnalysisArtifact`、`TestReportArtifact` 及子模型。
7. 实现 `ReportGenerator`：先构建并校验三份 JSON 模型，再净化，写 JSON，
   最后仅依据三份已校验模型渲染 `report.md`。
8. 每次审查在 `reports/<review_id>/` 下只生成四件产物：
   `metadata.json`、`static_analysis.json`、`test_report.json`、`report.md`；
   **不生成 `report.json`，不构造 `ReviewReport`**。
9. 外部 GitHub 仓库测试状态固定为 `not_executed`，数量与覆盖率字段保持 `null` 并给出原因。
10. 可信 Fixture 受控例外：仅默认 `tests/fixtures/trusted_repo/` 可通过显式开启的
    `review_trusted_fixture()` 执行 Pytest / Coverage；该入口不通过 CLI / API 暴露。
11. 单工具、测试执行或 LLM 失败被隔离为 `partial`，保留确定性工具结果；
    仓库获取、扫描、聚合与报告生成失败作为本次审查不可继续的阶段错误。
12. 产物净化：工作区、用户主目录与系统临时目录替换为占位符，密钥、令牌与凭据替换为
    `[REDACTED]`；净化后重新通过 Pydantic 校验。
13. 产物不可覆盖：目标报告目录已存在时拒绝写入；生成失败时删除本次已创建的部分目录。
14. 报告目录必须位于审查工作区之外；否则在报告生成前拒绝并清理工作区。
15. Finding 的 `tool_evidence.raw_output_ref` 指向
    `static_analysis.json#/tools/<tool>/findings/<index>`，测试证据指向
    `static_analysis.json#/tests/pytest`，可在产物内实际解析。

## 2. 修改与新增文件

### 2.1 新增运行代码

| 文件 | 说明 |
|---|---|
| `src/code_review/services/review_service.py` | `ReviewService`、`ReviewRequest`、`ReviewOutcome`、`ReviewServiceError`；统一流水线与资源清理 |
| `src/code_review/reporting/__init__.py` | 报告产物层导出 |
| `src/code_review/reporting/artifact_models.py` | 阶段 1 专用 Pydantic Artifact Schema：metadata / static analysis / test report |
| `src/code_review/reporting/report_generator.py` | 三份 JSON 构建、净化、写入与失败清理 |
| `src/code_review/reporting/markdown_renderer.py` | 仅从三份已校验模型渲染 12 节 Markdown 报告 |
| `src/code_review/cli.py` | CLI 主入口与 `review` 子命令 |
| `src/code_review/api/__init__.py` | API 包导出 |
| `src/code_review/api/app.py` | FastAPI `create_app()`、`POST /api/reviews`、并发槽位与错误映射 |

### 2.2 新增测试

| 文件 | 用例数 | 覆盖内容 |
|---|---:|---|
| `tests/stage1_helpers.py` | — | 共享时间/Commit/Fixture 常量、Finding/Tool/Test/LLM 构造器、Fake 仓库管理器/工具/测试执行器/LLM |
| `tests/unit/test_artifact_models.py` | 18 | GitHub 与可信 Fixture 元数据、Review ID 路径安全、UTC 时间、扫描部分语义、工具路径与时间校验、`Stage1Analyzer` / `unverified` 强制、LLM 失败原因、`not_executed` 空计数规则、`executed` 计数与覆盖率、多余字段拒绝 |
| `tests/unit/test_report_generator.py` | 11 | 恰好四件产物且无 `report.json`、Commit/工具版本、可信 Fixture 不伪造 Commit、`not_executed` 空计数、目录不覆盖、路径与密钥净化、证据指针可解析、Markdown 来自已校验模型、重复/缺失工具拒绝、失败清理、Review ID 不能逃逸输出根 |
| `tests/unit/test_markdown_renderer.py` | 10 | 12 节顺序、阶段 1 无 APPROVE/COMMENT/REQUEST_CHANGES、Finding 分类分组、`not_executed` 措辞、可信 Fixture 区分、工具/LLM 失败风险、拒绝提案不进入正式 Finding、空结果不等于通过、表格转义、超过 10 条截断 |
| `tests/unit/test_review_service.py` | 17 | 全流水线与四件产物、外部仓库永不执行测试、非法 URL/Revision 在 Clone 前拒绝、Clone 错误安全映射、非法快照、输出目录位于工作区、工具异常隔离、测试异常、LLM 异常保留确定性结果、LLM 未配置 `partial`、非法时钟/Review ID、报告失败清理、可信 Fixture 仅用 Fixture 测试、默认禁用可信 Fixture、工具唯一性、警告截断 |
| `tests/unit/test_cli.py` | 5 | 必需子命令、请求字段委托、人类可读输出、`--json` 负载、服务错误/未知错误退出 1 且无 traceback、始终关闭服务 |
| `tests/unit/test_api.py` | 13 | 合法请求 200 与报告引用、多余/缺失字段 422、GET 405、阶段到 HTTP 映射、未知错误通用化、并发第二请求 429、生命周期关闭自有服务 |
| `tests/integration/test_stage1_6_review.py` | 3 | 真实 Ruff/Bandit/Radon + Fake Clone 的四件产物与外部测试 `not_executed`；真实可信 Fixture 的 Pytest/Coverage 执行与元数据；CLI/API 导入同一 `ReviewService` 且不直接导入工具/聚合/LLM |

阶段 1.6 新增测试合计：**74 条单元测试 + 3 条集成测试**。

### 2.3 修改的既有文件

| 文件 | 修改 | 原因 |
|---|---|---|
| `config/settings.py` | 新增 `review_output_root: str = "reports"`，并纳入非空校验 | CLI / API 默认报告输出根可配置，避免在业务代码散落路径 |
| `.env.example` | 新增 `REVIEW_OUTPUT_ROOT=reports` | 与新配置项一致 |
| `README.md` | 更新阶段状态、技术栈、测试命令、CLI/API 用法、四件产物、安全边界与目录树 | 与 Stage 1.6 实际能力一致 |

未修改：`docs/task_contracts.md`、`src/code_review/schemas/task.py`、`result.py`、
`report.py`、`environment.yml`、`docs/acceptance.md`。未新增任何依赖。

`.env` 仍为本地文件且被 Git 忽略；本阶段未调用真实 LLM，未写入任何 API Key。

## 3. 核心设计决策

1. **唯一业务入口**：CLI 与 FastAPI 只构造 `ReviewRequest` 并调用 `ReviewService`；
   工具、聚合、LLM 与报告生成只在服务内部出现。集成测试通过模块对象同一性与源码
   静态检查双重证明不存在第二套审查逻辑。
2. **阶段 1 专用产物模型与阶段 0 合同解耦**：四件产物使用
   `reporting/artifact_models.py` 中的阶段 1 Schema，不修改冻结的
   `AgentTask` / `Finding` / `AgentResult` / `ReviewReport`，也不生成 `report.json`。
3. **先结构化、后 Markdown**：`report.md` 只读取三份已通过 Pydantic 校验的模型，
   不读取运行时对象，保证 JSON 与 Markdown 同源。
4. **两步净化**：先把本次工作区、用户主目录、系统临时目录替换为占位符，再做密钥
   脱敏；净化后的模型重新校验，防止净化破坏 Schema。
5. **外部仓库测试永不执行**：`ReviewService.review()` 只传入
   `trusted_fixture=None`；外部仓库即使工具或 LLM 失败，测试状态也只能是
   `not_executed` 或 `failed`，不会出现伪造的测试计数。
6. **可信 Fixture 双重限制**：构造服务时必须显式
   `allow_trusted_fixture_review=True`，且运行时验证 Fixture 根目录必须是默认
   `tests/fixtures/trusted_repo/`，名称必须在批准列表中；CLI/API 均无法触发该入口。
7. **失败隔离边界**：工具、测试执行、LLM 属于“可降级”阶段，失败进入
   `warnings` 且审查状态为 `partial`；仓库获取、扫描、聚合、报告生成属于
   “不可继续”阶段，抛出 `ReviewServiceError` 并带安全错误阶段。
8. **报告目录安全**：目标目录必须位于工作区之外；已存在则拒绝；写入中途失败
   删除本次创建的部分目录，避免留下半成品。
9. **并发模型**：FastAPI 保持同步 `def` 端点，使用
   `threading.BoundedSemaphore(1)` 非阻塞获取槽位，忙碌立即返回 429；
   阶段 1 不伪装成异步任务系统。
10. **错误信息收敛**：CLI 与 API 不输出 traceback；服务错误只包含固定文案、
    阶段、错误类型、可重试标记与 Review ID。
11. **元数据不伪造来源**：可信 Fixture 的 `source_type="trusted_fixture"`、
    `repository_url="fixture://<name>"`、`commit_sha=null`，并记录 64 位
    Manifest SHA-256；GitHub 仓库必须有 40 位 Commit SHA。
12. **Stage 1 Finding 约束写入产物合同**：`StaticAnalysisArtifact` 在模型层拒绝
    非 `Stage1Analyzer` 或非 `unverified` 的 Finding，LLM 拒绝提案只出现在
    `llm_analysis.rejected[]`。

## 4. 关键实现说明

- `ReviewService.review()` 的顺序为：URL/分支/SHA 校验 → 生成 Review ID →
  Clone 并固定 Commit → 扫描 → 工具 → 测试 → 聚合 → LLM → 报告 → `finally`
  清理工作区。
- Review ID 默认格式为 `stage1-YYYYMMDDTHHMMSSZ-<8 位十六进制>`；调用方注入的
  ID 必须通过 Artifact Schema 的安全路径校验。
- 参数校验先于 Clone：非法 URL、非法分支或非 40 位 SHA 不会触发仓库获取，
  也不会创建报告目录。
- `_WorkspaceInfo` 统一描述 GitHub 仓库与可信 Fixture 的来源元数据，避免在
  报告生成阶段判断来源分支。
- 工具按构造顺序串行执行；单个工具抛异常时生成 `failed` 的工具结果与
  `error_summary`，审查继续。测试执行器抛异常时生成 `failed` 的
  `TestExecutionResult`，计数保持 `null`。
- LLM 抛异常时返回 `LLMAnalysisStatus.FAILED` 且保留聚合后的确定性 Finding；
  LLM 未配置时返回 `not_configured`，两者都使审查状态为 `partial`。
- `review_status` 只有在扫描完整、工具成功/有发现且未截断、测试状态符合来源、
  只读校验未失败、LLM `completed` 且无警告时为 `completed`，否则为 `partial`。
- 警告文本统一压平换行并截断到 500 字符，避免把多行异常或路径带入 CLI/API。
- `ReportGenerator` 先构建 `MetadataArtifact`、`StaticAnalysisArtifact`、
  `TestReportArtifact`，净化后写入；Markdown 渲染器要求 12 节标题按固定顺序输出。
- Markdown 报告第 12 节明确说明阶段 1 不输出 APPROVE / COMMENT /
  REQUEST_CHANGES，避免把阶段 1 基础报告误读为最终评审结论。
- CLI 主入口为 `code_review.cli:main`，支持 `review <url>`、
  `--branch`、`--commit-sha`、`--output-dir`、`--json`；成功或 `partial` 退出 0，
  服务错误或未知错误退出 1。
- FastAPI 入口为 `code_review.api.app:app`；`create_app()` 支持注入与 CLI 相同的
  服务；仅 `POST /api/reviews`，请求体额外字段被拒绝，响应只返回报告相对引用。
- 测试统一使用顶层 `code_review.*` 导入，避免 `src.code_review.*` 与
  `code_review.*` 形成两个不同的 Pydantic 类；既有测试保持原导入方式，回归通过。
- 测试报告目录全部使用 `tmp_path`，未在仓库 `reports/` 下留下任何审查产物。

## 5. 测试命令

```powershell
$env:PYTHONUTF8 = "1"
$PY = "D:/python/Anaconda/envs/multi-agent-review/python.exe"

# Stage 1.6 新增单元测试
& $PY -m pytest tests/unit/test_artifact_models.py tests/unit/test_report_generator.py tests/unit/test_markdown_renderer.py tests/unit/test_review_service.py tests/unit/test_cli.py tests/unit/test_api.py -q

# 全量单元测试（含阶段 0 / 1.1～1.5 回归）
& $PY -m pytest tests/unit -q

# 阶段 0 Schema 回归
& $PY -m pytest tests/unit/test_task_schema.py tests/unit/test_result_schema.py tests/unit/test_report_schema.py -q

# 非联网、非真实 LLM 全量测试（单元 + 集成）
& $PY -m pytest tests -q -m "not real_network and not llm_smoke"

# 离线集成测试
& $PY -m pytest tests/integration -q -m "not real_network and not llm_smoke"

# Stage 1.6 变更文件 Ruff
& $PY -m ruff check src/code_review/services/review_service.py src/code_review/reporting src/code_review/cli.py src/code_review/api tests/stage1_helpers.py tests/unit/test_artifact_models.py tests/unit/test_report_generator.py tests/unit/test_markdown_renderer.py tests/unit/test_review_service.py tests/unit/test_cli.py tests/unit/test_api.py tests/integration/test_stage1_6_review.py config/settings.py

# CLI 冒烟（需要 PYTHONPATH=src）
$env:PYTHONPATH = "src"
& $PY -m code_review.cli --help
& $PY -m code_review.cli review "https://gitlab.com/x/y"

# FastAPI 导入与路由探针
& $PY -c "from code_review.api.app import app; print(app.title); print([r.path for r in app.routes if getattr(r, 'path', '') == '/api/reviews'])"

# 安全探针
git check-ignore .env
& $PY -c "import importlib.metadata as m; n={(d.metadata['Name'] or '').lower().replace('_','-') for d in m.distributions()}; exact={'langgraph','redis','arq','sqlalchemy','asyncpg','mcp','a2a-sdk','langsmith','streamlit'}; pre=('langchain','langgraph-','psycopg'); print('FORBIDDEN:', sorted(x for x in n if x in exact or x.startswith(pre) or (x.startswith('opentelemetry') and x!='opentelemetry-api'))); print('PASSIVE-ALLOWED:', sorted(x for x in n if x=='opentelemetry-api'))"
```

## 6. 实际测试结果

| 命令 | 结果 |
|---|---|
| Stage 1.6 新增单元测试 | **74 passed** |
| 全量单元测试 | **819 passed, 4 skipped** |
| 阶段 0 Schema 回归 | **204 passed** |
| 非联网全量测试（单元 + 集成） | **830 passed, 4 skipped, 3 deselected** |
| 离线集成测试 | **11 passed, 3 deselected** |
| Stage 1.6 变更文件 Ruff | **All checks passed** |
| CLI `--help` | 正常显示 `review` 子命令与参数 |
| CLI 非法 URL | `error[validation]: repository URL is invalid`，退出码 1 |
| FastAPI 导入 | `api_import_ok Multi-Agent Code Review (Stage 1)`；路由含 `/api/reviews` |
| `git check-ignore .env` | `.env` 被忽略 |
| 禁止依赖探针 | `FORBIDDEN: []`；`PASSIVE-ALLOWED: ['opentelemetry-api']` |

4 个 skip 均为 Windows 主机不允许创建符号链接导致的既有平台跳过：

```text
tests\unit\test_repository_inspector.py:207: symlinks are not available on this platform
tests\unit\test_trusted_fixture.py:224: symbolic links are not permitted on this host
tests\unit\test_trusted_fixture.py:236: symbolic links are not permitted on this host
tests\unit\test_workspace_snapshot.py:102: symbolic links are not permitted on this host
```

集成测试实际验证了：

- 外部样例仓库的四件产物内容、`not_executed` 空计数、无 `report.json`；
- 外部样例仓库的 `.env` 内容与工作区绝对路径均未进入任一产物；
- 外部样例仓库未产生 `__pycache__`、`.pytest_cache` 或 `*.pyc`；
- 可信 Fixture 真实执行 Pytest / Coverage，`execution_status="executed"`、
  `read_only_verified=true`，元数据不伪造 Git Commit，且 Fixture 内无缓存/字节码；
- CLI 与 API 导入的是同一个 `ReviewService` 类，且两者源码不直接引用
  Ruff/Bandit/Radon、聚合器或 LLM 分析器。

## 7. 尚未完成 / 已知限制

1. **真实 GitHub Clone 与真实模型冒烟未在 Stage 1.6 执行**：TC-1-04 与 TC-1-06
   属于 Stage 1.7 全链路验收。Stage 1.5 已有真实 Provider 冒烟与整仓扫描记录，
   但 Stage 1.6 本身未调用真实 LLM，也未 Clone 真实仓库；不得据此把 TC-1-04 /
   TC-1-06 记为 Stage 1.6 PASS。
2. **CLI 需要 `PYTHONPATH=src`**：仓库当前没有 `pyproject.toml` 或可编辑安装，
   从仓库根目录直接运行 `python -m code_review.cli` 会找不到包。README 已明确
   给出 `$env:PYTHONPATH = "src"` 的运行方式；这是打包/环境限制，不是架构偏离，
   但应在 Stage 1.7 验收命令中保持一致。
3. **FastAPI 测试客户端弃用警告**：`fastapi.testclient` 提示
   `Using httpx with starlette.testclient is deprecated; install httpx2 instead.`
   当前环境未安装 `httpx2`；本阶段不新增依赖，因此保留该警告，不影响用例结果。
   后续是否升级属于依赖变更，需用户确认。
4. **仓库整体 Ruff 仍有既有告警**：冻结的 Stage 0 Schema 与旧测试中存在既有
   Ruff 告警；本阶段只保证 Stage 1.6 变更文件 Ruff 全通过，未修改冻结文件。
5. **阶段 1 同步执行**：FastAPI 在请求线程内同步执行完整审查，单进程单并发槽位，
   忙碌返回 429；Redis/ARQ 与 202 异步语义属于阶段 4，本阶段未提前实现。
6. **阶段 1 不产出 `report.json` / `ReviewReport`**：四维评分、总体分与
   APPROVE / COMMENT / REQUEST_CHANGES 属于阶段 2 及以后；阶段 1 的
   `report.md` 只做基础报告，并在第 12 节明确声明。
7. **报告净化是启发式**：覆盖工作区、主目录、临时目录与常见密钥/令牌模式；
   不承诺识别所有可能的敏感字符串。仓库内容本身仍被视为不可信数据。
8. **本报告尚未提交**：等待人工审核 Stage 1.6 测试证据后再决定是否提交，
   以及是否进入 Stage 1.7。

## 8. 与 `docs/acceptance.md` 的对应关系

| 验收项 | 状态 | 证据 |
|---|---|---|
| AC-1-14：CLI 与 FastAPI 调用同一个 `ReviewService`，无两套审查逻辑；FastAPI 仅受控同步入口 | **PASS** | `test_cli_and_api_import_the_same_review_service` 验证 `cli.ReviewService is ReviewService`、`api_app.ReviewService is ReviewService`，并检查源码不直接引用工具/聚合/LLM；`test_cli_delegates_to_review_service`；`test_post_review_returns_summary_and_uses_service` 等 13 条 API 用例；API 端点同步执行且单并发槽位 |
| AC-1-15：四件基础输出文件；三份 JSON 符合阶段 1 专用 Artifact Schema；Markdown 由结构化数据渲染；不要求完整 `ReviewReport` | **PASS** | `test_generate_writes_exactly_four_artifacts` 断言目录恰好四件且无 `report.json`；`test_artifact_models.py` 18 条 Schema 合同；`test_markdown_is_rendered_from_validated_models`；集成测试验证真实工具输出下的四件产物与内容；`test_finding_evidence_pointers_resolve_in_static_analysis` 实际解析证据指针 |
| AC-1-10：外部不可信仓库不在宿主机执行测试，状态 `not_executed` 并说明原因 | **PASS（Stage 1.6 范围）** | `test_external_repository_tests_are_never_executed`；集成测试断言 `test_runner` 调用参数为 `None`、`test_report.json` 计数全 `null`、原因存在；外部样例代码未产生缓存/字节码 |
| AC-1-12：仓库工作区只读，分析不修改原始代码 | **PASS（Stage 1.6 范围）** | 可信 Fixture 集成测试断言 `read_only_verified=true` 且 Fixture 内无 `.pytest_cache` / `__pycache__` / `*.pyc`；外部仓库不执行测试 |
| TC-1-01：阶段 0 全部测试回归 | **PASS** | 204 passed |
| TC-1-02：单元测试不联网、不调用真实 LLM | **PASS（Stage 1.6 新增范围）** | 74 条新增单元测试全部使用 Fake / Mock；API 使用 `TestClient` 但服务为 Fake；无 API Key、无网络调用 |
| TC-1-03：可信样例仓库完整集成测试 | **PARTIAL** | Stage 1.6 集成测试已用真实 Ruff/Bandit/Radon 与真实可信 Fixture 覆盖完整服务链路；AC-1-01～AC-1-15 的最终整体判定仍由 Stage 1.7 执行 |
| TC-1-04：真实 GitHub Clone 验证 | **NOT RUN** | Stage 1.7 |
| TC-1-06：真实模型调用冒烟 | **NOT RUN（Stage 1.6）** | Stage 1.7；Stage 1.5 已有 Provider 冒烟与整仓扫描记录，但不能替代 Stage 1.7 最终验收 |

## 9. 架构偏离

未发现需要暂停实现的架构偏离：

- `ReviewService` 位于 `services/review_service.py`，与 `docs/architecture.md`
  的服务层定位一致；CLI 与 API 是薄入口，不持有业务逻辑。
- `reporting/` 只定义阶段 1 专用产物模型与生成器，不构造阶段 0 `ReviewReport`。
- 未创建 `agents/`、`graph/`、`orchestration/`、`workers/`，未引入 LangGraph、
  Redis、ARQ、PostgreSQL、MCP 或 A2A。
- 未修改三个冻结核心 Schema、`docs/task_contracts.md` 或 `environment.yml`。
- 未新增依赖；FastAPI、Pydantic、httpx 均为阶段 0 已有依赖。
- 所有阶段 1 Finding 保持 `Stage1Analyzer` + `unverified`；LLM 拒绝提案不进入
  正式 Finding。

已报告的非架构偏离：CLI 运行需要 `PYTHONPATH=src`（缺少打包/可编辑安装），
已在 README 与 §7 中说明。

## 10. 是否可以进入下一子阶段

- **Stage 1.6 范围内：PASS**。AC-1-14、AC-1-15 均有自动化测试与集成证据；
  全量单元回归 819 passed、4 skipped；非联网全量 830 passed、4 skipped、
  3 deselected；Stage 1.6 变更文件 Ruff 全通过。
- **阶段 1 整体：尚未完成**。Stage 1.7 仍需执行阶段 0 回归、全部阶段 1 测试、
  真实 GitHub Clone（TC-1-04）、安全测试与真实模型冒烟（TC-1-06），并出具
  阶段 1 最终验收报告。
- **人工审核结论（2026-11-10）：Stage 1.6 验收通过并提交。**
- 下一步：按 `阶段1_Prompt.md` 进入 Stage 1.7 全链路验收；Stage 1.7 证据
  单独出具，不修改本报告已记录的 Stage 1.6 结果。
