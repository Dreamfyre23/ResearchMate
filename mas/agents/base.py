"""Base agent abstraction for Multi-Agent System (MAS) agents (DEC-033).

Provides the core agent reasoning loop, tool permission filtering, Gemini
native function-calling integration, MCP tool execution via MCPHost, and
iteration-bounding protection against infinite loops.
"""

import logging
from typing import Any

from google.genai import types

from client_mcp.host import MCPHost
from client_mcp.models import ToolDescriptor
from mas.agents.gemini_agent_service import (
    AgentGeminiError,
    AgentGeminiService,
    _descriptor_to_gemini_tool,
)
from mas.agents.models import AgentRequest, AgentResponse, ToolCallRecord
from mas.agents.validator import evaluate_tool_records_success, validate_tool_call
from mas.config.settings import AgentSettings, get_agent_settings

logger = logging.getLogger(__name__)


def _response_to_tool_calls(
    response: Any,
) -> list[Any] | None:
    """Extract function calls from a Gemini GenerateContentResponse, or None."""
    try:
        candidate = response.candidates[0]
        parts = candidate.content.parts if candidate.content else []
        calls = [p.function_call for p in parts if p.function_call]
        return calls if calls else None
    except (AttributeError, IndexError):
        return None


def _response_to_text(response: Any) -> str:
    """Extract the final text from a Gemini GenerateContentResponse."""
    try:
        return response.text or ""
    except Exception:  # noqa: BLE001
        return ""


def _build_gemini_messages(
    raw_messages: list[dict[str, Any]],
) -> list[types.Content]:
    """Convert the accumulated message list into Gemini Content objects.

    The system prompt is handled separately via GenerateContentConfig, so
    this function maps only user/model/tool-result roles.

    Supported roles in raw_messages:
      - "user"          -> role="user" with text Part
      - "model"         -> role="model" with text Part
      - "function_call" -> role="model" with function_call Part(s)
      - "tool"          -> role="user" with function_response Part
    """
    contents: list[types.Content] = []
    for msg in raw_messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "user":
            contents.append(
                types.Content(
                    role="user", parts=[types.Part.from_text(text=str(content))]
                )
            )
        elif role == "model":
            contents.append(
                types.Content(
                    role="model", parts=[types.Part.from_text(text=str(content))]
                )
            )
        elif role == "model_content":
            # Exact Content object preserved from model response, keeping thought_signature
            raw_content = msg.get("content")
            if isinstance(raw_content, types.Content):
                contents.append(raw_content)
            elif raw_content is not None:
                contents.append(
                    types.Content(role="model", parts=list(raw_content.parts))
                )
        elif role == "function_call":
            fc_parts: list[types.Part] = msg.get("parts", [])
            contents.append(types.Content(role="model", parts=fc_parts))
        elif role == "tool":
            tool_name = msg.get("name", "tool")
            tool_resp = msg.get("response", {})
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_function_response(
                            name=tool_name,
                            response=tool_resp
                            if isinstance(tool_resp, dict)
                            else {"result": tool_resp},
                        )
                    ],
                )
            )
    return contents


class BaseAgent:
    """Base class for all Gemini-powered AI agents in the ResearchMate system."""

    def __init__(
        self,
        agent_name: str,
        system_prompt: str,
        permitted_tools: set[str],
        mcp_host: MCPHost,
        gemini_service: AgentGeminiService | None = None,
        settings: AgentSettings | None = None,
    ) -> None:
        self.agent_name = agent_name
        self.system_prompt = system_prompt
        self.permitted_tools = set(permitted_tools)
        self.mcp_host = mcp_host
        self.gemini_service = gemini_service or AgentGeminiService()
        self.settings = settings or get_agent_settings()

    async def get_permitted_tool_descriptors(self) -> list[ToolDescriptor]:
        """Dynamically query MCPHost for tools and filter to this agent's permitted set."""
        all_tools = await self.mcp_host.discover_tools()
        return [t for t in all_tools if t.name in self.permitted_tools]

    async def run(self, request: AgentRequest | str) -> AgentResponse:
        """Execute the agent reasoning loop for a given user request.

        1. Discovers available tools dynamically and filters to permitted set.
        2. Converts tool descriptors to Gemini Tool objects.
        3. Sends user turn to Gemini with function-calling config.
        4. Loops on function_call parts, executes tools via MCPHost, feeds
           function_response parts back to the model.
        5. Terminates on a text-only response or after max_iterations.
        """
        if isinstance(request, str):
            request = AgentRequest(prompt=request)

        prompt_text = request.prompt.strip()
        if not prompt_text:
            return AgentResponse(
                agent_name=self.agent_name,
                content="Please provide a non-empty request or instruction.",
                iterations=0,
                is_success=False,
                error="Empty request prompt",
            )

        # --- Tool discovery ---
        all_tools = await self.mcp_host.discover_tools()
        discovered_schemas = {t.name: (t.input_schema or {}) for t in all_tools}
        permitted_descriptors = [t for t in all_tools if t.name in self.permitted_tools]

        gemini_tools: list[types.Tool] = [
            _descriptor_to_gemini_tool(
                t.name, t.description or "", t.input_schema or {}
            )
            for t in permitted_descriptors
        ]

        # --- Conversation history (excludes system prompt, handled via config) ---
        raw_messages: list[dict[str, Any]] = [
            {"role": "user", "content": prompt_text},
        ]

        tool_records: list[ToolCallRecord] = []
        iteration = 0
        final_content = ""

        try:
            while iteration < self.settings.max_iterations:
                iteration += 1

                gemini_contents = _build_gemini_messages(raw_messages)

                response = await self.gemini_service.chat(
                    system_prompt=self.system_prompt,
                    messages=gemini_contents,
                    tools=gemini_tools if gemini_tools else None,
                )

                function_calls = _response_to_tool_calls(response)

                if not function_calls:
                    # No tool calls — model produced a final text response
                    final_content = _response_to_text(response)
                    is_success, eval_err = evaluate_tool_records_success(tool_records)
                    return AgentResponse(
                        agent_name=self.agent_name,
                        content=final_content,
                        tool_calls=tool_records,
                        iterations=iteration,
                        is_success=is_success,
                        error=eval_err,
                    )

                # Record model turn with function_call Part(s).
                # Preserve candidate.content from the SDK response so thought_signature is kept.
                candidate = (
                    response.candidates[0]
                    if getattr(response, "candidates", None)
                    else None
                )
                if candidate and getattr(candidate, "content", None):
                    raw_messages.append(
                        {"role": "model_content", "content": candidate.content}
                    )
                else:
                    model_parts = [
                        types.Part.from_function_call(
                            name=fc.name,
                            args=dict(fc.args) if fc.args else {},
                        )
                        for fc in function_calls
                    ]
                    raw_messages.append({"role": "function_call", "parts": model_parts})

                # --- Execute each function call ---
                for fc in function_calls:
                    func_name: str = fc.name
                    func_args: dict[str, Any] = dict(fc.args) if fc.args else {}

                    is_valid, validation_err, cleaned_args = validate_tool_call(
                        tool_name=func_name,
                        arguments=func_args,
                        user_prompt=prompt_text,
                        permitted_tools=self.permitted_tools,
                        discovered_schemas=discovered_schemas,
                        agent_name=self.agent_name,
                    )

                    if not is_valid:
                        logger.warning(
                            "Agent '%s' tool call validation failed for '%s': %s",
                            self.agent_name,
                            func_name,
                            validation_err,
                        )
                        feedback_msg = (
                            f"Validation error for tool '{func_name}': {validation_err}. "
                            "Please correct the arguments and retry. Remember that optional "
                            "nullable parameters should be JSON null or omitted, never the "
                            "string 'null'."
                        )
                        tool_result: Any = {"error": feedback_msg}
                        is_err = True
                        recorded_args = (
                            cleaned_args if isinstance(func_args, dict) else {}
                        )
                    else:
                        logger.info(
                            "Agent '%s' invoking tool '%s' with args %s",
                            self.agent_name,
                            func_name,
                            cleaned_args,
                        )
                        execution_result = await self.mcp_host.invoke_tool(
                            name=func_name,
                            arguments=cleaned_args,
                            raise_on_error=False,
                        )
                        tool_result = execution_result.data
                        is_err = execution_result.is_error
                        recorded_args = cleaned_args

                    tool_records.append(
                        ToolCallRecord(
                            tool_name=func_name,
                            arguments=recorded_args,
                            result=tool_result,
                            is_error=is_err,
                        )
                    )

                    # Feed tool result back as a function_response
                    content_data = (
                        tool_result
                        if isinstance(tool_result, dict)
                        else {"result": str(tool_result)}
                    )
                    raw_messages.append(
                        {
                            "role": "tool",
                            "name": func_name,
                            "response": content_data,
                        }
                    )

            # Exceeded iteration limit
            logger.warning(
                "Agent '%s' reached maximum iteration limit (%d)",
                self.agent_name,
                self.settings.max_iterations,
            )
            return AgentResponse(
                agent_name=self.agent_name,
                content=final_content
                or (
                    f"Agent reached maximum execution limit ({self.settings.max_iterations} "
                    "iterations) without producing a final answer."
                ),
                tool_calls=tool_records,
                iterations=iteration,
                is_success=False,
                error="Maximum iteration limit reached",
            )

        except AgentGeminiError as exc:
            safe_msg = str(exc)
            logger.error(
                "Gemini error during %s execution: %s", self.agent_name, safe_msg
            )
            return AgentResponse(
                agent_name=self.agent_name,
                content=f"Error executing request via Gemini: {safe_msg}",
                tool_calls=tool_records,
                iterations=iteration,
                is_success=False,
                error=safe_msg,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Unexpected error during %s execution: %s", self.agent_name, exc
            )
            return AgentResponse(
                agent_name=self.agent_name,
                content=f"An unexpected error occurred during execution: {exc}",
                tool_calls=tool_records,
                iterations=iteration,
                is_success=False,
                error=str(exc),
            )
