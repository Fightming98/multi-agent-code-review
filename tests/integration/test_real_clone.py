"""真实 GitHub Clone 集成测试。

默认不运行；需要显式设置 ``RUN_REAL_NETWORK=1`` 才会访问 GitHub。
目标仓库固定为 ``pallets/itsdangerous``，只做 Clone 与 Git 元数据校验，
不执行仓库内任何脚本或测试。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from config.settings import Settings
from src.code_review.tools.repository_manager import RepositoryManager
from src.code_review.tools.url_validator import is_full_commit_sha

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


def test_clone_real_repository_and_pin_commit(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, workspace_root=str(tmp_path / "workspaces"))

    with RepositoryManager(settings) as manager:
        by_branch = manager.clone(REPOSITORY_URL, branch=BRANCH)

        assert by_branch.owner == "pallets"
        assert by_branch.name == "itsdangerous"
        assert by_branch.repository_url == REPOSITORY_URL
        assert by_branch.branch == BRANCH
        assert is_full_commit_sha(by_branch.commit_sha)
        assert by_branch.workspace_path.is_dir()
        assert (by_branch.workspace_path / ".git").is_dir()
        assert by_branch.file_count > 0
        assert by_branch.size_bytes > 0
        assert by_branch.git_version.startswith("git version")

        head_file = by_branch.workspace_path / ".git" / "HEAD"
        assert head_file.read_text(encoding="utf-8").strip() == by_branch.commit_sha

        # 再按固定 SHA Clone，验证同一提交可确定性复现。
        by_sha = manager.clone(REPOSITORY_URL, commit_sha=by_branch.commit_sha)

        assert by_sha.commit_sha == by_branch.commit_sha
        assert by_sha.repository_url == REPOSITORY_URL
        assert (
            by_sha.workspace_path / ".git" / "HEAD"
        ).read_text(encoding="utf-8").strip() == by_sha.commit_sha

    assert list((tmp_path / "workspaces").iterdir()) == []
