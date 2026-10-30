"""Independent CLI execution entry point for ResearchMate central orchestrator."""

import asyncio
import sys

from client_mcp.host import MCPHost
from mas.orchestrator.orchestrator import Orchestrator


async def run_standalone_orchestrator_cli() -> int:
    """Run an interactive test session with the central orchestrator."""
    print("=" * 70)
    print(" ResearchMate Central Orchestrator (Phase 10)")
    print("=" * 70)

    prompt = " ".join(sys.argv[1:]).strip() if len(sys.argv) > 1 else ""
    if not prompt:
        prompt = input("\nEnter research/task instruction: ").strip()

    if not prompt:
        print("No prompt provided. Exiting.")
        return 1

    print("\nConnecting to MCP host and initializing orchestrator...")
    async with MCPHost() as host:
        orchestrator = Orchestrator(mcp_host=host)
        res = await orchestrator.run(prompt)

        print("\n" + "=" * 70)
        print(" Orchestration Results")
        print("=" * 70)
        print(f"Overall Success : {res.is_success}")
        if res.plan:
            print(f"Execution Mode  : {res.plan.mode.value}")
            print(f"Plan Reasoning  : {res.plan.reasoning}")
            print(f"Delegated Steps : {len(res.results)}")
        for r in res.results:
            print(
                f"  - Step: {r.step_id} | Agent: {r.agent_name} | Status: {r.status.value}"
            )
            if r.error:
                print(f"    Error: {r.error}")

        print("\nFinal Synthesized Response:")
        print("-" * 70)
        print(res.content)
        print("-" * 70)
        return 0 if res.is_success else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run_standalone_orchestrator_cli()))
