"""Lifecycle orchestration service managing sandboxes and persistent execution history."""

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import SandboxSettings, settings
from app.core.exceptions import (
    ExecutionNotFoundError,
    SandboxDestroyedError,
    SandboxExpiredError,
    SandboxNotFoundError,
)
from app.models.execution_job import JobStatus
from app.models.sandbox import InvalidStateTransitionError, Sandbox, SandboxStatus, utc_now
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.sandbox_repository import SandboxRepository
from app.sandbox.docker_client import (
    cleanup_container_safely,
    get_docker_client,
    list_sandbox_containers,
)
from app.sandbox.engine import EphemeralSandboxEngine
from app.schemas.sandbox import JobExecutionResponse

logger = logging.getLogger(__name__)


class SandboxLifecycleService:
    """Coordinates sandbox sessions, state transitions, TTL expiration, and executions."""

    def __init__(
        self,
        db: Session,
        config: SandboxSettings = settings,
        engine: EphemeralSandboxEngine | None = None,
    ) -> None:
        self.db = db
        self.config = config
        self.sandbox_repo = SandboxRepository(db)
        self.execution_repo = ExecutionRepository(db)
        self.engine = engine or EphemeralSandboxEngine(config=self.config)

    def create_sandbox(
        self,
        runtime: str = "python",
        ttl_seconds: int | None = None,
    ) -> Sandbox:
        """Instantiate a new persistent Sandbox session."""
        effective_ttl = ttl_seconds or self.config.DEFAULT_SANDBOX_TTL_SECONDS
        resource_config: dict[str, Any] = {
            "memory_limit": self.config.MEMORY_LIMIT,
            "cpu_limit": self.config.CPU_LIMIT,
            "pids_limit": self.config.PIDS_LIMIT,
            "max_stdout_bytes": self.config.MAX_STDOUT_BYTES,
            "max_stderr_bytes": self.config.MAX_STDERR_BYTES,
        }
        sandbox = self.sandbox_repo.create(
            runtime=runtime,
            ttl_seconds=effective_ttl,
            resource_config=resource_config,
        )
        logger.info(f"Sandbox created: id={sandbox.id}, status={sandbox.status}")
        return sandbox

    def get_sandbox(self, sandbox_id: uuid.UUID) -> Sandbox:
        """Retrieve a Sandbox by ID, automatically reconciling expiration if detected."""
        sandbox = self.sandbox_repo.get_by_id(sandbox_id)
        if not sandbox:
            raise SandboxNotFoundError(f"Sandbox {sandbox_id} not found")

        # Reconcile TTL expiration if detected upon retrieval. Expiration is a
        # distinct terminal lifecycle state; it is not an execution timeout.
        if sandbox.is_expired and sandbox.is_active:
            logger.info(f"Sandbox {sandbox_id} expired on access; executing cleanup.")
            self.expire_sandbox(sandbox)
            self.db.refresh(sandbox)

        return sandbox

    def get_execution(
        self,
        sandbox_id: uuid.UUID,
        execution_id: uuid.UUID,
    ) -> JobExecutionResponse:
        """Retrieve a persistent execution job record within a sandbox session."""
        sandbox = self.get_sandbox(sandbox_id)
        job = self.execution_repo.get_by_id(execution_id)
        if not job or job.sandbox_id != sandbox.id:
            raise ExecutionNotFoundError(
                f"Execution job {execution_id} not found for sandbox {sandbox_id}"
            )

        return JobExecutionResponse(
            execution_id=job.id,
            sandbox_id=job.sandbox_id,
            status=str(job.status),
            exit_code=job.exit_code,
            stdout=job.stdout,
            stderr=job.stderr,
            stdout_truncated=job.stdout_truncated,
            stderr_truncated=job.stderr_truncated,
            duration_ms=job.duration_ms,
            submitted_at=job.submitted_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            error_message=job.error_message,
        )

    def delete_sandbox(self, sandbox_id: uuid.UUID) -> Sandbox:
        """Idempotently terminate and destroy a sandbox session."""
        sandbox = self.sandbox_repo.get_by_id(sandbox_id)
        if not sandbox:
            raise SandboxNotFoundError(f"Sandbox {sandbox_id} not found")

        if sandbox.status == SandboxStatus.DESTROYED:
            return sandbox  # Idempotent: already destroyed

        logger.info(f"Destroying sandbox: id={sandbox_id}")
        # Transition state machine
        if sandbox.can_transition_to(SandboxStatus.DESTROYING):
            sandbox = self.sandbox_repo.update_status(sandbox, SandboxStatus.DESTROYING)

        self._cleanup_sandbox_containers(sandbox_id)

        sandbox = self.sandbox_repo.update_status(sandbox, SandboxStatus.DESTROYED)
        logger.info(f"Sandbox destroyed: id={sandbox_id}")
        return sandbox

    def expire_sandbox(self, sandbox: Sandbox) -> Sandbox:
        """Mark a TTL-expired sandbox unusable and clean any project containers."""
        if sandbox.status in (SandboxStatus.EXPIRED, SandboxStatus.DESTROYED):
            return sandbox
        sandbox = self.sandbox_repo.update_status(sandbox, SandboxStatus.EXPIRED)
        self._cleanup_sandbox_containers(sandbox.id)
        logger.info(f"Sandbox expired: id={sandbox.id}")
        return sandbox

    def _cleanup_sandbox_containers(self, sandbox_id: uuid.UUID) -> None:
        """Remove only project-owned containers associated with this sandbox."""
        try:
            client = get_docker_client()
            for container in list_sandbox_containers(client, config=self.config, all_states=True):
                labels = container.attrs.get("Config", {}).get("Labels", {})
                if labels.get("sandbox_id") == str(sandbox_id):
                    cleanup_container_safely(container, sandbox_id=str(sandbox_id))
        except Exception as exc:
            logger.warning(f"Error during Docker cleanup for sandbox {sandbox_id}: {exc}")

    async def execute_code(
        self,
        sandbox_id: uuid.UUID,
        code: str,
        timeout_seconds: float | None = None,
    ) -> JobExecutionResponse:
        """Execute code within a sandbox session and persist full execution history."""
        sandbox = self.sandbox_repo.get_by_id(sandbox_id)
        if not sandbox:
            raise SandboxNotFoundError(f"Sandbox {sandbox_id} not found")

        if sandbox.status in (SandboxStatus.DESTROYED, SandboxStatus.DESTROYING):
            raise SandboxDestroyedError(
                f"Cannot execute code in destroyed sandbox {sandbox_id}",
                details={"status": str(sandbox.status)},
            )

        if sandbox.status == SandboxStatus.EXPIRED or sandbox.is_expired:
            if sandbox.is_active:
                self.expire_sandbox(sandbox)
            raise SandboxExpiredError(
                f"Sandbox {sandbox_id} has expired (TTL={sandbox.ttl_seconds}s)",
                details={"expires_at": sandbox.expires_at.isoformat()},
            )

        effective_timeout = (
            min(timeout_seconds, self.config.TIMEOUT_SECONDS)
            if timeout_seconds is not None
            else self.config.TIMEOUT_SECONDS
        )

        # Enforce one execution per logical sandbox with an atomic database claim.
        sandbox = self.sandbox_repo.claim_for_execution(sandbox_id)
        if sandbox is None:
            current = self.sandbox_repo.get_by_id(sandbox_id)
            if current is None:
                raise SandboxNotFoundError(f"Sandbox {sandbox_id} not found")
            if current.status == SandboxStatus.EXPIRED or current.is_expired:
                if current.is_active:
                    self.expire_sandbox(current)
                raise SandboxExpiredError(f"Sandbox {sandbox_id} has expired")
            if current.status in (SandboxStatus.DESTROYED, SandboxStatus.DESTROYING):
                raise SandboxDestroyedError(
                    f"Cannot execute code in destroyed sandbox {sandbox_id}"
                )
            raise InvalidStateTransitionError(
                f"Sandbox {sandbox_id} is not available for execution",
                details={"current_status": str(current.status)},
            )

        # Create persistent job in QUEUED state
        job = self.execution_repo.create(
            sandbox_id=sandbox_id,
            code=code,
            timeout_seconds=effective_timeout,
        )

        try:
            # Mark started
            self.execution_repo.mark_started(job)

            # Offload blocking Docker execution to threadpool
            result = await run_in_threadpool(
                self.engine.execute,
                code,
                effective_timeout,
                str(sandbox_id),
            )

            # Map ExecutionResult status to JobStatus
            job_status = JobStatus.COMPLETED
            if result.status == "timed_out":
                job_status = JobStatus.TIMED_OUT
            elif result.status in ("failed", "error"):
                job_status = JobStatus.FAILED

            # Persist job outcome
            self.execution_repo.mark_completed(
                job=job,
                status=job_status,
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
                stdout_truncated=result.stdout_truncated,
                stderr_truncated=result.stderr_truncated,
                duration_ms=result.duration_ms,
                error_message=result.error_message,
            )

            return JobExecutionResponse(
                execution_id=job.id,
                sandbox_id=sandbox_id,
                status=job_status.value,
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
                stdout_truncated=result.stdout_truncated,
                stderr_truncated=result.stderr_truncated,
                duration_ms=result.duration_ms,
                submitted_at=job.submitted_at,
                started_at=job.started_at,
                completed_at=job.completed_at,
                error_message=result.error_message,
            )

        except Exception:
            # A failed engine call must not strand a persisted job in RUNNING.
            if job.status == JobStatus.RUNNING:
                self.execution_repo.mark_completed(
                    job=job,
                    status=JobStatus.FAILED,
                    exit_code=None,
                    stdout="",
                    stderr="",
                    stdout_truncated=False,
                    stderr_truncated=False,
                    duration_ms=0,
                    error_message="Execution infrastructure failure",
                )
            raise

        finally:
            # Revert the active session to RUNNING only when it remains usable.
            if sandbox.status == SandboxStatus.EXECUTING:
                self.sandbox_repo.update_status(sandbox, SandboxStatus.RUNNING)

    def cleanup_expired_sandboxes(self, limit: int = 50) -> int:
        """Scan PostgreSQL for expired active sandboxes and destroy them idempotently."""
        expired = self.sandbox_repo.get_expired_active(limit=limit)
        cleaned = 0
        for s in expired:
            try:
                self.expire_sandbox(s)
                cleaned += 1
            except Exception as exc:
                logger.error(f"Failed to clean expired sandbox {s.id}: {exc}")
        if cleaned > 0:
            logger.info(f"TTL Cleanup: successfully destroyed {cleaned} expired sandboxes.")
        return cleaned

    def reconcile_stale_sandboxes(self) -> int:
        """Reconcile TTL expiry and interrupted executions after an application restart."""
        cutoff = utc_now()
        expired = self.sandbox_repo.get_expired_active(cutoff)
        reconciled = 0
        for s in expired:
            self.expire_sandbox(s)
            reconciled += 1
        for sandbox in self.sandbox_repo.get_stale_active(cutoff):
            if sandbox.status == SandboxStatus.DESTROYING:
                self.delete_sandbox(sandbox.id)
            elif sandbox.status == SandboxStatus.EXECUTING:
                self._cleanup_sandbox_containers(sandbox.id)
                sandbox.transition_to(SandboxStatus.RUNNING)
                self.db.commit()
            reconciled += 1
        return reconciled
