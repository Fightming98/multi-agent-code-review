"""工作区只读快照与差异检测的单元测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.code_review.tools.workspace_snapshot import (
    WorkspaceSnapshotError,
    compare_snapshots,
    snapshot_workspace,
)


def test_snapshot_hashes_regular_files(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "core.py").write_bytes(b"x = 1\n")
    (tmp_path / "README.md").write_bytes(b"hello\n")

    snapshot = snapshot_workspace(tmp_path)

    assert snapshot.total_files == 2
    assert snapshot.total_bytes == len(b"x = 1\n") + len(b"hello\n")
    assert set(snapshot.files) == {"pkg/core.py", "README.md"}
    assert all(len(digest) == 64 for digest in snapshot.files.values())


def test_snapshot_detects_added_removed_and_modified(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "keep.py").write_bytes(b"x = 1\n")
    (root / "remove.py").write_bytes(b"y = 2\n")
    before = snapshot_workspace(root)

    (root / "remove.py").unlink()
    (root / "keep.py").write_bytes(b"x = 2\n")
    (root / "added.py").write_bytes(b"z = 3\n")
    after = snapshot_workspace(root)

    diff = compare_snapshots(before, after)

    assert diff.changed is True
    assert diff.added == ("added.py",)
    assert diff.removed == ("remove.py",)
    assert diff.modified == ("keep.py",)
    assert diff.paths == ("added.py", "keep.py", "remove.py")


def test_unchanged_workspace_has_no_diff(tmp_path: Path) -> None:
    (tmp_path / "file.py").write_bytes(b"x = 1\n")

    diff = compare_snapshots(
        snapshot_workspace(tmp_path),
        snapshot_workspace(tmp_path),
    )

    assert diff.changed is False
    assert diff.paths == ()


def test_git_directory_is_excluded_by_default(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_bytes(b"[core]\n")
    (tmp_path / "file.py").write_bytes(b"x = 1\n")

    snapshot = snapshot_workspace(tmp_path)

    assert set(snapshot.files) == {"file.py"}


def test_excluded_dirs_can_be_disabled(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_bytes(b"[core]\n")
    (tmp_path / "file.py").write_bytes(b"x = 1\n")

    snapshot = snapshot_workspace(tmp_path, excluded_dirs=())

    assert set(snapshot.files) == {".git/config", "file.py"}


def test_missing_workspace_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceSnapshotError, match="exist"):
        snapshot_workspace(tmp_path / "missing")


def test_workspace_file_must_be_a_directory(tmp_path: Path) -> None:
    file = tmp_path / "file.py"
    file.write_bytes(b"x = 1\n")

    with pytest.raises(WorkspaceSnapshotError, match="directory"):
        snapshot_workspace(file)


def test_symlink_is_recorded_without_following(tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_bytes(b"x = 1\n")
    link = tmp_path / "link.py"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symbolic links are not permitted on this host")

    snapshot = snapshot_workspace(tmp_path)

    assert snapshot.files["link.py"] == "link"
    assert "target.py" in snapshot.files
