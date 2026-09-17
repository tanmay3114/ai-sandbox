"""Unit tests for Groq provider abstraction using mocks/fakes."""

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import openai
import pytest

from app.agent.agent import SandboxAgent
from app.agent.llm import (
    GroqProvider,
    LLMMessage,
    LLMProviderError,
    ToolCallRequest,
    get_llm_provider,
)
from app.core.config import SandboxSettings
from app.models.sandbox import utc_now
from app.schemas.sandbox import JobExecutionResponse
from app.services.sandbox_lifecycle_service import SandboxLifecycleService


@pytest.fixture
def mock_groq_client() -> AsyncMock:
    """Mocked AsyncOpenAI client simulating Groq API responses."""
    client = AsyncMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock()
    return client


def _create_mock_groq_completion(
    content: str | None = None,
    tool_calls: list[dict] | None = None,
    finish_reason: str = "stop",
    prompt_tokens: int = 12,
    completion_tokens: int = 24,
) -> MagicMock:
    """Helper creating structured ChatCompletion mock responses for Groq."""
    choice = MagicMock()
    choice.finish_reason = finish_reason
    choice.message = MagicMock()
    choice.message.content = content

    if tool_calls:
        mock_tcs = []
        for tc in tool_calls:
            mock_tc = MagicMock()
            mock_tc.id = tc["id"]
            mock_tc.function = MagicMock()
            mock_tc.function.name = tc["name"]
            mock_tc.function.arguments = (
                json.dumps(tc["arguments"])
                if isinstance(tc["arguments"], dict)
                else str(tc["arguments"])
            )
            mock_tcs.append(mock_tc)
        choice.message.tool_calls = mock_tcs
    else:
        choice.message.tool_calls = None

    response = MagicMock()
    response.choices = [choice]
    response.usage = MagicMock()
    response.usage.prompt_tokens = prompt_tokens
    response.usage.completion_tokens = completion_tokens
    response.usage.total_tokens = prompt_tokens + completion_tokens
    return response


@pytest.mark.asyncio
async def test_groq_provider_normal_text_response(mock_groq_client: AsyncMock):
    """Test sending user message and receiving normal text response from Groq."""
    mock_groq_client.chat.completions.create.return_value = _create_mock_groq_completion(
        content="Hello from Groq!"
    )

    provider = GroqProvider(
        api_key="fake-groq-key",
        model="openai/gpt-oss-120b",
        client=mock_groq_client,
    )

    messages = [
        LLMMessage(role="system", content="You are a helpful assistant."),
        LLMMessage(role="user", content="Hello"),
    ]

    response = await provider.generate_response(messages)

    assert response.content == "Hello from Groq!"
    assert not response.has_tool_calls
    assert response.finish_reason == "stop"
    assert response.usage["total_tokens"] == 36

    mock_groq_client.chat.completions.create.assert_awaited_once()
    call_kwargs = mock_groq_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "openai/gpt-oss-120b"
    assert len(call_kwargs["messages"]) == 2
    assert call_kwargs["messages"][0]["role"] == "system"
    assert call_kwargs["messages"][1]["content"] == "Hello"


@pytest.mark.asyncio
async def test_groq_provider_tool_calls_response(mock_groq_client: AsyncMock):
    """Test receiving tool-call requests from Groq."""
    mock_groq_client.chat.completions.create.return_value = _create_mock_groq_completion(
        content=None,
        tool_calls=[
            {
                "id": "groq_call_456",
                "name": "create_sandbox",
                "arguments": {"runtime": "python", "ttl_seconds": 180},
            }
        ],
        finish_reason="tool_calls",
    )

    provider = GroqProvider(
        api_key="fake-groq-key",
        client=mock_groq_client,
    )

    messages = [LLMMessage(role="user", content="Create a python sandbox")]
    tools = [
        {
            "name": "create_sandbox",
            "description": "Creates a sandbox",
            "parameters": {"type": "object"},
        }
    ]

    response = await provider.generate_response(messages, tools=tools)

    assert response.has_tool_calls
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "groq_call_456"
    assert response.tool_calls[0].name == "create_sandbox"
    assert response.tool_calls[0].arguments["runtime"] == "python"
    assert response.tool_calls[0].arguments["ttl_seconds"] == 180
    assert response.finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_groq_provider_tool_result_message_formatting(mock_groq_client: AsyncMock):
    """Test sending assistant tool calls and tool result messages back to Groq."""
    mock_groq_client.chat.completions.create.return_value = _create_mock_groq_completion(
        content="The execution completed successfully."
    )

    provider = GroqProvider(api_key="fake-groq-key", client=mock_groq_client)

    messages = [
        LLMMessage(role="user", content="Execute code"),
        LLMMessage(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="call_groq_exec",
                    name="execute_code",
                    arguments={"code": "print(123)"},
                )
            ],
        ),
        LLMMessage(
            role="tool",
            tool_call_id="call_groq_exec",
            content='{"stdout": "123\\n", "exit_code": 0}',
        ),
    ]

    response = await provider.generate_response(messages)

    assert response.content == "The execution completed successfully."

    formatted_msgs = mock_groq_client.chat.completions.create.call_args.kwargs["messages"]
    assert len(formatted_msgs) == 3
    assert formatted_msgs[1]["role"] == "assistant"
    assert formatted_msgs[1]["tool_calls"][0]["id"] == "call_groq_exec"
    assert formatted_msgs[2]["role"] == "tool"
    assert formatted_msgs[2]["tool_call_id"] == "call_groq_exec"


def test_groq_provider_tool_message_missing_tool_call_id():
    """Tool message without tool_call_id raises LLMProviderError."""
    provider = GroqProvider(api_key="fake-groq-key", client=MagicMock())
    messages = [LLMMessage(role="tool", content="some output")]

    with pytest.raises(LLMProviderError) as exc_info:
        provider._format_messages(messages)
    assert "tool_call_id" in str(exc_info.value)


def test_groq_provider_missing_api_key():
    """Instantiating GroqProvider with no API key and no client raises LLMProviderError."""
    with pytest.raises(LLMProviderError) as exc_info:
        GroqProvider(api_key=None, client=None)
    assert "Groq API key is required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_groq_provider_api_error_handling(mock_groq_client: AsyncMock):
    """Groq API exceptions are cleanly caught and wrapped in LLMProviderError."""
    mock_groq_client.chat.completions.create.side_effect = openai.APIConnectionError(
        request=MagicMock()
    )

    provider = GroqProvider(api_key="fake-groq-key", client=mock_groq_client)
    messages = [LLMMessage(role="user", content="hi")]

    with pytest.raises(LLMProviderError) as exc_info:
        await provider.generate_response(messages)
    assert "Groq API completion failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_groq_provider_empty_choices_error(mock_groq_client: AsyncMock):
    """Empty choices list raises LLMProviderError."""
    mock_resp = MagicMock()
    mock_resp.choices = []
    mock_groq_client.chat.completions.create.return_value = mock_resp

    provider = GroqProvider(api_key="fake-groq-key", client=mock_groq_client)
    messages = [LLMMessage(role="user", content="hi")]

    with pytest.raises(LLMProviderError) as exc_info:
        await provider.generate_response(messages)
    assert "empty choices list" in str(exc_info.value)


def test_llm_factory_groq():
    """Factory instantiates GroqProvider from settings when LLM_PROVIDER=groq."""
    cfg = SandboxSettings(
        LLM_PROVIDER="groq",
        GROQ_API_KEY="test-groq-key",
        GROQ_MODEL="openai/gpt-oss-120b",
        GROQ_BASE_URL="https://api.groq.com/openai/v1",
    )
    provider = get_llm_provider(config=cfg)
    assert isinstance(provider, GroqProvider)
    assert provider.model == "openai/gpt-oss-120b"
    assert provider.base_url == "https://api.groq.com/openai/v1"


def test_llm_factory_groq_fallback_key():
    """Factory falls back to LLM_API_KEY if GROQ_API_KEY is not explicitly set."""
    cfg = SandboxSettings(
        LLM_PROVIDER="groq",
        LLM_API_KEY="test-fallback-key",
        GROQ_API_KEY=None,
    )
    provider = get_llm_provider(config=cfg)
    assert isinstance(provider, GroqProvider)
    assert provider.model == "openai/gpt-oss-120b"


@pytest.mark.asyncio
async def test_groq_provider_agent_loop_integration(mock_groq_client: AsyncMock):
    """Test full agent loop with GroqProvider:
    execute_code tool -> sandbox execution -> final response.
    """
    # Round 1: Model requests code execution
    resp1 = _create_mock_groq_completion(
        content=None,
        tool_calls=[
            {
                "id": "groq_call_1",
                "name": "execute_code",
                "arguments": {"sandbox_id": "test-sandbox-123", "code": "print(2 + 2)"},
            }
        ],
        finish_reason="tool_calls",
    )
    # Round 2: Model returns final text
    resp2 = _create_mock_groq_completion(
        content="The output of 2 + 2 is 4.",
        finish_reason="stop",
    )
    mock_groq_client.chat.completions.create.side_effect = [resp1, resp2]

    provider = GroqProvider(api_key="fake-groq-key", client=mock_groq_client)

    # Mock service
    service = MagicMock(spec=SandboxLifecycleService)
    now = utc_now()
    exec_resp = JobExecutionResponse(
        execution_id=uuid4(),
        sandbox_id=uuid4(),
        status="completed",
        exit_code=0,
        stdout="4\n",
        stderr="",
        duration_ms=15,
        submitted_at=now,
    )
    service.execute_code = AsyncMock(return_value=exec_resp)

    agent = SandboxAgent(
        llm_provider=provider,
        service=service,
        config=SandboxSettings(AGENT_MAX_ITERATIONS=5),
    )

    result = await agent.run(prompt="What is 2 + 2 in Python?")

    assert result.response == "The output of 2 + 2 is 4."
    assert result.iterations == 2
    assert result.tool_calls_count == 1
    assert mock_groq_client.chat.completions.create.await_count == 2
