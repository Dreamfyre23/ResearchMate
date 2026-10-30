# Task Management

## 1. Purpose

The Task Management component allows the ResearchMate orchestrator and
authorized agents to create, retrieve, update, search, and delete tasks.
Tasks may be assigned to an AI agent or a human user.

Task records are stored in PostgreSQL. The component exposes task
operations through MCP tools and provides predefined task collections
through MCP resources.

## 2. MCP Tools

The initial Task Management MCP server will expose the following six
tools.

  ------------------------------------------------------------------------
                           No. Tool                  Purpose
  ---------------------------- --------------------- ---------------------
                             1 `create_task`         Create a new task.

                             2 `get_task`            Retrieve one task
                                                     using its unique
                                                     identifier.

                             3 `get_tasks`           Retrieve multiple
                                                     tasks, optionally
                                                     filtered by task
                                                     attributes.

                             4 `update_task`         Update an existing
                                                     task.

                             5 `delete_task`         Delete an existing
                                                     task.

                             6 `search_tasks`        Search tasks using
                                                     keywords.
  ------------------------------------------------------------------------

### Tool behavior guidelines

-   `create_task` should validate required fields and accepted status
    and priority values before creating a record.
-   `get_task` should return a clear not-found result when the supplied
    identifier does not exist.
-   `get_tasks` should support relevant filters, such as status,
    priority, assignee, and due-date range. Exact parameters will be
    defined in the tool specification.
-   `update_task` should modify only the fields supplied by the caller
    and update `updated_at` automatically. When transitioning a task to
    `completed`, it must enforce dependency satisfaction (blocking completion
    if prerequisites are incomplete unless an explicit `force=True` override
    is provided; DEC-030). Transitioning to `in_progress` is permitted even
    if dependencies are incomplete.
-   `delete_task` marks the task as soft-deleted by setting `is_deleted = TRUE`
    and `deleted_at` to the current timestamp (DEC-028). Soft-deleted tasks
    are excluded from normal queries, listings, search, and resources by
    default, while dependencies and historical records are preserved.
    A clear report of the deletion or not-found status is returned.
-   `search_tasks` should search relevant task text, at minimum the
    title and description. Search behavior and matching rules will be
    defined during implementation.

All tools should return structured, predictable results and useful error
information. They should not silently report success when an operation
fails.

## 3. Task Data Model

The proposed initial task record contains the following fields.

  --------------------------------------------------------------------------------------------------------------------------------
  Field                   Description                                                 Example
  ----------------------- ----------------------------------------------------------- ----------------------------------------------------
  `task_id`               Unique task identifier (standard 36-character               `a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d`
                          hyphenated UUID string; DEC-026).                           

  `title`                 Short task title.                                           `Implement MCP server`

  `description`           Detailed explanation of the task.                           `Develop the server-side MCP implementation.`

  `status`                Current task status.                                        `in_progress`

  `priority`              Task priority.                                              `high`

  `assigned_to`           Attribution object representing assigned human user         `{"type": "agent", "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479", "name": "Research Agent"}`
                          or AI agent (DEC-027; optional).                            

  `created_by`            Attribution object representing task creator                `{"type": "agent", "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479", "name": "Research Agent"}`
                          (DEC-027; optional).                                        

  `created_at`            Timestamp at which the task was created.                    `2026-10-30T09:00:00Z`

  `updated_at`            Timestamp of the most recent update.                        `2026-10-30T10:30:00Z`

  `due_date`              Optional task deadline.                                     `2026-11-05`
  
  `is_deleted`            Soft-delete flag (DEC-028; boolean).                        `false`
  
  `deleted_at`            Timestamp when task was soft-deleted (DEC-028; optional).    `null`
  --------------------------------------------------------------------------------------------------------------------------------

### 3.0 Identifier format

In accordance with DEC-026:
- All task identifiers (`task_id`) must be standard 36-character hyphenated UUID strings (e.g. `"a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d"`).
- In PostgreSQL, tasks use the native `UUID` primary key type.
- MCP tool parameters (`get_task`, `update_task`, `delete_task`, etc.) and MCP resource responses serialize and accept UUID strings only.
- Integer identifiers (such as `101`) are not supported.

### 3.1 Status values

The initial supported statuses are:

-   `pending` --- The task has been created but work has not started.
-   `in_progress` --- Work on the task is underway.
-   `completed` --- The task has been completed.
-   `cancelled` --- The task has been cancelled and will not be pursued.

The stored values should use the lowercase identifiers shown above.
Human-readable labels can be formatted separately for display.

### 3.2 Priority values

The initial supported priorities are:

-   `low`
-   `medium`
-   `high`
-   `critical`

### 3.3 Assignment and creator attribution

In accordance with DEC-027:
- Task assignment (`assigned_to`) and creator attribution (`created_by`) use the canonical Attribution object across all MCP tool interfaces and resource representations:
  ```json
  {
    "type": "agent",
    "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "name": "Research Agent"
  }
  ```
- **Supported fields:**
  - `type`: `"user"` or `"agent"` (string, required).
  - `id`: Standard 36-character hyphenated UUID string referencing the registered agent or user (required).
  - `name`: Optional human-readable display name (string, optional).
- **Rules:**
  - Assignment is optional (`assigned_to` may be null or omitted if unassigned).
  - A task is assigned to exactly one entity (an agent or a user).
  - In PostgreSQL, this maps to `assigned_agent_id` or `assigned_user_id` (and `created_by_agent_id` or `created_by_user_id`). Exactly one corresponding foreign-key column is populated when attribution is provided.
  - The application service layer validates that the referenced entity exists and that the attribution type matches.
- **Security distinction:** The Attribution object is a data representation, not an authentication mechanism. It must not be treated as cryptographic proof of identity. Authentication and authorization are addressed separately in future security enhancements.

### 3.4 Timestamps and optional fields

-   `created_at` and `updated_at` should be stored as timezone-aware
    timestamps.
-   `created_at` should be set when the task is created.
-   `updated_at` should be refreshed whenever the task is modified.
-   `due_date` should be optional. If a time-of-day deadline is required
    later, the field can be changed to a timezone-aware timestamp.
-   A completion timestamp can be added later if reporting requirements
    justify it.

### 3.5 Soft deletion fields

In accordance with DEC-028:
-   `is_deleted`: A boolean flag (`false` by default) marking whether a task has been soft-deleted.
-   `deleted_at`: A timezone-aware timestamp set to the current time when a task is deleted (`null` while active).
-   Normal task queries, listings, search, and resources exclude soft-deleted tasks by default (`WHERE is_deleted = FALSE`).
-   Deleting a task preserves task dependency records and historical tracking.
-   Permanent deletion is not supported in the initial implementation.

## 4. MCP Resources

The Task Management MCP server will expose these five predefined
resources.

  ----------------------------------------------------------------------------
                           No. Resource URI              Content
  ---------------------------- ------------------------- ---------------------
                             1 `tasks://all`             All tasks.

                             2 `tasks://pending`         Tasks awaiting
                                                         completion.

                             3 `tasks://in-progress`     Tasks currently being
                                                         worked on.

                             4 `tasks://completed`       Completed tasks.

                             5 `tasks://high-priority`   Tasks with `high` or
                                                         `critical` priority.
  ----------------------------------------------------------------------------

Resources will retrieve their data from PostgreSQL and return it in a
consistent JSON representation. Empty collections should return an empty
result rather than an error.

Resource responses should use the same task field names and value
conventions as the MCP tools. If the number of tasks becomes large,
pagination or bounded results should be considered rather than returning
an unbounded collection.

## 5. Tools and Resources: Why Both Are Needed

`get_tasks` and predefined resources such as `tasks://pending` may
expose overlapping information, but they serve different MCP interaction
patterns.

-   **Tool --- `get_tasks`:** An agent invokes an operation and can
    provide filters or other arguments to shape the result.
-   **Resource --- `tasks://pending`:** An agent reads a known URI to
    retrieve a predefined view of task data.

Both are retained in the initial design so ResearchMate can support and
evaluate MCP tool invocation and resource reading independently. The two
interfaces should share the same underlying query and data definitions
to avoid inconsistent results.

## 6. Initial Scope Decisions

The following are the recommended decisions for the first
implementation.

  -----------------------------------------------------------------------
  Topic                   Initial decision        Rationale
  ----------------------- ----------------------- -----------------------
  Human and agent         Support both.           Tasks may be assigned
  assignment                                      to an AI agent or
                                                  remain assigned to a
                                                  human user.

  Task dependencies       Support dependencies    Some tasks cannot begin
                          between tasks.          or be completed until
                                                  prerequisite tasks are
                                                  complete.

  Recurring tasks         Defer. Support one-time Recurrence introduces
                          tasks initially.        scheduling and
                                                  task-generation
                                                  behavior that is not
                                                  required for the first
                                                  working version.
  -----------------------------------------------------------------------

### 6.1 Task dependencies

A task should be able to depend on another task. For example, Task B may
require Task A to be completed first.

Dependencies are represented in the `task_dependencies` join table separately
from the main task record, supporting zero, one, or multiple dependencies per task.
The schema enforces `CHECK (task_id != depends_on_task_id)` to prevent self-dependencies,
and the application service layer rejects circular dependency chains.

In accordance with DEC-030:
-   **Transition to `in_progress`:** Permitted even if dependencies are incomplete,
    allowing work to commence.
-   **Transition to `completed`:** Strictly blocked if any prerequisite dependency
    remains incomplete, unless the caller explicitly supplies `force=True`.
-   **Error reporting:** When completion is blocked, the tool returns a clear,
    structured error identifying all unsatisfied prerequisite tasks.

### 6.2 Recurring tasks

Recurring tasks are outside the initial implementation scope. The first
version will support one-time tasks only. Recurrence can be introduced
later if a concrete use case requires it.

## 7. Design Constraints

-   PostgreSQL is the source of truth for task records.
-   MCP tools and resources must use consistent field names, status
    values, and priority values.
-   Task identifiers must be unique, stable, and formatted as standard
    36-character hyphenated UUID strings matching PostgreSQL native UUIDs
    (DEC-026).
-   The system must validate status and priority values.
-   Task assignment and creator attribution must use the canonical
    Attribution object (DEC-027), distinguishing human users from AI agents.
-   Task dependency relationships must be stored separately from the
    task record.
-   Task deletion must use soft deletion (`is_deleted`, `deleted_at`), excluding
    deleted tasks from normal queries and resources by default (DEC-028).
-   Task completion transitions must enforce prerequisite dependency completion
    unless an explicit `force=True` override is supplied (DEC-030).
-   Timestamps must be generated and updated consistently.
-   Tool failures and invalid inputs must produce clear error responses.
-   Access control and authorization rules will be specified as part of
    the broader ResearchMate security design; this document does not
    define a complete authorization model.

## 8. Items to Finalize Before Implementation

The following details must be settled in coordination with the database
and implementation specifications:

1.  **Assignee representation:** Resolved by DEC-027 (canonical
    Attribution object mapped to discrete database foreign keys).
2.  **Dependency enforcement:** Resolved by DEC-030 (transition to
    `in_progress` allowed; transition to `completed` blocked unless
    prerequisites are satisfied or explicit `force=True` override is provided).
3.  **Deletion behavior:** Resolved by DEC-028 (soft deletion using `is_deleted`
    and `deleted_at`, preserving dependencies and history).
4.  **Task listing limits:** Define default ordering, pagination, and
    maximum result counts for `get_tasks` and resource reads.
5.  **Search behavior:** Define whether `search_tasks` uses PostgreSQL
    full-text search, substring matching, or both.
6.  **Due-date semantics:** Confirm whether deadlines are date-only or
    can include a time and timezone.

Recurring tasks are intentionally deferred and do not block the initial
implementation.

------------------------------------------------------------------------

**Document status:** Proposed initial MCP specification.\
**Component:** Task Management\
**Persistence:** PostgreSQL\
**Interfaces:** MCP tools and MCP resources
