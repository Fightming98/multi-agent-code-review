"""可信 Fixture 清单与哈希校验的单元测试。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from code_review.tools.trusted_fixture import (
    DEFAULT_TRUSTED_FIXTURE_ROOT,
    FIXTURE_MANIFEST_FILENAME,
    TrustedFixtureError,
    verify_trusted_fixture,
)
from tests.fixture_factory import make_trusted_fixture

BASE_FILES = {
    "README.md": "# fixture\n",
    "calc/__init__.py": "from .core import add\n",
    "calc/core.py": "def add(a, b):\n    return a + b\n",
    "tests/test_core.py": "def test_add():\n    assert True\n",
}


def read_manifest(root: Path) -> dict[str, object]:
    return json.loads((root / FIXTURE_MANIFEST_FILENAME).read_text("utf-8"))


def write_manifest(root: Path, payload: dict[str, object]) -> None:
    (root / FIXTURE_MANIFEST_FILENAME).write_bytes(
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )


def fixture(tmp_path: Path) -> Path:
    return make_trusted_fixture(tmp_path / "fixture", BASE_FILES)


def test_project_trusted_fixture_manifest_is_valid() -> None:
    verified = verify_trusted_fixture(expected_name="trusted_fixture_v1")

    assert verified.name == "trusted_fixture_v1"
    assert verified.version == "1.0.0"
    assert verified.file_count == 4
    assert set(verified.file_hashes) == {
        "README.md",
        "calc/__init__.py",
        "calc/core.py",
        "tests/test_core.py",
    }
    assert FIXTURE_MANIFEST_FILENAME not in verified.file_hashes
    assert len(verified.manifest_sha256) == 64


@pytest.mark.parametrize(
    "relative",
    [
        "README.md",
        "calc/__init__.py",
        "calc/core.py",
        "tests/test_core.py",
        FIXTURE_MANIFEST_FILENAME,
    ],
)
def test_project_fixture_files_keep_lf_line_endings(relative: str) -> None:
    data = (DEFAULT_TRUSTED_FIXTURE_ROOT / relative).read_bytes()

    assert b"\r\n" not in data


def test_valid_temporary_fixture_is_verified(tmp_path: Path) -> None:
    root = fixture(tmp_path)

    verified = verify_trusted_fixture(root, expected_name="trusted_fixture_v1")

    assert verified.root == root.resolve()
    assert verified.file_count == len(BASE_FILES)
    assert all(len(digest) == 64 for digest in verified.file_hashes.values())


def test_wrong_fixture_name_is_rejected(tmp_path: Path) -> None:
    root = fixture(tmp_path)

    with pytest.raises(TrustedFixtureError, match="name"):
        verify_trusted_fixture(root, expected_name="another_fixture")


def test_unapproved_fixture_name_is_rejected_even_with_manifest(
    tmp_path: Path,
) -> None:
    root = make_trusted_fixture(
        tmp_path / "fixture",
        BASE_FILES,
        name="other_fixture",
    )

    with pytest.raises(TrustedFixtureError, match="approved"):
        verify_trusted_fixture(root, expected_name="other_fixture")


def test_invalid_expected_name_is_rejected(tmp_path: Path) -> None:
    root = fixture(tmp_path)

    with pytest.raises(TrustedFixtureError, match="name"):
        verify_trusted_fixture(root, expected_name="../trusted")


def test_modified_file_is_rejected(tmp_path: Path) -> None:
    root = fixture(tmp_path)
    (root / "calc" / "core.py").write_text(
        "def add(a, b):\n    return a - b\n",
        encoding="utf-8",
    )

    with pytest.raises(TrustedFixtureError, match="hash mismatch"):
        verify_trusted_fixture(root, expected_name="trusted_fixture_v1")


def test_extra_file_is_rejected(tmp_path: Path) -> None:
    root = fixture(tmp_path)
    (root / "extra.py").write_text("x = 1\n", encoding="utf-8")

    with pytest.raises(TrustedFixtureError, match="file set"):
        verify_trusted_fixture(root, expected_name="trusted_fixture_v1")


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    root = fixture(tmp_path)
    (root / "calc" / "core.py").unlink()

    with pytest.raises(TrustedFixtureError, match="file set"):
        verify_trusted_fixture(root, expected_name="trusted_fixture_v1")


def test_manifest_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    root = fixture(tmp_path)
    manifest = read_manifest(root)
    files = manifest["files"]
    assert isinstance(files, dict)
    files["calc/core.py"] = "0" * 64
    write_manifest(root, manifest)

    with pytest.raises(TrustedFixtureError, match="hash mismatch"):
        verify_trusted_fixture(root, expected_name="trusted_fixture_v1")


def test_missing_manifest_is_rejected(tmp_path: Path) -> None:
    root = fixture(tmp_path)
    (root / FIXTURE_MANIFEST_FILENAME).unlink()

    with pytest.raises(TrustedFixtureError, match="manifest"):
        verify_trusted_fixture(root, expected_name="trusted_fixture_v1")


def test_invalid_manifest_json_is_rejected(tmp_path: Path) -> None:
    root = fixture(tmp_path)
    (root / FIXTURE_MANIFEST_FILENAME).write_bytes(b"{not-json")

    with pytest.raises(TrustedFixtureError, match="JSON"):
        verify_trusted_fixture(root, expected_name="trusted_fixture_v1")


def test_manifest_unknown_key_is_rejected(tmp_path: Path) -> None:
    root = fixture(tmp_path)
    manifest = read_manifest(root)
    manifest["unexpected"] = True
    write_manifest(root, manifest)

    with pytest.raises(TrustedFixtureError, match="structure"):
        verify_trusted_fixture(root, expected_name="trusted_fixture_v1")


def test_manifest_duplicate_keys_are_rejected(tmp_path: Path) -> None:
    root = fixture(tmp_path)
    (root / FIXTURE_MANIFEST_FILENAME).write_bytes(
        (
            '{"fixture_name": "trusted_fixture_v1", '
            '"fixture_name": "trusted_fixture_v1", '
            '"version": "1.0.0", "files": {"README.md": "'
            + "0" * 64
            + '"}}'
        ).encode("utf-8")
    )

    with pytest.raises(TrustedFixtureError, match="duplicate"):
        verify_trusted_fixture(root, expected_name="trusted_fixture_v1")


@pytest.mark.parametrize(
    "unsafe",
    [
        "../outside.py",
        "/absolute.py",
        "a\\b.py",
        "a:b.py",
        "./README.md",
        ".",
        "calc/../README.md",
    ],
)
def test_unsafe_manifest_path_is_rejected(
    tmp_path: Path,
    unsafe: str,
) -> None:
    root = fixture(tmp_path)
    manifest = read_manifest(root)
    files = manifest["files"]
    assert isinstance(files, dict)
    files[unsafe] = next(iter(files.values()))
    write_manifest(root, manifest)

    with pytest.raises(TrustedFixtureError):
        verify_trusted_fixture(root, expected_name="trusted_fixture_v1")


def test_symlinked_fixture_file_is_rejected(tmp_path: Path) -> None:
    root = fixture(tmp_path)
    link = root / "linked.py"
    try:
        os.symlink(root / "README.md", link)
    except OSError:
        pytest.skip("symbolic links are not permitted on this host")

    with pytest.raises(TrustedFixtureError, match="symbolic link"):
        verify_trusted_fixture(root, expected_name="trusted_fixture_v1")


def test_symlinked_fixture_root_is_rejected(tmp_path: Path) -> None:
    root = fixture(tmp_path)
    link = tmp_path / "fixture_link"
    try:
        os.symlink(root, link, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links are not permitted on this host")

    with pytest.raises(TrustedFixtureError, match="link"):
        verify_trusted_fixture(link, expected_name="trusted_fixture_v1")
