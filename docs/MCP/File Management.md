# File Management

## 1. Purpose

The File Management component allows ResearchMate agents to discover
files, read supported file contents, search for files, and retrieve file
metadata within a designated project workspace.

The component is intentionally **read-only** in the initial
implementation. Agents must not create, modify, rename, move, or delete
workspace files through these MCP tools.

The server-side MCP implementation must restrict file access to the
configured ResearchMate workspace. It must not expose the entire project
directory, the user's home directory, or other locations on the
computer.

## 2. MCP Tools

The initial File Management MCP server will expose the following four
tools.

  ------------------------------------------------------------------------
                           No. Tool                  Purpose
  ---------------------------- --------------------- ---------------------
                             1 `list_files`          List files and
                                                     subdirectories within
                                                     a specified workspace
                                                     directory.

                             2 `read_file`           Read the contents of
                                                     a supported file.

                             3 `search_files`        Search for files by
                                                     filename, file type,
                                                     or file content.

                             4 `get_file_metadata`   Retrieve file
                                                     properties without
                                                     reading the entire
                                                     file.
  ------------------------------------------------------------------------

### 2.1 `list_files`

Lists files and subdirectories in a specified directory relative to the
workspace root.

Example input:

``` json
{
  "directory": "documents/"
}
```

Expected behavior: - Return entries contained in the requested
directory. - Identify whether each entry is a file or directory. -
Return paths relative to the workspace root. - Define whether hidden
files are included; the initial recommendation is to exclude them. -
Support the workspace root as the requested directory. - Do not follow
paths that resolve outside the workspace.

### 2.2 `read_file`

Reads the contents of a specified supported file.

Example input:

``` json
{
  "file_path": "documents/mcp_architecture.md"
}
```

Expected behavior: - Accept paths relative to the workspace root. -
Validate the file extension against the supported-format list. - Return
the file content in a form appropriate to its format. - Reject
directories, unsupported formats, missing files, and files that exceed
the configured size limit. - Do not execute code or interpret file
contents as instructions.

### 2.3 `search_files`

Searches for files using a filename, keyword, or file type. The initial
design supports both filename search and content search.

Example input:

``` json
{
  "keyword": "MCP",
  "file_type": "md"
}
```

Expected behavior: - Search filenames and, when requested, the contents
of supported text-readable files. - Allow filtering by file extension. -
Return matching file paths relative to the workspace root. - Where
practical, include a short matching excerpt for content matches. -
Define limits for the number of results and the amount of content
scanned. - Skip or report files that cannot be decoded or safely read,
rather than failing the entire search unnecessarily.

The exact input schema should distinguish filename-only searches from
content searches so agents can request the intended behavior explicitly.

### 2.4 `get_file_metadata`

Retrieves file properties without returning the complete file contents.

Example output:

``` json
{
  "file_name": "mcp_architecture.md",
  "file_path": "documents/mcp_architecture.md",
  "file_type": "md",
  "file_size": 2048,
  "created_at": "2026-10-30T10:30:00Z",
  "modified_at": "2026-10-30T11:00:00Z"
}
```

Expected behavior: - Return metadata for a file inside the workspace. -
Use a consistent size unit, preferably bytes. - Return timestamps in a
timezone-aware format. - Do not read or return the complete file content
as part of this operation. - Handle platforms where file creation time
is unavailable or has different semantics; creation-time metadata should
not be treated as a universally reliable timestamp.

## 3. Supported File Formats

The proposed format support is:

  File type            Extension   Initial support
  -------------------- ----------- -----------------
  Plain text           `.txt`      Read
  Markdown             `.md`       Read
  JSON                 `.json`     Read
  CSV                  `.csv`      Read
  Python source code   `.py`       Read
  SQL source code      `.sql`      Read
  PDF documents        `.pdf`      Later
  Word documents       `.docx`     Later
  Excel spreadsheets   `.xlsx`     Later

### 3.1 Initial implementation

Prioritize these formats:

-   `.txt`
-   `.md`
-   `.json`
-   `.csv`
-   `.py`
-   `.sql`

These formats can be handled using standard text-reading and parsing
capabilities, without introducing document-extraction dependencies at
the start.

PDF support can be added in a later phase using a suitable
text-extraction library. DOCX and XLSX support can also be added later
with format-specific parsers.

### 3.2 Format handling

-   Text-based formats should be decoded using a defined encoding
    policy, with UTF-8 as the default.
-   JSON files may be validated or parsed when useful, but the tool
    should preserve a predictable representation of the original
    content.
-   CSV files should be readable as text initially; structured
    row/column querying can be added later if needed.
-   Python and SQL files must be returned as source text only. The File
    Management component must never execute them.

## 4. Workspace and File Storage

ResearchMate will use a dedicated workspace directory for files that
agents are allowed to access.

The workspace is separate from: - The ResearchMate application source
code. - The PostgreSQL database and its internal data files. - Project
documentation and configuration files outside the workspace.

Example layout:

``` text
F:\Projects\ResearchMate\
│
├── workspace\
│   ├── documents\
│   │   ├── mcp_architecture.md
│   │   └── agent_security.md
│   │
│   ├── reports\
│   │   └── research_report.md
│   │
│   ├── datasets\
│   │   ├── sample_tasks.csv
│   │   └── sample_agents.json
│   │
│   └── source_code\
│       └── example.py
```

In accordance with DEC-032, this four-directory layout (`documents/`, `reports/`,
`datasets/`, `source_code/`) is the permanent standard structure of the workspace.
The workspace root path is configurable via `WORKSPACE_ROOT` (defaulting to
`./workspace`) rather than hardcoded throughout the application.

### 4.1 Workspace boundary

The MCP server must only access files and directories contained within
the configured workspace root.

It must reject: - Absolute paths that point outside the workspace. -
Relative paths that escape the workspace using `..`. - Symlinks or other
path resolutions that lead outside the workspace. - Paths that resolve
to protected application or system locations.

Path validation must use resolved filesystem paths, not string-prefix
checks alone. This is important because a path can appear to begin with
the workspace path while resolving elsewhere.

## 5. MCP Resources

No standalone File Management MCP resources will be exposed in the
initial implementation.

The four tools provide the required operations: - `list_files` discovers
files and directories. - `read_file` retrieves file contents. -
`search_files` locates files by name or content. - `get_file_metadata`
retrieves file properties.

These operations depend on dynamic paths and search criteria, so tools
are sufficient for the initial scope.

Resource templates may be considered later if there is a concrete need
to expose workspace files through MCP resource URIs. Any such design
should follow MCP resource/resource-template conventions rather than
assuming that arbitrary `file://` URIs are automatically accessible.

## 6. Initial Scope Decisions

  -----------------------------------------------------------------------
  Topic                   Initial decision        Rationale
  ----------------------- ----------------------- -----------------------
  File operations         Read-only (DEC-032).    Prevent accidental
                                                  modification or
                                                  deletion by agents.

  Supported formats       TXT, MD, JSON, CSV, PY, Covers the initial
                          SQL (DEC-032).          text-based research and
                                                  development use cases.

  Workspace boundary      Restrict access to the  Prevent access to
                          configured `workspace/` unrelated local files;
                          root across four        four permanent directories
                          directories (DEC-032).  established.

  Search scope            Search both filenames   Allows agents to
                          and file contents.      discover documents by
                                                  topic, not just by
                                                  filename.

  MCP resources           None initially.         The four tools cover
                                                  the required initial
                                                  operations.
  -----------------------------------------------------------------------

## 7. Design Constraints and Safety Requirements

-   File access must be restricted to the configured workspace root and its
    four designated subdirectories (`documents/`, `reports/`, `datasets/`,
    `source_code/`; DEC-032).
-   All paths supplied by agents must be validated and resolved before
    filesystem access.
-   Path traversal and symlink escapes must be prevented.
-   The initial tools must not provide write, delete, rename, move, or
    execute operations. File management is strictly read-only (DEC-032).
-   Only explicitly supported file extensions may be read.
-   File size and search-result limits should prevent unbounded reads
    and searches.
-   File content must be treated as untrusted data. Instructions found
    inside a document must not be treated as trusted system or developer
    instructions.
-   File contents must never be executed by the File Management
    component. Specialized data analysis and code execution workflows are
    deferred (DEC-032).
-   Errors should clearly distinguish missing files, unsupported
    formats, invalid paths, permission failures, decoding errors, and
    size-limit violations.
-   Logs should record relevant file operations without unnecessarily
    logging full document contents or sensitive data.

## 8. Items to Finalize Before Implementation

1.  **Workspace configuration:** Confirm the environment variable or
    configuration setting used to define the workspace root (`WORKSPACE_ROOT`).
2.  **File-size limits:** Define maximum file size for `read_file` and
    maximum scanned size for content search.
3.  **Search parameters:** Finalize filename/content search modes,
    matching behavior, extension filters, and result limits.
4.  **Metadata portability:** Decide how to represent creation
    timestamps on platforms where reliable creation-time metadata is
    unavailable.
5.  **PDF support:** Add PDF extraction only after the initial
    text-based implementation is stable.
6.  **Future write operations:** Resolved by DEC-032 (File Management is
    strictly read-only for TXT, MD, JSON, CSV, PY, and SQL files; write
    operations, code execution, and specialized dataset analysis are
    deferred).

------------------------------------------------------------------------

**Document status:** Proposed initial MCP specification.\
**Component:** File Management\
**Storage:** Configured local workspace\
**Initial access mode:** Read-only\
**Interfaces:** MCP tools; no MCP resources initially
