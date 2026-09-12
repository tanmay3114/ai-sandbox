"""Tests for Model Context Protocol (MCP) server integration and tool adapters."""

import ast
import json
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.schemas import AGENT_TOOLS
from app.core.exceptions import (
    ExecutionNotFoundError,
    SandboxDestroyedError,
    SandboxExpiredError,
    SandboxNotFoundError,
    SandboxTimeoutError,
)
from app.mcp.server import create_mcp_server
from app.models.execution_job import ExecutionJob, JobStatus
from app.models.sandbox import Sandbox, SandboxStatus
from app.schemas.sandbox import JobExecutionResponse


@pytest.fixture
def mock_lifecycle_service() -> MagicMock:
    """Provide a mock SandboxLifecycleService fixture."""
    service = MagicMock()

    now = datetime.now(UTC)
    sample_sandbox_id = uuid.uuid4()
    sample_exec_id = uuid.uuid4()

    service.create_sandbox.return_value = Sandbox(
        id=sample_sandbox_id,
        status=SandboxStatus.RUNNING,
        runtime="python",
        created_at=now,
        expires_at=now,
        destroyed_at=None,
        resource_config={"memory_limit": "256m"},
    )

    sample_job = ExecutionJob(
        id=sample_exec_id,
        sandbox_id=sample_sandbox_id,
        status=JobStatus.COMPLETED,
        code="print('test')",
        exit_code=0,
        stdout="test output\n",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        duration_ms=45,
        submitted_at=now,
        started_at=now,
        completed_at=now,
    )

    sample_sandbox = Sandbox(
        id=sample_sandbox_id,
        status=SandboxStatus.RUNNING,
        runtime="python",
        created_at=now,
        expires_at=now,
        destroyed_at=None,
        resource_config={"memory_limit": "256m"},
    )
    sample_sandbox.executions = [sample_job]

    service.get_sandbox.return_value = sample_sandbox

    destroyed_sandbox = Sandbox(
        id=sample_sandbox_id,
        status=SandboxStatus.DESTROYED,
        runtime="python",
        created_at=now,
        expires_at=now,
        destroyed_at=now,
        resource_config={},
    )
    service.delete_sandbox.return_value = destroyed_sandbox

    service.execute_code = AsyncMock(
        return_value=JobExecutionResponse(
            execution_id=sample_exec_id,
            sandbox_id=sample_sandbox_id,
            status="completed",
            exit_code=0,
            stdout="test output\n",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            duration_ms=45,
            submitted_at=now,
            started_at=now,
            completed_at=now,
            error_message=None,
        )
    )

    service.get_execution.return_value = JobExecutionResponse(
        execution_id=sample_exec_id,
        sandbox_id=sample_sandbox_id,
        status="completed",
        exit_code=0,
        stdout="test output\n",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        duration_ms=45,
        submitted_at=now,
        started_at=now,
        completed_at=now,
        error_message=None,
    )

    return service


@pytest.fixture
def mcp_server(mock_lifecycle_service: MagicMock):
    """Provide an MCPServer instance configured with mock service factory."""

    @contextmanager
    def factory():
        yield mock_lifecycle_service

    return create_mcp_server(service_factory=factory)


def _parse_tool_result(result: Any) -> dict[str, Any]:
    """Helper to extract JSON dict from MCP tool CallToolResult content."""
    assert result is not None
    assert len(result.content) > 0
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_mcp_server_initialization(mcp_server):
    """1. MCP server initializes successfully with proper metadata."""
    assert mcp_server.name == "ai-sandbox-platform"
    assert mcp_server.version == "0.1.0"
    assert "ephemeral sandbox" in mcp_server.description.lower()


@pytest.mark.asyncio
async def test_mcp_required_tools_registered_and_names(mcp_server):
    """2 & 3. Required tools are registered and tool names are correct."""
    tools = await mcp_server.list_tools()
    tool_names = {t.name for t in tools}
    expected_tools = {
        "create_sandbox",
        "execute_code",
        "get_execution_result",
        "get_sandbox",
        "destroy_sandbox",
    }
    assert tool_names == expected_tools


@pytest.mark.asyncio
async def test_mcp_tool_descriptions_present(mcp_server):
    """4. Tool descriptions are present and match canonical agent tool descriptions."""
    tools = await mcp_server.list_tools()
    for tool in tools:
        assert tool.description is not None
        assert len(tool.description.strip()) > 0
        assert tool.description == AGENT_TOOLS[tool.name].description


@pytest.mark.asyncio
async def test_mcp_input_schemas_valid(mcp_server):
    """5. Input schemas are present and valid for all registered MCP tools."""
    tools = await mcp_server.list_tools()
    tool_map = {t.name: t for t in tools}

    # create_sandbox schema
    cs_props = tool_map["create_sandbox"].input_schema["properties"]
    assert "runtime" in cs_props
    assert "ttl_seconds" in cs_props
    assert cs_props["runtime"]["default"] == "python"

    # execute_code schema
    ec_props = tool_map["execute_code"].input_schema["properties"]
    assert "sandbox_id" in ec_props
    assert "code" in ec_props
    assert "timeout_seconds" in ec_props
    assert tool_map["execute_code"].input_schema["required"] == ["sandbox_id", "code"]

    # get_execution_result schema
    ger_props = tool_map["get_execution_result"].input_schema["properties"]
    assert "sandbox_id" in ger_props
    assert "execution_id" in ger_props

    # get_sandbox schema
    gs_props = tool_map["get_sandbox"].input_schema["properties"]
    assert "sandbox_id" in gs_props

    # destroy_sandbox schema
    ds_props = tool_map["destroy_sandbox"].input_schema["properties"]
    assert "sandbox_id" in ds_props


@pytest.mark.asyncio
async def test_mcp_create_sandbox_delegation(mcp_server, mock_lifecycle_service):
    """6. create_sandbox delegates to existing sandbox lifecycle service."""
    result = await mcp_server.call_tool("create_sandbox", {"runtime": "python", "ttl_seconds": 180})
    data = _parse_tool_result(result)

    assert "sandbox_id" in data
    assert data["status"] == "running"
    assert data["runtime"] == "python"

    mock_lifecycle_service.create_sandbox.assert_called_once_with(
        runtime="python",
        ttl_seconds=180,
    )


@pytest.mark.asyncio
async def test_mcp_execute_code_delegation(mcp_server, mock_lifecycle_service):
    """7. execute_code delegates to existing sandbox execution logic."""
    target_id = str(uuid.uuid4())
    result = await mcp_server.call_tool(
        "execute_code",
        {
            "sandbox_id": target_id,
            "code": "print('hello from mcp')",
            "timeout_seconds": 10.0,
        },
    )
    data = _parse_tool_result(result)

    assert data["status"] == "completed"
    assert data["exit_code"] == 0
    assert data["stdout"] == "test output\n"

    mock_lifecycle_service.execute_code.assert_awaited_once_with(
        sandbox_id=uuid.UUID(target_id),
        code="print('hello from mcp')",
        timeout_seconds=10.0,
    )


@pytest.mark.asyncio
async def test_mcp_get_execution_result_delegation(mcp_server, mock_lifecycle_service):
    """8. get_execution_result delegates correctly."""
    target_sandbox_id = str(uuid.uuid4())
    target_exec_id = str(uuid.uuid4())

    result = await mcp_server.call_tool(
        "get_execution_result",
        {
            "sandbox_id": target_sandbox_id,
            "execution_id": target_exec_id,
        },
    )
    data = _parse_tool_result(result)

    assert data["status"] == "completed"
    assert data["duration_ms"] == 45

    mock_lifecycle_service.get_execution.assert_called_once_with(
        sandbox_id=uuid.UUID(target_sandbox_id),
        execution_id=uuid.UUID(target_exec_id),
    )


@pytest.mark.asyncio
async def test_mcp_get_sandbox_delegation(mcp_server, mock_lifecycle_service):
    """9. get_sandbox delegates correctly."""
    target_sandbox_id = str(uuid.uuid4())

    result = await mcp_server.call_tool(
        "get_sandbox",
        {
            "sandbox_id": target_sandbox_id,
        },
    )
    data = _parse_tool_result(result)

    assert data["status"] == "running"
    assert data["executions_count"] == 1

    mock_lifecycle_service.get_sandbox.assert_called_once_with(
        uuid.UUID(target_sandbox_id),
    )


@pytest.mark.asyncio
async def test_mcp_destroy_sandbox_delegation(mcp_server, mock_lifecycle_service):
    """10. destroy_sandbox delegates correctly."""
    target_sandbox_id = str(uuid.uuid4())

    result = await mcp_server.call_tool(
        "destroy_sandbox",
        {
            "sandbox_id": target_sandbox_id,
        },
    )
    data = _parse_tool_result(result)

    assert data["status"] == "destroyed"

    mock_lifecycle_service.delete_sandbox.assert_called_once_with(
        uuid.UUID(target_sandbox_id),
    )


@pytest.mark.asyncio
async def test_mcp_invalid_arguments_rejected_safely(mcp_server):
    """11. Invalid arguments are rejected safely without crashing the server."""
    from mcp.server.mcpserver.exceptions import ToolError

    # Invalid runtime (rejected by CreateSandboxInput domain validation)
    res1 = await mcp_server.call_tool("create_sandbox", {"runtime": "invalid_runtime"})
    data1 = _parse_tool_result(res1)
    assert data1["error"] == "ValidationError"
    assert "Input arguments failed schema validation." in data1["message"]

    # Invalid TTL out of bounds (rejected by MCP schema validator)
    with pytest.raises(ToolError) as exc_info:
        await mcp_server.call_tool("create_sandbox", {"ttl_seconds": 1})
    assert "greater than or equal to 10" in str(exc_info.value)

    # Empty/whitespace code (rejected by ExecuteCodeInput validator)
    res3 = await mcp_server.call_tool(
        "execute_code",
        {"sandbox_id": str(uuid.uuid4()), "code": "   "},
    )
    data3 = _parse_tool_result(res3)
    assert data3["error"] == "ValidationError"

    # Bad UUID string (rejected by ExecuteCodeInput UUID validator)
    res4 = await mcp_server.call_tool(
        "execute_code",
        {"sandbox_id": "not-a-valid-uuid", "code": "print(1)"},
    )
    data4 = _parse_tool_result(res4)
    assert data4["error"] == "ValidationError"


@pytest.mark.asyncio
async def test_mcp_tool_service_failures_returned_safely(mcp_server, mock_lifecycle_service):
    """12. Tool/service domain failures are returned safely as structured error payloads."""
    target_id = uuid.uuid4()

    # SandboxNotFoundError
    mock_lifecycle_service.get_sandbox.side_effect = SandboxNotFoundError(
        "Sandbox does not exist",
        details={"sandbox_id": str(target_id)},
    )
    res = await mcp_server.call_tool("get_sandbox", {"sandbox_id": str(target_id)})
    data = _parse_tool_result(res)
    assert data["error"] == "SandboxNotFoundError"
    assert data["message"] == "Sandbox does not exist"

    # SandboxExpiredError
    mock_lifecycle_service.execute_code.side_effect = SandboxExpiredError(
        "Sandbox has expired",
        details={"sandbox_id": str(target_id)},
    )
    res = await mcp_server.call_tool(
        "execute_code", {"sandbox_id": str(target_id), "code": "print(1)"}
    )
    data = _parse_tool_result(res)
    assert data["error"] == "SandboxExpiredError"

    # SandboxDestroyedError
    mock_lifecycle_service.execute_code.side_effect = SandboxDestroyedError(
        "Sandbox is destroyed",
        details={"sandbox_id": str(target_id)},
    )
    res = await mcp_server.call_tool(
        "execute_code", {"sandbox_id": str(target_id), "code": "print(1)"}
    )
    data = _parse_tool_result(res)
    assert data["error"] == "SandboxDestroyedError"

    # ExecutionNotFoundError
    mock_lifecycle_service.get_execution.side_effect = ExecutionNotFoundError(
        "Execution not found",
        details={"execution_id": str(uuid.uuid4())},
    )
    res = await mcp_server.call_tool(
        "get_execution_result",
        {"sandbox_id": str(target_id), "execution_id": str(uuid.uuid4())},
    )
    data = _parse_tool_result(res)
    assert data["error"] == "ExecutionNotFoundError"

    # SandboxTimeoutError
    mock_lifecycle_service.execute_code.side_effect = SandboxTimeoutError(
        "Execution timed out",
        details={"timeout_seconds": 5.0},
    )
    res = await mcp_server.call_tool(
        "execute_code", {"sandbox_id": str(target_id), "code": "import time; time.sleep(10)"}
    )
    data = _parse_tool_result(res)
    assert data["error"] == "SandboxTimeoutError"


@pytest.mark.asyncio
async def test_mcp_unexpected_error_sanitizes_secrets(mcp_server, mock_lifecycle_service):
    """Verify unexpected exception details and secrets do not leak to MCP callers."""
    secret = "INTERNAL_SECRET_SHOULD_NOT_LEAK"
    mock_lifecycle_service.get_sandbox.side_effect = RuntimeError(f"Database crash with {secret}")

    res = await mcp_server.call_tool("get_sandbox", {"sandbox_id": str(uuid.uuid4())})
    data = _parse_tool_result(res)

    assert data["error"] == "InternalToolError"
    assert data["message"] == "An unexpected error occurred while executing the tool."
    assert data["details"] == {}
    assert secret not in json.dumps(data)
    assert secret not in res.content[0].text


@pytest.mark.asyncio
async def test_mcp_unknown_inputs_cannot_bypass_validation(mcp_server, mock_lifecycle_service):
    """13. Injected arbitrary arguments cannot bypass security validation."""
    target_id = str(uuid.uuid4())
    # Calling execute_code with injected Docker parameters
    result = await mcp_server.call_tool(
        "execute_code",
        {
            "sandbox_id": target_id,
            "code": "print(1)",
            "image": "alpine:latest",
            "privileged": True,
            "network": "bridge",
            "volumes": {"/etc": {"bind": "/host_etc", "mode": "rw"}},
        },
    )
    data = _parse_tool_result(result)
    assert data["status"] == "completed"

    # Verify that the service was called ONLY with validated parameters
    mock_lifecycle_service.execute_code.assert_awaited_once_with(
        sandbox_id=uuid.UUID(target_id),
        code="print(1)",
        timeout_seconds=None,
    )


def test_mcp_contains_no_direct_docker_logic():
    """14. MCP contains no direct Docker SDK imports or execution logic."""
    from app.core.config import _REPO_ROOT

    mcp_dir = Path(_REPO_ROOT) / "app" / "mcp"
    mcp_files = list(mcp_dir.glob("*.py"))
    assert len(mcp_files) > 0

    for file_path in mcp_files:
        tree = ast.parse(file_path.read_text("utf-8"), filename=str(file_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "docker", (
                        f"Direct 'docker' import detected in {file_path.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                assert node.module != "docker", (
                    f"Direct 'from docker' import detected in {file_path.name}"
                )
