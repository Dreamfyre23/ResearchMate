# Agent Information

## 1. Purpose and Scope

The Agent Information component provides information about the AI agents
registered in ResearchMate. It allows the orchestrator and other
authorized components to discover registered agents, inspect their
configuration and capabilities, check their operational status, and
retrieve tasks assigned to them.

This component describes **application-level agent records and
operational information only**.

It does not provide cryptographic agent identity, prove the identity of
an incoming connection, authenticate agents, enforce authorization, or
track delegation between agents. Those concerns belong to a separate
security design.

## 2. MCP Tools

The initial Agent Information MCP server will expose the following three
tools.

  ------------------------------------------------------------------------
                           No. Tool                  Purpose
  ---------------------------- --------------------- ---------------------
                             1 `get_agent_info`      Retrieve information
                                                     about one registered
                                                     agent using its
                                                     identifier.

                             2 `list_agents`         Retrieve registered
                                                     agents, optionally
                                                     filtered by role or
                                                     status.

                             3 `get_agent_tasks`     Retrieve tasks
                                                     assigned to a
                                                     particular agent,
                                                     optionally filtered
                                                     by task status.
  ------------------------------------------------------------------------

### 2.1 `get_agent_info`

Retrieves the registered information for one agent.

Example input:

``` json
{
  "agent_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479"
}
```

Example output:

``` json
{
  "agent_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "name": "Research Agent",
  "code": "AGENT-001",
  "role": "research",
  "description": "Responsible for researching information and preparing summaries.",
  "model": "llama3.2:3b",
  "provider": "ollama",
  "status": "active"
}
```

Expected behavior: - Return the registered record matching the supplied
`agent_id`. - Return a clear not-found result if the identifier is not
registered. - Use the same field names and value conventions as the
Agent Information data model.

### 2.2 `list_agents`

Retrieves registered agents. Callers may provide filters to narrow the
result.

Example input:

``` json
{
  "role": "research",
  "status": "active"
}
```

Expected behavior: - Support optional filters such as `role` and
`status`. - When no filters are supplied, return all registered agents
subject to the configured result limit. - Return an empty collection
when no agents match. - Define ordering and pagination or result limits
during implementation.

### 2.3 `get_agent_tasks`

Retrieves tasks assigned to a specified agent.

Example input:

``` json
{
  "agent_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "in_progress"
}
```

Expected behavior: - Validate that the supplied agent identifier refers
to a registered agent. - Retrieve tasks assigned to that agent. -
Optionally filter tasks by status. - Use the Task Management data model
and status values rather than defining a separate task representation. -
Return an empty collection when the agent has no matching tasks.

## 3. Agent Data Model

The proposed initial agent record contains the following fields.

  ----------------------------------------------------------------------------------------------------------------------------
  Field                   Description                                                 Example
  ----------------------- ----------------------------------------------------------- ----------------------------------------
  `agent_id`              Unique primary identifier for the registered agent          `f47ac10b-58cc-4372-a567-0e02b2c3d479`
                          (standard 36-character hyphenated UUID string; DEC-026).    

  `name`                  Human-readable agent name.                                  `Research Agent`

  `code`                  Optional human-readable display code (distinct from         `AGENT-001`
                          the UUID primary key).                                      

  `role`                  Main responsibility of the agent.                           `research`

  `description`           Description of the agent's purpose and responsibilities.    `Researches technical information and prepares summaries.`

  `model`                 Model configured for the agent.                             `llama3.2:3b`

  `provider`              Provider or runtime hosting the model.                      `ollama`

  `status`                Current operational status reported by the MAS.             `active`

  `capabilities`          Operations the agent is configured to perform and the       `["search_notes", "read_file"]`
                          MCP interfaces it is allowed to use.                        

  `created_at`            Timestamp at which the agent was registered.                `2026-10-30T10:30:00Z`

  `last_active_at`        Timestamp of the agent's most recent reported activity.     `2026-10-30T11:00:00Z`
  ----------------------------------------------------------------------------------------------------------------------------

### 3.0 Identifier format

In accordance with DEC-026:
- All agent primary identifiers (`agent_id`) must be standard 36-character hyphenated UUID strings (e.g. `"f47ac10b-58cc-4372-a567-0e02b2c3d479"`), matching PostgreSQL's native `UUID` primary key (`agents.agent_id UUID`).
- Human-readable agent codes such as `AGENT-001` are optional display identifiers only, strictly separate from the UUID primary key.
- MCP tool parameters (`get_agent_info`, `get_agent_tasks`) and MCP resource responses expect and serialize UUID strings.

### 3.1 Agent roles

The initial set of roles is:

-   `orchestrator`
-   `research`
-   `task_management`
-   `data_analysis`
-   `custom`

These roles describe an agent's application-level responsibility. They
are not security roles and must not be treated as authorization rules.

### 3.2 Agent statuses

The initial supported statuses are:

-   `active` --- The agent is registered and currently available.
-   `inactive` --- The agent is registered but not currently running or
    available.
-   `busy` --- The agent is currently processing work.
-   `error` --- The agent has reported an operational error or is in an
    error state.

The MAS is responsible for reporting status changes. The MCP server
should not assume that an agent is active merely because its
registration record exists.

Status definitions should be applied consistently. In particular, the
implementation should define how stale status information is detected,
such as when an agent stops responding without reporting that it has
become inactive.

### 3.3 Capabilities

Capabilities should describe both:

1.  **Functional capabilities:** The types of work the agent is designed
    to perform, such as research, task management, or data analysis.
2.  **MCP access capabilities:** The MCP tools and resources the agent
    is configured to use, such as `search_notes`, `read_file`, or
    `tasks://pending`.

The implementation should represent these clearly rather than mixing
descriptive task labels and MCP identifiers into an undocumented list. A
structured representation may distinguish capability names, tool names,
and resource URIs.

A capability record describes configured or declared access. It does not
itself enforce access control. Actual authorization must be implemented
separately.

### 3.4 Registration and timestamps

-   Agents will initially be registered through MAS configuration.
-   The MAS will provide the registered agent information to the Agent
    Information component during initialization.
-   `created_at` records when the agent was first registered.
-   `last_active_at` records the latest activity timestamp reported by
    the MAS.
-   Timestamps should be timezone-aware.
-   The implementation should define whether configuration changes
    update an existing registration or create a new record. Stable
    `agent_id` values should be retained across normal restarts.

## 4. MCP Resources

The Agent Information MCP server will expose these three predefined
resources.

  ----------------------------------------------------------------------------
                           No. Resource URI              Content
  ---------------------------- ------------------------- ---------------------
                             1 `agents://all`            Information about all
                                                         registered agents.

                             2 `agents://active`         Information about
                                                         agents whose reported
                                                         status is `active`.

                             3 `agents://capabilities`   Registered agent
                                                         capabilities,
                                                         including functional
                                                         capabilities and
                                                         configured MCP
                                                         tool/resource access.
  ----------------------------------------------------------------------------

Resources will return information in a consistent JSON representation.
Empty collections should return an empty result rather than an error.

### 4.1 Example: `agents://capabilities`

The following example illustrates the proposed resource representation:

``` json
{
  "agents": [
    {
      "agent_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
      "name": "Research Agent",
      "code": "AGENT-001",
      "functional_capabilities": [
        "research",
        "summarization"
      ],
      "mcp_tools": [
        "search_notes",
        "search_files",
        "read_file"
      ],
      "mcp_resources": [
        "notes://all"
      ]
    },
    {
      "agent_id": "e3b0c442-98fc-1c14-9afb-4c7fa3570222",
      "name": "Task Agent",
      "code": "AGENT-002",
      "functional_capabilities": [
        "task_management"
      ],
      "mcp_tools": [
        "create_task",
        "get_tasks",
        "update_task"
      ],
      "mcp_resources": [
        "tasks://pending"
      ]
    }
  ]
}
```

This is a descriptive view of configured capabilities. It must not be
interpreted as proof that a caller presenting one of these agent IDs is
that agent, or as a substitute for authorization checks.

## 5. Registration and Status Management

The initial implementation will use the following approach:

-   Agent definitions are maintained in MAS configuration.
-   During startup, the MAS registers or synchronizes the configured
    agents with the Agent Information component.
-   The MAS reports operational status changes.
-   The Agent Information component stores and exposes the latest
    reported information.
-   The component should distinguish an agent's registration state from
    its operational status.

A registered agent may be inactive. An active or busy status is
operational information reported by the MAS, not an independently
verified statement about the identity of a network connection.

The implementation should also define how status is refreshed and how
stale records are handled. A heartbeat or periodic status update may be
introduced if needed, but its interval and failure policy are
implementation decisions.

## 6. Initial Scope Decisions

  -------------------------------------------------------------------------
  Topic                   Initial decision        Rationale
  ----------------------- ----------------------- -------------------------
  Agent registration      Register and            Keeps the initial setup
                          synchronize agents      simple and avoids a
                          through MAS             separate manual
                          configuration.          registration workflow.

  Capabilities            Include functional      Allows agents and the
                          capabilities and        orchestrator to discover
                          configured MCP          what each agent is
                          tools/resources.        designed and configured
                                                  to use.

  Status management       Store status updates    Registration alone does
                          reported by the MAS.    not indicate whether an
                                                  agent is currently
                                                  available.

  Identity and            Excluded from this      Cryptographic identity
  authentication          component.              and connection
                                                  authentication require a
                                                  separate security design.

  Authorization           Excluded from this      Declared capabilities are
                          component.              descriptive; enforcement
                                                  belongs in the
                                                  security/access-control
                                                  layer.

  Delegation tracking     Excluded from this      Parent-child agent
                          component.              relationships and
                                                  delegation provenance
                                                  require a separate
                                                  activity-tracking design.
  -------------------------------------------------------------------------

## 7. Design Constraints

-   PostgreSQL is the source of truth for registered agent records and
    their latest reported status.
-   Agent identifiers must be unique, stable, and formatted as standard
    36-character hyphenated UUID strings matching PostgreSQL native UUIDs
    (DEC-026). Human-readable codes (like `AGENT-001`) are optional display
    identifiers only, distinct from the primary key.
-   Roles and statuses must use consistent identifiers.
-   The MAS is responsible for registration synchronization and
    operational status updates.
-   Capability information must distinguish functional capabilities from
    MCP tools and resource URIs.
-   `created_at` and `last_active_at` must use timezone-aware
    timestamps.
-   `get_agent_tasks` must use the Task Management data model and
    assignment relationship.
-   Agent records and capability declarations must not be treated as
    proof of identity or authorization.
-   Errors and unknown agent identifiers must produce clear responses.
-   Resource and tool responses should not expose secrets, API keys,
    credentials, or internal connection strings.

## 8. Items to Finalize Before Implementation

1.  **Capability representation:** Confirm the database and response
    structure for functional capabilities, MCP tool names, and resource
    URIs.
2.  **Registration synchronization:** Define how configuration changes,
    removed agents, and repeated startup registration are handled.
3.  **Status freshness:** Define how often the MAS reports status and
    how stale or unresponsive agents are represented.
4.  **Last activity semantics:** Decide which events update
    `last_active_at` (for example, task execution, status heartbeat, or
    any agent request).
5.  **Task assignment mapping:** Resolved by DEC-027. `get_agent_tasks`
    queries tasks where `assigned_agent_id` (or `assigned_to.id`)
    matches the agent's UUID.
6.  **Result limits:** Define ordering, pagination, and maximum result
    counts for `list_agents` and resource reads.

Cryptographic identity, authentication, authorization, and delegation
tracking are intentionally outside this component's initial scope.

------------------------------------------------------------------------

**Document status:** Proposed initial MCP specification.\
**Component:** Agent Information\
**Persistence:** PostgreSQL\
**Registration source:** MAS configuration\
**Interfaces:** MCP tools and MCP resources
