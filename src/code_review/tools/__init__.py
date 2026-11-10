"""阶段 1 确定性工具层。

当前包含 GitHub URL 安全校验与仓库获取；静态分析工具在后续子阶段加入。
"""

from .file_filters import FileCategory, FileFilterPolicy, FilterReason
from .repository_inspector import (
    TOTAL_SCAN_LIMIT_REASON,
    FilteredFile,
    RepositoryFile,
    RepositoryInspectionError,
    RepositoryInspector,
    RepositoryInventory,
    RepositoryStatistics,
)
from .repository_manager import (
    CloneError,
    CommitResolutionError,
    GitClient,
    GitNotFoundError,
    GitTimeoutError,
    RepositoryError,
    RepositoryManager,
    RepositorySnapshot,
    ResourceLimitExceededError,
)
from .url_validator import (
    GitHubRepository,
    URLValidationError,
    is_full_commit_sha,
    normalize_commit_sha,
    validate_branch_name,
    validate_github_url,
)

__all__ = [
    "TOTAL_SCAN_LIMIT_REASON",
    "CloneError",
    "CommitResolutionError",
    "FileCategory",
    "FileFilterPolicy",
    "FilterReason",
    "FilteredFile",
    "GitClient",
    "GitHubRepository",
    "GitNotFoundError",
    "GitTimeoutError",
    "RepositoryError",
    "RepositoryFile",
    "RepositoryInspectionError",
    "RepositoryInspector",
    "RepositoryInventory",
    "RepositoryManager",
    "RepositorySnapshot",
    "RepositoryStatistics",
    "ResourceLimitExceededError",
    "URLValidationError",
    "is_full_commit_sha",
    "normalize_commit_sha",
    "validate_branch_name",
    "validate_github_url",
]
