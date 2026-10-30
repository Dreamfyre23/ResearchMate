"""Data models for Multi-Agent System (MAS) request and response interactions."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentRequest:
    """Request payload sent to an AI agent."""

    prompt: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallRecord:
    """Audit record of a single tool invocation performed by an agent."""

    tool_name: str
    arguments: dict[str, Any]
    result: Any
    is_error: bool = False


@dataclass
class AgentResponse:
    """Structured response produced by an AI agent upon completing execution."""

    agent_name: str
    content: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    iterations: int = 0
    is_success: bool = True
    error: str | None = None
