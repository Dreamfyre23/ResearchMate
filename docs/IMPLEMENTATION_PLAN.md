# ResearchMate — Implementation Plan

**Document version:** 0.1  
**Status:** Initial Draft  
**Project name:** ResearchMate

---

## 1. Purpose

This document defines the proposed development sequence for ResearchMate. It divides implementation into phases, identifies the main activities and dependencies, and establishes completion criteria for each phase.

The implementation should proceed incrementally. Each phase should produce a working, testable result before dependent phases begin.

This document describes the development roadmap. Detailed functional requirements, database structures, and MCP tool/resource specifications are maintained in their respective documents.

## 2. Implementation Principles

1. **Build incrementally:** Implement and test one component at a time.
2. **Validate integrations early:** Test PostgreSQL, Ollama, Gemini, and MCP connections independently before combining them.
3. **Keep components modular:** MAS, the client-side MCP host, and the server-side MCP server should have clear responsibilities and interfaces.
4. **Avoid premature infrastructure:** Do not introduce Kubernetes, distributed message brokers, or enterprise observability infrastructure during the initial implementation.
5. **Use configuration rather than hardcoding:** Store environment-specific settings and credentials outside source code.
6. **Test each phase:** Add tests alongside implementation rather than postponing all testing until the end.
7. **Preserve decisions:** Follow the approved project documents. Record significant changes in `DECISIONS.md`.

## 3. Development Phases

### Phase 0 — Project Initialization

**Objective:** Establish the project repository and Python development environment.

Activities:
- Create the `ResearchMate` project directory.
- Initialize Git.
- Create and activate a Python 3.15.2 virtual environment.
- Create the initial project directory structure.
- Add `.gitignore`, `.env.example`, `requirements.txt`, and `README.md`.
- Add the project documentation under `docs/`.
- Configure environment-variable loading and application settings.
- Verify that secrets and the virtual environment are excluded from Git.

Deliverables:
- Initialized project repository.
- Working Python virtual environment.
- Initial configuration and documentation files.

Completion criteria:
- Python runs from the project virtual environment.
- Dependencies can be installed from the project dependency file.
- Git does not track `.env` or `.venv/`.
- The project structure is in place.

### Phase 1 — Foundation and Configuration

**Objective:** Create the common application foundation used by the other components.

Activities:
- Establish application configuration using environment variables and Pydantic Settings.
- Define common logging configuration.
- Define shared error-handling conventions.
- Add configuration for PostgreSQL, Ollama, Gemini, and MCP server connection settings.
- Add basic health or startup checks for required dependencies.
- Separate development configuration from application logic.

Deliverables:
- Centralized configuration module.
- Common logging and error-handling utilities.
- Dependency connectivity checks.

Completion criteria:
- Application settings load from the environment.
- Missing or invalid required settings produce clear errors.
- API keys and passwords are not written into source code or logs.

### Phase 2 — PostgreSQL Database Foundation

**Objective:** Establish persistent storage for ResearchMate.

Activities:
- Create the ResearchMate PostgreSQL database.
- Implement database connection management.
- Configure SQLAlchemy and Psycopg.
- Define the initial database models based on `DATABASE_DESIGN.md`.
- Configure database migrations.
- Implement and test database initialization.
- Add basic database connectivity checks.

Deliverables:
- Working PostgreSQL database connection.
- Initial SQLAlchemy models.
- Migration setup.
- Database initialization and connectivity tests.

Completion criteria:
- The application can connect to PostgreSQL.
- Migrations can create and update the required schema.
- Database operations can be tested independently of the agents and MCP server.

### Phase 3 — Server-Side MCP Foundation

**Objective:** Implement the independently runnable MCP server and verify MCP communication.

Activities:
- Create the server-side MCP application using the official Python MCP SDK.
- Configure Streamable HTTP transport.
- Implement server startup and shutdown.
- Add basic server status and diagnostic capabilities.
- Verify MCP initialization and capability discovery.
- Verify that an MCP client can connect and list the server's available tools and resources.
- Keep the server process independent of the MAS process.

Deliverables:
- Independently runnable server-side MCP server.
- Streamable HTTP endpoint.
- Initial MCP connection and discovery tests.

Completion criteria:
- The MCP server starts and stops cleanly.
- An MCP client can establish a connection.
- MCP capability discovery works.
- The server can be tested without starting the MAS.

### Phase 4 — MCP System and Agent Information

**Objective:** Implement the read-oriented system and agent information capabilities.

Activities:
- Implement the System Information resources.
- Implement the Agent Information tools and resources.
- Connect required information to application configuration, database state, and MAS agent registration data where applicable.
- Ensure system information does not expose secrets, credentials, or database connection strings.
- Add tests for normal and unavailable-service conditions.

Deliverables:
- System Information MCP capabilities.
- Agent Information MCP capabilities.
- Tests for the implemented capabilities.

Completion criteria:
- System status and statistics return accurate information.
- Agent information reflects the registered agents and their current application-reported status.
- Sensitive configuration values are not exposed.

### Phase 5 — Task Management MCP

**Objective:** Implement task storage and all Task Management MCP capabilities.

Activities:
- Implement task database models and migrations according to `DATABASE_DESIGN.md`.
- Implement soft deletion for tasks using `is_deleted` and `deleted_at` fields (DEC-028).
- Implement the six Task Management tools:
  - `create_task`
  - `get_task`
  - `get_tasks`
  - `update_task`
  - `delete_task` (soft delete)
  - `search_tasks`
- Implement the five Task Management resources.
- Validate task status, priority, and assignment rules using unified Attribution objects (DEC-027).
- Implement task dependency enforcement (DEC-030): allow transition to `in_progress` with incomplete dependencies; strictly block transition to `completed` if any prerequisite task remains incomplete unless an explicit `force=True` override is provided; return clear errors listing incomplete dependencies.
- Ensure normal task retrieval, listing, searching, and resources exclude soft-deleted tasks by default, while preserving dependencies and historical records.
- Add input validation and consistent error responses.
- Add unit and MCP integration tests.

Deliverables:
- Task Management database operations.
- Six MCP tools and five MCP resources.
- Automated tests.

Completion criteria:
- Task creation, retrieval, listing, updating, soft deletion, and searching work correctly.
- Task resources return the expected filtered task collections, excluding deleted tasks by default.
- Task completion is blocked when dependencies are incomplete, and permitted when dependencies are satisfied or overridden via `force=True`.
- Invalid inputs and invalid dependency operations are handled safely.
- Database changes persist across application restarts.

### Phase 6 — Notes Management MCP

**Objective:** Implement persistent notes and all Notes Management MCP capabilities.

Activities:
- Implement note database models and migrations according to `DATABASE_DESIGN.md`.
- Implement soft deletion for notes using `is_deleted` and `deleted_at` fields, preserving historical records in `note_versions` and tag associations (DEC-029).
- Implement the six Notes Management tools:
  - `create_note`
  - `get_note`
  - `get_notes`
  - `update_note`
  - `delete_note` (soft delete)
  - `search_notes`
- Implement the four Notes Management resources.
- Support the agreed note categories, tags, and Markdown content.
- Implement note version retention (DEC-031): retain versions indefinitely by default, governed by configurable `MAX_NOTE_VERSIONS: int = 0` (0 = unlimited; FIFO pruning when a positive integer is configured).
- Ensure normal note retrieval, listing, searching, and resources exclude soft-deleted notes by default.
- Add unit and MCP integration tests.

Deliverables:
- Notes Management database operations.
- Six MCP tools and four MCP resources.
- Automated tests.

Completion criteria:
- Note creation, retrieval, listing, updating, soft deletion, and searching work correctly.
- Soft deletion preserves note version history and tags while hiding notes from default queries and resources.
- Category and tag filtering works as specified.
- Version history behaves according to the indefinite retention policy (with configurable pruning ceiling).
- Note resources return the expected collections.

### Phase 7 — File Management MCP

**Objective:** Implement controlled access to files in the ResearchMate workspace.

Activities:
- Establish the workspace directory structure with four permanent subdirectories: `documents/`, `reports/`, `datasets/`, and `source_code/` (DEC-032).
- Implement the four File Management tools:
  - `list_files`
  - `read_file`
  - `search_files`
  - `get_file_metadata`
- Implement filename and supported-content search.
- Restrict file management to strictly read-only operations on TXT, MD, JSON, CSV, PY, and SQL files (defer specialized dataset analysis and code execution workflows).
- Restrict all file operations to the configured workspace root.
- Validate paths and handle traversal attempts, symbolic links, missing files, and unsupported file types safely.
- Apply file-size and search-result limits.
- Add unit and MCP integration tests.

Deliverables:
- Workspace directory with four standard subdirectories (`documents/`, `reports/`, `datasets/`, `source_code/`).
- Four File Management MCP tools (read-only).
- File-access validation and automated tests.

Completion criteria:
- Agents can list, read, search, and inspect supported workspace files across the designated directories.
- Operations remain strictly read-only.
- Attempts to access files outside the workspace are rejected.
- Unsupported files and malformed paths are handled safely.
- File operations do not expose arbitrary local-drive contents.

### Phase 8 — Client-Side MCP Host

**Objective:** Implement the MCP client management layer used by the MAS.

Activities:
- Implement MCP client connections using the official Python MCP SDK.
- Configure connections to the server-side MCP endpoint.
- Implement connection lifecycle management.
- Discover and retrieve available tools and resources.
- Provide a controlled interface for the MAS to invoke tools and read resources.
- Handle connection failures, timeouts, and server restarts.
- Test the client-side host independently from the agents.

Deliverables:
- Client-side MCP host.
- MCP client connection management.
- Tool invocation and resource retrieval interfaces.
- Independent client integration tests.

Completion criteria:
- The client-side host can connect to the server-side MCP server.
- It can discover tools and resources.
- It can invoke tools and retrieve resources.
- Connection failures are reported and handled without crashing the host.

### Phase 9 — Local AI Agents

**Objective:** Implement the Research Agent and Task Agent using Ollama.

Activities:
- Configure the shared Ollama endpoint and selected local model.
- Implement a common agent interface and agent configuration.
- Implement the Research Agent's role, instructions, and request handling.
- Implement the Task Agent's role, instructions, and request handling.
- Make MCP tools and resources available to agents through the intended client-side MCP host.
- Validate model outputs before passing them to tools.
- Handle malformed model output, unavailable models, and tool errors.
- Add tests using mocked model and MCP responses where appropriate.

Deliverables:
- Research Agent.
- Task Agent.
- Shared agent interface and configuration.
- Agent-level tests.

Completion criteria:
- Both agents can communicate with the local Ollama model.
- Each agent can perform its intended responsibilities.
- Agents can discover and use only the MCP capabilities made available through the application.
- Invalid model-generated tool arguments are rejected or safely handled.

### Phase 10 — Gemini-Powered Orchestrator

**Objective:** Implement the orchestrator that receives user requests and coordinates agents.

Activities:
- Integrate the Gemini API using the `google-genai` SDK.
- Define the orchestrator's instructions and agent-selection behavior.
- Provide the orchestrator with agent descriptions and capabilities.
- Implement request classification and delegation.
- Implement delegation input and output contracts.
- Collect agent responses and produce a final user-facing response.
- Handle unavailable agents, API errors, timeouts, and partial failures.
- Avoid exposing API keys or sensitive configuration in prompts and logs.
- Add unit and integration tests.

Deliverables:
- Gemini-powered orchestrator.
- Agent selection and delegation logic.
- Error and timeout handling.
- Orchestrator tests.

Completion criteria:
- The orchestrator can receive a user request.
- It can select and invoke the appropriate agent.
- It can process the agent's response and return a coherent result.
- Failures in one agent do not unexpectedly terminate the entire application.

### Phase 11 — End-to-End Integration

**Objective:** Connect the independently implemented components into a working ResearchMate system.

Activities:
- Integrate the user interaction entry point with the orchestrator.
- Connect the orchestrator to the Research Agent and Task Agent.
- Connect agents to the client-side MCP host.
- Connect the client-side MCP host to the server-side MCP server.
- Verify database-backed tools and workspace-backed file tools.
- Test complete user-request flows.
- Verify that the MAS, client-side MCP host, and server-side MCP server can be started and tested independently.
- Document startup order, configuration, and common troubleshooting steps.

Deliverables:
- Integrated ResearchMate application.
- End-to-end test scenarios.
- Updated setup and usage documentation.

Completion criteria:
- A user can submit a request and receive a result through the complete system.
- Agent delegation and MCP tool/resource access work end to end.
- Database and workspace operations work through MCP.
- The major components can be run and diagnosed independently.

### Phase 12 — Stabilization and Initial Release

**Objective:** Improve reliability and prepare the initial working version for regular use.

Activities:
- Run the complete unit, integration, and end-to-end test suites.
- Fix defects found during testing.
- Test invalid inputs and failure scenarios.
- Review file-system boundaries and secret handling.
- Review dependency versions and remove unused dependencies.
- Improve logs and error messages.
- Finalize README setup and usage instructions.
- Record known limitations and deferred features.

Deliverables:
- Tested initial version of ResearchMate.
- Updated documentation.
- Known limitations and future-work list.

Completion criteria:
- Critical and high-priority test cases pass.
- No known critical defects remain in the initial feature set.
- A fresh development environment can be configured by following the README.

## 4. Later Enhancements — Deferred

These enhancements are intentionally outside the initial implementation sequence. They should be planned after the basic system is working.

### 4.1 Observability
- OpenTelemetry instrumentation.
- Agent, model, tool, and MCP interaction traces.
- Centralized telemetry collection and storage.
- Agent activity and delegation visualization.

### 4.2 Agent Identity and Security
- Agent identity and authentication.
- Authorization and least-privilege access.
- Delegation-chain tracking.
- Session lifecycle management and orphaned-session handling.
- Policy enforcement and security monitoring.
- Evaluation of agent gateway solutions.

### 4.3 Additional Capabilities
- Internet research and external search integration.
- PDF, DOCX, and XLSX parsing.
- Dataset analysis.
- Source-code analysis.
- Additional specialized agents.
- User interface enhancements.
- Multi-user support and user-specific data separation.

Each enhancement should have its own requirements, design, and test updates before implementation.

## 5. Cross-Phase Testing Strategy

Testing should be performed throughout development.

| Test level | Purpose |
|---|---|
| Unit tests | Verify individual functions, models, validators, and business rules. |
| Database tests | Verify persistence, constraints, migrations, and transactions. |
| MCP integration tests | Verify server startup, discovery, tool invocation, and resource retrieval. |
| Agent tests | Verify agent instructions, model integration, output validation, and tool use. |
| Orchestrator tests | Verify request interpretation, agent selection, delegation, and response handling. |
| End-to-end tests | Verify complete user workflows across the MAS, MCP, and database. |
| Security tests | Verify workspace restrictions, secret handling, invalid inputs, and access boundaries. |

Tests that call external services such as Gemini should support mocking so that the normal test suite does not require API usage.

## 6. Development Order and Dependencies

The intended high-level dependency sequence is:

1. Project initialization and configuration.
2. PostgreSQL foundation.
3. Server-side MCP foundation.
4. MCP capability implementation.
5. Client-side MCP host.
6. Local AI agents.
7. Gemini orchestrator.
8. End-to-end integration.
9. Stabilization and initial release.
10. Deferred observability and security enhancements.

Some work can overlap after its prerequisites are stable. For example, agent prompt design and test-case preparation can proceed while MCP capabilities are being implemented. However, integration should use stable, documented interfaces.

## 7. Implementation Rules for Coding Agents

When Claude, Antigravity, or another coding agent implements ResearchMate:

1. Read `README.md`, `AGENTS.md`, and the relevant documents in `docs/` before changing code.
2. Follow the approved project structure and technology choices.
3. Implement only the current phase unless explicitly instructed otherwise.
4. Do not silently change requirements, MCP tool names, resource identifiers, or public interfaces.
5. Do not add major frameworks or infrastructure without approval.
6. Add or update tests for every implemented feature.
7. Run relevant tests and report their actual results.
8. Do not claim a feature is complete if it has only been stubbed or mocked.
9. Keep secrets out of source code, logs, and committed files.
10. Update documentation when implementation changes an established behavior or interface.
11. Record significant architectural or technology changes in `DECISIONS.md`.
12. At the end of each phase, report completed work, files changed, tests executed, test results, known issues, and the next recommended step.

## 8. Progress Tracking

Track each phase using one of these statuses:

- `NOT_STARTED`
- `IN_PROGRESS`
- `BLOCKED`
- `COMPLETED`

A phase should be marked `COMPLETED` only when its completion criteria have been met and the relevant tests have passed.

---

**End of document**
