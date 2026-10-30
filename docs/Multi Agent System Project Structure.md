# ResearchMate --- Multi-Agent System Project Structure

## 1. Project Overview

  Property            Value
  ------------------- -----------------------------
  Project name        ResearchMate
  Project directory   `F:\Projects\ResearchMate\`
  Repository name     `ResearchMate`

**Project description:** ResearchMate is a multi-agent AI research
assistant designed to help students conduct research, organize
knowledge, manage academic tasks, and access information through an
MCP-powered tool ecosystem.

This document describes the proposed repository layout, high-level
system architecture, and initial MCP tool/resource inventory. Detailed
behavior and data contracts belong in the corresponding project and MCP
specifications.

## 2. Repository Structure

The following is the proposed project directory structure:

``` text
F:\Projects\ResearchMate\
│
├── .venv\
├── .env
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
├── AGENTS.md
│
├── docs\
│   ├── Multi Agent System Project Structure.md
│   ├── DEVELOPMENT_ENVIRONMENT.md
│   ├── PROJECT_REQUIREMENTS.md
│   ├── DATABASE_DESIGN.md
│   ├── IMPLEMENTATION_PLAN.md
│   ├── TEST_PLAN.md
│   ├── DECISIONS.md
│   │
│   └── MCP\
│       ├── Task Management.md
│       ├── Notes Management.md
│       ├── File Management.md
│       ├── Agent Information.md
│       └── System Information.md
│
├── mas\
│   ├── orchestrator\
│   ├── agents\
│   │   ├── research_agent\
│   │   └── task_agent\
│   └── config\
│
├── client_mcp\
│   ├── clients\
│   └── host.py
│
├── server_mcp\
│   ├── tools\
│   ├── resources\
│   └── server.py
│
├── database\
│   ├── models.py
│   ├── connection.py
│   └── migrations\
│
├── workspace\
│   ├── documents\
│   ├── reports\
│   ├── datasets\
│   └── source_code\
│
├── tests\
│
└── logs\
```

### 2.1 Directory responsibilities

  -----------------------------------------------------------------------
  Directory or file                   Responsibility
  ----------------------------------- -----------------------------------
  `.venv/`                            Local Python virtual environment.
                                      It should not be committed to
                                      version control.

  `.env`                              Local environment variables and
                                      secrets. It must not be committed.

  `.env.example`                      Example configuration keys with
                                      placeholder values only.

  `requirements.txt`                  Python dependency list for the
                                      project.

  `README.md`                         Project introduction, setup, and
                                      usage instructions.

  `AGENTS.md`                         Project-specific instructions for
                                      AI coding agents working in the
                                      repository.

  `docs/`                             Requirements, architecture, design,
                                      planning, testing, and decision
                                      documents.

  `mas/`                              Multi-agent system, including
                                      orchestration, specialized agents,
                                      and configuration.

  `client_mcp/`                       Client-side MCP host and MCP client
                                      connections used by the MAS.

  `server_mcp/`                       Server-side MCP implementation,
                                      including registered tools,
                                      resources, and server startup.

  `database/`                         Database models, connection
                                      management, and schema migrations.

  `workspace/`                        Files made available to agents
                                      through the File Management
                                      component.

  `tests/`                            Automated tests for individual
                                      components and end-to-end
                                      workflows.

  `logs/`                             Application and diagnostic logs.
  -----------------------------------------------------------------------

The workspace is distinct from the application source code, project
documentation, and PostgreSQL data storage. File Management tools must
be restricted to the configured workspace root.

In accordance with DEC-032, all four subdirectories (`documents/`, `reports/`,
`datasets/`, `source_code/`) form the permanent workspace layout. File Management
provides strictly read-only access to supported text-readable files across them
(TXT, MD, JSON, CSV, PY, SQL), while specialized data analysis and code
execution workflows remain deferred.

## 3. High-Level System Architecture

The following diagram illustrates the intended request and tool-access
flow.

``` mermaid
flowchart TD
    U[User] --> O[Orchestrator]
    O --> G[Gemini API]
    O --> R[Research Agent]
    O --> T[Task Agent]

    R --> L[Local LLM via Ollama]
    T --> L

    R --> H[Client-side MCP Host]
    T --> H
    O --> H

    H --> C[MCP Client]
    C -->|Streamable HTTP| S[Server-side MCP Server]

    S --> TM[Task Management]
    S --> NM[Notes Management]
    S --> FM[File Management]
    S --> AI[Agent Information]
    S --> SI[System Information]

    TM --> DB[(PostgreSQL)]
    NM --> DB
    AI --> DB
    SI --> DB

    FM --> W[(Workspace Filesystem)]
    SI --> W
```

### 3.1 Request flow

1.  The user submits a request to ResearchMate.
2.  The orchestrator, using the Gemini API, interprets the request and
    determines whether specialized agent work or MCP operations are
    needed.
3.  The orchestrator delegates appropriate work to the Research Agent,
    Task Agent, or other configured agents.
4.  Agents use their configured local model through Ollama.
5.  When an agent needs external application functionality, it uses the
    client-side MCP host and its MCP client connection.
6.  The MCP client communicates with the server-side MCP server over
    Streamable HTTP.
7.  The server exposes the registered tools and resources for Task
    Management, Notes Management, File Management, Agent Information,
    and System Information.
8.  Task, note, and agent records are stored in or retrieved from
    PostgreSQL. File Management accesses files within the configured
    workspace.
9.  Results are returned through the MCP client to the requesting agent
    or orchestrator, which uses them to prepare the response to the
    user.

The diagram is a logical overview. Exact invocation patterns,
agent-to-host connection arrangements, and component boundaries will be
finalized in the implementation design.

### 3.2 Data storage responsibilities

  -----------------------------------------------------------------------
  Data                                Storage
  ----------------------------------- -----------------------------------
  Tasks and task dependencies         PostgreSQL

  Notes, tags, and note versions      PostgreSQL

  Registered agent information        PostgreSQL

  File contents                       Local workspace filesystem

  System/runtime status               Application runtime and relevant
                                      database/filesystem state
  -----------------------------------------------------------------------

File contents are not stored in PostgreSQL in the initial design.
PostgreSQL may store related metadata in the future if a concrete
requirement emerges.

## 4. MCP Tools

MCP tools are operations that agents can invoke to perform actions or
retrieve information.

The proposed initial tool inventory contains **19 tools** across four
categories.

    No. Category            Tool name
  ----- ------------------- ---------------------
      1 Task Management     `create_task`
      2 Task Management     `get_task`
      3 Task Management     `get_tasks`
      4 Task Management     `update_task`
      5 Task Management     `delete_task`
      6 Task Management     `search_tasks`
      7 Notes Management    `create_note`
      8 Notes Management    `get_note`
      9 Notes Management    `get_notes`
     10 Notes Management    `update_note`
     11 Notes Management    `delete_note`
     12 Notes Management    `search_notes`
     13 File Management     `list_files`
     14 File Management     `read_file`
     15 File Management     `search_files`
     16 File Management     `get_file_metadata`
     17 Agent Information   `get_agent_info`
     18 Agent Information   `list_agents`
     19 Agent Information   `get_agent_tasks`

**Total: 19 proposed MCP tools.**

System Information does not introduce application-specific MCP tools in
the initial design. MCP's native protocol operations, such as
`tools/list`, are separate from this application-specific inventory.

## 5. MCP Resources

MCP resources are information sources that agents can read using
resource URIs.

The initial resource inventory contains **17 resources** across four
categories.

    No. Category             Resource URI
  ----- -------------------- ----------------------------
      1 Task Management      `tasks://all`
      2 Task Management      `tasks://pending`
      3 Task Management      `tasks://in-progress`
      4 Task Management      `tasks://completed`
      5 Task Management      `tasks://high-priority`
      6 Notes Management     `notes://all`
      7 Notes Management     `notes://technical`
      8 Notes Management     `notes://project`
      9 Notes Management     `notes://ideas`
     10 Agent Information    `agents://all`
     11 Agent Information    `agents://active`
     12 Agent Information    `agents://capabilities`
     13 System Information   `system://status`
     14 System Information   `system://statistics`
     15 System Information   `system://available-tools`
     16 System Information   `system://server-info`
     17 System Information   `system://database-info`

**Total: 17 proposed MCP resources.**

File Management does not expose standalone MCP resources in the initial
design. Agents use its four tools to discover and read workspace files.

## 6. Consolidated MCP Inventory

The consolidated inventory is:

  Category                Tools   Resources
  -------------------- -------- -----------
  Task Management             6           5
  Notes Management            6           4
  File Management             4           0
  Agent Information           3           3
  System Information          0           5
  **Total**              **19**      **17**

This corrects the earlier 15-resource count: the System Information
specification includes five resources, not three. The two additional
resources are `system://server-info` and `system://database-info`.

The inventory is a proposed initial catalog. The detailed category
specifications remain the authoritative source for each tool's
parameters, behavior, response structure, and each resource's content.

## 7. Configuration and Secrets

Runtime configuration should be provided through environment variables
and loaded by the application configuration layer.

Example `.env.example`:

``` env
GOOGLE_API_KEY=replace_with_your_api_key

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b

DATABASE_URL=postgresql+psycopg://postgres:replace_with_your_password@localhost:5432/mas_database
```

Important: - `.env.example` must contain placeholders, not real
credentials. - Actual API keys and database passwords belong only in the
local `.env` file or an appropriate secrets manager. - `.env` must be
excluded from Git. - Do not place credentials in source code,
documentation examples, logs, or MCP resource responses.

If a real database password has previously been committed to a
repository or shared in an untrusted location, rotate it.

## 8. Related Specifications

This document provides the project-level structure and architecture
overview. The following documents define the detailed requirements and
implementation contracts:

  -----------------------------------------------------------------------
  Document                            Purpose
  ----------------------------------- -----------------------------------
  `PROJECT_REQUIREMENTS.md`           Functional and non-functional
                                      requirements.

  `DATABASE_DESIGN.md`                PostgreSQL entities, relationships,
                                      constraints, and migrations.

  `IMPLEMENTATION_PLAN.md`            Phased implementation sequence and
                                      completion criteria.

  `TEST_PLAN.md`                      Testing scope, scenarios, and
                                      release criteria.

  `DECISIONS.md`                      Accepted, proposed, and deferred
                                      architectural decisions.

  `MCP/Task Management.md`            Task Management tools, resources,
                                      and data behavior.

  `MCP/Notes Management.md`           Notes Management tools, resources,
                                      and data behavior.

  `MCP/File Management.md`            Workspace file tools, supported
                                      formats, and access boundaries.

  `MCP/Agent Information.md`          Agent records, capabilities,
                                      status, tools, and resources.

  `MCP/System Information.md`         Read-only server and system
                                      information resources.
  -----------------------------------------------------------------------

If this overview conflicts with a detailed category specification,
reconcile the documents and record the final decision rather than
silently implementing conflicting definitions.

------------------------------------------------------------------------

**Document status:** Proposed project architecture and structure.\
**Project:** ResearchMate\
**Repository:** `ResearchMate`\
**Initial MCP inventory:** 19 tools and 17 resources
