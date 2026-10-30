"""Independent CLI execution entry point for Research Agent."""

import asyncio
import sys

from mas.agents.research_agent.agent import run_standalone_cli

if __name__ == "__main__":
    sys.exit(asyncio.run(run_standalone_cli()))
