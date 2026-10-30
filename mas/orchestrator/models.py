"""Data contracts and schemas for central Gemini-powered orchestrator (Phase 10)."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from mas.agents.models import ToolCallRecord


class ExecutionStatus(str, Enum):
    """Execution status for an individual delegated agent step."""

    SUCCESS = "success"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    PARTIAL = "partial"
    SKIPPED = "skipped"


class AgentTarget(str, Enum):
    """Target agent designated to receive a delegated task."""

    RESEARCH_AGENT = "research_agent"
    TASK_AGENT = "task_agent"
    NONE = "none"


class ExecutionMode(str, Enum):
    """Execution mode determined by the orchestrator planning phase."""

    SINGLE = "single"
    INDEPENDENT = "independent"
    SEQUENTIAL = "sequential"
    UNSUPPORTED = "unsupported"


@dataclass
class DelegationTask:
    """A single discrete task delegated to a specific agent."""

    step_id: str
    agent_target: AgentTarget
    prompt: str
    depends_on: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class DelegationPlan:
    """The structured execution plan formulated by the orchestrator."""

    reasoning: str
    mode: ExecutionMode
    tasks: list[DelegationTask] = field(default_factory=list)
    direct_response: str | None = None


@dataclass
class DelegationResult:
    """Result returned from an individual delegated agent execution."""

    step_id: str
    agent_name: str
    prompt: str
    status: ExecutionStatus
    content: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    error: str | None = None
    execution_time_seconds: float = 0.0


@dataclass
class OrchestratorRequest:
    """Incoming user request submitted to the central orchestrator."""

    prompt: str
    user_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class OrchestratorResponse:
    """Final synthesized response produced by the orchestrator."""

    content: str
    plan: DelegationPlan | None = None
    results: list[DelegationResult] = field(default_factory=list)
    is_success: bool = True
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
