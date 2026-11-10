# trusted_fixture_v1

本目录是阶段 1 唯一允许在宿主机执行 Pytest / Coverage.py 的可信测试 Fixture。

## 约束

- 内容由项目维护并经过人工审查，不包含网络访问、安装脚本或第三方依赖。
- 文件字节级哈希记录在 `FIXTURE_MANIFEST.json`；执行前由 `TestRunner` 校验。
- 不要直接在本目录运行 `pytest`、`coverage` 或其他工具；该目录已被项目
  `pytest.ini` 的 `norecursedirs` 排除。
- 若修改任何 Fixture 文件，必须同步重新生成清单并发起人工审核。

## 结构

```text
calc/
  __init__.py   公开接口
  core.py       示例实现（multiply 故意不被测试覆盖）
tests/
  test_core.py  确定性测试（3 passed + 1 skipped）
FIXTURE_MANIFEST.json
```

## 预期结果

- 收集 4 条测试：3 passed、0 failed、1 skipped。
- Coverage.py 对 `calc` 包的总体覆盖率为 90%，`calc/core.py` 的 `multiply`
  函数未被覆盖。
