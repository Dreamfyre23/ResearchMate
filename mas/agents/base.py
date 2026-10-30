"""Base agent abstraction for local Multi-Agent System (MAS) agents (Phase 9).

Provides the core agent reasoning loop, tool permission filtering, Ollama schema conversion,
MCP tool execution via MCPHost, and iteration-bounding protection against infinite loops.
"""

import json
import logging
from typing import Any

from client_mcp.host import MCPHost
from client_mcp.models import ToolDescriptor
from mas.agents.models import AgentRequest, AgentResponse, ToolCallRecord
from mas.agents.validator import validate_tool_call
from mas.config.settings import AgentSettings, get_agent_settings
from mas.ollama.client import OllamaService
from mas.ollama.exceptions import OllamaError

logger = logging.getLogger(__name__)


def _descriptor_to_ollama(tool: ToolDescriptor) -> dict[str, Any]:
    """Convert an MCP ToolDescriptor into the standard Ollama function tool format."""
    schema = (
        tool.input_schema if tool.input_schema else {"type": "object", "properties": {}}
    )
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": schema,
        },
    }


class BaseAgent:
    """Base class for all local AI agents in the ResearchMate system."""

    def __init__(
        self,
        agent_name: str,
        system_prompt: str,
        permitted_tools: set[str],
        mcp_host: MCPHost,
        ollama_service: OllamaService | None = None,
        settings: AgentSettings | None = None,
    ) -> None:
        self.agent_name = agent_name
        self.system_prompt = system_prompt
        self.permitted_tools = set(permitted_tools)
        self.mcp_host = mcp_host
        self.ollama_service = ollama_service or OllamaService()
        self.settings = settings or get_agent_settings()

    async def get_permitted_tool_descriptors(self) -> list[ToolDescriptor]:
        """Dynamically query MCPHost for tools and filter to this agent's permitted set."""
        all_tools = await self.mcp_host.discover_tools()
        return [t for t in all_tools if t.name in self.permitted_tools]

    async def run(self, request: AgentRequest | str) -> AgentResponse:
        """Execute the agent reasoning loop for a given user request.

        1. Discovers available tools dynamically and filters strictly to permitted tools.
        2. Formats messages and calls Ollama with tools.
        3. Loops tool calls until final response or max iterations reached.
        4. Bounds iterations to prevent infinite loops (8GB RAM optimization).
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

        # 1. Discover tools and input schemas dynamically
        all_tools = await self.mcp_host.discover_tools()
        discovered_schemas = {t.name: (t.input_schema or {}) for t in all_tools}
        permitted_descriptors = [t for t in all_tools if t.name in self.permitted_tools]
        ollama_tools = [_descriptor_to_ollama(t) for t in permitted_descriptors]

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt_text},
        ]

        tool_records: list[ToolCallRecord] = []
        iteration = 0
        final_content = ""

        try:
            while iteration < self.settings.max_iterations:
                iteration += 1

                # Send request to local Ollama model
                response = await self.ollama_service.chat(
                    messages=messages,
                    tools=ollama_tools if ollama_tools else None,
                )

                response_message = response.message
                tool_calls = getattr(response_message, "tool_calls", None)

                # Check if the model produced tool calls or final answer
                if not tool_calls:
                    final_content = response_message.content or ""
                    return AgentResponse(
                        agent_name=self.agent_name,
                        content=final_content,
                        tool_calls=tool_records,
                        iterations=iteration,
                        is_success=True,
                    )

                # Append assistant message with tool calls to history
                messages.append(response_message)

                # Execute each tool call requested by the model
                for tc in tool_calls:
                    func_name = tc.function.name
                    func_args = tc.function.arguments

                    # Validate tool call against schema and safety policies
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
                        tool_result: Any = {"error": validation_err}
                        is_err = True
                        recorded_args = (
                            cleaned_args
                            if isinstance(func_args, dict)
                            else {"raw_arguments": func_args}
                        )
                    else:
                        # Invoke tool via MCPHost
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

                    # Serialize result back to model in tool role
                    content_str = (
                        json.dumps(tool_result)
                        if not isinstance(tool_result, str)
                        else tool_result
                    )
                    messages.append({"role": "tool", "content": content_str})

            # Exceeded maximum loop limit
            logger.warning(
                "Agent '%s' reached maximum iteration limit (%d)",
                self.agent_name,
                self.settings.max_iterations,
            )
            return AgentResponse(
                agent_name=self.agent_name,
                content=final_content
                or (
                    f"Agent reached maximum execution limit ({self.settings.max_iterations} iterations) "
                    "without producing a final answer."
                ),
                tool_calls=tool_records,
                iterations=iteration,
                is_success=False,
                error="Maximum iteration limit reached",
            )

        except OllamaError as exc:
            logger.error("Ollama error during %s execution: %s", self.agent_name, exc)
            return AgentResponse(
                agent_name=self.agent_name,
                content=f"Error executing request via local model: {exc}",
                tool_calls=tool_records,
                iterations=iteration,
                is_success=False,
                error=str(exc),
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
