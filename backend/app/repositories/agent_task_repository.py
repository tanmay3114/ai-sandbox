"""Repository for AgentTask database persistence."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.agent_task import AgentTask, TaskStatus
from app.models.sandbox import utc_now


class AgentTaskRepository:
    """Encapsulates PostgreSQL database operations for AgentTask entities."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        sandbox_id: uuid.UUID,
        task_description: str,
        task_id: uuid.UUID | None = None,
    ) -> AgentTask:
        """Create and persist a new agent task record in PENDING state."""
        task = AgentTask(
            id=task_id or uuid.uuid4(),
            sandbox_id=sandbox_id,
            status=TaskStatus.PENDING,
            task_description=task_description,
            iterations=0,
            tool_calls_count=0,
            tool_history=[],
            created_at=utc_now(),
        )
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def claim_task(
        self,
        task_id: uuid.UUID,
        worker_id: str,
    ) -> AgentTask | None:
        """Atomically claim a PENDING task for execution, transitioning it to RUNNING.

        Returns the updated task if claim was successful, or None if the task is already
        claimed, running, or in a terminal state.
        """
        now = utc_now()
        stmt = (
            update(AgentTask)
            .where(
                AgentTask.id == task_id,
                AgentTask.status == TaskStatus.PENDING,
            )
            .values(
                status=TaskStatus.RUNNING,
                started_at=now,
                claimed_at=now,
                worker_id=worker_id,
            )
            .returning(AgentTask)
        )
        res = self.db.scalars(stmt).first()
        if res:
            self.db.commit()
            self.db.refresh(res)
        return res

    def record_cancellation_intent(
        self,
        task_id: uuid.UUID,
    ) -> AgentTask | None:
        """Atomically persist cancellation intent for a nonterminal task in PostgreSQL.

        Returns the updated task, or None if task is already in a terminal state or missing.
        """
        now = utc_now()
        stmt = (
            update(AgentTask)
            .where(
                AgentTask.id == task_id,
                AgentTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]),
            )
            .values(cancellation_requested_at=now)
            .returning(AgentTask)
        )
        res = self.db.scalars(stmt).first()
        if res:
            self.db.commit()
            self.db.refresh(res)
        return res

    def is_cancellation_requested(self, task_id: uuid.UUID) -> bool:
        """Check whether cancellation intent has been persisted for a task."""
        stmt = select(AgentTask.cancellation_requested_at).where(AgentTask.id == task_id)
        val = self.db.scalar(stmt)
        return val is not None

    def mark_started(
        self,
        task: AgentTask,
        worker_id: str | None = None,
    ) -> AgentTask:
        """Transition task to RUNNING state with start and claim timestamps."""
        now = utc_now()
        task.transition_to(TaskStatus.RUNNING)
        task.started_at = now
        task.claimed_at = now
        if worker_id:
            task.worker_id = worker_id
        self.db.commit()
        self.db.refresh(task)
        return task

    def mark_completed(
        self,
        task: AgentTask,
        result_summary: str,
        iterations: int,
        tool_calls_count: int,
        tool_history: list[dict[str, Any]],
    ) -> AgentTask:
        """Record final successful outcome and completion timestamp."""
        task.transition_to(TaskStatus.COMPLETED)
        task.result_summary = result_summary
        task.iterations = iterations
        task.tool_calls_count = tool_calls_count
        task.tool_history = tool_history
        task.completed_at = utc_now()
        self.db.commit()
        self.db.refresh(task)
        return task

    def mark_failed(
        self,
        task: AgentTask,
        error_message: str,
        error_type: str | None,
        iterations: int,
        tool_calls_count: int,
        tool_history: list[dict[str, Any]],
    ) -> AgentTask:
        """Record task failure details and completion timestamp."""
        task.transition_to(TaskStatus.FAILED)
        task.error_message = error_message
        task.error_type = error_type
        task.iterations = iterations
        task.tool_calls_count = tool_calls_count
        task.tool_history = tool_history
        task.completed_at = utc_now()
        self.db.commit()
        self.db.refresh(task)
        return task

    def mark_interrupted(
        self,
        task: AgentTask,
        reason: str,
        error_message: str,
    ) -> AgentTask:
        """Record task interruption due to backend process restart or shutdown."""
        task.transition_to(TaskStatus.FAILED)
        task.interruption_reason = reason
        task.error_message = error_message
        task.error_type = "ProcessInterruptedError"
        task.completed_at = utc_now()
        self.db.commit()
        self.db.refresh(task)
        return task

    def mark_timed_out(
        self,
        task: AgentTask,
        error_message: str,
        iterations: int,
        tool_calls_count: int,
        tool_history: list[dict[str, Any]],
    ) -> AgentTask:
        """Record task timeout and completion timestamp."""
        task.transition_to(TaskStatus.TIMED_OUT)
        task.error_message = error_message
        task.error_type = "AgentTimeoutError"
        task.iterations = iterations
        task.tool_calls_count = tool_calls_count
        task.tool_history = tool_history
        task.completed_at = utc_now()
        self.db.commit()
        self.db.refresh(task)
        return task

    def mark_cancelled(
        self,
        task: AgentTask,
        iterations: int,
        tool_calls_count: int,
        tool_history: list[dict[str, Any]],
    ) -> AgentTask:
        """Record task explicit cancellation and completion timestamp."""
        now = utc_now()
        task.transition_to(TaskStatus.CANCELLED)
        if not task.cancellation_requested_at:
            task.cancellation_requested_at = now
        task.error_message = "Task was explicitly cancelled by user or operator."
        task.error_type = "AgentCancelledError"
        task.iterations = iterations
        task.tool_calls_count = tool_calls_count
        task.tool_history = tool_history
        task.completed_at = now
        self.db.commit()
        self.db.refresh(task)
        return task

    def get_by_id(self, task_id: uuid.UUID) -> AgentTask | None:
        """Query agent task by its unique identifier."""
        stmt = select(AgentTask).where(AgentTask.id == task_id)
        return self.db.scalars(stmt).first()

    def get_nonterminal_tasks(self) -> list[AgentTask]:
        """Query all tasks currently in nonterminal (PENDING, RUNNING) states."""
        stmt = (
            select(AgentTask)
            .where(AgentTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]))
            .order_by(AgentTask.created_at.asc())
        )
        return list(self.db.scalars(stmt).all())

    def list_by_sandbox(
        self,
        sandbox_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentTask]:
        """Query all agent tasks for a given sandbox ordered by creation time descending."""
        stmt = (
            select(AgentTask)
            .where(AgentTask.sandbox_id == sandbox_id)
            .order_by(AgentTask.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.scalars(stmt).all())
