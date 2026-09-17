"""Unit tests for LLM provider abstraction using mocks/fakes."""

import json
from unittest.mock import AsyncMock, MagicMock

import openai
import pytest
from google import genai
from google.genai import errors, types

from app.agent.llm import (
    GeminiProvider,
    LLMMessage,
    LLMProviderError,
    OpenAIProvider,
    ToolCallRequest,
    get_llm_provider,
)
from app.core.config import SandboxSettings


@pytest.fixture
def mock_openai_client() -> AsyncMock:
    """Mocked AsyncOpenAI client simulating OpenAI SDK responses."""
    client = AsyncMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock()
    return client


def _create_mock_completion(
    content: str | None = None,
    tool_calls: list[dict] | None = None,
    finish_reason: str = "stop",
    prompt_tokens: int = 10,
    completion_tokens: int = 20,
) -> MagicMock:
    """Helper creating structured ChatCompletion mock responses."""
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
async def test_openai_provider_normal_text_response(mock_openai_client: AsyncMock):
    """Test sending user message and receiving normal text response."""
    mock_openai_client.chat.completions.create.return_value = _create_mock_completion(
        content="Hello! How can I help?"
    )

    provider = OpenAIProvider(
        api_key="fake-key",
        model="gpt-4o-mini",
        client=mock_openai_client,
    )

    messages = [
        LLMMessage(role="system", content="You are a coding assistant."),
        LLMMessage(role="user", content="Hi"),
    ]

    response = await provider.generate_response(messages)

    assert response.content == "Hello! How can I help?"
    assert not response.has_tool_calls
    assert response.finish_reason == "stop"
    assert response.usage["total_tokens"] == 30

    mock_openai_client.chat.completions.create.assert_awaited_once()
    call_kwargs = mock_openai_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o-mini"
    assert len(call_kwargs["messages"]) == 2
    assert call_kwargs["messages"][0]["role"] == "system"
    assert call_kwargs["messages"][1]["content"] == "Hi"


@pytest.mark.asyncio
async def test_openai_provider_tool_calls_response(mock_openai_client: AsyncMock):
    """Test receiving tool-call requests from the model."""
    mock_openai_client.chat.completions.create.return_value = _create_mock_completion(
        content=None,
        tool_calls=[
            {
                "id": "call_123",
                "name": "create_sandbox",
                "arguments": {"runtime": "python", "ttl_seconds": 300},
            }
        ],
        finish_reason="tool_calls",
    )

    provider = OpenAIProvider(
        api_key="fake-key",
        client=mock_openai_client,
    )

    messages = [LLMMessage(role="user", content="Create a sandbox")]
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
    assert response.tool_calls[0].id == "call_123"
    assert response.tool_calls[0].name == "create_sandbox"
    assert response.tool_calls[0].arguments["runtime"] == "python"
    assert response.finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_openai_provider_tool_result_message_formatting(mock_openai_client: AsyncMock):
    """Test sending assistant tool calls and tool result messages back to model."""
    mock_openai_client.chat.completions.create.return_value = _create_mock_completion(
        content="The sandbox has been created."
    )

    provider = OpenAIProvider(api_key="fake-key", client=mock_openai_client)

    messages = [
        LLMMessage(role="user", content="Create sandbox"),
        LLMMessage(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="call_abc",
                    name="create_sandbox",
                    arguments={"ttl_seconds": 120},
                )
            ],
        ),
        LLMMessage(
            role="tool",
            tool_call_id="call_abc",
            content='{"sandbox_id": "uuid-1", "status": "running"}',
        ),
    ]

    response = await provider.generate_response(messages)

    assert response.content == "The sandbox has been created."

    formatted_msgs = mock_openai_client.chat.completions.create.call_args.kwargs["messages"]
    assert len(formatted_msgs) == 3
    assert formatted_msgs[1]["role"] == "assistant"
    assert "tool_calls" in formatted_msgs[1]
    assert formatted_msgs[1]["tool_calls"][0]["id"] == "call_abc"
    assert formatted_msgs[2]["role"] == "tool"
    assert formatted_msgs[2]["tool_call_id"] == "call_abc"


def test_openai_provider_tool_message_missing_tool_call_id():
    """Tool message without tool_call_id raises LLMProviderError."""
    provider = OpenAIProvider(api_key="fake-key", client=MagicMock())
    messages = [LLMMessage(role="tool", content="some output")]

    with pytest.raises(LLMProviderError) as exc_info:
        provider._format_messages(messages)
    assert "tool_call_id" in str(exc_info.value)


def test_openai_provider_missing_api_key():
    """Instantiating OpenAIProvider with no API key and no client raises LLMProviderError."""
    with pytest.raises(LLMProviderError) as exc_info:
        OpenAIProvider(api_key=None, client=None)
    assert "API key is required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_openai_provider_api_error_handling(mock_openai_client: AsyncMock):
    """OpenAI SDK exceptions are cleanly caught and wrapped in LLMProviderError."""
    mock_openai_client.chat.completions.create.side_effect = openai.APIConnectionError(
        request=MagicMock()
    )

    provider = OpenAIProvider(api_key="fake-key", client=mock_openai_client)
    messages = [LLMMessage(role="user", content="hi")]

    with pytest.raises(LLMProviderError) as exc_info:
        await provider.generate_response(messages)
    assert "OpenAI API completion failed" in str(exc_info.value)


def test_llm_factory_openai():
    """Factory instantiates OpenAIProvider from settings."""
    cfg = SandboxSettings(
        LLM_PROVIDER="openai",
        LLM_API_KEY="test-key-from-settings",
        LLM_MODEL="gpt-4o-mini",
    )
    provider = get_llm_provider(config=cfg)
    assert isinstance(provider, OpenAIProvider)
    assert provider.model == "gpt-4o-mini"


def test_llm_factory_unsupported_provider():
    """Factory raises LLMProviderError on unsupported provider string."""
    cfg = SandboxSettings(
        LLM_PROVIDER="unsupported_vendor",
        LLM_API_KEY="some-key",
    )
    with pytest.raises(LLMProviderError) as exc_info:
        get_llm_provider(config=cfg)
    assert "Unsupported LLM provider" in str(exc_info.value)


@pytest.fixture
def mock_gemini_client() -> MagicMock:
    """Mocked genai.Client simulating Google Gemini SDK responses."""
    client = MagicMock(spec=genai.Client)
    client.aio = MagicMock()
    client.aio.models = MagicMock()
    client.aio.models.generate_content = AsyncMock()
    return client


def _create_mock_gemini_response(
    text: str | None = None,
    function_calls: list[dict] | None = None,
    finish_reason: str = "STOP",
    prompt_tokens: int = 15,
    candidates_tokens: int = 25,
    thought_parts: list[types.Part] | None = None,
) -> types.GenerateContentResponse:
    """Helper creating structured GenerateContentResponse mock objects."""
    parts = []
    if thought_parts:
        parts.extend(thought_parts)
    if text:
        parts.append(types.Part.from_text(text=text))
    if function_calls:
        for fc in function_calls:
            parts.append(
                types.Part(
                    function_call=types.FunctionCall(
                        name=fc["name"],
                        args=fc["arguments"],
                        id=fc.get("id"),
                    ),
                    thought_signature=fc.get("thought_signature"),
                )
            )
    candidate = types.Candidate(
        finish_reason=finish_reason,
        content=types.Content(role="model", parts=parts),
    )
    usage = types.GenerateContentResponseUsageMetadata(
        prompt_token_count=prompt_tokens,
        candidates_token_count=candidates_tokens,
        total_token_count=prompt_tokens + candidates_tokens,
    )
    return types.GenerateContentResponse(
        candidates=[candidate],
        usage_metadata=usage,
    )



@pytest.mark.asyncio
async def test_gemini_provider_normal_text_response(mock_gemini_client: MagicMock):
    """Test sending user message and receiving normal text response from Gemini."""
    mock_gemini_client.aio.models.generate_content.return_value = _create_mock_gemini_response(
        text="Hello! I am Gemini."
    )

    provider = GeminiProvider(
        api_key="fake-gemini-key",
        model="gemini-2.5-flash",
        client=mock_gemini_client,
    )

    messages = [
        LLMMessage(role="system", content="You are a coding assistant."),
        LLMMessage(role="user", content="Hi"),
    ]

    response = await provider.generate_response(messages)

    assert response.content == "Hello! I am Gemini."
    assert not response.has_tool_calls
    assert response.finish_reason == "stop"
    assert response.usage["total_tokens"] == 40

    mock_gemini_client.aio.models.generate_content.assert_awaited_once()
    call_kwargs = mock_gemini_client.aio.models.generate_content.call_args.kwargs
    assert call_kwargs["model"] == "gemini-2.5-flash"
    assert call_kwargs["config"].system_instruction == "You are a coding assistant."
    assert len(call_kwargs["contents"]) == 1
    assert call_kwargs["contents"][0].role == "user"


@pytest.mark.asyncio
async def test_gemini_provider_tool_calls_response(mock_gemini_client: MagicMock):
    """Test Gemini generating function/tool calls."""
    mock_gemini_client.aio.models.generate_content.return_value = _create_mock_gemini_response(
        function_calls=[
            {
                "id": "gemini_call_1",
                "name": "create_sandbox",
                "arguments": {"runtime": "python", "ttl_seconds": 300},
            }
        ]
    )

    provider = GeminiProvider(
        api_key="fake-gemini-key",
        model="gemini-2.5-flash",
        client=mock_gemini_client,
    )

    tools = [
        {
            "name": "create_sandbox",
            "description": "Instantiate sandbox session",
            "parameters": {
                "type": "object",
                "properties": {
                    "runtime": {"type": "string"},
                    "ttl_seconds": {"type": "integer"},
                },
                "required": ["runtime"],
            },
        }
    ]

    messages = [LLMMessage(role="user", content="Start a new python sandbox")]
    response = await provider.generate_response(messages, tools=tools)

    assert response.content is None
    assert response.has_tool_calls
    assert len(response.tool_calls) == 1
    assert response.finish_reason == "tool_calls"

    tc = response.tool_calls[0]
    assert tc.id == "gemini_call_1"
    assert tc.name == "create_sandbox"
    assert tc.arguments["runtime"] == "python"
    assert tc.arguments["ttl_seconds"] == 300


@pytest.mark.asyncio
async def test_gemini_provider_tool_result_message_formatting(
    mock_gemini_client: MagicMock,
):
    """Test conversation formatting with function call and tool result returned to Gemini."""
    mock_gemini_client.aio.models.generate_content.return_value = _create_mock_gemini_response(
        text="Sandbox uuid-1 is running and ready."
    )

    provider = GeminiProvider(
        api_key="fake-gemini-key",
        client=mock_gemini_client,
    )

    messages = [
        LLMMessage(role="user", content="Create sandbox"),
        LLMMessage(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="call_gemini_abc",
                    name="create_sandbox",
                    arguments={"ttl_seconds": 120},
                )
            ],
        ),
        LLMMessage(
            role="tool",
            name="create_sandbox",
            tool_call_id="call_gemini_abc",
            content='{"sandbox_id": "uuid-1", "status": "running"}',
        ),
    ]

    response = await provider.generate_response(messages)

    assert response.content == "Sandbox uuid-1 is running and ready."
    assert not response.has_tool_calls

    call_kwargs = mock_gemini_client.aio.models.generate_content.call_args.kwargs
    contents = call_kwargs["contents"]
    assert len(contents) == 3
    # Turn 0: User message
    assert contents[0].role == "user"
    # Turn 1: Model message with function_call
    assert contents[1].role == "model"
    assert contents[1].parts[0].function_call.name == "create_sandbox"
    assert contents[1].parts[0].function_call.id == "call_gemini_abc"
    # Turn 2: User message containing function_response
    assert contents[2].role == "user"
    assert contents[2].parts[0].function_response.name == "create_sandbox"
    assert contents[2].parts[0].function_response.id == "call_gemini_abc"
    assert contents[2].parts[0].function_response.response["sandbox_id"] == "uuid-1"


@pytest.mark.asyncio
async def test_gemini_provider_multiple_rounds_tool_calling(
    mock_gemini_client: MagicMock,
):
    """Test multi-turn sequence: create_sandbox -> execute_code -> final response."""
    # Round 1: Model calls execute_code
    mock_gemini_client.aio.models.generate_content.return_value = _create_mock_gemini_response(
        text="Calculation result is 42."
    )

    provider = GeminiProvider(
        api_key="fake-gemini-key",
        client=mock_gemini_client,
    )

    messages = [
        LLMMessage(role="user", content="Calculate 40 + 2"),
        # Round 1: create_sandbox
        LLMMessage(
            role="assistant",
            tool_calls=[
                ToolCallRequest(
                    id="c1",
                    name="create_sandbox",
                    arguments={"runtime": "python"},
                )
            ],
        ),
        LLMMessage(
            role="tool",
            name="create_sandbox",
            tool_call_id="c1",
            content='{"sandbox_id": "s1"}',
        ),
        # Round 2: execute_code
        LLMMessage(
            role="assistant",
            tool_calls=[
                ToolCallRequest(
                    id="c2",
                    name="execute_code",
                    arguments={"sandbox_id": "s1", "code": "print(42)"},
                )
            ],
        ),
        LLMMessage(
            role="tool",
            name="execute_code",
            tool_call_id="c2",
            content='{"stdout": "42\\n", "exit_code": 0}',
        ),
    ]

    response = await provider.generate_response(messages)

    assert response.content == "Calculation result is 42."
    assert not response.has_tool_calls

    contents = mock_gemini_client.aio.models.generate_content.call_args.kwargs["contents"]
    # Verify strict alternating role structure: user -> model -> user -> model -> user
    assert [c.role for c in contents] == ["user", "model", "user", "model", "user"]


def test_gemini_provider_missing_api_key():
    """Instantiating GeminiProvider with no API key and no client raises LLMProviderError."""
    with pytest.raises(LLMProviderError) as exc_info:
        GeminiProvider(api_key=None, client=None)
    assert "Gemini API key is required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_gemini_provider_api_error_handling(mock_gemini_client: MagicMock):
    """Gemini SDK exceptions are cleanly caught and wrapped in LLMProviderError."""
    mock_gemini_client.aio.models.generate_content.side_effect = errors.APIError(
        429, {"error": {"message": "Quota exceeded"}}
    )

    provider = GeminiProvider(api_key="fake-key", client=mock_gemini_client)
    messages = [LLMMessage(role="user", content="hi")]

    with pytest.raises(LLMProviderError) as exc_info:
        await provider.generate_response(messages)
    assert "Gemini API generation failed" in str(exc_info.value)


def test_llm_factory_gemini():
    """Factory instantiates GeminiProvider from settings when LLM_PROVIDER=gemini."""
    cfg = SandboxSettings(
        LLM_PROVIDER="gemini",
        LLM_API_KEY="test-gemini-key",
        LLM_MODEL="gemini-2.5-flash",
    )
    provider = get_llm_provider(config=cfg)
    assert isinstance(provider, GeminiProvider)
    assert provider.model == "gemini-2.5-flash"


def test_llm_factory_default_provider():
    """Factory defaults to GeminiProvider when LLM_API_KEY is supplied."""
    cfg = SandboxSettings(LLM_API_KEY="test-gemini-key")
    provider = get_llm_provider(config=cfg)
    assert isinstance(provider, GeminiProvider)
    assert provider.model == cfg.LLM_MODEL



@pytest.mark.asyncio
async def test_gemini_provider_function_call_thought_signature_preserved(
    mock_gemini_client: MagicMock,
):
    """Verify thought_signature on Gemini function call parts is extracted and preserved."""
    test_sig = b"gemini_3_crypto_thought_signature_001"
    mock_gemini_client.aio.models.generate_content.return_value = _create_mock_gemini_response(
        function_calls=[
            {
                "id": "gemini_call_sig_1",
                "name": "create_sandbox",
                "arguments": {"runtime": "python"},
                "thought_signature": test_sig,
            }
        ]
    )

    provider = GeminiProvider(api_key="fake-key", client=mock_gemini_client)
    messages = [LLMMessage(role="user", content="Create a sandbox")]

    response = await provider.generate_response(messages)

    assert response.has_tool_calls
    tc = response.tool_calls[0]
    assert tc.id == "gemini_call_sig_1"
    assert tc.name == "create_sandbox"
    # Proves thought_signature is preserved on ToolCallRequest
    assert tc.thought_signature == test_sig
    # Proves native SDK Part is preserved
    assert tc.raw_part is not None
    assert tc.raw_part.thought_signature == test_sig


@pytest.mark.asyncio
async def test_gemini_provider_next_request_contains_thought_signature(
    mock_gemini_client: MagicMock,
):
    """Verify that when sending subsequent turn back to Gemini, thought_signature is present."""
    test_sig = b"gemini_3_crypto_thought_signature_002"

    mock_gemini_client.aio.models.generate_content.return_value = _create_mock_gemini_response(
        text="Sandbox ready."
    )

    provider = GeminiProvider(api_key="fake-key", client=mock_gemini_client)

    fc_part = types.Part(
        function_call=types.FunctionCall(
            name="create_sandbox",
            args={"runtime": "python"},
            id="call_sig_2",
        ),
        thought_signature=test_sig,
    )

    tc = ToolCallRequest(
        id="call_sig_2",
        name="create_sandbox",
        arguments={"runtime": "python"},
        thought_signature=test_sig,
        raw_part=fc_part,
    )

    messages = [
        LLMMessage(role="user", content="Create sandbox"),
        LLMMessage(role="assistant", tool_calls=[tc]),
        LLMMessage(
            role="tool",
            name="create_sandbox",
            tool_call_id="call_sig_2",
            content='{"sandbox_id": "sb_100"}',
        ),
    ]

    response = await provider.generate_response(messages)
    assert response.content == "Sandbox ready."

    # Inspect outgoing contents sent to Gemini API
    call_kwargs = mock_gemini_client.aio.models.generate_content.call_args.kwargs
    contents = call_kwargs["contents"]

    # Turn 0: User message
    assert contents[0].role == "user"

    # Turn 1: Model message MUST contain the exact thought_signature
    assert contents[1].role == "model"
    model_part = contents[1].parts[0]
    assert model_part.function_call.name == "create_sandbox"
    assert model_part.function_call.id == "call_sig_2"
    assert model_part.thought_signature == test_sig

    # Turn 2: User message with tool function response
    assert contents[2].role == "user"
    assert contents[2].parts[0].function_response.name == "create_sandbox"
    assert contents[2].parts[0].function_response.id == "call_sig_2"


@pytest.mark.asyncio
async def test_gemini_provider_sequential_tool_calls_preserve_thought_signatures(
    mock_gemini_client: MagicMock,
):
    """Verify that multiple sequential turns all preserve their respective thought signatures."""
    sig1 = b"sig_round_1_create_sandbox"
    sig2 = b"sig_round_2_execute_code"

    mock_gemini_client.aio.models.generate_content.return_value = _create_mock_gemini_response(
        text="Final result."
    )

    provider = GeminiProvider(api_key="fake-key", client=mock_gemini_client)

    part1 = types.Part(
        function_call=types.FunctionCall(
            name="create_sandbox", args={"runtime": "python"}, id="c1"
        ),
        thought_signature=sig1,
    )
    tc1 = ToolCallRequest(
        id="c1",
        name="create_sandbox",
        arguments={"runtime": "python"},
        thought_signature=sig1,
        raw_part=part1,
    )

    part2 = types.Part(
        function_call=types.FunctionCall(
            name="execute_code", args={"code": "print(1)"}, id="c2"
        ),
        thought_signature=sig2,
    )
    tc2 = ToolCallRequest(
        id="c2",
        name="execute_code",
        arguments={"code": "print(1)"},
        thought_signature=sig2,
        raw_part=part2,
    )

    messages = [
        LLMMessage(role="user", content="Initialize and run"),
        # Turn 1 (create_sandbox)
        LLMMessage(role="assistant", tool_calls=[tc1]),
        LLMMessage(role="tool", name="create_sandbox", tool_call_id="c1", content='{"id": "1"}'),
        # Turn 2 (execute_code)
        LLMMessage(role="assistant", tool_calls=[tc2]),
        LLMMessage(role="tool", name="execute_code", tool_call_id="c2", content='{"out": "1"}'),
    ]

    await provider.generate_response(messages)

    call_kwargs = mock_gemini_client.aio.models.generate_content.call_args.kwargs
    contents = call_kwargs["contents"]

    # Verify Turn 1 (first tool call) retains sig1
    assert contents[1].role == "model"
    assert contents[1].parts[0].thought_signature == sig1
    assert contents[1].parts[0].function_call.name == "create_sandbox"

    # Verify Turn 3 (second tool call) retains sig2
    assert contents[3].role == "model"
    assert contents[3].parts[0].thought_signature == sig2
    assert contents[3].parts[0].function_call.name == "execute_code"


@pytest.mark.asyncio
async def test_gemini_provider_thought_parts_alongside_function_call_preserved(
    mock_gemini_client: MagicMock,
):
    """Verify thought reasoning parts alongside function call parts are preserved."""
    thought_sig = b"thought_sig_003"
    call_sig = b"call_sig_003"

    p_thought = types.Part(
        thought=True,
        text="Need to provision sandbox first.",
        thought_signature=thought_sig,
    )

    mock_gemini_client.aio.models.generate_content.return_value = _create_mock_gemini_response(
        thought_parts=[p_thought],
        function_calls=[
            {
                "id": "c3",
                "name": "create_sandbox",
                "arguments": {"runtime": "python"},
                "thought_signature": call_sig,
            }
        ],
    )

    provider = GeminiProvider(api_key="fake-key", client=mock_gemini_client)
    messages = [LLMMessage(role="user", content="Run")]

    # Round 1: receive response with thought and function call
    response = await provider.generate_response(messages)
    assert response.has_tool_calls
    tc = response.tool_calls[0]
    assert tc.thought_signature == call_sig
    assert len(tc.thought_parts) == 1
    assert tc.thought_parts[0].thought is True
    assert tc.thought_parts[0].thought_signature == thought_sig

    # Round 2: send tool result back, verify both parts are in outgoing model turn
    mock_gemini_client.aio.models.generate_content.return_value = _create_mock_gemini_response(
        text="Done."
    )
    messages.append(LLMMessage(role="assistant", tool_calls=[tc]))
    messages.append(
        LLMMessage(role="tool", name="create_sandbox", tool_call_id="c3", content='{"ok": true}')
    )

    await provider.generate_response(messages)
    call_kwargs = mock_gemini_client.aio.models.generate_content.call_args.kwargs
    contents = call_kwargs["contents"]

    model_turn = contents[1]
    assert model_turn.role == "model"
    assert len(model_turn.parts) == 2
    assert model_turn.parts[0].thought is True
    assert model_turn.parts[0].thought_signature == thought_sig
    assert model_turn.parts[1].function_call.name == "create_sandbox"
    assert model_turn.parts[1].thought_signature == call_sig


