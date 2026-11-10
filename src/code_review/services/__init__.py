"""阶段 1 服务层：Finding 聚合、证据校验与 LLM 辅助分析。"""

from .evidence_validator import (
    CodeEvidenceValidator,
    EvidenceValidation,
    EvidenceValidationConfigurationError,
)
from .finding_aggregator import (
    AggregationResult,
    AggregationStats,
    ToolAggregateSummary,
    aggregate_review_results,
    deduplicate_findings,
)
from .llm_analyzer import (
    LLMAcceptedProposal,
    LLMAnalysisResult,
    LLMAnalysisStatus,
    LLMAnalyzer,
    LLMExplanation,
    LLMRejectedProposal,
)
from .llm_client import (
    LLMClient,
    LLMClientError,
    LLMCompletion,
    OpenAICompatibleClient,
)
from .redaction import REDACTED, redact_sensitive_text

__all__ = [
    "REDACTED",
    "AggregationResult",
    "AggregationStats",
    "CodeEvidenceValidator",
    "EvidenceValidation",
    "EvidenceValidationConfigurationError",
    "LLMAcceptedProposal",
    "LLMAnalysisResult",
    "LLMAnalysisStatus",
    "LLMAnalyzer",
    "LLMClient",
    "LLMClientError",
    "LLMCompletion",
    "LLMExplanation",
    "LLMRejectedProposal",
    "OpenAICompatibleClient",
    "ToolAggregateSummary",
    "aggregate_review_results",
    "deduplicate_findings",
    "redact_sensitive_text",
]
