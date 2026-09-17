"""Unit tests for the model-driven AI Agent loop."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agent.agent import AgentRunResult, SandboxAgent
from app.agent.llm.base import LLMMessage, LLMProvider, LLMResponse, ToolCallRequest
from app.core.config import SandboxSettings
from app.core.exceptions import (
    AgentMaxIterationsError,
    AgentTimeoutError,
    LLMProviderError,
    SandboxNotFoundError,
)
from app.models.sandbox import utc_now
from app.schemas.sandbox import JobExecutionResponse
from app.services.sandbox_lifecycle_service import SandboxLifecycleService


class FakeLLMProvider(LLMProvider):
    """Configurable test double for LLMProvider generating sequential responses."""

    def __init__(self, responses: list[LLMResponse | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def generate_response(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.calls.append({"messages": list(messages), "tools": tools})
        if not self.responses:
            raise RuntimeError("FakeLLMProvider ran out of mock responses.")
        next_resp = self.responses.pop(0)
        if isinstance(next_resp, Exception):
            raise next_resp
        return next_resp


@pytest.fixture
def mock_service() -> MagicMock:
    """Mocked SandboxLifecycleService."""
    service = MagicMock(spec=SandboxLifecycleService)
    return service


@pytest.mark.asyncio
async def test_agent_normal_text_response(mock_service: MagicMock):
    """Test standard flow where LLM provides a final text response without tool calls."""
    fake_llm = FakeLLMProvider(
        responses=[
            LLMResponse(
                content="The answer is 42.",
                tool_calls=[],
                finish_reason="stop",
            )
        ]
    )

    agent = SandboxAgent(llm_provider=fake_llm, service=mock_service)
    result = await agent.run(prompt="What is 40 + 2?")

    assert isinstance(result, AgentRunResult)
    assert result.response == "The answer is 42."
    assert result.iterations == 1
    assert result.tool_calls_count == 0
    assert len(result.messages) == 3
    assert result.messages[0].role == "system"
    assert result.messages[1].role == "user"
    assert result.messages[1].content == "What is 40 + 2?"
    assert result.messages[2].role == "assistant"
    assert result.messages[2].content == "The answer is 42."


@pytest.mark.asyncio
async def test_agent_single_tool_execution(mock_service: MagicMock):
    """Test model calling execute_code, receiving result, then generating final text."""
    sandbox_id = uuid4()
    execution_id = uuid4()

    mock_service.execute_code = AsyncMock(
        return_value=JobExecutionResponse(
            execution_id=execution_id,
            sandbox_id=sandbox_id,
            status="completed",
            exit_code=0,
            stdout="Hello from Python\n",
            stderr="",
            duration_ms=120,
            submitted_at=utc_now(),
        )
    )

    fake_llm = FakeLLMProvider(
        responses=[
            # Iteration 1: model requests execute_code tool
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_001",
                        name="execute_code",
                        arguments={
                            "sandbox_id": str(sandbox_id),
                            "code": "print('Hello from Python')",
                        },
                    )
                ],
                finish_reason="tool_calls",
            ),
            # Iteration 2: model inspects tool output and responds
            LLMResponse(
                content="The code executed successfully and printed 'Hello from Python'.",
                tool_calls=[],
                finish_reason="stop",
            ),
        ]
    )

    agent = SandboxAgent(llm_provider=fake_llm, service=mock_service)
    result = await agent.run(prompt="Run print('Hello from Python') in my sandbox.")

    assert result.response == "The code executed successfully and printed 'Hello from Python'."
    assert result.iterations == 2
    assert result.tool_calls_count == 1

    # Verify message sequence: system, user, assistant (call), tool (result), assistant (final)
    assert len(result.messages) == 5
    assert result.messages[0].role == "system"
    assert result.messages[1].role == "user"
    assert result.messages[2].role == "assistant"
    assert result.messages[2].tool_calls[0].name == "execute_code"
    assert result.messages[3].role == "tool"
    assert result.messages[3].tool_call_id == "call_001"
    assert "Hello from Python" in result.messages[3].content
    assert result.messages[4].role == "assistant"
    assert result.messages[4].content == result.response

    mock_service.execute_code.assert_awaited_once()


@pytest.mark.asyncio
async def test_agent_multi_turn_tools(mock_service: MagicMock):
    """Test model calling multiple tools sequentially across reasoning turns."""
    sandbox_id = uuid4()
    execution_id = uuid4()

    mock_sandbox = MagicMock()
    mock_sandbox.id = sandbox_id
    mock_sandbox.status = "running"
    mock_sandbox.runtime = "python"
    mock_sandbox.created_at = utc_now()
    mock_sandbox.expires_at = utc_now()
    mock_sandbox.destroyed_at = None
    mock_service.create_sandbox.return_value = mock_sandbox

    mock_service.execute_code = AsyncMock(
        return_value=JobExecutionResponse(
            execution_id=execution_id,
            sandbox_id=sandbox_id,
            status="completed",
            exit_code=0,
            stdout="RESULT=100\n",
            stderr="",
            duration_ms=85,
            submitted_at=utc_now(),
        )
    )

    fake_llm = FakeLLMProvider(
        responses=[
            # Turn 1: create sandbox
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_create",
                        name="create_sandbox",
                        arguments={"runtime": "python", "ttl_seconds": 300},
                    )
                ],
                finish_reason="tool_calls",
            ),
            # Turn 2: execute code
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_exec",
                        name="execute_code",
                        arguments={
                            "sandbox_id": str(sandbox_id),
                            "code": "print('RESULT=100')",
                        },
                    )
                ],
                finish_reason="tool_calls",
            ),
            # Turn 3: final answer
            LLMResponse(
                content="Created sandbox and calculated result: 100.",
                tool_calls=[],
                finish_reason="stop",
            ),
        ]
    )

    agent = SandboxAgent(llm_provider=fake_llm, service=mock_service)
    result = await agent.run(prompt="Create a sandbox and calculate 10 * 10.")

    assert result.iterations == 3
    assert result.tool_calls_count == 2
    assert "Created sandbox and calculated result: 100." in result.response

    # Verify tool calls happened in order
    mock_service.create_sandbox.assert_called_once()
    mock_service.execute_code.assert_awaited_once()


@pytest.mark.asyncio
async def test_agent_unknown_tool_handled(mock_service: MagicMock):
    """Test that an unknown tool request returns structured error to the model."""
    fake_llm = FakeLLMProvider(
        responses=[
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_unknown",
                        name="unsupported_network_tool",
                        arguments={"url": "https://example.com"},
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="I apologize, but 'unsupported_network_tool' is not available.",
                tool_calls=[],
                finish_reason="stop",
            ),
        ]
    )

    agent = SandboxAgent(llm_provider=fake_llm, service=mock_service)
    result = await agent.run(prompt="Download something.")

    assert result.iterations == 2
    assert result.tool_calls_count == 1
    # Check that tool error was fed back to LLM
    tool_msg = result.messages[3]
    assert tool_msg.role == "tool"
    assert "UnknownToolError" in tool_msg.content
    assert "not recognized" in tool_msg.content


@pytest.mark.asyncio
async def test_agent_malformed_arguments(mock_service: MagicMock):
    """Test that malformed/invalid arguments return validation error to model without crashing."""
    sandbox_id = uuid4()
    fake_llm = FakeLLMProvider(
        responses=[
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_bad_args",
                        name="execute_code",
                        # Missing required 'code' field
                        arguments={"sandbox_id": str(sandbox_id)},
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="I see the arguments were invalid. Let me fix that.",
                tool_calls=[],
                finish_reason="stop",
            ),
        ]
    )

    agent = SandboxAgent(llm_provider=fake_llm, service=mock_service)
    result = await agent.run(prompt="Execute nothing.")

    assert result.iterations == 2
    tool_msg = result.messages[3]
    assert tool_msg.role == "tool"
    assert "ValidationError" in tool_msg.content


@pytest.mark.asyncio
async def test_agent_tool_execution_failure(mock_service: MagicMock):
    """Test that domain/lifecycle errors during tool run are safely fed back to model."""
    sandbox_id = uuid4()
    mock_service.execute_code = AsyncMock(
        side_effect=SandboxNotFoundError(
            f"Sandbox {sandbox_id} was not found.",
            details={"sandbox_id": str(sandbox_id)},
        )
    )

    fake_llm = FakeLLMProvider(
        responses=[
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_missing_sb",
                        name="execute_code",
                        arguments={
                            "sandbox_id": str(sandbox_id),
                            "code": "print(1)",
                        },
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="The sandbox was not found.",
                tool_calls=[],
                finish_reason="stop",
            ),
        ]
    )

    agent = SandboxAgent(llm_provider=fake_llm, service=mock_service)
    result = await agent.run(prompt="Run code in non-existent sandbox.")

    assert result.iterations == 2
    tool_msg = result.messages[3]
    assert tool_msg.role == "tool"
    assert "SandboxNotFoundError" in tool_msg.content


@pytest.mark.asyncio
async def test_agent_llm_provider_failure(mock_service: MagicMock):
    """Test that unexpected LLM provider exceptions are wrapped in LLMProviderError."""
    fake_llm = FakeLLMProvider(
        responses=[
            RuntimeError("Provider connection reset by peer"),
        ]
    )

    agent = SandboxAgent(llm_provider=fake_llm, service=mock_service)

    with pytest.raises(LLMProviderError) as exc_info:
        await agent.run(prompt="Hello")

    assert "LLM provider failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_agent_max_iterations_exceeded(mock_service: MagicMock):
    """Test that exceeding AGENT_MAX_ITERATIONS raises AgentMaxIterationsError."""
    # Loop that continuously requests a tool call
    fake_llm = FakeLLMProvider(
        responses=[
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id=f"call_{i}",
                        name="execute_code",
                        arguments={
                            "sandbox_id": str(uuid4()),
                            "code": f"print({i})",
                        },
                    )
                ],
                finish_reason="tool_calls",
            )
            for i in range(10)
        ]
    )

    mock_service.execute_code = AsyncMock(
        return_value=JobExecutionResponse(
            execution_id=uuid4(),
            sandbox_id=uuid4(),
            status="completed",
            exit_code=0,
            stdout="ok\n",
            stderr="",
            duration_ms=10,
            submitted_at=utc_now(),
        )
    )

    custom_config = SandboxSettings(AGENT_MAX_ITERATIONS=3)
    agent = SandboxAgent(
        llm_provider=fake_llm,
        service=mock_service,
        config=custom_config,
    )

    with pytest.raises(AgentMaxIterationsError) as exc_info:
        await agent.run(prompt="Loop forever")

    assert "exceeded maximum permitted iterations (3)" in str(exc_info.value)
    assert exc_info.value.details["max_iterations"] == 3


@pytest.mark.asyncio
async def test_agent_request_timeout(mock_service: MagicMock):
    """Test that exceeding configured timeout raises AgentTimeoutError."""

    class SlowLLMProvider(LLMProvider):
        async def generate_response(
            self,
            messages: list[LLMMessage],
            tools: list[dict[str, Any]] | None = None,
        ) -> LLMResponse:
            await asyncio.sleep(0.5)
            return LLMResponse(content="Finally done", tool_calls=[])

    agent = SandboxAgent(
        llm_provider=SlowLLMProvider(),
        service=mock_service,
    )

    with pytest.raises(AgentTimeoutError) as exc_info:
        await agent.run(prompt="Be quick", timeout_seconds=0.05)

    assert "exceeded configured timeout" in str(exc_info.value)
    assert exc_info.value.details["timeout_seconds"] == 0.05


@pytest.mark.asyncio
async def test_agent_custom_history_and_system_prompt(mock_service: MagicMock):
    """Test passing custom history or custom system prompt to agent."""
    fake_llm = FakeLLMProvider(
        responses=[
            LLMResponse(
                content="Understood, context preserved.",
                tool_calls=[],
                finish_reason="stop",
            )
        ]
    )

    custom_history = [
        LLMMessage(role="system", content="Custom system instruction."),
        LLMMessage(role="user", content="Earlier message."),
        LLMMessage(role="assistant", content="Earlier reply."),
        LLMMessage(role="user", content="Follow up prompt."),
    ]

    agent = SandboxAgent(
        llm_provider=fake_llm,
        service=mock_service,
        system_prompt="Default prompt",
    )
    result = await agent.run(prompt="Ignored because history is provided", history=custom_history)

    assert result.response == "Understood, context preserved."
    assert len(result.messages) == 5
    assert result.messages[0].content == "Custom system instruction."
    assert result.messages[-1].content == "Understood, context preserved."
