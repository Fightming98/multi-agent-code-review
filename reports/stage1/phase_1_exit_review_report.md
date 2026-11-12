# 阶段 1 收尾核查报告（Stage 1 Exit Review）

- 报告版本：v1.0
- 生成日期：2026-11-10
- 审计对象：`multi-agent-review` 阶段 1（Stage 1.1～Stage 1.7）
- 审计基线：Git `HEAD = a7d384d`（阶段 1.6）＋ 工作区中尚未提交的 Stage 1.7 改动
- 审计性质：**审计阶段只读**。审计期间未修改代码、文档、Schema 或依赖，未执行任何改变 Git 状态的命令；收尾执行阶段按用户 2026-11-10 批准完成 MF-1、生成 `environment.lock.yml` 并提交 Stage 1.7（见 §11）。未进入阶段 2
- 最终结论：**READY**（阶段 1 验收基线满足；MF-1 已修复；提交按用户批准的显式清单执行）

> 本报告中的“通过”只表示本轮实际执行并取得的结果。未在本轮复跑的项会明确标注“本轮未复跑”，不以阶段 1.7 验收报告的结论替代独立核查，也不把未执行项写成通过。

---

## 1. 审计范围与依据

### 1.1 审计范围

| 范围 | 内容 |
| --- | --- |
| 符号链接安全 | 仓库扫描、敏感文件过滤、可信 Fixture 校验、Pytest/Coverage 前后只读快照 |
| Finding/LLM 统计 | 真实产物 `reports/stage1-20261110T120331Z-d8333a8c/` 的 240/91/90/1/49/1 口径 |
| 依赖与环境 | Python、直接/关键传递依赖、`environment.yml`、干净环境可复现性 |
| 正式文档一致性 | 仅 `docs/requirements.md`、`docs/architecture.md`、`docs/workflow.md`、`docs/task_contracts.md`、`docs/acceptance.md` |
| Git 与提交准备 | 工作区状态、Schema/文档 diff、未跟踪文件、推荐提交与排除清单 |
| 技术债 | 阶段 0 冻结 Schema 的 Ruff 提示、LLM 语义不确定性、同步单槽、第三方代码片段、Windows 符号链接限制 |

### 1.2 审计依据

- 本轮任务书：`Stage 1 Exit Review：阶段收尾核查与 Stage 2 启动前准备`（Task 1～Task 5）
- `docs/acceptance.md`（v1.3，阶段 1 基线；§4.7～§4.11）
- `docs/architecture.md`（v1.1；§7.1.1、§8.1）
- `docs/workflow.md`（v1.1；§8.7、§10）
- `docs/task_contracts.md`（v1.0；Finding/AgentResult/ReviewReport 合同）
- `docs/requirements.md`（v1.1；FR/NFR、安全边界）
- 实际代码、测试、真实产物与 Git 工作区

### 1.3 审计环境

| 项 | 值 |
| --- | --- |
| 宿主 OS | Windows 11 Pro 10.0.26100 |
| Conda | 25.7.0 |
| 项目环境 | `multi-agent-review` |
| Python | 3.12.16（项目 Conda 环境 `multi-agent-review` 的解释器） |
| pip | 26.2.2 |
| Git | 2.49.0.windows.1 |
| Linux 复核环境 | WSL `Ubuntu 24.04.2 LTS`；Python 3.13.9（仅用于符号链接测试复核） |

> 重要操作提示：宿主 PATH 上的 `python` 指向 Anaconda base 环境（本轮观测为 fastapi 0.110.2 / pydantic 2.13.4 / pytest 7.4.4），**不是**项目环境。所有项目命令必须使用 `conda run -n multi-agent-review` 或项目环境的绝对解释器，否则会得到不同的依赖版本与不同的测试结果。该差异已列入第 4 节与第 10 节。

### 1.4 本轮实际执行的命令与结果

| 命令 | 结果 | 说明 |
| --- | --- | --- |
| `pytest tests/unit -q`（项目环境） | **820 passed, 4 skipped, 1 warning in 16.21s** | 4 条 skip 均为 Windows 符号链接限制；非失败 |
| `pytest tests/integration -q -m "not real_network and not llm_smoke"` | **11 passed, 4 deselected in 15.03s** | 4 条为显式门控：3 条 `real_network`＋1 条 `llm_smoke` |
| `pytest tests/unit/test_task_schema.py tests/unit/test_result_schema.py tests/unit/test_report_schema.py -q` | **204 passed in 0.51s** | 阶段 0 Schema 回归 |
| Windows 符号链接 5 条定向测试 | **1 passed, 4 skipped in 0.63s** | 通过的是 Windows junction 测试；4 条 skip 原因见第 2 节 |
| WSL Linux 4 条符号链接测试 | **4 passed in 2.17s** | 本轮重新执行，非引用旧报告 |
| `pytest tests/integration/test_llm_smoke.py -q`（默认） | **1 skipped in 1.68s** | 未设置 `RUN_LLM_SMOKE=1`，按设计跳过 |
| `RUN_LLM_SMOKE=1 pytest tests/integration/test_llm_smoke.py -q -s` | **1 passed in 2.75s** | MF-1 修复后验证；模型 `deepseek-ai/DeepSeek-V3`，usage 54，latency 2153 ms |
| WSL Linux Inspector 探针 | 仅 `normal.py` 进入分析；`innocent.py`、`linkdir` 均以 `symlink` 过滤 | 见 §2.3 |
| WSL Linux 可信 Fixture 探针 | 文件链接与根目录链接均被拒绝 | 见 §2.3 |
| WSL Linux 快照探针 | 链接记录为 `link`，未跟随 | 见 §2.3 |

**本轮未复跑、不得表述为新通过的项目：**

- 真实 GitHub Clone（`real_network`）
- 真实整仓扫描（`pallets/itsdangerous`）

以上两项引用 `reports/phase_1_acceptance_report.md` 中 Stage 1.7 的既有证据（Commit `672971d66a2ef9f85151e53283113f33d642dabd`、模型 `deepseek-ai/DeepSeek-V3`、LLM usage `prompt=15,900 / completion=2,900 / total=18,800`）。真实 LLM 冒烟已在 MF-1 修复后重新执行（1 passed，usage 54），但它只验证最小结构化输出，不等同于整仓扫描的 LLM 阶段。

---

## 2. 符号链接安全测试复核

### 2.1 测试执行矩阵

| 测试 | 文件:行 | Windows 结果 | WSL Linux 结果 | 覆盖点 |
| --- | --- | --- | --- | --- |
| `test_symlink_escape_is_filtered` | `tests/unit/test_repository_inspector.py:194` | SKIP：`symlinks are not available on this platform` | **PASS** | 仓库内文件/目录符号链接指向仓库外时被过滤 |
| `test_windows_junction_escape_is_filtered` | `tests/unit/test_repository_inspector.py:218` | **PASS** | SKIP：非 Windows 平台 | Windows junction 逃逸被过滤 |
| `test_symlinked_fixture_file_is_rejected` | `tests/unit/test_trusted_fixture.py:218` | SKIP：`symbolic links are not permitted on this host` | **PASS** | Fixture 内文件链接被拒绝 |
| `test_symlinked_fixture_root_is_rejected` | `tests/unit/test_trusted_fixture.py:230` | SKIP：同上 | **PASS** | Fixture 根目录链接被拒绝 |
| `test_symlink_is_recorded_without_following` | `tests/unit/test_workspace_snapshot.py:95` | SKIP：同上 | **PASS** | 快照记录链接但不跟随目标 |

结论：

- Windows 宿主机因权限/平台限制无法创建符号链接，4 条测试被跳过；这不是失败，也没有被伪造成通过。
- 同一批测试在 WSL Linux 上**真实执行并通过**（4 passed）。另有 Windows junction 测试在本机真实通过。
- 因此 Stage 1 的符号链接边界具备跨平台证据，而不是只有 Windows 的 skip 记录。

### 2.2 代码层边界核查

#### 2.2.1 Repository Inspector

`src/code_review/tools/repository_inspector.py`：

- 使用 `os.walk(resolved_root, topdown=True, followlinks=False)`，不跟随目录链接。
- 目录链接在下降前过滤：`FilterReason.SYMLINK`，并从 `dirnames` 中移除。
- 文件链接在 `resolve()` 与敏感文件判断之前过滤：`FilterReason.SYMLINK`。
- 对非链接文件再做 `resolve(strict=True)` 与 `is_relative_to(resolved_root)` 检查，越界记 `PATH_ESCAPE`。
- `_is_link()` 同时识别 `is_symlink()` 与 `is_junction()`。

**关键顺序**：符号链接过滤发生在敏感文件判断之前。因此“把敏感文件改成看似无害的链接名”不会绕过敏感文件过滤，链接本身会先被排除。

#### 2.2.2 敏感文件过滤

`src/code_review/tools/file_filters.py`：

- 按文件名、stem、前缀、后缀识别 `.env`、私钥、凭证等敏感路径。
- 过滤阶段不读取文件内容；内容级私钥标记检测在 Inspector 的读取探针中完成。
- 符号链接先于敏感路径规则被排除，因此链接不能成为敏感文件进入 LLM 上下文的通道。

#### 2.2.3 可信 Fixture

`src/code_review/tools/trusted_fixture.py`：

- `verify_trusted_fixture()` 先 `resolve(strict=True)`，再拒绝根目录链接/junction。
- 拒绝 `FIXTURE_MANIFEST.json` 本身是链接。
- `_actual_file_set()` 以 `followlinks=False` 遍历，遇到任何文件/目录链接或 junction 立即抛出 `TrustedFixtureError`。
- 清单必须与真实文件集合完全一致，逐文件 SHA-256 校验，拒绝重复键、缺失、额外文件、非普通文件、超大文件。
- `review_service` 生产路径只允许默认 Fixture 根目录与白名单名称；`review_trusted_fixture()` 不经 CLI/API 暴露。

#### 2.2.4 Pytest/Coverage 前后只读快照

`src/code_review/tools/test_runner.py` 与 `src/code_review/tools/workspace_snapshot.py`：

- 执行前 `snapshot_workspace(fixture.root, excluded_dirs=())`，执行后再次快照并 `compare_snapshots()`。
- 快照对文件/目录链接记录 `"link"` 标记，不跟随目标；目录链接从 `os.walk` 中移除。
- 任一路径新增、删除或哈希变化，`_finalize()` 将 `read_only_verified` 置为 false，并记录 `read_only_violation`。
- 测试执行设置 `PYTHONDONTWRITEBYTECODE=1`，避免 `__pycache__` 噪声。
- **这是检测机制，不是沙箱/强制只读机制**：它发现“执行后状态与执行前不一致”，但不阻止进程在运行期间写文件。

#### 2.2.5 静态分析工具

`src/code_review/tools/base.py`：

- 工具只接收 `inventory.python_files`，该列表已排除链接与越界路径。
- `_prepare_files()` 对每个路径再次 `resolve(strict=True)`，并拒绝 `resolved` 不在 workspace 内的路径；随后还要求 `is_file()`。
- 因此即使上游过滤出现遗漏，工具层仍有第二道路径校验。

#### 2.2.6 Clone 阶段

`src/code_review/tools/repository_manager.py`：

- Git clone 使用隔离配置，显式设置 `core.symlinks=false`、`submodule.recurse=false`、`protocol.file.allow=never`、`http.followRedirects=false`。
- `core.symlinks=false` 使 Git 在检出时把链接条目写成普通文件，而不是在宿主机创建链接；这是对克隆仓库的第一道防线。
- 资源统计使用 `os.walk(..., followlinks=False)` 与 `os.lstat()`，不会因链接把外部目标大小计入。

### 2.3 Linux 探针结果（本轮重新执行）

| 探针 | 构造 | 结果 |
| --- | --- | --- |
| Inspector 文件链接逃逸 | `repo/innocent.py -> ../outside/secret.env` | 未进入 `python_files`；`filtered=[('innocent.py','symlink')]` |
| Inspector 目录链接逃逸 | `repo/linkdir -> ../outside` | 未下降；记录为 `symlink` |
| Fixture 文件链接 | 合法清单 + `evil.py -> ../outside/secret.env` | `TrustedFixtureError: fixture contains a symbolic link or junction` |
| Fixture 根目录链接 | `link -> real_fixture` | `TrustedFixtureError: trusted fixture directory must not be a link` |
| 快照链接处理 | 工作区含文件链接与目录链接 | `{'evil.py': 'link', 'linkdir/': 'link', 'ok.py': '<sha256>'}`，未读取外部目标 |

### 2.4 已核实与未核实边界

**已核实：**

- 仓库扫描不会跟随文件/目录符号链接，也不会把链接目标当作仓库文件读取。
- 符号链接不能绕过敏感文件过滤；链接在敏感规则之前被排除。
- 可信 Fixture 在验证阶段拒绝任何链接/junction；根目录链接同样拒绝。
- 静态工具只接收已过滤的 Python 文件，并再次校验解析后的路径仍在 workspace 内。
- 只读快照能发现执行后新增/删除/修改的链接或文件。

**未核实 / 残余限制：**

1. **只读保护是检测而非预防。** 一个可信 Fixture 的测试代码如果在执行期间创建链接、写入后删除或写后还原，前后快照可能看不到瞬时变化。该风险仅存在于“允许在宿主机执行”的可信 Fixture；外部 GitHub 仓库从不执行测试，因此不适用。
2. **快照不覆盖 Fixture 根目录之外。** 测试进程可写临时目录或外部路径；`read_only_verified` 只证明 Fixture 根目录的前后状态一致，不证明进程没有访问外部路径。
3. **TOCTOU 窗口。** `_is_link()` 检查与后续 `open()`/`resolve()` 之间理论上存在竞争；需要本地写权限才能利用。阶段 1 的威胁模型是“不可信仓库内容”，不是“本机已被入侵”。
4. **硬链接未单独建模。** Git clone 不保留硬链接；可信 Fixture 由人工审查。当前未对硬链接做专门拒绝。
5. **Windows 本机未真实执行 4 条符号链接测试。** 已用 WSL Linux 真实执行；未把 Windows skip 当作通过。

### 2.5 对 Stage 1 验收的影响

- 未发现可导致“越界读取、敏感文件进入 LLM 上下文、执行外部仓库脚本、伪造只读验证”的安全缺陷。
- AC-1-05（敏感文件不进入 LLM 上下文）、AC-1-10（外部仓库不执行）、AC-1-12（工作区只读）的实现边界与阶段 1 的威胁模型一致。
- 残余限制属于“可信 Fixture 受控例外”的已知代价，不构成 Stage 1 阻断项；但必须在 Stage 2 引入沙箱/更强隔离时重新评估。

---

## 3. Finding 与 LLM 统计对账

### 3.1 真实产物原始数据

产物：`reports/stage1-20261110T120331Z-d8333a8c/`

`static_analysis.json#/statistics`：

| 字段 | 值 |
| --- | ---: |
| `source_finding_count` | 240 |
| `mapped_finding_count` | 91 |
| `deterministic_finding_count` | 90 |
| `final_finding_count` | 91 |
| `semantic_finding_count` | 1 |
| `duplicate_count` | 1 |
| `skipped_finding_count` | 149 |
| `test_failure_finding_count` | 0 |
| `tool_failure_count` | 0 |
| `partial_tool_count` | 0 |

严重级别：`critical=0, high=2, medium=4, low=85, info=0`。

按工具拆分：

| 工具 | 原始 Finding | 映射后 | 跳过 | 说明 |
| --- | ---: | ---: | ---: | --- |
| Ruff | 17 | 17 | 0 | `I001` 10、`BLE001` 2、`UP017` 2、`RUF012` 1、`S110` 1、`SIM117` 1 |
| Bandit | 68 | 68 | 0 | `B101` 57、`B106` 8、`B324` 1、`B110` 1、`B403` 1 |
| Radon | 155 | 6 | 149 | CC 140（A 134、B 5、C 1）；MI 15（全部 A） |
| **合计** | **240** | **91** | **149** | 去重 1 条后确定性 Finding 90 |

### 3.2 240 → 91 → 90 → 91 的完整链路

1. **240 条原始工具 Finding**：Ruff 17 + Bandit 68 + Radon 155。
2. **跳过 149 条**：Radon CC rank A 134 条 + Radon MI rank A 15 条。跳过规则在 `finding_aggregator.py`：CC A 不构成复杂度问题，MI A 不构成可维护性问题。
3. **映射 91 条**：Ruff 17 + Bandit 68 + Radon CC B/C 6 条。
4. **去重 1 条**：`BANDIT-0001` 合并进 `RUFF-0007`，位置 `src/itsdangerous/timed.py:114`（Ruff S110 与 Bandit B110 指向同一 `try/except/pass`）。最终 Finding 的 `merged_from=["BANDIT-0001"]`。
5. **确定性 Finding 90 条**：91 − 1 条重复。
6. **语义 Finding 1 条**：`LLM-0001`，`src/itsdangerous/signer.py:231-232`，`missing_error_handling` / medium。
7. **最终 Finding 91 条**：90 条确定性 + 1 条语义。

`mapped_finding_count=91` 是**去重前**的映射数；`deterministic_finding_count=90` 是**去重后**的确定性数；`final_finding_count=91` 是确定性 + 语义的最终数。三者不是同一口径，不能互相替代。

### 3.3 LLM 提案语义

`static_analysis.json#/llm_analysis` 的关键字段：

| 字段 | 值 | 含义 |
| --- | ---: | --- |
| `status` | `completed` | 4 次调用全部成功 |
| `proposal_count` | 50 | 模型返回并解析出的提案总数（含因上限被丢弃的提案） |
| `accepted[]` | 49 | 通过校验的提案，不等于“新建 49 条 Finding” |
| `rejected[]` | 1 | 校验失败、只进入拒绝列表的提案 |
| `explanations[]` | 48 | 工具解释提案 |
| `dropped_proposal_count` | 0 | 超过 50 条提案上限而丢弃的数量 |
| `call_count` | 4 | 分块调用次数 |
| `context_finding_count` | 56 | 送入模型的 Finding 上下文条目总数 |
| `context_snippet_count` | 56 | 送入模型的代码片段总数 |
| `input_chars` | 58,050 | 输入字符总数 |
| `duration_ms` | 91,535 | LLM 阶段耗时 |
| `usage` | prompt 15,900 / completion 2,900 / total 18,800 | Provider 返回的用量 |

`accepted[]` 的来源拆分：

| `source` | 数量 | 是否新建 Finding | 去向 |
| --- | ---: | --- | --- |
| `tool_explanation` | 48 | 否 | `llm_analysis.explanations[]` 与 `llm_analysis.accepted[]` |
| `semantic_supplement` | 1 | 是 | `findings[]` 中的 `LLM-0001`；同时记录在 `accepted[]` |

被拒绝的 1 条提案：

- `proposal_index=4`
- `kind=semantic_supplement`
- `category=error_handling`（不在允许类别内）
- `title=时间戳解码静默失败`
- `file_path=src/itsdangerous/timed.py`，`start_line=114`
- `reason=unsupported or missing category`
- 只存在于 `llm_analysis.rejected[]`，没有进入 `findings[]`。

`LLM-0001` 的具体字段：

| 字段 | 值 |
| --- | --- |
| `finding_id` | `LLM-0001` |
| `agent_name` | `Stage1Analyzer` |
| `category` | `missing_error_handling` |
| `severity` | `medium` |
| `file_path` | `src/itsdangerous/signer.py` |
| `start_line` / `end_line` | 231 / 232 |
| `tool_evidence` | `[]` |
| `verification_status` | `unverified` |

### 3.4 七个问题的直接回答

#### 1. `proposals_received` 是什么含义？

阶段 1 产物中**没有** `proposals_received` 字段。最接近的是 `llm_analysis.proposal_count`，其含义是“模型返回并解析出的提案总数”，包含：

- 通过校验的 49 条；
- 校验失败进入 `rejected[]` 的 1 条；
- 若超过 50 条上限，还会包含 `dropped_proposal_count` 的提案（本次为 0）。

本次 `proposal_count=50`，恰好等于 `accepted 49 + rejected 1`，且 `dropped=0`。

#### 2. `accepted` 是否等于“新建 Finding”？

**不等于。** 49 条 accepted 中：

- 48 条 `tool_explanation` 只生成解释记录，不创建 Finding；
- 1 条 `semantic_supplement` 创建 `LLM-0001`。

因此“49 条 accepted”与“1 条新增语义 Finding”并不矛盾，它们是不同层级的概念。

#### 3. 未新建 Finding 的 accepted 提案去了哪里？

48 条 `tool_explanation` 进入：

- `llm_analysis.explanations[]`：每条包含 `related_finding_id`、`proposal_index`、`description`；
- `llm_analysis.accepted[]`：每条包含 `finding_id`（即关联 Finding）、`proposal_index`、`source="tool_explanation"`、`related_finding_id`。

它们不会写入 `findings[]`，也不会改变关联 Finding 的标题、严重级别、证据或状态。

#### 4. 已有 Finding 是否被补充、增强或关联？

- **关联**：是。48 条解释通过 `related_finding_id` 关联到已有 Finding。
- **补充/增强**：只体现在 `explanations[]` 的可读解释中；正式 Finding 的字段不被修改。
- **合并标记**：`_reconcile_final_ids()` 在去重导致 ID 变化时设置 `merged=true`，并重映射 `related_finding_id`；本次 48 条解释的 `merged` 均为 false（关联 ID 未变化）。
- **语义提案**：如果语义提案带 `related_finding_id`，它会复制关联 Finding 的 `tool_evidence`（深拷贝），但仍创建新的 `LLM-xxxx` Finding，不修改原 Finding。本次 `LLM-0001` 没有关联 Finding，因此 `tool_evidence=[]`。

#### 5. 去重、拒绝、跳过如何计数？

它们是彼此独立、不可互相抵扣的计数器：

| 概念 | 字段/位置 | 本次值 | 说明 |
| --- | --- | ---: | --- |
| 原始工具 Finding | `source_finding_count` | 240 | 工具输出条数 |
| 规则跳过 | `skipped_finding_count` | 149 | Radon A 级 CC/MI |
| 映射后 | `mapped_finding_count` | 91 | 去重前 |
| 确定性去重 | `duplicate_count` | 1 | `BANDIT-0001` → `RUFF-0007` |
| 确定性最终 | `deterministic_finding_count` | 90 | 去重后 |
| 语义新增 | `semantic_finding_count` | 1 | `LLM-0001` |
| 最终 Finding | `final_finding_count` | 91 | 90 + 1 |
| LLM 提案总数 | `proposal_count` | 50 | 含拒绝/丢弃 |
| LLM 接受 | `accepted[]` | 49 | 含 48 条解释 |
| LLM 拒绝 | `rejected[]` | 1 | 不进入正式 Finding |
| LLM 超限丢弃 | `dropped_proposal_count` | 0 | 本次没有超过 50 条上限 |

#### 6. LLM 能否修改工具生成的证据？

**不能。**

- `tool_explanation` 路径只创建解释对象，不接触关联 Finding 的任何字段。
- `semantic_supplement` 路径创建新 Finding：
  - `tool_evidence` 从关联 Finding **深拷贝**，或为空列表；
  - 代码证据片段由 `CodeEvidenceValidator` 对真实文件内容校验，模型不能凭空编造位置或片段；
  - 关联 Finding 本身不被修改。
- 确定性 Finding 由 `finding_aggregator` 生成，LLM 阶段只读 `deterministic` 列表并构建上下文。

#### 7. LLM 能否把 `verification_status` 从 `unverified` 改成 `verified`？

**不能。**

- `finding_aggregator` 的所有构造路径硬编码 `verification_status="unverified"`。
- `llm_analyzer` 创建语义 Finding 时同样硬编码 `verification_status="unverified"`。
- `artifact_models.StaticAnalysisArtifact` 的模型校验要求所有 Stage 1 Finding 必须 `agent_name="Stage1Analyzer"` 且 `verification_status="unverified"`，否则拒绝产物。
- 只有阶段 2 的 Final Reviewer 才允许改写该字段（`docs/task_contracts.md` 的 Finding 合同）。
- 真实产物 91 条 Finding 的核查结果：`agent_name` 全部 `Stage1Analyzer`，`verification_status` 全部 `unverified`。

### 3.5 统计口径的歧义与最小修改建议

当前实现没有错误，但命名容易让人误读：

1. `proposal_count` 容易被理解为“收到的提案数”，实际包含超限丢弃的提案；`accepted` 又包含不新建 Finding 的解释提案。
2. `mapped_finding_count` 是去重前，`deterministic_finding_count` 是去重后，两者相差 `duplicate_count`。
3. 阶段 1 产物使用 `metadata.review_status` 与 `static_analysis.llm_analysis.status`，而核心文档中的 `report_status` 属于阶段 2 的 `ReviewReport`，两者不应混用。

**最小修改建议（需人工批准，本轮未实施）：**

- 优先做**文档/字段说明**，不改 Schema 形状、不改字段值：
  - 在 `docs/acceptance.md` §4.9 或 `docs/workflow.md` §8.7 的阶段 1 补充段落中，增加一张“统计口径表”，逐项说明上述字段；
  - 在 `artifact_models.py` 的 `LLMAnalysisArtifact` / `StaticAnalysisStatisticsArtifact` 字段旁补充中文 docstring（仅注释，不改变校验）。
- 不建议在阶段 1 重命名 `proposal_count` 或拆分 `accepted[]`；那会改变 Artifact Schema 与已有产物兼容性。若 Stage 2 需要仪表盘口径，可在 Stage 2 新增计数字段并保留旧字段。
- 不修改 `schemas/task.py`、`schemas/result.py`、`schemas/report.py`。

---

## 4. 依赖环境基线

### 4.1 运行时基线

| 项 | 值 |
| --- | --- |
| OS | Windows 11 Pro 10.0.26100 |
| Conda | 25.7.0 |
| 环境名 | `multi-agent-review` |
| Python | 3.12.16 |
| pip | 26.2.2 |
| Git | 2.49.0.windows.1 |
| WSL（仅符号链接复核） | Ubuntu 24.04.2 LTS，Python 3.13.9 |

### 4.2 直接依赖（项目环境实测）

| 依赖 | 版本 | 来源 |
| --- | --- | --- |
| fastapi | 0.162.2 | 阶段 0 |
| uvicorn | 0.54.0 | 阶段 0 |
| pydantic | 2.14.3 | 阶段 0 |
| pydantic-settings | 2.16.2 | 阶段 0 |
| python-dotenv | 1.2.4 | 阶段 0 |
| pytest | 9.2.0 | 阶段 0 |
| httpx | 0.28.1 | 阶段 0 |
| structlog | 26.1.0 | 阶段 0 |
| ruff | 0.17.4 | 阶段 1（固定版本） |
| bandit | 1.9.4 | 阶段 1（固定版本） |
| radon | 6.0.1 | 阶段 1（固定版本） |
| coverage | 7.17.2 | 阶段 1（固定版本） |

以上 12 个直接依赖的版本与 `reports/phase_1_acceptance_report.md` §13 的记录逐项一致。

### 4.3 关键传递依赖（项目环境实测）

| 依赖 | 版本 | 依赖来源 |
| --- | --- | --- |
| anyio | 4.16.0 | fastapi/httpx |
| starlette | 1.10.0 | fastapi |
| pydantic-core | 2.50.4 | pydantic |
| typing-extensions | 4.16.0 | pydantic/fastapi |
| opentelemetry-api | 1.45.2 | FastAPI 被动带入（AC-0-05 允许） |
| click | 8.5.1 | uvicorn |
| rich | 15.0.0 | bandit/typer 生态 |
| pyyaml | 6.0.3 | bandit |
| mando | 0.7.1 | radon |
| stevedore | 5.9.1 | bandit |
| markdown-it-py | 4.2.0 | rich |
| packaging | 26.3 | pytest/构建工具 |
| pluggy | 1.7.0 | pytest |
| iniconfig | 2.3.1 | pytest |
| certifi | 2026.10.23 | httpx |
| idna | 3.20 | httpx |
| h11 | 0.16.0 | httpcore/uvicorn |
| httpcore | 1.0.9 | httpx |
| annotated-types | 0.8.0 | pydantic |
| annotated-doc | 0.0.5 | fastapi |
| colorama | 0.4.6 | click |
| mdurl | 0.1.2 | markdown-it-py |
| pygments | 2.21.0 | rich |
| setuptools | 84.2.1 | Python 环境 |
| wheel | 0.48.0 | Python 环境 |
| six | 1.17.0 | bandit |

禁止项探测：`FORBIDDEN: []`；`PASSIVE-ALLOWED: ['opentelemetry-api']`。未发现 langgraph、langchain、redis、arq、sqlalchemy、psycopg、mcp、a2a-sdk、langsmith、streamlit 等阶段 2+ 依赖。

### 4.4 `environment.yml` 状态

```yaml
name: multi-agent-review
channels:
  - conda-forge
dependencies:
  - python=3.12
  - pip
  - pip:
      - fastapi
      - uvicorn
      - pydantic
      - pydantic-settings
      - python-dotenv
      - pytest
      - httpx
      - structlog
      - ruff==0.17.4
      - bandit==1.9.4
      - radon==6.0.1
      - coverage==7.17.2
```

事实：

- 8 个阶段 0 直接依赖**未固定版本**；4 个阶段 1 工具已固定版本。
- `python=3.12` 只固定 minor，不固定 patch。
- 仓库中没有 `pyproject.toml`、`requirements.txt`、`requirements.lock.txt` 或 `conda-lock.yml`；已按 MD-1 生成 `environment.lock.yml`（Stage 1 Windows 快照，见 §4.6）。
- `environment.yml` 自阶段 0 提交 `6fe6abe` 到 `HEAD` 只增加 4 个阶段 1 工具；阶段 0 的依赖组合未被替换或删除。阶段 0 的 8 个直接依赖版本与验收记录一致。
- 本机环境实际安装的 fastapi 0.162.2、pydantic 2.14.3、pytest 9.2.0 等版本，均高于 `environment.yml` 可保证的下限；这些版本是当前环境的实测值，不是文件锁定的值。

### 4.5 干净环境可复现性评估

**结论：仅用 `environment.yml` 不能在干净环境中精确复现 Stage 1 结果；MD-1 已生成的 `environment.lock.yml` 可在同平台（Windows）复现当前环境。**

原因：

1. `conda env create -f environment.yml` 只会安装“当前解析到的最新兼容版本”，不会安装本轮实测的 12 个直接依赖版本；fastapi、pydantic、pytest 等任一版本变化都可能改变行为或测试结果。
2. 传递依赖（anyio、starlette、pydantic-core、opentelemetry-api 等）完全没有记录在文件中；它们会随直接依赖的解析结果漂移。
3. 宿主 PATH 上的 `python` 指向 base 环境（fastapi 0.110.2 / pydantic 2.13.4 / pytest 7.4.4），与项目环境不同；如果执行者没有显式激活/使用项目环境，会得到另一套结果。这是一个真实的操作风险，不只是理论问题。
4. `pytest.ini` 只设置 `pythonpath = src .` 与 `testpaths = tests`，不锁定依赖。

可以保证的部分：

- 当前这台机器上的项目环境版本已完整记录（§4.2/§4.3）。
- 阶段 1 的测试与真实产物是在该环境（Python 3.12.16）下生成的。
- 已生成 `environment.lock.yml`（当前 Windows 环境快照）：在这台 Windows 机器上可用 `conda env create -f environment.lock.yml` 重建同一组版本；它不适用于 Linux，也不替代 Stage 2 的依赖清单。
- 如果保留当前环境不重建，本轮结果可重复；如果删除环境后仅用 `environment.yml` 重建，**不保证**得到相同版本。

### 4.6 依赖锁定方案与已生成的 Stage 1 快照（MD-1 已批准方案 B）

**方案 A：`conda-lock`（跨平台，推荐用于 CI）**

- 工具：`conda-lock`（开发工具，不是运行时依赖）。
- 产物：`conda-lock.yml`，可同时锁定 win-64 与 linux-64。
- 使用：`conda-lock install --name multi-agent-review conda-lock.yml`。
- 优点：跨平台、哈希校验、适合 Stage 2 引入 CI 后复现。
- 代价：需要新增开发依赖与安装步骤；对 `environment.yml` 的 pip 段落支持需要验证；生成文件较大。
- 影响：不改变现有 `environment.yml` 作为人类维护源；只是新增锁文件。

**方案 B：`conda env export` 快照（最小改动，推荐先做）**

- 命令：`conda env export -n multi-agent-review --no-builds`，移除 `prefix:` 行后写入 `environment.lock.yml`（已执行）。
- 已生成：`environment.lock.yml`，5 行说明头 + 62 行导出内容；Python 3.12.16；未升级、未替换任何依赖；不含主机路径。
- 注意：导出文件记录的 channels 为 `defaults`（当前环境的实际来源），与 `environment.yml` 的 `conda-forge` 不同；这是快照事实，不代表修改了 `environment.yml`。
- 使用：`conda env create -f environment.lock.yml`。
- 优点：不新增工具；能精确记录当前 Windows 环境的直接与传递依赖；实施成本最低。
- 代价：平台相关（Windows 专用），不能直接用于 Linux CI；需要与 `environment.yml` 明确区分“人类维护源”与“机器生成快照”。
- 影响：不修改 `environment.yml`，符合“不要把全部传递依赖塞进 environment.yml”的要求。

**方案 C：`pip-compile` 哈希锁（备选）**

- 从 `requirements.in` 生成 `requirements.lock.txt`（`pip-compile --generate-hashes`）。
- 优点：哈希固定、Linux/Windows 通用性好。
- 代价：Conda 的 Python 版本仍由 `environment.yml` 管理；pip 与 conda 混用会增加维护复杂度。

**建议顺序：**

1. **已执行**：采用方案 B，生成 `environment.lock.yml` 并随 Stage 1.7 提交，作为 Stage 2 启动前的可复现快照。
2. 如果 Stage 2 建立 Linux CI 或需要跨平台复现，再评估方案 A。
3. 是否把 8 个阶段 0 直接依赖在 `environment.yml` 中固定到本轮实测版本，需要单独批准；这会修改阶段 0 基线文件，但不改变依赖组合。**本轮未修改。**
4. Stage 2 安装 `langgraph` 后生成新的快照文件（例如 `environment.stage2.lock.yml`），**不得覆盖**本 Stage 1 快照。

### 4.7 关键测试命令（项目环境）

```powershell
# 环境
conda env create -f environment.yml
conda activate multi-agent-review
python --version   # 期望 3.12.x

# 阶段 0 回归 + 阶段 1 单元测试
conda run -n multi-agent-review python -m pytest tests/unit -q

# 离线集成测试（不联网、不调用真实 LLM）
conda run -n multi-agent-review python -m pytest tests/integration -q -m "not real_network and not llm_smoke"

# 阶段 0 Schema 子集
conda run -n multi-agent-review python -m pytest tests/unit/test_task_schema.py tests/unit/test_result_schema.py tests/unit/test_report_schema.py -q

# 真实网络（需批准与网络）
$env:RUN_REAL_NETWORK="1"; conda run -n multi-agent-review python -m pytest tests/integration -q -m real_network

# 真实 LLM 冒烟（需 .env 配置）
$env:RUN_LLM_SMOKE="1"; conda run -n multi-agent-review python -m pytest tests/integration/test_llm_smoke.py -q -s
```

---

## 5. 五份正式文档与代码一致性矩阵

只读核查范围严格限定为：`docs/requirements.md`、`docs/architecture.md`、`docs/workflow.md`、`docs/task_contracts.md`、`docs/acceptance.md`。`README.md`、`阶段1_Prompt.md` 等不作为本矩阵的“文档依据”，仅用于交叉参考。

| 核查项 | 文档依据 | 实际实现 | 是否一致 | 建议 |
| --- | --- | --- | --- | --- |
| 1. AC 编号以 `acceptance.md` 为准 | `acceptance.md` 头部冻结说明与 §4.11 v1.1 变更记录；AC-1-01～AC-1-15 定义于 §4.3 | 验收报告与测试记录均引用 AC-1 编号；未发现 AC-0/AC-2 混用；阶段 2 的 AC-2 编号未提前用于阶段 1 | 一致 | 保持；后续文档引用继续以 `acceptance.md` 原文为准 |
| 2. 阶段 1 只生成四件产物 | `acceptance.md` §4.2、AC-1-15、§4.9；`workflow.md` §8.7 与 §10；`requirements.md` FR-2.5；`architecture.md` §3⑦ | `report_generator.py` 只定义 `metadata.json`、`static_analysis.json`、`test_report.json`、`report.md`；真实产物目录恰好四件；`test_report_generator.py::test_generate_writes_exactly_four_artifacts` | 一致 | 无 |
| 3. 阶段 1 不生成完整 `ReviewReport` / `report.json` | `acceptance.md` §4.9；`workflow.md` §8.7 阶段 1 补充；`requirements.md` FR-9.1 按阶段 2 起解释 | `report_generator.py` 无 `report.json`；`reporting/__init__.py` 明确不构造 `ReviewReport`；真实产物无 `report.json`；`ReviewReport` 仅作为阶段 0 冻结合同存在 | 一致 | 无；阶段 2 再启用 `report.json` |
| 4. 资源限制与超限语义 | `acceptance.md` §4.7 表格与补充约束 | `config/settings.py` 默认值逐项匹配：Clone/Git 300s、仓库 200MB、文件 5000、单文件 2MB、总扫描 50MB、工具 120s、输出 5MiB、Finding 1000、Pytest/Coverage 300s、LLM 60s/60k/8000 tokens/每次 15（上限 20）/temperature 0.0/提案 50；`repository_manager`、`repository_inspector`、`base.py`、`test_runner`、`llm_analyzer` 均有对应处理 | **部分一致** | 数值与超限结果一致；两处低风险缺口见 §5.2：内部上限常量未全部集中到 `settings.py`；单文件超限原因未逐文件落入四件产物 |
| 5. 仅可信 Fixture 可执行 Pytest/Coverage | `acceptance.md` §4.8；AC-1-09、AC-1-10 | `trusted_fixture.py` 默认路径 + 白名单 + 清单哈希 + 链接拒绝；`review_service` 强制默认根目录；`test_runner` 只对已校验 Fixture 执行；CLI/API 无 `--trusted` 入口；不自动安装依赖、不执行 `setup.py`/`build.py` | 一致 | 无 |
| 6. 外部 GitHub 仓库测试恒为 `not_executed` | `acceptance.md` AC-1-10、§4.8；`requirements.md` FR-2.3；`task_contracts.md` RP-09 | `test_runner.execute(trusted_fixture=None)` 直接返回 `not_executed`；`review_service` 对外部仓库传 `None`；真实 `test_report.json` 为 `not_executed`/`external_repository` 且 `reason` 非空；计数与覆盖率均为 null | 一致 | 无 |
| 7. Stage 1 Finding 使用 `Stage1Analyzer` 且保持 `unverified`；LLM 不合格提案只进 `rejected[]` | `acceptance.md` §4.9；`architecture.md` §8.1；`task_contracts.md` Finding 合同 | `finding_aggregator` 硬编码 `Stage1Analyzer`/`unverified`；`llm_analyzer` 语义 Finding 同样硬编码；`artifact_models` 校验 91 条 Finding 全部满足；真实产物 91/91 符合；`rejected[]` 1 条未进入 `findings[]` | 一致 | 无 |
| 8. `ReviewService` 是 CLI 与 FastAPI 的唯一业务入口 | `acceptance.md` AC-1-14；`architecture.md` §3、DR-4、ADR-9；`workflow.md` §2/§10；`requirements.md` FR-1.2、NFR-M6 | `cli.py` 只解析参数并调用 `ReviewService.review`；`api/app.py` 只做 HTTP 校验/单槽并发控制并调用同一个 `ReviewService.review`；两端均无重复审查逻辑 | 一致 | `review_trusted_fixture()` 是测试专用第二入口，未通过 CLI/API 暴露，不违反“唯一业务入口” |
| 9. LangGraph、专业 Agent、Final Reviewer 等属于阶段 2+ | `architecture.md` §3③/§6；`workflow.md` §10；`requirements.md` 阶段表；`acceptance.md` 阶段 2 | `src/` 无 `agents/`、`graph/`、LangGraph/Redis/ARQ 导入；`environment.yml` 无阶段 2+ 依赖；`ReviewReport` 仅冻结合同，无生成逻辑 | 一致 | 阶段 2 再引入；不得提前安装依赖 |
| 10. 阶段 1 Artifact Schema 不修改阶段 0 三个核心 Schema | `acceptance.md` §4.9 | `git diff -- src/code_review/schemas` 为空；`git diff 6fe6abe HEAD -- src/code_review/schemas/` 为空；`artifact_models.py` 独立定义并复用 `Finding`/`ErrorInfo`，未改核心字段 | 一致 | 保持冻结；任何核心 Schema 变更需单独批准 |

### 5.1 补充核查（文档未完整规定，非阻断）

| 核查项 | 文档依据 | 实际实现 | 是否一致 | 建议 |
| --- | --- | --- | --- | --- |
| 11. 可信 Fixture 的产物字段口径 | `acceptance.md` §4.8 只规定“固定版本或哈希清单”，未规定 `fixture://`、`source_type`、`commit_sha=null`、`fixture_manifest_sha256` | `artifact_models.MetadataArtifact` 强制这些字段；`review_service` 生成 `fixture://<name>` 与 `source_type=trusted_fixture`；测试覆盖 | **部分一致（文档滞后）** | 在 §4.9 增加“可信 Fixture 产物字段”说明；不改 Schema |
| 12. `POST /api/reviews` 的可选 `commit_sha` 与 429 | `requirements.md` FR-1.2 只列 `repository_url`/`branch`；`workflow.md` §2 示例未列 `commit_sha`、未提 429；`architecture.md` 只说同步入口 | `api/app.py` 接受 `repository_url`/`branch`/`commit_sha`；单槽 `BoundedSemaphore(1)`，忙碌返回 429 `review_slot_busy`；README 已写明 | **部分一致（文档滞后）** | 在 `workflow.md` §2 或 `requirements.md` FR-1.2 补充可选 `commit_sha` 与 429 语义；不改代码 |
| 13. 阶段 1 状态字段命名 | 五份文档定义阶段 2 的 `report_status`，未定义阶段 1 的 `review_status` 与 `llm_analysis.status` | `metadata.review_status` 为 `completed/partial`；`static_analysis.llm_analysis.status` 为 `completed/not_configured/skipped/timeout/failed`；`test_report.execution_status` 为 `executed/not_executed/timeout/failed` | **部分一致（文档未规定）** | 在 §4.9 增加阶段 1 产物字段表，明确与阶段 2 `report_status` 的区别 |
| 14. 单文件超限的逐文件记录 | `acceptance.md` §4.7：“单文件大小 2 MB，跳过该文件，记录过滤原因” | Inspector 内部 `RepositoryInventory.filtered_files` 记录 `FilteredFile(path, reason, size)`；四件产物只写入 `inventory.filtered_files` 计数（本次为 2），未逐文件列出原因 | **部分一致（实现记录未落入产物）** | Stage 2 可在产物中增加过滤清单摘要；阶段 1 不新增核心 Schema 字段 |

### 5.2 不一致分类与最小修改建议

**代码偏差（非阻断）：**

- 单文件超限的过滤原因在内存对象中存在，但未序列化到四件产物；这是可审计性缺口，不是安全缺陷。最小修改是 Stage 2 在 Artifact Schema 中增加可选过滤清单，不改阶段 0 核心 Schema。
- 少量内部安全上限常量散落在 `llm_analyzer.py`（`_MAX_CONTEXT_FINDINGS`、`_MAX_CONTEXT_EVIDENCE_CHARS`、`_MAX_RESPONSE_CHARS` 等）与 `test_runner.py`（`_MAX_STORED_OUTPUT_CHARS` 等），与 `acceptance.md` §4.7 “阈值实现必须集中在 `config/settings.py`”的字面要求不完全一致。这些常量不在 §4.7 的阈值表中，属于实现安全上限；建议 Stage 2 配置化时统一，或在文档中明确其为“内部上限常量”。

**文档滞后（非阻断）：**

- 可信 Fixture 的 `fixture://`/`source_type`/`commit_sha=null`/清单哈希字段未写入五份核心文档。
- API 的可选 `commit_sha` 与 429 未写入核心文档。
- 阶段 1 的 `review_status` / `llm_analysis.status` 未定义，容易与阶段 2 的 `report_status` 混淆。

**建议处理方式：**

- 本轮**不修改**五份文档与三个核心 Schema；以上均为文档补充，不改合同形状。
- 若用户批准，Stage 2 启动前可用一个独立的文档修订提交补齐 §5.1 的 11～13 项；第 14 项留到 Stage 2 的 Artifact Schema 扩展。
- 不建议为了“字面一致”把内部安全上限常量强行塞进 `settings.py` 后再改变阶段 1 行为；应作为 Stage 2 配置化的一部分统一处理。

---

## 6. Git 工作区与阶段 1.7 提交准备

### 6.1 当前状态（只读检查）

- 分支：`main`
- `HEAD`：`a7d384d 阶段 1.6：报告生成与统一服务入口`
- 工作区：34 个已修改文件，3 个未跟踪项
- `git diff --stat`：34 files changed, 230 insertions(+), 137 deletions(-)
- 未跟踪：
  - `reports/phase_1_acceptance_report.md`
  - `reports/stage1-20261110T120331Z-d8333a8c/`（4 件产物）
  - `tests/integration/test_llm_smoke.py`

最近提交：

```text
a7d384d 阶段 1.6：报告生成与统一服务入口
6343e54 阶段 1.5：Finding 聚合与 LLM 辅助分析
939a5a2 阶段 1.4：可信 Fixture 测试执行与覆盖率
57c6c33 阶段 1.3：静态分析工具集成
bcd8fc9 阶段 1.2：仓库扫描、文件过滤与路径安全
398d5f6 阶段 1.1：仓库获取、URL 校验与资源限制
1623e06 docs: 完成阶段 1 实施基线修订
6fe6abe 阶段 0：工程初始化、数据契约与验收基线
```

### 6.2 核心 Schema 与文档 diff

```text
git diff -- src/code_review/schemas docs
（无输出）
```

- `src/code_review/schemas/task.py`、`result.py`、`report.py` 自阶段 0 提交 `6fe6abe` 后未修改。
- 五份核心文档自阶段 1 基线修订提交 `1623e06` 后未修改。
- 本轮只读审计未修改任何文件；本报告是新增文件。

### 6.3 密钥、令牌与主机路径检查

| 检查 | 结果 |
| --- | --- |
| `.env` 是否被跟踪 | 否；`git check-ignore -v .env` 返回 `.gitignore:1:.env` |
| 已跟踪的 `.env*` | 仅 `.env.example`，值为空占位 |
| 已跟踪文件的 `sk-`/`ghp_`/`AKIA` 模式 | 仅 `tests/unit/test_redaction.py` 的测试用假值；无真实凭据 |
| 真实产物 `metadata.json`/`static_analysis.json`/`test_report.json`/`report.md` | 0 处用户主目录路径、0 处仓库绝对路径、0 处密钥样式字符串、0 处用户目录名 |
| `reports/phase_1_acceptance_report.md` | 无主机路径；`sk-` 仅作为“密钥样式”文字出现，无真实值 |
| 阶段 1 产物中的工具 stdout | 已脱敏为 `<workspace>`/`<home>`/`<temp>`；仍可能包含被截断的第三方代码片段（见 TD-4） |

### 6.4 推荐提交文件清单

建议用**显式路径**提交，禁止 `git add -A` / `git add .`，以免把真实产物目录带入版本控制。

**生产与文档：**

- `README.md`
- `src/code_review/reporting/report_generator.py`
- `environment.lock.yml`（MD-1 生成的 Stage 1 Windows 环境快照）

**测试（32 个已修改文件）：**

- `tests/fixture_factory.py`
- `tests/stage1_helpers.py`
- `tests/integration/test_read_only_analysis.py`
- `tests/integration/test_real_clone.py`
- `tests/integration/test_real_static_analysis.py`
- `tests/integration/test_stage1_5_pipeline.py`
- `tests/integration/test_stage1_6_review.py`
- `tests/integration/test_trusted_fixture_execution.py`
- `tests/unit/test_api.py`
- `tests/unit/test_artifact_models.py`
- `tests/unit/test_bandit_tool.py`
- `tests/unit/test_cli.py`
- `tests/unit/test_evidence_validator.py`
- `tests/unit/test_file_filters.py`
- `tests/unit/test_llm_client.py`
- `tests/unit/test_markdown_renderer.py`
- `tests/unit/test_process_runner.py`
- `tests/unit/test_radon_tool.py`
- `tests/unit/test_redaction.py`
- `tests/unit/test_report_generator.py`
- `tests/unit/test_report_schema.py`
- `tests/unit/test_repository_inspector.py`
- `tests/unit/test_repository_manager.py`
- `tests/unit/test_result_schema.py`
- `tests/unit/test_review_service.py`
- `tests/unit/test_ruff_tool.py`
- `tests/unit/test_test_report_parsers.py`
- `tests/unit/test_test_runner.py`
- `tests/unit/test_tool_base.py`
- `tests/unit/test_trusted_fixture.py`
- `tests/unit/test_url_validator.py`
- `tests/unit/test_workspace_snapshot.py`

**新增测试（MF-1 已修正）：**

- `tests/integration/test_llm_smoke.py`

**报告：**

- `reports/phase_1_acceptance_report.md`
- `reports/phase_1_exit_review_report.md`（本报告）

### 6.5 排除清单

| 排除项 | 原因 |
| --- | --- |
| `reports/stage1-20261110T120331Z-d8333a8c/` | 真实第三方仓库产物，含被截断的第三方代码片段与原始工具输出；按数据分级不进入版本控制 |
| `.env`、`.env.*`（`.env.example` 除外） | 本地密钥；已被 `.gitignore` 忽略 |
| `__pycache__/`、`*.pyc`、`.pytest_cache/`、`.ruff_cache/`、`.mypy_cache/` | 缓存 |
| 临时工作区、`reports/` 下的临时目录 | 非交付物 |
| 任何 `stage1-*` 真实审查产物 | 同上 |

### 6.6 提交前必须修复项

**MF-1：`tests/integration/test_llm_smoke.py` 的导入根不一致**

- 位置：`tests/integration/test_llm_smoke.py:15-16`
- 修复前：

```python
from src.code_review.services.llm_analyzer import _extract_json_object
from src.code_review.services.llm_client import OpenAICompatibleClient
```

- 修复后：

```python
from code_review.services.llm_analyzer import _extract_json_object
from code_review.services.llm_client import OpenAICompatibleClient
```

- 原因：Stage 1.7 已将 33 个测试文件统一为顶层 `code_review.*` 导入，以避免 `src.code_review.*` 与 `code_review.*` 的重复模块身份；该新增文件遗漏。当前测试只使用无状态函数/客户端，所以即使保留 `src.*` 也能通过/跳过，但会破坏统一性，并在未来引入 Pydantic 模型或 `isinstance` 校验时产生隐蔽的类身份冲突。
- 影响：仅影响该未跟踪测试文件；不影响生产代码与已跟踪测试。
- 处理：**已修复（2026-11-10）**。默认运行：`1 skipped`；`RUN_LLM_SMOKE=1`：`1 passed`，模型 `deepseek-ai/DeepSeek-V3`，usage `prompt=39 / completion=15 / total=54`，latency 2153 ms。

### 6.7 建议提交信息

```text
feat(stage1): complete single-agent code review foundation
```

如需说明，可在正文补充：

```text
- 完成 Stage 1.7 报告产物净化与测试导入根统一
- 补充真实产物验收报告与阶段 1 收尾核查报告
- 不包含真实第三方仓库产物
```

### 6.8 Git 操作授权与执行

用户于 2026-11-10 明确批准按第 6.4 节清单提交 Stage 1.7。本报告随该提交一并提交；提交前使用显式路径执行 `git add`，未使用 `git add -A` / `git add .`。未执行 `git reset`、`git checkout`、`git clean`、`git restore` 或其他改写历史/工作区的命令。提交 SHA 无法写入本提交自身，记录于 `git log -1` 与会话执行记录（§11）。

---

## 7. 非阻断技术债清单

| 编号 | 技术债 | 描述与位置 | 影响范围 | 对 Stage 2 的影响 | 建议处理阶段 |
| --- | --- | --- | --- | --- | --- |
| TD-1 | 阶段 0 冻结 Schema 的 10 条 Ruff 提示 | 9 条 `UP037/UP017` 在 `schemas/task.py`、`result.py`、`report.py`；1 条 `FURB167` 在 `tests/unit/test_report_schema.py` | 风格/静态检查；不影响运行与合同 | 若 Stage 2 引入全仓 Ruff gate，需要先清理或配置豁免 | Stage 2 启动前或独立 hygiene 提交 |
| TD-2 | LLM 语义不确定性 | `llm_analyzer` 的语义补充依赖模型输出；本次 50 条提案中 49 接受、1 拒绝，语义 Finding 仅 1 条 | 语义 Finding 的数量/内容可能随运行变化；确定性工具结果不受影响 | Stage 2 的评分、评估与回归需要重复运行或固定基线 | Stage 2 评估体系；Stage 7 阈值 |
| TD-3 | FastAPI 同步单槽 | `api/app.py` 的 `BoundedSemaphore(1)`，忙碌返回 429 | 并发请求被拒绝；仅适合本地受控演示 | Stage 2 仍为同步单进程；Stage 4 才引入 Redis + ARQ | Stage 4 |
| TD-4 | 真实报告可能含第三方代码片段 | `static_analysis.json` / `report.md` 的工具 stdout 与证据片段 | 数据分级/隐私；不得提交真实产物 | Stage 2 报告仍会包含代码片段；需要保留排除规则 | Stage 2/7 数据治理 |
| TD-5 | Windows 无法完整执行符号链接测试 | 4 条测试在 Windows skip；WSL Linux 通过 | 本地 Windows 证据不完整 | Stage 2 CI 应使用 Linux runner 或 WSL | Stage 2 CI |
| TD-6 | 仅有 Stage 1 Windows 环境快照 | `environment.lock.yml` 已记录当前 Windows 环境；`environment.yml` 8 个阶段 0 依赖仍未固定；无跨平台 `conda-lock.yml` | 同平台可复现；Linux/CI 不能直接复用 | Stage 2 新增 `langgraph` 后应生成新快照；跨平台复现需 `conda-lock` | Stage 2 启动前（MD-1 已执行） |
| TD-7 | 内部上限常量未集中 | `llm_analyzer.py` 的 `_MAX_CONTEXT_FINDINGS`、`_MAX_CONTEXT_EVIDENCE_CHARS`、`_MAX_RESPONSE_CHARS` 等；`test_runner.py` 的 `_MAX_STORED_OUTPUT_CHARS` 等 | 与 §4.7“阈值集中在 settings.py”的字面要求不完全一致 | Stage 2 配置化时统一 | Stage 2 |
| TD-8 | 阶段 1 产物字段文档滞后 | `fixture://`、`source_type`、`commit_sha=null`、`review_status`、`llm_analysis.status`、API `commit_sha`/429 | 文档可读性；非代码缺陷 | Stage 2 文档修订时补齐 | Stage 2 文档阶段 |
| TD-9 | 单文件超限原因未逐文件入产物 | `metadata.inventory` 只有 `filtered_files` 计数；内部 `FilteredFile` 未序列化 | 可审计性降低 | Stage 2 可在 Artifact Schema 增加可选过滤清单 | Stage 2 |

---

## 8. 必须修复与需要批准的事项

### 8.1 必须修复（提交前）

| 编号 | 事项 | 位置 | 影响 | 状态 |
| --- | --- | --- | --- | --- |
| MF-1 | 统一 `test_llm_smoke.py` 的导入根 | `tests/integration/test_llm_smoke.py:15-16` | 避免 `src.code_review.*` 与 `code_review.*` 重复模块身份；保持 Stage 1.7 导入统一 | **已修复**（默认 `1 skipped`；`RUN_LLM_SMOKE=1` 时 `1 passed`，usage 54） |

### 8.2 必须决策（Stage 2 启动前）

| 编号 | 事项 | 选项 | 状态 |
| --- | --- | --- | --- |
| MD-1 | 依赖锁定方案 | A. `conda-lock` 跨平台锁；B. `environment.lock.yml` 当前平台快照（推荐先做）；C. `pip-compile` 哈希锁 | **已批准方案 B；已生成 `environment.lock.yml`** |
| MD-2 | 是否补齐阶段 1 字段文档 | 在 `acceptance.md` §4.9 / `workflow.md` 补充 `fixture://`、`source_type`、`review_status`、`llm_analysis.status`、API `commit_sha`/429 | **已批准纳入 Stage 2 文档同步；本轮不修改文档** |
| MD-3 | 是否清理 10 条冻结 Schema 的 Ruff 提示 | 独立 hygiene 提交 / 配置 Ruff 豁免 / 暂不处理 | **已批准暂不清理；Stage 2 不因全仓风格检查修改阶段 0 文件** |

### 8.3 已批准的变更

用户 2026-11-10 的决定：

1. MF-1 两行导入修正——**已执行**。
2. 第 6.4 节的提交文件清单与第 6.5 节的排除清单——**已批准，按清单提交**。
3. MD-1 方案 B（`environment.lock.yml` 当前 Windows 环境快照）——**已执行**；不固定阶段 0 的 8 个直接依赖版本到 `environment.yml`。
4. MD-2 文档补充的范围与措辞——**纳入 Stage 2 文档同步**，本轮不改五份核心文档。
5. MD-3 是否在 Stage 2 前处理 Ruff 提示——**暂不清理**；Stage 2 不因全仓风格检查擅自修改阶段 0 文件。

---

## 9. 阶段 1 收尾结论

### 9.1 三态结论

**READY**

### 9.2 判定依据

1. **测试证据**：本轮独立复跑 `820 passed, 4 skipped`（单元）、`11 passed, 4 deselected`（离线集成）、`204 passed`（阶段 0 Schema），无 failure/error。
2. **符号链接边界**：4 条 Windows skip 的测试已在 WSL Linux 上真实执行并通过；Windows junction 测试本机通过；Inspector/Fixture/快照三个探针均未跟随或放行链接逃逸。
3. **数据契约**：未发现阶段 0 三个核心 Schema 被修改；阶段 1 Artifact Schema 独立；91 条 Finding 全部 `Stage1Analyzer`/`unverified`；LLM 不能修改工具证据或提权。
4. **文档一致性**：五份核心文档未发现阻断性冲突；低风险文档滞后已分类记录，均可通过文档补充解决。
5. **Git 边界**：`.env` 未被跟踪；真实产物与第三方代码片段可排除；没有未解释的本地修改（所有改动均可归因于 Stage 1.7 的导入统一、路径净化、README 更新与新增 smoke 测试）。
6. **真实外部调用**：MF-1 修复后复跑了真实 LLM 冒烟（1 passed，usage 54）；真实 GitHub Clone 与整仓扫描未复跑，引用 Stage 1.7 验收报告的既有证据，不把它们表述为本轮新通过。

### 9.3 附条件

READY 的提交条件已于 2026-11-10 满足：

1. **已完成**：MF-1 两行导入修正；默认运行 `1 skipped`，`RUN_LLM_SMOKE=1` 时 `1 passed`。
2. **已批准并执行**：提交使用第 6.4 节显式清单，禁止 `git add -A`；排除 `reports/stage1-20261110T120331Z-d8333a8c/`。
3. **已决策**：MD-1 采用方案 B，`environment.lock.yml` 已生成；Stage 2 启动前不再阻塞。
4. **保持**：真实产物目录不进入版本控制；如组织需要保留，按数据分级单独归档。
5. **Stage 2 约束**：新增依赖原则上只引入 `langgraph`；复用 Stage 1 的 `OpenAICompatibleClient`，不额外引入 `langchain-openai` 等模型接入依赖，除非后续审计证明必要并经批准。

### 9.4 不构成 Stage 1 失败的事项

- Windows 无法创建符号链接导致的 4 条 skip（已有 Linux 真实通过证据）。
- LLM 语义结果的轻微不确定性（阶段 1 只要求“解释与补充”，不要求确定性）。
- FastAPI 同步单槽（阶段 1 受控演示定位；Stage 4 解决）。
- 真实报告含第三方代码片段（已通过排除清单处理；Stage 2/7 继续治理）。
- Stage 1 环境锁为 Windows 快照（方案 B），不是跨平台锁；这是已知的可复现性边界，不是阶段 1 验收失败项。Stage 2 安装 `langgraph` 后需生成新快照，不得覆盖 Stage 1 基线。

---

## 10. Stage 2 启动前检查清单

### 10.1 提交与基线

- [x] 批准并完成 MF-1（`test_llm_smoke.py:15-16` 改为 `code_review.*`）。
- [x] 按第 6.4 节清单提交 Stage 1.7；确认 `git status` 中不再有未解释的源文件改动。
- [x] 确认 `reports/stage1-20261110T120331Z-d8333a8c/` 未被提交。
- [x] 确认 `git diff -- src/code_review/schemas docs` 仍为空。
- [ ] 记录 Stage 1.7 提交 SHA，作为 Stage 2 的起点基线（提交后由 `git log -1` 记录）。
- [ ] 如项目要求 tag，另行创建 Stage 1 tag（本轮未创建）。

### 10.2 依赖与可复现性

- [x] 决定 MD-1：采用 `environment.lock.yml` 当前 Windows 环境快照（方案 B）；已生成并随 Stage 1.7 提交。
- [ ] 明确 Stage 2 新增依赖审批流程：原则上只引入 `langgraph`；复用 Stage 1 的 `OpenAICompatibleClient`，不新增 `langchain-openai` 等模型接入依赖，除非审计批准。
- [x] 不固定阶段 0 的 8 个直接依赖版本到 `environment.yml`；实际版本由 `environment.lock.yml` 记录，不改变依赖组合。
- [x] 记录“必须使用 `conda run -n multi-agent-review`”的操作规范，避免 base 环境污染结果。
- [ ] 在 Linux CI 或 WSL 中至少运行一次完整单元/集成套件，覆盖 Windows skip 的符号链接用例。

### 10.3 文档与合同

- [x] 决定 MD-2：纳入 Stage 2 文档同步；补齐 Stage 1 字段口径、Fixture 元数据和 API 行为说明，不修改 Schema。
- [ ] 明确阶段 2 的 `report.json` / `ReviewReport` 与阶段 1 四件产物的边界，避免命名混淆。
- [x] 决定 MD-3：暂不清理 10 条冻结 Schema 的 Ruff 提示；Stage 2 不因全仓风格检查擅自修改阶段 0 文件。
- [ ] 确认 `docs/task_contracts.md` 仍为 v1.0，Stage 2 如需扩展合同，单独走修订流程。

### 10.4 Stage 2 范围与安全

- [ ] 确认 Stage 2 只引入 LangGraph 进程内编排、Manager/四个专业 Agent、Final Reviewer、`review_rules.yaml`、`report.json`；不引入 Redis/ARQ（Stage 4）、MCP（Stage 5）、A2A（Stage 6）。
- [ ] 确认 Stage 2 的 Agent 仍不得自行把 Finding 标为 `verified`；只有 Final Reviewer 可以改写。
- [ ] 确认 Stage 2 的并行节点只返回自己的状态键；列表字段使用 `Annotated[list, operator.add]` reducer。
- [ ] 确认 Stage 2 的 LLM Provider 仍通过 `config/settings.py` 注入，不在 Agent 内硬编码。
- [ ] 确认 Stage 2 的单元测试不联网、不调用真实 LLM；真实调用使用显式门控。
- [ ] 确认 Stage 2 不执行外部不可信仓库的测试/安装/构建脚本；沙箱建立前保持 `not_executed`。

### 10.5 数据与产物

- [ ] 确认真实产物目录的归档/保留策略；不得提交含第三方代码片段的产物。
- [ ] 确认 Stage 2 报告仍执行主机路径/密钥脱敏，并保留 `<workspace>`/`<home>`/`<temp>` 回归测试。
- [ ] 确认 Stage 2 的 `report.json` 通过 `ReviewReport` 校验后才生成 `report.md`，两者内容一致。

---

## 11. 收尾执行记录（2026-11-10）

### 11.1 用户决定

- MF-1：必须修复。
- MD-1：选择方案 B，生成 Stage 1 Windows 环境快照。
- MD-2：纳入 Stage 2 文档同步，不修改 Schema。
- MD-3：暂不清理冻结 Schema 的 Ruff 提示；Stage 2 不因全仓风格检查修改阶段 0 文件。
- Stage 2 依赖边界：原则上只新增 `langgraph`；复用 `OpenAICompatibleClient`，不新增 `langchain-openai` 等模型接入依赖，除非审计批准。

### 11.2 执行结果

| 步骤 | 动作 | 结果 |
| --- | --- | --- |
| 1 | 修复 `tests/integration/test_llm_smoke.py:15-16` 导入 | `src.code_review.*` → `code_review.*` |
| 1 | 默认运行该测试 | `1 skipped in 1.68s` |
| 1 | `RUN_LLM_SMOKE=1` 运行该测试 | `1 passed in 2.75s`；usage 54，latency 2153 ms |
| 2 | 生成 `environment.lock.yml` | 5 行头注释 + 62 行导出；Python 3.12.16；无主机路径 |
| 3 | 提交前检查 | `git diff -- src/code_review/schemas docs` 为空；`.env` 被忽略；新增文件无密钥/主机路径 |
| 4 | 显式路径提交 Stage 1.7 | 见 §6.4；排除 `reports/stage1-20261110T120331Z-d8333a8c/` |
| 5 | 记录提交 SHA | 提交后由 `git log -1 --format=%H` 记录 |

### 11.3 环境快照边界

`environment.lock.yml` 是**当前 Windows 环境的可复现快照**，不是跨平台锁文件：

- 适用平台：Windows 11 10.0.26100；Python 3.12.16。
- 已移除 `prefix:`，不含主机路径。
- 未升级、未替换、未删除任何依赖。
- Stage 2 安装 `langgraph` 后生成新的快照文件，不得覆盖本文件。
- `environment.yml` 仍是人类维护的依赖源；本轮未修改。

### 11.4 提交信息

```text
feat(stage1): complete single-agent code review foundation
```

---

## 附录 A：本轮证据索引

| 证据 | 位置/命令 | 结果 |
| --- | --- | --- |
| 全量单元测试 | `pytest tests/unit -q` | 820 passed, 4 skipped |
| 离线集成 | `pytest tests/integration -q -m "not real_network and not llm_smoke"` | 11 passed, 4 deselected |
| 阶段 0 Schema | `pytest tests/unit/test_{task,result,report}_schema.py -q` | 204 passed |
| Windows 符号链接定向 | 5 条测试 | 1 passed, 4 skipped |
| WSL Linux 符号链接 | 4 条测试 | 4 passed |
| LLM 冒烟（默认） | `pytest tests/integration/test_llm_smoke.py -q` | 1 skipped |
| LLM 冒烟（真实） | `RUN_LLM_SMOKE=1 pytest tests/integration/test_llm_smoke.py -q -s` | 1 passed；usage 54；latency 2153 ms |
| Inspector 探针 | WSL Linux | 仅 `normal.py`；链接均 `symlink` 过滤 |
| Fixture 探针 | WSL Linux | 文件链接/根链接均拒绝 |
| 快照探针 | WSL Linux | 链接记录 `link`，不跟随 |
| 真实产物统计 | `reports/stage1-20261110T120331Z-d8333a8c/static_analysis.json` | 240/91/90/1/49/1 |
| 真实 LLM 用量 | 同上 `llm_analysis.usage` | prompt 15,900 / completion 2,900 / total 18,800 |
| Git 状态 | `git status --porcelain` | 34 modified, 5 untracked（含 `environment.lock.yml`） |
| Schema/文档 diff | `git diff -- src/code_review/schemas docs` | 空 |
| `.env` 忽略 | `git check-ignore -v .env` | `.gitignore:1:.env` |
| 环境快照 | `environment.lock.yml` | Python 3.12.16；无 `prefix:`；无主机路径 |

## 附录 B：本轮未执行项

| 项 | 原因 | 现有证据 |
| --- | --- | --- |
| 真实 GitHub Clone | 本轮为只读审计，未重新联网 | 阶段 1.7 验收报告：Commit `672971d...`，`real_network` 门控测试通过 |
| 真实整仓扫描 | 本轮未重新生成真实产物 | `reports/stage1-20261110T120331Z-d8333a8c/`（既有产物） |
| 同平台干净环境重建 | 会改变当前环境，且没有必要；已生成快照 | `environment.lock.yml` 可在同平台重建 |
| 跨平台干净环境重建 | 未建立 Linux CI；方案 B 仅记录 Windows 快照 | 需 Stage 2 评估 `conda-lock` |
| 全量 Linux 套件 | 本轮只跑 4 条符号链接用例 | Windows 已跑全量；Linux 仅符号链接边界 |

---

**报告结束。**
