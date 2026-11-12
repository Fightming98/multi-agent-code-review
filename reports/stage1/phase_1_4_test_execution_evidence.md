# 阶段 1.4 测试执行与覆盖率证据

- 日期：2026-11-10
- 范围：Stage 1.4「测试执行与覆盖率」
- 状态：**实现与测试完成，未提交，等待人工审核**
- 后续：Stage 1.5 **未开始**

> 本报告只记录本机真实执行结果。所有 Pytest / Coverage 数据来自实际工具输出；外部仓库测试状态为 `not_executed`，没有伪造或补写任何执行数据。

## 1. 本阶段完成内容

- 新增可信 Fixture：`tests/fixtures/trusted_repo/`，固定名称 `trusted_fixture_v1`、固定版本 `1.0.0`、字节级 SHA-256 清单。
- 新增可信 Fixture 校验器：路径、链接、清单结构、文件集合、逐文件哈希与白名单名称校验。
- 新增受限 Pytest / Coverage.py 执行器：参数数组、`shell=False`、仓库外临时工作目录、最小环境、禁用第三方插件自动加载、禁止字节码与 Pytest 缓存。
- 新增 `not_executed` 门禁：外部仓库、未批准名称、Fixture 被篡改或缺失时，不创建测试进程。
- 新增测试超时、输出上限、测试记录上限、覆盖率文件上限与结果解析器。
- 新增只读快照与差异检测：测试执行与静态分析前后对工作区做 SHA-256 快照。
- 新增 83 条测试（含 Windows 上跳过的符号链接用例），并完成真实 Fixture 与真实 GitHub 仓库验证。

## 2. 环境

| 项 | 值 |
| --- | --- |
| 操作系统 | Windows 11 Pro 10.0.26100 |
| Python | 3.12.16 |
| Conda 环境 | `multi-agent-review` |
| pytest | 9.2.0 |
| coverage | 7.17.2 |
| Ruff | 0.17.4 |
| Bandit | 1.9.4 |
| Radon | 6.0.1 |

未新增依赖；未修改 `environment.yml`。

## 3. 新增与修改文件

### 3.1 新增

| 文件 | 说明 |
| --- | --- |
| `.gitattributes` | 可信 Fixture 使用 `-text`，禁止 Git 换行转换，保证字节级哈希稳定 |
| `src/code_review/tools/trusted_fixture.py` | Fixture 清单、白名单与 SHA-256 校验 |
| `src/code_review/tools/workspace_snapshot.py` | 只读快照与差异检测 |
| `src/code_review/tools/test_runner.py` | 受限 Pytest / Coverage 执行、JUnit/Coverage 解析与状态映射 |
| `tests/fixture_factory.py` | 测试用临时 Fixture 与清单生成辅助 |
| `tests/fixtures/trusted_repo/README.md` | 可信 Fixture 约束与预期结果 |
| `tests/fixtures/trusted_repo/FIXTURE_MANIFEST.json` | 文件哈希清单 |
| `tests/fixtures/trusted_repo/calc/__init__.py` | Fixture 公开接口 |
| `tests/fixtures/trusted_repo/calc/core.py` | Fixture 示例实现（`multiply` 故意未覆盖） |
| `tests/fixtures/trusted_repo/tests/test_core.py` | 4 条确定性测试（3 passed、1 skipped） |
| `tests/unit/test_trusted_fixture.py` | 27 条 Fixture 校验测试 |
| `tests/unit/test_workspace_snapshot.py` | 8 条快照测试 |
| `tests/unit/test_test_report_parsers.py` | 18 条 JUnit / Coverage 解析测试 |
| `tests/unit/test_test_runner.py` | 24 条执行门禁、状态映射与只读测试 |
| `tests/integration/test_trusted_fixture_execution.py` | 4 条真实执行、篡改、超时与写入检测测试 |
| `tests/integration/test_read_only_analysis.py` | 2 条静态分析只读测试 |

### 3.2 修改

| 文件 | 变更 |
| --- | --- |
| `config/settings.py` | 新增 `max_test_output_bytes`、`max_test_records`、`max_coverage_files` |
| `tests/unit/test_settings_stage1.py` | 新配置默认值与越界测试 |
| `pytest.ini` | `norecursedirs = tests/fixtures ...`，防止外层 pytest 收集 Fixture 测试 |
| `src/code_review/tools/__init__.py` | 导出测试执行、Fixture 与快照相关类型 |
| `tests/integration/test_real_static_analysis.py` | 增加静态分析前后快照与外部仓库 `not_executed` 断言 |

未修改 `docs/task_contracts.md`、阶段 0 的三个核心 Schema（`task.py`、`result.py`、`report.py`）或任何冻结文档。

## 4. 核心设计

### 4.1 可信 Fixture 信任锚

- 唯一默认路径：`tests/fixtures/trusted_repo/`。
- 唯一批准名称：`trusted_fixture_v1`（`APPROVED_TRUSTED_FIXTURE_NAMES`），配置项不能扩大白名单。
- 清单必须与 `fixture_name`、`version`、`files` 三个键严格一致；不允许未知键、重复键或空文件列表。
- 清单路径必须是规范仓库相对 POSIX 路径；拒绝绝对路径、`..`、`.`、反斜杠、盘符/冒号与 NUL。
- 实际文件集合必须与清单完全一致；拒绝新增、缺失、符号链接、junction 与非普通文件。
- 每个文件按字节计算 SHA-256；清单自身也计算 SHA-256 并写入结果，供报告追溯。
- `TestRunner` 默认只能使用固定路径；测试注入其他根目录必须显式设置 `allow_custom_fixture_root=True`，避免调用方把外部仓库路径当作可信 Fixture 执行。
- `.gitattributes` 对 Fixture 设置 `-text`，避免 Windows `core.autocrlf` 改变换行并破坏哈希。

### 4.2 受限执行

- Pytest 与 Coverage 均通过参数数组启动，`shell=False`。
- 工作目录为系统临时目录，不在 Fixture 内；测试结果、JUnit XML、Coverage JSON 与 `.coverage` 均写在 Fixture 外。
- 环境变量采用最小集合，并设置：
  - `PYTHONPATH=<fixture_root>`
  - `PYTHONDONTWRITEBYTECODE=1`
  - `PYTHONNOUSERSITE=1`
  - `PYTHONIOENCODING=utf-8`
  - `PYTHONHASHSEED=0`
  - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`
  - `COVERAGE_FILE=<temp>/.coverage`
- Pytest 参数包含 `-p no:cacheprovider`、外部空 `pytest.ini`、`--rootdir=<fixture_root>`、`--basetemp=<temp>`。
- Coverage 的 omit 模式以 Fixture 根目录为前缀，只排除 Fixture 自己的 `tests/`、顶层 `test_*.py` 与 `conftest.py`。
- 不自动安装依赖；不执行 `setup.py`、`build.py` 或任何安装脚本；Fixture 只包含标准库与 Pytest 测试。

### 4.3 状态语义

| 场景 | 工具层状态 | 合同 `TestSummary.execution_status` | 说明 |
| --- | --- | --- | --- |
| 可信 Fixture 正常执行 | `executed` | `executed` | 真实 passed/failed/skipped 与 coverage |
| 外部仓库（`trusted_fixture=None`） | `not_executed` | `not_executed` | 不创建进程，计数与覆盖率全部为 null，必须给出原因 |
| 未批准名称、篡改、缺失、无 `tests/` | `failed` | `not_executed` | 不创建进程，`invalid_input` |
| Pytest / Coverage 超时 | `timeout` | `failed` | 记录 `timeout`，不得记为 `not_executed` |
| 可执行文件缺失 / 进程无法启动 | `failed` | `not_executed` | 环境原因导致未执行 |
| 测试自身失败 | `executed` | `executed` | `failed` 计数大于 0，但不是工具失败 |
| 非预期退出码、JUnit/Coverage 缺失或解析失败 | `failed` | `failed` | 工具层错误，保留可用计数 |
| 执行期间 Fixture 被写入 | `failed` | `failed` | `read_only_violation`，保留计数与覆盖率，列出修改路径 |

### 4.4 只读校验

- 执行前、执行后对 Fixture 做严格快照（不排除任何目录），逐文件 SHA-256；新增、删除、修改全部判为违规。
- 静态分析集成测试对工作区副本做前后快照，确认 Ruff、Bandit、Radon 不产生 `.ruff_cache`、`.pytest_cache`、`__pycache__` 或 `.pyc`。
- 真实 GitHub 仓库集成测试在 Clone 后做快照，静态分析与外部测试门禁后再次快照，差异必须为空。

### 4.5 阈值

本阶段新增配置集中在 `config/settings.py`：

| 配置 | 默认值 |
| --- | --- |
| `pytest_timeout_seconds` | 300 |
| `coverage_timeout_seconds` | 300 |
| `max_test_output_bytes` | 5 MiB |
| `max_test_records` | 100 |
| `max_coverage_files` | 1,000 |

## 5. 实施中发现并修正的问题

1. **Coverage omit 模式误伤全部源码**
   - 原模式 `*/tests/*` 会匹配 Fixture 自身路径（Fixture 位于仓库 `tests/fixtures/trusted_repo/`），导致 Coverage 报 `No data was collected`。
   - 已改为以 Fixture 根目录为前缀的绝对模式，并新增单元回归断言与真实覆盖率集成断言。
2. **自定义 Fixture 根目录可绕过固定路径信任**
   - 原构造参数允许直接传入任意根目录；现已要求测试显式设置 `allow_custom_fixture_root=True`。
3. **JUnit DTD 检查只扫描前 4 KiB**
   - 已改为扫描整个报告，拒绝任意位置的 `<!DOCTYPE` / `<!ENTITY`，并新增超过 4 KiB 前缀的回归测试。
4. **可信 Fixture 根目录符号链接校验**
   - 同时检查原始路径与解析后路径，避免 `resolve()` 后绕过链接检查。

## 6. 测试执行结果

### 6.1 单元测试

```text
python -m pytest tests/unit -q
619 passed, 4 skipped in 8.16s
```

4 条跳过均为 Windows 主机不允许创建符号链接（3 条为 Fixture/快照符号链接用例，1 条为既有仓库扫描用例），不是功能失败。

### 6.2 集成测试（不联网）

```text
python -m pytest tests/integration -q -m "not real_network and not llm_smoke"
6 passed, 3 deselected in 8.27s
```

其中 Stage 1.4 新增 6 条：

- 真实可信 Fixture 执行并生成 Pytest + Coverage 数据；
- 被篡改 Fixture 不执行；
- Pytest 超时被强制终止并记录 `timeout`；
- 测试写入 Fixture 被检测为 `read_only_violation`；
- 静态分析前后工作区完全不变；
- 静态分析 Finding 路径全部为相对 POSIX 路径。

### 6.3 真实 GitHub 仓库

```text
RUN_REAL_NETWORK=1 python -m pytest tests/integration -q -m real_network
3 passed, 6 deselected in 18.27s
```

目标仓库固定为 `https://github.com/pallets/itsdangerous`。执行内容仅限 Clone、文件扫描、Ruff/Bandit/Radon 静态分析与只读快照比对；未执行该仓库的测试、安装或构建脚本。外部仓库测试结果为 `not_executed`，所有测试计数与覆盖率均为 null，原因字段非空。

### 6.4 全量默认测试

```text
python -m pytest tests -q
625 passed, 7 skipped in 20.24s
```

7 条跳过包括 3 条真实网络测试（未设置 `RUN_REAL_NETWORK=1`）和 4 条符号链接相关测试。

### 6.5 Ruff

```text
python -m ruff check <Stage 1.4 source/tests/fixture files>
All checks passed!
```

### 6.6 真实 Fixture 执行数据

```text
status = executed
summary = execution_status='executed' passed=3 failed=0 skipped=1
          coverage=90.0 source='pytest+coverage'
collected_tests = 4
read_only_verified = True
modified_paths = ()
exit_code = 0
coverage_exit_code = 0
pytest_version = 9.2.0
coverage_version = 7.17.2
coverage_files = calc/__init__.py 100.0, calc/core.py 87.5
fixture_manifest_sha256 = 36015c96f30b797685ae98e74caae636845fcb8ecc61d0d181b999e4aa911f3b
```

Fixture 清单：

| 文件 | SHA-256 |
| --- | --- |
| `README.md` | `dde65138fb8ed5e89d8b90cbb7a88442e5fed345716a2162c5a8ec2ced37be47` |
| `calc/__init__.py` | `5b55f151a63a419c39d8aaad9b7c8afd7a659edda689a3d5f3888397a57fa104` |
| `calc/core.py` | `951533072e030a0c0649a3211436558c477c98fc887c935209c63c33454875c7` |
| `tests/test_core.py` | `6cdd4ed9fee7210c7505d16fb3debe2fa858673df8a52e30b01883be640f4d71` |
| `FIXTURE_MANIFEST.json` | `36015c96f30b797685ae98e74caae636845fcb8ecc61d0d181b999e4aa911f3b` |

## 7. 与 acceptance.md 的对应关系

| 验收项 | 证据 | 状态 |
| --- | --- | --- |
| AC-1-09：Pytest 对可信测试仓库执行并输出结果；Coverage.py 生成可信样例覆盖率 | 真实 Fixture 集成测试：4 collected、3 passed、1 skipped、90.0% coverage；`test_report` 数据来自 JUnit XML 与 Coverage JSON | **PASS** |
| AC-1-10：外部不可信仓库不在宿主机执行测试/安装/构建脚本，状态 `not_executed` 并说明原因 | 外部仓库门禁单元测试；真实 `pallets/itsdangerous` 集成测试中 `execute(trusted_fixture=None)` 返回 `not_executed`，计数/覆盖率/source 均为 null，原因非空；未创建测试进程 | **PASS** |
| AC-1-12：仓库工作区只读，分析不修改原始代码 | Fixture 执行前后严格快照；静态分析副本前后快照；真实 GitHub 仓库前后快照；写入 Fixture 的测试被判定 `read_only_violation` | **PASS** |
| 测试执行超时（内部质量项，不计入 AC-1-11） | 真实临时 Fixture 设置 1 秒超时并执行 20 秒睡眠测试，结果为 `timeout`；单元测试覆盖 Pytest/Coverage 两类超时 | **PASS** |
| AC-1-11：静态分析工具超时、输出大小与资源限制 | Stage 1.3 已交付，本阶段未改动静态工具阈值；新增只读校验不改变 AC-1-11 范围 | 不在本阶段变更范围 |

## 8. 安全边界核对

- 外部仓库：`TestRunner.execute(trusted_fixture=None)` 在创建进程前返回，真实 GitHub 仓库测试未执行任何仓库代码。
- 未批准名称、被篡改 Fixture、缺失 Fixture、无 `tests/` 目录：均不创建进程，返回 `not_executed`。
- 未自动安装依赖；未执行 `setup.py`、`build.py` 或安装脚本。
- 未执行外部仓库的 Pytest/Coverage；真实仓库仅做静态分析。
- 测试进程使用仓库外工作目录与最小环境；Fixture 内未产生缓存或字节码。
- 存储结果中的 Fixture/临时目录/宿主用户目录/Python 目录被替换为 `<fixture>`、`<temp>`、`<home>`、`<python>`；测试断言真实 Fixture 输出不包含宿主路径。
- 未修改核心 Schema；`TestSummary` 直接复用阶段 0 合同模型。
- 未提交 `.env`、密钥或 token。

## 9. 尚未完成与待确认事项

- **Stage 1.4 改动未提交**，等待人工审核测试证据。
- **Stage 1.5 未开始**：Finding 映射、聚合、去重、证据管理与 LLM 辅助分析尚未实现。
- 阶段 1 的 `test_report.json` 与 `reporting/artifact_models.py` 属于 Stage 1.6，本阶段只产出工具层 `TestExecutionResult`，不生成报告文件。
- 3 条符号链接用例在 Windows 主机因权限限制跳过；代码路径已实现，但本机未实际执行到。
- 可信 Fixture 执行仍是宿主机原生子进程，不是操作系统级沙箱；该例外仅适用于阶段 1 的项目自维护 Fixture。
- Fixture 校验与执行之间存在理论上的 TOCTOU 窗口；当前依赖 Fixture 受版本控制且由项目维护，执行前后快照用于发现实际修改。

## 10. 是否可进入下一子阶段

建议：**等待人工审核通过后再进入 Stage 1.5**。本阶段 AC-1-09、AC-1-10、AC-1-12 均有真实执行证据，测试执行超时作为内部质量项已验证；未发现需要修改核心 Schema、增加依赖或偏离架构的情况。
