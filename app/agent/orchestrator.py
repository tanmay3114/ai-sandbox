"""Agent Orchestrator with bounded execution, loop detection, and lifecycle integration."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.agent.llm.base import LLMMessage, LLMProvider
from app.agent.tool_registry import AgentToolRegistry
from app.core.config import SandboxSettings, settings
from app.core.exceptions import (
    AgentCancelledError,
    AgentMaxIterationsError,
    AgentMaxToolCallsError,
    AgentTimeoutError,
    LLMProviderError,
    SandboxDestroyedError,
    SandboxExpiredError,
)
from app.models.sandbox import SandboxStatus
from app.services.sandbox_lifecycle_service import SandboxLifecycleService

logger = logging.getLogger(__name__)


@dataclass
class AgentExecutionContext:
    """Execution state tracking for an active agent orchestration task."""

    task_id: uuid.UUID
    sandbox_id: uuid.UUID
    prompt: str
    iteration: int = 0
    tool_calls_count: int = 0
    execution_ids: list[uuid.UUID] = field(default_factory=list)
    tool_history: list[dict[str, Any]] = field(default_factory=list)
    messages: list[LLMMessage] = field(default_factory=list)
    cancelled: bool = False
    _recent_tool_signatures: list[str] = field(default_factory=list)

    def record_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        raw_output: str,
    ) -> None:
        """Record a completed tool invocation in bounded structured history."""
        self.tool_calls_count += 1

        # Check for error in tool response
        is_error = False
        execution_id: str | None = None
        try:
            parsed = json.loads(raw_output)
            if isinstance(parsed, dict):
                if "error" in parsed:
                    is_error = True
                if "execution_id" in parsed:
                    execution_id = parsed["execution_id"]
                    try:
                        self.execution_ids.append(uuid.UUID(execution_id))
                    except (ValueError, TypeError):
                        pass
        except Exception:
            pass

        # Bounded representation of arguments (avoiding huge write_file contents in history)
        safe_args = dict(arguments)
        if "content" in safe_args and isinstance(safe_args["content"], str):
            if len(safe_args["content"]) > 120:
                safe_args["content"] = safe_args["content"][:120] + "... [truncated]"

        self.tool_history.append(
            {
                "tool": tool_name,
                "arguments": safe_args,
                "is_error": is_error,
                "execution_id": execution_id,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

        # Track signature for infinite loop detection
        sig = f"{tool_name}:{sorted(safe_args.items())}"
        self._recent_tool_signatures.append(sig)

    def is_looping(self, max_consecutive: int) -> bool:
        """Detect if the agent is stuck in an identical consecutive tool-call loop."""
        if len(self._recent_tool_signatures) < max_consecutive:
            return False
        last_sig = self._recent_tool_signatures[-1]
        return all(s == last_sig for s in self._recent_tool_signatures[-max_consecutive:])

    def get_bounded_messages(self, max_messages: int = 40) -> list[LLMMessage]:
        """Return conversation messages bounded to prevent token context explosion."""
        if len(self.messages) <= max_messages:
            return self.messages

        # Always preserve system prompt (index 0) and original user prompt (index 1)
        system_msg = self.messages[0]
        user_msg = self.messages[1]
        tail = self.messages[-(max_messages - 2) :]
        return [system_msg, user_msg] + tail


class AgentTaskResult(BaseModel):
    """Structured result produced by the Agent Orchestrator."""

    task_id: uuid.UUID
    sandbox_id: uuid.UUID
    status: str
    final_response: str = ""
    iterations: int = 0
    tool_calls_count: int = 0
    execution_ids: list[uuid.UUID] = Field(default_factory=list)
    tool_history: list[dict[str, Any]] = Field(default_factory=list)
    error_message: str | None = None
    error_type: str | None = None


class AgentOrchestrator:
    """Manages the agent task execution loop against an authorized sandbox session."""

    def __init__(
        self,
        llm: LLMProvider,
        service: SandboxLifecycleService,
        config: SandboxSettings = settings,
    ) -> None:
        self.llm = llm
        self.service = service
        self.config = config
        self.max_iterations = config.AGENT_MAX_ITERATIONS
        self.max_tool_calls = config.AGENT_MAX_TOOL_CALLS
        self.request_timeout = config.AGENT_REQUEST_TIMEOUT
        self.max_consecutive_repeats = config.AGENT_MAX_CONSECUTIVE_REPEATS

    def _build_system_prompt(self, sandbox_id: uuid.UUID) -> str:
        """Construct context-aware system prompt disclosing sandbox information and files."""
        # 1. Inspect sandbox
        sandbox = self.service.get_sandbox(sandbox_id)

        # 2. Inspect existing workspace files
        file_summary = "None (empty workspace)"
        try:
            files_resp = self.service.list_files(sandbox_id)
            if files_resp.files:
                file_summary = ", ".join(f.path for f in files_resp.files[:20])
        except Exception:
            pass

        return f"""You are an autonomous AI coding assistant connected to an isolated sandbox.

Sandbox Session Context:
- Sandbox ID: {sandbox.id}
- Runtime: {sandbox.runtime}
- Status: {sandbox.status}
- Existing Workspace Files: {file_summary}

Available Tools:
1. get_sandbox: Inspect active session status, remaining TTL, and execution counts.
2. list_files: List files and directories in your persistent workspace.
3. read_file: Read file content from your persistent workspace.
4. write_file: Create or modify files in your persistent workspace.
5. create_directory: Create directories in your persistent workspace.
6. delete_file: Delete files or empty directories in your persistent workspace.
7. execute_code: Run Python code inside a fresh ephemeral container.
8. get_execution_result: Inspect full stdout, stderr, and exit code of a past execution job.

Instructions & Problem-Solving Guidelines:
- Inspect existing workspace files or sandbox information if necessary.
- Write programs using write_file and execute them using execute_code.
- Inspect execution exit_code, stdout, and stderr.
- A non-zero exit code indicates a program error. If a script fails, analyze the stderr traceback,
  correct the code using write_file or execute_code, and re-run to verify the fix.
- Verify that requirements have been completely met before presenting your final answer.
- Once completed, provide a concise, natural-language explanation of the outcome and results.
"""

    async def run_task(
        self,
        task_id: uuid.UUID,
        sandbox_id: uuid.UUID,
        prompt: str,
        timeout_seconds: float | None = None,
        cancellation_token: asyncio.Event | None = None,
        is_cancelled_func: Callable[[], bool] | None = None,
    ) -> AgentTaskResult:
        """Run the bounded agent orchestration loop against an authorized sandbox."""
        effective_timeout = (
            timeout_seconds
            if timeout_seconds is not None and timeout_seconds > 0
            else self.request_timeout
        )

        def _check_cancellation(stage: str) -> None:
            if (cancellation_token and cancellation_token.is_set()) or (
                is_cancelled_func and is_cancelled_func()
            ):
                raise AgentCancelledError(
                    f"Agent task was cancelled by user ({stage}).",
                    details={"task_id": str(task_id), "stage": stage},
                )

        # 1. Pre-flight sandbox verification
        sandbox = self.service.get_sandbox(sandbox_id)
        if sandbox.status == SandboxStatus.EXPIRED or sandbox.is_expired:
            raise SandboxExpiredError(
                f"Cannot execute agent task in expired sandbox '{sandbox_id}'.",
                details={"sandbox_id": str(sandbox_id)},
            )
        if sandbox.status == SandboxStatus.DESTROYED:
            raise SandboxDestroyedError(
                f"Cannot execute agent task in destroyed sandbox '{sandbox_id}'.",
                details={"sandbox_id": str(sandbox_id)},
            )

        # 2. Initialize Tool Registry and Context
        registry = AgentToolRegistry(
            service=self.service,
            authorized_sandbox_id=sandbox_id,
            max_output_bytes=self.config.AGENT_MAX_TOOL_RESULT_BYTES,
        )

        system_prompt = self._build_system_prompt(sandbox_id)
        context = AgentExecutionContext(
            task_id=task_id,
            sandbox_id=sandbox_id,
            prompt=prompt,
            messages=[
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(role="user", content=prompt),
            ],
        )

        formatted_tools = registry.get_definitions()

        # 3. Execute bounded orchestration loop
        try:
            async with asyncio.timeout(effective_timeout):
                while context.iteration < self.max_iterations:
                    # Check cancellation
                    _check_cancellation("iteration_start")

                    context.iteration += 1
                    logger.info(
                        "Agent task %s [sandbox %s] iteration %d/%d",
                        task_id,
                        sandbox_id,
                        context.iteration,
                        self.max_iterations,
                    )

                    # Revalidate sandbox lifecycle before model turn
                    current_sb = self.service.get_sandbox(sandbox_id)
                    if current_sb.is_expired or current_sb.status == SandboxStatus.EXPIRED:
                        raise SandboxExpiredError(
                            f"Sandbox '{sandbox_id}' expired during task execution.",
                            details={"sandbox_id": str(sandbox_id)},
                        )
                    if current_sb.status == SandboxStatus.DESTROYED:
                        raise SandboxDestroyedError(
                            f"Sandbox '{sandbox_id}' was destroyed during task execution.",
                            details={"sandbox_id": str(sandbox_id)},
                        )

                    # Ask model for next action
                    try:
                        llm_resp = await self.llm.generate_response(
                            messages=context.get_bounded_messages(),
                            tools=formatted_tools,
                        )
                    except LLMProviderError:
                        raise
                    except Exception as exc:
                        logger.error("LLM communication failure during agent task: %s", exc)
                        raise LLMProviderError(
                            f"AI model provider communication failed: {exc}"
                        ) from exc

                    # If model didn't request tools, it has arrived at a final response
                    if not llm_resp.has_tool_calls:
                        final_text = llm_resp.content or ""
                        context.messages.append(LLMMessage(role="assistant", content=final_text))
                        logger.info("Agent task %s converged with final answer.", task_id)
                        return AgentTaskResult(
                            task_id=task_id,
                            sandbox_id=sandbox_id,
                            status="completed",
                            final_response=final_text,
                            iterations=context.iteration,
                            tool_calls_count=context.tool_calls_count,
                            execution_ids=context.execution_ids,
                            tool_history=context.tool_history,
                        )

                    # Append model turn containing tool calls
                    context.messages.append(
                        LLMMessage(
                            role="assistant",
                            content=llm_resp.content,
                            tool_calls=llm_resp.tool_calls,
                        )
                    )

                    # Dispatch each requested tool call
                    for tc in llm_resp.tool_calls:
                        _check_cancellation("before_tool_execution")

                        if context.tool_calls_count >= self.max_tool_calls:
                            msg = f"Agent task exceeded maximum tool calls ({self.max_tool_calls})."
                            raise AgentMaxToolCallsError(
                                msg,
                                details={"max_tool_calls": self.max_tool_calls},
                            )

                        logger.info(
                            "Agent task %s executing tool '%s' (call_id=%s)",
                            task_id,
                            tc.name,
                            tc.id,
                        )

                        # Execute tool through security-enforced registry
                        tool_output = await registry.execute(tc.name, tc.arguments)

                        # Record call in structured task history
                        context.record_tool_call(tc.name, tc.arguments, tool_output)

                        # Loop breaker guidance
                        if context.is_looping(self.max_consecutive_repeats):
                            tool_output += (
                                "\n\n[SYSTEM ADVISORY: You executed this identical tool call "
                                f"{self.max_consecutive_repeats} consecutive times without change. "
                                "Do not repeat it. Please diagnose or provide a final explanation.]"
                            )

                        # Append tool response turn to conversation
                        context.messages.append(
                            LLMMessage(
                                role="tool",
                                name=tc.name,
                                tool_call_id=tc.id,
                                content=tool_output,
                            )
                        )

                # Loop exceeded maximum iterations
                logger.warning(
                    "Agent task %s reached max iterations (%d)", task_id, self.max_iterations
                )
                msg = f"Agent task exceeded max iterations ({self.max_iterations}) without finish."
                raise AgentMaxIterationsError(
                    msg,
                    details={
                        "max_iterations": self.max_iterations,
                        "tool_calls_count": context.tool_calls_count,
                    },
                )

        except TimeoutError as exc:
            logger.warning("Agent task %s timed out after %fs", task_id, effective_timeout)
            raise AgentTimeoutError(
                f"Agent task execution exceeded timeout of {effective_timeout} seconds.",
                details={
                    "timeout_seconds": effective_timeout,
                    "iterations": context.iteration,
                    "tool_calls_count": context.tool_calls_count,
                },
            ) from exc
