# Stage 1.3 测试证据与验收报告：静态分析工具集成

| 项目 | 内容 |
| --- | --- |
| 报告日期 | 2026-11-10 |
| 实施依据 | `阶段1_Prompt.md` Stage 1.3 与 §十七；`docs/acceptance.md` AC-1-06、AC-1-07、AC-1-08、AC-1-11 |
| 实施范围 | 受限子进程执行器、统一工具接口、Ruff / Bandit / Radon 集成、结构化输出、异常处理、资源限制、对应测试 |
| 当前状态 | **实现与测试完成，未提交；等待项目负责人人工审核** |
| 下一子阶段 | Stage 1.4 **未开始** |
| 测试环境 | Windows 11 / Python 3.12.16 / pytest 9.2.0 / ruff 0.17.4 / bandit 1.9.4 / radon 6.0.1 |
| 测试结果 | 单元测试 `542 passed, 1 skipped`；含真实网络的全量测试 `545 passed, 1 skipped` |

---

## 1. 本子阶段完成内容

1. **受限子进程执行器（`src/code_review/tools/process_runner.py`）**
   - 只接受参数数组，`shell=False`，不经过 shell 解析，元字符按字面量传递。
   - `stdin=DEVNULL`；最小化环境变量白名单（仅 PATH、SystemRoot、COMSPEC、TEMP/TMP、HOME、USERPROFILE、LANG 等），不继承 `PYTHONPATH` 等可注入变量。
   - 每路输出独立上限（默认 5 MiB），读取线程持续排空管道，超限部分不保留并设置截断标记。
   - 超时后终止整个进程树：Windows 使用 `taskkill /F /T /PID`，POSIX 使用进程组；失败时回退 `kill`。
   - 统一状态：`completed`、`timeout`、`not_found`、`os_error`；输出按 UTF-8 解码。
2. **统一工具接口（`src/code_review/tools/base.py`）**
   - `AnalysisTool` 模板方法：子类只负责构造命令、执行阶段与解析输出；路径校验、进程调用、超时、输出上限、Finding 上限、结果汇总由基类统一处理。
   - 输入校验：工作区必须存在且为目录；文件必须是仓库内已存在的 `.py` 文件；拒绝绝对路径、反斜杠、`..`、缺失文件、目录、符号链接/junction 逃逸；重复路径只分析一次。
   - `ToolFinding`：工具层 DTO，字段含工具名、规则 ID、POSIX 相对路径、消息、起止行、列、严重度、置信度与工具元数据；构造时再次校验路径与行号。
   - `ToolExecutionResult`：工具版本、执行状态、退出码、起止时间、耗时、stdout/stderr、Finding 元组、`ErrorInfo`、分析文件数及三类截断标记。
   - 错误直接使用阶段 0 合同 `ErrorInfo`：`timeout`（`retryable=true`）、`tool_error`、`invalid_input`。
   - 工具版本通过 `importlib.metadata` 从已安装发行版读取；无法确定时返回 `null`，不硬编码到业务代码。
   - 命令长度分批：默认上限 24,000 字符，避免 Windows 命令行长度限制；所有批次共享同一工具级超时预算。
   - Finding 数量上限来自 `Settings.max_tool_findings`（默认 1000），超出时保留前 N 条并标记 `findings_truncated`。
3. **Ruff 集成（`src/code_review/tools/ruff_tool.py`）**
   - 命令：`python -I -B -X utf8 -m ruff check --isolated --no-cache --output-format json -- <显式文件列表>`。
   - `--isolated` 忽略被评审仓库的 Ruff 配置；`--` 终止选项解析，避免以 `-` 开头的路径被当作参数。
   - 解析规则 ID、消息、绝对/相对文件名、起止行列、严重度、规则名称/文档链接/修复信息；异常路径映射为解析错误。
4. **Bandit 集成（`src/code_review/tools/bandit_tool.py`）**
   - 在仓库外临时目录创建空 `[bandit]` 配置，命令使用 `-f json -q --ini <空配置> <显式文件列表>`，避免读取仓库内的 Bandit 配置。
   - 解析 `test_id`、`issue_text`、文件、行号/行范围、列、严重度、置信度、CWE、规则名与文档链接。
   - Bandit 的 `errors[]` 表示部分文件分析失败：即使同时有 Finding，也标记为 `partial` 并保留 Finding 与错误数量，不伪装为完整成功。
5. **Radon 集成（`src/code_review/tools/radon_tool.py`）**
   - 每批次依次执行 `radon cc --json` 与 `radon mi --json`。
   - 复杂度：解析代码块类型、名称、起止行、复杂度、rank，规则 ID 为 `RADON_CC`。
   - 可维护性：解析 MI 值与 rank，规则 ID 为 `RADON_MI`。
   - 只有两阶段均成功才增加已分析文件数；后一阶段失败时保留前一阶段已解析的 Finding，并以失败状态返回。
6. **结果汇总与失败隔离**
   - `success`：正常执行且无 Finding；`findings`：正常执行并产生 Finding；`partial`：完成但部分文件失败；`timeout` / `not_found` / `parse_error` / `failed`：执行异常。
   - 一个工具失败不会清空或覆盖其他工具的结果；跨批次时，已完成批次的 Finding 保留。
   - 所有工具失败均返回结构化结果，不向调用方抛出未捕获异常。
7. **真实性约束**
   - 只做静态分析；不执行被评审仓库的测试、安装脚本、构建脚本或仓库代码。
   - 工具进程工作目录为仓库外临时目录，Python 使用 `-I`，避免仓库内同名模块劫持。
   - 工具只接收调用方显式传入的 `.py` 文件列表，不扫描仓库根目录，因此阶段 1.2 已过滤的敏感文件不会进入工具参数。
   - 未修改阶段 0 三个核心 Schema，未引入新依赖。

---

## 2. 文件清单

### 2.1 新增文件

| 文件 | 说明 |
| --- | --- |
| `src/code_review/tools/process_runner.py` | 受限子进程执行器、输出截断、超时与进程树终止 |
| `src/code_review/tools/base.py` | 统一工具接口、输入校验、分批、状态汇总、工具层 DTO |
| `src/code_review/tools/ruff_tool.py` | Ruff 命令构造与 JSON 解析 |
| `src/code_review/tools/bandit_tool.py` | Bandit 命令构造、JSON 解析与部分失败处理 |
| `src/code_review/tools/radon_tool.py` | Radon 复杂度与可维护性解析 |
| `tests/unit/test_process_runner.py` | 子进程执行器测试（8 条） |
| `tests/unit/test_tool_base.py` | 公共接口、输入安全、版本与合同类型测试（18 条） |
| `tests/unit/test_ruff_tool.py` | Ruff 解析与执行测试（16 条） |
| `tests/unit/test_bandit_tool.py` | Bandit 解析与执行测试（16 条） |
| `tests/unit/test_radon_tool.py` | Radon 解析与执行测试（20 条） |
| `tests/integration/test_real_static_analysis.py` | 真实仓库 Clone + 三工具静态分析集成测试（默认跳过） |

### 2.2 修改文件

| 文件 | 说明 |
| --- | --- |
| `src/code_review/tools/__init__.py` | 导出工具接口、结果模型、三个工具与解析函数 |

未修改：`docs/task_contracts.md`、阶段 0 三个核心 Schema 文件、`environment.yml`、阶段 1.1/1.2 已提交的实现与测试。

---

## 3. 核心设计决策

1. **`ToolFinding` 不是合同 `Finding`**
   - 本阶段不修改 `schemas/result.py`，也不提前填充 `Finding` 的必填字段（如 `agent_name`、`verification_status`、证据 ID）。
   - Stage 1.5 统一将 `ToolFinding` 映射为 `docs/task_contracts.md` 的正式 `Finding`；阶段 1 全部 Finding 保持 `unverified`。
2. **显式文件列表而非仓库根目录**
   - 工具参数来自 `RepositoryInventory.python_files`；阶段 1.2 已排除敏感文件、二进制、超大文件、`.git` 等目录。
   - 即使工具自身支持目录扫描，也不传入仓库根目录，避免敏感文件被工具读取后进入 stdout/日志。
3. **仓库外工作目录 + 隔离配置**
   - Ruff `--isolated`、Bandit `--ini` 空配置、Radon 无配置读取；工作目录为临时目录。
   - 防止被评审仓库通过 `pyproject.toml` / `.bandit` 改变工具行为或扩大读取范围。
4. **`python -I` 启动工具**
   - `-I` 隔离模式不把脚本目录/当前目录加入 `sys.path`，避免仓库内同名模块（如伪造的 `json.py`）被工具导入。
5. **统一超时预算与输出上限**
   - 一次工具执行的所有批次共享 `static_tool_timeout_seconds`，避免“每批都超时”导致总时长失控。
   - stdout/stderr 各 5 MiB、Finding 1000 条，超限显式标记，不静默伪装完整。
6. **失败隔离**
   - 每个工具独立返回 `ToolExecutionResult`；部分批次失败时保留已完成批次 Finding，但状态反映失败。
   - Bandit 的文件级 `errors[]` 归为 `partial`，因为此时输出不完整。

---

## 4. 安全边界核验

1. 子进程 `shell=False`，命令以参数数组传递；测试用 `a&b`、`c|d`、`$HOME`、`x y` 验证元字符不被展开。
2. 环境变量白名单不包含 `PYTHONPATH`、`PYTHONSTARTUP` 等可影响解释器行为的变量。
3. `-I` 阻止仓库内同名模块劫持工具；工作目录在仓库外，避免工具自动读取仓库配置。
4. 工具输出路径必须解析到工作区内，否则按解析错误拒绝；测试覆盖绝对路径逃逸、`..`、反斜杠、Windows junction。
5. 工具只接收显式 `.py` 文件列表；阶段 1.2 的敏感文件过滤结果不会被绕过。
6. 不执行被评审仓库的任何脚本、测试或安装命令；集成测试断言工作区未生成 `.pytest_cache`。
7. 超时终止整个进程树，避免子进程残留；每路输出有硬上限，避免内存被不可信输出耗尽。
8. 错误信息只包含工具名、批次序号、阶段、退出码等元数据，不包含文件内容、密钥或主机敏感路径。

---

## 5. 测试证据

### 5.1 阶段 1.3 单元测试

```text
pytest tests/unit/test_process_runner.py tests/unit/test_tool_base.py \
  tests/unit/test_ruff_tool.py tests/unit/test_bandit_tool.py \
  tests/unit/test_radon_tool.py -v
78 passed in 5.60s
```

明细：

- `test_process_runner.py`：8 条。输出/退出码、无 shell 参数传递、两路截断标记、UTF-8、真实超时终止、可执行文件缺失、工作目录缺失、空命令拒绝。
- `test_tool_base.py`：18 条。Finding 路径/行号/消息校验、截断属性、安装版本读取、发行版缺失、非法输入不启动进程、缺失文件、重复路径去重、junction 逃逸、`ErrorInfo` 合同类型。
- `test_ruff_tool.py`：16 条。字段解析、非法 JSON/空输出/错误形状/越界路径、真实 F401 执行、真实干净文件、空列表不启动进程、可执行文件缺失、超时、解析错误、非预期退出码、Finding 上限、流截断标记、分批、后批超时保留前批结果。
- `test_bandit_tool.py`：16 条。字段解析、`errors[]` 计数、非法输出、越界路径、真实 B605 执行、真实干净文件、部分失败 `partial`、无 Finding 的 `errors[]`、缺失可执行文件、超时、解析错误、非预期退出码、Finding 上限、空列表。
- `test_radon_tool.py`：20 条。CC/MI 字段解析、空对象、非法 JSON/空输出/错误形状/畸形块/非法结束行/越界路径、真实 CC+MI 执行、空列表、缺失可执行文件、CC 超时、MI 失败保留 CC、CC/MI 解析错误、非预期退出码、Finding 上限、分批两阶段顺序。

### 5.2 全量单元回归

```text
pytest tests/unit -q
542 passed, 1 skipped in 7.64s
```

阶段 1.2 基线为 `464 passed, 1 skipped`；本阶段新增 78 条单元测试。跳过的 1 条仍是阶段 1.2 中 Windows 创建符号链接需开发者模式的测试，同一路径安全分支已由 Windows junction 测试覆盖。

### 5.3 真实仓库集成测试

```text
RUN_REAL_NETWORK=1 pytest tests/integration/test_real_static_analysis.py -v
1 passed in 7.31s
```

测试内容：Clone `https://github.com/pallets/itsdangerous`（`main`），用 Inspector 获取 Python 文件列表，对列表执行三个真实工具。实际结果：

| 项目 | 结果 |
| --- | --- |
| 固定 Commit SHA | `672971d66a2ef9f85151e53283113f33d642dabd` |
| Inspector partial | `False` |
| Python 文件数 | 15 |
| Ruff | `findings`，exit 1，版本 0.17.4，分析 15，Finding 17，无截断，无错误 |
| Bandit | `findings`，exit 1，版本 1.9.4，分析 15，Finding 68，无截断，无错误 |
| Radon | `findings`，exit 0，版本 6.0.1，分析 15，Finding 155，无截断，无错误 |
| `.pytest_cache` | 不存在 |
| 工作区清理 | 退出后为空 |

三个工具的全部 Finding 路径均为仓库相对 POSIX 路径、无 `..`/反斜杠且属于已传入文件列表；Radon 为每个函数/方法输出复杂度块，因此真实结果必然非空，测试对 `RADON_CC` 做了断言。

### 5.4 含真实网络的全量测试

```text
RUN_REAL_NETWORK=1 pytest tests -q
545 passed, 1 skipped in 27.13s
```

### 5.5 静态检查

```text
ruff check src/code_review/tools tests/unit/test_process_runner.py \
  tests/unit/test_tool_base.py tests/unit/test_ruff_tool.py \
  tests/unit/test_bandit_tool.py tests/unit/test_radon_tool.py \
  tests/integration/test_real_static_analysis.py
All checks passed!
```

---

## 6. AC 覆盖情况（如实标注）

| AC | 本子阶段实现与证据 | 状态 |
| --- | --- | --- |
| AC-1-06 Ruff 输出结构化检查结果 | 真实 Ruff JSON 解析为 `ToolFinding`（规则 ID、路径、起止行列、严重度、元数据）；真实仓库 17 条结果；单元测试覆盖字段映射与异常输出 | 本子阶段 PASS |
| AC-1-07 Bandit 输出结构化安全检查结果 | 真实 Bandit JSON 解析（test_id、行号/行范围、严重度、置信度、CWE）；真实仓库 68 条结果；`errors[]` 标为 partial | 本子阶段 PASS |
| AC-1-08 Radon 输出结构化复杂度结果 | `cc --json` 与 `mi --json` 均解析为结构化 Finding；真实仓库 155 条结果；单元测试覆盖两阶段失败保留 | 本子阶段 PASS |
| AC-1-11 静态分析工具超时、输出大小与资源限制 | 工具级超时预算、进程树终止、stdout/stderr 各 5 MiB、Finding 上限 1000、分批命令长度；真实进程超时与 mock 超时均有测试 | 本子阶段 PASS |

说明：AC-1-11 的“资源限制”在静态分析范围内包括输出大小、Finding 数量与命令长度；仓库文件数量/大小限制由 Stage 1.1/1.2 的 Clone 与扫描限制负责，本报告不重复计为 Stage 1.3 证据。

---

## 7. 尚未完成的任务

- Stage 1.4：Pytest / Coverage、可信 Fixture、测试执行安全策略、外部仓库 `not_executed` 状态、测试执行超时与输出限制。
- Stage 1.5：`ToolFinding` → 合同 `Finding` 映射、聚合、去重、证据管理、LLM 辅助分析、Prompt Injection 防护、模型失败处理。
- Stage 1.6：四件产物（`metadata.json`、`static_analysis.json`、`test_report.json`、`report.md`）、`ReviewService`、CLI、FastAPI。
- Stage 1.7：全链路验收与安全测试。
- 本子阶段改动尚未提交；未开始 Stage 1.4。

---

## 8. 架构偏离检查

- 新增模块均位于 `src/code_review/tools/`，符合 `docs/architecture.md` 的分层与目录约定；`base.py` 为架构规定的统一工具接口位置。
- 依赖方向仍为 `schemas → tools`；`tools` 未依赖 `agents`、`graph`、`orchestration`。
- 未修改阶段 0 三个核心 Schema、`docs/task_contracts.md` 或冻结文档。
- 未引入任何新依赖；Ruff/Bandit/Radon 版本与 `environment.yml` 固定值一致。
- `ToolFinding` / `ToolExecutionResult` 是工具层内部 DTO，未新增合同字段，不构成合同偏离。

**结论：Stage 1.3 实现与测试完成，AC-1-06 / AC-1-07 / AC-1-08 / AC-1-11 本子阶段 PASS；未提交，等待人工审核；Stage 1.4 未开始。**
