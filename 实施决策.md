已经标注人工意见的事项视为已裁定，不再重复讨论：

- Q2 / C2： 实现最小同步 FastAPI `POST /api/reviews`。
- Q4 / C5： 实现 LLM 辅助分析，参考 `architecture.md` §8 的思路，由工具证据与 LLM 语义分析共同辅助组装 Finding；LLM 不得伪造证据。
- Q6 / C4： 阶段 1 不引入 Semgrep、Gitleaks、pip-audit，按阶段计划保留 Ruff、Bandit、Radon、Pytest、Coverage。

下面集中裁定其余 10 个问题：Q1、Q3、Q5、Q7、Q8、Q9、Q10、Q11、Q12、Q13。

### Q1：AC 编号以哪份文档为准？

裁定：A

以 `docs/acceptance.md` 原文编号为准。

理由很明确：`acceptance.md` 是项目正式验收依据，Prompt 中的映射表只是辅助说明。两者编号错位时，必须以正式验收文档为准，否则后续测试名称、验收证据、阶段报告都会产生系统性错配。

执行要求：

1. 不修改 `acceptance.md` 现有 AC 编号。
2. 修正 `阶段1_Prompt.md` §14 的错误映射表。
3. 所有测试、代码注释、阶段报告均按照 `acceptance.md` 的 AC 编号追溯。
4. 特别注意：
   - AC-1-09：可信仓库 Pytest + Coverage。
   - AC-1-10：外部不可信仓库禁止执行测试，状态为 `not_executed`。

### Q3：阶段 1 最终生成四件还是五件报告产物？

裁定：A

阶段 1 只生成四件，不生成 `report.json`。

Stage 1 输出目录

```
reports/
└── <review_id>/
    ├── metadata.json
    ├── static_analysis.json
    ├── test_report.json
    └── report.md
```

Stage 2 再引入

```
report.json
```

其内容为完整的 `ReviewReport`，由 Final Reviewer 生成。

这里必须坚持我们之前已经确认的架构边界：

- Stage 1 是线性单 Agent 基础工具链，不存在四个专业 Agent。
- `ReviewReport` 的 `dimension_scores` 和 `agent_results` 必须包含四个核心维度。
- Stage 1 如果为了生成 `report.json` 而虚构四个 Agent 的执行结果，就会破坏阶段边界和数据合同。

因此，Stage 1 的四个基础产物应使用独立的阶段专用模型校验；Stage 2 引入 Final Reviewer 后，再生成完整 `ReviewReport`。

需要额外修正的地方： `acceptance.md` 的 AC-1-15 目前写的是四个基础文件，但“JSON 符合 `task_contracts.md`”这一表述不够准确，因为合同没有定义这三份基础 JSON 的字段级 Schema。建议把它明确为：

- 三份 JSON 分别符合 Stage 1 专用 Pydantic Artifact Schema；
- `report.md` 由这三份结构化数据渲染；
- 不要求 Stage 1 生成完整 `ReviewReport`。

这也与报告中发现的字段合同缺口一致。

### Q5：Repository Manager、Repository Inspector 等组件放在哪里？

裁定：A

遵循 `architecture.md` 已有目录，不新增 `repository/`、`inspectors/` 等目录。

建议最终目录映射如下：

| 组件                 | 文件路径                         | 职责                            |
| -------------------- | -------------------------------- | ------------------------------- |
| Repository Manager   | `tools/repository_manager.py`    | Git Clone、SHA 固定、工作区管理 |
| Repository Inspector | `tools/repository_inspector.py`  | 仓库遍历、文件识别、源码统计    |
| URL Validator        | `tools/url_validator.py`         | GitHub URL 校验及安全限制       |
| File Filters         | `tools/file_filters.py`          | 文件类型、敏感文件、二进制过滤  |
| AnalysisTool         | `tools/base.py`                  | 静态分析工具抽象                |
| ToolExecutionResult  | `tools/base.py`                  | 工具执行结果 DTO                |
| ReviewService        | `services/review_service.py`     | 唯一业务入口                    |
| LLM Analyzer         | `services/llm_analyzer.py`       | LLM 语义分析                    |
| Artifact Models      | `reporting/artifact_models.py`   | 阶段 1 报告数据模型             |
| Report Generator     | `reporting/report_generator.py`  | JSON 产物生成                   |
| Markdown Renderer    | `reporting/markdown_renderer.py` | Markdown 报告渲染               |
| CLI                  | `cli.py`                         | 命令行入口                      |
| FastAPI              | `api/`                           | HTTP 接口                       |

这里我特别强调：目录映射必须服从架构依赖方向，而不是只要文件能运行就行。

例如：

- `schemas/` 不能反向依赖 `services/`。
- `tools/` 不应该直接调用 `ReviewService`。
- CLI 和 API 只能调用 `ReviewService`，不能各自实现一套审查流程。
- `ReviewService` 调用工具、聚合器和报告模块。

这能够为 Stage 2 引入 LangGraph 和多个专业 Agent 留出清晰的扩展边界。

### Q7：是否批准报告中的资源阈值？

有条件批准

大部分默认值可以直接采用，但必须补充两个关键约束。

报告给出的默认值总体比较合理，我建议如下：

| 配置                 | 裁定值                  | 我的意见 |
| -------------------- | ----------------------- | -------- |
| Clone 超时           | 300 秒                  | 采用     |
| Git 命令超时         | 300 秒                  | 采用     |
| 仓库大小             | 200 MB                  | 采用     |
| 文件数量             | 5,000                   | 采用     |
| 单文件大小           | 2 MB                    | 采用     |
| 总扫描大小           | 50 MB                   | 采用     |
| 单个静态工具超时     | 120 秒                  | 采用     |
| 单工具 stdout/stderr | 各 5 MiB                | 采用     |
| 单工具 Finding 上限  | 1,000                   | 采用     |
| Pytest 超时          | 300 秒                  | 采用     |
| Coverage 超时        | 300 秒                  | 采用     |
| LLM 请求超时         | 60 秒                   | 采用     |
| LLM 输入上限         | 60,000 字符             | 采用     |
| LLM 输出上限         | 2,000 tokens            | 采用     |
| LLM temperature      | 0.0                     | 采用     |
| LLM Finding 提案上限 | 50                      | 采用     |
| 可信仓库名单         | 仅 `trusted_fixture_v1` | 采用     |
| GitHub 域名          | 仅 `github.com`         | 采用     |
| GitHub 端口          | 443 或默认端口          | 采用     |

phase_1_pre_implementation_check_report.mdphase_1_pre_implementation_check_report.md

但有两个地方我不建议直接照搬报告中的实现描述。

第一，仓库大小限制不能只在 Clone 完成后检查。

如果先完整 Clone 一个超大仓库，最后才发现超过 200 MB，那么网络流量和磁盘空间已经被消耗了。

建议要求 Repository Manager：

- Clone 过程监控工作区磁盘占用；
- 结合 Clone 超时和资源监控，超过限制时终止 Git 进程树；
- Clone 完成后再次核验仓库大小、文件数量；
- 对超限情况明确记录 `resource_limit_exceeded`，并清理临时目录。

也就是说，200 MB 不只是一个事后统计指标，而应该成为 Clone 过程中的资源控制目标。

第二，超限处理必须区分“拒绝”和“跳过”。

我建议统一以下语义：

| 超限情况             | 处理方式                                                     |
| -------------------- | ------------------------------------------------------------ |
| 仓库整体超过 200 MB  | 拒绝本次审查                                                 |
| 文件数量超过 5,000   | 拒绝本次审查                                                 |
| 单个文件超过 2 MB    | 跳过该文件，记录过滤原因                                     |
| 总扫描大小超过 50 MB | 停止继续扫描，报告 `partial` 并记录原因，或按明确策略拒绝；不能静默截断 |
| 工具输出超过 5 MiB   | 截断输出，标记 `truncated=true`                              |
| 工具执行超过 120 秒  | 终止进程，记录 `timeout`                                     |

尤其是总扫描大小超过 50 MB 时，不建议直接把已经分析的结果伪装成完整分析结果。

另外，`keep_workspace_on_failure=false` 可以作为默认值，但安全审计需要保留足够的错误信息和资源超限记录；不能因为删除工作区就丢失诊断证据。

### Q8：可信 Fixture 是否允许在宿主机执行 Pytest/Coverage？

附条件批准

选择 A，但必须正式确认可信 Fixture 的例外边界。

这是我认为本轮最重要的安全裁定之一。

报告中指出，项目 `CLAUDE.md` 存在一条约束：

> 未沙箱化前，测试执行状态必须为 `not_executed`，绝不能执行不可信脚本。

与此同时，AC-1-09 又要求对可信测试仓库真实执行 Pytest/Coverage。

这两者不能简单地靠一个 `--trusted` 参数解决。

phase_1_pre_implementation_check_report.md

我的建议是：

仅允许项目自己维护、经过审查、固定版本的 Fixture 在宿主机执行。

具体约束：

1. 仅允许 `tests/fixtures/trusted_repo/` 下的 Fixture。
2. Fixture 必须由项目开发者编写并经过人工审查。
3. 使用固定的 Fixture 版本或哈希清单，不允许运行时动态替换。
4. 不允许用户传入任意 GitHub URL，再通过 `--trusted` 提升信任等级。
5. 不自动安装 Fixture 的第三方依赖。
6. 不执行 Fixture 中的 `setup.py`、`build.py` 或任意安装脚本。
7. 外部 GitHub 仓库一律视为不可信，测试状态必须为 `not_executed`。
8. 可信 Fixture 的测试执行数据与普通外部仓库数据必须在报告中区分。

这里还需要做一件事：在 `CLAUDE.md` 中明确写入“项目自维护白名单 Fixture”的受控例外。

否则，Claude Code 后续可能会把“未沙箱化前一律不执行测试”理解成绝对禁止，从而导致 AC-1-09 无法实现。

### Q9：阶段 1 Finding 的 agent_name、task_type 和产物模型位置如何定义？

裁定：采用 A 的主体方案，微调命名

报告提出：

```
agent_name = "Stage1ReviewAgent"
task_type = "stage1_review"
verification_status = "unverified"
```

其中 `verification_status="unverified"` 我完全赞同；但我不建议直接把 `Stage1ReviewAgent` 当作真正的 Agent 名称。

原因是 Stage 1 明确不实现多 Agent，也不引入 Stage 2 的 Agent 执行架构。此时使用 `Stage1ReviewAgent` 容易让后续开发者误以为已经存在一个符合 Agent 注册表和任务合同的 Agent。

我的建议：

- Finding 的 `agent_name` 使用一个明确的阶段 1 来源标识，例如 `Stage1Analyzer`。
- 在阶段 1 文档中注明：`Stage1Analyzer` 是单 Agent 基础分析流程的来源标识，不代表已经实现了 Stage 2 的专业 Agent。
- `task_type="stage1_review"` 仅在确实需要创建相应任务对象时使用；不要为了填充这个值而额外创建一套 Stage 1 `AgentTask` 任务体系。
- 所有 Stage 1 Finding 的 `verification_status` 保持 `unverified`。
- 不允许 Stage 1 工具或 LLM 直接把 Finding 标记为 `verified`。
- LLM 不合格的 Finding 提案放在 `llm_analysis.rejected[]`，保留拒绝原因，不得混入正式 Finding 列表。

产物模型则采用报告的建议：

```
src/code_review/reporting/artifact_models.py
```

这些模型属于 Stage 1 专用数据模型，不得修改三个阶段 0 核心 Schema 文件。

还有一个细节：不要把 LLM 生成的语义描述直接当成 ToolEvidence。 工具证据必须来自真实工具调用；LLM 语义分析应保留自己的来源记录。最终 Finding 的证据必须经过确定性校验，不能因为 LLM 声称某行代码存在问题，就直接认定证据成立。

这样既能满足 Finding 的数据合同，也不会提前引入 Final Reviewer 的核验职责。

### Q10：是否允许修改已经冻结的 acceptance.md / architecture.md？

裁定：A

允许修改，但必须通过正式变更记录，禁止随意改写冻结文档。



报告建议 B，即只在 `settings.py` 和验收报告中记录阈值。

我不赞同完全采用 B，因为 `requirements.md` 的 D2 已经明确要求：

- 阈值在 `config/settings.py` 中定义；
- 阈值在 `acceptance.md` 中记录。

如果只修改代码和验收报告，就没有真正满足 D2。

phase_1_pre_implementation_check_report.md

建议采用以下方式：

| 文件                     | 是否允许修改 | 修改范围                                                     |
| ------------------------ | ------------ | ------------------------------------------------------------ |
| `docs/acceptance.md`     | 允许         | 补充 Stage 1 阈值、验收命令、可信 Fixture 规则、AC-1-15 的 JSON 验收口径 |
| `docs/architecture.md`   | 允许         | 补充 Stage 1 组件映射，修正阶段 1～3 流程图中提前出现 LangGraph 的问题 |
| `docs/requirements.md`   | 原则上不改   | 仅当发现实际需求表述冲突时，经过批准再修改                   |
| `docs/workflow.md`       | 原则上不改   | 仅在需要澄清 Stage 1 执行流程或安全边界时修改                |
| `docs/task_contracts.md` | 不允许       | Stage 1 不修改阶段 0 已冻结的数据合同                        |

每次修改都要求：

1. 说明修改原因。
2. 记录原文和新文的差异。
3. 说明影响哪些 AC、TC 或模块。
4. 同步检查相关测试。
5. 经过你人工确认后再提交。

我建议不要把“文档冻结”理解成永远不能修改，而应该理解为：未经批准不能修改，批准后必须有变更记录。

### Q11：三份未提交文档修改如何处理？

裁定：A

确认作为阶段 1 前的正式基线提交。

这里报告第 1.3 节已经有你的人工意见：

> 已人工确认这些修改并让 CC 作为新的冻结基线提交。

因此，我建议 Q11 不再重新讨论，直接按 A 执行。

但要注意提交前检查：

- `docs/architecture.md`
- `docs/requirements.md`
- `项目总框架与实施计划V2.0.md`

这三份文件的修改内容应与人工确认的版本一致。

另外，`阶段1_Prompt.md` 当前是未跟踪文件。是否提交它可以独立处理，不要把它和三份核心文档的冻结基线混为一谈。

### Q12：PASS / BLOCKED / FAIL 与无 API Key 时如何验收？

裁定：A，但 BLOCKED 不等于通过

我建议采用三态：

| 状态      | 含义                                   | 是否允许宣布 Stage 1 PASS |
| --------- | -------------------------------------- | ------------------------- |
| `PASS`    | 全部要求满足，证据完整                 | 允许                      |
| `BLOCKED` | 因外部条件或前置条件缺失，无法完成验收 | 不允许                    |
| `FAIL`    | 已执行验收，但实际结果不符合要求       | 不允许                    |

这里要解决的是一个逻辑问题：

- `acceptance.md` 明确要求所有 AC 和 TC 满足；
- `TC-1-06` 要求完成一次真实 LLM 调用冒烟测试；
- 如果没有 API Key，测试无法执行；
- 不能因为没有 API Key，就把未执行的测试当作通过。

因此：

如果没有 API Key，TC-1-06 应标记为 BLOCKED，整个 Stage 1 的最终状态也只能是 BLOCKED，而不是 PASS。

这不代表代码实现失败，但也不能把阶段验收宣布为完成。

我建议在阶段验收报告中同时保留：

```
TC-1-06: BLOCKED
Reason: LLM API credentials are not configured.

Overall Stage 1 Status: BLOCKED
```

当 API Key 配置完成后，再补做真实模型调用测试。

这样既保留了工程实施的客观性，也不违背 `acceptance.md` “不设有条件通过”的原则。

### Q13：真实 GitHub Clone 目标仓库选哪个？

裁定：A

选择 `https://github.com/pallets/itsdangerous`。

理由：

- 公开的 Python 项目，适合验证 GitHub HTTPS URL 校验。
- 仓库规模相对适中，适合阶段 1 的 Clone 和源码扫描测试。
- 能够验证真实 Commit SHA 固定、文件识别、静态工具执行和报告生成。
- 不需要引入私有仓库认证流程。

但有一个必须强调的边界：

真实 Clone 测试只验证仓库获取与静态分析链路，不执行这个外部仓库的 Pytest、安装脚本或构建脚本。

它与 Q8 的自维护可信 Fixture 是两种不同的测试对象，不能混为一谈。