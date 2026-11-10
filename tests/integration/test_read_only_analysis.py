"""静态分析工具的只读边界集成测试。

Ruff / Bandit / Radon 只允许读取工作区并输出结构化发现；本测试在真实
Fixture 副本前后做 SHA-256 快照，确认没有新增、删除、修改或缓存文件。
"""

from __future__ import annotations

from pathlib import Path

from code_review.tools.bandit_tool import BanditTool
from code_review.tools.base import ToolExecutionStatus
from code_review.tools.radon_tool import RadonTool
from code_review.tools.ruff_tool import RuffTool
from code_review.tools.workspace_snapshot import (
    compare_snapshots,
    snapshot_workspace,
)
from config.settings import Settings
from tests.fixture_factory import copy_trusted_fixture

ANALYZED_FILES = [
    "calc/__init__.py",
    "calc/core.py",
    "tests/test_core.py",
]


def test_static_analysis_is_read_only(tmp_path: Path) -> None:
    workspace = copy_trusted_fixture(tmp_path / "fixture")
    settings = Settings(_env_file=None)
    before = snapshot_workspace(workspace)

    results = [
        RuffTool(settings).run(workspace, ANALYZED_FILES),
        BanditTool(settings).run(workspace, ANALYZED_FILES),
        RadonTool(settings).run(workspace, ANALYZED_FILES),
    ]

    after = snapshot_workspace(workspace)
    diff = compare_snapshots(before, after)

    assert diff.changed is False, diff.paths
    for result in results:
        assert result.execution_status in {
            ToolExecutionStatus.SUCCESS,
            ToolExecutionStatus.FINDINGS,
        }, result.error
        assert result.error is None
        assert result.analyzed_file_count == len(ANALYZED_FILES)

    assert not any(workspace.rglob(".ruff_cache"))
    assert not any(workspace.rglob(".pytest_cache"))
    assert not any(workspace.rglob("__pycache__"))
    assert not any(workspace.rglob("*.pyc"))


def test_analysis_findings_use_relative_paths(tmp_path: Path) -> None:
    workspace = copy_trusted_fixture(tmp_path / "fixture")
    settings = Settings(_env_file=None)

    results = [
        RuffTool(settings).run(workspace, ANALYZED_FILES),
        BanditTool(settings).run(workspace, ANALYZED_FILES),
        RadonTool(settings).run(workspace, ANALYZED_FILES),
    ]

    for result in results:
        for finding in result.findings:
            assert not Path(finding.file_path).is_absolute()
            assert "\\" not in finding.file_path
            assert ".." not in Path(finding.file_path).parts
