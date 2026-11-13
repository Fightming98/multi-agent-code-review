# Stage 2 Sample Fixture

本项目自维护、受控、可重复的 Stage 2 审查样例仓库。Fixture 内容由
`FIXTURE_MANIFEST.json` 逐文件固定 SHA-256，只有清单与字节完全一致时
TestRunner 才会执行测试。

Ground Truth（详细位置见验收报告）：

| GT | 问题 | 预期 Agent | 证据来源 |
| --- | --- | --- | --- |
| GT-1 | 硬编码默认密码 | SecurityAgent | Bandit B107 |
| GT-2 | SQL 字符串拼接 | SecurityAgent | Bandit B608 |
| GT-3 | 高圈复杂度函数 | QualityAgent | Radon CC |
| GT-4 | 文件读取缺少错误处理 | QualityAgent | 受控 Fake LLM |
| GT-5 | 一个测试断言故意失败 | TestingAgent | Pytest / JUnit |
| GT-6 | 覆盖率低于阈值 | TestingAgent | Coverage.py |
| GT-7 | 二次方扫描风险（可选） | PerformanceAgent | 受控 Fake LLM |

说明：

- `tests/test_inventory.py::test_low_stock_uses_exclusive_threshold` 的断言
  是有意写错的，用于验证“测试套件发现失败”与“TestRunner 自身执行失败”的
  区分。
- `sample_app/reporting.py` 不提供测试，用于稳定地把覆盖率压到配置阈值以下。
- Bandit 严重级别由工具原始级别经 `config/review_rules.yaml` 映射，不预设
  B107 或 B608 为 critical。
