"""阶段 1 确定性工具层。

包含 GitHub URL 安全校验、仓库获取与扫描、Ruff / Bandit / Radon 静态分析，
以及可信 Fixture 的受限 Pytest / Coverage.py 执行与只读校验。
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
from .test_runner import (
    CoverageFileReport,
    CoverageReport,
    PytestReport,
    TestExecutionResult,
    TestExecutionStatus,
    TestRecord,
    TestReportParseError,
    TestRunner,
    parse_coverage_json,
    parse_junit_xml,
)
from .trusted_fixture import (
    APPROVED_TRUSTED_FIXTURE_NAMES,
    DEFAULT_TRUSTED_FIXTURE_ROOT,
    FIXTURE_MANIFEST_FILENAME,
    TrustedFixture,
    TrustedFixtureError,
    verify_trusted_fixture,
)
from .url_validator import (
    GitHubRepository,
    URLValidationError,
    is_full_commit_sha,
    normalize_commit_sha,
    validate_branch_name,
    validate_github_url,
)
from .workspace_snapshot import (
    SnapshotDiff,
    WorkspaceSnapshot,
    WorkspaceSnapshotError,
    compare_snapshots,
    snapshot_workspace,
)

__all__ = [
    "APPROVED_TRUSTED_FIXTURE_NAMES",
    "DEFAULT_TRUSTED_FIXTURE_ROOT",
    "FIXTURE_MANIFEST_FILENAME",
    "TOTAL_SCAN_LIMIT_REASON",
    "AnalysisTool",
    "BanditOutput",
    "BanditTool",
    "CloneError",
    "CommitResolutionError",
    "CoverageFileReport",
    "CoverageReport",
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
    "PytestReport",
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
    "SnapshotDiff",
    "TestExecutionResult",
    "TestExecutionStatus",
    "TestRecord",
    "TestReportParseError",
    "TestRunner",
    "ToolExecutionResult",
    "ToolExecutionStatus",
    "ToolFinding",
    "ToolInputError",
    "ToolOutputParseError",
    "TrustedFixture",
    "TrustedFixtureError",
    "URLValidationError",
    "WorkspaceSnapshot",
    "WorkspaceSnapshotError",
    "compare_snapshots",
    "is_full_commit_sha",
    "normalize_commit_sha",
    "parse_bandit_output",
    "parse_coverage_json",
    "parse_junit_xml",
    "parse_radon_cc_output",
    "parse_radon_mi_output",
    "parse_ruff_output",
    "run_process",
    "snapshot_workspace",
    "validate_branch_name",
    "validate_github_url",
    "verify_trusted_fixture",
]
