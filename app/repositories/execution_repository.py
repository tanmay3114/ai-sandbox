"""Repository for ExecutionJob database persistence."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.execution_job import ExecutionJob, JobStatus
from app.models.sandbox import utc_now


class ExecutionRepository:
    """Encapsulates PostgreSQL database operations for ExecutionJob entities."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        sandbox_id: uuid.UUID,
        code: str,
        timeout_seconds: float,
        job_id: uuid.UUID | None = None,
    ) -> ExecutionJob:
        """Create and persist a new execution record in QUEUED state."""
        job = ExecutionJob(
            id=job_id or uuid.uuid4(),
            sandbox_id=sandbox_id,
            status=JobStatus.QUEUED,
            code=code,
            timeout_seconds=timeout_seconds,
            submitted_at=utc_now(),
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def mark_started(self, job: ExecutionJob) -> ExecutionJob:
        """Update job to RUNNING state with start timestamp."""
        job.transition_to(JobStatus.RUNNING)
        job.started_at = utc_now()
        self.db.commit()
        self.db.refresh(job)
        return job

    def mark_completed(
        self,
        job: ExecutionJob,
        status: JobStatus,
        exit_code: int | None,
        stdout: str,
        stderr: str,
        stdout_truncated: bool,
        stderr_truncated: bool,
        duration_ms: int,
        error_message: str | None = None,
    ) -> ExecutionJob:
        """Record final execution outcome and timestamps."""
        job.transition_to(status)
        job.completed_at = utc_now()
        job.exit_code = exit_code
        job.stdout = stdout
        job.stderr = stderr
        job.stdout_truncated = stdout_truncated
        job.stderr_truncated = stderr_truncated
        job.duration_ms = duration_ms
        job.error_message = error_message
        self.db.commit()
        self.db.refresh(job)
        return job

    def get_by_id(self, job_id: uuid.UUID) -> ExecutionJob | None:
        """Retrieve execution job by primary key."""
        stmt = select(ExecutionJob).where(ExecutionJob.id == job_id)
        return self.db.scalars(stmt).first()

    def list_by_sandbox(self, sandbox_id: uuid.UUID) -> list[ExecutionJob]:
        """List all execution records for a specific sandbox session."""
        stmt = (
            select(ExecutionJob)
            .where(ExecutionJob.sandbox_id == sandbox_id)
            .order_by(ExecutionJob.submitted_at.desc())
        )
        return list(self.db.scalars(stmt).all())
