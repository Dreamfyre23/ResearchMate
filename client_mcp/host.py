"""Client-side MCP host for ResearchMate.

Provides the high-level host abstraction used by the Multi-Agent System (MAS)
to discover tools and resources, execute tools, read resources, and manage connection
lifecycles over Streamable HTTP (DEC-004, DEC-005, DEC-006, DEC-024).

Can also be executed independently via:
    python -m client_mcp
or:
    python client_mcp/host.py
"""

import asyncio
import json
import logging
import sys
from types import TracebackType
from typing import Any, Self

from client_mcp.clients.mcp_client import MCPClient
from client_mcp.config import MCPClientSettings, get_client_settings
from client_mcp.exceptions import (
    MCPClientError,
    MCPConnectionError,
    MCPResourceError,
    MCPTimeoutError,
)
from client_mcp.models import (
    ResourceDescriptor,
    ResourceReadResult,
    ToolDescriptor,
    ToolExecutionResult,
)

logger = logging.getLogger(__name__)


class MCPHost:
    """High-level MCP host abstraction for the Multi-Agent System."""

    def __init__(
        self,
        settings: MCPClientSettings | None = None,
        client: MCPClient | None = None,
    ) -> None:
        self._settings = settings or get_client_settings()
        self._client = client or MCPClient(settings=self._settings)
        self._tool_cache: dict[str, ToolDescriptor] = {}
        self._resource_cache: dict[str, ResourceDescriptor] = {}

    @property
    def settings(self) -> MCPClientSettings:
        """Return the active client configuration settings."""
        return self._settings

    @property
    def client(self) -> MCPClient:
        """Return the underlying MCPClient instance."""
        return self._client

    @property
    def is_connected(self) -> bool:
        """Return True if the underlying client is connected to the server."""
        return self._client.is_connected

    async def connect(self) -> None:
        """Connect to the configured MCP server."""
        await self._client.connect()

    async def disconnect(self) -> None:
        """Disconnect from the MCP server and clear cached state."""
        await self._client.disconnect()
        self._tool_cache.clear()
        self._resource_cache.clear()

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.disconnect()

    async def discover_tools(self, refresh: bool = False) -> list[ToolDescriptor]:
        """Discover available tools from the server and update local cache.

        Args:
            refresh: If True, forces re-fetching from the server even if cached.

        Returns:
            List of ToolDescriptor objects discovered dynamically from the server.
        """
        if self._tool_cache and not refresh:
            return list(self._tool_cache.values())

        tools = await self._client.list_tools()
        self._tool_cache = {tool.name: tool for tool in tools}
        logger.debug("Discovered %d tools from MCP server", len(tools))
        return tools

    async def discover_resources(
        self, refresh: bool = False
    ) -> list[ResourceDescriptor]:
        """Discover available resources from the server and update local cache.

        Args:
            refresh: If True, forces re-fetching from the server even if cached.

        Returns:
            List of ResourceDescriptor objects discovered dynamically from the server.
        """
        if self._resource_cache and not refresh:
            return list(self._resource_cache.values())

        resources = await self._client.list_resources()
        self._resource_cache = {resource.uri: resource for resource in resources}
        logger.debug("Discovered %d resources from MCP server", len(resources))
        return resources

    async def get_tool(self, name: str) -> ToolDescriptor | None:
        """Retrieve a specific tool descriptor by name, discovering tools if not yet cached."""
        if not self._tool_cache:
            await self.discover_tools()
        return self._tool_cache.get(name)

    async def get_resource(self, uri: str) -> ResourceDescriptor | None:
        """Retrieve a specific resource descriptor by URI, discovering resources if not yet cached."""
        if not self._resource_cache:
            await self.discover_resources()
        return self._resource_cache.get(uri)

    async def invoke_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        raise_on_error: bool = False,
    ) -> ToolExecutionResult:
        """Invoke an MCP tool by name with arguments.

        Args:
            name: Registered tool name.
            arguments: Dictionary of arguments conforming to tool schema.
            raise_on_error: If True, raises MCPToolError when tool signals failure.

        Returns:
            ToolExecutionResult containing structured data or error message.
        """
        return await self._client.call_tool(
            name=name, arguments=arguments, raise_on_error=raise_on_error
        )

    async def read_resource(self, uri: str) -> ResourceReadResult:
        """Read a registered MCP resource by its URI.

        Args:
            uri: Standard URI of the resource.

        Returns:
            ResourceReadResult containing parsed content and mime type.
        """
        return await self._client.read_resource(uri=uri)

    async def run_diagnostics(self) -> dict[str, Any]:
        """Perform a quick diagnostic health check through the client session."""
        tools = await self.discover_tools(refresh=True)
        resources = await self.discover_resources(refresh=True)
        server_info = self._client.server_info

        return {
            "server_url": self._settings.server_url,
            "connected": self.is_connected,
            "server_info": getattr(
                server_info, "model_dump", lambda: str(server_info)
            )()
            if server_info
            else None,
            "tool_count": len(tools),
            "resource_count": len(resources),
            "tools": [t.name for t in tools],
            "resources": [r.uri for r in resources],
        }


async def run_standalone_demo() -> int:
    """Execute independent CLI demonstration for Phase 8.

    Flow:
    1. Load client configuration.
    2. Connect to the MCP server.
    3. Discover and display available tools and resources.
    4. Demonstrate at least one tool invocation and one resource read.
    5. Disconnect cleanly.
    """
    settings = get_client_settings()

    print("=" * 70)
    print(" ResearchMate — Client-Side MCP Host (Independent Execution)")
    print("=" * 70)
    print(f"Server Target URL : {settings.server_url}")
    print(f"Request Timeout   : {settings.timeout_seconds}s")
    print(f"Max Retries       : {settings.max_retries}")
    print("-" * 70)

    host = MCPHost(settings=settings)

    try:
        print("[1/5] Connecting to MCP Server...")
        await host.connect()
        print(f"      Connected successfully to {settings.server_url}!")

        print("\n[2/5] Discovering Capabilities dynamically...")
        tools = await host.discover_tools()
        resources = await host.discover_resources()

        print(f"      Discovered {len(tools)} registered tools:")
        for tool in tools:
            desc = (
                tool.description.split("\n")[0]
                if tool.description
                else "No description"
            )
            print(f"        - {tool.name:<25} : {desc}")

        print(f"\n      Discovered {len(resources)} registered resources:")
        for res in resources:
            desc = (
                res.description.split("\n")[0] if res.description else "No description"
            )
            print(f"        - {res.uri:<35} : {desc}")

        print("\n[3/5] Demonstrating Tool Invocation (calling 'list_files')...")
        files_res = await host.invoke_tool("list_files", {"directory": "documents"})
        if files_res.is_error:
            print(f"      [WARN] Tool invocation returned error: {files_res.data}")
        else:
            print("      Tool Invocation Succeeded:")
            print(f"      Result: {json.dumps(files_res.data, indent=2)}")

        print("\n[4/5] Demonstrating Resource Read (reading 'system://server-info')...")
        try:
            res_data = await host.read_resource("system://server-info")
            print("      Resource Read Succeeded:")
            print(f"      MIME Type: {res_data.mime_type}")
            print(f"      Content:   {json.dumps(res_data.data, indent=2)}")
        except MCPResourceError as exc:
            print(f"      [WARN] Could not read resource: {exc}")

        print("\n[5/5] Disconnecting cleanly...")
        await host.disconnect()
        print("      Disconnected cleanly. Transport and streams closed.")
        print("=" * 70)
        print(" Demonstration completed successfully.")
        print("=" * 70)
        return 0

    except (MCPConnectionError, MCPTimeoutError) as exc:
        print(f"\n[ERROR] Connection failed: {exc}", file=sys.stderr)
        print(
            "\nPlease verify that the ResearchMate MCP server is running at the configured URL.",
            file=sys.stderr,
        )
        print("Start the server using:", file=sys.stderr)
        print("    python -m server_mcp.server", file=sys.stderr)
        return 1
    except MCPClientError as exc:
        print(f"\n[ERROR] MCP Client error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"\n[ERROR] Unexpected error: {exc}", file=sys.stderr)
        return 1
    finally:
        if host.is_connected:
            await host.disconnect()


if __name__ == "__main__":
    sys.exit(asyncio.run(run_standalone_demo()))
