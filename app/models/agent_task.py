"""AgentTask persistent model for tracking autonomous agent orchestration tasks."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base
from app.models.sandbox import InvalidStateTransitionError, utc_now


class TaskStatus(StrEnum):
    """Lifecycle states for an autonomous agent orchestration task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


VALID_TASK_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.FAILED},
    TaskStatus.RUNNING: {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.TIMED_OUT,
        TaskStatus.CANCELLED,
    },
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.TIMED_OUT: set(),
    TaskStatus.CANCELLED: set(),
}


class AgentTask(Base):
    """Persistent entity recording an agent orchestration task within a sandbox."""

    __tablename__ = "agent_tasks"

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
    task_description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    status: Mapped[TaskStatus] = mapped_column(
        String(32),
        nullable=False,
        default=TaskStatus.PENDING,
        index=True,
    )
    iterations: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    tool_calls_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    result_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
    )
    error_type: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        default=None,
    )
    tool_history: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
    )
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        index=True,
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    worker_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        default=None,
    )
    interruption_reason: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
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

    # Relationships
    sandbox: Mapped[Sandbox] = relationship(  # noqa: F821
        "Sandbox",
        back_populates="agent_tasks",
    )

    def can_transition_to(self, target: TaskStatus) -> bool:
        """Determine whether a task lifecycle transition is legal."""
        if self.status == target:
            return True
        return target in VALID_TASK_TRANSITIONS.get(self.status, set())

    def transition_to(self, target: TaskStatus) -> None:
        """Apply a validated task lifecycle transition."""
        if not self.can_transition_to(target):
            raise InvalidStateTransitionError(
                f"Cannot transition agent task {self.id} from '{self.status}' to '{target}'",
                details={"current_status": str(self.status), "requested_status": str(target)},
            )
        self.status = target
