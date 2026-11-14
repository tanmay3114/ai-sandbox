"""Integration tests for Phase 5 Agent Orchestration."""

from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.agent.llm.base import LLMMessage, LLMProvider, LLMResponse, ToolCallRequest
from app.api.dependencies import get_llm_provider_dependency
from app.core.config import SandboxSettings
from app.main import app
from app.mcp.server import create_mcp_server
from app.models.agent_task import TaskStatus
from app.sandbox.docker_backend import DockerSandboxBackend
from app.sandbox.engine import EphemeralSandboxEngine
from app.services.agent_orchestrator_service import AgentOrchestratorService
from app.services.sandbox_lifecycle_service import SandboxLifecycleService


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """TestClient fixture for FastAPI endpoints."""
    with TestClient(app) as test_client:
        yield test_client


class ScriptedLLMProvider(LLMProvider):
    """Deterministic scripted LLM provider for simulating multi-turn agent reasoning."""

    def __init__(self, turns: list[LLMResponse | Exception]) -> None:
        self.turns = list(turns)
        self.call_records: list[dict[str, Any]] = []

    async def generate_response(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.call_records.append({"messages": list(messages), "tools": tools})
        if not self.turns:
            raise RuntimeError("ScriptedLLMProvider ran out of mock turns.")
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        return turn


# -----------------------------------------------------------------------------
# 1. Multi-Step Task: Read Existing File, Write Code, Execute, Explain
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_read_modify_and_execute_workflow(
    db_session: Session,
    engine: EphemeralSandboxEngine,
    fast_settings: SandboxSettings,
):
    """Agent reads existing data.txt, computes sum via python script, and explains outcome."""
    backend = DockerSandboxBackend(config=fast_settings, engine=engine)
    lifecycle_service = SandboxLifecycleService(
        db=db_session, backend=backend, config=fast_settings
    )
    sandbox = lifecycle_service.create_sandbox(runtime="python", ttl_seconds=300)
    sandbox_id = sandbox.id

    # Seed existing workspace file
    lifecycle_service.write_file(sandbox_id, "numbers.txt", "10,20,30,40")

    # Scripted LLM interaction:
    # Turn 1: Model reads numbers.txt
    # Turn 2: Model writes calc.py
    # Turn 3: Model executes calc.py
    # Turn 4: Model outputs final answer
    turns = [
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="call_read",
                    name="read_file",
                    arguments={"path": "numbers.txt"},
                )
            ],
            finish_reason="tool_calls",
        ),
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="call_write",
                    name="write_file",
                    arguments={
                        "path": "calc.py",
                        "content": (
                            "with open('numbers.txt') as f:\n"
                            "    nums = [int(x) for x in f.read().strip().split(',')]\n"
                            "print(f'SUM={sum(nums)}')\n"
                        ),
                    },
                )
            ],
            finish_reason="tool_calls",
        ),
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="call_exec",
                    name="execute_code",
                    arguments={"code": "import subprocess; exec(open('calc.py').read())"},
                )
            ],
            finish_reason="tool_calls",
        ),
        LLMResponse(
            content="The sum of the numbers [10, 20, 30, 40] in numbers.txt is 100.",
            tool_calls=[],
            finish_reason="stop",
        ),
    ]

    llm = ScriptedLLMProvider(turns)
    orchestrator_service = AgentOrchestratorService(
        db=db_session,
        service=lifecycle_service,
        llm_provider=llm,
    )

    task = await orchestrator_service.create_and_run_task(
        sandbox_id=sandbox_id,
        prompt="Read numbers.txt, sum the values with a Python script, and report the result.",
    )

    assert task.status == TaskStatus.COMPLETED
    assert task.iterations == 4
    assert task.tool_calls_count == 3
    assert "sum of the numbers" in task.result_summary
    assert "100" in task.result_summary

    # Verify workspace file calc.py was persisted
    file_content = lifecycle_service.read_file(sandbox_id, "calc.py")
    assert "SUM={sum(nums)}" in file_content.content


# -----------------------------------------------------------------------------
# 2. Non-zero Exit Code Handling & Recovery
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_error_recovery_workflow(
    db_session: Session,
    engine: EphemeralSandboxEngine,
    fast_settings: SandboxSettings,
):
    """Agent encounters a bug (division by zero), inspects traceback, fixes code, and succeeds."""
    backend = DockerSandboxBackend(config=fast_settings, engine=engine)
    lifecycle_service = SandboxLifecycleService(
        db=db_session, backend=backend, config=fast_settings
    )
    sandbox = lifecycle_service.create_sandbox(runtime="python", ttl_seconds=300)
    sandbox_id = sandbox.id

    turns = [
        # Turn 1: Model writes buggy code
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="c1",
                    name="write_file",
                    arguments={
                        "path": "app.py",
                        "content": "val = 10 / 0\nprint(val)\n",
                    },
                )
            ],
            finish_reason="tool_calls",
        ),
        # Turn 2: Model executes app.py (will fail with exit_code=1)
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="c2",
                    name="execute_code",
                    arguments={"code": "exec(open('app.py').read())"},
                )
            ],
            finish_reason="tool_calls",
        ),
        # Turn 3: Model inspects error and rewrites app.py with the fix
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="c3",
                    name="write_file",
                    arguments={
                        "path": "app.py",
                        "content": "val = 10 / 2\nprint(f'RESULT={val}')\n",
                    },
                )
            ],
            finish_reason="tool_calls",
        ),
        # Turn 4: Model re-executes fixed code
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="c4",
                    name="execute_code",
                    arguments={"code": "exec(open('app.py').read())"},
                )
            ],
            finish_reason="tool_calls",
        ),
        # Turn 5: Model delivers final explanation
        LLMResponse(
            content="Fixed ZeroDivisionError in app.py. The program now outputs RESULT=5.0.",
            tool_calls=[],
            finish_reason="stop",
        ),
    ]

    llm = ScriptedLLMProvider(turns)
    orchestrator_service = AgentOrchestratorService(
        db=db_session,
        service=lifecycle_service,
        llm_provider=llm,
    )

    task = await orchestrator_service.create_and_run_task(
        sandbox_id=sandbox_id,
        prompt="Write and run app.py.",
    )

    assert task.status == TaskStatus.COMPLETED
    assert task.iterations == 5
    assert task.tool_calls_count == 4
    assert "Fixed ZeroDivisionError" in task.result_summary


# -----------------------------------------------------------------------------
# 3. Complete End-to-End Scenario: Fibonacci 20
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_fibonacci_complete_scenario(
    db_session: Session,
    engine: EphemeralSandboxEngine,
    fast_settings: SandboxSettings,
):
    """Verify complete end-to-end user scenario:

    Task: 'Create a Python program that calculates the first 20 Fibonacci numbers,
           save it as fibonacci.py, execute it, inspect the output, and explain the result.'
    """
    backend = DockerSandboxBackend(config=fast_settings, engine=engine)
    lifecycle_service = SandboxLifecycleService(
        db=db_session, backend=backend, config=fast_settings
    )
    sandbox = lifecycle_service.create_sandbox(runtime="python", ttl_seconds=300)
    sandbox_id = sandbox.id

    fib_code = (
        "def fibonacci(n):\n"
        "    seq = [0, 1]\n"
        "    while len(seq) < n:\n"
        "        seq.append(seq[-1] + seq[-2])\n"
        "    return seq[:n]\n\n"
        "res = fibonacci(20)\n"
        "print('FIBONACCI_20:', res)\n"
    )

    turns = [
        # 1. Agent inspects the sandbox
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="turn1_inspect",
                    name="get_sandbox",
                    arguments={},
                )
            ],
            finish_reason="tool_calls",
        ),
        # 2. Agent creates fibonacci.py
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="turn2_write",
                    name="write_file",
                    arguments={
                        "path": "fibonacci.py",
                        "content": fib_code,
                    },
                )
            ],
            finish_reason="tool_calls",
        ),
        # 3. Agent executes the program
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="turn3_exec",
                    name="execute_code",
                    arguments={
                        "code": "exec(open('fibonacci.py').read())",
                    },
                )
            ],
            finish_reason="tool_calls",
        ),
        # 4. Agent inspects execution output & 5. Verifies output
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="turn4_verify",
                    name="read_file",
                    arguments={
                        "path": "fibonacci.py",
                    },
                )
            ],
            finish_reason="tool_calls",
        ),
        # 6. Agent provides concise final response
        LLMResponse(
            content=(
                "I created and executed fibonacci.py in your sandbox. The first 20 Fibonacci "
                "numbers were successfully computed: [0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, "
                "144, 233, 377, 610, 987, 1597, 2584, 4181]. The 20th number is 4181."
            ),
            tool_calls=[],
            finish_reason="stop",
        ),
    ]

    llm = ScriptedLLMProvider(turns)
    orchestrator_service = AgentOrchestratorService(
        db=db_session,
        service=lifecycle_service,
        llm_provider=llm,
    )

    task = await orchestrator_service.create_and_run_task(
        sandbox_id=sandbox_id,
        prompt=(
            "Create a Python program that calculates the first 20 Fibonacci numbers, "
            "save it as fibonacci.py, execute it, inspect the output, and explain the result."
        ),
    )

    assert task.status == TaskStatus.COMPLETED
    assert task.iterations == 5
    assert task.tool_calls_count == 4
    assert "first 20 Fibonacci numbers" in task.result_summary
    assert "4181" in task.result_summary

    # Verify fibonacci.py was created in the real persistent workspace
    ws_file = lifecycle_service.read_file(sandbox_id, "fibonacci.py")
    assert "def fibonacci(n):" in ws_file.content

    # Verify execution job was tracked
    execs = orchestrator_service.get_task_executions(sandbox_id, task.id)
    assert len(execs) >= 1
    assert execs[0].exit_code == 0
    assert "FIBONACCI_20:" in execs[0].stdout


# -----------------------------------------------------------------------------
# 4. REST API Endpoint Integration Tests
# -----------------------------------------------------------------------------


def test_rest_api_agent_task_lifecycle(client: TestClient, db_session: Session):
    """Test POST, GET, list, and execution endpoints for agent tasks via REST API."""
    # 1. Create a sandbox via REST API
    sb_resp = client.post("/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 300})
    assert sb_resp.status_code == 201
    sandbox_id = sb_resp.json()["sandbox_id"]

    # 2. Mock LLM for the task endpoint
    fake_llm = ScriptedLLMProvider(
        [
            LLMResponse(
                content="Task completed without tool calls.",
                tool_calls=[],
                finish_reason="stop",
            )
        ]
    )
    app.dependency_overrides[get_llm_provider_dependency] = lambda: fake_llm

    try:
        # 3. POST /{sandbox_id}/agent/tasks
        task_resp = client.post(
            f"/api/v1/sandboxes/{sandbox_id}/agent/tasks",
            json={"prompt": "Say hello"},
        )
        assert task_resp.status_code == 200
        task_data = task_resp.json()
        assert task_data["status"] == "completed"
        assert task_data["result_summary"] == "Task completed without tool calls."
        task_id = task_data["task_id"]

        # 4. GET /{sandbox_id}/agent/tasks/{task_id}
        get_resp = client.get(f"/api/v1/sandboxes/{sandbox_id}/agent/tasks/{task_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["task_id"] == task_id

        # 5. GET /api/v1/agent/tasks/{task_id}
        direct_get = client.get(f"/api/v1/agent/tasks/{task_id}")
        assert direct_get.status_code == 200
        assert direct_get.json()["task_id"] == task_id

        # 6. GET /{sandbox_id}/agent/tasks (list)
        list_resp = client.get(f"/api/v1/sandboxes/{sandbox_id}/agent/tasks")
        assert list_resp.status_code == 200
        assert list_resp.json()["total"] >= 1

    finally:
        app.dependency_overrides.pop(get_llm_provider_dependency, None)


def test_rest_api_cross_sandbox_task_isolation(client: TestClient):
    """Verify attempting to get a task under the wrong sandbox_id returns 404."""
    # Create two sandboxes
    sb1 = client.post("/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 300}).json()
    sb2 = client.post("/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 300}).json()

    fake_llm = ScriptedLLMProvider([LLMResponse(content="Done.", tool_calls=[])])
    app.dependency_overrides[get_llm_provider_dependency] = lambda: fake_llm

    try:
        post_resp = client.post(
            f"/api/v1/sandboxes/{sb1['sandbox_id']}/agent/tasks",
            json={"prompt": "Task on sb1"},
        )
        assert post_resp.status_code == 200, post_resp.text
        task1 = post_resp.json()

        # Querying task1 through sb2 must return 404
        cross_url = f"/api/v1/sandboxes/{sb2['sandbox_id']}/agent/tasks/{task1['task_id']}"
        cross_resp = client.get(cross_url)
        assert cross_resp.status_code == 404
        assert "not found for sandbox" in cross_resp.json()["message"]
    finally:
        app.dependency_overrides.pop(get_llm_provider_dependency, None)


# -----------------------------------------------------------------------------
# 5. MCP Tool: run_agent_task Integration
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_run_agent_task_tool(
    db_session: Session,
    engine: EphemeralSandboxEngine,
    fast_settings: SandboxSettings,
):
    """Verify run_agent_task tool exposed in MCP executes task and enforces anti-recursion."""
    backend = DockerSandboxBackend(config=fast_settings, engine=engine)
    lifecycle_service = SandboxLifecycleService(
        db=db_session, backend=backend, config=fast_settings
    )
    sandbox = lifecycle_service.create_sandbox(runtime="python", ttl_seconds=300)

    from contextlib import contextmanager

    @contextmanager
    def mock_factory():
        yield lifecycle_service

    mcp = create_mcp_server(service_factory=mock_factory)
    from app.mcp.tools import register_mcp_tools

    # Register MCP tools with enable_agent_orchestrator=True
    register_mcp_tools(server=mcp, service_factory=mock_factory, enable_agent_orchestrator=True)

    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}
    assert "run_agent_task" in tool_names

    # Verify anti-recursion: AgentToolRegistry MUST NOT contain run_agent_task
    from app.agent.tool_registry import AgentToolRegistry

    internal_registry = AgentToolRegistry(
        service=lifecycle_service, authorized_sandbox_id=sandbox.id
    )
    assert "run_agent_task" not in internal_registry.tool_names
