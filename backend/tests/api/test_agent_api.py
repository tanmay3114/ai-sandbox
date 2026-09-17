"""Integration and unit tests for POST /api/v1/agent/run API endpoint."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.agent.agent import SandboxAgent
from app.agent.llm import LLMMessage, LLMProvider, LLMResponse, ToolCallRequest
from app.api.dependencies import get_llm_provider_dependency, get_sandbox_agent
from app.core.exceptions import (
    AgentMaxIterationsError,
    AgentTimeoutError,
    LLMProviderError,
)
from app.main import app


class FakeLLMProvider(LLMProvider):
    """Test double simulating sequential LLM generation responses."""

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
def client() -> TestClient:
    """FastAPI TestClient fixture with default fake LLM provider."""
    default_fake_llm = FakeLLMProvider(
        [
            LLMResponse(
                content="Default mock response.",
                tool_calls=[],
                finish_reason="stop",
            )
        ]
    )
    app.dependency_overrides[get_llm_provider_dependency] = lambda: default_fake_llm
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_api_agent_run_success_direct_text(client: TestClient):
    """Test 1 & 4: Valid prompt without tool calls returns 200 and final text."""
    fake_llm = FakeLLMProvider(
        responses=[
            LLMResponse(
                content="The capital of France is Paris.",
                tool_calls=[],
                finish_reason="stop",
            )
        ]
    )

    app.dependency_overrides[get_llm_provider_dependency] = lambda: fake_llm
    response = client.post(
        "/api/v1/agent/run",
        json={"prompt": "What is the capital of France?"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["response"] == "The capital of France is Paris."
    assert data["tools_used"] is False
    assert data["iterations"] == 1
    assert data["tool_calls_count"] == 0
    assert data["executed_tools"] == []


def test_api_agent_invoked_with_prompt(client: TestClient):
    """Test 2: Verify the user's prompt is accurately passed into the agent loop."""
    fake_llm = FakeLLMProvider(
        responses=[
            LLMResponse(
                content="Acknowledged.",
                tool_calls=[],
                finish_reason="stop",
            )
        ]
    )

    app.dependency_overrides[get_llm_provider_dependency] = lambda: fake_llm
    test_prompt = "Calculate the sum of [1, 2, 3, 4, 5] using Python."
    response = client.post("/api/v1/agent/run", json={"prompt": test_prompt})
    assert response.status_code == 200

    assert len(fake_llm.calls) == 1
    call_messages = fake_llm.calls[0]["messages"]
    user_messages = [m for m in call_messages if m.role == "user"]
    assert len(user_messages) == 1
    assert user_messages[0].content == test_prompt


def test_api_agent_run_with_tool_usage(client: TestClient):
    """Test 3: Model calls a tool; tool usage and names are represented correctly."""
    fake_llm = FakeLLMProvider(
        responses=[
            # Round 1: Model requests create_sandbox
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_create_1",
                        name="create_sandbox",
                        arguments={"runtime": "python", "ttl_seconds": 180},
                    )
                ],
                finish_reason="tool_calls",
            ),
            # Round 2: Model provides final explanation
            LLMResponse(
                content="Created sandbox session successfully.",
                tool_calls=[],
                finish_reason="stop",
            ),
        ]
    )

    app.dependency_overrides[get_llm_provider_dependency] = lambda: fake_llm
    response = client.post(
        "/api/v1/agent/run",
        json={"prompt": "Please initialize an isolated Python sandbox."},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["response"] == "Created sandbox session successfully."
    assert data["tools_used"] is True
    assert data["iterations"] == 2
    assert data["tool_calls_count"] == 1
    assert data["executed_tools"] == ["create_sandbox"]


def test_api_agent_run_empty_prompt_rejected(client: TestClient):
    """Test 5: Empty string prompt is rejected with HTTP 422."""
    response = client.post("/api/v1/agent/run", json={"prompt": ""})
    assert response.status_code == 422
    data = response.json()
    assert data["error"] == "ValidationError"


def test_api_agent_run_whitespace_prompt_rejected(client: TestClient):
    """Test 5: Whitespace-only prompt is rejected with HTTP 422."""
    response = client.post("/api/v1/agent/run", json={"prompt": "   \n\t  "})
    assert response.status_code == 422
    data = response.json()
    assert data["error"] == "ValidationError"


def test_api_agent_run_missing_payload_rejected(client: TestClient):
    """Test 5: Empty body is rejected with HTTP 422."""
    response = client.post("/api/v1/agent/run", json={})
    assert response.status_code == 422
    data = response.json()
    assert data["error"] == "ValidationError"


def test_api_agent_run_llm_failure_handled_safely(client: TestClient):
    """Test 6: LLM provider communication failure returns 502 with safe message."""
    fake_llm = FakeLLMProvider(
        responses=[
            LLMProviderError("Google Gemini API token quota exhausted."),
        ]
    )

    app.dependency_overrides[get_llm_provider_dependency] = lambda: fake_llm
    response = client.post(
        "/api/v1/agent/run",
        json={"prompt": "Calculate factorial of 10."},
    )
    assert response.status_code == 502
    data = response.json()
    assert data["error"] == "LLMProviderError"
    assert "AI model provider communication failed" in data["message"]
    # Ensure no sensitive credentials or internal details leaked
    assert "quota" not in data["message"].lower()


def test_api_agent_run_timeout_handled_safely(client: TestClient):
    """Test 7: Agent request timeout returns 504 Gateway Timeout."""
    mock_agent = MagicMock(spec=SandboxAgent)
    mock_agent.run = AsyncMock(
        side_effect=AgentTimeoutError(
            "Agent execution exceeded configured timeout of 60.0 seconds.",
            details={"timeout_seconds": 60.0},
        )
    )

    app.dependency_overrides[get_sandbox_agent] = lambda: mock_agent
    try:
        response = client.post(
            "/api/v1/agent/run",
            json={"prompt": "Run a very long task."},
        )
        assert response.status_code == 504
        data = response.json()
        assert data["error"] == "AgentTimeoutError"
        assert "timeout" in data["message"].lower()
    finally:
        app.dependency_overrides.pop(get_sandbox_agent, None)


def test_api_agent_run_max_iterations_handled_safely(client: TestClient):
    """Test 8: Agent iteration limit exceeded returns 500 with structured error."""
    mock_agent = MagicMock(spec=SandboxAgent)
    mock_agent.run = AsyncMock(
        side_effect=AgentMaxIterationsError(
            "Agent exceeded maximum permitted iterations (10) without completing.",
            details={"max_iterations": 10},
        )
    )

    app.dependency_overrides[get_sandbox_agent] = lambda: mock_agent
    try:
        response = client.post(
            "/api/v1/agent/run",
            json={"prompt": "Infinite loop request."},
        )
        assert response.status_code == 500
        data = response.json()
        assert data["error"] == "AgentMaxIterationsError"
        assert "iterations" in data["message"].lower()
    finally:
        app.dependency_overrides.pop(get_sandbox_agent, None)


def test_api_agent_run_never_leaks_secrets(client: TestClient):
    """Verify that unexpected server errors never leak environment secrets."""
    class CrashingProvider(LLMProvider):
        async def generate_response(
            self,
            messages: list[LLMMessage],
            tools: list[dict[str, Any]] | None = None,
        ) -> LLMResponse:
            raise RuntimeError("CRITICAL_SECRET_AI_API_KEY_xyz12345 in stack trace")

    app.dependency_overrides[get_llm_provider_dependency] = lambda: CrashingProvider()
    response = client.post("/api/v1/agent/run", json={"prompt": "Break it"})
    assert response.status_code in (500, 502)
    body = response.text
    assert "CRITICAL_SECRET_AI_API_KEY_xyz12345" not in body
    assert "Traceback" not in body
