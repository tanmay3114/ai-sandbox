"""ExecutionJob persistent model for tracking individual code execution tasks."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.sandbox import InvalidStateTransitionError, utc_now


class JobStatus(StrEnum):
    """Lifecycle states for an individual code execution job."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


VALID_JOB_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.FAILED},
    JobStatus.RUNNING: {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.TIMED_OUT},
    JobStatus.COMPLETED: set(),
    JobStatus.FAILED: set(),
    JobStatus.TIMED_OUT: set(),
}


class ExecutionJob(Base):
    """Persistent entity recording an execution invocation within a sandbox session."""

    __tablename__ = "execution_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    sandbox_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("sandboxes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[JobStatus] = mapped_column(
        String(32),
        nullable=False,
        default=JobStatus.QUEUED,
        index=True,
    )
    code: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    timeout_seconds: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    exit_code: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        default=None,
    )
    stdout: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    stderr: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    stdout_truncated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    stderr_truncated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    duration_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        default=None,
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
    )

    # Relationships
    sandbox: Mapped["Sandbox"] = relationship(  # noqa: F821
        "Sandbox",
        back_populates="executions",
    )

    def can_transition_to(self, target: JobStatus) -> bool:
        """Determine whether a job lifecycle transition is legal."""
        if self.status == target:
            return True
        return target in VALID_JOB_TRANSITIONS.get(self.status, set())

    def transition_to(self, target: JobStatus) -> None:
        """Apply a validated job lifecycle transition."""
        if not self.can_transition_to(target):
            raise InvalidStateTransitionError(
                f"Cannot transition execution job {self.id} from '{self.status}' to '{target}'",
                details={"current_status": str(self.status), "requested_status": str(target)},
            )
        self.status = target
