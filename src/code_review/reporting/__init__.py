"""Stage 1 与 Stage 2 报告产物层。

Stage 1 的模型、生成器与 Markdown 渲染器保持冻结；Stage 2 新增五件产物
模型与生成器，不改变 Stage 1 的四件产物行为。
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
from .stage2_models import (
    Stage2MetadataArtifact,
    Stage2StaticAnalysisArtifact,
    Stage2TestReportArtifact,
)
from .stage2_report_generator import (
    Stage2ArtifactInput,
    Stage2ReportArtifacts,
    Stage2ReportGenerationError,
    Stage2ReportGenerator,
    Stage2ReportOutputError,
    render_stage2_markdown,
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
    "Stage2ArtifactInput",
    "Stage2MetadataArtifact",
    "Stage2ReportArtifacts",
    "Stage2ReportGenerationError",
    "Stage2ReportGenerator",
    "Stage2ReportOutputError",
    "Stage2StaticAnalysisArtifact",
    "Stage2TestReportArtifact",
    "StaticAnalysisArtifact",
    "StaticAnalysisStatisticsArtifact",
    "TestCountsArtifact",
    "TestRecordArtifact",
    "TestReferenceArtifact",
    "TestReferenceEntryArtifact",
    "TestReportArtifact",
    "ToolRunArtifact",
    "render_markdown",
    "render_stage2_markdown",
]
