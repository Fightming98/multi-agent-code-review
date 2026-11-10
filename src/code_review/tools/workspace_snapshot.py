"""工作区只读快照与变更检测。

执行测试或静态分析前后，对工作区内的常规文件计算 SHA-256，生成仓库相对
POSIX 路径到哈希的映射。任何新增、删除或内容变化都会在 diff 中显式列出，
用于 AC-1-12 的只读边界验证。符号链接/junction 只记录其存在，不跟随目标。
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType

_DEFAULT_EXCLUDED_DIRS = (".git",)
_LINK_MARKER = "link"


class WorkspaceSnapshotError(RuntimeError):
    """工作区无法被完整快照。"""


@dataclass(frozen=True)
class WorkspaceSnapshot:
    """工作区文件哈希快照。"""

    files: Mapping[str, str]
    total_files: int
    total_bytes: int

    @property
    def is_empty(self) -> bool:
        return not self.files


@dataclass(frozen=True)
class SnapshotDiff:
    """两个快照之间的差异。"""

    added: tuple[str, ...]
    removed: tuple[str, ...]
    modified: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed or self.modified)

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(sorted({*self.added, *self.removed, *self.modified}))


def snapshot_workspace(
    root: Path,
    *,
    excluded_dirs: tuple[str, ...] = _DEFAULT_EXCLUDED_DIRS,
) -> WorkspaceSnapshot:
    """递归记录工作区常规文件与链接的哈希。

    ``excluded_dirs`` 按目录名排除；默认排除 ``.git``。只读校验可信 Fixture
    时应传入空元组，确保 Fixture 内所有变化（包括缓存文件）都能被发现。
    """

    try:
        workspace = Path(root).expanduser().resolve(strict=True)
    except OSError as exc:
        raise WorkspaceSnapshotError("workspace does not exist") from exc
    if not workspace.is_dir():
        raise WorkspaceSnapshotError("workspace path is not a directory")

    excluded = set(excluded_dirs)
    files: dict[str, str] = {}
    total_bytes = 0

    for current, dirnames, filenames in os.walk(workspace, followlinks=False):
        current_path = Path(current)
        for dirname in list(dirnames):
            candidate = current_path / dirname
            if dirname in excluded:
                dirnames.remove(dirname)
                continue
            if _is_link(candidate):
                relative = _relative_posix(workspace, candidate) + "/"
                files[relative] = _LINK_MARKER
                dirnames.remove(dirname)
        for filename in filenames:
            candidate = current_path / filename
            relative = _relative_posix(workspace, candidate)
            if _is_link(candidate):
                files[relative] = _LINK_MARKER
                continue
            if not candidate.is_file():
                continue
            try:
                size = candidate.stat().st_size
            except OSError as exc:
                raise WorkspaceSnapshotError(
                    "workspace file could not be read"
                ) from exc
            files[relative] = _hash_file(candidate)
            total_bytes += size

    ordered = dict(sorted(files.items()))
    return WorkspaceSnapshot(
        files=MappingProxyType(ordered),
        total_files=len(ordered),
        total_bytes=total_bytes,
    )


def compare_snapshots(
    before: WorkspaceSnapshot,
    after: WorkspaceSnapshot,
) -> SnapshotDiff:
    """比较两个快照，返回排序后的新增、删除与修改路径。"""

    before_files = before.files
    after_files = after.files
    before_paths = set(before_files)
    after_paths = set(after_files)
    return SnapshotDiff(
        added=tuple(sorted(after_paths - before_paths)),
        removed=tuple(sorted(before_paths - after_paths)),
        modified=tuple(
            sorted(
                path
                for path in before_paths & after_paths
                if before_files[path] != after_files[path]
            )
        ),
    )


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(64 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise WorkspaceSnapshotError("workspace file could not be read") from exc
    return digest.hexdigest()


def _relative_posix(root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise WorkspaceSnapshotError(
            "workspace entry escapes the workspace"
        ) from exc
    return PurePosixPath(*relative.parts).as_posix()


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()
