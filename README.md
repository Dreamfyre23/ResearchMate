# ResearchMate

ResearchMate is a multi-agent AI research assistant designed for students and academic researchers. A central Gemini-powered orchestrator classifies user requests, plans multi-step academic workflows, and delegates subtasks to specialized local agents running on Ollama (`llama3.2:3b`). The agents interact with academic data and local documents through an ecosystem of tools and resources exposed over the Model Context Protocol (MCP) using Streamable HTTP. Relational data is persisted in PostgreSQL, and files are managed within a strictly bounded workspace.

**Release Status:** Initial Release (v0.1.0) — Phase 12 (Stabilization and Initial Release) Complete.

---

## 1. Architecture and Execution Flow

```text
User
 │
 ▼
CLI Entry Point (main.py / mas/cli.py)
 │
 ▼
Gemini Orchestrator (mas/orchestrator/)
 ├── Single Mode      -> Research Agent or Task Agent
 ├── Independent Mode -> Concurrent execution across both agents
 ├── Sequential Mode  -> Step 1 output propagated to Step 2
 └── Unsupported Mode -> Direct domain assistance without agent invocation
 │
 ▼
Specialist Agents (mas/agents/)
 ├── Research Agent -> Local Ollama (llama3.2:3b) -> Notes & Workspace Files
 └── Task Agent     -> Local Ollama (llama3.2:3b) -> Tasks, Deadlines & Agent Info
 │
 ▼
Client-Side MCP Host (client_mcp/host.py)
 │  [Streamable HTTP Transport]
 ▼
Server-Side MCP Server (server_mcp/server.py)
 ├── Task Management Tools & Resources (19 tools, 17 resources)
 ├── Notes Management Tools & Resources
 ├── File Management Tools (read-only; documents, reports, datasets, source_code)
 ├── Agent Information Tools & Resources
 └── System Information Tools & Resources
 │
 ├──> PostgreSQL Database (tasks, dependencies, notes, versions, tags, agents)
 └──> Local Workspace Filesystem (workspace/)
```

---

## 2. Directory Layout

```text
mas/           Central orchestrator, specialist agents, conversation manager, lifecycle
client_mcp/    Client-side MCP host and Streamable HTTP client connections
server_mcp/    Server-side MCP implementation (tools, resources, Starlette server)
database/      SQLAlchemy ORM models, connection management, Alembic migrations
workspace/     Files agents may read (documents/, reports/, datasets/, source_code/)
tests/         Unit, integration, and end-to-end automated tests
docs/          Detailed architecture, requirements, database design, and MCP specifications
logs/          Application logs (git-ignored)
```

---

## 3. Setup and Environment

### Prerequisites
- **Operating System:** Windows 10/11, macOS, or Linux (optimized for 8 GB RAM laptops)
- **Python:** 3.15.2 (64-bit)
- **PostgreSQL:** PostgreSQL 16+ (running on `localhost:5432`)
- **Ollama:** Ollama daemon running locally with model `llama3.2:3b` pulled
- **Google Gemini API Key:** `GOOGLE_API_KEY` for orchestrator planning and synthesis

### Installation Steps

```powershell
# 1. Clone the repository and navigate to the project directory
cd F:\Projects\ResearchMate

# 2. Create and activate a Python 3.15 virtual environment
py -3.15 -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Upgrade pip and install pinned dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4. Configure environment variables
# Copy template and update with your local credentials
cp .env.example .env
```

### PostgreSQL Setup & Database Migrations
Create the PostgreSQL database and run Alembic migrations:
```powershell
# Run Alembic migrations to apply initial schema (tasks, notes, versions, tags, agents)
python -m alembic upgrade head
```

### Pull Ollama Model
Verify that the Ollama service is running and download the shared model instance:
```powershell
ollama pull llama3.2:3b
```

---

## 4. Running ResearchMate

### Pre-Flight System Health Check
Verify that all system components (PostgreSQL, MCP server, Ollama, Gemini configuration, and workspace) are operational:
```powershell
python main.py --check
```

### Interactive REPL Mode
Start ResearchMate in interactive multi-turn conversation mode:

**Option A: Automated Server Management** (spawns background MCP server and terminates it on exit):
```powershell
python main.py --spawn-server
```

**Option B: Independent Server** (start MCP server in one terminal, run CLI in another):
```powershell
# Terminal 1: Start MCP Server
python -m server_mcp

# Terminal 2: Start ResearchMate CLI
python main.py
```

### CLI Interactive Commands
Within the interactive REPL:
- `/help` — Display command list and agent capabilities.
- `/status` — View real-time status of connected services.
- `/diagnostics` — View MCPHost tool and resource discovery statistics.
- `/reset` — Clear multi-turn conversation context history.
- `/quit` or `/exit` — Disconnect cleanly and terminate.

### Single-Query Non-Interactive Mode
Execute a single query directly and return results to standard output:
```powershell
python main.py "List my research tasks"
```

---

## 5. Security & Safety Architecture

ResearchMate enforces strict defense-in-depth security controls across all layers:

1. **Agent Tool Whitelists:**
   - **Research Agent:** Restricted strictly to read-only File Management tools (`list_files`, `read_file`, `search_files`, `get_file_metadata`) and Notes Management tools.
   - **Task Agent:** Restricted to Task Management and Agent Information tools.
2. **Dynamic MCP Schema Validation:**
   - All model-generated tool calls are validated at runtime against the server's dynamically discovered JSON schemas via `jsonschema` before invocation.
3. **Destructive Operation Authorization:**
   - Destructive operations (`delete_task`, `delete_note`) require explicit, affirmative user authorization. Negations, hypothetical queries, past-tense references, general questions, and ambiguous targets are rejected.
4. **Workspace Path Traversal & Symlink Sandboxing:**
   - File Management tools resolve paths canonically using `Path.resolve()` and verify strictly that targets lie within `workspace/`. Traversal sequences (`..`), absolute paths, and symlink escapes pointing outside the workspace are blocked.
   - Only permitted file extensions (`.txt`, `.md`, `.json`, `.csv`, `.py`, `.sql`) are readable.
   - Maximum file size limits (`MAX_FILE_SIZE_BYTES=10485760`) prevent memory exhaustion.
5. **Credential Protection & Log Sanitization:**
   - API keys and secrets are excluded from logs, error messages, and MCP resource responses using automated regex pattern redaction.
   - `.env` and `.venv/` are excluded from version control.

---

## 6. Resource Management & Hardware Optimization (8 GB RAM)

ResearchMate is engineered to run reliably on resource-constrained development machines:
- **Single Ollama Instance:** A single `llama3.2:3b` model instance is shared sequentially or concurrently between agents with `keep_alive=5m` to prevent model thrashing.
- **Low Model Temperature:** Set to `0.1` for local agents to ensure deterministic tool calling and low inference latency.
- **Bounded Sliding-Window Context:** The conversation manager maintains a 3-turn sliding window with response summaries truncated to 250 characters, preventing memory and context explosion.
- **Bounded Tool Limits:** File searches and directory listings are bounded (maximum 200–1000 items) to prevent large payload memory spikes.
- **Connection Pools & Cleanup:** PostgreSQL connection pool is sized to 5 connections with clean context-manager disposal. `MCPHost` leverages `AsyncExitStack` for clean transport disconnection.

---

## 7. Independent Component Execution (DEC-024)

Each major subsystem can be executed, tested, and diagnosed completely independently:

- **Server-Side MCP Server:**
  ```powershell
  python -m server_mcp
  ```
- **Client-Side MCP Host Demo:**
  ```powershell
  python -m client_mcp
  ```
- **Research Agent Standalone:**
  ```powershell
  python -m mas.agents.research_agent "Search notes for deep learning"
  ```
- **Task Agent Standalone:**
  ```powershell
  python -m mas.agents.task_agent "List pending tasks"
  ```
- **Central Orchestrator Standalone:**
  ```powershell
  python -m mas.orchestrator "Summarize my research notes"
  ```

---

## 8. Testing

### Run Consolidated Test Suite
```powershell
# Run all unit and integration tests (excluding live Gemini API)
pytest tests -m "not live_gemini"
```

### Run Unit Tests Only
```powershell
pytest tests/unit/
```

### Run End-to-End Integration Tests
```powershell
pytest tests/integration/test_end_to_end.py
```

### Run Live Gemini API Tests (Requires valid GOOGLE_API_KEY)
```powershell
pytest tests/integration/test_mas_orchestrator_integration.py -k "test_live_gemini"
```

### Code Quality and Linting
```powershell
ruff check .
ruff format --check .
```

---

## 9. Known Limitations & Deferred Capabilities

As documented in `docs/IMPLEMENTATION_PLAN.md` (Section 4) and accepted architectural decisions:
- **Document Formats:** Initial release supports text-based academic assets (`.txt`, `.md`, `.json`, `.csv`, `.py`, `.sql`). Binary document parsing (PDF, DOCX, XLSX) is deferred to future capability phases.
- **External Web Search:** Live internet academic retrieval is deferred to future capability phases.
- **Single-User Workspace:** The workspace is structured for single-user local development; multi-user data isolation is planned for future releases.
- **Windows Symlink Testing:** Symbolic link escape verification tests require Windows Developer Mode or Administrator privileges to create local test symlinks; non-privileged runs gracefully skip that test while full runtime path boundary checks remain active.
