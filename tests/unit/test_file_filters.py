"""文件过滤与分类规则的单元测试。"""

from __future__ import annotations

import pytest

from code_review.tools.file_filters import (
    FileCategory,
    FileFilterPolicy,
    classify_path,
    detect_language,
    is_binary_probe,
    is_dependency_manifest,
    is_python_test_path,
)


@pytest.mark.parametrize(
    ("path", "category"),
    [
        ("app.py", FileCategory.PYTHON_SOURCE),
        ("src/pkg/module.py", FileCategory.PYTHON_SOURCE),
        ("src/testing.py", FileCategory.PYTHON_SOURCE),
        ("tests/test_app.py", FileCategory.PYTHON_TEST),
        ("test/unit.py", FileCategory.PYTHON_TEST),
        ("pkg/test_api.py", FileCategory.PYTHON_TEST),
        ("pkg/api_test.py", FileCategory.PYTHON_TEST),
        ("conftest.py", FileCategory.PYTHON_TEST),
        ("requirements.txt", FileCategory.DEPENDENCY_MANIFEST),
        ("requirements-dev.txt", FileCategory.DEPENDENCY_MANIFEST),
        ("requirements/prod.txt", FileCategory.DEPENDENCY_MANIFEST),
        ("pyproject.toml", FileCategory.DEPENDENCY_MANIFEST),
        ("setup.py", FileCategory.DEPENDENCY_MANIFEST),
        ("setup.cfg", FileCategory.DEPENDENCY_MANIFEST),
        ("Pipfile", FileCategory.DEPENDENCY_MANIFEST),
        ("poetry.lock", FileCategory.DEPENDENCY_MANIFEST),
        ("environment.yml", FileCategory.DEPENDENCY_MANIFEST),
        ("package.json", FileCategory.DEPENDENCY_MANIFEST),
        ("go.mod", FileCategory.DEPENDENCY_MANIFEST),
        ("tox.ini", FileCategory.DEPENDENCY_MANIFEST),
        ("mypy.ini", FileCategory.PROJECT_CONFIG),
        ("config.yaml", FileCategory.PROJECT_CONFIG),
        ("data.json", FileCategory.PROJECT_CONFIG),
        (".editorconfig", FileCategory.PROJECT_CONFIG),
        ("Makefile", FileCategory.PROJECT_CONFIG),
        ("README.md", FileCategory.DOCUMENTATION),
        ("README", FileCategory.DOCUMENTATION),
        ("CHANGELOG.rst", FileCategory.DOCUMENTATION),
        ("docs/guide.md", FileCategory.DOCUMENTATION),
        ("LICENSE", FileCategory.DOCUMENTATION),
        ("notes.csv", FileCategory.OTHER_TEXT),
        ("data.bin", FileCategory.OTHER_TEXT),
    ],
)
def test_classify_path(path: str, category: FileCategory) -> None:
    assert classify_path(path) == category


@pytest.mark.parametrize(
    "path",
    ["tests/test_app.py", "test/unit.py", "pkg/test_api.py", "pkg/api_test.py", "conftest.py"],
)
def test_python_test_detection(path: str) -> None:
    assert is_python_test_path(path) is True


@pytest.mark.parametrize("path", ["app.py", "src/testing.py", "src/latest.py", "tests_data/app.py"])
def test_non_test_python_paths(path: str) -> None:
    assert is_python_test_path(path) is False


@pytest.mark.parametrize(
    "path",
    ["requirements.txt", "requirements/runtime.txt", "pyproject.toml", "Pipfile.lock"],
)
def test_dependency_manifest_detection(path: str) -> None:
    assert is_dependency_manifest(path) is True


def test_detect_language_only_supports_python() -> None:
    assert detect_language("pkg/module.py") == "python"
    assert detect_language("README.md") is None
    assert detect_language("web/app.js") is None


@pytest.mark.parametrize(
    "name",
    [
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".pytest_cache",
        "demo.egg-info",
        "build",
        "dist",
    ],
)
def test_excluded_directories(name: str) -> None:
    assert FileFilterPolicy().is_excluded_directory(name) is True


@pytest.mark.parametrize("name", ["src", "venv2", "my_node_modules", "docs"])
def test_regular_directories_are_kept(name: str) -> None:
    assert FileFilterPolicy().is_excluded_directory(name) is False


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        ".env.example",
        "id_rsa",
        "config/server.pem",
        "config/server.key",
        "credentials.json",
        "secrets.yaml",
        "src/secrets.py",
        "pkg/credentials.py",
        "service-account.json",
        "backup.kdbx",
    ],
)
def test_sensitive_paths(path: str) -> None:
    assert FileFilterPolicy().is_sensitive_path(path) is True


@pytest.mark.parametrize(
    "path",
    ["environment.py", "tokenizer.py", "settings.py", "README.md", "src/latest.py"],
)
def test_normal_paths_are_not_sensitive(path: str) -> None:
    assert FileFilterPolicy().is_sensitive_path(path) is False


@pytest.mark.parametrize("name", ["module.pyc", "lib.so", "app.exe", "package.whl"])
def test_compiled_artifacts(name: str) -> None:
    assert FileFilterPolicy().is_compiled_artifact(name) is True


def test_python_source_is_not_compiled_artifact() -> None:
    assert FileFilterPolicy().is_compiled_artifact("module.py") is False


@pytest.mark.parametrize("name", ["app.js", "main.go", "script.sh", "page.html", "notebook.ipynb"])
def test_unsupported_code_suffixes(name: str) -> None:
    assert FileFilterPolicy().is_unsupported_code(name) is True


def test_python_and_config_are_supported() -> None:
    policy = FileFilterPolicy()
    assert policy.is_unsupported_code("module.py") is False
    assert policy.is_unsupported_code("pyproject.toml") is False


def test_binary_probe() -> None:
    assert is_binary_probe(b"\x00\x01\x02") is True
    assert is_binary_probe(b"plain text") is False
    assert is_binary_probe(b"") is False


def test_private_key_marker() -> None:
    policy = FileFilterPolicy()
    assert policy.contains_private_key_marker(b"-----BEGIN RSA PRIVATE KEY-----") is True
    assert policy.contains_private_key_marker(b"-----BEGIN OPENSSH PRIVATE KEY-----") is True
    assert policy.contains_private_key_marker(b"public certificate") is False


def test_custom_policy_overrides_defaults() -> None:
    policy = FileFilterPolicy(
        excluded_directories=frozenset({"custom_dir"}),
        sensitive_filenames=frozenset({"secret.txt"}),
    )

    assert policy.is_excluded_directory("custom_dir") is True
    assert policy.is_excluded_directory("node_modules") is False
    assert policy.is_sensitive_path("secret.txt") is True
    assert policy.is_sensitive_path("id_rsa") is False
