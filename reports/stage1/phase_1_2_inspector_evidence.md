# Stage 1.2 测试证据与验收报告：仓库扫描与源码识别

| 项目 | 内容 |
| --- | --- |
| 报告日期 | 2026-11-10 |
| 实施依据 | `阶段1_Prompt.md` Stage 1.2 与 §五；`docs/acceptance.md` AC-1-04、AC-1-05、§4.7 |
| 实施范围 | Repository Inspector、文件遍历、Python 源码/测试识别、配置/依赖/文档分类、敏感文件过滤、路径安全、统计信息 |
| 当前状态 | **实现与测试完成，未提交；等待项目负责人人工审核** |
| 下一子阶段 | Stage 1.3 **未开始** |
| 测试环境 | Windows 11 / Python 3.12.16 / pytest 9.2.0 |
| 测试结果 | 单元测试 `464 passed, 1 skipped`；真实网络集成测试 `2 passed` |

---

## 1. 本子阶段完成内容

1. **文件过滤策略（`src/code_review/tools/file_filters.py`）**
   - `FileFilterPolicy` 可整体注入替换，所有规则集中且可测试。
   - 排除目录：`.git`、`__pycache__`、`.venv`、`venv`、`node_modules`、`.tox`、`.nox`、`.mypy_cache`、`.pytest_cache`、`.ruff_cache`、`.hypothesis`、`.eggs`、`*.egg-info`、`build`、`dist`。
   - 编译产物：`.pyc`、`.pyo`、`.pyd`、`.so`、`.dll`、`.dylib`、`.o`、`.obj`、`.a`、`.lib`、`.exe`、`.class`、`.jar`、`.whl`、`.egg`。
   - 敏感文件：`.env` 及 `.env.*`、私钥（`id_rsa` 等）、证书/密钥后缀（`.pem`、`.key`、`.p12`、`.pfx`、`.jks`、`.keystore`、`.ppk`、`.kdbx` 等）、凭据文件名，以及 `secrets`/`credentials`/`passwords` 等敏感词干。
   - 二进制判定：文件头部 8 KiB 含 NUL 字节。
   - 私钥内容标记：探针中发现 `PRIVATE KEY-----` 时按敏感文件过滤（覆盖改名的私钥文件）。
   - 其他语言源码（`.js`、`.go`、`.sh`、`.html` 等）记录为 `unsupported_language`，不进入扫描清单。
2. **仓库扫描（`src/code_review/tools/repository_inspector.py`）**
   - 递归遍历、确定性排序、POSIX 相对路径输出。
   - 分类：`python_source`、`python_test`、`project_config`、`dependency_manifest`、`documentation`、`other_text`。
   - 输出字段：路径、类别、语言（Python 为 `python`）、行数、字节大小。
   - Python 文件使用 `tokenize.open` 遵循 PEP 263 编码声明；非 Python 文本按 UTF-8 容错解码。
   - 单文件超过 2 MB：跳过并记录 `oversized`。
   - 总扫描大小达到 50 MB：停止扫描，返回 `is_partial=true`、`partial_reason="total_scan_size_limit"`，不静默截断。
   - `RepositoryStatistics`：各类别文件数、过滤数、排除目录数、总大小、已扫描字节、总行数。
3. **路径安全**
   - 文件的真实路径必须位于仓库根目录内，否则记录 `path_escape`。
   - 符号链接文件/目录在读取或下钻前剪枝。
   - 额外处理 Windows junction：`os.walk(followlinks=False)` 会进入 junction，Inspector 显式识别并剪枝，避免扫描逃逸（已用真实 junction 验证）。
   - 敏感文件与排除目录在打开文件前处理，不读取内容。
4. **真实性约束**
   - 过滤结果只包含路径、原因、大小，不包含文件内容；敏感文件内容不进入返回值、日志或字符串表示。
   - 未修改阶段 0 三个核心 Schema，未引入新依赖。

---

## 2. 文件清单

### 2.1 新增文件

| 文件 | 说明 |
| --- | --- |
| `src/code_review/tools/file_filters.py` | 文件分类、敏感文件/二进制/编译产物/排除目录规则 |
| `src/code_review/tools/repository_inspector.py` | 遍历、读取、行数统计、过滤记录与仓库统计 |
| `tests/unit/test_file_filters.py` | 过滤与分类单元测试（90 条） |
| `tests/unit/test_repository_inspector.py` | Inspector 单元测试（12 条，1 条 Windows 符号链接测试跳过） |
| `tests/integration/test_real_inspection.py` | 真实仓库 Clone + 扫描集成测试（默认跳过） |

### 2.2 修改文件

| 文件 | 说明 |
| --- | --- |
| `src/code_review/tools/__init__.py` | 导出 Inspector、过滤器与统计模型 |

未修改：`docs/task_contracts.md`、阶段 0 三个核心 Schema 文件、阶段 1.1 已提交的实现与测试。

---

## 3. AC 覆盖情况（如实标注）

| AC | 本子阶段实现与证据 | 状态 |
| --- | --- | --- |
| AC-1-04 源码识别与过滤 | Python 源码/测试文件识别，输出路径、语言、行数、大小；过滤二进制、超大文件、`.git`、`node_modules`、`.venv` 及缓存/构建目录；真实仓库扫描验证 | 本子阶段 PASS |
| AC-1-05 敏感文件不进入 LLM 上下文 | 敏感文件在读取内容前过滤；私钥内容标记兜底；测试断言 `.env`/私钥/`secrets.py` 内容不出现在 Inventory 返回值的字符串表示中 | 过滤层 PASS；LLM 调用在 Stage 1.5，最终需在 1.5/1.7 验证上下文只取 `python_files` |

口径说明：

- `setup.py` 归类为 `dependency_manifest` 而不是 `python_source`，因为它主要承担项目/依赖声明职责；如需参与 Python 审查，Stage 1.3 的工具仍可直接扫描仓库文件。
- `other_text` 类文件只用于统计与后续报告，Stage 1.5 的 LLM 上下文必须只从 `python_files` 选取。

---

## 4. 安全边界核验

1. 敏感文件（`.env`、`id_rsa`、`*.pem`、`secrets.py` 等）在 `open()` 之前被过滤，未读取内容。
2. 改名私钥通过二进制探针中的 `PRIVATE KEY-----` 标记识别并过滤，探针内容不保存。
3. 符号链接与 Windows junction 均被剪枝，扫描不会逃逸仓库根目录。
4. 每个文件解析真实路径后再次校验是否位于仓库根内，防止路径穿越。
5. 排除目录在下钻前剪枝，避免遍历 `.git`、`node_modules`、虚拟环境等大目录。
6. 总扫描大小超限时显式标记 partial，不把不完整结果伪装成完整结果。
7. 扫描过程只读，不执行仓库内脚本、测试或安装命令。

---

## 5. 测试证据

### 5.1 单元测试

```text
pytest tests/unit -q
464 passed, 1 skipped in 2.51s
```

其中阶段 1.2 新增：

```text
tests/unit/test_file_filters.py         90 passed
tests/unit/test_repository_inspector.py 11 passed, 1 skipped
```

覆盖：文件分类、测试文件识别、排除目录、敏感文件（含 `.env`、私钥、`secrets.py`）、二进制、超大文件、总扫描大小 partial、定制策略、编码声明、符号链接/junction 逃逸、路径穿越、空仓库、非法根目录、统计字段。

跳过的 1 条为 Windows 下创建符号链接需要开发者模式权限；同一路径安全分支已由 Windows junction 测试真实覆盖。

### 5.2 真实仓库集成测试

```text
RUN_REAL_NETWORK=1 pytest tests/integration -q
2 passed in 7.89s
```

新增 `test_real_inspection.py`：Clone `pallets/itsdangerous` 后扫描，验证：

- 非 partial，Python 源码、测试、依赖清单、文档均被识别；
- 所有路径为 POSIX 相对路径，不含反斜杠、`..`、`.git`；
- Python 文件语言均为 `python`；
- 无 `.pyc`/`.pyo` 进入清单；
- 工作区在退出后清理。

### 5.3 静态检查

```text
ruff check src/code_review/tools tests/unit/test_file_filters.py \
  tests/unit/test_repository_inspector.py tests/integration/test_real_inspection.py
All checks passed!
```

---

## 6. 本子阶段明确未包含

- Ruff / Bandit / Radon 集成（Stage 1.3）。
- Pytest / Coverage 与可信 Fixture（Stage 1.4）。
- Finding 聚合、LLM 调用与 `llm_analysis.rejected[]`（Stage 1.5）。
- 四件产物、CLI、FastAPI、`ReviewService`（Stage 1.6）。
- 仓库只读强制（AC-1-12）不在本子阶段范围。
- 全链路验收（Stage 1.7）。

---

## 7. 待人工审核事项

1. Stage 1.2 的测试证据是否足以确认本子阶段完成。
2. 敏感文件过滤口径（含 `secrets.py`、`credentials.py` 等词干）是否认可。
3. 工作区另存在 `实施决策.md` → `Stage1实施前人工决策.md` 的重命名（未纳入本次 Stage 1.2 改动），请确认是否需要单独处理。
4. 是否确认提交 Stage 1.2 改动；确认前不进入 Stage 1.3。

**结论：Stage 1.2 实现与测试完成，等待人工审核；未提交，Stage 1.3 未开始。**
