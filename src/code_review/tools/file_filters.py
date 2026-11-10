"""仓库文件过滤与分类规则。

本模块只依据路径、文件名、后缀与二进制探针做确定性判断，不读取或保存
文件内容。规则集中在 :class:`FileFilterPolicy`，可通过构造参数替换以便测试。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath


class FileCategory(StrEnum):
    """进入扫描清单的文件类别。"""

    PYTHON_SOURCE = "python_source"
    PYTHON_TEST = "python_test"
    PROJECT_CONFIG = "project_config"
    DEPENDENCY_MANIFEST = "dependency_manifest"
    DOCUMENTATION = "documentation"
    OTHER_TEXT = "other_text"


class FilterReason(StrEnum):
    """文件被过滤的确定性原因。"""

    SENSITIVE = "sensitive"
    COMPILED_ARTIFACT = "compiled_artifact"
    BINARY = "binary"
    OVERSIZED = "oversized"
    SYMLINK = "symlink"
    PATH_ESCAPE = "path_escape"
    UNSUPPORTED_LANGUAGE = "unsupported_language"
    UNREADABLE = "unreadable"


def _default_excluded_directories() -> frozenset[str]:
    return frozenset(
        {
            ".git",
            "__pycache__",
            ".venv",
            "venv",
            "node_modules",
            ".tox",
            ".nox",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            ".hypothesis",
            ".eggs",
            "build",
            "dist",
        }
    )


def _default_sensitive_filenames() -> frozenset[str]:
    return frozenset(
        {
            ".env",
            ".netrc",
            ".npmrc",
            ".pypirc",
            ".git-credentials",
            ".htpasswd",
            "id_rsa",
            "id_dsa",
            "id_ecdsa",
            "id_ed25519",
            "credentials",
            "credentials.json",
            "secrets",
            "secrets.json",
            "secrets.yaml",
            "secrets.yml",
            "service-account.json",
            "service_account.json",
        }
    )


_DEFAULT_SENSITIVE_STEMS = frozenset(
    {"secrets", "secret", "credentials", "credential", "passwords", "passwd"}
)

_DEFAULT_SENSITIVE_SUFFIXES = frozenset(
    {".env", ".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".ppk", ".gpg", ".asc", ".kdbx"}
)

_DEFAULT_COMPILED_SUFFIXES = frozenset(
    {
        ".pyc",
        ".pyo",
        ".pyd",
        ".so",
        ".dll",
        ".dylib",
        ".o",
        ".obj",
        ".a",
        ".lib",
        ".exe",
        ".class",
        ".jar",
        ".whl",
        ".egg",
    }
)

_DEFAULT_UNSUPPORTED_CODE_SUFFIXES = frozenset(
    {
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".vue",
        ".svelte",
        ".java",
        ".kt",
        ".kts",
        ".go",
        ".rs",
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".cxx",
        ".hpp",
        ".cs",
        ".rb",
        ".php",
        ".swift",
        ".scala",
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".ps1",
        ".bat",
        ".cmd",
        ".sql",
        ".r",
        ".m",
        ".mm",
        ".lua",
        ".pl",
        ".ex",
        ".exs",
        ".dart",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".less",
        ".ipynb",
    }
)

_DEPENDENCY_MANIFESTS = frozenset(
    {
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "pipfile",
        "pipfile.lock",
        "poetry.lock",
        "uv.lock",
        "environment.yml",
        "environment.yaml",
        "conda.yml",
        "conda.yaml",
        "requirements.txt",
        "constraints.txt",
        "tox.ini",
        "package.json",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "go.mod",
        "go.sum",
        "cargo.toml",
        "cargo.lock",
        "gemfile",
        "gemfile.lock",
    }
)

_CONFIG_SUFFIXES = frozenset(
    {".ini", ".cfg", ".toml", ".yaml", ".yml", ".json", ".xml", ".properties", ".conf"}
)

_CONFIG_FILENAMES = frozenset(
    {
        ".editorconfig",
        ".gitignore",
        ".gitattributes",
        ".dockerignore",
        "makefile",
        "dockerfile",
    }
)

_DOCUMENTATION_SUFFIXES = frozenset({".md", ".rst", ".txt", ".adoc"})

_DOCUMENTATION_STEMS = frozenset(
    {"readme", "changelog", "changes", "contributing", "license", "authors", "notice"}
)

_TEST_DIRECTORY_NAMES = frozenset({"test", "tests"})

_PRIVATE_KEY_MARKER = b"PRIVATE KEY-----"


@dataclass(frozen=True)
class FileFilterPolicy:
    """可替换的文件过滤策略。

    默认值偏向安全：无法确认用途的凭据类文件一律排除；只审查 Python 源码，
    其他语言源码记录为 unsupported_language，避免进入后续 LLM 上下文。
    """

    excluded_directories: frozenset[str] = field(
        default_factory=_default_excluded_directories
    )
    excluded_directory_suffixes: tuple[str, ...] = (".egg-info",)
    sensitive_filenames: frozenset[str] = field(
        default_factory=_default_sensitive_filenames
    )
    sensitive_stems: frozenset[str] = _DEFAULT_SENSITIVE_STEMS
    sensitive_prefixes: tuple[str, ...] = (".env.",)
    sensitive_suffixes: frozenset[str] = _DEFAULT_SENSITIVE_SUFFIXES
    compiled_suffixes: frozenset[str] = _DEFAULT_COMPILED_SUFFIXES
    unsupported_code_suffixes: frozenset[str] = _DEFAULT_UNSUPPORTED_CODE_SUFFIXES
    binary_probe_bytes: int = 8192

    def is_excluded_directory(self, name: str) -> bool:
        """目录名是否属于排除目录（大小写不敏感）。"""

        lowered = name.lower()
        if lowered in self.excluded_directories:
            return True
        return any(lowered.endswith(suffix) for suffix in self.excluded_directory_suffixes)

    def is_sensitive_path(self, relative_path: str) -> bool:
        """路径是否属于敏感文件（仅基于名称与后缀）。"""

        name = PurePosixPath(relative_path).name.lower()
        if name in self.sensitive_filenames:
            return True
        if PurePosixPath(name).stem in self.sensitive_stems:
            return True
        if any(name.startswith(prefix) for prefix in self.sensitive_prefixes):
            return True
        return any(name.endswith(suffix) for suffix in self.sensitive_suffixes)

    def is_compiled_artifact(self, name: str) -> bool:
        lowered = name.lower()
        return any(lowered.endswith(suffix) for suffix in self.compiled_suffixes)

    def is_unsupported_code(self, name: str) -> bool:
        lowered = name.lower()
        return any(lowered.endswith(suffix) for suffix in self.unsupported_code_suffixes)

    def contains_private_key_marker(self, probe: bytes) -> bool:
        """二进制探针中是否出现私钥标记（用于发现改名的私钥文件）。"""

        return _PRIVATE_KEY_MARKER in probe


def is_binary_probe(probe: bytes) -> bool:
    """通过 NUL 字节判断二进制内容。"""

    return b"\x00" in probe


def detect_language(relative_path: str) -> str | None:
    """返回受支持的语言标识；v1 只审查 Python。"""

    if PurePosixPath(relative_path).suffix.lower() == ".py":
        return "python"
    return None


def is_python_test_path(relative_path: str) -> bool:
    """判断 Python 文件是否属于测试代码。"""

    path = PurePosixPath(relative_path)
    name = path.name.lower()
    if any(part.lower() in _TEST_DIRECTORY_NAMES for part in path.parts[:-1]):
        return True
    return (
        name == "conftest.py"
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


def is_dependency_manifest(relative_path: str) -> bool:
    path = PurePosixPath(relative_path)
    name = path.name.lower()
    if name in _DEPENDENCY_MANIFESTS:
        return True
    if name.startswith("requirements") and name.endswith(".txt"):
        return True
    return len(path.parts) >= 2 and path.parts[-2].lower() == "requirements" and name.endswith(".txt")


def classify_path(relative_path: str) -> FileCategory | None:
    """对路径分类；返回 ``None`` 表示不进入扫描清单（如其他语言源码）。"""

    path = PurePosixPath(relative_path)
    name = path.name
    lowered = name.lower()

    if is_dependency_manifest(relative_path):
        return FileCategory.DEPENDENCY_MANIFEST

    if lowered.endswith(".py"):
        return (
            FileCategory.PYTHON_TEST
            if is_python_test_path(relative_path)
            else FileCategory.PYTHON_SOURCE
        )

    if path.suffix.lower() in _CONFIG_SUFFIXES or lowered in _CONFIG_FILENAMES:
        return FileCategory.PROJECT_CONFIG

    if (
        path.suffix.lower() in _DOCUMENTATION_SUFFIXES
        or path.stem.lower() in _DOCUMENTATION_STEMS
    ):
        return FileCategory.DOCUMENTATION

    return FileCategory.OTHER_TEXT
