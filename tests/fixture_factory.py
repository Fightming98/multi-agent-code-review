"""测试辅助：构造临时可信 Fixture 与固定清单。

这些辅助只写入测试提供的临时目录，不修改项目自维护的
``tests/fixtures/trusted_repo/``。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Mapping
from pathlib import Path

from code_review.tools.trusted_fixture import (
    DEFAULT_TRUSTED_FIXTURE_ROOT,
    FIXTURE_MANIFEST_FILENAME,
)


def make_trusted_fixture(
    root: Path,
    files: Mapping[str, str],
    *,
    name: str = "trusted_fixture_v1",
    version: str = "1.0.0",
) -> Path:
    """在 ``root`` 下写入文件并生成匹配的清单。"""

    root.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        if relative == FIXTURE_MANIFEST_FILENAME:
            raise ValueError("fixture files must not include the manifest itself")
        target = root.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))
    rewrite_manifest(root, name=name, version=version)
    return root


def copy_trusted_fixture(destination: Path) -> Path:
    """复制项目自维护 Fixture，便于测试篡改检测。"""

    shutil.copytree(
        DEFAULT_TRUSTED_FIXTURE_ROOT,
        destination,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            ".pytest_cache",
            "*.pyc",
        ),
    )
    return destination


def rewrite_manifest(
    root: Path,
    *,
    name: str = "trusted_fixture_v1",
    version: str = "1.0.0",
) -> None:
    """按当前文件内容重新生成清单。"""

    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative == FIXTURE_MANIFEST_FILENAME:
            continue
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "fixture_name": name,
        "version": version,
        "files": files,
    }
    (root / FIXTURE_MANIFEST_FILENAME).write_bytes(
        (
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    )
