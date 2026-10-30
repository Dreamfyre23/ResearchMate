"""Exceptions for the ResearchMate client-side MCP host."""


class MCPClientError(Exception):
    """Base exception for all MCP client errors."""


class MCPConnectionError(MCPClientError):
    """Raised when connection to the MCP server fails, is refused, or is lost."""


class MCPTimeoutError(MCPClientError):
    """Raised when an MCP operation or connection attempt times out."""


class MCPProtocolError(MCPClientError):
    """Raised when an MCP protocol violation or unexpected response occurs."""


class MCPToolError(MCPClientError):
    """Raised when an MCP tool invocation fails or an unknown tool is requested."""


class MCPResourceError(MCPClientError):
    """Raised when an MCP resource read fails or an unknown resource is requested."""
