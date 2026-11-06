# ResearchMate

ResearchMate is a multi-agent AI research assistant designed for students and academic researchers. A central Gemini-powered orchestrator classifies user requests, plans multi-step academic workflows, and delegates subtasks to specialized agents (Research Agent and Task Agent) powered by Google Gemini with native function calling and multi-model fallback (DEC-033). The agents interact with academic data and local documents through an ecosystem of tools and resources exposed over the Model Context Protocol (MCP) using Streamable HTTP. Relational data is persisted in PostgreSQL, and files are managed within a strictly bounded workspace.

**Release Status:** Initial Release (v0.1.0) — Stabilized and fully migrated to Google Gemini API (DEC-033).

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
 ├── Research Agent -> Google Gemini (gemini-3.5-flash-lite, fallback chain) -> Notes & Workspace Files
 └── Task Agent     -> Google Gemini (gemini-3.5-flash-lite, fallback chain) -> Tasks, Deadlines & Agent Info
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
- **Google Gemini API Key:** A valid `GOOGLE_API_KEY` from [Google AI Studio](https://aistudio.google.com/) for orchestrator planning and sub-agent function calling.

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
# Copy template and update with your local credentials and API key
cp .env.example .env
```

### PostgreSQL Setup & Database Migrations
Create the PostgreSQL database and run Alembic migrations:
```powershell
# Run Alembic migrations to apply initial schema (tasks, notes, versions, tags, agents)
python -m alembic upgrade head
```

### Environment Configuration (.env)
Update `.env` with your Google API key, database credentials, and model configurations:
```env
GOOGLE_API_KEY=your_actual_api_key_here

# Central Orchestrator Models (Multi-Model Fallback)
GEMINI_PRIMARY_MODEL=gemini-3.5-flash-lite
GEMINI_FALLBACK_MODELS=gemini-3.6-flash,gemini-3.8-flash
GEMINI_TIMEOUT_SECONDS=60.0
GEMINI_TEMPERATURE=0.2
GEMINI_MODEL_RETRY_ATTEMPTS=1
GEMINI_MODEL_RETRY_DELAY=0.5

# Sub-Agents Models (Task Agent & Research Agent)
AGENT_GEMINI_PRIMARY_MODEL=gemini-3.5-flash-lite
AGENT_GEMINI_FALLBACK_MODELS=gemini-3.6-flash,gemini-3.8-flash
AGENT_GEMINI_TIMEOUT_SECONDS=60.0
AGENT_GEMINI_TEMPERATURE=0.1
AGENT_GEMINI_MODEL_RETRY_ATTEMPTS=1
AGENT_GEMINI_MODEL_RETRY_DELAY=0.5

# PostgreSQL Database
DATABASE_URL=postgresql+psycopg://postgres:your_password@localhost:5432/mas_database

# MCP Server
MCP_SERVER_HOST=127.0.0.1
MCP_SERVER_PORT=8000
MCP_SERVER_URL=http://127.0.0.1:8000/mcp
WORKSPACE_ROOT=workspace
```

---

## 4. Running ResearchMate

### Pre-Flight System Health Check
Verify that all system components (PostgreSQL, MCP server, Gemini configuration, and workspace) are operational:
```powershell
python main.py --check
```

### Interactive REPL Mode
Start ResearchMate in interactive multi-turn conversation mode:

**Option A: Automated Server Management** (automatically starts the background MCP server and shuts it down on exit):
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
- `/status` — View real-time status of connected services (PostgreSQL, MCP Server, Gemini API).
- `/diagnostics` — View MCPHost tool and resource discovery statistics.
- `/reset` — Clear multi-turn conversation context history.
- `/quit` or `/exit` — Disconnect cleanly and terminate.

### Single-Query Non-Interactive Mode
Execute a single query directly and return results to standard output:
```powershell
python main.py --spawn-server "Find tasks containing the keyword Cryptography"
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

## 6. Resource Management & Gemini Multi-Model Fallback

ResearchMate is engineered for low latency, zero hardware bottlenecks, and resilient execution:
- **Native Gemini Function Calling:** Leverages Google's official `google-genai` SDK for reliable schema compliance, structured query generation, and seamless thought-signature preservation.
- **Low Model Temperature:** Set to `0.1` for sub-agents to guarantee deterministic, reproducible tool calls.
- **Bounded Sliding-Window Context:** The conversation manager maintains a 3-turn sliding window with response summaries truncated to 250 characters, preventing memory and context explosion.
- **Bounded Tool Limits:** File searches and directory listings are bounded (maximum 200–1000 items) to prevent large payload memory spikes.
- **Connection Pools & Cleanup:** PostgreSQL connection pool is sized to 5 connections with clean context-manager disposal. `MCPHost` leverages `AsyncExitStack` for clean transport disconnection.

### Dual-Layer Multi-Model Fallback System
Both the central orchestrator and specialist agents implement independent, resilient multi-model fallback chains:
- **Prioritized Model Traversal:** Tries the primary model (e.g. `gemini-3.5-flash-lite`) and automatically advances to fallbacks (`gemini-3.6-flash`, `gemini-3.8-flash`) if quotas or transient errors occur.
- **Error Classification & Bounded Retries:**
  - `DAILY_QUOTA_EXHAUSTED` (429 daily quota): Switches immediately to the next fallback model without retry delay, recording the exhausted model in cooldown for subsequent turns.
  - `OVERLOADED_503`, `TIMEOUT`, `SERVER_ERROR_5XX`: Performs a bounded retry (1 attempt) before transitioning to the next candidate model.
  - `INVALID_REQUEST_400`, `AUTH_ERROR_401_403`: Terminate candidate evaluation immediately without futile fallback calls.
- **In-Memory Health Tracker (`AgentModelHealthTracker`):** Prevents redundant API requests to models currently experiencing cooldowns or quota exhaustion.
- **Deterministic Heuristic Fallback:** If all configured Gemini models are exhausted or unavailable during orchestrator planning, execution safely reverts to deterministic rule-based processing without crashing.
- **Preservation of Agent Results:** Synthesis failures never trigger agent re-execution; collected findings from specialist agents remain preserved.

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
