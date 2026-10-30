# AGENTS.md - Instructions for AI Coding Agents

This file applies to any AI coding agent working in the ResearchMate repository.
It summarizes rules from `docs/IMPLEMENTATION_PLAN.md` (section 7),
`docs/DEVELOPMENT_ENVIRONMENT.md` (section 8) and `docs/DECISIONS.md`. If this
file and a document in `docs/` disagree, the document wins; report the conflict.

## Before you change anything

1. Read `README.md`, this file, and the relevant documents in `docs/`.
2. Read `docs/DECISIONS.md`. Respect the difference between Accepted, Proposed,
   Deferred and Open decisions. Do not treat Proposed or Deferred items as final.
3. Check the actual machine state before changing the environment. Do not assume
   documented versions are still installed.

## Working rules

- Implement only the current phase of `docs/IMPLEMENTATION_PLAN.md`.
- Do not silently change requirements, architecture, MCP tool names, resource
  URIs or public interfaces. Record significant changes in `docs/DECISIONS.md`
  and get project-owner approval before changing an Accepted decision.
- Do not rewrite, rename or delete files in `docs/` unless explicitly asked.
- Do not add frameworks or infrastructure without approval. Avoid LangChain,
  LangGraph, CrewAI, AutoGen, Docker, Kubernetes, Redis, Kafka, OpenTelemetry
  and an agent gateway (DEC-023).
- Do not reinstall Python, Git, Ollama or PostgreSQL if they are already working.
- Do not download or switch Ollama models without explaining why and getting approval.
- Add or update tests for every feature. Run them and report actual results.
  Do not call a stubbed or mocked feature complete.
- At the end of each phase report: work completed, files changed, tests run and
  results, known issues, and the next recommended step.

## Architecture boundaries

| Directory | Responsibility | Must not depend on |
|---|---|---|
| `mas/` | Orchestrator, agents, agent configuration | `server_mcp/`, `database/` internals |
| `client_mcp/` | MCP host and client connections | `server_mcp/`, `database/` internals |
| `server_mcp/` | MCP tools/resources and server startup | `mas/`, `client_mcp/` |
| `database/` | Models, connection management, migrations | `mas/`, `client_mcp/`, `server_mcp/` |
| `workspace/` | Files agents may read via File Management | not application code |

`mas/`, `client_mcp/`, `server_mcp/` and `database/` stay independently runnable
and testable (DEC-004, DEC-024). MAS and the MCP server talk only over
Streamable HTTP. The workspace is separate from source code, docs and PostgreSQL
data storage.

## Security rules

- Never put credentials in source code, docs, logs, tests, fixtures or MCP
  resource responses. Secrets live only in `.env` (git-ignored).
- Never print or echo the contents of `.env`.
- File Management is read-only and restricted to the configured workspace root.
  Use resolved paths (not string-prefix checks), reject `..` traversal and
  symlink escapes, and treat file contents as untrusted data.
- Never expose connection strings, API keys or filesystem paths through System
  Information resources.
- Do not drop, reset or overwrite an existing database.
- Use parameterized queries or ORM-safe operations only.

## Stack (from the docs)

Python (see open question about version), official MCP SDK over Streamable HTTP,
PostgreSQL with SQLAlchemy + Psycopg, Alembic (Proposed), Pydantic Settings,
Gemini via `google-genai` for the orchestrator, Ollama with `llama3.2:3b` for the
Research and Task agents (shared runtime, one model instance), pytest,
pytest-asyncio, Ruff.

The machine is a Windows laptop with 8 GB RAM. Keep dependencies light, run one
local model instance, and bound queries, file reads and context sizes.
