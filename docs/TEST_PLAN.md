# ResearchMate — Test Plan

**Document version:** 0.1  
**Status:** Initial Draft  
**Project name:** ResearchMate

---

## 1. Purpose

This document defines how ResearchMate will be tested during development and before its initial release.

It identifies the test levels, areas to validate, expected outcomes, failure scenarios, and release criteria. Tests should be added alongside implementation and run throughout the project rather than being postponed until the end.

Detailed test cases may be expanded as individual features are implemented.

## 2. Testing Objectives

The testing process aims to verify that:

1. Individual application components behave as intended.
2. PostgreSQL operations preserve data integrity.
3. MCP clients and servers communicate correctly.
4. Agents use the intended models and MCP capabilities.
5. The orchestrator delegates requests to appropriate agents.
6. Complete user workflows function across the system.
7. File operations remain within the designated workspace.
8. Failures are handled without unexpected application termination.
9. Configuration and secrets are handled safely.
10. The initial implementation meets the acceptance criteria in `PROJECT_REQUIREMENTS.md`.

## 3. Testing Scope

### 3.1 Included in Initial Testing

- Project configuration and startup.
- PostgreSQL connectivity, models, constraints, and migrations.
- Task Management MCP tools and resources.
- Notes Management MCP tools and resources.
- File Management MCP tools.
- Agent Information MCP tools and resources.
- System Information MCP resources.
- Client-side MCP host and server-side MCP server.
- Research Agent and Task Agent.
- Gemini-powered orchestrator.
- Agent delegation and complete user workflows.
- Error handling, logging, and workspace access restrictions.

### 3.2 Deferred Testing

The following require separate test plans when those capabilities are introduced:

- Enterprise agent identity and authentication.
- Fine-grained authorization and delegation policies.
- Agent gateway behavior.
- OpenTelemetry instrumentation and telemetry pipelines.
- Advanced threat detection and response.
- Distributed deployment and Kubernetes.
- Multi-user isolation, if multi-user support is added.
- Advanced PDF, DOCX, and XLSX processing.

## 4. Test Environment

The initial test environment is the local development machine.

| Component | Test configuration |
|---|---|
| Operating system | Windows |
| Python | Python 3.15.2 |
| Python environment | Project `.venv` |
| Local LLM runtime | Ollama |
| Local model | Llama 3.2 3B, subject to model configuration |
| Cloud LLM | Gemini API |
| Database | PostgreSQL 18 |
| MCP transport | Streamable HTTP |
| Test framework | pytest |
| Async tests | pytest-asyncio |

Tests should use separate test configuration and test data. They must not accidentally modify the developer's normal database or workspace.

## 5. Test Levels

### 5.1 Unit Testing

Purpose: Verify individual functions and components independently.

Examples:
- Input validation.
- Task status and priority validation.
- Note category and tag validation.
- Task dependency cycle detection.
- File path validation.
- Agent selection logic.
- Response parsing and output validation.
- Error mapping and exception handling.

Expected result: Each unit behaves according to its defined contract, including invalid-input cases.

### 5.2 Database Testing

Purpose: Verify database models, relationships, constraints, and persistence.

Examples:
- Creating, retrieving, updating, and deleting records.
- Foreign-key behavior.
- Unique constraints.
- Task dependency relationships.
- Note version creation.
- Tag associations.
- Transaction rollback.
- Migration from an empty database.
- Applying subsequent migrations.

Expected result: Valid operations persist correctly; invalid operations are rejected without leaving inconsistent records.

### 5.3 MCP Integration Testing

Purpose: Verify communication between MCP clients and the server-side MCP server.

Examples:
- Server startup and shutdown.
- Client connection and initialization.
- Tool discovery.
- Resource discovery.
- Tool invocation with valid arguments.
- Tool invocation with invalid arguments.
- Resource retrieval.
- Connection timeout and server-unavailable handling.
- Reconnection after server restart.

Expected result: MCP capabilities are discoverable and behave according to their specifications.

### 5.4 Agent Testing

Purpose: Verify the behavior of the Research Agent and Task Agent.

Examples:
- Agent initialization and model connectivity.
- Agent instructions and role boundaries.
- Request interpretation.
- Selection of an appropriate MCP capability.
- Tool argument generation and validation.
- Handling of tool results.
- Handling malformed model output.
- Handling model unavailability and timeouts.

Expected result: Each agent performs its intended responsibilities and does not treat unvalidated model output as a successful operation.

Model-generated responses can vary. Tests should focus on required behavior and structured contracts rather than expecting identical natural-language wording on every run.

### 5.5 Orchestrator Testing

Purpose: Verify request interpretation, agent selection, delegation, and response handling.

Examples:
- Selecting the Research Agent for research requests.
- Selecting the Task Agent for task-management requests.
- Handling requests that require more than one agent.
- Handling ambiguous or unsupported requests.
- Passing the correct task context to an agent.
- Combining agent results.
- Handling agent errors and partial results.
- Handling Gemini API errors and timeouts.

Expected result: Requests are routed appropriately, and failures are reported clearly.

### 5.6 End-to-End Testing

Purpose: Verify complete workflows from user input through the MAS, MCP, and database.

Examples:
- User submits a request to create a task.
- Orchestrator delegates the request to the Task Agent.
- Task Agent invokes the appropriate MCP tool.
- MCP server writes to PostgreSQL.
- The result is returned to the user.
- User requests a research summary from a workspace document.
- Research Agent reads the document through MCP and produces a summary.
- User creates a note from the research result.
- The note is stored and can later be retrieved.

Expected result: The complete workflow succeeds and produces the expected persistent state and user-facing response.

### 5.7 Security and Boundary Testing

Purpose: Verify basic security boundaries in the initial implementation.

Examples:
- Attempting path traversal outside the workspace.
- Attempting to read unsupported file types.
- Supplying malformed file paths.
- Attempting to access missing files.
- Checking that API keys and database credentials are not exposed in logs or error messages.
- Checking that system information does not reveal secrets or connection strings.
- Supplying invalid tool arguments.
- Checking that database operations use parameterized queries or ORM-safe operations.

Expected result: Unsafe or invalid operations are rejected safely, and sensitive values are not exposed.

## 6. Functional Test Scenarios

### 6.1 Task Management

| ID | Test scenario | Expected result |
|---|---|---|
| TASK-001 | Create a task with valid fields. | Task is stored and returned with an identifier. |
| TASK-002 | Create a task without a required title. | Validation error is returned. |
| TASK-003 | Retrieve an existing task by ID. | Correct task is returned. |
| TASK-004 | Retrieve a nonexistent task. | A clear not-found result is returned. |
| TASK-005 | List all tasks. | Matching task records are returned. |
| TASK-006 | Filter tasks by status. | Only tasks with the requested status are returned. |
| TASK-007 | Update task fields. | Changes persist and `updated_at` is refreshed. |
| TASK-008 | Delete an existing task. | Task is soft-deleted (`is_deleted=True`, `deleted_at` set); excluded from normal queries and resources; task dependencies and history are preserved (DEC-028). |
| TASK-009 | Search tasks. | Relevant matching tasks are returned. |
| TASK-010 | Supply an invalid status or priority. | Invalid value is rejected. |
| TASK-011 | Assign a task to an existing agent. | Assignment is stored correctly using unified Attribution object (DEC-027). |
| TASK-012 | Create a dependency between two tasks. | Dependency is stored correctly. |
| TASK-013 | Create a self-dependency or dependency cycle. | Invalid dependency is rejected. |
| TASK-014 | Retrieve pending task resource. | Only pending tasks are returned. |
| TASK-015 | Transition task to `in_progress` with incomplete dependencies. | Transition is permitted (DEC-030). |
| TASK-016 | Transition task to `completed` with incomplete dependencies (no force). | Transition is blocked with a clear error indicating unsatisfied dependencies (DEC-030). |
| TASK-017 | Transition task to `completed` with incomplete dependencies using `force=True`. | Transition succeeds with explicit override (DEC-030). |

### 6.2 Notes Management

| ID | Test scenario | Expected result |
|---|---|---|
| NOTE-001 | Create a note with valid fields. | Note is stored and returned with an identifier. |
| NOTE-002 | Create a note without a required title. | Validation error is returned. |
| NOTE-003 | Retrieve an existing note. | Correct note is returned. |
| NOTE-004 | Retrieve a nonexistent note. | A clear not-found result is returned. |
| NOTE-005 | List notes. | Matching note records are returned. |
| NOTE-006 | Filter notes by category. | Only notes in the requested category are returned. |
| NOTE-007 | Update a note. | Current content is updated and a previous version is retained in `note_versions` (DEC-029). |
| NOTE-008 | Delete a note. | Note is soft-deleted (`is_deleted=True`, `deleted_at` set); historical versions in `note_versions` and tag associations are preserved; excluded from default listings and resources (DEC-029). |
| NOTE-009 | Search notes. | Relevant matching notes are returned. |
| NOTE-010 | Add and retrieve tags. | Tag associations are stored and returned correctly. |
| NOTE-011 | Retrieve note versions. | Version history is returned in reverse chronological order; indefinite retention by default governed by `MAX_NOTE_VERSIONS` (DEC-031). |
| NOTE-012 | Retrieve a category-specific note resource. | Only matching notes are returned. |
| NOTE-013 | Enforce note version retention under `MAX_NOTE_VERSIONS`. | Indefinite retention when 0; FIFO pruning of oldest historical versions when positive limit set (DEC-031). |

### 6.3 File Management

| ID | Test scenario | Expected result |
|---|---|---|
| FILE-001 | List files in workspace directories. | Only permitted files across the four designated directories (`documents/`, `reports/`, `datasets/`, `source_code/`) are listed (DEC-032). |
| FILE-002 | Read a supported text file. | Correct file content is returned. |
| FILE-003 | Read a nonexistent file. | A clear not-found result is returned. |
| FILE-004 | Search by filename. | Matching filenames are returned. |
| FILE-005 | Search supported file contents. | Matching files or relevant matches are returned. |
| FILE-006 | Retrieve file metadata. | Correct metadata is returned. |
| FILE-007 | Request an unsupported file type. | Operation is rejected or reports the supported-type limitation. |
| FILE-008 | Attempt path traversal outside the workspace. | Access is rejected. |
| FILE-009 | Attempt access through a symbolic link escaping the workspace. | Access is rejected. |
| FILE-010 | Read a file exceeding the configured size limit. | Operation is safely rejected or limited. |
| FILE-011 | Attempt write or file modification operations through File Management. | Rejected; File Management is strictly read-only (DEC-032). |

### 6.4 Agent Information

| ID | Test scenario | Expected result |
|---|---|---|
| AGENT-001 | Retrieve information about a registered agent. | Correct agent details are returned. |
| AGENT-002 | List registered agents. | Registered agents are returned. |
| AGENT-003 | Retrieve active agents. | Only agents reported as active are returned. |
| AGENT-004 | Retrieve agent capabilities. | Correct capability information is returned. |
| AGENT-005 | Retrieve tasks assigned to an agent. | Matching assigned tasks are returned. |
| AGENT-006 | Request an unknown agent. | A clear not-found result is returned. |

### 6.5 System Information

| ID | Test scenario | Expected result |
|---|---|---|
| SYS-001 | Retrieve system status. | Accurate application status is returned. |
| SYS-002 | Retrieve system statistics. | Counts match the underlying application data. |
| SYS-003 | Retrieve available-tools information. | The documented tool overview is returned. |
| SYS-004 | Retrieve server information. | Non-sensitive server information is returned. |
| SYS-005 | Retrieve database information. | Database status and permitted metadata are returned. |
| SYS-006 | Check read-only behavior. | System information operations do not modify application data. |
| SYS-007 | Check sensitive-value exposure. | Credentials and connection strings are not returned. |

## 7. Integration and End-to-End Scenarios

| ID | Scenario | Expected result |
|---|---|---|
| INT-001 | MCP client connects to the server. | Connection initializes successfully. |
| INT-002 | MCP client discovers tools and resources. | Expected capabilities are listed. |
| INT-003 | MCP client invokes a database-backed task tool. | Correct database operation occurs. |
| INT-004 | MCP client invokes a workspace-backed file tool. | Only permitted file access occurs. |
| INT-005 | Task Agent creates a task through MCP. | Task is persisted and result reaches the caller. |
| INT-006 | Research Agent reads a workspace document through MCP. | Document content reaches the agent. |
| INT-007 | Orchestrator delegates a task-management request. | Task Agent is selected and its result is returned. |
| INT-008 | Orchestrator delegates a research request. | Research Agent is selected and its result is returned. |
| INT-009 | MCP server becomes unavailable during a request. | Failure is handled and reported clearly. |
| INT-010 | Ollama becomes unavailable during agent execution. | Agent failure is handled without crashing the MAS. |
| INT-011 | Gemini API returns an error or times out. | Orchestrator reports or handles the failure gracefully. |
| INT-012 | Application components are started independently. | Each component can be started and diagnosed separately. |

## 8. Negative and Failure Testing

The following failure conditions should be tested:

- Missing environment variables.
- Invalid database credentials.
- PostgreSQL unavailable.
- Ollama service unavailable.
- Requested local model not installed.
- Gemini API key missing or invalid.
- Gemini API rate limit or service error.
- MCP server unavailable.
- MCP client timeout.
- Invalid MCP tool arguments.
- Malformed or unexpected model output.
- Database constraint violation.
- File not found or inaccessible.
- Workspace path traversal attempt.
- Unexpected exception during a multi-step operation.

For each scenario, verify that:
- The error is handled at the appropriate component boundary.
- The user receives a useful error message.
- Sensitive information is not exposed.
- The application remains usable where possible.
- Partial database changes are rolled back when a transaction is required.

## 9. Test Data and Isolation

1. Use a dedicated test database, separate from the development database.
2. Use temporary workspace directories for file tests.
3. Use synthetic tasks, notes, agents, and files.
4. Avoid using real API credentials in committed test fixtures.
5. Mock Gemini and Ollama responses in routine unit tests.
6. Run a smaller number of live model integration tests separately.
7. Clean up test data after each test or test session.
8. Do not run destructive tests against the developer's real workspace or database.

## 10. Automation and Tools

| Tool | Purpose |
|---|---|
| `pytest` | Test execution and organization. |
| `pytest-asyncio` | Testing asynchronous application code. |
| `unittest.mock` / `pytest-mock` | Mocking external dependencies where appropriate. |
| SQLAlchemy test sessions | Isolated database tests. |
| Official Python MCP SDK | MCP client/server integration tests. |
| Ruff | Linting and basic code-quality checks. |

Tests should be runnable with documented commands, for example:

```powershell
pytest
pytest tests/unit
pytest tests/integration
ruff check .
```

The exact test directory structure and commands should be updated to match the implementation.

## 11. Test Execution and Defect Tracking

For each test run, record:

- Test identifier.
- Component or feature tested.
- Test environment.
- Expected result.
- Actual result.
- Pass/fail status.
- Defect or issue reference, if applicable.

Suggested defect severity:

| Severity | Meaning |
|---|---|
| Critical | Data loss, unauthorized access, or complete system failure. |
| High | Major feature unavailable or serious incorrect behavior. |
| Medium | Feature partially works or has a significant limitation. |
| Low | Minor defect or usability issue with a workaround. |

A failed test should not be marked as passed merely because the application did not crash.

## 12. Initial Release Exit Criteria

The initial version may be considered ready for release when:

1. All critical and high-priority test cases pass.
2. Core Task Management and Notes Management operations pass.
3. File access boundary tests pass.
4. MCP discovery, tool invocation, and resource retrieval pass.
5. Research Agent and Task Agent integration tests pass.
6. Orchestrator delegation tests pass.
7. End-to-end workflows pass.
8. Database migrations can initialize a clean test database.
9. No known critical security or data-integrity defect remains.
10. Setup and test instructions are documented and reproducible.

Any uncompleted or deferred test areas must be recorded as known limitations.

---

**End of document**
