"""ResearchMate — Main Application Entry Point (Phase 11).

Integrates the CLI user interface with the Gemini-powered central orchestrator,
specialized agents (Research Agent and Task Agent), client-side MCP host,
and server-side MCP ecosystem over Streamable HTTP.
"""

import argparse
import asyncio
import logging
import signal
import sys
import time
from typing import Any

import httpx

from client_mcp.config import get_client_settings
from client_mcp.host import MCPHost
from mas.cli import ResearchMateCLI
from mas.lifecycle import check_mcp_server_health, run_preflight_checks
from mas.orchestrator.orchestrator import Orchestrator

# Configure application logging
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ResearchMate")


async def _wait_for_server(url: str, timeout_seconds: float = 10.0) -> bool:
    """Poll the MCP server health endpoint until available or timed out."""
    base_url = url.split("/mcp")[0]
    health_url = f"{base_url}/health"
    deadline = time.monotonic() + timeout_seconds

    async with httpx.AsyncClient(timeout=1.0) as client:
        while time.monotonic() < deadline:
            try:
                res = await client.get(health_url)
                if res.status_code == 200:
                    return True
            except (httpx.HTTPError, OSError):
                await asyncio.sleep(0.2)
    return False


async def async_main(args: argparse.Namespace) -> int:
    """Async application lifecycle controller."""
    client_settings = get_client_settings()
    server_process: asyncio.subprocess.Process | None = None

    # Pre-flight server check
    mcp_online, _ = await check_mcp_server_health(client_settings.server_url)

    if not mcp_online and args.spawn_server:
        print(f"Starting background MCP server at {client_settings.server_url}...")
        python_exe = sys.executable
        server_process = await asyncio.create_subprocess_exec(
            python_exe,
            "-m",
            "server_mcp",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        ready = await _wait_for_server(client_settings.server_url, timeout_seconds=10.0)
        if not ready:
            print(
                "[ERROR] Spawned MCP server failed to respond within 10s.",
                file=sys.stderr,
            )
            if server_process and server_process.returncode is None:
                try:
                    server_process.terminate()
                except ProcessLookupError:
                    pass
            return 1
        print("MCP server started successfully.")
    elif not mcp_online and not args.check:
        print(
            f"\n[ERROR] MCP Server is not reachable at {client_settings.server_url}",
            file=sys.stderr,
        )
        print(
            "Please start the MCP server before running ResearchMate:\n"
            "    python -m server_mcp\n"
            "Or run ResearchMate with automated server management:\n"
            "    python main.py --spawn-server",
            file=sys.stderr,
        )
        return 1

    try:
        # Pre-flight check mode
        if args.check:
            print("--- ResearchMate Pre-Flight Check ---")
            health = await run_preflight_checks()
            for service, msg in health.details.items():
                ok = getattr(health, service, False)
                print(f"  [{'OK' if ok else 'FAIL'}] {service.capitalize():12}: {msg}")
            return 0 if health.is_operational else 1

        # Instantiate shared host and orchestrator
        async with MCPHost(settings=client_settings) as host:
            orchestrator = Orchestrator(mcp_host=host)
            cli = ResearchMateCLI(mcp_host=host, orchestrator=orchestrator)

            # Single query mode (non-interactive)
            if args.prompt:
                query = " ".join(args.prompt).strip()
                return await cli.run_single_query(query)

            # Interactive REPL mode
            return await cli.run_interactive_session()

    finally:
        # Cleanup spawned server process on exit
        if server_process is not None and server_process.returncode is None:
            print("\nShutting down background MCP server...")
            try:
                server_process.terminate()
                await asyncio.wait_for(server_process.wait(), timeout=3.0)
            except (ProcessLookupError, TimeoutError):
                try:
                    server_process.kill()
                except ProcessLookupError:
                    pass


def main() -> None:
    """Synchronous entry point with CLI argument parsing and signal handling."""
    parser = argparse.ArgumentParser(
        description="ResearchMate — Multi-Agent AI Research Assistant",
        prog="researchmate",
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="Optional single query to execute in non-interactive batch mode.",
    )
    parser.add_argument(
        "--spawn-server",
        action="store_true",
        help="Automatically launch server_mcp in the background if not already running.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run pre-flight health checks across all dependencies and exit.",
    )

    args = parser.parse_args()

    # Gracefully intercept SIGINT (Ctrl+C)
    def sigint_handler(signum: int, frame: Any) -> None:
        print("\nProcess interrupted by user. Exiting ResearchMate.")
        sys.exit(0)

    try:
        signal.signal(signal.SIGINT, sigint_handler)
    except (ValueError, AttributeError):
        pass

    try:
        exit_code = asyncio.run(async_main(args))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nExiting ResearchMate.")
        sys.exit(0)


if __name__ == "__main__":
    main()
