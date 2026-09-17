"""Tests for SandboxLifecycleService."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import (
    DockerEngineError,
    ExecutionNotFoundError,
    SandboxDestroyedError,
    SandboxExpiredError,
    SandboxNotFoundError,
)
from app.models.sandbox import SandboxStatus, utc_now
from app.repositories.execution_repository import ExecutionRepository
from app.sandbox.engine import EphemeralSandboxEngine
from app.services.sandbox_lifecycle_service import SandboxLifecycleService


def test_service_create_and_get(db_session: Session, engine: EphemeralSandboxEngine):
    """Test creating and retrieving a sandbox session."""
    service = SandboxLifecycleService(db=db_session, engine=engine)
    sandbox = service.create_sandbox(runtime="python", ttl_seconds=180)

    assert sandbox.id is not None
    assert sandbox.status == SandboxStatus.RUNNING
    assert sandbox.ttl_seconds == 180

    fetched = service.get_sandbox(sandbox.id)
    assert fetched.id == sandbox.id
    assert fetched.status == SandboxStatus.RUNNING


def test_service_delete_idempotent(db_session: Session, engine: EphemeralSandboxEngine):
    """Test destroying a sandbox and repeated idempotent destruction."""
    service = SandboxLifecycleService(db=db_session, engine=engine)
    sandbox = service.create_sandbox(runtime="python", ttl_seconds=180)

    deleted = service.delete_sandbox(sandbox.id)
    assert deleted.status == SandboxStatus.DESTROYED
    assert deleted.destroyed_at is not None

    # Repeated delete must be idempotent
    repeated = service.delete_sandbox(sandbox.id)
    assert repeated.status == SandboxStatus.DESTROYED


def test_service_not_found(db_session: Session, engine: EphemeralSandboxEngine):
    """Test that querying an unknown UUID raises SandboxNotFoundError."""
    service = SandboxLifecycleService(db=db_session, engine=engine)
    random_id = uuid.uuid4()

    with pytest.raises(SandboxNotFoundError):
        service.get_sandbox(random_id)

    with pytest.raises(SandboxNotFoundError):
        service.delete_sandbox(random_id)


@pytest.mark.asyncio
async def test_service_execute_code_success(db_session: Session, engine: EphemeralSandboxEngine):
    """Test executing code within an active persistent sandbox."""
    service = SandboxLifecycleService(db=db_session, engine=engine)
    sandbox = service.create_sandbox(runtime="python", ttl_seconds=180)

    result = await service.execute_code(
        sandbox_id=sandbox.id,
        code="print('Lifecycle Execution Success')",
    )

    assert result.sandbox_id == sandbox.id
    assert result.status == "completed"
    assert result.exit_code == 0
    assert "Lifecycle Execution Success" in result.stdout
    assert result.submitted_at is not None
    assert result.completed_at is not None

    # Verify sandbox is back to RUNNING state
    db_session.refresh(sandbox)
    assert sandbox.status == SandboxStatus.RUNNING
    assert len(sandbox.executions) == 1


@pytest.mark.asyncio
async def test_service_execute_on_destroyed_sandbox_fails(
    db_session: Session,
    engine: EphemeralSandboxEngine,
):
    """Test that executing code on a destroyed sandbox raises SandboxDestroyedError."""
    service = SandboxLifecycleService(db=db_session, engine=engine)
    sandbox = service.create_sandbox(runtime="python", ttl_seconds=180)
    service.delete_sandbox(sandbox.id)

    with pytest.raises(SandboxDestroyedError):
        await service.execute_code(sandbox_id=sandbox.id, code="print('fail')")


@pytest.mark.asyncio
async def test_service_execute_on_expired_sandbox_fails(
    db_session: Session,
    engine: EphemeralSandboxEngine,
):
    """Test that executing code on an expired sandbox raises SandboxExpiredError."""
    service = SandboxLifecycleService(db=db_session, engine=engine)
    sandbox = service.create_sandbox(runtime="python", ttl_seconds=10)

    # Force expiration
    sandbox.expires_at = utc_now() - timedelta(seconds=20)
    db_session.commit()

    with pytest.raises(SandboxExpiredError):
        await service.execute_code(sandbox_id=sandbox.id, code="print('fail')")


def test_service_cleanup_expired_sandboxes(db_session: Session, engine: EphemeralSandboxEngine):
    """Test that cleanup_expired_sandboxes sweeps all expired active sandboxes."""
    service = SandboxLifecycleService(db=db_session, engine=engine)
    now = utc_now()

    # Create active sandbox
    s_active = service.create_sandbox(runtime="python", ttl_seconds=300)

    # Create expired sandbox
    s_expired = service.create_sandbox(runtime="python", ttl_seconds=10)
    s_expired.expires_at = now - timedelta(seconds=30)
    db_session.commit()

    cleaned = service.cleanup_expired_sandboxes()
    assert cleaned == 1

    db_session.refresh(s_expired)
    assert s_expired.status == SandboxStatus.EXPIRED

    db_session.refresh(s_active)
    assert s_active.status == SandboxStatus.RUNNING


def test_service_get_expired_sandbox_preserves_expired_state(
    db_session: Session, engine: EphemeralSandboxEngine
):
    """A TTL-expired sandbox remains visible as expired instead of silently destroyed."""
    service = SandboxLifecycleService(db=db_session, engine=engine)
    sandbox = service.create_sandbox(runtime="python", ttl_seconds=10)
    sandbox.expires_at = utc_now() - timedelta(seconds=1)
    db_session.commit()

    fetched = service.get_sandbox(sandbox.id)

    assert fetched.status == SandboxStatus.EXPIRED


@pytest.mark.asyncio
async def test_service_persists_engine_failure_as_failed_job(db_session: Session):
    """An infrastructure error finalizes the job instead of leaving it running."""

    class FailingEngine:
        def execute(self, *_args: object) -> None:
            raise DockerEngineError("unavailable")

    service = SandboxLifecycleService(db=db_session, engine=FailingEngine())  # type: ignore[arg-type]
    sandbox = service.create_sandbox(runtime="python", ttl_seconds=180)

    with pytest.raises(DockerEngineError):
        await service.execute_code(sandbox.id, "print('never runs')")

    jobs = ExecutionRepository(db_session).list_by_sandbox(sandbox.id)
    assert len(jobs) == 1
    assert jobs[0].status == "failed"
    assert jobs[0].completed_at is not None
    assert jobs[0].error_message == "Execution infrastructure failure"


@pytest.mark.asyncio
async def test_service_get_execution_success(db_session: Session, engine: EphemeralSandboxEngine):
    """Test retrieving a historical execution record by sandbox_id and execution_id."""
    service = SandboxLifecycleService(db=db_session, engine=engine)
    sandbox = service.create_sandbox(runtime="python", ttl_seconds=180)

    exec_res = await service.execute_code(sandbox.id, "print('history check')")

    fetched_exec = service.get_execution(sandbox.id, exec_res.execution_id)
    assert fetched_exec.execution_id == exec_res.execution_id
    assert fetched_exec.sandbox_id == sandbox.id
    assert fetched_exec.status == "completed"
    assert "history check" in fetched_exec.stdout
    assert fetched_exec.exit_code == 0
    assert fetched_exec.completed_at is not None


def test_service_get_execution_not_found(db_session: Session, engine: EphemeralSandboxEngine):
    """Test retrieving a non-existent execution ID raises ExecutionNotFoundError."""
    service = SandboxLifecycleService(db=db_session, engine=engine)
    sandbox = service.create_sandbox(runtime="python", ttl_seconds=180)
    random_exec_id = uuid.uuid4()

    with pytest.raises(ExecutionNotFoundError):
        service.get_execution(sandbox.id, random_exec_id)


@pytest.mark.asyncio
async def test_service_get_execution_mismatch_sandbox(
    db_session: Session, engine: EphemeralSandboxEngine
):
    """Test retrieving an execution belonging to another sandbox raises ExecutionNotFoundError."""
    service = SandboxLifecycleService(db=db_session, engine=engine)
    sandbox1 = service.create_sandbox(runtime="python", ttl_seconds=180)
    sandbox2 = service.create_sandbox(runtime="python", ttl_seconds=180)

    exec1 = await service.execute_code(sandbox1.id, "print('sandbox 1')")

    with pytest.raises(ExecutionNotFoundError):
        service.get_execution(sandbox2.id, exec1.execution_id)

