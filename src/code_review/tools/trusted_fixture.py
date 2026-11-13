"""可信测试 Fixture 的固定路径、固定清单与字节级哈希校验。

阶段 1 只允许 ``tests/fixtures/trusted_repo/`` 下的项目自维护 Fixture 在宿主机
执行 Pytest / Coverage.py。本模块负责在执行前确认：

- Fixture 目录不是符号链接或 junction；
- ``FIXTURE_MANIFEST.json`` 存在、结构严格且名称匹配；
- 清单与实际文件集合完全一致，没有新增、缺失或未登记文件；
- 每个文件的 SHA-256 与清单一致，清单本身也计算哈希；
- 清单中的路径是安全的仓库相对 POSIX 路径。

任何校验失败都返回不带宿主机绝对路径的错误；调用方不得在失败后执行 Fixture。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

DEFAULT_TRUSTED_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "trusted_repo"
)
FIXTURE_MANIFEST_FILENAME = "FIXTURE_MANIFEST.json"

# 阶段 1 可信 Fixture 白名单（docs/acceptance.md §4.7）。
# Stage 2.6 仅新增一个明确批准的自有 Fixture；批准规则与校验逻辑不变。
APPROVED_TRUSTED_FIXTURE_NAMES = frozenset(
    {"trusted_fixture_v1", "stage2_sample_repo_v1"}
)

MAX_MANIFEST_BYTES = 1 * 1024 * 1024
MAX_FIXTURE_FILES = 1_000
MAX_FIXTURE_FILE_BYTES = 10 * 1024 * 1024
MAX_FIXTURE_TOTAL_BYTES = 20 * 1024 * 1024

_FIXTURE_NAME_PATTERN = re.compile(r"^[a-z0-9_]{1,64}$")
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MANIFEST_KEYS = {"fixture_name", "version", "files"}


class TrustedFixtureError(RuntimeError):
    """可信 Fixture 不存在、被修改或清单不符合约定。"""


@dataclass(frozen=True)
class TrustedFixture:
    """通过校验的可信 Fixture。

    ``root`` 是宿主机绝对路径，只供执行模块内部使用，不得写入报告、日志或
    模型输入。对外结果只暴露名称、版本、清单哈希与相对文件哈希。
    """

    name: str
    version: str
    root: Path
    manifest_sha256: str
    file_hashes: Mapping[str, str]

    @property
    def file_count(self) -> int:
        return len(self.file_hashes)

    @property
    def manifest_path(self) -> Path:
        return self.root / FIXTURE_MANIFEST_FILENAME


def verify_trusted_fixture(
    fixture_root: Path | None = None,
    *,
    expected_name: str,
) -> TrustedFixture:
    """校验并返回可信 Fixture；失败时抛出 ``TrustedFixtureError``。

    ``fixture_root`` 仅用于测试注入；生产调用应省略该参数，始终使用
    ``tests/fixtures/trusted_repo/``。
    """

    if not isinstance(expected_name, str) or not _FIXTURE_NAME_PATTERN.fullmatch(
        expected_name
    ):
        raise TrustedFixtureError("trusted fixture name is invalid")
    if expected_name not in APPROVED_TRUSTED_FIXTURE_NAMES:
        raise TrustedFixtureError("trusted fixture name is not approved")

    root = Path(fixture_root) if fixture_root is not None else DEFAULT_TRUSTED_FIXTURE_ROOT
    root = root.expanduser()
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise TrustedFixtureError("trusted fixture directory does not exist") from exc
    if _is_link(root) or _is_link(resolved_root):
        raise TrustedFixtureError("trusted fixture directory must not be a link")
    if not resolved_root.is_dir():
        raise TrustedFixtureError("trusted fixture path is not a directory")
    root = resolved_root

    manifest_path = root / FIXTURE_MANIFEST_FILENAME
    if _is_link(manifest_path):
        raise TrustedFixtureError("fixture manifest must not be a link")
    if not manifest_path.is_file():
        raise TrustedFixtureError("fixture manifest is missing")

    manifest_bytes = _read_limited(
        manifest_path,
        MAX_MANIFEST_BYTES,
        "fixture manifest exceeds the size limit",
    )
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    manifest = _load_manifest(manifest_bytes)

    if set(manifest) != _MANIFEST_KEYS:
        raise TrustedFixtureError("fixture manifest has an unexpected structure")

    name = manifest["fixture_name"]
    version = manifest["version"]
    files = manifest["files"]
    if not isinstance(name, str) or not _FIXTURE_NAME_PATTERN.fullmatch(name):
        raise TrustedFixtureError("fixture manifest name is invalid")
    if name != expected_name:
        raise TrustedFixtureError("fixture manifest name does not match the configured name")
    if not isinstance(version, str) or not _VERSION_PATTERN.fullmatch(version):
        raise TrustedFixtureError("fixture manifest version is invalid")
    if not isinstance(files, dict) or not files:
        raise TrustedFixtureError("fixture manifest file list is empty or invalid")
    if len(files) > MAX_FIXTURE_FILES:
        raise TrustedFixtureError("fixture manifest contains too many files")

    declared: dict[str, str] = {}
    for raw_path, digest in files.items():
        relative = _validate_relative_posix(raw_path)
        if not isinstance(digest, str) or not _SHA256_PATTERN.fullmatch(digest):
            raise TrustedFixtureError("fixture manifest contains an invalid SHA-256 value")
        declared[relative] = digest

    actual = _actual_file_set(root)
    declared_set = set(declared)
    if actual != declared_set:
        missing = sorted(declared_set - actual)
        extra = sorted(actual - declared_set)
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(missing[:3]))
        if extra:
            details.append("extra=" + ",".join(extra[:3]))
        raise TrustedFixtureError(
            "fixture file set does not match manifest (" + "; ".join(details) + ")"
        )

    for relative in sorted(declared):
        actual_digest = _hash_file(root / relative)
        if actual_digest != declared[relative]:
            raise TrustedFixtureError(
                f"fixture file hash mismatch: {relative}"
            )

    return TrustedFixture(
        name=name,
        version=version,
        root=root,
        manifest_sha256=manifest_sha256,
        file_hashes=MappingProxyType(dict(sorted(declared.items()))),
    )


def _load_manifest(manifest_bytes: bytes) -> dict[str, Any]:
    try:
        text = manifest_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TrustedFixtureError("fixture manifest is not valid UTF-8") from exc
    try:
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except TrustedFixtureError:
        raise
    except json.JSONDecodeError as exc:
        raise TrustedFixtureError("fixture manifest is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise TrustedFixtureError("fixture manifest must be a JSON object")
    return payload


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TrustedFixtureError("fixture manifest contains duplicate keys")
        result[key] = value
    return result


def _actual_file_set(root: Path) -> set[str]:
    actual: set[str] = set()
    total_bytes = 0
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        for dirname in list(dirnames):
            candidate = current_path / dirname
            if _is_link(candidate):
                raise TrustedFixtureError(
                    "fixture contains a symbolic link or junction"
                )
        for filename in filenames:
            candidate = current_path / filename
            if _is_link(candidate):
                raise TrustedFixtureError(
                    "fixture contains a symbolic link or junction"
                )
            if not candidate.is_file():
                raise TrustedFixtureError("fixture contains a non-regular file")
            relative = _relative_posix(root, candidate)
            if relative == FIXTURE_MANIFEST_FILENAME:
                continue
            actual.add(_validate_relative_posix(relative))
            if len(actual) > MAX_FIXTURE_FILES:
                raise TrustedFixtureError("fixture contains too many files")
            try:
                size = candidate.stat().st_size
            except OSError as exc:
                raise TrustedFixtureError("fixture file could not be read") from exc
            if size > MAX_FIXTURE_FILE_BYTES:
                raise TrustedFixtureError("fixture file exceeds the size limit")
            total_bytes += size
            if total_bytes > MAX_FIXTURE_TOTAL_BYTES:
                raise TrustedFixtureError("fixture total size exceeds the limit")
    return actual


def _validate_relative_posix(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise TrustedFixtureError("fixture manifest contains an empty file path")
    if len(value) > 512:
        raise TrustedFixtureError("fixture manifest contains an overlong file path")
    if "\\" in value or "\x00" in value or ":" in value:
        raise TrustedFixtureError("fixture manifest contains an unsafe file path")
    pure = PurePosixPath(value)
    if (
        not pure.parts
        or pure.is_absolute()
        or ".." in pure.parts
        or "." in pure.parts
    ):
        raise TrustedFixtureError("fixture manifest contains an unsafe file path")
    if pure.as_posix() != value:
        raise TrustedFixtureError("fixture manifest contains a non-canonical file path")
    return value


def _relative_posix(root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise TrustedFixtureError("fixture file escapes the fixture directory") from exc
    return PurePosixPath(*relative.parts).as_posix()


def _read_limited(path: Path, limit: int, message: str) -> bytes:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise TrustedFixtureError("fixture file could not be read") from exc
    if size > limit:
        raise TrustedFixtureError(message)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise TrustedFixtureError("fixture file could not be read") from exc
    if len(data) > limit:
        raise TrustedFixtureError(message)
    return data


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(64 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise TrustedFixtureError("fixture file could not be read") from exc
    return digest.hexdigest()


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()
