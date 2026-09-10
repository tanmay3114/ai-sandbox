"""Integration tests for SandboxRepository and ExecutionRepository."""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.models.execution_job import JobStatus
from app.models.sandbox import SandboxStatus, utc_now
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.sandbox_repository import SandboxRepository


def test_sandbox_repository_crud(db_session: Session):
    """Test SandboxRepository CRUD and query operations."""
    repo = SandboxRepository(db_session)
    sandbox = repo.create(
        runtime="python",
        ttl_seconds=120,
        resource_config={"mem_limit": "256m"},
    )
    assert sandbox.id is not None
    assert sandbox.status == SandboxStatus.RUNNING

    # Fetch by ID
    fetched = repo.get_by_id(sandbox.id)
    assert fetched is not None
    assert fetched.id == sandbox.id

    # Update status
    updated = repo.update_status(sandbox, SandboxStatus.DESTROYED)
    assert updated.status == SandboxStatus.DESTROYED
    assert updated.destroyed_at is not None


def test_sandbox_repository_expired_query(db_session: Session):
    """Test get_expired_active correctly filters only expired and non-destroyed sandboxes."""
    repo = SandboxRepository(db_session)
    now = utc_now()

    # 1. Active not expired
    s1 = repo.create(runtime="python", ttl_seconds=300, resource_config={})

    # 2. Active but expired
    s2 = repo.create(runtime="python", ttl_seconds=10, resource_config={})
    s2.expires_at = now - timedelta(seconds=20)
    db_session.commit()

    # 3. Expired but already destroyed
    s3 = repo.create(runtime="python", ttl_seconds=10, resource_config={})
    s3.expires_at = now - timedelta(seconds=20)
    s3.status = SandboxStatus.DESTROYED
    db_session.commit()

    expired_active = repo.get_expired_active(now=now)
    expired_ids = [s.id for s in expired_active]

    assert s2.id in expired_ids
    assert s1.id not in expired_ids
    assert s3.id not in expired_ids


def test_execution_repository_lifecycle(db_session: Session):
    """Test ExecutionRepository job lifecycle transitions."""
    sandbox_repo = SandboxRepository(db_session)
    exec_repo = ExecutionRepository(db_session)

    sandbox = sandbox_repo.create(runtime="python", ttl_seconds=300, resource_config={})

    # Create queued job
    job = exec_repo.create(
        sandbox_id=sandbox.id,
        code="print('test')",
        timeout_seconds=5.0,
    )
    assert job.status == JobStatus.QUEUED
    assert job.submitted_at is not None

    # Mark started
    exec_repo.mark_started(job)
    assert job.status == JobStatus.RUNNING
    assert job.started_at is not None

    # Mark completed
    exec_repo.mark_completed(
        job=job,
        status=JobStatus.COMPLETED,
        exit_code=0,
        stdout="test\n",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        duration_ms=45,
    )
    assert job.status == JobStatus.COMPLETED
    assert job.completed_at is not None
    assert job.exit_code == 0
    assert job.stdout == "test\n"

    # List by sandbox
    jobs = exec_repo.list_by_sandbox(sandbox.id)
    assert len(jobs) == 1
    assert jobs[0].id == job.id
