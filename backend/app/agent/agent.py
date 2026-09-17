"""Autonomous model-driven AI Agent orchestrator for sandbox execution."""

import asyncio
import logging
from typing import Any

from pydantic import BaseModel, Field

from app.agent.llm.base import LLMMessage, LLMProvider
from app.agent.prompts import DEFAULT_SYSTEM_PROMPT
from app.agent.schemas import AGENT_TOOLS, AgentToolDefinition, AgentToolError
from app.agent.tools import execute_agent_tool
from app.core.config import SandboxSettings, settings
from app.core.exceptions import (
    AgentMaxIterationsError,
    AgentTimeoutError,
    LLMProviderError,
)
from app.services.sandbox_lifecycle_service import SandboxLifecycleService

logger = logging.getLogger(__name__)


class AgentRunResult(BaseModel):
    """Structured result returned by an agent execution run."""

    response: str = Field(..., description="Final natural-language response from the agent")
    iterations: int = Field(..., ge=1, description="Total LLM reasoning iterations completed")
    tool_calls_count: int = Field(default=0, ge=0, description="Total tool calls executed")
    messages: list[LLMMessage] = Field(
        default_factory=list,
        description="Complete conversation message history including tool calls and outputs",
    )


class SandboxAgent:
    """Autonomous agent running a model-driven tool calling loop against sandbox tools."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        service: SandboxLifecycleService,
        config: SandboxSettings = settings,
        system_prompt: str | None = None,
        tools: dict[str, AgentToolDefinition] | None = None,
    ) -> None:
        self.llm = llm_provider
        self.service = service
        self.config = config
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self.tools = tools if tools is not None else AGENT_TOOLS
        self.max_iterations = config.AGENT_MAX_ITERATIONS
        self.request_timeout = config.AGENT_REQUEST_TIMEOUT

    def _format_tools_for_llm(self) -> list[dict[str, Any]]:
        """Convert registered tool definitions into standard JSON Schema declarations."""
        return [
            {
                "name": tool_def.name,
                "description": tool_def.description,
                "parameters": tool_def.parameters,
            }
            for tool_def in self.tools.values()
        ]

    async def run(
        self,
        prompt: str,
        history: list[LLMMessage] | None = None,
        timeout_seconds: float | None = None,
    ) -> AgentRunResult:
        """Execute the bounded model-driven agent tool-calling loop.

        Workflow:
        1. Initialize conversation with system prompt and user prompt (or prior history).
        2. Prompt the LLM with available sandbox tools.
        3. If LLM decides a tool is needed:
           - Validate arguments against tool Pydantic schema.
           - Execute existing sandbox lifecycle tool.
           - Append tool result to conversation.
           - Send updated conversation back to LLM.
        4. Repeat until model decides no further tools are needed and produces a final answer.
        5. Enforce bounded iteration limits and timeout.
        """
        effective_timeout = (
            timeout_seconds
            if timeout_seconds is not None and timeout_seconds > 0
            else self.request_timeout
        )

        messages: list[LLMMessage] = []
        if history:
            messages.extend(history)
        else:
            messages.append(LLMMessage(role="system", content=self.system_prompt))
            messages.append(LLMMessage(role="user", content=prompt))

        formatted_tools = self._format_tools_for_llm()
        iterations = 0
        total_tool_calls = 0

        try:
            async with asyncio.timeout(effective_timeout):
                while iterations < self.max_iterations:
                    iterations += 1

                    # 1. Ask model for next action
                    try:
                        llm_response = await self.llm.generate_response(
                            messages=messages,
                            tools=formatted_tools,
                        )
                    except LLMProviderError:
                        raise
                    except Exception as exc:
                        logger.error(f"LLM communication error in agent loop: {exc}")
                        raise LLMProviderError(
                            f"LLM provider failed during agent execution: {exc}"
                        ) from exc

                    # 2. Check if model requested any tool calls
                    if not llm_response.has_tool_calls:
                        # Model generated final answer
                        final_text = llm_response.content or ""
                        messages.append(LLMMessage(role="assistant", content=final_text))
                        return AgentRunResult(
                            response=final_text,
                            iterations=iterations,
                            tool_calls_count=total_tool_calls,
                            messages=messages,
                        )

                    # 3. Append assistant message containing tool calls
                    messages.append(
                        LLMMessage(
                            role="assistant",
                            content=llm_response.content,
                            tool_calls=llm_response.tool_calls,
                        )
                    )

                    # 4. Dispatch each requested tool call
                    for tc in llm_response.tool_calls:
                        total_tool_calls += 1
                        tool_name = tc.name
                        tool_args = tc.arguments

                        logger.info(
                            f"Agent iteration {iterations}: executing tool '{tool_name}' "
                            f"(call_id={tc.id})"
                        )

                        if tool_name not in self.tools:
                            tool_result = AgentToolError(
                                error="UnknownToolError",
                                message=(
                                    f"Tool '{tool_name}' is not recognized. "
                                    f"Available tools: {list(self.tools.keys())}"
                                ),
                                details={"requested_tool": tool_name},
                            )
                        else:
                            # Reuses thin adapter layer with schema validation & service
                            tool_result = await execute_agent_tool(
                                tool_name=tool_name,
                                arguments=tool_args,
                                service=self.service,
                            )

                        # Serialize tool result deterministically to JSON
                        if hasattr(tool_result, "model_dump_json"):
                            result_json = tool_result.model_dump_json()
                        else:
                            result_json = str(tool_result)

                        # Append tool response message to conversation state
                        messages.append(
                            LLMMessage(
                                role="tool",
                                name=tool_name,
                                tool_call_id=tc.id,
                                content=result_json,
                            )
                        )

                # Reached max iterations without final text answer
                logger.warning(
                    f"Agent reached max iterations limit ({self.max_iterations}) "
                    "without final answer"
                )
                raise AgentMaxIterationsError(
                    f"Agent exceeded maximum permitted iterations ({self.max_iterations}) "
                    "without completing.",
                    details={
                        "max_iterations": self.max_iterations,
                        "tool_calls_count": total_tool_calls,
                    },
                )

        except TimeoutError as exc:
            logger.warning(f"Agent execution timed out after {effective_timeout}s")
            raise AgentTimeoutError(
                f"Agent execution exceeded configured timeout of {effective_timeout} seconds.",
                details={
                    "timeout_seconds": effective_timeout,
                    "iterations": iterations,
                    "tool_calls_count": total_tool_calls,
                },
            ) from exc
