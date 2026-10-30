# Notes Management

## 1. Purpose

The Notes Management component allows ResearchMate users and agents to
create, retrieve, update, search, and delete persistent notes.

Notes are stored in PostgreSQL. The component exposes note operations
through MCP tools and provides predefined note collections through MCP
resources. Notes are intended to preserve useful research findings,
technical information, project documentation, meeting notes, ideas, and
other knowledge that agents may need across tasks.

## 2. MCP Tools

The initial Notes Management MCP server will expose the following six
tools.

  ------------------------------------------------------------------------
                           No. Tool                  Purpose
  ---------------------------- --------------------- ---------------------
                             1 `create_note`         Create a new note.

                             2 `get_note`            Retrieve one note
                                                     using its unique
                                                     identifier.

                             3 `get_notes`           Retrieve multiple
                                                     notes, optionally
                                                     filtered by note
                                                     attributes.

                             4 `update_note`         Update an existing
                                                     note.

                             5 `delete_note`         Delete an existing
                                                     note.

                             6 `search_notes`        Search notes using
                                                     keywords.
  ------------------------------------------------------------------------

### Tool behavior guidelines

-   `create_note` should validate required fields and the supplied
    category before creating a note.
-   `get_note` should return a clear not-found result when the supplied
    identifier does not exist.
-   `get_notes` should support filters such as category, creator, and
    tags. Exact parameters will be defined in the tool specification.
-   `update_note` should update only the supplied fields, archive the
    prior content into `note_versions`, and refresh `updated_at` automatically.
-   `delete_note` marks the note as soft-deleted by setting `is_deleted = TRUE`
    and `deleted_at` to the current timestamp (DEC-029). Historical versions
    in `note_versions` and tag associations are preserved. Soft-deleted notes
    are excluded from normal queries, listings, search, and resources by
    default. A clear report of the deletion or not-found status is returned.
-   `search_notes` should search relevant note content, at minimum the
    title and content. Search behavior and matching rules will be
    defined during implementation.

All tools should return structured, predictable results and useful error
information. They should not silently report success when an operation
fails.

## 3. Note Data Model

The proposed initial note record contains the following fields.

  ----------------------------------------------------------------------------------------------------------------------------------------------
  Field                   Description                                                   Example
  ----------------------- ------------------------------------------------------------- ----------------------------------------------------------------
  `note_id`               Unique note identifier (standard 36-character hyphenated      `b2c3d4e5-f6a7-8b9c-0d1e-2f3a4b5c6d7e`
                          UUID string; DEC-026).                                        

  `title`                 Short title describing the note.                              `Understanding MCP`

  `content`               Main body of the note.                                        `MCP enables AI applications to interact with external tools and resources.`

  `category`              Classification of the note.                                   `technical_research`

  `tags`                  Keywords associated with the note. A note may have multiple   `["MCP", "AI", "Agent Architecture"]`
                          tags.                                                         

  `created_by`            Canonical Attribution object (DEC-027) identifying creator    `{"type": "agent", "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479", "name": "Research Agent"}`
                          (human user or AI agent).                                     

  `created_at`            Timestamp at which the note was created.                      `2026-10-30T10:30:00Z`

  `updated_at`            Timestamp of the most recent update.                          `2026-10-30T10:30:00Z`

  `is_deleted`            Soft-delete flag (DEC-029; boolean).                          `false`

  `deleted_at`            Timestamp when note was soft-deleted (DEC-029; optional).     `null`
  ----------------------------------------------------------------------------------------------------------------------------------------------

### 3.0 Identifier format

In accordance with DEC-026:
- All note identifiers (`note_id`) must be standard 36-character hyphenated UUID strings (e.g. `"b2c3d4e5-f6a7-8b9c-0d1e-2f3a4b5c6d7e"`).
- In PostgreSQL, notes use the native `UUID` primary key type (`notes.note_id UUID`, `note_versions.note_id UUID`).
- MCP tool parameters (`get_note`, `update_note`, `delete_note`, etc.) and MCP resource responses serialize and accept UUID strings only.
- Integer identifiers (such as `201`) are not supported.

### 3.1 Note categories

The initial supported categories are:

-   `technical_research`
-   `project_documentation`
-   `meeting_notes`
-   `ideas`
-   `general_knowledge`
-   `personal_notes`

The stored values should use the lowercase identifiers shown above.
Human-readable labels can be formatted separately for display.

### 3.2 Tags

Tags allow a note to be associated with multiple topics. For example, a
note about MCP agent architecture could have the tags `MCP`, `AI`, and
`Agent Architecture`.

The data model should support multiple tags per note and avoid storing a
comma-separated tag string as the canonical representation. The database
design should define how tags are stored and whether duplicate tags are
normalized case-insensitively.

### 3.3 Content format

The initial content format should be Markdown. This supports headings,
lists, links, code blocks, tables, and other useful structures for
technical and academic notes.

The note content should be stored as text. Structured JSON content is
not part of the initial scope. If structured metadata is needed later,
it can be introduced as separate fields or a dedicated metadata field
without making the main note body ambiguous.

### 3.4 Creator and timestamps

In accordance with DEC-027:
- `created_by` uses the canonical Attribution object across MCP interfaces:
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
- In PostgreSQL, this maps to `created_by_agent_id` or `created_by_user_id` (and `changed_by_agent_id` or `changed_by_user_id` in `note_versions`). Exactly one corresponding foreign-key column is populated.
- The service layer validates that the referenced entity exists and that the attribution type matches.
- The Attribution object is a data representation, not an authentication mechanism. It must not be treated as cryptographic proof of identity.
- `created_at` and `updated_at` should be stored as timezone-aware timestamps.
- `created_at` should be set when the note is created.
- `updated_at` should be refreshed whenever the note is modified.

### 3.5 Soft deletion fields

In accordance with DEC-029:
- `is_deleted`: A boolean flag (`false` by default) marking whether a note has been soft-deleted.
- `deleted_at`: A timezone-aware timestamp set to the current time when a note is deleted (`null` while active).
- Normal note queries, listings, search, and resources exclude soft-deleted notes by default (`WHERE is_deleted = FALSE`).
- Deleting a note preserves all historical records in `note_versions` and tag associations.
- Permanent deletion is not supported in the initial implementation.

## 4. MCP Resources

The Notes Management MCP server will expose these four predefined
resources.

  ----------------------------------------------------------------------------
                           No. Resource URI          Content
  ---------------------------- --------------------- -------------------------
                             1 `notes://all`         All available notes.

                             2 `notes://technical`   Notes in the
                                                     `technical_research`
                                                     category.

                             3 `notes://project`     Notes in the
                                                     `project_documentation`
                                                     category.

                             4 `notes://ideas`       Notes in the `ideas`
                                                     category.
  ----------------------------------------------------------------------------

Resources will retrieve their data from PostgreSQL and return it in a
consistent JSON representation. Empty collections should return an empty
result rather than an error.

Resource responses should use the same field names and value conventions
as the MCP tools. If the number of notes becomes large, pagination or
bounded results should be considered rather than returning an unbounded
collection.

## 5. Example Note

The following JSON illustrates the proposed representation of a note.
The timestamps include a UTC offset to make the timezone explicit.

``` json
{
  "note_id": "b2c3d4e5-f6a7-8b9c-0d1e-2f3a4b5c6d7e",
  "title": "Understanding MCP",
  "content": "Model Context Protocol is a protocol that allows AI applications to interact with external tools and resources.",
  "category": "technical_research",
  "tags": [
    "MCP",
    "AI",
    "Agent Architecture"
  ],
  "created_by": {
    "type": "agent",
    "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "name": "Research Agent"
  },
  "created_at": "2026-10-30T10:30:00Z",
  "updated_at": "2026-10-30T10:30:00Z",
  "is_deleted": false,
  "deleted_at": null
}
```

The `created_by` object illustrates the recommended distinction between
creator type and creator identifier. The exact representation must match
the database schema and the Agent Information specification.

## 6. Initial Scope Decisions

The following are the recommended decisions for the first
implementation.

  -----------------------------------------------------------------------
  Topic                   Initial decision        Rationale
  ----------------------- ----------------------- -----------------------
  Note ownership and      Shared notes accessible Agents can reuse
  visibility              to all ResearchMate     information and
                          agents.                 collaborate through a
                                                  common knowledge store.

  Content format          Markdown text.          Markdown is readable
                                                  and suitable for
                                                  technical and academic
                                                  notes.

  Version history         Retain previous         Version history makes
                          versions when a note is it possible to inspect
                          updated.                or recover earlier
                                                  content.
  -----------------------------------------------------------------------

### 6.1 Shared notes

In the initial version, notes will be shared across ResearchMate agents
rather than private to individual agents. The creator should still be
recorded for traceability.

Private notes and per-user visibility can be introduced later if
ResearchMate expands to support multiple users or access-control
requirements.

### 6.2 Version history

Updating a note preserves its previous content as a historical record in
`note_versions` rather than overwriting it.

In accordance with DEC-031:
-   Note versions are retained indefinitely by default (`MAX_NOTE_VERSIONS: int = 0`).
-   If a positive ceiling is configured in application settings, FIFO pruning
    removes the oldest historical versions when the count exceeds the threshold,
    while preserving the active note.
-   In accordance with DEC-029, soft-deleting a note preserves all historical
    records in `note_versions` and tag associations intact.

## 7. Design Constraints

-   PostgreSQL is the source of truth for note records.
-   MCP tools and resources must use consistent field names and category
    values.
-   Note identifiers must be unique, stable, and formatted as standard
    36-character hyphenated UUID strings matching PostgreSQL native UUIDs
    (DEC-026).
-   Note content must support Markdown.
-   Tags must support multiple values per note.
-   Creator attribution must use the canonical Attribution object
    (DEC-027), distinguishing human users from AI agents.
-   `created_at` and `updated_at` must be maintained consistently.
-   Updates must preserve historical versions according to the
    version-history policy.
-   Note deletion must use soft deletion (`is_deleted`, `deleted_at`), excluding
    deleted notes from normal queries and resources by default, while preserving
    historical versions and tag associations (DEC-029).
-   Note version retention retains versions indefinitely by default, governed by
    configurable `MAX_NOTE_VERSIONS` (DEC-031).
-   Tool failures and invalid inputs must produce clear error responses.
-   Access control and authorization rules will be specified as part of
    the broader ResearchMate security design; this document does not
    define a complete authorization model.

## 8. Items to Finalize Before Implementation

The following details must be settled in coordination with the database
and implementation specifications:

1.  **Creator representation:** Resolved by DEC-027 (canonical
    Attribution object mapped to discrete database foreign keys).
2.  **Version retention:** Resolved by DEC-031 (indefinite retention by default,
    governed by configurable `MAX_NOTE_VERSIONS: int = 0` with FIFO pruning).
3.  **Deletion behavior:** Resolved by DEC-029 (soft deletion with version
    preservation using `is_deleted` and `deleted_at`).
4.  **Tag behavior:** Define case sensitivity, normalization, and
    whether tags are created automatically when a note is saved.
5.  **Search behavior:** Define whether `search_notes` uses PostgreSQL
    full-text search, substring matching, or both.
6.  **Listing limits:** Define default ordering, pagination, and maximum
    result counts for `get_notes` and resource reads.

Private notes and structured JSON note bodies are intentionally outside
the initial scope.

------------------------------------------------------------------------

**Document status:** Proposed initial MCP specification.\
**Component:** Notes Management\
**Persistence:** PostgreSQL\
**Content format:** Markdown text\
**Interfaces:** MCP tools and MCP resources
