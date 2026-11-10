"""Repository Inspector 的单元测试：文件分类、过滤、统计与路径安全。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from config.settings import Settings
from src.code_review.tools.file_filters import (
    FileCategory,
    FileFilterPolicy,
    FilterReason,
)
from src.code_review.tools.repository_inspector import (
    TOTAL_SCAN_LIMIT_REASON,
    RepositoryInspectionError,
    RepositoryInspector,
)


def write_file(root: Path, relative: str, content: bytes | str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_bytes(content.encode("utf-8"))
    else:
        path.write_bytes(content)
    return path


def make_inspector(
    policy: FileFilterPolicy | None = None, **overrides: object
) -> RepositoryInspector:
    settings = Settings(_env_file=None, **overrides)
    return RepositoryInspector(settings, policy=policy)


def test_inventory_reports_files_and_statistics(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    write_file(repo, "app.py", "print('hi')\n")
    write_file(repo, "pkg/module.py", "a = 1\nb = 2")
    write_file(repo, "tests/test_app.py", "def test():\n    pass\n")
    write_file(repo, "README.md", "# Title\n")
    write_file(repo, "pyproject.toml", "[project]\n")
    write_file(repo, "requirements.txt", "pytest\n")
    write_file(repo, "notes.csv", "a,b\n")
    write_file(repo, "empty.py", "")

    inventory = make_inspector().inspect(repo)

    paths = [file.path for file in inventory.files]
    assert paths == sorted(paths)
    by_path = {file.path: file for file in inventory.files}

    assert by_path["app.py"].category == FileCategory.PYTHON_SOURCE
    assert by_path["app.py"].language == "python"
    assert by_path["app.py"].line_count == 1
    assert by_path["app.py"].size_bytes == len("print('hi')\n")

    assert by_path["pkg/module.py"].category == FileCategory.PYTHON_SOURCE
    assert by_path["pkg/module.py"].line_count == 2

    assert by_path["tests/test_app.py"].category == FileCategory.PYTHON_TEST
    assert by_path["tests/test_app.py"].line_count == 2
    assert by_path["README.md"].category == FileCategory.DOCUMENTATION
    assert by_path["pyproject.toml"].category == FileCategory.DEPENDENCY_MANIFEST
    assert by_path["requirements.txt"].category == FileCategory.DEPENDENCY_MANIFEST
    assert by_path["notes.csv"].category == FileCategory.OTHER_TEXT
    assert by_path["empty.py"].line_count == 0

    statistics = inventory.statistics
    assert statistics.total_files == 8
    assert statistics.python_source_files == 3
    assert statistics.python_test_files == 1
    assert statistics.project_config_files == 0
    assert statistics.dependency_manifests == 2
    assert statistics.documentation_files == 1
    assert statistics.other_text_files == 1
    assert statistics.total_line_count == 9
    assert statistics.scanned_bytes == sum(
        file.size_bytes for file in inventory.files
    )
    assert inventory.is_partial is False
    assert inventory.partial_reason is None
    assert len(inventory.python_files) == 4


def test_excluded_directories_are_pruned(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    for relative in [
        ".git/config",
        "__pycache__/module.pyc",
        ".venv/lib/python3.12/site.py",
        "venv/lib/python3.12/site.py",
        "node_modules/pkg/index.js",
        ".pytest_cache/state.json",
        "demo.egg-info/METADATA",
        "build/lib/module.py",
        "dist/package.tar.gz",
    ]:
        write_file(repo, relative, "ignored\n")
    write_file(repo, "src/app.py", "x = 1\n")

    inventory = make_inspector().inspect(repo)

    assert [file.path for file in inventory.files] == ["src/app.py"]
    assert set(inventory.excluded_directories) == {
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".pytest_cache",
        "demo.egg-info",
        "build",
        "dist",
    }


def test_sensitive_files_are_filtered_without_content(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    write_file(repo, ".env", "DATABASE_PASSWORD=supersecret\n")
    write_file(repo, "id_rsa", "-----BEGIN RSA PRIVATE KEY-----\nabc\n")
    write_file(repo, "certs/server.pem", "certificate material\n")
    write_file(repo, "renamed.txt", "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n")
    write_file(repo, "src/secrets.py", "TOKEN = 'abcdef'\n")
    write_file(repo, "app.py", "x = 1\n")

    inventory = make_inspector().inspect(repo)

    reasons = {file.path: file.reason for file in inventory.filtered_files}
    assert reasons[".env"] == FilterReason.SENSITIVE
    assert reasons["id_rsa"] == FilterReason.SENSITIVE
    assert reasons["certs/server.pem"] == FilterReason.SENSITIVE
    assert reasons["renamed.txt"] == FilterReason.SENSITIVE
    assert reasons["src/secrets.py"] == FilterReason.SENSITIVE
    assert [file.path for file in inventory.files] == ["app.py"]

    rendered = repr(inventory)
    assert "supersecret" not in rendered
    assert "abcdef" not in rendered
    assert "PRIVATE KEY" not in rendered


def test_binary_files_are_filtered(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    write_file(repo, "blob.dat", b"\x00\x01\x02\x03")
    write_file(repo, "app.py", "x = 1\n")

    inventory = make_inspector().inspect(repo)

    reasons = {file.path: file.reason for file in inventory.filtered_files}
    assert reasons["blob.dat"] == FilterReason.BINARY
    assert [file.path for file in inventory.files] == ["app.py"]


def test_oversized_file_is_skipped_and_recorded(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    write_file(repo, "big.py", b"x" * (1024 * 1024 + 1))
    write_file(repo, "small.py", "ok = True\n")

    inventory = make_inspector(max_single_file_size_mb=1).inspect(repo)

    reasons = {file.path: file.reason for file in inventory.filtered_files}
    assert reasons["big.py"] == FilterReason.OVERSIZED
    assert [file.path for file in inventory.files] == ["small.py"]
    assert inventory.is_partial is False


def test_total_scan_limit_stops_and_marks_partial(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    payload = b"x" * (600 * 1024)
    write_file(repo, "a_first.py", payload)
    write_file(repo, "b_second.py", payload)

    inventory = make_inspector(max_total_scan_size_mb=1).inspect(repo)

    assert inventory.is_partial is True
    assert inventory.partial_reason == TOTAL_SCAN_LIMIT_REASON
    assert [file.path for file in inventory.files] == ["a_first.py"]
    assert inventory.scanned_bytes == len(payload)
    assert inventory.statistics.scanned_bytes == len(payload)


def test_symlink_escape_is_filtered(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside_file = tmp_path / "outside.py"
    outside_file.write_text("secret = 1\n", encoding="utf-8")
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    write_file(outside_dir, "nested.py", "nested = 1\n")

    try:
        os.symlink(outside_file, repo / "link_file.py")
        os.symlink(outside_dir, repo / "link_dir")
    except OSError:
        pytest.skip("symlinks are not available on this platform")

    inventory = make_inspector().inspect(repo)

    reasons = {file.path: file.reason for file in inventory.filtered_files}
    assert reasons["link_file.py"] == FilterReason.SYMLINK
    assert reasons["link_dir"] == FilterReason.SYMLINK
    assert inventory.files == ()
    assert inventory.excluded_directories == ()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction test")
def test_windows_junction_escape_is_filtered(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    write_file(outside_dir, "nested.py", "nested = 1\n")
    link = repo / "link_dir"

    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(outside_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("unable to create a Windows junction")

    try:
        inventory = make_inspector().inspect(repo)

        reasons = {file.path: file.reason for file in inventory.filtered_files}
        assert reasons["link_dir"] == FilterReason.SYMLINK
        assert inventory.files == ()
        assert inventory.excluded_directories == ()
    finally:
        if link.exists():
            os.rmdir(link)


def test_python_encoding_declaration_is_respected(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    latin = "# -*- coding: latin-1 -*-\ncaf\xe9\n".encode("latin-1")
    write_file(repo, "latin.py", latin)
    write_file(repo, "broken.py", b"# -*- coding: no-such-codec -*-\nx = 1\n")

    inventory = make_inspector().inspect(repo)

    by_path = {file.path: file for file in inventory.files}
    reasons = {file.path: file.reason for file in inventory.filtered_files}
    assert by_path["latin.py"].line_count == 2
    assert reasons["broken.py"] == FilterReason.UNREADABLE


def test_custom_policy_is_used(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    write_file(repo, "custom_dir/app.py", "x = 1\n")
    write_file(repo, "node_modules/pkg/module.py", "y = 2\n")
    policy = FileFilterPolicy(excluded_directories=frozenset({"custom_dir"}))

    inventory = make_inspector(policy=policy).inspect(repo)

    assert inventory.excluded_directories == ("custom_dir",)
    assert [file.path for file in inventory.files] == ["node_modules/pkg/module.py"]


def test_missing_or_non_directory_root_is_rejected(tmp_path: Path) -> None:
    file_path = tmp_path / "not-a-directory"
    file_path.write_text("x", encoding="utf-8")

    with pytest.raises(RepositoryInspectionError):
        make_inspector().inspect(tmp_path / "missing")
    with pytest.raises(RepositoryInspectionError):
        make_inspector().inspect(file_path)


def test_empty_repository(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    inventory = make_inspector().inspect(repo)

    assert inventory.files == ()
    assert inventory.filtered_files == ()
    assert inventory.excluded_directories == ()
    assert inventory.statistics.total_files == 0
    assert inventory.is_partial is False
