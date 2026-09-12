"""Tests for AI Agent tool schemas and tool adapter definitions."""

import uuid

import pytest
from pydantic import ValidationError

from app.agent.schemas import (
    AGENT_TOOLS,
    AgentToolError,
    CreateSandboxInput,
    DestroySandboxInput,
    ExecuteCodeInput,
    GetExecutionResultInput,
    GetSandboxInput,
)


def test_agent_tool_catalog_contains_all_five_tools():
    """Verify that AGENT_TOOLS declares all 5 minimum conceptual operations."""
    expected_tools = {
        "create_sandbox",
        "execute_code",
        "get_execution_result",
        "get_sandbox",
        "destroy_sandbox",
    }
    assert set(AGENT_TOOLS.keys()) == expected_tools

    for tool_name, tool_def in AGENT_TOOLS.items():
        assert tool_def.name == tool_name
        assert len(tool_def.description) > 10
        assert isinstance(tool_def.parameters, dict)
        assert "properties" in tool_def.parameters or "type" in tool_def.parameters


def test_create_sandbox_input_validation():
    """Test valid and invalid CreateSandboxInput payloads."""
    valid = CreateSandboxInput(runtime="python", ttl_seconds=120)
    assert valid.runtime == "python"
    assert valid.ttl_seconds == 120

    with pytest.raises(ValidationError):
        CreateSandboxInput(runtime="unsupported_lang")

    with pytest.raises(ValidationError):
        CreateSandboxInput(ttl_seconds=1)  # Below MIN_SANDBOX_TTL_SECONDS (10)


def test_execute_code_input_validation():
    """Test valid and invalid ExecuteCodeInput payloads."""
    valid = ExecuteCodeInput(
        sandbox_id=uuid.uuid4(),
        code="print('hello')",
        timeout_seconds=5.0,
    )
    assert valid.code == "print('hello')"
    assert valid.timeout_seconds == 5.0

    with pytest.raises(ValidationError):
        ExecuteCodeInput(sandbox_id=uuid.uuid4(), code="")

    with pytest.raises(ValidationError):
        ExecuteCodeInput(sandbox_id=uuid.uuid4(), code="   \t\n ")


    with pytest.raises(ValidationError):
        ExecuteCodeInput(sandbox_id=uuid.uuid4(), code="pass", timeout_seconds=0.1)


def test_get_execution_result_input_validation():
    """Test GetExecutionResultInput validation."""
    s_id = uuid.uuid4()
    e_id = uuid.uuid4()
    valid = GetExecutionResultInput(sandbox_id=s_id, execution_id=e_id)
    assert valid.sandbox_id == s_id
    assert valid.execution_id == e_id

    with pytest.raises(ValidationError):
        GetExecutionResultInput(sandbox_id="not-a-uuid", execution_id=e_id)


def test_get_sandbox_input_validation():
    """Test GetSandboxInput validation."""
    s_id = uuid.uuid4()
    valid = GetSandboxInput(sandbox_id=s_id)
    assert valid.sandbox_id == s_id


def test_destroy_sandbox_input_validation():
    """Test DestroySandboxInput validation."""
    s_id = uuid.uuid4()
    valid = DestroySandboxInput(sandbox_id=s_id)
    assert valid.sandbox_id == s_id


def test_agent_tool_error_schema():
    """Test structured AgentToolError serialization."""
    err = AgentToolError(
        error="SandboxNotFoundError",
        message="Sandbox does not exist.",
        details={"sandbox_id": "test-id"},
    )
    assert err.error == "SandboxNotFoundError"
    assert err.message == "Sandbox does not exist."
    assert err.details["sandbox_id"] == "test-id"
