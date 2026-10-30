"""Data models for client-side MCP host operations.

Provides structured, predictable data models for tool descriptors, resource
descriptors, tool execution results, and resource read results.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolDescriptor:
    """Descriptor for an available MCP tool discovered dynamically from the server."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResourceDescriptor:
    """Descriptor for an available MCP resource discovered dynamically from the server."""

    uri: str
    name: str
    description: str
    mime_type: str = "application/json"


@dataclass
class ToolExecutionResult:
    """Result of an MCP tool invocation."""

    tool_name: str
    is_error: bool
    data: Any
    raw_text: str | None = None


@dataclass
class ResourceReadResult:
    """Result of reading an MCP resource."""

    uri: str
    mime_type: str
    data: Any
    raw_text: str | None = None
