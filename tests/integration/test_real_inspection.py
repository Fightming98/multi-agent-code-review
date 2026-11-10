"""真实 GitHub 仓库的 Inspector 集成测试。

默认不运行；需要 ``RUN_REAL_NETWORK=1``。只 Clone 并扫描文件元数据，
不执行仓库内任何脚本或测试。
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

import pytest

from code_review.tools.repository_inspector import RepositoryInspector
from code_review.tools.repository_manager import RepositoryManager
from config.settings import Settings

REPOSITORY_URL = "https://github.com/pallets/itsdangerous"
RUN_REAL_NETWORK = os.environ.get("RUN_REAL_NETWORK") == "1"

pytestmark = [
    pytest.mark.real_network,
    pytest.mark.skipif(
        not RUN_REAL_NETWORK,
        reason="set RUN_REAL_NETWORK=1 to run real-network integration tests",
    ),
]


def test_inspect_real_repository(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, workspace_root=str(tmp_path / "workspaces"))

    with RepositoryManager(settings) as manager:
        snapshot = manager.clone(REPOSITORY_URL, branch="main")
        inventory = RepositoryInspector(settings).inspect(snapshot.workspace_path)

        assert inventory.is_partial is False
        assert inventory.partial_reason is None
        assert inventory.statistics.python_source_files > 0
        assert inventory.statistics.python_test_files > 0
        assert inventory.statistics.dependency_manifests > 0
        assert inventory.statistics.documentation_files > 0
        assert inventory.scanned_bytes > 0

        assert all(file.language == "python" for file in inventory.python_files)
        assert all(file.line_count >= 0 for file in inventory.files)

        for file in inventory.files:
            path = PurePosixPath(file.path)
            assert not path.is_absolute()
            assert "\\" not in file.path
            assert ".." not in path.parts
            assert ".git" not in path.parts

        assert not any(
            file.path.endswith((".pyc", ".pyo")) for file in inventory.files
        )
        assert not any(file.path == ".env" for file in inventory.files)

    assert list((tmp_path / "workspaces").iterdir()) == []
