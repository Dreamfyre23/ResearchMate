"""Research Agent implementation for ResearchMate (Phase 9).

Specialized local AI agent using Ollama (llama3.2:3b) to process research requests,
inspect workspace documents, and manage research notes through MCPHost (DEC-003, DEC-009).
"""

import asyncio
import logging
import sys

from client_mcp.config import get_client_settings
from client_mcp.host import MCPHost
from mas.agents.base import BaseAgent
from mas.agents.research_agent.prompts import RESEARCH_AGENT_SYSTEM_PROMPT
from mas.config.settings import AgentSettings, OllamaSettings
from mas.ollama.client import OllamaService

logger = logging.getLogger(__name__)

RESEARCH_AGENT_PERMITTED_TOOLS = {
    # File Management (strictly read-only)
    "list_files",
    "read_file",
    "search_files",
    "get_file_metadata",
    # Notes Management
    "create_note",
    "get_note",
    "get_notes",
    "update_note",
    "delete_note",
    "search_notes",
}


class ResearchAgent(BaseAgent):
    """Specialized Research Agent for academic inquiry, file inspection, and note organization."""

    def __init__(
        self,
        mcp_host: MCPHost,
        ollama_service: OllamaService | None = None,
        agent_settings: AgentSettings | None = None,
        ollama_settings: OllamaSettings | None = None,
    ) -> None:
        service = ollama_service or OllamaService(settings=ollama_settings)
        super().__init__(
            agent_name="Research Agent",
            system_prompt=RESEARCH_AGENT_SYSTEM_PROMPT,
            permitted_tools=RESEARCH_AGENT_PERMITTED_TOOLS,
            mcp_host=mcp_host,
            ollama_service=service,
            settings=agent_settings,
        )


async def run_standalone_cli() -> int:
    """Run Research Agent independently from command line for testing and validation."""
    prompt = (
        " ".join(sys.argv[1:])
        if len(sys.argv) > 1
        else "List the files available in the workspace documents directory."
    )

    print("=" * 70)
    print(" ResearchMate — Research Agent (Independent CLI Execution)")
    print("=" * 70)
    print(f"Prompt: {prompt}")
    print("-" * 70)

    client_settings = get_client_settings()
    async with MCPHost(settings=client_settings) as host:
        agent = ResearchAgent(mcp_host=host)

        print("[1/2] Verifying Ollama and model availability...")
        try:
            await agent.ollama_service.ensure_model_available()
            print(f"      Ollama model '{agent.ollama_service.model_name}' verified.")
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] Ollama verification failed: {exc}", file=sys.stderr)
            return 1

        print("\n[2/2] Running Research Agent reasoning loop...")
        res = await agent.run(prompt)

        print("\n" + "=" * 70)
        print(" Agent Execution Results")
        print("=" * 70)
        print(f"Success    : {res.is_success}")
        print(f"Iterations : {res.iterations}")
        print(f"Tool Calls : {len(res.tool_calls)}")
        for i, tc in enumerate(res.tool_calls, 1):
            print(f"  [{i}] Tool: {tc.tool_name} (error={tc.is_error})")
            print(f"      Args  : {tc.arguments}")

        print("\nAgent Response:")
        print("-" * 70)
        print(res.content)
        print("-" * 70)
        return 0 if res.is_success else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run_standalone_cli()))
