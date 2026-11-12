"""Stage 2 Agent 基础设施。

具体 Security/Quality/Performance/Testing Agent 在 Stage 2.2 实现。
"""

from code_review.agents.base import AgentContractError, BaseAgent
from code_review.agents.contracts import (
    AgentExecution,
    AgentRunOutput,
    ArtifactData,
    ArtifactPointerError,
    ContractValidationError,
    LLMClientProtocol,
    UsageSummary,
    WorkerDispatch,
    WorkerEvidence,
    WorkerRuntime,
    WorkerTiming,
)
from code_review.agents.llm_support import (
    JsonCompletion,
    LLMProjectionError,
    LLMResponseError,
    LLMUsageError,
    PromptProjection,
    UsageAccumulator,
    build_prompt_projection,
    build_user_prompt,
    load_agent_prompt,
    parse_json_object,
    request_json,
    validate_json_fields,
)

__all__ = [
    "AgentContractError",
    "AgentExecution",
    "AgentRunOutput",
    "ArtifactData",
    "ArtifactPointerError",
    "BaseAgent",
    "ContractValidationError",
    "JsonCompletion",
    "LLMClientProtocol",
    "LLMProjectionError",
    "LLMResponseError",
    "LLMUsageError",
    "PromptProjection",
    "UsageAccumulator",
    "UsageSummary",
    "WorkerDispatch",
    "WorkerEvidence",
    "WorkerRuntime",
    "WorkerTiming",
    "build_prompt_projection",
    "build_user_prompt",
    "load_agent_prompt",
    "parse_json_object",
    "request_json",
    "validate_json_fields",
]
