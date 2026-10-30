"""Independent execution entry point for ResearchMate client-side MCP host."""

import asyncio
import sys

from client_mcp.host import run_standalone_demo

if __name__ == "__main__":
    sys.exit(asyncio.run(run_standalone_demo()))
