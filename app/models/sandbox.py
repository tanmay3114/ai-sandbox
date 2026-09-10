"""Sandbox persistent model and lifecycle state machine."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.exceptions import SandboxPlatformError
from app.db.base import Base


class InvalidStateTransitionError(SandboxPlatformError):
    """Raised when an illegal lifecycle state transition is requested."""
    pass


class SandboxStatus(StrEnum):
    """Explicit lifecycle states for a sandbox session."""

    CREATING = "creating"
    RUNNING = "running"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    EXPIRED = "expired"
    DESTROYING = "destroying"
    DESTROYED = "destroyed"


# Explicit valid state transition matrix
VALID_SANDBOX_TRANSITIONS: dict[SandboxStatus, set[SandboxStatus]] = {
    SandboxStatus.CREATING: {
        SandboxStatus.RUNNING,
        SandboxStatus.FAILED,
        SandboxStatus.EXPIRED,
        SandboxStatus.DESTROYING,
        SandboxStatus.DESTROYED,
    },
    SandboxStatus.RUNNING: {
        SandboxStatus.EXECUTING,
        SandboxStatus.EXPIRED,
        SandboxStatus.DESTROYING,
        SandboxStatus.DESTROYED,
    },
    SandboxStatus.EXECUTING: {
        SandboxStatus.RUNNING,
        SandboxStatus.COMPLETED,
        SandboxStatus.FAILED,
        SandboxStatus.TIMED_OUT,
        SandboxStatus.EXPIRED,
        SandboxStatus.DESTROYING,
        SandboxStatus.DESTROYED,
    },
    SandboxStatus.COMPLETED: {
        SandboxStatus.RUNNING,
        SandboxStatus.EXECUTING,
        SandboxStatus.EXPIRED,
        SandboxStatus.DESTROYING,
        SandboxStatus.DESTROYED,
    },
    SandboxStatus.FAILED: {
        SandboxStatus.RUNNING,
        SandboxStatus.EXECUTING,
        SandboxStatus.EXPIRED,
        SandboxStatus.DESTROYING,
        SandboxStatus.DESTROYED,
    },
    SandboxStatus.TIMED_OUT: {
        SandboxStatus.RUNNING,
        SandboxStatus.EXECUTING,
        SandboxStatus.EXPIRED,
        SandboxStatus.DESTROYING,
        SandboxStatus.DESTROYED,
    },
    SandboxStatus.DESTROYING: {
        SandboxStatus.DESTROYED,
    },
    SandboxStatus.EXPIRED: {
        SandboxStatus.DESTROYING,
        SandboxStatus.DESTROYED,
    },
    SandboxStatus.DESTROYED: set(),  # Terminal state: no outgoing transitions
}


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(UTC)


class Sandbox(Base):
    """Persistent database entity representing an isolated execution environment."""

    __tablename__ = "sandboxes"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    status: Mapped[SandboxStatus] = mapped_column(
        String(32),
        nullable=False,
        default=SandboxStatus.CREATING,
        index=True,
    )
    runtime: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="python",
    )
    ttl_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    destroyed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    container_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        default=None,
    )
    resource_config: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    # Relationships
    executions: Mapped[list["ExecutionJob"]] = relationship(  # noqa: F821
        "ExecutionJob",
        back_populates="sandbox",
        cascade="all, delete-orphan",
        order_by="ExecutionJob.submitted_at.desc()",
    )

    @property
    def is_expired(self) -> bool:
        """Check if sandbox TTL expiration timestamp has passed."""
        return utc_now() >= self.expires_at

    @property
    def is_active(self) -> bool:
        """Check if sandbox is in an active non-terminal state."""
        return self.status not in (
            SandboxStatus.EXPIRED,
            SandboxStatus.DESTROYING,
            SandboxStatus.DESTROYED,
        )

    def can_transition_to(self, target: SandboxStatus) -> bool:
        """Determine if transitioning to target state is legally allowed."""
        if self.status == target:
            return True  # Idempotent re-affirmation
        allowed = VALID_SANDBOX_TRANSITIONS.get(self.status, set())
        return target in allowed

    def transition_to(self, target: SandboxStatus) -> None:
        """Enforce strict state machine transitions."""
        if not self.can_transition_to(target):
            raise InvalidStateTransitionError(
                f"Cannot transition sandbox {self.id} from '{self.status}' to '{target}'",
                details={"current_status": str(self.status), "requested_status": str(target)},
            )
        self.status = target
        if target == SandboxStatus.DESTROYED and self.destroyed_at is None:
            self.destroyed_at = utc_now()
