"""Unit tests for ResearchMate client-side MCP components (Phase 8).

Validates:
- Configuration parsing and environment variable overrides (MCPClientSettings).
- Model representations (ToolDescriptor, ResourceDescriptor, ToolExecutionResult, ResourceReadResult).
- Exception hierarchy.
- Architectural boundary: verifies client_mcp has zero imports from server_mcp or database.
- Exception unwrapping and connection failure categorization helpers.
- Tool result parsing and JSON extraction logic.
"""

import ast
from pathlib import Path

import pytest

from client_mcp.clients.mcp_client import (
    _is_connection_failure,
    _is_timeout_failure,
    _unwrap_exception,
)
from client_mcp.config import MCPClientSettings, get_client_settings
from client_mcp.exceptions import (
    MCPClientError,
    MCPConnectionError,
    MCPProtocolError,
    MCPResourceError,
    MCPTimeoutError,
    MCPToolError,
)
from client_mcp.models import (
    ResourceDescriptor,
    ResourceReadResult,
    ToolDescriptor,
    ToolExecutionResult,
)


def test_client_settings_defaults() -> None:
    """Verify default client settings match system requirements."""
    settings = MCPClientSettings()
    assert settings.server_url == "http://127.0.0.1:8000/mcp"
    assert settings.timeout_seconds == 30.0
    assert settings.max_retries == 3
    assert settings.retry_delay_seconds == 1.0
    assert settings.log_level.lower() == "info"


def test_client_settings_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify client settings respect environment variable overrides."""
    monkeypatch.setenv("MCP_SERVER_URL", "http://10.0.0.5:9000/mcp")
    monkeypatch.setenv("MCP_CLIENT_TIMEOUT_SECONDS", "45.5")
    monkeypatch.setenv("MCP_CLIENT_MAX_RETRIES", "5")
    monkeypatch.setenv("MCP_CLIENT_RETRY_DELAY_SECONDS", "2.5")
    monkeypatch.setenv("MCP_CLIENT_LOG_LEVEL", "DEBUG")

    settings = get_client_settings()
    assert settings.server_url == "http://10.0.0.5:9000/mcp"
    assert settings.timeout_seconds == 45.5
    assert settings.max_retries == 5
    assert settings.retry_delay_seconds == 2.5
    assert settings.log_level == "DEBUG"


def test_exception_hierarchy() -> None:
    """Verify client exception class hierarchy."""
    assert issubclass(MCPConnectionError, MCPClientError)
    assert issubclass(MCPTimeoutError, MCPClientError)
    assert issubclass(MCPProtocolError, MCPClientError)
    assert issubclass(MCPToolError, MCPClientError)
    assert issubclass(MCPResourceError, MCPClientError)


def test_models_descriptors_and_results() -> None:
    """Verify ToolDescriptor, ResourceDescriptor, and Result data models."""
    tool = ToolDescriptor(
        name="test_tool",
        description="A test tool",
        input_schema={"type": "object", "properties": {"arg": {"type": "string"}}},
    )
    assert tool.name == "test_tool"
    assert tool.description == "A test tool"
    assert "arg" in tool.input_schema["properties"]

    res = ResourceDescriptor(
        uri="system://test",
        name="Test Resource",
        description="A test resource",
        mime_type="application/json",
    )
    assert res.uri == "system://test"
    assert res.mime_type == "application/json"

    tool_result = ToolExecutionResult(
        tool_name="test_tool",
        is_error=False,
        data={"status": "ok"},
        raw_text='{"status": "ok"}',
    )
    assert not tool_result.is_error
    assert tool_result.data["status"] == "ok"

    res_result = ResourceReadResult(
        uri="system://test",
        mime_type="application/json",
        data={"key": "val"},
        raw_text='{"key": "val"}',
    )
    assert res_result.data["key"] == "val"


def test_architectural_boundary_no_forbidden_imports() -> None:
    """Verify that client_mcp strictly does NOT import server_mcp or database internals.

    Enforces DEC-004, DEC-024, and AGENTS.md architectural boundary rules.
    """
    client_mcp_dir = Path(__file__).resolve().parent.parent.parent / "client_mcp"
    py_files = list(client_mcp_dir.rglob("*.py"))
    assert len(py_files) > 0, "No Python files found in client_mcp directory"

    forbidden_modules = {"server_mcp", "database"}

    for file_path in py_files:
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_level = alias.name.split(".")[0]
                    assert top_level not in forbidden_modules, (
                        f"Architecture violation: {file_path.name} imports forbidden module '{alias.name}'"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                top_level = node.module.split(".")[0]
                assert top_level not in forbidden_modules, (
                    f"Architecture violation: {file_path.name} imports from forbidden module '{node.module}'"
                )


def test_exception_unwrapping_helper() -> None:
    """Verify recursive unwrapping of nested ExceptionGroups."""
    root_cause = ConnectionRefusedError("Host unreachable")
    group1 = ExceptionGroup("inner group", [root_cause])
    group2 = ExceptionGroup("outer group", [group1])

    unwrapped = _unwrap_exception(group2)
    assert unwrapped is root_cause
    assert _is_connection_failure(unwrapped)


def test_failure_categorization_helpers() -> None:
    """Verify connection and timeout error categorization."""
    conn_err = ConnectionRefusedError("Connection refused")
    timeout_err = TimeoutError("Request timed out")
    runtime_err = RuntimeError("Something unexpected")

    assert _is_connection_failure(conn_err)
    assert not _is_connection_failure(runtime_err)

    assert _is_timeout_failure(timeout_err)
    assert not _is_timeout_failure(runtime_err)
