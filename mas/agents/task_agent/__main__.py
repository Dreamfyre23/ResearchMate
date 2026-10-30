"""Independent CLI execution entry point for Task Agent."""

import asyncio
import sys

from mas.agents.task_agent.agent import run_standalone_cli

if __name__ == "__main__":
    sys.exit(asyncio.run(run_standalone_cli()))
