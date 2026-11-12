"""Lifecycle orchestration service managing sandboxes and persistent execution history."""

import logging
import threading
import uuid
from contextlib import nullcontext
from dataclasses import dataclass
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
from app.sandbox.backend import SandboxBackend
from app.sandbox.schemas import (
    ExecutionRequest,
    ExecutionResult,
    FileContent,
    FileInfo,
    FileListResponse,
)
from app.schemas.sandbox import JobExecutionResponse

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CleanupReport:
    """Structured outcome of a best-effort lifecycle cleanup batch."""

    attempted: int = 0
    succeeded: int = 0
    failed: int = 0


class SandboxLifecycleService:
    """Coordinates sandbox sessions, state transitions, TTL expiration, and executions."""

    def __init__(
        self,
        db: Session,
        backend: SandboxBackend,
        config: SandboxSettings = settings,
    ) -> None:
        """Create orchestration with an explicitly injected backend."""
        self.db = db
        self.config = config
        self.sandbox_repo = SandboxRepository(db)
        self.execution_repo = ExecutionRepository(db)
        self.backend = backend
        self._db_lock = threading.RLock()
        self.last_cleanup_report = CleanupReport()
        self.last_reconciliation_report = CleanupReport()

    def _get_workspace_manager(self) -> Any | None:
        """Return the backend's WorkspaceManager when available."""
        return getattr(self.backend, "workspace_manager", None)

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
        with self._db_lock:
            sandbox = self.sandbox_repo.create(
                runtime=runtime,
                ttl_seconds=effective_ttl,
                resource_config=resource_config,
            )
        logger.info(f"Sandbox created: id={sandbox.id}, status={sandbox.status}")
        return sandbox

    def get_sandbox(self, sandbox_id: uuid.UUID) -> Sandbox:
        """Retrieve a Sandbox by ID, automatically reconciling expiration if detected."""
        with self._db_lock:
            sandbox = self.sandbox_repo.get_by_id(sandbox_id)
            if not sandbox:
                raise SandboxNotFoundError(f"Sandbox {sandbox_id} not found")
            self.db.refresh(sandbox)
            should_expire = sandbox.is_expired and sandbox.is_active

        # Reconcile TTL expiration if detected upon retrieval. Expiration is a
        # distinct terminal lifecycle state; it is not an execution timeout.
        if should_expire:
            logger.info(f"Sandbox {sandbox_id} expired on access; executing cleanup.")
            self.expire_sandbox(sandbox)
            with self._db_lock:
                self.db.refresh(sandbox)

        return sandbox

    def get_execution(
        self,
        sandbox_id: uuid.UUID,
        execution_id: uuid.UUID,
    ) -> JobExecutionResponse:
        """Retrieve a persistent execution job record within a sandbox session."""
        sandbox = self.get_sandbox(sandbox_id)
        with self._db_lock:
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
        """Idempotently terminate and destroy a sandbox session and its persistent workspace."""
        with self._db_lock:
            sandbox = self.sandbox_repo.get_by_id(sandbox_id)
            if not sandbox:
                raise SandboxNotFoundError(f"Sandbox {sandbox_id} not found")
            self.db.refresh(sandbox)

            if sandbox.status == SandboxStatus.DESTROYED:
                return sandbox  # Idempotent: already destroyed

            logger.info(f"Destroying sandbox: id={sandbox_id}")
            if sandbox.status != SandboxStatus.DESTROYING and sandbox.can_transition_to(
                SandboxStatus.DESTROYING
            ):
                sandbox = self.sandbox_repo.update_status(sandbox, SandboxStatus.DESTROYING)

        # Coordinate with any running execution via the sandbox exclusive lock and clean up
        # all execution containers, anonymous volumes, and the persistent workspace outside
        # the DB lock/transaction. If cleanup raises, the sandbox remains DESTROYING.
        self.backend.cleanup_sandbox(str(sandbox_id))

        with self._db_lock:
            current = self.sandbox_repo.get_by_id(sandbox_id)
            if current is not None:
                self.db.refresh(current)
                sandbox = current
            if sandbox.status != SandboxStatus.DESTROYED:
                sandbox = self.sandbox_repo.update_status(sandbox, SandboxStatus.DESTROYED)
            logger.info(f"Sandbox destroyed: id={sandbox_id}")
            return sandbox

    def expire_sandbox(self, sandbox: Sandbox) -> Sandbox:
        """Mark a TTL-expired sandbox unusable and clean its containers and workspace."""
        with self._db_lock:
            self.db.refresh(sandbox)
            if sandbox.status == SandboxStatus.DESTROYED:
                return sandbox
            if sandbox.status == SandboxStatus.DESTROYING:
                is_destroying = True
            else:
                is_destroying = False
                if sandbox.status != SandboxStatus.EXPIRED:
                    sandbox = self.sandbox_repo.update_status(sandbox, SandboxStatus.EXPIRED)

        if is_destroying:
            return self.delete_sandbox(sandbox.id)

        # EXPIRED is retryable: a prior infrastructure failure must never make
        # future cleanup attempts skip this logical sandbox.
        self.backend.cleanup_sandbox(str(sandbox.id))
        logger.info(f"Sandbox expired: id={sandbox.id}")
        return sandbox

    def _execute_in_backend(
        self,
        sandbox_id: uuid.UUID,
        request: ExecutionRequest,
    ) -> ExecutionResult:
        """Synchronize execution with lifecycle termination under the sandbox exclusive lock."""
        workspace_mgr = self._get_workspace_manager()
        lock_ctx = (
            workspace_mgr.sandbox_lock(str(sandbox_id), exclusive=True)
            if workspace_mgr is not None
            else nullcontext()
        )
        with lock_ctx:
            with self._db_lock:
                current = self.sandbox_repo.get_by_id(sandbox_id)
                if current is None:
                    raise SandboxNotFoundError(f"Sandbox {sandbox_id} not found")
                self.db.refresh(current)
                if current.status in (SandboxStatus.DESTROYED, SandboxStatus.DESTROYING):
                    raise SandboxDestroyedError(
                        f"Cannot execute code in destroyed sandbox {sandbox_id}",
                        details={"status": str(current.status)},
                    )
                if current.status == SandboxStatus.EXPIRED or current.is_expired:
                    raise SandboxExpiredError(
                        f"Sandbox {sandbox_id} has expired (TTL={current.ttl_seconds}s)",
                        details={"expires_at": current.expires_at.isoformat()},
                    )

            return self.backend.execute(
                request,
                sandbox_id=str(sandbox_id),
            )

    async def execute_code(
        self,
        sandbox_id: uuid.UUID,
        code: str,
        timeout_seconds: float | None = None,
    ) -> JobExecutionResponse:
        """Execute code within a sandbox session and persist full execution history."""
        with self._db_lock:
            sandbox = self.sandbox_repo.get_by_id(sandbox_id)
            if not sandbox:
                raise SandboxNotFoundError(f"Sandbox {sandbox_id} not found")
            self.db.refresh(sandbox)

            if sandbox.status in (SandboxStatus.DESTROYED, SandboxStatus.DESTROYING):
                raise SandboxDestroyedError(
                    f"Cannot execute code in destroyed sandbox {sandbox_id}",
                    details={"status": str(sandbox.status)},
                )

            if sandbox.status == SandboxStatus.EXPIRED or sandbox.is_expired:
                should_expire = sandbox.is_active
                expires_iso = sandbox.expires_at.isoformat()
                ttl = sandbox.ttl_seconds
            else:
                should_expire = None

        if should_expire is not None:
            if should_expire:
                try:
                    self.expire_sandbox(sandbox)
                except Exception as exc:
                    logger.error(
                        "Lazy expiration cleanup failed sandbox_id=%s error_type=%s",
                        sandbox_id,
                        type(exc).__name__,
                    )
            raise SandboxExpiredError(
                f"Sandbox {sandbox_id} has expired (TTL={ttl}s)",
                details={"expires_at": expires_iso},
            )

        effective_timeout = (
            min(timeout_seconds, self.config.TIMEOUT_SECONDS)
            if timeout_seconds is not None
            else self.config.TIMEOUT_SECONDS
        )

        # Enforce one execution per logical sandbox with an atomic database claim.
        with self._db_lock:
            claimed = self.sandbox_repo.claim_for_execution(sandbox_id)
            if claimed is None:
                current = self.sandbox_repo.get_by_id(sandbox_id)
                if current is None:
                    raise SandboxNotFoundError(f"Sandbox {sandbox_id} not found")
                self.db.refresh(current)
                if current.status == SandboxStatus.EXPIRED or current.is_expired:
                    should_expire_current = current.is_active
                else:
                    should_expire_current = None
                    if current.status in (SandboxStatus.DESTROYED, SandboxStatus.DESTROYING):
                        raise SandboxDestroyedError(
                            f"Cannot execute code in destroyed sandbox {sandbox_id}"
                        )
                    raise InvalidStateTransitionError(
                        f"Sandbox {sandbox_id} is not available for execution",
                        details={"current_status": str(current.status)},
                    )
            else:
                should_expire_current = None
                sandbox = claimed

        if should_expire_current is not None:
            if should_expire_current:
                try:
                    self.expire_sandbox(current)
                except Exception as exc:
                    logger.error(
                        "Lazy expiration cleanup failed sandbox_id=%s error_type=%s",
                        sandbox_id,
                        type(exc).__name__,
                    )
            raise SandboxExpiredError(f"Sandbox {sandbox_id} has expired")

        # Create persistent job in QUEUED state
        with self._db_lock:
            job = self.execution_repo.create(
                sandbox_id=sandbox_id,
                code=code,
                timeout_seconds=effective_timeout,
            )

        try:
            # Mark started
            with self._db_lock:
                self.execution_repo.mark_started(job)

            # Offload blocking Docker execution to threadpool while synchronizing
            # with lifecycle state under the sandbox exclusive lock.
            request = ExecutionRequest(
                code=code,
                timeout_seconds=effective_timeout,
            )
            result = await run_in_threadpool(
                self._execute_in_backend,
                sandbox_id,
                request,
            )

            # Map ExecutionResult status to JobStatus
            job_status = JobStatus.COMPLETED
            if result.status == "timed_out":
                job_status = JobStatus.TIMED_OUT
            elif result.status in ("failed", "error"):
                job_status = JobStatus.FAILED

            # Persist job outcome
            with self._db_lock:
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

        except (SandboxDestroyedError, SandboxExpiredError) as exc:
            with self._db_lock:
                if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
                    self.execution_repo.mark_completed(
                        job=job,
                        status=JobStatus.FAILED,
                        exit_code=None,
                        stdout="",
                        stderr="",
                        stdout_truncated=False,
                        stderr_truncated=False,
                        duration_ms=0,
                        error_message=exc.message,
                    )
            raise

        except Exception:
            # A failed engine call must not strand a persisted job in RUNNING.
            with self._db_lock:
                if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
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
            # Revert the active session to RUNNING only when it remains EXECUTING and non-expired.
            with self._db_lock:
                self.sandbox_repo.release_execution_claim(sandbox_id)
                self.db.refresh(sandbox)

    def _ensure_usable_for_workspace(self, sandbox_id: uuid.UUID) -> Sandbox:
        """Verify that a sandbox exists and is usable before workspace operations."""
        with self._db_lock:
            sandbox = self.sandbox_repo.get_by_id(sandbox_id)
            if not sandbox:
                raise SandboxNotFoundError(f"Sandbox {sandbox_id} not found")
            self.db.refresh(sandbox)
            if sandbox.status in (SandboxStatus.DESTROYED, SandboxStatus.DESTROYING):
                raise SandboxDestroyedError(
                    f"Cannot access workspace of destroyed sandbox {sandbox_id}",
                    details={"status": str(sandbox.status)},
                )
            if sandbox.status == SandboxStatus.EXPIRED or sandbox.is_expired:
                should_expire = sandbox.is_active
                expires_iso = sandbox.expires_at.isoformat()
                ttl = sandbox.ttl_seconds
            else:
                return sandbox

        if should_expire:
            try:
                self.expire_sandbox(sandbox)
            except Exception as exc:
                logger.error(
                    "Lazy expiration cleanup failed sandbox_id=%s error_type=%s",
                    sandbox_id,
                    type(exc).__name__,
                )
        raise SandboxExpiredError(
            f"Sandbox {sandbox_id} has expired (TTL={ttl}s)",
            details={"expires_at": expires_iso},
        )

    def write_file(
        self,
        sandbox_id: uuid.UUID,
        path: str,
        content: str | bytes,
        encoding: str = "utf-8",
    ) -> FileInfo:
        """Write a file into an active sandbox's workspace."""
        workspace_mgr = self._get_workspace_manager()
        lock_ctx = (
            workspace_mgr.sandbox_lock(str(sandbox_id), exclusive=True)
            if workspace_mgr is not None
            else nullcontext()
        )
        with lock_ctx:
            self._ensure_usable_for_workspace(sandbox_id)
            return self.backend.write_file(str(sandbox_id), path, content, encoding=encoding)

    def read_file(self, sandbox_id: uuid.UUID, path: str) -> FileContent:
        """Read a file from an active sandbox's workspace."""
        self._ensure_usable_for_workspace(sandbox_id)
        return self.backend.read_file(str(sandbox_id), path)

    def list_files(self, sandbox_id: uuid.UUID, path: str = "") -> FileListResponse:
        """List files in an active sandbox's workspace."""
        self._ensure_usable_for_workspace(sandbox_id)
        return self.backend.list_files(str(sandbox_id), path=path)

    def delete_file(self, sandbox_id: uuid.UUID, path: str) -> bool:
        """Delete a file or empty directory in an active sandbox's workspace."""
        workspace_mgr = self._get_workspace_manager()
        lock_ctx = (
            workspace_mgr.sandbox_lock(str(sandbox_id), exclusive=True)
            if workspace_mgr is not None
            else nullcontext()
        )
        with lock_ctx:
            self._ensure_usable_for_workspace(sandbox_id)
            return self.backend.delete_file(str(sandbox_id), path)

    def create_directory(self, sandbox_id: uuid.UUID, path: str) -> bool:
        """Create a directory in an active sandbox's workspace."""
        workspace_mgr = self._get_workspace_manager()
        lock_ctx = (
            workspace_mgr.sandbox_lock(str(sandbox_id), exclusive=True)
            if workspace_mgr is not None
            else nullcontext()
        )
        with lock_ctx:
            self._ensure_usable_for_workspace(sandbox_id)
            return self.backend.create_directory(str(sandbox_id), path)

    def cleanup_expired_sandboxes(self, limit: int = 50) -> int:
        """Scan PostgreSQL for expired active sandboxes and clean them idempotently."""
        with self._db_lock:
            expired = self.sandbox_repo.get_expired_active(limit=limit)
        cleaned = 0
        failed = 0
        for s in expired:
            try:
                self.expire_sandbox(s)
                cleaned += 1
            except Exception as exc:
                failed += 1
                logger.error(
                    "Failed to clean expired sandbox sandbox_id=%s error_type=%s",
                    s.id,
                    type(exc).__name__,
                )
        self.last_cleanup_report = CleanupReport(
            attempted=len(expired), succeeded=cleaned, failed=failed
        )
        logger.info(
            "TTL cleanup report attempted=%d succeeded=%d failed=%d",
            self.last_cleanup_report.attempted,
            self.last_cleanup_report.succeeded,
            self.last_cleanup_report.failed,
        )
        return cleaned

    def reconcile_stale_sandboxes(self) -> int:
        """Reconcile TTL expiry and interrupted executions/destructions after a restart."""
        cutoff = utc_now()
        with self._db_lock:
            expired = self.sandbox_repo.get_expired_active(cutoff)
        reconciled = 0
        failed = 0
        for s in expired:
            try:
                with self._db_lock:
                    self.execution_repo.fail_active_jobs_for_sandbox(
                        s.id, "Sandbox expired before execution completed"
                    )
                self.expire_sandbox(s)
                reconciled += 1
            except Exception as exc:
                failed += 1
                logger.error(
                    "Failed to reconcile expired sandbox sandbox_id=%s error_type=%s",
                    s.id,
                    type(exc).__name__,
                )
        with self._db_lock:
            stale = self.sandbox_repo.get_stale_active(cutoff)
        for sandbox in stale:
            try:
                with self._db_lock:
                    self.db.refresh(sandbox)
                if sandbox.status == SandboxStatus.DESTROYING:
                    with self._db_lock:
                        self.execution_repo.fail_active_jobs_for_sandbox(
                            sandbox.id, "Sandbox destroyed during execution"
                        )
                    self.delete_sandbox(sandbox.id)
                elif sandbox.status == SandboxStatus.EXECUTING:
                    with self._db_lock:
                        self.execution_repo.fail_active_jobs_for_sandbox(
                            sandbox.id, "Execution interrupted by application restart"
                        )
                    if hasattr(self.backend, "cleanup_execution_containers"):
                        self.backend.cleanup_execution_containers(str(sandbox.id))
                        workspace_mgr = self._get_workspace_manager()
                        if workspace_mgr is not None:
                            with workspace_mgr.sandbox_lock(str(sandbox.id), exclusive=True):
                                workspace_mgr._ensure_recovered(str(sandbox.id))
                    else:
                        self.backend.cleanup_sandbox(str(sandbox.id))
                    with self._db_lock:
                        self.sandbox_repo.update_status(sandbox, SandboxStatus.RUNNING)
                reconciled += 1
            except Exception as exc:
                failed += 1
                logger.error(
                    "Failed to reconcile stale sandbox sandbox_id=%s error_type=%s",
                    sandbox.id,
                    type(exc).__name__,
                )
        self.last_reconciliation_report = CleanupReport(
            attempted=len(expired) + len(stale),
            succeeded=reconciled,
            failed=failed,
        )
        logger.info(
            "Startup reconciliation report attempted=%d succeeded=%d failed=%d",
            self.last_reconciliation_report.attempted,
            self.last_reconciliation_report.succeeded,
            self.last_reconciliation_report.failed,
        )
        return reconciled
