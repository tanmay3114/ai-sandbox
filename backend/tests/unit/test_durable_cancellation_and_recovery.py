"""Unit tests for Phase 5.1: Durable Agent Task Recovery, Cancellation & Concurrency."""

import asyncio
import uuid
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.agent.llm.base import LLMMessage, LLMProvider, LLMResponse, ToolCallRequest
from app.agent.orchestrator import AgentOrchestrator
from app.core.exceptions import AgentCancelledError
from app.models.agent_task import TaskStatus
from app.models.sandbox import Sandbox, SandboxStatus, utc_now
from app.repositories.agent_task_repository import AgentTaskRepository
from app.services.agent_orchestrator_service import AgentOrchestratorService
from app.services.sandbox_lifecycle_service import SandboxLifecycleService


class MockLLM(LLMProvider):
    """Deterministic mock provider returning pre-programmed responses."""

    def __init__(self, responses: list[LLMResponse | Exception]) -> None:
        self.responses = list(responses)

    async def generate_response(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        if not self.responses:
            raise RuntimeError("MockLLM out of responses")
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


@pytest.fixture
def test_sandbox(db_session: Session) -> Sandbox:
    """Create a persistent active sandbox for testing agent tasks."""
    sb = Sandbox(
        id=uuid.uuid4(),
        status=SandboxStatus.RUNNING,
        runtime="python",
        ttl_seconds=300,
        expires_at=utc_now() + timedelta(seconds=300),
    )
    db_session.add(sb)
    db_session.commit()
    db_session.refresh(sb)
    return sb


# -----------------------------------------------------------------------------
# 1. Durable Cancellation Tests
# -----------------------------------------------------------------------------


def test_durable_cancellation_intent_committed_to_postgres(
    db_session: Session, test_sandbox: Sandbox
):
    """Verify record_cancellation_intent persists cancellation_requested_at in PostgreSQL."""
    repo = AgentTaskRepository(db_session)
    task = repo.create(sandbox_id=test_sandbox.id, task_description="Task to cancel")

    assert task.cancellation_requested_at is None
    assert task.status == TaskStatus.PENDING

    # Record cancellation intent
    updated = repo.record_cancellation_intent(task.id)
    assert updated is not None
    assert updated.cancellation_requested_at is not None

    # Query afresh from DB session
    fresh = repo.get_by_id(task.id)
    assert fresh is not None
    assert fresh.cancellation_requested_at is not None
    assert repo.is_cancellation_requested(task.id) is True


@pytest.mark.asyncio
async def test_orchestrator_aborts_on_database_cancellation_without_local_event():
    """Verify orchestrator checks DB cancellation callback and halts without local event."""
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

    mock_llm = MockLLM([])
    orchestrator = AgentOrchestrator(llm=mock_llm, service=mock_service)

    # Local event is NOT set, but DB callback returns True
    local_event = asyncio.Event()
    assert not local_event.is_set()

    with pytest.raises(AgentCancelledError) as exc_info:
        await orchestrator.run_task(
            task_id=uuid.uuid4(),
            sandbox_id=mock_sandbox.id,
            prompt="Task with DB cancellation",
            cancellation_token=local_event,
            is_cancelled_func=lambda: True,  # DB says cancellation requested
        )

    assert "cancelled by user" in str(exc_info.value)


@pytest.mark.asyncio
async def test_orchestrator_aborts_before_tool_execution_when_cancelled():
    """Verify orchestrator stops before dispatching a tool call once cancelled."""
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

    # Model requests a tool call
    mock_llm = MockLLM(
        [
            LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="c1", name="list_files", arguments={})],
                finish_reason="tool_calls",
            )
        ]
    )
    orchestrator = AgentOrchestrator(llm=mock_llm, service=mock_service)

    # Flag toggles to cancelled after model turn
    cancelled_flag = False

    def check_cancel() -> bool:
        return cancelled_flag

    # Trigger cancellation right after model outputs tool call
    original_generate = mock_llm.generate_response

    async def generate_and_cancel(*args, **kwargs):
        nonlocal cancelled_flag
        res = await original_generate(*args, **kwargs)
        cancelled_flag = True
        return res

    mock_llm.generate_response = generate_and_cancel

    with pytest.raises(AgentCancelledError):
        await orchestrator.run_task(
            task_id=uuid.uuid4(),
            sandbox_id=mock_sandbox.id,
            prompt="Task cancelling mid-turn",
            is_cancelled_func=check_cancel,
        )


def test_repeated_cancellation_is_idempotent(db_session: Session, test_sandbox: Sandbox):
    """Verify repeated cancellation requests do not fail or alter task state."""
    repo = AgentTaskRepository(db_session)
    task = repo.create(sandbox_id=test_sandbox.id, task_description="Idempotent cancellation")

    res1 = repo.record_cancellation_intent(task.id)
    assert res1 is not None
    assert res1.cancellation_requested_at is not None

    res2 = repo.record_cancellation_intent(task.id)
    assert res2 is not None
    # Both calls succeeded cleanly
    assert repo.is_cancellation_requested(task.id) is True


def test_terminal_task_cannot_be_overwritten_by_cancellation(
    db_session: Session, test_sandbox: Sandbox
):
    """Verify completed or failed tasks ignore cancellation requests."""
    repo = AgentTaskRepository(db_session)
    task = repo.create(sandbox_id=test_sandbox.id, task_description="Completed task")
    repo.mark_started(task)
    repo.mark_completed(
        task=task,
        result_summary="All done successfully",
        iterations=2,
        tool_calls_count=1,
        tool_history=[],
    )

    assert task.status == TaskStatus.COMPLETED

    # record_cancellation_intent on a terminal task returns None (no rows updated)
    res = repo.record_cancellation_intent(task.id)
    assert res is None

    # Refresh task; it remains COMPLETED
    fresh = repo.get_by_id(task.id)
    assert fresh.status == TaskStatus.COMPLETED
    assert fresh.cancellation_requested_at is None


# -----------------------------------------------------------------------------
# 2. Concurrency & Atomic Claim Tests
# -----------------------------------------------------------------------------


def test_atomic_task_claim_prevents_duplicate_workers(db_session: Session, test_sandbox: Sandbox):
    """Verify conditional atomic claim allows only one worker to claim a PENDING task."""
    repo = AgentTaskRepository(db_session)
    task = repo.create(sandbox_id=test_sandbox.id, task_description="Claim race task")

    # Worker 1 claims task
    claim1 = repo.claim_task(task_id=task.id, worker_id="worker_alpha")
    assert claim1 is not None
    assert claim1.status == TaskStatus.RUNNING
    assert claim1.worker_id == "worker_alpha"
    assert claim1.claimed_at is not None

    # Worker 2 attempts to claim the same task
    claim2 = repo.claim_task(task_id=task.id, worker_id="worker_beta")
    assert claim2 is None, "Worker 2 must not be able to claim an already running task"

    # Verify task state in database
    fresh = repo.get_by_id(task.id)
    assert fresh.status == TaskStatus.RUNNING
    assert fresh.worker_id == "worker_alpha"


# -----------------------------------------------------------------------------
# 3. Startup Reconciliation Tests
# -----------------------------------------------------------------------------


def test_reconciliation_running_task_without_cancellation(
    db_session: Session, test_sandbox: Sandbox
):
    """A RUNNING task without cancellation intent is marked FAILED with PROCESS_RESTARTED."""
    repo = AgentTaskRepository(db_session)
    task = repo.create(sandbox_id=test_sandbox.id, task_description="Running before crash")
    repo.mark_started(task, worker_id="crashed_worker")

    mock_service = MagicMock(spec=SandboxLifecycleService)
    mock_service.get_sandbox.return_value = test_sandbox
    mock_service.backend = MagicMock()

    orchestrator_service = AgentOrchestratorService(
        db=db_session,
        service=mock_service,
        llm_provider=MockLLM([]),
    )

    report = orchestrator_service.reconcile_interrupted_tasks()
    assert report["attempted"] == 1
    assert report["reconciled"] == 1
    assert report["failed"] == 1
    assert report["cancelled"] == 0

    fresh = repo.get_by_id(task.id)
    assert fresh.status == TaskStatus.FAILED
    assert fresh.interruption_reason == "PROCESS_RESTARTED"
    assert "process restart" in fresh.error_message


def test_reconciliation_running_task_with_cancellation(db_session: Session, test_sandbox: Sandbox):
    """A RUNNING task with cancellation intent is reconciled as CANCELLED."""
    repo = AgentTaskRepository(db_session)
    task = repo.create(sandbox_id=test_sandbox.id, task_description="Running with cancel intent")
    repo.mark_started(task)
    repo.record_cancellation_intent(task.id)

    mock_service = MagicMock(spec=SandboxLifecycleService)
    mock_service.get_sandbox.return_value = test_sandbox
    mock_service.backend = MagicMock()

    orchestrator_service = AgentOrchestratorService(
        db=db_session,
        service=mock_service,
        llm_provider=MockLLM([]),
    )

    report = orchestrator_service.reconcile_interrupted_tasks()
    assert report["attempted"] == 1
    assert report["reconciled"] == 1
    assert report["cancelled"] == 1
    assert report["failed"] == 0

    fresh = repo.get_by_id(task.id)
    assert fresh.status == TaskStatus.CANCELLED
    assert fresh.cancellation_requested_at is not None


def test_reconciliation_pending_task_marked_failed(db_session: Session, test_sandbox: Sandbox):
    """A PENDING task left after restart is marked FAILED with PROCESS_RESTARTED_BEFORE_START."""
    repo = AgentTaskRepository(db_session)
    task = repo.create(sandbox_id=test_sandbox.id, task_description="Pending before crash")

    mock_service = MagicMock(spec=SandboxLifecycleService)
    mock_service.get_sandbox.return_value = test_sandbox
    mock_service.backend = MagicMock()

    orchestrator_service = AgentOrchestratorService(
        db=db_session,
        service=mock_service,
        llm_provider=MockLLM([]),
    )

    report = orchestrator_service.reconcile_interrupted_tasks()
    assert report["attempted"] == 1
    assert report["reconciled"] == 1
    assert report["failed"] == 1

    fresh = repo.get_by_id(task.id)
    assert fresh.status == TaskStatus.FAILED
    assert fresh.interruption_reason == "PROCESS_RESTARTED_BEFORE_START"


def test_reconciliation_is_idempotent(db_session: Session, test_sandbox: Sandbox):
    """Verify running reconciliation multiple times leaves state unchanged."""
    repo = AgentTaskRepository(db_session)
    task = repo.create(sandbox_id=test_sandbox.id, task_description="Task for idempotence")
    repo.mark_started(task)

    mock_service = MagicMock(spec=SandboxLifecycleService)
    mock_service.get_sandbox.return_value = test_sandbox
    mock_service.backend = MagicMock()

    orchestrator_service = AgentOrchestratorService(
        db=db_session,
        service=mock_service,
        llm_provider=MockLLM([]),
    )

    # First reconciliation
    report1 = orchestrator_service.reconcile_interrupted_tasks()
    assert report1["reconciled"] == 1

    # Second reconciliation: zero nonterminal tasks to reconcile
    report2 = orchestrator_service.reconcile_interrupted_tasks()
    assert report2["attempted"] == 0
    assert report2["reconciled"] == 0

    fresh = repo.get_by_id(task.id)
    assert fresh.status == TaskStatus.FAILED
    assert fresh.interruption_reason == "PROCESS_RESTARTED"


def test_reconciliation_handles_expired_or_destroyed_sandbox(
    db_session: Session, test_sandbox: Sandbox
):
    """Tasks associated with expired/destroyed sandboxes are safely failed with correct reason."""
    repo = AgentTaskRepository(db_session)
    task = repo.create(sandbox_id=test_sandbox.id, task_description="Task with dead sandbox")
    repo.mark_started(task)

    # Mutate test_sandbox in DB to EXPIRED
    test_sandbox.status = SandboxStatus.EXPIRED
    test_sandbox.expires_at = utc_now() - timedelta(seconds=10)
    db_session.commit()
    db_session.refresh(test_sandbox)

    mock_service = MagicMock(spec=SandboxLifecycleService)
    mock_service.get_sandbox.return_value = test_sandbox
    mock_service.backend = MagicMock()

    orchestrator_service = AgentOrchestratorService(
        db=db_session,
        service=mock_service,
        llm_provider=MockLLM([]),
    )

    report = orchestrator_service.reconcile_interrupted_tasks()
    assert report["reconciled"] == 1
    assert report["failed"] == 1

    fresh = repo.get_by_id(task.id)
    assert fresh.status == TaskStatus.FAILED
    assert fresh.interruption_reason == "SANDBOX_EXPIRED"
