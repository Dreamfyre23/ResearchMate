"""ResearchMate Client-Side MCP package.

Provides client-side host and connection management for interacting with the MCP server
over Streamable HTTP (DEC-004, DEC-005, DEC-006, DEC-024).
"""

from client_mcp.clients.mcp_client import MCPClient
from client_mcp.config import MCPClientSettings, get_client_settings
from client_mcp.exceptions import (
    MCPClientError,
    MCPConnectionError,
    MCPProtocolError,
    MCPResourceError,
    MCPTimeoutError,
    MCPToolError,
)
from client_mcp.host import MCPHost
from client_mcp.models import (
    ResourceDescriptor,
    ResourceReadResult,
    ToolDescriptor,
    ToolExecutionResult,
)

__all__ = [
    "MCPClient",
    "MCPClientError",
    "MCPClientSettings",
    "MCPConnectionError",
    "MCPHost",
    "MCPProtocolError",
    "MCPResourceError",
    "MCPTimeoutError",
    "MCPToolError",
    "ResourceDescriptor",
    "ResourceReadResult",
    "ToolDescriptor",
    "ToolExecutionResult",
    "get_client_settings",
]
