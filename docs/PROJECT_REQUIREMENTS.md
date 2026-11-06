# ResearchMate — Project Requirements

**Document version:** 0.1  
**Status:** Initial Draft  
**Project name:** ResearchMate

---

## 1. Project Overview

ResearchMate is a multi-agent AI research assistant designed to help students with academic research, knowledge organization, and productivity.

It uses a central orchestrator to understand user requests, delegate tasks to specialized AI agents, and coordinate their responses. Agents can access external capabilities through the Model Context Protocol (MCP).

The system combines locally hosted language models with cloud-based LLM services. It uses PostgreSQL for persistent data storage.

## 2. Project Objectives

The primary objectives are to:

1. Provide students with an AI assistant for academic research and related activities.
2. Divide complex requests into smaller tasks and delegate them to specialized agents.
3. Enable agents to access tools and resources through MCP.
4. Support persistent storage and retrieval of tasks, notes, and other information.
5. Allow agents to work with files in a controlled local workspace.
6. Establish a modular architecture that can accommodate additional agents and capabilities.
7. Provide a foundation for future agent observability, identity management, authorization, and security enhancements.

## 3. Intended Users

The primary users are students who need assistance with:

- Academic research and information gathering.
- Organizing research materials and notes.
- Managing academic tasks and activities.
- Reading and analyzing documents.
- Working with datasets and source code.
- Retrieving previously stored information.

## 4. Core System Components

### 4.1 Multi-Agent System (MAS)

The MAS coordinates interactions between the user, orchestrator, and specialized agents.

**Orchestrator**
- Receives and interprets user requests.
- Determines which agent or agents are appropriate for a request.
- Delegates tasks to specialized agents.
- Collects and combines agent responses.
- Returns the final response to the user.

**Research Agent**
- Assists with academic research.
- Gathers and organizes information.
- Uses available tools and resources to support research activities.
- Produces research-related responses and summaries.

**Task Agent**
- Creates, retrieves, updates, searches, and deletes tasks.
- Helps users organize and track academic activities.
- Uses the Task Management MCP capabilities.

### 4.2 Client-Side MCP Host

The client-side MCP host manages MCP client connections used by the MAS.

Its responsibilities include:
- Establishing connections to MCP servers.
- Discovering available tools and resources.
- Making MCP capabilities accessible to the appropriate agents.
- Managing MCP client sessions and communication.

### 4.3 Server-Side MCP Server

The server-side MCP server exposes the application's tools and resources to MCP clients.

It provides capabilities for:

- Task Management
- Notes Management
- File Management
- Agent Information
- System Information

It interacts with PostgreSQL and the designated local workspace where required.

### 4.4 Database

PostgreSQL provides persistent storage for application data, including tasks, notes, and other information required by the system.

### 4.5 Local Workspace

The workspace is a controlled directory used for files that agents need to access (DEC-032).

Directories:
- `documents/`
- `reports/`
- `datasets/`
- `source_code/`

All four directories are established within `workspace/`. File Management MCP tools operate strictly read-only across the configured workspace root for TXT, MD, JSON, CSV, PY, and SQL files. Specialized dataset analysis and source-code execution workflows remain deferred to future phases.

## 5. Technology Requirements

| Component | Technology |
|---|---|
| Orchestrator LLM | Google Gemini API |
| Research Agent LLM | Google Gemini API (DEC-033) |
| Task Agent LLM | Google Gemini API (DEC-033) |
| Local LLM runtime | Not required (Ollama removed from agent stack — DEC-033) |
| MCP implementation | Official Python MCP SDK |
| MCP transport | Streamable HTTP |
| Database | PostgreSQL |
| Database access | SQLAlchemy and Psycopg |
| Programming language | Python 3.15.2 |
| Configuration | Environment variables and Pydantic Settings |
| Entity identifiers | PostgreSQL native UUID (standard 36-character hyphenated UUID strings in MCP) |

The technology stack should remain modular so that models and services can be replaced or extended later.

## 6. Functional Requirements

### 6.1 User Interaction and Orchestration

- **FR-001:** The system shall accept requests from users.
- **FR-002:** The orchestrator shall interpret user requests and identify the required operations.
- **FR-003:** The orchestrator shall delegate suitable requests to specialized agents.
- **FR-004:** The orchestrator shall collect and present agent responses.
- **FR-005:** The system shall handle agent failures and unsuccessful operations without crashing the entire application.

### 6.2 Agent Management

- **FR-006:** The system shall support multiple specialized agents.
- **FR-007:** Each agent shall have a defined name, role, description, model, and capabilities.
- **FR-008:** The orchestrator shall select agents based on their capabilities.
- **FR-009:** Agents shall be able to access the MCP capabilities made available to them.
- **FR-010:** The system shall maintain information about registered agents and their status.

### 6.3 Task Management

- **FR-011:** Users and authorized agents shall be able to create tasks.
- **FR-012:** Users and authorized agents shall be able to retrieve individual tasks and task lists.
- **FR-013:** Users and authorized agents shall be able to update tasks.
- **FR-014:** Users and authorized agents shall be able to soft-delete tasks, marking them as deleted while preserving dependencies and history (DEC-028).
- **FR-015:** Users and authorized agents shall be able to search tasks.
- **FR-016:** Tasks shall support status and priority values.
- **FR-017:** Tasks shall support assignment to humans or AI agents using the canonical Attribution object (DEC-027).
- **FR-018:** Tasks shall support dependencies on other tasks. A task can enter `in_progress` with incomplete dependencies, but cannot transition to `completed` unless dependencies are satisfied or `force=True` is provided (DEC-030).

### 6.4 Notes Management

- **FR-019:** Users and authorized agents shall be able to create notes with creator attribution (DEC-027).
- **FR-020:** Users and authorized agents shall be able to retrieve individual notes and note lists.
- **FR-021:** Users and authorized agents shall be able to update notes.
- **FR-022:** Users and authorized agents shall be able to soft-delete notes, preserving all historical version records and tag associations (DEC-029).
- **FR-023:** Users and authorized agents shall be able to search notes.
- **FR-024:** Notes shall support categories and tags.
- **FR-025:** Notes shall support Markdown content.
- **FR-026:** The system shall retain previous note versions indefinitely by default, governed by a configurable retention limit (DEC-031).

### 6.5 File Management

- **FR-027:** Agents shall be able to list files in the designated workspace.
- **FR-028:** Agents shall be able to read supported files.
- **FR-029:** Agents shall be able to search for files by name and content.
- **FR-030:** Agents shall be able to retrieve file metadata.
- **FR-031:** File access shall be read-only and restricted to the designated workspace root (DEC-032).
- **FR-032:** The initial implementation shall support TXT, MD, JSON, CSV, PY, and SQL files.
- **FR-033:** PDF, DOCX, and XLSX support may be added in a later phase.

### 6.6 Agent Information

- **FR-034:** The system shall provide information about registered agents.
- **FR-035:** The system shall provide a list of available agents.
- **FR-036:** The system shall provide tasks assigned to a specified agent.
- **FR-037:** The system shall expose information about agent capabilities and status.

### 6.7 System Information

- **FR-038:** The system shall expose its operational status.
- **FR-039:** The system shall provide basic system statistics.
- **FR-040:** The system shall provide information about available tools.
- **FR-041:** The system shall provide basic server and database information.
- **FR-042:** System information capabilities shall be read-only.

## 7. MCP Requirements

The server-side MCP implementation shall expose the following capabilities.

| Category | Tools | Resources |
|---|---:|---:|
| Task Management | 6 | 5 |
| Notes Management | 6 | 4 |
| File Management | 4 | 0 |
| Agent Information | 3 | 3 |
| System Information | 0 | 5 |
| **Total** | **19** | **17** |

The detailed names, descriptions, input parameters, outputs, and resource identifiers shall be defined in the five MCP category specification documents.

The system shall use MCP's native capability discovery mechanisms to discover available tools and resources.

## 8. Non-Functional Requirements

### 8.1 Modularity
- MAS, client-side MCP host, server-side MCP server, and database components should remain logically separated.
- New agents and MCP capabilities should be addable without major changes to existing components.

### 8.2 Reliability
- The system should handle unavailable models, database failures, and MCP connection failures gracefully.
- Errors should be logged with sufficient context for debugging.

### 8.3 Performance
- The system should avoid unnecessary model calls.
- The implementation should account for the limited computing resources of the initial development machine.
- Agents should share the available local Ollama runtime rather than unnecessarily loading multiple model instances.

### 8.4 Maintainability
- Code should be modular and readable.
- Configuration should be separated from application code.
- Dependencies should be documented and managed through the Python virtual environment.

### 8.5 Security
- Secrets such as API keys and database credentials shall be stored outside source code.
- File access shall be restricted to the designated workspace.
- Database access shall use controlled application connections.
- Future security enhancements shall include agent identity, authorization, delegation tracking, and activity monitoring.

## 9. Initial Scope and Exclusions

The initial implementation focuses on building a working local multi-agent research assistant.

The following capabilities are intentionally deferred:

- Enterprise-grade agent identity and authentication.
- Fine-grained authorization and delegation policies.
- Agent gateway deployment.
- OpenTelemetry-based observability.
- Advanced threat detection and response.
- Distributed deployment and Kubernetes.
- Advanced document parsing and multimodal processing.
- Recurring task scheduling.
- External web research integration, unless explicitly added to the initial scope.

These exclusions may be revisited in later development phases.

## 10. Initial Acceptance Criteria

The initial implementation will be considered functionally complete when:

1. The user can submit a request to the MAS.
2. The orchestrator can identify and delegate requests to the appropriate agents.
3. The Research Agent and Task Agent can execute their intended responsibilities.
4. Agents can discover and invoke permitted MCP tools.
5. Agents can retrieve available MCP resources.
6. Task and note operations work correctly with PostgreSQL.
7. File Management tools can safely access supported files within the workspace.
8. Agent Information and System Information capabilities return accurate information.
9. MAS, client-side MCP host, and server-side MCP server can be started and tested independently.
10. Core functionality passes the defined unit and integration tests.

## 11. Open Questions

Status of open questions:

1. **User interface:** Will the initial system use a command-line interface, a web interface, or both? (OPEN-001, Deferred).
2. **External research:** Should the Research Agent initially access the internet, or work only with user-provided files and stored information? (OPEN-002, Deferred).
3. **File operations:** Resolved by DEC-032. Initial access is strictly read-only within the workspace root.
4. **Note versioning:** Resolved by DEC-031. Retain versions indefinitely by default, governed by configurable `MAX_NOTE_VERSIONS`.
5. **Task dependencies:** Resolved by DEC-030. Incomplete dependencies block transition to `completed` unless `force=True` is provided; `in_progress` is permitted.
6. **Human approval:** Should certain agent operations require user confirmation before execution? (OPEN-010, Deferred).

---

**End of document**
