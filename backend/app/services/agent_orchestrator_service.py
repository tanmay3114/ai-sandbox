"""Agent Orchestration Service coordinating task lifecycle, DB persistence, and cancellation."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import ClassVar

from sqlalchemy.orm import Session

from app.agent.llm.base import LLMProvider
from app.agent.orchestrator import AgentOrchestrator, AgentTaskResult
from app.core.config import SandboxSettings, settings
from app.core.exceptions import (
    AgentCancelledError,
    AgentMaxIterationsError,
    AgentMaxToolCallsError,
    AgentTaskNotFoundError,
    AgentTimeoutError,
    ConcurrencyLimitError,
    LLMProviderError,
    SandboxNotFoundError,
    SandboxPlatformError,
)
from app.models.agent_task import AgentTask, TaskStatus
from app.models.sandbox import SandboxStatus
from app.repositories.agent_task_repository import AgentTaskRepository
from app.schemas.sandbox import JobExecutionResponse
from app.services.sandbox_lifecycle_service import SandboxLifecycleService

logger = logging.getLogger(__name__)


class AgentOrchestratorService:
    """Coordinates persistent AgentTask execution, monitoring, and cancellation."""

    # In-memory tracking shared across service instances in this process
    _cancellation_tokens: ClassVar[dict[uuid.UUID, asyncio.Event]] = {}
    _active_tasks: ClassVar[set[uuid.UUID]] = set()
    _shutting_down: ClassVar[bool] = False

    def __init__(
        self,
        db: Session,
        service: SandboxLifecycleService,
        llm_provider: LLMProvider | None = None,
        config: SandboxSettings = settings,
    ) -> None:
        self.db = db
        self.service = service
        self.llm = llm_provider
        self.config = config
        self.task_repo = AgentTaskRepository(db)
        self.orchestrator = (
            AgentOrchestrator(
                llm=llm_provider,
                service=service,
                config=config,
            )
            if llm_provider is not None
            else None
        )

    def get_task(self, sandbox_id: uuid.UUID, task_id: uuid.UUID) -> AgentTask:
        """Retrieve task by ID and verify sandbox association."""
        task = self.task_repo.get_by_id(task_id)
        if not task or task.sandbox_id != sandbox_id:
            raise AgentTaskNotFoundError(
                f"Agent task '{task_id}' not found for sandbox '{sandbox_id}'.",
                details={"task_id": str(task_id), "sandbox_id": str(sandbox_id)},
            )
        return task

    def list_tasks(
        self,
        sandbox_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentTask]:
        """List all tasks associated with a sandbox."""
        self.service.get_sandbox(sandbox_id)
        return self.task_repo.list_by_sandbox(sandbox_id=sandbox_id, limit=limit, offset=offset)

    def get_task_executions(
        self,
        sandbox_id: uuid.UUID,
        task_id: uuid.UUID,
    ) -> list[JobExecutionResponse]:
        """Retrieve all code execution jobs triggered during an agent task."""
        task = self.get_task(sandbox_id, task_id)
        execution_ids: list[uuid.UUID] = []

        for item in task.tool_history:
            if isinstance(item, dict) and item.get("execution_id"):
                try:
                    eid = uuid.UUID(item["execution_id"])
                    if eid not in execution_ids:
                        execution_ids.append(eid)
                except (ValueError, TypeError):
                    pass

        results: list[JobExecutionResponse] = []
        for eid in execution_ids:
            try:
                exec_job = self.service.get_execution(sandbox_id=sandbox_id, execution_id=eid)
                results.append(exec_job)
            except Exception:
                pass

        return results

    async def cancel_task(self, sandbox_id: uuid.UUID, task_id: uuid.UUID) -> AgentTask:
        """Cancel an in-flight or pending agent task durably."""
        task = self.get_task(sandbox_id, task_id)

        # Idempotent terminal check: never overwrite terminal state
        if task.status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.TIMED_OUT,
            TaskStatus.CANCELLED,
        ):
            return task

        # Atomically record cancellation intent in PostgreSQL before proceeding
        updated = self.task_repo.record_cancellation_intent(task_id)
        if updated:
            task = updated

        # Signal in-memory cancellation token if active in this process
        token = self._cancellation_tokens.get(task_id)
        if token:
            token.set()

        # If task has not started running yet (PENDING), transition to CANCELLED immediately
        if task.status == TaskStatus.PENDING:
            cancelled_task = self.task_repo.mark_cancelled(
                task=task,
                iterations=0,
                tool_calls_count=0,
                tool_history=[],
            )
            logger.info("Pending agent task %s cancelled successfully.", task_id)
            return cancelled_task

        # If task is RUNNING, allow brief bounded wait for active loop to stop safely
        if task_id in self._active_tasks:
            for _ in range(15):
                await asyncio.sleep(0.1)
                self.db.refresh(task)
                if task.status == TaskStatus.CANCELLED:
                    break

        self.db.refresh(task)
        logger.info(
            "Agent task %s cancellation processed; current status is '%s'.",
            task_id,
            task.status,
        )
        return task

    async def create_and_run_task(
        self,
        sandbox_id: uuid.UUID,
        prompt: str,
        timeout_seconds: float | None = None,
        task_id: uuid.UUID | None = None,
        worker_id: str | None = None,
    ) -> AgentTask:
        """Create persistent task, atomically claim it, execute, and record outcome."""
        if self._shutting_down:
            raise SandboxPlatformError("Service is shutting down; not accepting new agent tasks.")

        if self.orchestrator is None:
            raise LLMProviderError("Cannot execute agent task: LLM provider is not configured.")

        # 1. Verify sandbox exists and is active
        self.service.get_sandbox(sandbox_id)

        # 2. Persist task in PENDING state
        task = self.task_repo.create(
            sandbox_id=sandbox_id,
            task_description=prompt,
            task_id=task_id,
        )
        actual_task_id = task.id

        # 3. Atomically claim task for execution
        effective_worker = worker_id or f"worker_{uuid.uuid4().hex[:8]}"
        claimed = self.task_repo.claim_task(task_id=actual_task_id, worker_id=effective_worker)
        if not claimed:
            self.db.refresh(task)
            if task.status == TaskStatus.CANCELLED:
                return task
            raise ConcurrencyLimitError(
                f"Agent task '{actual_task_id}' could not be claimed; "
                f"current status is '{task.status}'."
            )
        task = claimed

        # 4. Set up cancellation token and active task tracking
        cancel_token = asyncio.Event()
        self._cancellation_tokens[actual_task_id] = cancel_token
        self._active_tasks.add(actual_task_id)

        def is_cancelled_in_db() -> bool:
            return self.task_repo.is_cancellation_requested(actual_task_id)

        # 5. Execute orchestration loop
        try:
            result: AgentTaskResult = await self.orchestrator.run_task(
                task_id=actual_task_id,
                sandbox_id=sandbox_id,
                prompt=prompt,
                timeout_seconds=timeout_seconds,
                cancellation_token=cancel_token,
                is_cancelled_func=is_cancelled_in_db,
            )

            # Persist completed task outcome
            return self.task_repo.mark_completed(
                task=task,
                result_summary=result.final_response,
                iterations=result.iterations,
                tool_calls_count=result.tool_calls_count,
                tool_history=result.tool_history,
            )

        except AgentCancelledError:
            logger.info("Agent task %s execution stopped due to cancellation.", actual_task_id)
            return self.task_repo.mark_cancelled(
                task=task,
                iterations=getattr(self.orchestrator, "last_iterations", task.iterations),
                tool_calls_count=getattr(
                    self.orchestrator, "last_tool_calls", task.tool_calls_count
                ),
                tool_history=task.tool_history,
            )
        except AgentTimeoutError as err:
            logger.warning("Agent task %s execution timed out: %s", actual_task_id, err)
            self.task_repo.mark_timed_out(
                task=task,
                error_message=err.message,
                iterations=err.details.get("iterations", task.iterations),
                tool_calls_count=err.details.get("tool_calls_count", task.tool_calls_count),
                tool_history=task.tool_history,
            )
            raise
        except (
            AgentMaxIterationsError,
            AgentMaxToolCallsError,
            LLMProviderError,
            SandboxPlatformError,
        ) as err:
            logger.warning("Agent task %s failed with domain error: %s", actual_task_id, err)
            self.task_repo.mark_failed(
                task=task,
                error_message=err.message,
                error_type=err.__class__.__name__,
                iterations=err.details.get("max_iterations", task.iterations)
                if hasattr(err, "details")
                else task.iterations,
                tool_calls_count=err.details.get("tool_calls_count", task.tool_calls_count)
                if hasattr(err, "details")
                else task.tool_calls_count,
                tool_history=task.tool_history,
            )
            raise
        except Exception as exc:
            logger.exception("Agent task %s unexpected failure: %s", actual_task_id, exc)
            self.task_repo.mark_failed(
                task=task,
                error_message="An unexpected server error occurred during agent orchestration.",
                error_type="InternalServerError",
                iterations=task.iterations,
                tool_calls_count=task.tool_calls_count,
                tool_history=task.tool_history,
            )
            raise
        finally:
            self._cancellation_tokens.pop(actual_task_id, None)
            self._active_tasks.discard(actual_task_id)

    def reconcile_interrupted_tasks(self) -> dict[str, int]:
        """Reconcile nonterminal agent tasks after backend process restart or crash."""
        nonterminal = self.task_repo.get_nonterminal_tasks()
        reconciled = 0
        cancelled = 0
        failed = 0

        for task in nonterminal:
            try:
                sandbox_id = task.sandbox_id
                try:
                    sandbox = self.service.get_sandbox(sandbox_id)
                    is_sandbox_dead = (
                        sandbox.status in (SandboxStatus.DESTROYED, SandboxStatus.DESTROYING)
                        or sandbox.is_expired
                        or sandbox.status == SandboxStatus.EXPIRED
                    )
                except SandboxNotFoundError:
                    sandbox = None
                    is_sandbox_dead = True

                # Safely clean any residual execution containers for this sandbox
                if hasattr(self.service.backend, "cleanup_execution_containers"):
                    try:
                        self.service.backend.cleanup_execution_containers(str(sandbox_id))
                    except Exception as exc:
                        logger.warning(
                            "Container cleanup failed during task recovery for sandbox %s: %s",
                            sandbox_id,
                            exc,
                        )

                # Reconcile based on task state and cancellation intent
                if task.cancellation_requested_at is not None:
                    # Task had durable cancellation intent
                    self.task_repo.mark_cancelled(
                        task=task,
                        iterations=task.iterations,
                        tool_calls_count=task.tool_calls_count,
                        tool_history=task.tool_history,
                    )
                    cancelled += 1
                    reconciled += 1
                elif is_sandbox_dead:
                    reason = (
                        "SANDBOX_DESTROYED"
                        if sandbox and "destroy" in str(sandbox.status)
                        else "SANDBOX_EXPIRED"
                    )
                    self.task_repo.mark_interrupted(
                        task=task,
                        reason=reason,
                        error_message=(
                            f"Agent task interrupted because sandbox was {reason.lower()}."
                        ),
                    )
                    failed += 1
                    reconciled += 1
                elif task.status == TaskStatus.RUNNING:
                    self.task_repo.mark_interrupted(
                        task=task,
                        reason="PROCESS_RESTARTED",
                        error_message=(
                            "Agent task execution was interrupted by "
                            "backend process restart or crash."
                        ),
                    )
                    failed += 1
                    reconciled += 1
                elif task.status == TaskStatus.PENDING:
                    self.task_repo.mark_interrupted(
                        task=task,
                        reason="PROCESS_RESTARTED_BEFORE_START",
                        error_message=(
                            "Pending agent task was interrupted by backend process restart "
                            "before execution began."
                        ),
                    )
                    failed += 1
                    reconciled += 1
            except Exception as exc:
                logger.exception("Failed to reconcile agent task %s: %s", task.id, exc)

        report = {
            "attempted": len(nonterminal),
            "reconciled": reconciled,
            "cancelled": cancelled,
            "failed": failed,
        }
        logger.info(
            "Agent tasks reconciliation completed: "
            "attempted=%d, reconciled=%d, cancelled=%d, failed=%d",
            report["attempted"],
            report["reconciled"],
            report["cancelled"],
            report["failed"],
        )
        return report

    @classmethod
    async def graceful_shutdown(cls, db: Session, timeout_seconds: float = 3.0) -> None:
        """Signal active orchestrator loops to cancel and await bounded shutdown."""
        cls._shutting_down = True
        try:
            repo = AgentTaskRepository(db)

            for task_id, token in list(cls._cancellation_tokens.items()):
                try:
                    repo.record_cancellation_intent(task_id)
                except Exception:
                    pass
                token.set()

            if cls._active_tasks:
                deadline = asyncio.get_event_loop().time() + timeout_seconds
                while cls._active_tasks and asyncio.get_event_loop().time() < deadline:
                    await asyncio.sleep(0.1)
        finally:
            cls._shutting_down = False
