# ResearchMate — Architecture and Technical Decisions

**Document version:** 0.1  
**Status:** Initial Draft  
**Project name:** ResearchMate

---

## 1. Purpose

This document records important architectural, technical, and product decisions made during ResearchMate development.

It provides a shared reference for developers and AI coding agents. Its purpose is to prevent decisions from being unintentionally changed, duplicated, or contradicted during implementation.

This document is a decision log, not a replacement for the detailed requirements, architecture, database, MCP, implementation, or test documents.

## 2. Decision Status

Use the following status values:

- **Accepted:** Decision has been agreed and should be followed.
- **Proposed:** Suggested decision awaiting confirmation.
- **Deferred:** Deliberately postponed until a later development phase.
- **Superseded:** Replaced by a newer decision. Keep the historical entry for context.

Do not treat proposed or deferred decisions as finalized requirements.

---

## 3. Project Identity and Purpose

### DEC-001 — Project name

**Status:** Accepted

**Decision:** The project is named **ResearchMate**.

**Rationale:** The name communicates the project's purpose as an AI research assistant for students while allowing future expansion beyond research activities.

**Implication:** Use `ResearchMate` as the repository and project directory name.

### DEC-002 — Project purpose

**Status:** Accepted

**Decision:** ResearchMate is a multi-agent AI research assistant intended to help students with academic research, knowledge organization, and productivity.

**Rationale:** The system should combine specialized agents with a shared set of tools and resources.

---

## 4. Architecture Decisions

### DEC-003 — Multi-agent architecture

**Status:** Accepted

**Decision:** Use a central orchestrator with specialized agents.

Initial agents:
- Orchestrator
- Research Agent
- Task Agent

**Rationale:** Specialized agents provide separation of responsibilities, while the orchestrator coordinates user requests and delegation.

**Implication:** Agent responsibilities and interfaces should be defined independently. Additional agents may be introduced later.

### DEC-004 — Separate client-side and server-side MCP components

**Status:** Accepted

**Decision:** Maintain separate client-side MCP host/client functionality and a server-side MCP server.

**Rationale:** The client-side component manages MCP connections for the MAS, while the server-side component exposes tools and resources and performs the associated operations.

**Implication:** Both components should be independently runnable and testable.

### DEC-005 — MCP implementation

**Status:** Accepted

**Decision:** Use the official Python MCP SDK for MCP client and server implementation.

**Rationale:** Use the standard Python SDK rather than implementing the protocol manually.

### DEC-006 — MCP transport

**Status:** Accepted

**Decision:** Use Streamable HTTP for communication between the client-side MCP component and the server-side MCP server.

**Rationale:** It supports independent processes communicating through an HTTP endpoint and is suitable for the intended local service separation.

### DEC-007 — MCP capability organization

**Status:** Proposed

**Decision:** Organize the initial server-side MCP catalog into five categories:

1. Task Management
2. Notes Management
3. File Management
4. Agent Information
5. System Information

The current proposed catalog contains 19 tools and 17 resources.

**Rationale:** Grouping capabilities by responsibility makes the MCP server easier to understand, test, and extend.

**Implication:** Refer to the five category specification files for exact tool names, resource identifiers, arguments, and behavior.

**Note:** The catalog remains subject to review and finalization before implementation.

---

## 5. Model and AI Decisions

### DEC-008 — Orchestrator model provider

**Status:** Accepted

**Decision:** Use the Google Gemini API for the initial orchestrator.

**Rationale:** Use the available Gemini API access for request interpretation, agent selection, and delegation.

**Implication:** The API key must be provided through environment configuration and must not be committed to source control.

### DEC-009 — Local agent model runtime

**Status:** Superseded (by DEC-033)

**Decision:** Use Ollama to run local language models for the Research Agent and Task Agent.

**Rationale:** Ollama provides a local model runtime and allows the initial agents to operate without sending their model inference requests to a cloud LLM provider.

### DEC-010 — Initial local model

**Status:** Superseded (by DEC-033)

**Decision:** Use `llama3.2:3b` as the initial local model for both the Research Agent and Task Agent.

**Rationale:** It is a practical baseline for the available development hardware and has been tested locally.

**Implication:** Both agents should share the same Ollama service rather than unnecessarily loading separate model instances.

**Note:** Validate actual task completion, structured output, and tool-use behavior before treating this model choice as permanent. Replace or revise it if testing shows inadequate performance.

**Superseded by DEC-033:** Testing confirmed `llama3.2:3b` produces unreliable structured tool calls. Agents now use the Google Gemini API.

### DEC-011 — Shared local model runtime

**Status:** Superseded (by DEC-033)

**Decision:** The initial local agents will use a shared Ollama runtime.

**Rationale:** The development machine has limited memory and CPU resources. Running multiple separate model instances would increase resource consumption.

**Superseded by DEC-033:** Agents migrated to Gemini API; Ollama runtime is no longer required.

---

## 6. Database Decisions

### DEC-012 — Database technology

**Status:** Accepted

**Decision:** Use PostgreSQL as the persistent database for ResearchMate.

**Rationale:** PostgreSQL provides relational data storage, constraints, transactions, indexing, and JSONB support suitable for the initial requirements.

### DEC-013 — Database access layer

**Status:** Accepted

**Decision:** Use SQLAlchemy with Psycopg for Python database access.

**Rationale:** SQLAlchemy provides a maintainable application data-access layer, while Psycopg provides PostgreSQL connectivity.

### DEC-014 — Database migrations

**Status:** Proposed

**Decision:** Use Alembic for database schema migrations.

**Rationale:** Version-controlled migrations make database changes reproducible across development and test environments.

---

## 7. Development Environment and Configuration

### DEC-015 — Programming language and version

**Status:** Superseded (by DEC-025)

**Decision:** Use Python 3.11 for the initial implementation.

**Rationale:** It provides compatibility with the selected Python libraries and a stable development baseline.

**Note:** Superseded by DEC-025, which adopts Python 3.15.2 based on verified environment state and package wheel availability.

### DEC-016 — Python virtual environment

**Status:** Accepted

**Decision:** Maintain a project-specific `.venv` directory.

**Rationale:** Project dependencies should be isolated from globally installed Python packages.

### DEC-017 — Environment configuration

**Status:** Accepted

**Decision:** Store local configuration and secrets in `.env`, with `.env.example` as a template.

**Rationale:** Credentials and machine-specific settings must remain outside source code.

**Implication:** `.env` and `.venv/` must be excluded from Git.

### DEC-018 — Project documentation format

**Status:** Accepted

**Decision:** Use Markdown (`.md`) for new project documentation.

**Rationale:** Markdown is readable by developers and AI coding agents, supports structured content, and works well with Git.

**Note:** Existing `.txt` MCP specifications may remain in their current format unless the project owner decides to convert them.

---

## 8. File Management Decisions

### DEC-019 — Controlled local workspace

**Status:** Accepted (Updated by DEC-032)

**Decision:** Use a dedicated `workspace/` directory for files that agents are permitted to access through File Management MCP tools.

**Rationale:** Separating user-provided and agent-generated files from application source code provides a clear storage boundary.

**Workspace layout:**
- `workspace/documents/`
- `workspace/reports/`
- `workspace/datasets/`
- `workspace/source_code/`

**Note:** All four directories are established in the repository structure. Specialized dataset analysis and source-code execution workflows remain deferred (DEC-032).

### DEC-020 — Workspace access boundary

**Status:** Accepted

**Decision:** File Management operations must be restricted to the configured workspace root.

**Rationale:** Agents should not receive arbitrary access to the developer's local drives.

**Implication:** Validate paths, reject path traversal, and prevent symbolic-link escapes.

### DEC-021 — Initial supported file types

**Status:** Proposed

**Decision:** Initially support:
- TXT
- MD
- JSON
- CSV
- PY
- SQL

PDF, DOCX, and XLSX support is deferred.

**Rationale:** Start with formats that can be handled with relatively simple text and structured-data processing.

---

## 9. Development Scope Decisions

### DEC-022 — Build the functional system before advanced security infrastructure

**Status:** Accepted

**Decision:** Implement the basic MAS, MCP capabilities, database integration, and agent delegation before introducing enterprise-grade observability and security infrastructure.

**Rationale:** A working application is needed before advanced monitoring and security controls can be integrated and evaluated meaningfully.

**Deferred areas include:**
- Agent identity and authentication.
- Fine-grained authorization.
- Delegation-chain security and monitoring.
- Agent gateway.
- OpenTelemetry-based observability.
- Advanced threat detection and response.

This decision does not mean basic security practices should be postponed. Secret protection, input validation, database safety, and workspace restrictions are required from the beginning.

### DEC-023 — Avoid unnecessary frameworks in the initial implementation

**Status:** Accepted

**Decision:** Do not introduce large agent frameworks or infrastructure components unless a demonstrated requirement justifies them.

Initially avoid adding:
- LangChain
- LangGraph
- CrewAI
- AutoGen
- Kubernetes
- Redis
- Kafka
- Prometheus and Grafana
- OpenTelemetry
- Agent gateway

**Rationale:** Keep the initial implementation understandable, lightweight, and easier to debug.

**Note:** These technologies are not permanently prohibited. Reconsider them when their capabilities are needed.

### DEC-024 — Independent component execution

**Status:** Accepted

**Decision:** MAS, client-side MCP host, and server-side MCP server should be independently runnable and testable.

**Rationale:** Independent execution supports component-level debugging, integration testing, and future deployment flexibility.

### DEC-025 — Official Python version (Python 3.15.2)

**Status:** Accepted

**Decision:** Adopt Python 3.15.2 as the official project Python version for ResearchMate, superseding DEC-015.

**Rationale:** The development machine is equipped with Python 3.15.2 (64-bit). Package dependency resolution confirmed that all selected libraries (MCP Python SDK, SQLAlchemy, Psycopg 3, Alembic, Pydantic Settings, google-genai, Ollama, Pytest, Ruff) provide native, pre-built binary wheels for Python 3.15 on Windows 64-bit. Adopting 3.15.2 avoids unnecessary runtime downgrades or reinstallation on the host machine.

**Alternatives considered:** Reverting to Python 3.11 was evaluated, but would require installing an older runtime on the host system without technical necessity.

**Implications:** The project virtual environment (`.venv`) uses Python 3.15.2. All project documentation, requirements, and test plans reflect Python 3.15.2. Complete application-level compatibility must be verified through phased implementation and automated testing, rather than assuming complete compatibility from successful installation/import alone.

**Date:** 2026-10-30

### DEC-026 — Identifier standardization (UUID)

**Status:** Accepted

**Decision:** Use UUIDs consistently as the primary identifier across the entire system. PostgreSQL uses its native `UUID` type for primary and foreign keys. All MCP tool inputs, outputs, and resource URIs serialize UUIDs as standard 36-character hyphenated UUID strings (e.g. `a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d`). This applies uniformly to tasks, notes, agents, note versions, and tags. Human-readable agent codes (such as `AGENT-001`) are retained only as optional display identifiers, strictly separate from the UUID primary key.

**Rationale:** Establishes unambiguous consistency between the PostgreSQL relational schema, SQLAlchemy ORM models, Pydantic schemas, and MCP JSON data contracts. Eliminates conflicting illustrative examples (such as integer IDs `101`, `201`) and prevents ID collisions.

**Alternatives considered:**
- Integer auto-increment IDs: Rejected because it conflicts with `DATABASE_DESIGN.md` and complicates future distributed or multi-agent identification.
- Dual-identifier scheme: Rejected as overly complex.

**Implications:** Database models, Pydantic schemas, MCP tool signatures, and resource responses consistently use standard 36-character hyphenated UUID strings. Illustrative examples in MCP specifications are updated to standard UUID strings.

**Date:** 2026-10-30

### DEC-027 — Unified Attribution object for MCP interfaces

**Status:** Accepted

**Decision:** Adopt a consistent canonical Attribution object across all MCP tool interfaces and resource representations for attributing creators, assignees, and modifiers (users or agents):

```json
{
  "type": "agent",
  "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "name": "Research Agent"
}
```

- Supported fields:
  - `type`: `"user"` or `"agent"` (string, required).
  - `id`: Standard 36-character hyphenated UUID string referencing the registered agent or user (required).
  - `name`: Optional human-readable display name (string, optional).

- Database mapping:
  - In PostgreSQL, discrete nullable foreign-key columns are maintained (e.g., `assigned_agent_id` vs. `assigned_user_id`, and `created_by_agent_id` vs. `created_by_user_id`).
  - Exactly one of the corresponding user or agent foreign-key columns is populated.
  - The application service layer validates that the referenced entity exists and that the attribution type matches the referenced entity.

- Security boundary:
  - The Attribution object is a data representation, not an authentication mechanism. It must not be treated as cryptographic proof of identity. Authentication and authorization are addressed separately in future security enhancements.

**Rationale:** Reconciles differences between flat strings (e.g. `"assigned_to": "Research Agent"` in Task Management) and dictionary structures (in Notes Management), creating a predictable, unambiguous contract for AI agents while preserving relational referential integrity in PostgreSQL. Resolves OPEN-005.

**Alternatives considered:**
- Flat string names: Ambiguous, cannot reliably distinguish users from agents, lacks foreign key integrity.
- Raw database foreign key columns in MCP: Exposes relational null-pair mechanics to LLMs and complicates tool invocation.

**Implications:** Task assignment (`assigned_to`), task creation (`created_by`), note creation (`created_by`), and note version modification (`changed_by`) consistently use the Attribution object in MCP payloads. Pydantic schemas serialize and validate this structure.

**Date:** 2026-10-30

### DEC-028 — Task deletion policy (Soft Delete)

**Status:** Accepted

**Decision:** Adopt soft deletion for tasks. Add `is_deleted BOOLEAN NOT NULL DEFAULT FALSE` and `deleted_at TIMESTAMPTZ NULL` to the `tasks` table. The `delete_task` MCP tool marks the task as deleted (`is_deleted = TRUE`, `deleted_at = NOW()`) rather than physically removing the row. All standard task queries, listings (`get_tasks`), keyword searches (`search_tasks`), and MCP resources (`tasks://all`, `tasks://pending`, etc.) exclude soft-deleted tasks by default (`is_deleted = FALSE`). Task dependency relationships and historical references are preserved. No permanent deletion tool is introduced in the initial implementation.

**Rationale:** In a multi-agent system where autonomous LLM agents execute tool operations, physical row deletion presents high risks of permanent data loss due to hallucination or misinterpretation. Soft deletion preserves full auditability, prevents breaking dependency graphs unexpectedly, and allows safe recovery. Resolves OPEN-006.

**Alternatives considered:**
- Hard deletion: Simple, but permanent and risks irrecoverable data loss.
- Status transition to `cancelled` only: Does not distinguish intentionally deleted tasks from cancelled active tasks.

**Implications:** `tasks` table includes `is_deleted` and `deleted_at`. Service layer applies `is_deleted = FALSE` filter automatically across all default reads.

**Date:** 2026-10-30

### DEC-029 — Note deletion policy (Soft Delete with Version Preservation)

**Status:** Accepted

**Decision:** Adopt soft deletion for notes while preserving full version history. Add `is_deleted BOOLEAN NOT NULL DEFAULT FALSE` and `deleted_at TIMESTAMPTZ NULL` to the `notes` table. The `delete_note` MCP tool marks the note as deleted (`is_deleted = TRUE`, `deleted_at = NOW()`). All historical snapshots in `note_versions` and tag associations in `notes_tags` are preserved. Standard note queries (`get_notes`), keyword searches (`search_notes`), and MCP resources (`notes://all`, `notes://technical`, etc.) exclude deleted notes by default. No permanent deletion tool is provided in the initial implementation.

**Rationale:** Academic research notes represent accumulated knowledge that must not be permanently lost due to accidental deletion by an agent. Preserving version history allows research findings to be inspected or restored. Resolves OPEN-009.

**Alternatives considered:**
- Hard deletion with cascading version purge: Permanently destroys all research history; rejected.
- Detaching version history into an archive table: Unnecessarily complex when a boolean soft-delete flag achieves the same safety.

**Implications:** `notes` table includes `is_deleted` and `deleted_at`. `note_versions` records are retained. Standard note queries filter on `is_deleted = FALSE`.

**Date:** 2026-10-30

### DEC-030 — Task dependency enforcement rules

**Status:** Accepted

**Decision:** Adopt balanced dependency rules:
1. A task can transition to `in_progress` even if its prerequisite dependencies are incomplete.
2. A task cannot transition to `completed` while any prerequisite task in `task_dependencies` remains incomplete (`pending` or `in_progress`).
3. An explicit `force=True` override parameter is provided on `update_task` for exceptional completion cases.
4. When completion is blocked, the service layer returns a clear, descriptive validation error identifying the specific incomplete dependency tasks.

**Rationale:** Enforces workflow integrity and prevents premature task completion by agents, while avoiding deadlocks by allowing preliminary research and preparation work (`in_progress`) to begin in parallel. Resolves OPEN-007.

**Alternatives considered:**
- Blocking `in_progress`: Too rigid; prevents parallel exploration and preparatory work.
- Advisory-only dependencies: Risks autonomous agents marking tasks complete out of sequence without addressing prerequisites.

**Implications:** Task status update logic in the service layer validates dependencies upon `status = 'completed'` requests. Clear error messages list blocking dependencies.

**Date:** 2026-10-30

### DEC-031 — Note version retention policy (Indefinite by Default)

**Status:** Accepted

**Decision:** Adopt indefinite note version retention by default, governed by an application configuration setting `MAX_NOTE_VERSIONS: int = 0` (where `0` denotes unlimited retention). When a note is updated, a new snapshot is created in `note_versions`. If a positive limit is explicitly configured (`MAX_NOTE_VERSIONS > 0`), older versions beyond the limit are pruned in FIFO order upon new version creation. Version retention operates seamlessly with soft deletion (DEC-029), retaining version records when notes are marked deleted.

**Rationale:** Text-based Markdown notes consume minimal storage in PostgreSQL. Maintaining complete revision history is essential for academic research provenance. Configurable retention provides future storage control without requiring database schema changes. Resolves OPEN-008.

**Alternatives considered:**
- Fixed hardcoded limit (e.g. 10 or 20 versions): Unnecessarily discards early revisions and adds arbitrary pruning.
- Database trigger pruning: Harder to configure and test than application-level configuration.

**Implications:** `MAX_NOTE_VERSIONS` added to Pydantic Settings in `mas/config/`. Note service creates version snapshots on update and checks the configured pruning limit.

**Date:** 2026-10-30

### DEC-032 — Workspace scope and supported file operations

**Status:** Accepted

**Decision:** Reconcile workspace layout and boundaries (updating DEC-019 and confirming DEC-020, DEC-021):
1. The workspace directory permanently maintains four subdirectories:
   ```text
   workspace/
   ├── documents/
   ├── reports/
   ├── datasets/
   └── source_code/
   ```
2. File Management MCP tools (`list_files`, `read_file`, `search_files`, `get_file_metadata`) operate read-only within the configured workspace root (`WORKSPACE_ROOT`).
3. Supported file formats for read-only access are: TXT (`.txt`), Markdown (`.md`), JSON (`.json`), CSV (`.csv`), Python (`.py`), and SQL (`.sql`).
4. Agents must not create, modify, rename, move, or delete workspace files through initial MCP tools.
5. Specialized dataset analysis and source-code execution workflows remain deferred to future phases.
6. Path traversal rejection (`..`), symlink escape prevention, and workspace root boundary enforcement are strictly maintained.

**Rationale:** Harmonizes the repository structure defined in `Multi Agent System Project Structure.md` with format requirements in `PROJECT_REQUIREMENTS.md` (FR-032). Providing `datasets/` and `source_code/` gives structured locations for sample CSV data and script files while keeping File Management safely read-only. Resolves OPEN-003.

**Alternatives considered:**
- Removing `datasets/` and `source_code/`: Conflicted with directory structure and format support for `.csv` and `.py`/`.sql`.
- Read/write file tools: Exposes risk of unintended file modification or script execution by agents; deferred to future phases with human approval.

**Implications:** File Management tool suite operates across the workspace tree in read-only mode for the 6 supported file types. Filesystem boundary checks are enforced.

**Date:** 2026-10-30

### DEC-033 — Replace Ollama with Google Gemini API for Research and Task agents

**Status:** Accepted

**Decision:** Replace the Ollama local model runtime (llama3.2:3b) used by the Research Agent and Task Agent with the Google Gemini API, using the same `GOOGLE_API_KEY` and `google-genai` SDK already in use by the orchestrator. Sub-agents support a full multi-model fallback chain (`AGENT_GEMINI_PRIMARY_MODEL`, `AGENT_GEMINI_FALLBACK_MODELS`, `AGENT_GEMINI_MODEL_RETRY_ATTEMPTS`, `AGENT_GEMINI_MODEL_RETRY_DELAY`), with an in-memory health tracker (`AgentModelHealthTracker`) that isolates sub-agent rate limits, transient 503s, and daily quota events from orchestrator models. A legacy single-model configuration (`AGENT_GEMINI_MODEL`) remains supported for backwards compatibility.

**Rationale:** During testing, `llama3.2:3b` frequently produced `OllamaInferenceError: Unexpected error during Ollama inference` failures when attempting structured function-calling for tools like `search_tasks`. A 3-billion parameter model running on CPU with 8 GB RAM is insufficiently capable for reliable JSON tool-call construction with complex schemas (Attribution objects, UUID arrays, enum values). The Gemini API provides native, reliable function-calling, better schema compliance, and no local hardware bottleneck. Both agents already share the same API key as the orchestrator.

**Supersedes:** DEC-009 (Accepted → Superseded), DEC-010 (Proposed → Superseded), DEC-011 (Accepted → Superseded).

**Alternatives considered:**
- Upgrading to a larger local model (e.g., llama3.2:8b or qwen2.5:7b): Would improve tool-calling reliability but still limited by 8 GB RAM, CPU-only inference, and continued maintenance of a local daemon.
- Keeping Ollama but pinning a different model: Rejected — hardware constraints make reliable function-calling difficult at any practical local model size without a GPU.

**Implications:**
- `mas/agents/base.py` rewritten to use `AgentGeminiService` (new `mas/agents/gemini_agent_service.py`) instead of `OllamaService`.
- `mas/agents/task_agent/agent.py` and `mas/agents/research_agent/agent.py` updated — `OllamaService` dependency removed; `AgentGeminiService` injected.
- `mas/config/settings.py` adds `AgentGeminiSettings` (env vars: `AGENT_GEMINI_PRIMARY_MODEL`, `AGENT_GEMINI_FALLBACK_MODELS`, `AGENT_GEMINI_MODEL`, `AGENT_GEMINI_TIMEOUT_SECONDS`, `AGENT_GEMINI_TEMPERATURE`, `AGENT_GEMINI_MODEL_RETRY_ATTEMPTS`, `AGENT_GEMINI_MODEL_RETRY_DELAY`).
- `mas/agents/gemini_agent_service.py` implements resilient multi-model fallback traversal and health tracking for sub-agents.
- `mas/lifecycle.py` updated — Ollama removed from pre-flight checks; `check_ollama_health` retained as an optional utility but not called by `run_preflight_checks`.
- `mas/ollama/` module retained but no longer used by agents. It remains available for optional diagnostics and is not deleted to preserve test coverage.
- `.env.example` updated with agent Gemini model settings and Ollama section commented out.
- All agent unit and integration tests updated to mock `AgentGeminiService` instead of `OllamaService`.
- `PROJECT_REQUIREMENTS.md` technology table updated.

**Date:** 2026-11-02

---

## 10. Deferred Product and Design Decisions

The following decisions remain open. They must be resolved before implementing the affected functionality.

| ID | Decision area | Current status | Why it matters |
|---|---|---|---|
| OPEN-001 | Initial user interface: CLI, web, or both | Deferred | Determines the user interaction layer. |
| OPEN-002 | Internet access for Research Agent | Deferred | Determines whether external search tools are required. |
| OPEN-003 | Read-only or read/write workspace access | Resolved (DEC-032) | File Management is read-only within workspace root. |
| OPEN-004 | Single-user or multi-user support | Deferred | Affects database ownership and access isolation. |
| OPEN-005 | Task assignment to one or multiple assignees | Resolved (DEC-027) | Single assignee via Attribution object. |
| OPEN-006 | Task deletion: permanent or soft delete | Resolved (DEC-028) | Soft delete with is_deleted and deleted_at. |
| OPEN-007 | Task dependency completion rules | Resolved (DEC-030) | Block on complete unless force=True; in_progress allowed. |
| OPEN-008 | Note version retention policy | Resolved (DEC-031) | Indefinite retention by default (MAX_NOTE_VERSIONS=0). |
| OPEN-009 | Note deletion and version recovery | Resolved (DEC-029) | Soft delete with version preservation. |
| OPEN-010 | Human approval for selected agent actions | Deferred | Affects interaction and execution controls. |
| OPEN-011 | PostgreSQL full-text search sufficiency | Deferred | Affects search implementation. |

Do not make irreversible implementation assumptions for these areas without recording the selected decision.

---

## 11. Decision Change Procedure

When a technical or architectural decision needs to change:

1. Identify the existing decision ID.
2. Explain why the current decision is no longer suitable.
3. Describe the proposed replacement.
4. Consider effects on requirements, architecture, database design, MCP specifications, implementation, and tests.
5. Obtain project-owner approval before changing an accepted decision.
6. Mark the old entry as `Superseded`.
7. Add a new decision entry with a new ID.
8. Update affected documentation and implementation.

Do not silently overwrite historical decisions.

## 12. Decision Log Template

Use this template for future decisions:

```markdown
### DEC-XXX — Decision title

**Status:** Proposed / Accepted / Deferred / Superseded

**Decision:** What was decided?

**Rationale:** Why was this selected?

**Alternatives considered:** What other options were evaluated?

**Implications:** What changes or constraints follow from this decision?

**Date:** YYYY-MM-DD
```

---

**End of document**
