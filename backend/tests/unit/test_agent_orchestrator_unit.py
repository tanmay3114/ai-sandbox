"""Unit tests for Phase 5 Agent Orchestrator, Tool Registry, and Task State Persistence."""

import asyncio
import uuid
from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.agent.llm.base import LLMMessage, LLMProvider, LLMResponse, ToolCallRequest
from app.agent.orchestrator import AgentExecutionContext, AgentOrchestrator
from app.agent.tool_registry import AgentToolRegistry
from app.core.config import SandboxSettings
from app.core.exceptions import (
    AgentCancelledError,
    AgentMaxIterationsError,
    AgentMaxToolCallsError,
    SandboxDestroyedError,
    SandboxExpiredError,
)
from app.models.agent_task import AgentTask, TaskStatus
from app.models.sandbox import (
    InvalidStateTransitionError,
    Sandbox,
    SandboxStatus,
    utc_now,
)
from app.services.sandbox_lifecycle_service import SandboxLifecycleService


class MockLLM(LLMProvider):
    """Deterministic mock provider returning sequential pre-programmed responses."""

    def __init__(self, responses: list[LLMResponse | Exception]) -> None:
        self.responses = list(responses)
        self.history: list[list[LLMMessage]] = []

    async def generate_response(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.history.append(list(messages))
        if not self.responses:
            raise RuntimeError("MockLLM has no more scripted responses.")
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


# -----------------------------------------------------------------------------
# 1. Tool Registry & Security Boundary Tests
# -----------------------------------------------------------------------------


def test_tool_registry_initialization():
    """Verify tool registry registers exactly the 8 controlled sandbox tools."""
    mock_service = MagicMock(spec=SandboxLifecycleService)
    sandbox_id = uuid.uuid4()
    registry = AgentToolRegistry(service=mock_service, authorized_sandbox_id=sandbox_id)

    expected_tools = {
        "get_sandbox",
        "list_files",
        "read_file",
        "write_file",
        "create_directory",
        "delete_file",
        "execute_code",
        "get_execution_result",
    }
    assert set(registry.tool_names) == expected_tools

    # Verify JSON Schema exports
    definitions = registry.get_definitions()
    assert len(definitions) == 8
    def_names = {d["name"] for d in definitions}
    assert def_names == expected_tools


@pytest.mark.asyncio
async def test_tool_registry_enforces_authorized_sandbox_id():
    """Verify tool calls attempting cross-sandbox access are blocked with AgentSecurityError."""
    mock_service = MagicMock(spec=SandboxLifecycleService)
    authorized_id = uuid.uuid4()
    attacker_id = uuid.uuid4()
    registry = AgentToolRegistry(service=mock_service, authorized_sandbox_id=authorized_id)

    # Calling tool with different sandbox_id must return AccessDeniedError
    output = await registry.execute(
        "read_file",
        {"sandbox_id": str(attacker_id), "path": "secret.txt"},
    )
    assert "AccessDeniedError" in output
    assert "strictly restricted to authorized sandbox" in output
    mock_service.read_file.assert_not_called()


@pytest.mark.asyncio
async def test_tool_registry_auto_binds_missing_sandbox_id():
    """Verify tool calls omitting sandbox_id are automatically bound to authorized sandbox."""
    mock_service = MagicMock(spec=SandboxLifecycleService)
    authorized_id = uuid.uuid4()
    registry = AgentToolRegistry(service=mock_service, authorized_sandbox_id=authorized_id)

    mock_service.list_files.return_value = MagicMock(model_dump_json=lambda: '{"files": []}')

    output = await registry.execute("list_files", {"path": ""})
    assert "files" in output
    mock_service.list_files.assert_called_once_with(
        sandbox_id=authorized_id,
        path="",
    )


@pytest.mark.asyncio
async def test_tool_registry_rejects_invalid_tool_name():
    """Verify unknown tool name returns deterministic UnknownToolError."""
    mock_service = MagicMock(spec=SandboxLifecycleService)
    registry = AgentToolRegistry(service=mock_service, authorized_sandbox_id=uuid.uuid4())

    output = await registry.execute("drop_database", {"table": "all"})
    assert "UnknownToolError" in output
    assert "drop_database" in output


@pytest.mark.asyncio
async def test_tool_registry_truncates_oversized_output():
    """Verify tool outputs exceeding max_output_bytes are safely truncated."""
    mock_service = MagicMock(spec=SandboxLifecycleService)
    registry = AgentToolRegistry(
        service=mock_service,
        authorized_sandbox_id=uuid.uuid4(),
        max_output_bytes=200,
    )

    mock_service.read_file.return_value = MagicMock(model_dump_json=lambda: "A" * 1000)

    output = await registry.execute("read_file", {"path": "huge.txt"})
    assert len(output.encode("utf-8")) < 500
    assert "Tool output truncated" in output


# -----------------------------------------------------------------------------
# 2. Execution Context & Loop Detection Tests
# -----------------------------------------------------------------------------


def test_context_loop_detection():
    """Verify context identifies consecutive identical tool invocations."""
    ctx = AgentExecutionContext(
        task_id=uuid.uuid4(),
        sandbox_id=uuid.uuid4(),
        prompt="Fix my code",
    )

    # Initial state
    assert not ctx.is_looping(max_consecutive=3)

    # Record 3 identical calls
    for _ in range(3):
        ctx.record_tool_call(
            tool_name="execute_code",
            arguments={"code": "print(1/0)"},
            raw_output='{"error": "ZeroDivisionError"}',
        )

    assert ctx.is_looping(max_consecutive=3)
    assert ctx.tool_calls_count == 3
    assert len(ctx.tool_history) == 3


def test_context_bounded_messages():
    """Verify bounded messages preservation preserves system prompt and user prompt."""
    ctx = AgentExecutionContext(
        task_id=uuid.uuid4(),
        sandbox_id=uuid.uuid4(),
        prompt="User prompt",
    )
    ctx.messages = [
        LLMMessage(role="system", content="System Prompt"),
        LLMMessage(role="user", content="User prompt"),
    ] + [LLMMessage(role="assistant", content=f"Step {i}") for i in range(50)]

    bounded = ctx.get_bounded_messages(max_messages=10)
    assert len(bounded) == 10
    assert bounded[0].content == "System Prompt"
    assert bounded[1].content == "User prompt"
    assert bounded[-1].content == "Step 49"


# -----------------------------------------------------------------------------
# 3. Agent Task State Machine & Transitions Tests
# -----------------------------------------------------------------------------


def test_agent_task_lifecycle_transitions():
    """Verify AgentTask state transitions conform to valid transition matrix."""
    task = AgentTask(
        id=uuid.uuid4(),
        sandbox_id=uuid.uuid4(),
        task_description="Test task",
        status=TaskStatus.PENDING,
    )

    # PENDING -> RUNNING
    assert task.can_transition_to(TaskStatus.RUNNING)
    task.transition_to(TaskStatus.RUNNING)
    assert task.status == TaskStatus.RUNNING

    # RUNNING -> COMPLETED
    assert task.can_transition_to(TaskStatus.COMPLETED)
    task.transition_to(TaskStatus.COMPLETED)
    assert task.status == TaskStatus.COMPLETED

    # COMPLETED is terminal
    assert not task.can_transition_to(TaskStatus.RUNNING)
    assert not task.can_transition_to(TaskStatus.FAILED)
    with pytest.raises(InvalidStateTransitionError):
        task.transition_to(TaskStatus.RUNNING)


def test_agent_task_cancellation_transition():
    """Verify PENDING and RUNNING tasks can transition to CANCELLED."""
    task = AgentTask(
        id=uuid.uuid4(),
        sandbox_id=uuid.uuid4(),
        task_description="Test task",
        status=TaskStatus.PENDING,
    )
    assert task.can_transition_to(TaskStatus.CANCELLED)
    task.transition_to(TaskStatus.CANCELLED)
    assert task.status == TaskStatus.CANCELLED


# -----------------------------------------------------------------------------
# 4. Orchestrator Limits & Safeguards Tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_max_iterations_enforced():
    """Verify orchestrator raises AgentMaxIterationsError when limit is reached."""
    mock_service = MagicMock(spec=SandboxLifecycleService)
    mock_sandbox = Sandbox(
        id=uuid.uuid4(),
        status=SandboxStatus.RUNNING,
        runtime="python",
        ttl_seconds=300,
        expires_at=utc_now() + timedelta(seconds=300),
    )
    mock_service.get_sandbox.return_value = mock_sandbox
    mock_service.list_files.return_value = MagicMock(files=[])

    # Mock LLM that endlessly calls get_sandbox
    looping_responses = [
        LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(id=f"c_{i}", name="get_sandbox", arguments={})],
            finish_reason="tool_calls",
        )
        for i in range(10)
    ]
    mock_llm = MockLLM(looping_responses)

    cfg = SandboxSettings(AGENT_MAX_ITERATIONS=3, AGENT_MAX_TOOL_CALLS=10)
    orchestrator = AgentOrchestrator(llm=mock_llm, service=mock_service, config=cfg)

    with pytest.raises(AgentMaxIterationsError) as exc_info:
        await orchestrator.run_task(
            task_id=uuid.uuid4(),
            sandbox_id=mock_sandbox.id,
            prompt="Endless loop task",
        )
    assert exc_info.value.details["max_iterations"] == 3


@pytest.mark.asyncio
async def test_orchestrator_max_tool_calls_enforced():
    """Verify orchestrator raises AgentMaxToolCallsError when tool calls exceed limit."""
    mock_service = MagicMock(spec=SandboxLifecycleService)
    mock_sandbox = Sandbox(
        id=uuid.uuid4(),
        status=SandboxStatus.RUNNING,
        runtime="python",
        ttl_seconds=300,
        expires_at=utc_now() + timedelta(seconds=300),
    )
    mock_service.get_sandbox.return_value = mock_sandbox
    mock_service.list_files.return_value = MagicMock(files=[])

    # LLM requests 4 tool calls in one iteration
    multi_call_response = LLMResponse(
        content=None,
        tool_calls=[
            ToolCallRequest(id=f"c_{i}", name="list_files", arguments={}) for i in range(4)
        ],
        finish_reason="tool_calls",
    )
    mock_llm = MockLLM([multi_call_response])

    cfg = SandboxSettings(AGENT_MAX_ITERATIONS=10, AGENT_MAX_TOOL_CALLS=2)
    orchestrator = AgentOrchestrator(llm=mock_llm, service=mock_service, config=cfg)

    with pytest.raises(AgentMaxToolCallsError) as exc_info:
        await orchestrator.run_task(
            task_id=uuid.uuid4(),
            sandbox_id=mock_sandbox.id,
            prompt="Too many tools",
        )
    assert exc_info.value.details["max_tool_calls"] == 2


@pytest.mark.asyncio
async def test_orchestrator_cancellation_token():
    """Verify orchestrator aborts when cancellation token is signaled."""
    mock_service = MagicMock(spec=SandboxLifecycleService)
    mock_sandbox = Sandbox(
        id=uuid.uuid4(),
        status=SandboxStatus.RUNNING,
        runtime="python",
        ttl_seconds=300,
        expires_at=utc_now() + timedelta(seconds=300),
    )
    mock_service.get_sandbox.return_value = mock_sandbox
    mock_service.list_files.return_value = MagicMock(files=[])

    cancel_event = asyncio.Event()
    cancel_event.set()  # Cancelled prior to execution

    mock_llm = MockLLM([])
    orchestrator = AgentOrchestrator(llm=mock_llm, service=mock_service)

    with pytest.raises(AgentCancelledError):
        await orchestrator.run_task(
            task_id=uuid.uuid4(),
            sandbox_id=mock_sandbox.id,
            prompt="Cancelled task",
            cancellation_token=cancel_event,
        )


@pytest.mark.asyncio
async def test_orchestrator_rejects_expired_sandbox():
    """Verify orchestrator immediately rejects task on an expired sandbox."""
    mock_service = MagicMock(spec=SandboxLifecycleService)
    mock_sandbox = Sandbox(
        id=uuid.uuid4(),
        status=SandboxStatus.EXPIRED,
        runtime="python",
        ttl_seconds=300,
        expires_at=utc_now() - timedelta(seconds=10),
    )
    mock_service.get_sandbox.return_value = mock_sandbox

    orchestrator = AgentOrchestrator(llm=MockLLM([]), service=mock_service)

    with pytest.raises(SandboxExpiredError):
        await orchestrator.run_task(
            task_id=uuid.uuid4(),
            sandbox_id=mock_sandbox.id,
            prompt="Do something in expired sandbox",
        )


@pytest.mark.asyncio
async def test_orchestrator_rejects_destroyed_sandbox():
    """Verify orchestrator immediately rejects task on a destroyed sandbox."""
    mock_service = MagicMock(spec=SandboxLifecycleService)
    mock_sandbox = Sandbox(
        id=uuid.uuid4(),
        status=SandboxStatus.DESTROYED,
        runtime="python",
        ttl_seconds=300,
        expires_at=utc_now() + timedelta(seconds=300),
        destroyed_at=utc_now(),
    )
    mock_service.get_sandbox.return_value = mock_sandbox

    orchestrator = AgentOrchestrator(llm=MockLLM([]), service=mock_service)

    with pytest.raises(SandboxDestroyedError):
        await orchestrator.run_task(
            task_id=uuid.uuid4(),
            sandbox_id=mock_sandbox.id,
            prompt="Do something in destroyed sandbox",
        )
