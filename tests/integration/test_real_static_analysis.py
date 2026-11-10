"""真实 GitHub 仓库的静态分析工具集成测试。

默认不运行；需要 ``RUN_REAL_NETWORK=1``。目标仓库固定为
``pallets/itsdangerous``，只 Clone 后做 Ruff / Bandit / Radon 静态分析，
绝不执行仓库内的脚本或测试，仓库测试执行状态保持 ``not_executed``。
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

import pytest

from config.settings import Settings
from src.code_review.tools.bandit_tool import BanditTool
from src.code_review.tools.base import ToolExecutionResult, ToolExecutionStatus
from src.code_review.tools.radon_tool import RadonTool
from src.code_review.tools.repository_inspector import RepositoryInspector
from src.code_review.tools.repository_manager import RepositoryManager
from src.code_review.tools.ruff_tool import RuffTool

REPOSITORY_URL = "https://github.com/pallets/itsdangerous"
BRANCH = "main"
RUN_REAL_NETWORK = os.environ.get("RUN_REAL_NETWORK") == "1"

pytestmark = [
    pytest.mark.real_network,
    pytest.mark.skipif(
        not RUN_REAL_NETWORK,
        reason="set RUN_REAL_NETWORK=1 to run real-network integration tests",
    ),
]


def _assert_result_is_usable(
    result: ToolExecutionResult,
    *,
    expected_version: str,
    file_count: int,
) -> None:
    assert result.execution_status in {
        ToolExecutionStatus.SUCCESS,
        ToolExecutionStatus.FINDINGS,
    }
    assert result.error is None
    assert result.tool_version == expected_version
    assert result.analyzed_file_count == file_count
    assert result.exit_code is not None
    assert result.stdout_truncated is False
    assert result.stderr_truncated is False
    assert result.findings_truncated is False


def test_real_repository_static_analysis(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        workspace_root=str(tmp_path / "workspaces"),
    )

    with RepositoryManager(settings) as manager:
        snapshot = manager.clone(REPOSITORY_URL, branch=BRANCH)
        inventory = RepositoryInspector(settings).inspect(
            snapshot.workspace_path
        )

        assert inventory.is_partial is False
        python_files = [file.path for file in inventory.python_files]
        assert python_files
        assert all(path.endswith(".py") for path in python_files)
        assert not any(
            PurePosixPath(path).parts[0] == ".git" for path in python_files
        )

        ruff = RuffTool(settings).run(snapshot.workspace_path, python_files)
        bandit = BanditTool(settings).run(
            snapshot.workspace_path,
            python_files,
        )
        radon = RadonTool(settings).run(snapshot.workspace_path, python_files)

        expected_count = len(python_files)
        _assert_result_is_usable(
            ruff,
            expected_version="0.17.4",
            file_count=expected_count,
        )
        _assert_result_is_usable(
            bandit,
            expected_version="1.9.4",
            file_count=expected_count,
        )
        _assert_result_is_usable(
            radon,
            expected_version="6.0.1",
            file_count=expected_count,
        )

        # Radon 会为每个函数/方法输出复杂度块，真实仓库必然有结果。
        assert radon.findings
        assert any(
            finding.rule_id == "RADON_CC" for finding in radon.findings
        )

        known_paths = set(python_files)
        for result in (ruff, bandit, radon):
            for finding in result.findings:
                path = PurePosixPath(finding.file_path)
                assert not path.is_absolute()
                assert "\\" not in finding.file_path
                assert ".." not in path.parts
                assert finding.file_path in known_paths

        # 阶段 1 不执行被评审仓库的任何脚本或测试。
        assert not (snapshot.workspace_path / ".pytest_cache").exists()

    assert list((tmp_path / "workspaces").iterdir()) == []
