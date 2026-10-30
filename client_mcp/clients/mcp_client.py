"""Low-level MCP Client connection and protocol manager.

Manages connection lifecycle, Streamable HTTP streams, dynamic capability discovery,
tool invocations, and resource readings using the official Python MCP SDK (DEC-005, DEC-006, DEC-024).
"""

import asyncio
import contextlib
import json
import logging
from types import TracebackType
from typing import Any, Self

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

from client_mcp.config import MCPClientSettings, get_client_settings
from client_mcp.exceptions import (
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

logger = logging.getLogger(__name__)


def _unwrap_exception(exc: BaseException) -> BaseException:
    """Unwrap ExceptionGroup or nested wrappers down to the root cause."""
    if isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        return _unwrap_exception(exc.exceptions[0])
    return exc


def _is_connection_failure(exc: BaseException) -> bool:
    """Determine whether an exception represents a network connectivity or refusal failure."""
    root = _unwrap_exception(exc)
    name = type(root).__name__.lower()
    if isinstance(root, (OSError, ConnectionError)):
        return True
    return any(
        term in name
        for term in (
            "connecterror",
            "connecttimeout",
            "connectionrefused",
            "remotedisconnected",
            "all connection attempts failed",
        )
    )


def _is_timeout_failure(exc: BaseException) -> bool:
    """Determine whether an exception represents a timeout condition."""
    root = _unwrap_exception(exc)
    name = type(root).__name__.lower()
    if isinstance(root, (TimeoutError, asyncio.TimeoutError)):
        return True
    return "timeout" in name


class MCPClient:
    """Low-level client managing an MCP connection session over Streamable HTTP."""

    def __init__(
        self,
        settings: MCPClientSettings | None = None,
        server_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._settings = settings or get_client_settings()
        self._url = server_url or self._settings.server_url
        self._timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else self._settings.timeout_seconds
        )
        self._max_retries = self._settings.max_retries
        self._retry_delay = self._settings.retry_delay_seconds

        self._exit_stack: contextlib.AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._is_connected: bool = False

    @property
    def is_connected(self) -> bool:
        """Return True if the client session is actively connected and initialized."""
        return self._is_connected and self._session is not None

    @property
    def server_url(self) -> str:
        """Return the target server URL."""
        return self._url

    @property
    def server_info(self) -> Any:
        """Return server information reported during initialization handshake."""
        return self._session.server_info if self._session else None

    @property
    def server_capabilities(self) -> Any:
        """Return server capabilities reported during initialization handshake."""
        return self._session.server_capabilities if self._session else None

    async def connect(self) -> None:
        """Establish Streamable HTTP connection and perform MCP initialization handshake.

        Idempotent: does nothing if already connected.
        Retries transient connection errors up to max_retries.
        """
        if self.is_connected:
            return

        last_error: BaseException | None = None

        for attempt in range(1 + self._max_retries):
            stack = contextlib.AsyncExitStack()
            try:
                http_client = httpx.AsyncClient(timeout=self._timeout)
                await stack.enter_async_context(http_client)

                streams = await stack.enter_async_context(
                    streamable_http_client(self._url, http_client=http_client)
                )
                read_stream, write_stream = streams

                session = await stack.enter_async_context(
                    ClientSession(read_stream, write_stream)
                )
                await session.initialize()

                self._exit_stack = stack
                self._session = session
                self._is_connected = True
                logger.info(
                    "Successfully connected and initialized MCP session with %s",
                    self._url,
                )
                return

            except BaseException as orig_exc:
                exc = orig_exc
                try:
                    await stack.aclose()
                except BaseException as close_exc:  # noqa: BLE001
                    # Closing task groups in streamable_http_client re-raises the true root cause
                    exc = close_exc

                last_error = exc
                root = _unwrap_exception(exc)

                # Do not retry on programming errors or obvious client mistakes
                if not (_is_connection_failure(root) or _is_timeout_failure(root)):
                    if isinstance(root, MCPError):
                        raise MCPProtocolError(
                            f"Protocol initialization error: {root}"
                        ) from exc
                    raise

                if attempt < self._max_retries:
                    delay = self._retry_delay * (2**attempt)
                    logger.warning(
                        "Connection attempt %d to %s failed: %s. Retrying in %.1fs...",
                        attempt + 1,
                        self._url,
                        root,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "All %d connection attempts to %s exhausted.",
                        1 + self._max_retries,
                        self._url,
                    )

        root_error = (
            _unwrap_exception(last_error)
            if last_error
            else RuntimeError("Unknown error")
        )
        if _is_connection_failure(root_error):
            raise MCPConnectionError(
                f"Failed to connect to MCP server at {self._url}: {root_error}"
            ) from last_error
        if _is_timeout_failure(root_error):
            raise MCPTimeoutError(
                f"Connection to MCP server at {self._url} timed out after {self._timeout}s: {root_error}"
            ) from last_error
        raise MCPConnectionError(
            f"Failed to connect to MCP server at {self._url}: {root_error}"
        ) from last_error

    async def disconnect(self) -> None:
        """Terminate the MCP session and release transport resources cleanly."""
        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            except (OSError, RuntimeError) as exc:
                logger.debug("Error while closing MCP client exit stack: %s", exc)
            finally:
                self._exit_stack = None
                self._session = None
                self._is_connected = False
                logger.info(
                    "MCP client session cleanly disconnected from %s", self._url
                )

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

    def _ensure_connected(self) -> ClientSession:
        """Ensure the client is actively connected before sending requests."""
        if not self.is_connected or self._session is None:
            raise MCPConnectionError(
                "MCP client is not connected. Call 'connect()' or use 'async with' context."
            )
        return self._session

    async def list_tools(self) -> list[ToolDescriptor]:
        """Dynamically discover all available tools registered on the MCP server."""
        session = self._ensure_connected()
        descriptors: list[ToolDescriptor] = []
        cursor: str | None = None

        try:
            while True:
                # Support pagination if server supports cursors
                result = await session.list_tools()
                for tool in result.tools:
                    schema = getattr(
                        tool, "input_schema", getattr(tool, "inputSchema", {})
                    )
                    descriptors.append(
                        ToolDescriptor(
                            name=tool.name,
                            description=tool.description or "",
                            input_schema=dict(schema) if schema else {},
                        )
                    )
                cursor = getattr(result, "next_cursor", None)
                if not cursor:
                    break
        except (BaseExceptionGroup, OSError, ConnectionError) as exc:
            root = _unwrap_exception(exc)
            raise MCPConnectionError(
                f"Connection lost while discovering tools: {root}"
            ) from exc
        except MCPError as exc:
            raise MCPProtocolError(f"MCP protocol error listing tools: {exc}") from exc

        return descriptors

    async def list_resources(self) -> list[ResourceDescriptor]:
        """Dynamically discover all available resources registered on the MCP server."""
        session = self._ensure_connected()
        descriptors: list[ResourceDescriptor] = []

        try:
            while True:
                result = await session.list_resources()
                for resource in result.resources:
                    descriptors.append(
                        ResourceDescriptor(
                            uri=str(resource.uri),
                            name=resource.name,
                            description=resource.description or "",
                            mime_type=resource.mime_type or "application/json",
                        )
                    )
                cursor = getattr(result, "next_cursor", None)
                if not cursor:
                    break
        except (BaseExceptionGroup, OSError, ConnectionError) as exc:
            root = _unwrap_exception(exc)
            raise MCPConnectionError(
                f"Connection lost while discovering resources: {root}"
            ) from exc
        except MCPError as exc:
            raise MCPProtocolError(
                f"MCP protocol error listing resources: {exc}"
            ) from exc

        return descriptors

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        raise_on_error: bool = False,
    ) -> ToolExecutionResult:
        """Invoke a registered MCP tool with structured arguments.

        Args:
            name: Name of the registered tool.
            arguments: Dictionary of arguments matching tool input schema.
            raise_on_error: If True, raises MCPToolError when the tool indicates failure.

        Returns:
            ToolExecutionResult with parsed data and raw text.
        """
        session = self._ensure_connected()

        try:
            res = await session.call_tool(name=name, arguments=arguments or {})
        except (BaseExceptionGroup, OSError, ConnectionError) as exc:
            root = _unwrap_exception(exc)
            raise MCPConnectionError(
                f"Connection error while calling tool '{name}': {root}"
            ) from exc
        except MCPError as exc:
            if raise_on_error:
                raise MCPToolError(
                    f"Protocol error executing tool '{name}': {exc}"
                ) from exc
            return ToolExecutionResult(
                tool_name=name,
                is_error=True,
                data={"error": str(exc)},
                raw_text=str(exc),
            )

        raw_text: str | None = None
        data: Any = None
        is_error: bool = bool(res.is_error)

        if getattr(res, "structured_content", None) is not None:
            struct = res.structured_content
            if isinstance(struct, dict) and "result" in struct and len(struct) == 1:
                data = struct["result"]
            else:
                data = struct
        elif res.content:
            texts = [
                c.text for c in res.content if hasattr(c, "text") and c.text is not None
            ]
            if texts:
                raw_text = "\n".join(texts)
                try:
                    data = json.loads(raw_text)
                except (json.JSONDecodeError, TypeError):
                    data = raw_text
        elif not is_error:
            data = []

        if isinstance(data, dict) and "error" in data:
            is_error = True

        if is_error and raise_on_error:
            error_message = (
                data.get("error")
                if isinstance(data, dict)
                else (raw_text or "Tool failed")
            )
            raise MCPToolError(f"Tool '{name}' failed: {error_message}")

        return ToolExecutionResult(
            tool_name=name,
            is_error=is_error,
            data=data,
            raw_text=raw_text,
        )

    async def read_resource(self, uri: str) -> ResourceReadResult:
        """Read a registered MCP resource by its URI.

        Args:
            uri: Standard URI of the registered resource.

        Returns:
            ResourceReadResult with structured data or raw text.
        """
        session = self._ensure_connected()

        try:
            res = await session.read_resource(uri=uri)
        except (BaseExceptionGroup, OSError, ConnectionError) as exc:
            root = _unwrap_exception(exc)
            raise MCPConnectionError(
                f"Connection error while reading resource '{uri}': {root}"
            ) from exc
        except MCPError as exc:
            raise MCPResourceError(f"Failed to read resource '{uri}': {exc}") from exc

        if not res.contents:
            return ResourceReadResult(
                uri=uri,
                mime_type="text/plain",
                data=None,
                raw_text="",
            )

        first_content = res.contents[0]
        mime_type = (
            getattr(first_content, "mime_type", "application/json")
            or "application/json"
        )
        raw_text = getattr(first_content, "text", None)

        if raw_text is not None:
            try:
                data = json.loads(raw_text)
            except (json.JSONDecodeError, TypeError):
                data = raw_text
        else:
            blob = getattr(first_content, "blob", None)
            data = blob

        return ResourceReadResult(
            uri=uri,
            mime_type=mime_type,
            data=data,
            raw_text=raw_text,
        )
