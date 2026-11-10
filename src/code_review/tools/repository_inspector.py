"""仓库扫描、文件分类与源码统计。

Inspector 只读取通过过滤策略的文本文件，用于计算行数；敏感文件、二进制、
超大文件与符号链接在读取内容前即被排除，且过滤结果不包含文件内容。
"""

from __future__ import annotations

import os
import tokenize
from dataclasses import dataclass
from pathlib import Path

from config.settings import Settings

from .file_filters import (
    FileCategory,
    FileFilterPolicy,
    FilterReason,
    classify_path,
    detect_language,
    is_binary_probe,
)

TOTAL_SCAN_LIMIT_REASON = "total_scan_size_limit"


class RepositoryInspectionError(RuntimeError):
    """仓库扫描无法进行（根目录不存在或不是目录）。"""


@dataclass(frozen=True)
class RepositoryFile:
    """通过过滤、进入扫描清单的文件。"""

    path: str
    category: FileCategory
    language: str | None
    line_count: int
    size_bytes: int


@dataclass(frozen=True)
class FilteredFile:
    """被过滤的文件及其原因；不包含任何文件内容。"""

    path: str
    reason: FilterReason
    size_bytes: int | None = None


@dataclass(frozen=True)
class RepositoryStatistics:
    """仓库文件统计。"""

    total_files: int
    python_source_files: int
    python_test_files: int
    project_config_files: int
    dependency_manifests: int
    documentation_files: int
    other_text_files: int
    filtered_files: int
    excluded_directories: int
    total_size_bytes: int
    scanned_bytes: int
    total_line_count: int


@dataclass(frozen=True)
class RepositoryInventory:
    """一次仓库扫描的完整结果。

    ``is_partial=True`` 表示总扫描大小达到上限并提前停止；调用方不得把
    该结果当作完整扫描结果使用。
    """

    root: Path
    files: tuple[RepositoryFile, ...]
    filtered_files: tuple[FilteredFile, ...]
    excluded_directories: tuple[str, ...]
    scanned_bytes: int
    is_partial: bool
    partial_reason: str | None

    @property
    def python_files(self) -> tuple[RepositoryFile, ...]:
        return tuple(
            file
            for file in self.files
            if file.category in (FileCategory.PYTHON_SOURCE, FileCategory.PYTHON_TEST)
        )

    @property
    def statistics(self) -> RepositoryStatistics:
        def count(category: FileCategory) -> int:
            return sum(1 for file in self.files if file.category == category)

        return RepositoryStatistics(
            total_files=len(self.files),
            python_source_files=count(FileCategory.PYTHON_SOURCE),
            python_test_files=count(FileCategory.PYTHON_TEST),
            project_config_files=count(FileCategory.PROJECT_CONFIG),
            dependency_manifests=count(FileCategory.DEPENDENCY_MANIFEST),
            documentation_files=count(FileCategory.DOCUMENTATION),
            other_text_files=count(FileCategory.OTHER_TEXT),
            filtered_files=len(self.filtered_files),
            excluded_directories=len(self.excluded_directories),
            total_size_bytes=sum(file.size_bytes for file in self.files),
            scanned_bytes=self.scanned_bytes,
            total_line_count=sum(file.line_count for file in self.files),
        )


class RepositoryInspector:
    """按过滤策略遍历仓库并生成文件清单与统计。"""

    def __init__(
        self,
        settings: Settings,
        policy: FileFilterPolicy | None = None,
    ) -> None:
        self.settings = settings
        self.policy = policy or FileFilterPolicy()

    def inspect(self, root: Path) -> RepositoryInventory:
        """扫描 ``root`` 指向的工作区并返回扫描结果。"""

        candidate = Path(root).expanduser()
        if not candidate.exists() or not candidate.is_dir():
            raise RepositoryInspectionError(f"repository root is not a directory: {root}")
        resolved_root = candidate.resolve()

        max_single_bytes = self.settings.max_single_file_size_mb * 1024 * 1024
        max_total_bytes = self.settings.max_total_scan_size_mb * 1024 * 1024

        files: list[RepositoryFile] = []
        filtered: list[FilteredFile] = []
        excluded_directories: list[str] = []
        scanned_bytes = 0
        partial_reason: str | None = None

        for current, dirnames, filenames in os.walk(
            resolved_root, topdown=True, followlinks=False
        ):
            current_path = Path(current)
            dirnames.sort()
            filenames.sort()

            kept_directories: list[str] = []
            for name in dirnames:
                child = current_path / name
                relative = self._relative(child, resolved_root)
                if self._is_link(child):
                    filtered.append(FilteredFile(path=relative, reason=FilterReason.SYMLINK))
                    continue
                if self.policy.is_excluded_directory(name):
                    excluded_directories.append(relative)
                    continue
                kept_directories.append(name)
            dirnames[:] = kept_directories

            for name in filenames:
                child = current_path / name
                relative = self._relative(child, resolved_root)

                if self._is_link(child):
                    filtered.append(FilteredFile(path=relative, reason=FilterReason.SYMLINK))
                    continue

                try:
                    resolved = child.resolve(strict=True)
                    size_bytes = resolved.stat().st_size
                except OSError:
                    filtered.append(
                        FilteredFile(path=relative, reason=FilterReason.UNREADABLE)
                    )
                    continue

                if not resolved.is_relative_to(resolved_root):
                    filtered.append(
                        FilteredFile(
                            path=relative,
                            reason=FilterReason.PATH_ESCAPE,
                            size_bytes=size_bytes,
                        )
                    )
                    continue

                if self.policy.is_sensitive_path(relative):
                    filtered.append(
                        FilteredFile(
                            path=relative,
                            reason=FilterReason.SENSITIVE,
                            size_bytes=size_bytes,
                        )
                    )
                    continue

                if self.policy.is_compiled_artifact(name):
                    filtered.append(
                        FilteredFile(
                            path=relative,
                            reason=FilterReason.COMPILED_ARTIFACT,
                            size_bytes=size_bytes,
                        )
                    )
                    continue

                if size_bytes > max_single_bytes:
                    filtered.append(
                        FilteredFile(
                            path=relative,
                            reason=FilterReason.OVERSIZED,
                            size_bytes=size_bytes,
                        )
                    )
                    continue

                if self.policy.is_unsupported_code(name):
                    filtered.append(
                        FilteredFile(
                            path=relative,
                            reason=FilterReason.UNSUPPORTED_LANGUAGE,
                            size_bytes=size_bytes,
                        )
                    )
                    continue

                category = classify_path(relative)
                if category is None:
                    filtered.append(
                        FilteredFile(
                            path=relative,
                            reason=FilterReason.UNSUPPORTED_LANGUAGE,
                            size_bytes=size_bytes,
                        )
                    )
                    continue

                if scanned_bytes + size_bytes > max_total_bytes:
                    partial_reason = TOTAL_SCAN_LIMIT_REASON
                    break

                try:
                    probe = self._read_probe(resolved)
                except OSError:
                    filtered.append(
                        FilteredFile(
                            path=relative,
                            reason=FilterReason.UNREADABLE,
                            size_bytes=size_bytes,
                        )
                    )
                    continue

                if is_binary_probe(probe):
                    filtered.append(
                        FilteredFile(
                            path=relative,
                            reason=FilterReason.BINARY,
                            size_bytes=size_bytes,
                        )
                    )
                    continue

                if self.policy.contains_private_key_marker(probe):
                    filtered.append(
                        FilteredFile(
                            path=relative,
                            reason=FilterReason.SENSITIVE,
                            size_bytes=size_bytes,
                        )
                    )
                    continue

                try:
                    line_count = self._count_lines(
                        resolved,
                        python=category
                        in (FileCategory.PYTHON_SOURCE, FileCategory.PYTHON_TEST),
                    )
                except (OSError, SyntaxError, UnicodeDecodeError, LookupError):
                    filtered.append(
                        FilteredFile(
                            path=relative,
                            reason=FilterReason.UNREADABLE,
                            size_bytes=size_bytes,
                        )
                    )
                    continue

                files.append(
                    RepositoryFile(
                        path=relative,
                        category=category,
                        language=detect_language(relative),
                        line_count=line_count,
                        size_bytes=size_bytes,
                    )
                )
                scanned_bytes += size_bytes

            if partial_reason is not None:
                break

        return RepositoryInventory(
            root=resolved_root,
            files=tuple(sorted(files, key=lambda file: file.path)),
            filtered_files=tuple(sorted(filtered, key=lambda file: file.path)),
            excluded_directories=tuple(sorted(excluded_directories)),
            scanned_bytes=scanned_bytes,
            is_partial=partial_reason is not None,
            partial_reason=partial_reason,
        )

    def _read_probe(self, path: Path) -> bytes:
        with path.open("rb") as handle:
            return handle.read(self.policy.binary_probe_bytes)

    @staticmethod
    def _count_lines(path: Path, *, python: bool) -> int:
        if python:
            with tokenize.open(path) as handle:
                text = handle.read()
        else:
            text = path.read_bytes().decode("utf-8", errors="replace")

        if not text:
            return 0
        return text.count("\n") + (0 if text.endswith("\n") else 1)

    @staticmethod
    def _is_link(path: Path) -> bool:
        """文件或目录是否为符号链接/Windows junction。

        ``os.walk(followlinks=False)`` 不会跟随符号链接，但会进入 Windows
        junction；必须在遍历前显式剪枝，防止扫描逃逸仓库根目录。
        """

        try:
            return path.is_symlink() or path.is_junction()
        except OSError:
            return False

    @staticmethod
    def _relative(path: Path, root: Path) -> str:
        return path.relative_to(root).as_posix()
