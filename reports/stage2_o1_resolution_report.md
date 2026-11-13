# Stage 2 O-1 成本语义与真实 LLM 五件产物验证报告

- 日期：2026-11-13
- 状态：**PASS**
- 范围：O-1 方案实现、真实 LLM 进入 Stage 2 五件产物链路、缺陷修复与回归
- 未包含：Stage 3、Redis/ARQ、PostgreSQL、MCP/A2A、真实 LLM 自动化验收

## 1. 结论

O-1 已解决，真实 LLM 已进入 Stage 2 五件产物链路。真实调用返回的
`prompt_tokens` / `completion_tokens` 经 `config/llm_pricing.yaml` 的精确模型价格
换算后写入 `report.json.cost_summary`；缺少 usage、缺少价格或 token 不一致时报告
生成失败，不再伪造 0 成本。

真实端到端验证使用 `pallets/itsdangerous@672971d66a2ef9f85151e53283113f33d642dabd`，
生成五件产物，`llm_status=completed`，成本为 **0.01299775 USD**。

## 2. O-1 方案

### 2.1 价格表

- `config/llm_pricing.yaml`：按精确模型 ID 记录输入/输出单价、币种、官方来源与
  获取日期，不使用默认价或近似匹配。
- `config/llm_pricing.py`：严格加载并校验价格条目；`ModelPricing.estimate()` 使用
  `Decimal` 计算，避免浮点误差。
- 当前条目：`deepseek-ai/DeepSeek-V3`，USD，输入 **0.25** / 输出 **1.00**
  （每百万 token），来源为 SiliconFlow 官方模型页，`retrieved_at=2026-11-13`。

### 2.2 五件产物链路

```
CLI --real-llm
→ OpenAICompatibleClient
→ build_stage2_dependencies(llm_client=...)
→ Security / Quality / Performance Agent（受限语义补充）
→ Manager 聚合 UsageSummary
→ Final Reviewer 读取 ModelPricing，生成 CostSummary
→ Stage2ReportGenerator 校验成本一致性
→ metadata.json / static_analysis.json / test_report.json / report.json / report.md
```

- `--real-llm` 是显式可选入口；默认路径仍不调用 LLM。
- TestingAgent 不使用 LLM，测试统计只来自真实工具结果。
- 成本校验规则：无调用时 usage/token/cost 必须全为 0；有调用时
  `reported_usage_calls == llm_calls`、成本 token 与 usage token 一致、
  `estimated_cost > 0`。

## 3. 真实端到端验证

命令：

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = "src"
conda run --no-capture-output -n multi-agent-review `
  python -m code_review.cli review https://github.com/pallets/itsdangerous `
  --branch main --real-llm
```

结果：

| 项目 | 值 |
| --- | --- |
| review_id | `stage2-20261113T080311Z-aece7aa8` |
| Commit SHA | `672971d66a2ef9f85151e53283113f33d642dabd` |
| Python 文件 / 全部文件 | 15 / 48 |
| Agent 状态 | Security/Quality/Performance/Testing 全部 `completed` |
| LLM 调用 | 3 次，均返回真实 usage |
| 输入 / 输出 token | 47095 / 1224 |
| 估算成本 | 0.01299775 USD |
| Finding 数量 | 35（其中 LLM Finding 3 条） |
| 综合分 / 结论 | 70.9375 / `REQUEST_CHANGES` |
| 报告状态 | `partial`（外部仓库测试未执行） |
| 耗时 | 24.949 秒 |

五件产物位于本地：

```
reports/stage2-20261113T080311Z-aece7aa8/
├── metadata.json          2444 bytes
├── static_analysis.json  235106 bytes
├── test_report.json         853 bytes
├── report.json            86166 bytes
└── report.md              23064 bytes
```

`report.json` 中的成本：

```json
{
  "total_input_tokens": 47095,
  "total_output_tokens": 1224,
  "estimated_cost": 0.01299775,
  "currency": "USD"
}
```

`report.md` 显示 `估算成本：0.01 USD`；`report.json` 保留精确值，符合 B-2 裁定。

该目录包含第三方仓库代码片段与工具原始输出，**仅保留本地，不纳入版本控制**。

## 4. 首次失败的根因与修复

首次真实运行（`stage2-20261113T075552Z-d46d975b`）生成了五件产物，但
`llm_status=not_configured`，三个 Agent 均为 `partial`，警告为
`llm semantic supplement failed`。

根因：

1. `build_prompt_projection()` 最多读取 20 个文件 × 6000 字符，但
   `build_user_prompt()` 固定限制 30000 字符。
2. `itsdangerous` 的 15 个 Python 文件截断后仍约 44058 字符，投影序列化后超过
   30000 字符，`build_user_prompt()` 在调用客户端之前抛出 `LLMProjectionError`。
3. 该异常被 Agent 吞掉，`UsageAccumulator.llm_calls` 仍为 0，因此成本守卫没有触发，
   报告以零成本生成；同时 warning 没有携带失败原因，难以定位。

修复：

- `build_prompt_projection()` 新增 `max_prompt_chars` 预算：按确定性顺序省略末尾
  源码文件，直到序列化后的 user prompt 落入预算；省略数量写入 evidence warning。
- 三个专业 Agent 使用 `settings.llm_max_input_chars`（默认 60000）作为投影与
  `build_user_prompt()` 的共同预算。
- `describe_llm_error()` 将安全异常类型与消息写入 warning；未知异常只写类型名，
  避免泄漏第三方响应正文或凭据。
- 基础上下文本身超限时仍然失败，不发送截断或无效 Prompt。

修复后，`itsdangerous` 的 15 个源码文件全部进入投影（user prompt 约 50054 字符），
真实 LLM 调用成功。

## 5. 回归与安全检查

| 检查 | 结果 |
| --- | --- |
| 定向测试（LLM support / Security / Quality / Performance） | 134 passed |
| 单元测试 | 1308 passed, 5 skipped |
| 全量测试 | 1339 passed, 9 skipped |
| Ruff（本次改动文件） | All checks passed |
| 产物密钥扫描（`sk-` / `api_key`） | 未发现 |
| `.env` 跟踪状态 | 未跟踪 |

## 6. 限制与后续

- 本次仅验证一个真实仓库；真实 LLM 输出具有非确定性，不作为默认验收项。
- 外部仓库测试仍为 `not_executed`；本报告不改变 Stage 2 安全边界。
- Stage 2.6 整体验收仍等待负责人确认；未进入 Stage 3，未新增依赖。
- 本报告与真实产物均未提交；如需纳入版本控制，请负责人确认后使用显式路径提交，
  且不要提交 `reports/stage2-<timestamp>/` 第三方产物目录。
