"""Unit and integration tests for persistent models and state machine transitions."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.models.execution_job import ExecutionJob, JobStatus
from app.models.sandbox import (
    InvalidStateTransitionError,
    Sandbox,
    SandboxStatus,
    utc_now,
)


def test_sandbox_state_machine_valid_transitions():
    """Verify legal state transitions through the sandbox lifecycle."""
    sandbox = Sandbox(
        id=uuid.uuid4(),
        status=SandboxStatus.CREATING,
        runtime="python",
        ttl_seconds=300,
        expires_at=utc_now() + timedelta(seconds=300),
    )

    # CREATING -> RUNNING
    assert sandbox.can_transition_to(SandboxStatus.RUNNING)
    sandbox.transition_to(SandboxStatus.RUNNING)
    assert sandbox.status == SandboxStatus.RUNNING

    # RUNNING -> EXECUTING
    assert sandbox.can_transition_to(SandboxStatus.EXECUTING)
    sandbox.transition_to(SandboxStatus.EXECUTING)
    assert sandbox.status == SandboxStatus.EXECUTING

    # EXECUTING -> RUNNING (task finished, ready for next command)
    assert sandbox.can_transition_to(SandboxStatus.RUNNING)
    sandbox.transition_to(SandboxStatus.RUNNING)
    assert sandbox.status == SandboxStatus.RUNNING

    # RUNNING -> DESTROYING
    assert sandbox.can_transition_to(SandboxStatus.DESTROYING)
    sandbox.transition_to(SandboxStatus.DESTROYING)
    assert sandbox.status == SandboxStatus.DESTROYING

    # DESTROYING -> DESTROYED
    assert sandbox.can_transition_to(SandboxStatus.DESTROYED)
    sandbox.transition_to(SandboxStatus.DESTROYED)
    assert sandbox.status == SandboxStatus.DESTROYED
    assert sandbox.destroyed_at is not None


def test_sandbox_state_machine_invalid_transitions():
    """Verify that illegal transitions are strictly rejected with InvalidStateTransitionError."""
    sandbox = Sandbox(
        id=uuid.uuid4(),
        status=SandboxStatus.DESTROYED,
        runtime="python",
        ttl_seconds=300,
        expires_at=utc_now() + timedelta(seconds=300),
    )

    # Terminal state cannot transition to active states
    assert not sandbox.can_transition_to(SandboxStatus.RUNNING)
    with pytest.raises(InvalidStateTransitionError):
        sandbox.transition_to(SandboxStatus.RUNNING)

    with pytest.raises(InvalidStateTransitionError):
        sandbox.transition_to(SandboxStatus.EXECUTING)


def test_sandbox_expiration_logic():
    """Verify is_expired and is_active properties."""
    now = utc_now()
    active_sandbox = Sandbox(
        id=uuid.uuid4(),
        status=SandboxStatus.RUNNING,
        runtime="python",
        ttl_seconds=300,
        expires_at=now + timedelta(seconds=300),
    )
    assert not active_sandbox.is_expired
    assert active_sandbox.is_active

    expired_sandbox = Sandbox(
        id=uuid.uuid4(),
        status=SandboxStatus.RUNNING,
        runtime="python",
        ttl_seconds=300,
        expires_at=now - timedelta(seconds=10),
    )
    assert expired_sandbox.is_expired
    assert expired_sandbox.is_active


def test_expired_sandbox_is_terminal_and_cannot_execute():
    """TTL expiry is a lifecycle state distinct from destruction or execution timeout."""
    sandbox = Sandbox(
        id=uuid.uuid4(),
        status=SandboxStatus.RUNNING,
        runtime="python",
        ttl_seconds=300,
        expires_at=utc_now() - timedelta(seconds=1),
    )

    sandbox.transition_to(SandboxStatus.EXPIRED)

    assert sandbox.status == SandboxStatus.EXPIRED
    assert not sandbox.is_active
    assert not sandbox.can_transition_to(SandboxStatus.EXECUTING)
    assert sandbox.can_transition_to(SandboxStatus.DESTROYING)


def test_execution_job_state_machine_rejects_invalid_transitions():
    """Execution jobs cannot skip from queued straight to a final success state."""
    job = ExecutionJob(
        id=uuid.uuid4(),
        sandbox_id=uuid.uuid4(),
        status=JobStatus.QUEUED,
        code="print('test')",
        timeout_seconds=5.0,
    )

    with pytest.raises(InvalidStateTransitionError):
        job.transition_to(JobStatus.COMPLETED)

    job.transition_to(JobStatus.RUNNING)
    job.transition_to(JobStatus.TIMED_OUT)
    assert job.status == JobStatus.TIMED_OUT

    with pytest.raises(InvalidStateTransitionError):
        job.transition_to(JobStatus.RUNNING)


def test_database_persistence_and_cascade(db_session: Session):
    """Verify database persistence of Sandbox and cascade delete to ExecutionJobs."""
    sandbox_id = uuid.uuid4()
    now = utc_now()
    sandbox = Sandbox(
        id=sandbox_id,
        status=SandboxStatus.RUNNING,
        runtime="python",
        ttl_seconds=300,
        created_at=now,
        expires_at=now + timedelta(seconds=300),
        resource_config={"memory": "256m"},
    )
    db_session.add(sandbox)
    db_session.commit()

    job_id = uuid.uuid4()
    job = ExecutionJob(
        id=job_id,
        sandbox_id=sandbox_id,
        status=JobStatus.QUEUED,
        code="print('persisted')",
        timeout_seconds=5.0,
        submitted_at=now,
    )
    db_session.add(job)
    db_session.commit()

    # Query back
    fetched_sandbox = db_session.get(Sandbox, sandbox_id)
    assert fetched_sandbox is not None
    assert len(fetched_sandbox.executions) == 1
    assert fetched_sandbox.executions[0].code == "print('persisted')"

    # Cascade deletion
    db_session.delete(fetched_sandbox)
    db_session.commit()

    assert db_session.get(Sandbox, sandbox_id) is None
    assert db_session.get(ExecutionJob, job_id) is None
