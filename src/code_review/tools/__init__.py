"""阶段 1 确定性工具层。

包含 GitHub URL 安全校验、仓库获取与扫描，以及 Ruff / Bandit / Radon
静态分析工具的统一接口与结果模型。
"""

from .bandit_tool import BanditOutput, BanditTool, parse_bandit_output
from .base import (
    AnalysisTool,
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolFinding,
    ToolInputError,
    ToolOutputParseError,
)
from .file_filters import FileCategory, FileFilterPolicy, FilterReason
from .process_runner import ProcessResult, ProcessStatus, run_process
from .radon_tool import (
    RadonTool,
    parse_radon_cc_output,
    parse_radon_mi_output,
)
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
from .ruff_tool import RuffTool, parse_ruff_output
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
    "AnalysisTool",
    "BanditOutput",
    "BanditTool",
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
    "ProcessResult",
    "ProcessStatus",
    "RadonTool",
    "RepositoryError",
    "RepositoryFile",
    "RepositoryInspectionError",
    "RepositoryInspector",
    "RepositoryInventory",
    "RepositoryManager",
    "RepositorySnapshot",
    "RepositoryStatistics",
    "ResourceLimitExceededError",
    "RuffTool",
    "ToolExecutionResult",
    "ToolExecutionStatus",
    "ToolFinding",
    "ToolInputError",
    "ToolOutputParseError",
    "URLValidationError",
    "is_full_commit_sha",
    "normalize_commit_sha",
    "parse_bandit_output",
    "parse_radon_cc_output",
    "parse_radon_mi_output",
    "parse_ruff_output",
    "run_process",
    "validate_branch_name",
    "validate_github_url",
]
