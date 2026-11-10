# Stage 1.1 测试证据与验收报告：基础工程与仓库获取

| 项目 | 内容 |
| --- | --- |
| 报告日期 | 2026-11-10 |
| 实施依据 | `阶段1_Prompt.md` Stage 1.1；`实施决策.md`；`docs/acceptance.md` §4.7、AC-1-01～AC-1-03 |
| 实施范围 | 依赖固定、Repository Manager、URL 校验、Clone、Commit SHA 固定、仓库资源限制、单元测试 |
| 当前状态 | **实现与测试完成，未提交；等待项目负责人人工审核** |
| 下一子阶段 | Stage 1.2 **未开始** |
| 测试环境 | Windows 11 / Python 3.12.16 / pytest 9.2.0 |
| 测试结果 | 单元测试 `363 passed, 1 skipped`；真实 Clone 集成测试 `1 passed`（显式启用） |

> 本报告只覆盖 Stage 1.1。AC-1-01～AC-1-03 的端到端验收还需在后续子阶段（ReviewService、报告产物）集成后最终确认；本报告如实区分“本子阶段已完成”与“后续子阶段补齐”。

---

## 1. 本子阶段完成内容

1. **依赖配置**
   - `environment.yml` 固定阶段 1 工具版本：`ruff==0.17.4`、`bandit==1.9.4`、`radon==6.0.1`、`coverage==7.17.2`。
   - 已在 Conda 环境 `multi-agent-review` 安装并验证版本（见 §5.4）。
   - 未引入 LangGraph、Redis、ARQ、PostgreSQL、MCP、A2A、Semgrep、Gitleaks、pip-audit。
2. **集中配置**
   - `config/settings.py` 新增阶段 1 全部阈值（Clone/Git 超时、仓库大小、文件数量、单文件大小、总扫描大小、工具超时与输出、LLM 参数、可信 Fixture 名称、工作区开关）。
   - 强制 `github_allowed_host == "github.com"`、`github_allowed_port == 443`；空 `workspace_root` 归一为 `None`。
   - `.env.example` 同步全部新增配置项。
3. **URL / 分支 / SHA 校验（`src/code_review/tools/url_validator.py`）**
   - 仅接受 `https://github.com/<owner>/<repo>`（允许一个 `.git` 后缀与尾部斜杠）。
   - 拒绝：非 HTTPS、非 `github.com`、非 443 端口、凭据、查询串、片段、额外路径段、`..` 穿越、百分号编码、控制字符、反斜杠、超长 owner/repo/URL。
   - 分支名拒绝选项注入（前导 `-`）、空白、控制字符、Git 非法引用字符、`..`、`@{`、`//`、`.lock`、`HEAD`、`@` 等。
   - Commit SHA 仅接受 40 位十六进制并归一为小写。
4. **Repository Manager（`src/code_review/tools/repository_manager.py`）**
   - `GitClient`：参数数组、`shell=False`、`stdin=DEVNULL`、最小化环境、隔离 Git 配置、HTTPS-only 协议、禁用交互提示、输出上限 64 KiB、超时/资源超限终止整个进程树。
   - `RepositoryManager.clone`：URL/分支/SHA 全部在调用 Git 前校验；Clone 使用 `--no-checkout --depth=1 --single-branch --no-recurse-submodules`，并强制 `http.followRedirects=false`、`http.sslVerify=true`、`core.symlinks=false`、`submodule.recurse=false`、`credential.helper=`、`protocol.file.allow=never`。
   - SHA 固定：解析 Tip SHA，必要时按 SHA 抓取，detached checkout 后再校验一次；不一致抛 `CommitResolutionError`。
   - 资源限制：Clone 过程中按轮询监控工作区大小；完成后复核仓库大小与文件数量；超过单文件上限的文件记录到 `RepositorySnapshot.oversized_files`。
   - 工作区只能创建在 `workspace_root` 内；只清理自己创建的工作区；失败默认清理，`keep_workspace_on_failure=true` 时保留；隔离 Git 配置文件始终删除。
5. **测试标记**
   - `pytest.ini` 注册 `real_network` 与 `llm_smoke`，默认不运行真实网络测试。

---

## 2. 文件清单

### 2.1 新增文件

| 文件 | 说明 |
| --- | --- |
| `src/code_review/tools/__init__.py` | 工具层导出 |
| `src/code_review/tools/url_validator.py` | GitHub URL、分支名、Commit SHA 校验 |
| `src/code_review/tools/repository_manager.py` | Git 子进程封装、Clone、SHA 固定、资源限制、工作区生命周期 |
| `tests/unit/test_url_validator.py` | URL/分支/SHA 校验单元测试（112 条） |
| `tests/unit/test_repository_manager.py` | Repository Manager 单元测试（26 条） |
| `tests/unit/test_settings_stage1.py` | 阶段 1 配置阈值与主机约束测试（21 条） |
| `tests/integration/test_real_clone.py` | 真实网络 Clone 集成测试（默认跳过；`RUN_REAL_NETWORK=1` 启用） |

### 2.2 修改文件

| 文件 | 说明 |
| --- | --- |
| `environment.yml` | 固定 ruff / bandit / radon / coverage 版本 |
| `config/settings.py` | 新增阶段 1 阈值与 GitHub 主机/端口约束 |
| `.env.example` | 同步阶段 1 配置项 |
| `pytest.ini` | 注册 `real_network`、`llm_smoke` 标记 |

未修改：`docs/task_contracts.md`、阶段 0 三个核心 Schema 文件、任何阶段 0 测试文件。

---

## 3. AC 覆盖情况（如实标注）

| AC | 本子阶段实现与证据 | 状态 |
| --- | --- | --- |
| AC-1-01 Clone + 固定完整 Commit SHA | 真实 Clone `pallets/itsdangerous`，返回 40 位 SHA；`.git/HEAD` 与 SHA 一致；按 SHA 再次 Clone 结果一致。写入审查上下文尚无 `ReviewService`，待 Stage 1.5/1.6 集成 | 组件完成，端到端待后续子阶段 |
| AC-1-02 URL 校验 | 112 条单元测试覆盖 HTTP/SSH/file/本地路径、非 GitHub 域名、IP、非常规端口、凭据、查询串/片段、路径穿越、编码、控制字符与命令注入字符；校验发生在任何 Git 调用之前（测试断言 Git 调用数为 0） | 本子阶段 PASS |
| AC-1-03 资源限制 | 仓库大小：Clone 轮询监控 + 完成后复核；文件数量：超限拒绝；单文件大小：检测并记录 `oversized_files`；下载/Git 命令超时：终止进程树并抛 `GitTimeoutError`。单文件“跳过”按 §4.7 属扫描期行为，Stage 1.2（AC-1-04）实现 | 大小/数量/超时 PASS；单文件跳过待 1.2 |

---

## 4. 安全边界核验

1. 不可信仓库不执行任何内容：本子阶段仅 `git clone` / `fetch` / `checkout` / `rev-parse`，未运行仓库内脚本、测试或安装命令。
2. Git 调用全部使用参数数组与 `shell=False`；URL 经规范化后才以 `--` 分隔传入，避免选项注入。
3. Git 环境隔离：`GIT_CONFIG_NOSYSTEM=1`、独立 `GIT_CONFIG_GLOBAL`、`GIT_ALLOW_PROTOCOL=https`、`GIT_TERMINAL_PROMPT=0`、`GIT_LFS_SKIP_SMUDGE=1`，不继承 LLM Key 等宿主环境变量。
4. Clone 关闭重定向、子模块递归、符号链接、fsmonitor 与外部 credential helper。
5. 超时与资源超限终止整个进程树（Windows `taskkill /T`，POSIX `killpg`），避免残留子进程。
6. 工作区创建与删除均限制在 `workspace_root` 内；`cleanup` 拒绝删除非本管理器创建的路径。
7. `.env` 仍被 Git 忽略（`git check-ignore .env` 输出 `.env`）。

---

## 5. 测试证据

### 5.1 单元测试

```text
pytest tests/unit -q
363 passed in 2.23s
```

其中阶段 0 回归 204 条全部通过；Stage 1.1 新增 159 条：

```text
tests/unit/test_url_validator.py        112 passed
tests/unit/test_repository_manager.py    26 passed
tests/unit/test_settings_stage1.py       21 passed
```

Repository Manager 测试覆盖：URL/分支/SHA 前置拒绝、Clone 安全参数、分支传递、按 SHA 抓取与检出、SHA 不一致回滚、Clone 失败清理、超时清理、`keep_workspace_on_failure`、仓库大小/文件数量/单文件检测、`.git` 排除、目标目录限制、非托管工作区拒绝清理、上下文管理器清理、隔离配置清理、`shell=False` 与最小环境、Git 不存在、超时与资源监控终止进程树。

### 5.2 真实 Clone 集成测试

```text
RUN_REAL_NETWORK=1 pytest tests/integration/test_real_clone.py -q
1 passed in 6.25s
```

验证：Clone `https://github.com/pallets/itsdangerous` 分支 `main`；返回 40 位 SHA；`.git/HEAD` 与快照 SHA 一致；按该 SHA 再次 Clone 得到相同提交；退出上下文后工作区已清理。

默认运行 `pytest` 时该测试标记为 `skipped`（需显式 `RUN_REAL_NETWORK=1`）。

### 5.3 静态检查

```text
ruff check config/settings.py src/code_review/tools \
  tests/unit/test_url_validator.py tests/unit/test_repository_manager.py \
  tests/unit/test_settings_stage1.py tests/integration/test_real_clone.py
All checks passed!
```

注：对全仓库运行 ruff 会命中阶段 0 既有文件 `tests/unit/test_report_schema.py` 的 `re.S` 风格提示；本子阶段未修改该文件，未擅自改动阶段 0 测试。

### 5.4 依赖与禁止项探针

```text
ruff 0.17.4
bandit 1.9.4
radon 6.0.1
Coverage.py 7.17.2
基础依赖导入：deps ok
FORBIDDEN: []
PASSIVE-ALLOWED: ['opentelemetry-api']
```

未安装或引入 LangGraph、LangChain、Redis、ARQ、PostgreSQL、SQLAlchemy、MCP、A2A、LangSmith、Streamlit 等阶段 1 禁止项。

---

## 6. 本子阶段明确未包含

- Repository Inspector、文件遍历、Python 源码识别、敏感文件过滤、路径安全（Stage 1.2）。
- Ruff / Bandit / Radon 集成（Stage 1.3）。
- Pytest / Coverage 与可信 Fixture（Stage 1.4）。
- Finding 聚合、LLM 分析、`llm_analysis.rejected[]`（Stage 1.5）。
- 四件产物、CLI、FastAPI、`ReviewService`（Stage 1.6）。
- 全链路验收与 AC-1-01/03 的端到端签收（Stage 1.7）。

---

## 7. 待人工审核事项

1. Stage 1.1 的测试证据是否足以确认本子阶段完成。
2. 是否同意将单文件“跳过并记录”按 §4.7 放到 Stage 1.2（AC-1-04）实现；本子阶段只做检测与记录。
3. 是否确认提交 Stage 1.1 改动（清单见 §2，含本报告）；确认前不进入 Stage 1.2。

**结论：Stage 1.1 实现与测试完成，等待人工审核；未提交，Stage 1.2 未开始。**
