"""Interactive Command Line Interface for ResearchMate (Phase 11).

Provides an interactive multi-turn REPL and single-query execution interface,
managing conversation state, pre-flight diagnostics, and graceful shutdown.
"""

import asyncio
import logging
import sys

from client_mcp.host import MCPHost
from mas.lifecycle import run_preflight_checks
from mas.orchestrator.conversation import ConversationManager
from mas.orchestrator.models import OrchestratorRequest, OrchestratorResponse
from mas.orchestrator.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

BANNER = """
================================================================================
                     ResearchMate — AI Research Assistant
                     Multi-Agent System & MCP Tool Host
================================================================================
Type your research request or instruction.
Commands: /help (assistance), /status (health), /reset (clear context), /quit
"""

HELP_TEXT = """
Available Commands:
  /help        - Show this help message and system capabilities.
  /status      - Show connectivity status for PostgreSQL, MCP Server, and Gemini.
  /diagnostics - Query dynamic tool and resource counts from the active MCPHost session.
  /reset       - Clear multi-turn conversation history.
  /quit, /exit - Disconnect cleanly and terminate ResearchMate.

System Capabilities:
  - Research Agent : Reads/searches workspace files (documents, reports, datasets, code),
                     manages research notes, tags, and note version history.
  - Task Agent     : Tracks academic milestones, creates/updates/deletes tasks, manages
                     priorities, deadlines, and agent system information.
  - Orchestrator   : Gemini-powered multi-agent planner with automatic single, independent,
                     and sequential delegation.
"""


class ResearchMateCLI:
    """CLI session coordinator for ResearchMate."""

    def __init__(
        self,
        mcp_host: MCPHost | None = None,
        orchestrator: Orchestrator | None = None,
        conversation_manager: ConversationManager | None = None,
    ) -> None:
        self.mcp_host = mcp_host or MCPHost()
        self.conversation_manager = conversation_manager or ConversationManager()
        self.orchestrator = orchestrator or Orchestrator(mcp_host=self.mcp_host)

    def print_banner(self) -> None:
        """Display the welcome banner."""
        print(BANNER)

    async def print_status(self) -> None:
        """Display consolidated pre-flight dependency health report."""
        print("\n--- System Dependency Status ---")
        health = await run_preflight_checks(host=self.mcp_host)
        status_symbol = lambda ok: "[OK]" if ok else "[WARN]"

        print(
            f"  {status_symbol(health.workspace)} Workspace   : {health.details.get('workspace')}"
        )
        print(
            f"  {status_symbol(health.mcp_server)} MCP Server  : {health.details.get('mcp_server')}"
        )
        print(
            f"  {status_symbol(health.database)} PostgreSQL  : {health.details.get('database')}"
        )
        print(
            f"  {status_symbol(health.gemini)} Gemini API  : {health.details.get('gemini')}"
        )
        print(f"  Conversation Turns Active : {self.conversation_manager.turn_count}")

    async def print_diagnostics(self) -> None:
        """Query and display MCPHost capability discovery diagnostics."""
        print("\n--- MCPHost Diagnostics ---")
        try:
            diag = await self.mcp_host.run_diagnostics()
            print(f"  Connected Server : {diag.get('server_url')}")
            print(f"  Session Active   : {diag.get('connected')}")
            print(f"  Tools Discovered : {diag.get('tool_count')} available")
            print(f"  Resources Loaded : {diag.get('resource_count')} available")
            tools = diag.get("tools", [])
            if tools:
                print(
                    f"  Tool Inventory   : {', '.join(tools[:8])}{'...' if len(tools) > 8 else ''}"
                )
        except Exception as exc:  # noqa: BLE001
            print(f"  Diagnostics query failed: {exc}")

    def format_response(self, response: OrchestratorResponse) -> str:
        """Format an OrchestratorResponse for clean CLI display."""
        lines: list[str] = [""]
        mode_str = response.plan.mode.value if response.plan else "direct"
        lines.append(
            f"[{'SUCCESS' if response.is_success else 'ATTENTION'}] (Mode: {mode_str})"
        )

        # Display individual step status if multi-step or agent execution occurred
        if response.results:
            lines.append("Delegation Summary:")
            for r in response.results:
                tool_summary = ""
                if r.tool_calls:
                    names = [tc.tool_name for tc in r.tool_calls]
                    tool_summary = f" (Tools: {', '.join(names)})"
                lines.append(
                    f"  * {r.step_id}: {r.agent_name} [{r.status.value}]{tool_summary}"
                )
                if r.error:
                    lines.append(f"    Error: {r.error}")

        lines.append("\n" + response.content)
        return "\n".join(lines)

    async def execute_turn(self, prompt: str) -> OrchestratorResponse:
        """Execute a single user prompt within the conversation session."""
        req = OrchestratorRequest(
            prompt=prompt,
            context=self.conversation_manager.get_context_dict(),
        )
        response = await self.orchestrator.run(req)
        self.conversation_manager.add_turn(prompt, response)
        return response

    async def run_single_query(self, prompt: str) -> int:
        """Execute a single query in non-interactive batch mode and exit."""
        try:
            if not self.mcp_host.is_connected:
                await self.mcp_host.connect()

            response = await self.execute_turn(prompt)
            print(self.format_response(response))
            return 0 if response.is_success else 1
        except Exception as exc:  # noqa: BLE001
            print(f"\n[ERROR] Request failed: {exc}", file=sys.stderr)
            return 1
        finally:
            if self.mcp_host.is_connected:
                await self.mcp_host.disconnect()

    async def run_interactive_session(self) -> int:
        """Execute the interactive REPL multi-turn conversation loop."""
        self.print_banner()

        # Connect MCPHost
        try:
            print("Connecting to MCP host and validating pre-flight health...")
            await self.mcp_host.connect()
            await self.print_status()
        except Exception as exc:  # noqa: BLE001
            print(f"\n[ERROR] Failed to connect to MCP Server: {exc}", file=sys.stderr)
            print(
                "Please ensure the MCP server is running at its configured URL.\n"
                "Start the server in another terminal via: python -m server_mcp\n"
                "Or launch ResearchMate with: python main.py --spawn-server",
                file=sys.stderr,
            )
            return 1

        print("\nResearchMate is ready.")

        try:
            while True:
                try:
                    # Async-friendly user input in executor to avoid event loop blocking
                    user_input = await asyncio.to_thread(input, "\nResearchMate > ")
                except (EOFError, KeyboardInterrupt):
                    print("\nSession interrupted. Exiting ResearchMate.")
                    break

                text = user_input.strip()
                if not text:
                    continue

                lowered = text.lower()
                if lowered in ("/quit", "/exit", "quit", "exit"):
                    print("Goodbye!")
                    break

                if lowered == "/help":
                    print(HELP_TEXT)
                    continue

                if lowered == "/status":
                    await self.print_status()
                    continue

                if lowered == "/diagnostics":
                    await self.print_diagnostics()
                    continue

                if lowered == "/reset":
                    self.conversation_manager.clear()
                    print("Conversation context cleared. Starting fresh conversation.")
                    continue

                # Process user request through orchestrator
                try:
                    response = await self.execute_turn(text)
                    print(self.format_response(response))
                except Exception as exc:  # noqa: BLE001
                    print(f"\n[ERROR] Failed to process request: {exc}")

        finally:
            print("Cleaning up connections and shutting down...")
            if self.mcp_host.is_connected:
                await self.mcp_host.disconnect()

        return 0
