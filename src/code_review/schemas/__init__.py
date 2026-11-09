"""统一数据合同（docs/task_contracts.md）。

模块依赖方向固定为：task.py ← result.py ← report.py。
"""

from .report import (
    CostSummary,
    DimensionScore,
    ExecutionSummary,
    ReviewReport,
    TestSummary,
)
from .result import AgentResult, Finding, ToolEvidence
from .task import (
    AgentTask,
    ErrorInfo,
    TaskPriority,
    TaskStatus,
    is_transition_allowed,
    utc_now,
)

__all__ = [
    "AgentResult",
    "AgentTask",
    "CostSummary",
    "DimensionScore",
    "ErrorInfo",
    "ExecutionSummary",
    "Finding",
    "ReviewReport",
    "TaskPriority",
    "TaskStatus",
    "TestSummary",
    "ToolEvidence",
    "is_transition_allowed",
    "utc_now",
]
