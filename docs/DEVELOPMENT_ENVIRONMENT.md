# ResearchMate --- Development Environment

## 1. Purpose

This document records the development environment and software already
available for the ResearchMate project.

The implementation agent should read this document before making
environment changes. It must inspect and verify the actual machine state
rather than assuming every listed version or service is still installed
and available.

## 2. Operating Environment

  Item                Current information
  ------------------- -----------------------------
  Operating system    Windows
  Project directory   `F:\Projects\ResearchMate\`
  Repository name     `ResearchMate`
  IDE/editor          Visual Studio Code

### 2.1 Hardware

The development machine has the following reported specifications:

  Component             Specification
  --------------------- ----------------------------------------------
  Processor             Intel Core i5-10210U
  CPU cores / threads   4 cores / 8 logical processors
  Installed RAM         8 GB
  Integrated graphics   Intel UHD Graphics
  Dedicated graphics    AMD Radeon 610 Series, 2 GB dedicated memory

The implementation should account for these hardware constraints. Avoid
unnecessarily heavy dependencies, multiple concurrent local model
instances, and resource-intensive services. Prefer a modular
implementation that can be developed and tested on this machine.

## 3. Installed Software and Versions

The following software and versions have been reported as installed.

  Software             Reported version / configuration   Purpose
  -------------------- ---------------------------------- ------------------------------------
  Python               `3.15.2`                           Main application language
  Ollama               `0.40.13`                          Local LLM runtime
  Ollama model         `llama3.2:3b`                      Local model for specialized agents
  Git                  `2.56.0.windows.4`                 Version control
  PostgreSQL           `18.6`                             Application database
  PostgreSQL port      `5432`                             Local database connection
  Visual Studio Code   Installed                          Development environment
  pgAdmin 4            Installed                          PostgreSQL administration

**Version verification is required.** Before installation or
configuration, inspect the machine and confirm the actual versions. The
reported versions are starting information, not a substitute for
verification.

Useful Windows PowerShell commands:

``` powershell
python --version
py --list
ollama --version
ollama list
git --version
psql --version
Get-Service *postgres*
```

To check whether PostgreSQL is listening on the expected port:

``` powershell
Test-NetConnection localhost -Port 5432
```

To inspect the PostgreSQL server version after connecting:

``` sql
SELECT version();
```

## 4. Local LLM Configuration

Ollama is the local model runtime.

  Setting                      Value
  ---------------------------- --------------------------
  Runtime                      Ollama
  Reported Ollama version      `0.40.13`
  Model                        `llama3.2:3b`
  Default local API endpoint   `http://localhost:11434`

The Research Agent and Task Agent are initially intended to use the
local model through Ollama. The initial design aims to share one local
model runtime rather than running separate model instances for each
agent.

The implementation agent must verify that the model is available with
`ollama list`. It must not download another model or replace the
selected model without explaining the reason and obtaining approval.

## 5. PostgreSQL Configuration

  Setting                 Value
  ----------------------- ----------------------------
  Database engine         PostgreSQL
  Reported version        `18.6`
  Host                    `localhost`
  Port                    `5432`
  Python driver           Psycopg
  SQLAlchemy URL format   `postgresql+psycopg://...`

The PostgreSQL service has previously been reported as running, and
local `psql` connectivity has been tested.

The target application database name is:

``` text
mas_database
```

The implementation agent must verify whether this database already
exists before attempting to create it. Do not drop, reset, or overwrite
an existing database.

Database credentials must be supplied through local environment
configuration. Never place actual passwords or connection secrets in
source code, committed documentation, or logs.

## 6. Python Environment Policy

-   Python `3.15.2` is accepted as the official project Python version
    (DEC-025, superseding DEC-015).
-   Use a project-local virtual environment at `.venv/`.
-   Do not install project dependencies globally unless explicitly
    required.
-   Keep dependencies isolated from other Python projects.
-   Check whether the selected Python version is supported by the
    required packages before installing them. Dependency compatibility has
    been verified for all candidate packages in `requirements.txt`.
-   Do not claim complete application compatibility merely because
    dependencies install and import successfully. Application-level
    compatibility must be verified through phased implementation and
    testing.
-   Record project dependencies in `requirements.txt` after they are
    selected and tested.

The intended virtual environment location is:

``` text
F:\Projects\ResearchMate\.venv\
```

## 7. Environment and Resource Constraints

The development machine has 8 GB RAM and a low-power mobile CPU.
Therefore:

-   Avoid running multiple local LLM instances concurrently.
-   Avoid adding Docker, Kubernetes, Redis, Kafka, or other
    infrastructure unless a documented requirement justifies it.
-   Do not introduce heavyweight agent frameworks when the initial
    architecture can be implemented with the official MCP SDK and
    lightweight Python components.
-   Prefer running and testing components independently.
-   Keep database queries, file reads, and agent context sizes bounded.
-   Consider local model inference speed when designing agent workflows.
-   Use Gemini API for the orchestrator as specified in the project
    design; the API key must be stored in `.env`.

## 8. Instructions for the Implementation Agent

Before changing the project:

1.  Read `Multi Agent System Project Structure.md` and all related
    project and MCP specifications.
2.  Read `DECISIONS.md` and respect the distinction between accepted,
    proposed, deferred, and open decisions.
3.  Inspect the current machine and verify installed software, versions,
    PostgreSQL service state, and Ollama model availability.
4.  Compare the actual environment with this document and report
    discrepancies.
5.  Create the project structure described in
    `Multi Agent System Project Structure.md`.
6.  Preserve all existing documentation. Do not rewrite, delete, or
    rename the specifications unless explicitly instructed.
7.  Do not install software that is already available and verified.
8.  Do not install project dependencies globally. Use the project
    virtual environment.
9.  Do not expose, print, or commit secrets.
10. Do not start implementing all application features during the
    initial structure setup. First create and verify the repository
    structure and configuration foundation, then report what was created
    and any blockers.

If a requirement conflicts with the actual machine environment or
another project document, stop and report the conflict rather than
silently making an architectural change.

------------------------------------------------------------------------

**Document status:** Environment record; verify versions and service
state before implementation.\
**Project:** ResearchMate\
**Platform:** Windows\
**Project root:** `F:\Projects\ResearchMate\`
