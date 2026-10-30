"""Tool argument and safety validation for Multi-Agent System (MAS) (Phase 9).

Validates model-generated tool calls against dynamically discovered MCP inputSchemas
and enforces conservative, operation-specific destructive operation safeguards before invoking MCPHost.
"""

import re
from typing import Any

import jsonschema

DESTRUCTIVE_TOOLS = {"delete_task", "delete_note"}

GENERIC_WORDS = {
    "a",
    "an",
    "the",
    "my",
    "this",
    "that",
    "these",
    "those",
    "some",
    "any",
    "all",
    "each",
    "every",
    "task",
    "tasks",
    "note",
    "notes",
    "it",
    "item",
    "one",
    "record",
    "entry",
    "here",
    "there",
    "now",
    "please",
    "completely",
    "entirely",
    "about",
    "on",
    "for",
    "with",
    "named",
    "titled",
    "regarding",
}


def _has_quoted_deletion(text: str) -> bool:
    """Check if deletion instruction is merely quoted inside speech or documentation."""
    quotes = re.findall(r'["\']([^"\']+)["\']', text)
    if not quotes:
        return False
    text_outside = re.sub(r'["\']([^"\']+)["\']', " ", text)
    has_delete_in_quotes = any(
        re.search(r"\b(?:delete|remove)\b", q, re.IGNORECASE) for q in quotes
    )
    has_delete_outside = bool(
        re.search(r"\b(?:delete|remove)\b", text_outside, re.IGNORECASE)
    )
    return has_delete_in_quotes and not has_delete_outside


def _is_negated(text: str) -> bool:
    """Detect negation patterns in the prompt."""
    negation_patterns = [
        r"\b(?:do\s+not|don'?t|never|cannot|can'?t|won'?t|will\s+not|should\s+not|shouldn'?t|must\s+not|mustn'?t|would\s+not|wouldn'?t)\b",
        r"\b(?:not\s+to\s+delete|not\s+delete|avoid\s+delet\w*|stop\s+delet\w*|refrain\s+from\s+delet\w*|without\s+delet\w*|prevent\s+delet\w*)\b",
        r"\b(?:don'?t\s+want\s+to\s+delete|do\s+not\s+want\s+to\s+delete|no\s+need\s+to\s+delete)\b",
        r"\b(?:not\s+to\s+remove|not\s+remove|avoid\s+remov\w*|stop\s+remov\w*|refrain\s+from\s+remov\w*|without\s+remov\w*)\b",
        r"\b(?:don'?t\s+want\s+to\s+remove|do\s+not\s+want\s+to\s+remove|no\s+need\s+to\s+remove)\b",
    ]
    return any(re.search(p, text, re.IGNORECASE) for p in negation_patterns)


def _is_question_or_inquiry(text: str) -> bool:
    """Detect questions or requests for explanations."""
    if text.strip().endswith("?"):
        return True
    inquiry_patterns = [
        r"^(?:can\s+you\s+explain|explain|how\s+to|how\s+do\s+i|how\s+does|why\s+would|should\s+i|is\s+it\s+possible|tell\s+me\s+about\s+how\s+to)\b",
        r"\b(?:what\s+happens\s+if|what\s+would\s+happen\s+if|how\s+does\s+\w+\s+deletion\s+work)\b",
        r"^(?:what|why|how|when|where|who)\b",
    ]
    return any(re.search(p, text.strip(), re.IGNORECASE) for p in inquiry_patterns)


def _is_hypothetical_or_conditional(text: str) -> bool:
    """Detect hypothetical, conditional, or tentative statements."""
    conditional_patterns = [
        r"\b(?:what\s+if|what\s+happens\s+if|what\s+would\s+happen\s+if)\b",
        r"\b(?:in\s+case|assuming|supposing|whether\s+to|whether\s+i\s+should)\b",
        r"\b(?:before\s+deleting|after\s+deleting)\b",
        r"\bif\b",
        r"\bunless\b",
        r"\bwhenever\b",
        r"\bprovided\s+that\b",
    ]
    return any(re.search(p, text, re.IGNORECASE) for p in conditional_patterns)


def _is_past_tense(text: str) -> bool:
    """Detect past tense statements referring to completed actions."""
    past_patterns = [
        r"\b(?:previously\s+deleted|already\s+deleted|have\s+deleted|has\s+been\s+deleted|was\s+deleted|were\s+deleted|i\s+deleted|we\s+deleted)\b",
        r"\b(?:previously\s+removed|already\s+removed|have\s+removed|has\s+been\s+removed|was\s+removed|were\s+removed|i\s+removed|we\s+removed)\b",
    ]
    return any(re.search(p, text, re.IGNORECASE) for p in past_patterns)


def _is_tag_removal(text: str) -> bool:
    """Detect requests to remove tags, labels, or properties from notes."""
    tag_patterns = [
        r"\b(?:remove|delete)\s+.*?\b(?:tag|tags|label|labels|comment|comments|property|field)\b",
        r"\b(?:tag|tags|label|labels)\b.*?\bfrom\b.*?\bnote\b",
    ]
    return any(re.search(p, text, re.IGNORECASE) for p in tag_patterns)


def _is_cancellation(text: str) -> bool:
    """Detect cancellation requests that do not affirmatively ask for deletion."""
    return bool(
        re.search(r"\b(?:cancel|cancelling|cancellation)\b", text, re.IGNORECASE)
        and not re.search(r"\bdelete\b", text, re.IGNORECASE)
    )


def _extract_task_target(text: str) -> str | None:
    """Extract identifiable task target from affirmative instruction."""
    # Pattern 1: named / titled / with title / with id
    m = re.search(
        r"\btask\s+(?:named|titled|with\s+title|with\s+id|with\s+name)\s+[\"']?([^\"'.,;\n]+)[\"']?",
        text,
        re.IGNORECASE,
    )
    if m:
        val = m.group(1).strip()
        if val.lower() not in GENERIC_WORDS:
            return val

    # Pattern 2: task in quotes e.g. task "Draft Methodology"
    m = re.search(r"\btask\s+[\"']([^\"']+)[\"']", text, re.IGNORECASE)
    if m:
        val = m.group(1).strip()
        if val.lower() not in GENERIC_WORDS:
            return val

    # Pattern 3: '<descriptor>' task
    m = re.search(r"[\"']([^\"']+)[\"']\s+task\b", text, re.IGNORECASE)
    if m:
        val = m.group(1).strip()
        if val.lower() not in GENERIC_WORDS:
            return val

    # Pattern 4: task for/about/regarding <descriptor>
    m = re.search(
        r"\btask\s+(?:for|about|regarding)\s+[\"']?([^\"'.,;\n]+)[\"']?",
        text,
        re.IGNORECASE,
    )
    if m:
        val = m.group(1).strip()
        if val.lower() not in GENERIC_WORDS:
            return val

    # Pattern 5: task with explicit id/UUID or number or identifier
    m = re.search(
        r"\btask\s+(?:id\s+|#\s*|number\s+)?([a-zA-Z0-9_-]+)\b", text, re.IGNORECASE
    )
    if m:
        val = m.group(1).strip()
        if val.lower() not in GENERIC_WORDS:
            return val

    return None


def _extract_note_target(text: str) -> str | None:
    """Extract identifiable note target from affirmative instruction."""
    # Pattern 1: named / titled / with title / with id
    m = re.search(
        r"\bnote\s+(?:named|titled|with\s+title|with\s+id|with\s+name)\s+[\"']?([^\"'.,;\n]+)[\"']?",
        text,
        re.IGNORECASE,
    )
    if m:
        val = m.group(1).strip()
        if val.lower() not in GENERIC_WORDS:
            return val

    # Pattern 2: note in quotes e.g. note "Neural Networks"
    m = re.search(r"\bnote\s+[\"']([^\"']+)[\"']", text, re.IGNORECASE)
    if m:
        val = m.group(1).strip()
        if val.lower() not in GENERIC_WORDS:
            return val

    # Pattern 3: '<descriptor>' note
    m = re.search(r"[\"']([^\"']+)[\"']\s+note\b", text, re.IGNORECASE)
    if m:
        val = m.group(1).strip()
        if val.lower() not in GENERIC_WORDS:
            return val

    # Pattern 4: note about/on/regarding/for <descriptor>
    m = re.search(
        r"\bnote\s+(?:about|on|regarding|for)\s+[\"']?([^\"'.,;\n]+)[\"']?",
        text,
        re.IGNORECASE,
    )
    if m:
        val = m.group(1).strip()
        if val.lower() not in GENERIC_WORDS:
            return val

    # Pattern 5: note with explicit id/UUID or number or identifier
    m = re.search(
        r"\bnote\s+(?:id\s+|#\s*|number\s+)?([a-zA-Z0-9_-]+)\b", text, re.IGNORECASE
    )
    if m:
        val = m.group(1).strip()
        if val.lower() not in GENERIC_WORDS:
            return val

    return None


def is_task_deletion_authorized(
    user_prompt: str, arguments: Any = None
) -> tuple[bool, str | None]:
    """Conservatively verify affirmative user authorization for task deletion."""
    if not user_prompt or not user_prompt.strip():
        return False, "User request is empty."

    if _has_quoted_deletion(user_prompt):
        return (
            False,
            "Deletion command appears inside quoted text rather than as an affirmative instruction.",
        )

    if _is_negated(user_prompt):
        return False, "User request contains a negated instruction regarding deletion."

    if _is_question_or_inquiry(user_prompt):
        return (
            False,
            "Questions or inquiries cannot authorize task deletion. Please confirm with an explicit deletion command.",
        )

    if _is_hypothetical_or_conditional(user_prompt):
        return (
            False,
            "Hypothetical or conditional statements cannot authorize task deletion.",
        )

    if _is_past_tense(user_prompt):
        return (
            False,
            "Request refers to a past deletion rather than an affirmative deletion instruction.",
        )

    if _is_cancellation(user_prompt):
        return (
            False,
            "Task cancellation is a status change, not task deletion. Provide an explicit 'delete' instruction to permanently delete.",
        )

    # Check for affirmative delete command targeting a task
    has_delete_task = bool(
        re.search(
            r"\b(?:delete|permanently\s+delete)\b.*?\btask\w*\b",
            user_prompt,
            re.IGNORECASE,
        )
        or re.search(r"\btask\w*\b.*?\bdelete\b", user_prompt, re.IGNORECASE)
    )
    if not has_delete_task:
        if re.search(r"\bremove\b.*?\btask\w*\b", user_prompt, re.IGNORECASE):
            pass
        else:
            return (
                False,
                "Request does not contain a clear affirmative instruction to delete a task.",
            )

    target = _extract_task_target(user_prompt)
    if not target:
        return (
            False,
            "No identifiable task target (ID, title, or name) was specified in the user request. Please specify which task to delete.",
        )

    return True, None


def is_note_deletion_authorized(
    user_prompt: str, arguments: Any = None
) -> tuple[bool, str | None]:
    """Conservatively verify affirmative user authorization for note deletion."""
    if not user_prompt or not user_prompt.strip():
        return False, "User request is empty."

    if _has_quoted_deletion(user_prompt):
        return (
            False,
            "Deletion command appears inside quoted text rather than as an affirmative instruction.",
        )

    if _is_negated(user_prompt):
        return False, "User request contains a negated instruction regarding deletion."

    if _is_question_or_inquiry(user_prompt):
        return (
            False,
            "Questions or inquiries cannot authorize note deletion. Please confirm with an explicit deletion command.",
        )

    if _is_hypothetical_or_conditional(user_prompt):
        return (
            False,
            "Hypothetical or conditional statements cannot authorize note deletion.",
        )

    if _is_past_tense(user_prompt):
        return (
            False,
            "Request refers to a past deletion rather than an affirmative deletion instruction.",
        )

    if _is_tag_removal(user_prompt):
        return (
            False,
            "Removing tags, labels, or content attributes is not note deletion. To permanently delete the note, provide an explicit note deletion instruction.",
        )

    # Check for affirmative delete command targeting a note
    has_delete_note = bool(
        re.search(
            r"\b(?:delete|permanently\s+delete)\b.*?\bnote\w*\b",
            user_prompt,
            re.IGNORECASE,
        )
        or re.search(r"\bnote\w*\b.*?\bdelete\b", user_prompt, re.IGNORECASE)
    )
    if not has_delete_note:
        if re.search(r"\bremove\b.*?\bnote\w*\b", user_prompt, re.IGNORECASE):
            pass
        else:
            return (
                False,
                "Request does not contain a clear affirmative instruction to delete a note.",
            )

    target = _extract_note_target(user_prompt)
    if not target:
        return (
            False,
            "No identifiable note target (ID, title, or topic) was specified in the user request. Please specify which note to delete.",
        )

    return True, None


def is_deletion_authorized(
    user_prompt: str,
    tool_name: str = "delete_task",
    arguments: Any = None,
) -> bool:
    """Check if the user prompt explicitly authorizes deletion for the given tool."""
    if tool_name == "delete_task":
        auth, _ = is_task_deletion_authorized(user_prompt, arguments)
        return auth
    if tool_name == "delete_note":
        auth, _ = is_note_deletion_authorized(user_prompt, arguments)
        return auth
    return False


def validate_tool_call(
    tool_name: str,
    arguments: Any,
    user_prompt: str,
    permitted_tools: set[str],
    discovered_schemas: dict[str, dict[str, Any]],
    agent_name: str,
) -> tuple[bool, str | None, dict[str, Any]]:
    """Validate a model-generated tool call against dynamic schemas and security rules.

    Args:
        tool_name: Name of the tool requested by the model.
        arguments: Raw payload arguments produced by the model.
        user_prompt: Original user instruction to verify authorization.
        permitted_tools: Whitelist of tool names allowed for this agent.
        discovered_schemas: Mapping of tool names to their MCP inputSchema dicts.
        agent_name: Display name of the agent executing the request.

    Returns:
        (is_valid, error_message, sanitized_arguments)
    """
    # 1. Verify tool exists in discovered MCP catalog
    if tool_name not in discovered_schemas:
        return (
            False,
            f"Tool '{tool_name}' is not recognized or available on the MCP server.",
            {},
        )

    # 2. Verify agent permission whitelist
    if tool_name not in permitted_tools:
        return (
            False,
            f"Permission denied: Tool '{tool_name}' is not permitted for {agent_name}.",
            {},
        )

    # 3. Enforce operation-specific destructive tool safeguard
    if tool_name == "delete_task":
        is_auth, auth_err = is_task_deletion_authorized(user_prompt, arguments)
        if not is_auth:
            return (
                False,
                f"Destructive operation 'delete_task' was blocked: {auth_err}",
                {},
            )
    elif tool_name == "delete_note":
        is_auth, auth_err = is_note_deletion_authorized(user_prompt, arguments)
        if not is_auth:
            return (
                False,
                f"Destructive operation 'delete_note' was blocked: {auth_err}",
                {},
            )

    # 4. Verify arguments is a dictionary/object
    if not isinstance(arguments, dict):
        return (
            False,
            (
                f"Malformed tool arguments for '{tool_name}': expected a JSON object "
                f"(key-value dictionary), got {type(arguments).__name__}."
            ),
            {},
        )

    # 5. Sanitize arguments (strip None values for optional properties where type is not nullable)
    schema = discovered_schemas[tool_name]
    properties = schema.get("properties", {})
    cleaned_args: dict[str, Any] = {}

    for k, v in arguments.items():
        if v is None:
            # If property explicitly allows null in schema, keep it; otherwise omit so default applies
            prop_def = properties.get(k, {})
            any_of = prop_def.get("anyOf", [])
            type_def = prop_def.get("type")
            allows_null = type_def == "null" or any(
                sub.get("type") == "null" for sub in any_of
            )
            if allows_null:
                cleaned_args[k] = None
        else:
            cleaned_args[k] = v

    # 6. Validate against JSON Schema
    try:
        validator_cls = jsonschema.validators.validator_for(schema)
        validator = validator_cls(schema)
        errors = list(validator.iter_errors(cleaned_args))
        if errors:
            sorted_errors = sorted(errors, key=lambda e: (list(e.path), e.message))
            error_details = "; ".join(e.message for e in sorted_errors)
            return (
                False,
                f"Invalid arguments for tool '{tool_name}': {error_details}",
                cleaned_args,
            )
    except jsonschema.SchemaError as exc:
        return (
            False,
            f"Schema validation error on tool '{tool_name}': {exc}",
            cleaned_args,
        )

    return True, None, cleaned_args
