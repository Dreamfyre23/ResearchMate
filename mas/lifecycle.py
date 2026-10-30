"""Service lifecycle and pre-flight validation management for ResearchMate (Phase 11).

Performs health checks on startup and coordinates graceful shutdown of connections
and background tasks across all integrated components.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from client_mcp.config import get_client_settings
from client_mcp.host import MCPHost
from mas.config.settings import get_gemini_settings, get_ollama_settings
from mas.ollama.client import OllamaService
from mas.ollama.exceptions import OllamaModelNotFoundError

logger = logging.getLogger(__name__)


@dataclass
class ServiceHealth:
    """Consolidated health status across all ResearchMate dependencies."""

    mcp_server: bool = False
    database: bool = False
    ollama: bool = False
    gemini: bool = False
    workspace: bool = False
    details: dict[str, str] = field(default_factory=dict)

    @property
    def is_operational(self) -> bool:
        """Return True if core dependencies required for request routing are available."""
        # Core: MCP server and workspace must be operational
        return self.mcp_server and self.workspace


def ensure_workspace_structure(workspace_root: Path | str | None = None) -> bool:
    """Ensure the four permanent workspace directories exist (DEC-032).

    Safely creates missing directories without modifying existing user files.
    """
    root = Path(workspace_root) if workspace_root else Path("workspace")
    subdirs = ["documents", "reports", "datasets", "source_code"]

    try:
        root.mkdir(parents=True, exist_ok=True)
        for subdir in subdirs:
            (root / subdir).mkdir(parents=True, exist_ok=True)
        return True
    except OSError as exc:
        logger.error("Failed to initialize workspace directory structure: %s", exc)
        return False


async def check_mcp_server_health(
    server_url: str | None = None,
    timeout_seconds: float = 2.0,
) -> tuple[bool, str]:
    """Check if the server-side MCP server is reachable and reports healthy.

    Returns:
        Tuple of (is_healthy, diagnostic_message).
    """
    url = server_url or get_client_settings().server_url
    # Extract base URL from endpoint (e.g. http://127.0.0.1:8000/mcp -> http://127.0.0.1:8000/health)
    base_url = url.split("/mcp")[0]
    health_url = f"{base_url}/health"

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.get(health_url)
            if resp.status_code == 200:
                data = resp.json()
                status_text = data.get("status", "ok")
                return True, f"MCP server online ({status_text}) at {base_url}"
            return False, f"MCP server returned HTTP {resp.status_code} at {health_url}"
    except (httpx.ConnectError, OSError) as exc:
        err_msg = str(exc).strip() or "Connection refused (server offline)"
        return False, f"Cannot connect to MCP server at {base_url}: {err_msg}"
    except Exception as exc:  # noqa: BLE001
        err_msg = str(exc).strip() or type(exc).__name__
        return False, f"MCP health check failed: {err_msg}"


async def check_ollama_health(
    ollama_service: OllamaService | None = None,
) -> tuple[bool, str]:
    """Verify connectivity to local Ollama daemon and model availability.

    Returns:
        Tuple of (is_healthy, diagnostic_message).
    """
    service = ollama_service or OllamaService(settings=get_ollama_settings())
    try:
        is_up = await service.check_health()
        if not is_up:
            return False, f"Ollama HTTP service not responding at {service.base_url}"

        try:
            has_model = await service.ensure_model_available()
            if not has_model:
                return (
                    False,
                    f"Model '{service.model_name}' not found in local Ollama repository",
                )
        except OllamaModelNotFoundError as exc:
            return False, str(exc)

        return True, f"Ollama online with model '{service.model_name}'"
    except Exception as exc:  # noqa: BLE001
        return False, f"Ollama check failed: {exc}"


def check_gemini_configuration() -> tuple[bool, str]:
    """Verify Google Gemini API credentials configuration.

    Returns:
        Tuple of (is_healthy, diagnostic_message).
    """
    settings = get_gemini_settings()
    if not settings.api_key or settings.api_key == "replace_with_your_api_key":
        return (
            False,
            "GOOGLE_API_KEY not set in .env (will use deterministic fallback planner)",
        )
    return True, f"Gemini API configured (model: {settings.model})"


async def check_database_status_via_mcp(host: MCPHost) -> tuple[bool, str]:
    """Verify PostgreSQL connectivity via the MCP server's system://database-info resource.

    Returns:
        Tuple of (is_healthy, diagnostic_message).
    """
    try:
        res = await host.read_resource("system://database-info")
        if isinstance(res.data, dict):
            status = res.data.get("status", "unknown")
            if status == "connected":
                db_ver = res.data.get("database_version", "PostgreSQL")
                short_ver = db_ver.split("\n")[0] if db_ver else "PostgreSQL"
                return True, f"Database connected ({short_ver})"
            return False, f"Database reports status: {status}"
        return False, "Unexpected database resource payload from MCP server"
    except Exception as exc:  # noqa: BLE001
        return False, f"Could not query database status through MCP: {exc}"


async def run_preflight_checks(
    host: MCPHost | None = None,
    server_url: str | None = None,
    workspace_root: Path | str | None = None,
) -> ServiceHealth:
    """Execute pre-flight checks across all system dependencies.

    Returns:
        ServiceHealth report detailing availability of each component.
    """
    health = ServiceHealth()

    # Determine MCP server URL
    target_mcp_url = server_url
    if not target_mcp_url and host is not None:
        target_mcp_url = host.settings.server_url

    # 1. Workspace
    ws_ok = ensure_workspace_structure(workspace_root)
    health.workspace = ws_ok
    health.details["workspace"] = (
        "Directories verified (documents, reports, datasets, source_code)"
        if ws_ok
        else "Failed to access/initialize workspace directories"
    )

    # 2. MCP Server
    mcp_ok, mcp_msg = await check_mcp_server_health(target_mcp_url)
    health.mcp_server = mcp_ok
    health.details["mcp_server"] = mcp_msg

    # 3. Database (via MCP if host connected, else note dependency)
    if host and host.is_connected:
        db_ok, db_msg = await check_database_status_via_mcp(host)
        health.database = db_ok
        health.details["database"] = db_msg
    elif mcp_ok:
        health.database = True
        health.details["database"] = (
            "MCP server online; database will be queried through tools"
        )
    else:
        health.database = False
        health.details["database"] = "MCP server offline; cannot reach database"

    # 4. Ollama
    ollama_ok, ollama_msg = await check_ollama_health()
    health.ollama = ollama_ok
    health.details["ollama"] = ollama_msg

    # 5. Gemini
    gemini_ok, gemini_msg = check_gemini_configuration()
    health.gemini = gemini_ok
    health.details["gemini"] = gemini_msg

    return health
