# System Information

## 1. Purpose and Scope

The System Information component exposes read-only information about the
ResearchMate server-side MCP implementation and its available
functionality.

Unlike Task Management, Notes Management, File Management, and Agent
Information, this component focuses on the operational state and
capabilities of the MCP server rather than individual application
records.

The initial implementation will expose MCP resources only. It will not
provide tools that restart services, change configuration, or modify
database settings.

## 2. MCP Resources

The System Information MCP server will expose five read-only resources.

  -------------------------------------------------------------------------------
                           No. Resource URI                 Purpose
  ---------------------------- ---------------------------- ---------------------
                             1 `system://status`            Provides the current
                                                            operational status of
                                                            the MCP server and
                                                            its database
                                                            dependency.

                             2 `system://statistics`        Provides aggregated
                                                            statistics about
                                                            ResearchMate data and
                                                            registered agents.

                             3 `system://available-tools`   Provides a
                                                            categorized overview
                                                            of the tools exposed
                                                            by the MCP server.

                             4 `system://server-info`       Provides
                                                            non-sensitive server
                                                            information, version
                                                            details, and
                                                            supported MCP
                                                            capabilities.

                             5 `system://database-info`     Provides database
                                                            connection status and
                                                            non-sensitive
                                                            database information.
  -------------------------------------------------------------------------------

Resource contents should be returned in a consistent JSON
representation. Values should reflect the current application state
where practical, rather than being hardcoded examples.

### 2.1 `system://status`

Provides information about the current operational state of the MCP
server and its database dependency.

Example content:

``` json
{
  "server_name": "ResearchMate MCP Server",
  "status": "running",
  "version": "1.0.0",
  "uptime_seconds": 3600,
  "database": {
    "status": "connected",
    "type": "PostgreSQL",
    "version": "18.6"
  }
}
```

Expected behavior: - Report whether the MCP server is running and able
to serve requests. - Provide the server version and uptime when
available. - Report database connectivity separately from the server's
own status. - Avoid reporting the whole system as healthy if a required
dependency is unavailable. - Define a consistent status vocabulary, such
as `running`, `degraded`, and `unavailable`, where appropriate.

The example is illustrative. Exact status values and health criteria
should be finalized during implementation.

### 2.2 `system://statistics`

Provides aggregated information about ResearchMate data and registered
agents.

Example content:

``` json
{
  "tasks": {
    "total": 25,
    "pending": 8,
    "in_progress": 5,
    "completed": 12,
    "cancelled": 0
  },
  "notes": {
    "total": 15
  },
  "files": {
    "total": 20
  },
  "agents": {
    "registered": 3,
    "active": 2,
    "inactive": 1,
    "busy": 0,
    "error": 0
  }
}
```

Expected behavior: - Calculate task counts from the Task Management
records. - Calculate note counts from the Notes Management records. -
Calculate file counts from the configured workspace. - Calculate agent
counts from registered agent records and their latest reported
statuses. - Use consistent definitions for totals and status-specific
counts. - Return a clear error or partial-result indication if a data
source is unavailable; do not silently present incomplete statistics as
complete.

Statistics should be calculated from current database and application
state. File counts should reflect the accessible workspace and should
not require reading file contents.

### 2.3 `system://available-tools`

Provides a categorized, human-readable overview of tools exposed by the
MCP server.

Example content:

``` json
{
  "categories": [
    {
      "name": "Task Management",
      "tools": [
        "create_task",
        "get_task",
        "get_tasks",
        "update_task",
        "delete_task",
        "search_tasks"
      ]
    },
    {
      "name": "Notes Management",
      "tools": [
        "create_note",
        "get_note",
        "get_notes",
        "update_note",
        "delete_note",
        "search_notes"
      ]
    },
    {
      "name": "File Management",
      "tools": [
        "list_files",
        "read_file",
        "search_files",
        "get_file_metadata"
      ]
    },
    {
      "name": "Agent Information",
      "tools": [
        "get_agent_info",
        "list_agents",
        "get_agent_tasks"
      ]
    }
  ]
}
```

Expected behavior: - Describe the tools actually registered by the MCP
server. - Group tools by their functional category. - Keep the overview
synchronized with the server's registered tool set. - Do not include
tools that are merely planned but are not currently available.

**MCP distinction:** MCP already defines native tool discovery through
`tools/list`. The `system://available-tools` resource is an additional
categorized overview for convenient inspection. It does not replace or
override native MCP discovery.

### 2.4 `system://server-info`

Provides non-sensitive information about the MCP server implementation.

Suggested content:

``` json
{
  "server_name": "ResearchMate MCP Server",
  "version": "1.0.0",
  "protocol_transport": "Streamable HTTP",
  "supported_capabilities": [
    "tools",
    "resources"
  ]
}
```

Expected behavior: - Report the server name and application version. -
Describe the configured transport and supported MCP capabilities. -
Report only information intended for clients to see. - Avoid exposing
internal filesystem paths, environment variables, secrets, or
unnecessary implementation details.

The exact capability list should reflect what the server actually
supports, not simply what it plans to support.

### 2.5 `system://database-info`

Provides basic, non-sensitive information about the configured database
dependency.

Suggested content:

``` json
{
  "status": "connected",
  "database_type": "PostgreSQL",
  "database_version": "18.6"
}
```

Expected behavior: - Report whether the application can connect to its
configured database. - Provide the database type and version when
available. - Avoid returning database credentials, passwords, connection
strings, host details, or other sensitive configuration. - Distinguish
an unavailable database from an MCP server failure.

This resource should provide operational information, not unrestricted
database inspection or administrative access.

## 3. MCP Tools

The System Information component will expose **no additional MCP tools**
initially.

All five resources are read-only. The initial implementation will not
provide operations to: - Restart or stop the MCP server. - Change server
configuration. - Modify database settings. - Execute arbitrary database
queries. - Perform administrative operations.

Native MCP operations such as `tools/list` remain part of MCP protocol
discovery; they are not additional application-specific System
Information tools.

## 4. Data Sources and Consistency

System Information aggregates data from several parts of ResearchMate.

  -----------------------------------------------------------------------
  Information                         Source
  ----------------------------------- -----------------------------------
  Server status, version, and uptime  MCP server runtime and application
                                      configuration

  Database status and version         Database connection and PostgreSQL
                                      server

  Task statistics                     Task Management records in
                                      PostgreSQL

  Note statistics                     Notes Management records in
                                      PostgreSQL

  File statistics                     Configured workspace filesystem

  Agent statistics                    Agent Information records

  Available tools                     Tools registered with the MCP
                                      server

  Server capabilities and transport   MCP server configuration and
                                      implementation
  -----------------------------------------------------------------------

The implementation should avoid maintaining duplicate hardcoded
inventories where the information can be derived from the actual
registered components.

For aggregated statistics, the implementation should define whether
counts are calculated on every resource read or cached briefly. Initial
implementation can favor straightforward queries and correctness;
caching can be introduced if performance measurements justify it.

## 5. Security and Information Disclosure

System Information is read-only, but its output can still reveal
operational details.

The following information must not be exposed: - API keys, passwords,
tokens, or credentials. - Database connection strings. - Environment
variable values containing secrets. - Private keys or authentication
material. - Sensitive internal filesystem paths. - Arbitrary database
query results.

Only information needed by authorized ResearchMate clients should be
returned. The broader authorization policy is outside this component's
scope and must be defined separately.

## 6. Initial Scope Decisions

  -----------------------------------------------------------------------
  Topic                   Initial decision        Rationale
  ----------------------- ----------------------- -----------------------
  MCP resources           Five resources.         Covers server status,
                                                  statistics, tool
                                                  overview, server
                                                  details, and database
                                                  details.

  MCP tools               None.                   System information
                                                  should remain read-only
                                                  initially.

  Statistics              Derived from current    Avoids stale or
                          database and            manually maintained
                          application state.      counts.

  Tool discovery          Provide a categorized   Makes the server's
                          overview in addition to functionality easier to
                          native `tools/list`.    inspect without
                                                  replacing MCP
                                                  discovery.

  Sensitive configuration Never expose secrets or Prevents information
                          connection strings.     disclosure through
                                                  diagnostic resources.
  -----------------------------------------------------------------------

## 7. Design Constraints

-   All System Information resources must be read-only.
-   Resource data should reflect actual runtime, database, and
    application state.
-   The available-tools overview must reflect tools actually registered
    by the MCP server.
-   Database unavailability must be distinguishable from MCP server
    unavailability.
-   Aggregated statistics must use consistent definitions across
    categories.
-   File statistics must respect the configured workspace boundary.
-   Responses must not disclose credentials, secrets, or sensitive
    configuration.
-   Resource failures should return clear error information rather than
    fabricated or misleading values.
-   The implementation must not expose arbitrary SQL execution or
    administrative database operations through this component.

## 8. Items to Finalize Before Implementation

1.  **Health status definitions:** Define the criteria for `running`,
    `degraded`, and `unavailable`.
2.  **Statistics semantics:** Confirm whether deleted, archived, or
    cancelled records are included in totals.
3.  **File statistics:** Define which files and file types count toward
    workspace totals.
4.  **Statistics freshness:** Decide whether counts are computed on
    every read or cached for a short period.
5.  **Server information:** Finalize which MCP capabilities and
    implementation details are safe and useful to expose.
6.  **Failure behavior:** Define whether unavailable data sources result
    in an error or a partial response with explicit source status.

------------------------------------------------------------------------

## 9. Consolidated Initial MCP Inventory

The following table summarizes the proposed initial catalog across all
five categories.

  Category                Tools   Resources
  -------------------- -------- -----------
  Task Management             6           5
  Notes Management            6           4
  File Management             4           0
  Agent Information           3           3
  System Information          0           5
  **Total**              **19**      **17**

This inventory is the proposed initial catalog. Tool parameters,
resource response schemas, error formats, and implementation contracts
should be finalized before server implementation begins.

------------------------------------------------------------------------

**Document status:** Proposed initial MCP specification.\
**Component:** System Information\
**Access mode:** Read-only\
**Persistence and data sources:** PostgreSQL, workspace filesystem, and
MCP server runtime\
**Interfaces:** MCP resources only\
**Initial catalog contribution:** 0 tools and 5 resources
