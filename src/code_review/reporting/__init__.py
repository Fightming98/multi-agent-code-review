"""阶段 1 报告产物层。

本包只定义阶段 1 专用的产物模型、产物生成器与 Markdown 渲染器，不构造
阶段 0 的 ``ReviewReport``，也不生成 ``report.json``。
"""

from .artifact_models import (
    ARTIFACT_SCHEMA_VERSION,
    CoverageArtifact,
    CoverageFileArtifact,
    ErrorSummaryArtifact,
    ExecutionEnvironmentArtifact,
    FixtureArtifact,
    InventorySummaryArtifact,
    LLMAcceptedProposalArtifact,
    LLMAnalysisArtifact,
    LLMExplanationArtifact,
    LLMRejectedProposalArtifact,
    MetadataArtifact,
    RawToolFindingArtifact,
    StaticAnalysisArtifact,
    StaticAnalysisStatisticsArtifact,
    TestCountsArtifact,
    TestRecordArtifact,
    TestReferenceArtifact,
    TestReferenceEntryArtifact,
    TestReportArtifact,
    ToolRunArtifact,
)
from .markdown_renderer import render_markdown
from .report_generator import (
    InventorySummary,
    ReportArtifacts,
    ReportGenerationError,
    ReportGenerator,
    ReportOutputError,
    ReviewArtifactInput,
)

__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "CoverageArtifact",
    "CoverageFileArtifact",
    "ErrorSummaryArtifact",
    "ExecutionEnvironmentArtifact",
    "FixtureArtifact",
    "InventorySummary",
    "InventorySummaryArtifact",
    "LLMAcceptedProposalArtifact",
    "LLMAnalysisArtifact",
    "LLMExplanationArtifact",
    "LLMRejectedProposalArtifact",
    "MetadataArtifact",
    "RawToolFindingArtifact",
    "ReportArtifacts",
    "ReportGenerationError",
    "ReportGenerator",
    "ReportOutputError",
    "ReviewArtifactInput",
    "StaticAnalysisArtifact",
    "StaticAnalysisStatisticsArtifact",
    "TestCountsArtifact",
    "TestRecordArtifact",
    "TestReferenceArtifact",
    "TestReferenceEntryArtifact",
    "TestReportArtifact",
    "ToolRunArtifact",
    "render_markdown",
]
