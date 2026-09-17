"""End-to-end integration tests for AI Agent workflow using tool adapter."""

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.agent.schemas import AgentToolError
from app.agent.tools import (
    create_sandbox_tool,
    execute_agent_tool,
    execute_code_tool,
)
from app.models.sandbox import utc_now
from app.sandbox.engine import EphemeralSandboxEngine
from app.schemas.sandbox import (
    JobExecutionResponse,
    SandboxDetailResponse,
    SandboxResponse,
)
from app.services.sandbox_lifecycle_service import SandboxLifecycleService


@pytest.mark.asyncio
async def test_complete_agent_workflow(
    db_session: Session,
    engine: EphemeralSandboxEngine,
):
    """Simulate full AI agent lifecycle:

    1. create_sandbox
    2. execute_code (calculation)
    3. get_execution_result (inspect past job)
    4. get_sandbox (verify execution count & status)
    5. destroy_sandbox
    6. verify rejection of execution on destroyed sandbox
    """
    service = SandboxLifecycleService(db=db_session, engine=engine)

    # 1. create_sandbox
    create_res = await execute_agent_tool(
        "create_sandbox",
        {"runtime": "python", "ttl_seconds": 300},
        service=service,
    )
    assert isinstance(create_res, SandboxResponse)
    assert create_res.status == "running"
    sandbox_id = create_res.sandbox_id

    # 2. execute_code
    exec_res = await execute_agent_tool(
        "execute_code",
        {
            "sandbox_id": str(sandbox_id),
            "code": "val = 40 + 2\nprint(f'ANSWER={val}')",
            "timeout_seconds": 5.0,
        },
        service=service,
    )
    assert isinstance(exec_res, JobExecutionResponse)
    assert exec_res.status == "completed"
    assert exec_res.exit_code == 0
    assert "ANSWER=42" in exec_res.stdout
    execution_id = exec_res.execution_id

    # 3. get_execution_result
    lookup_res = await execute_agent_tool(
        "get_execution_result",
        {
            "sandbox_id": str(sandbox_id),
            "execution_id": str(execution_id),
        },
        service=service,
    )
    assert isinstance(lookup_res, JobExecutionResponse)
    assert lookup_res.execution_id == execution_id
    assert lookup_res.status == "completed"
    assert "ANSWER=42" in lookup_res.stdout

    # 4. get_sandbox
    status_res = await execute_agent_tool(
        "get_sandbox",
        {"sandbox_id": str(sandbox_id)},
        service=service,
    )
    assert isinstance(status_res, SandboxDetailResponse)
    assert status_res.sandbox_id == sandbox_id
    assert status_res.status == "running"
    assert status_res.executions_count == 1

    # 5. destroy_sandbox
    destroy_res = await execute_agent_tool(
        "destroy_sandbox",
        {"sandbox_id": str(sandbox_id)},
        service=service,
    )
    assert isinstance(destroy_res, SandboxResponse)
    assert destroy_res.status == "destroyed"

    # 6. execute on destroyed sandbox returns structured error
    err_res = await execute_agent_tool(
        "execute_code",
        {"sandbox_id": str(sandbox_id), "code": "print('should fail')"},
        service=service,
    )
    assert isinstance(err_res, AgentToolError)
    assert err_res.error == "SandboxDestroyedError"


@pytest.mark.asyncio
async def test_agent_tool_failed_execution(
    db_session: Session,
    engine: EphemeralSandboxEngine,
):
    """Agent submits Python code that raises an unhandled runtime exception."""
    service = SandboxLifecycleService(db=db_session, engine=engine)
    create_res = create_sandbox_tool(service, {"runtime": "python", "ttl_seconds": 180})

    exec_res = await execute_code_tool(
        service,
        {"sandbox_id": str(create_res.sandbox_id), "code": "print(1 / 0)"},
    )
    assert isinstance(exec_res, JobExecutionResponse)
    assert exec_res.status == "failed"
    assert exec_res.exit_code != 0
    assert "ZeroDivisionError" in exec_res.stderr


@pytest.mark.asyncio
async def test_agent_tool_timed_out_execution(
    db_session: Session,
    engine: EphemeralSandboxEngine,
):
    """Agent submits Python code that exceeds the execution timeout."""
    service = SandboxLifecycleService(db=db_session, engine=engine)
    create_res = create_sandbox_tool(service, {"runtime": "python", "ttl_seconds": 180})

    exec_res = await execute_code_tool(
        service,
        {
            "sandbox_id": str(create_res.sandbox_id),
            "code": "while True: pass",
            "timeout_seconds": 1.0,
        },
    )
    assert isinstance(exec_res, JobExecutionResponse)
    assert exec_res.status == "timed_out"
    assert exec_res.exit_code is None


@pytest.mark.asyncio
async def test_agent_tool_expired_sandbox(
    db_session: Session,
    engine: EphemeralSandboxEngine,
):
    """Agent attempts execution on a TTL-expired sandbox."""
    service = SandboxLifecycleService(db=db_session, engine=engine)
    sandbox = service.create_sandbox(runtime="python", ttl_seconds=10)

    # Fast-forward expiry
    sandbox.expires_at = utc_now() - timedelta(seconds=20)
    db_session.commit()

    err_res = await execute_agent_tool(
        "execute_code",
        {"sandbox_id": str(sandbox.id), "code": "print('expired')"},
        service=service,
    )
    assert isinstance(err_res, AgentToolError)
    assert err_res.error == "SandboxExpiredError"


@pytest.mark.asyncio
async def test_agent_tool_execution_ownership_mismatch(
    db_session: Session,
    engine: EphemeralSandboxEngine,
):
    """Agent tries to query an execution belonging to another sandbox."""
    service = SandboxLifecycleService(db=db_session, engine=engine)
    s1 = service.create_sandbox(runtime="python", ttl_seconds=180)
    s2 = service.create_sandbox(runtime="python", ttl_seconds=180)

    exec1 = await service.execute_code(s1.id, "print('s1 job')")

    err_res = await execute_agent_tool(
        "get_execution_result",
        {"sandbox_id": str(s2.id), "execution_id": str(exec1.execution_id)},
        service=service,
    )
    assert isinstance(err_res, AgentToolError)
    assert err_res.error == "ExecutionNotFoundError"


@pytest.mark.asyncio
async def test_agent_tool_invalid_tool_name(
    db_session: Session,
    engine: EphemeralSandboxEngine,
):
    """Agent calls a non-existent tool name."""
    service = SandboxLifecycleService(db=db_session, engine=engine)
    err_res = await execute_agent_tool("unknown_tool", {}, service=service)
    assert isinstance(err_res, AgentToolError)
    assert err_res.error == "InvalidToolName"


@pytest.mark.asyncio
async def test_agent_tool_validation_error(
    db_session: Session,
    engine: EphemeralSandboxEngine,
):
    """Agent provides invalid schema parameters (e.g. empty code)."""
    service = SandboxLifecycleService(db=db_session, engine=engine)
    s = service.create_sandbox(runtime="python", ttl_seconds=180)

    err_res = await execute_agent_tool(
        "execute_code",
        {"sandbox_id": str(s.id), "code": ""},
        service=service,
    )
    assert isinstance(err_res, AgentToolError)
    assert err_res.error == "ValidationError"
