"""Ephemeral QEMU VM execution lifecycle manager."""

from __future__ import annotations

import contextlib
import logging
import subprocess
import threading
import time
import uuid
from collections.abc import Callable

try:
    from benchmarks.telemetry import get_current_telemetry
except ImportError:

    def get_current_telemetry() -> None:  # type: ignore[misc]
        return None


from app.core.config import SandboxSettings, settings
from app.core.exceptions import (
    ConcurrencyLimitError,
    FileQuotaExceededError,
    PathTraversalError,
    QemuAgentTimeoutError,
    QemuEngineError,
    QemuProtocolError,
    WorkspaceCleanupError,
    WorkspaceRollbackError,
)
from app.sandbox.archive import SecureTarImporter, WorkspaceArchiveSerializer
from app.sandbox.engine import _build_empty_workspace_root_archive
from app.sandbox.policy import EffectiveSandboxPolicy
from app.sandbox.qemu.config import QemuVmConfig
from app.sandbox.qemu.guest_protocol import GuestAgentClient
from app.sandbox.qemu.image_manager import PreparedVmStorage, QemuImageManager
from app.sandbox.qemu.process_manager import QemuProcessManager, QemuVmHandle
from app.sandbox.qemu.runtime import verify_qemu_runtime
from app.sandbox.schemas import ExecutionRequest, ExecutionResult, ExecutionStatus
from app.sandbox.workspace import WorkspaceManager

logger = logging.getLogger(__name__)


class QemuVmManager:
    """Manages single-request ephemeral ARM64 Linux VMs and workspace synchronization."""

    def __init__(
        self,
        config: SandboxSettings = settings,
        workspace_manager: WorkspaceManager | None = None,
        image_manager: QemuImageManager | None = None,
        process_manager: QemuProcessManager | None = None,
        client_factory: Callable[[PreparedVmStorage, QemuVmConfig], GuestAgentClient] | None = None,
    ) -> None:
        self.config = config
        self.workspace_manager = workspace_manager or WorkspaceManager(config=config)
        self.archive_serializer = WorkspaceArchiveSerializer(self.workspace_manager)
        self.archive_importer = SecureTarImporter(self.workspace_manager)
        self.image_manager = image_manager or QemuImageManager(config=config)
        self.process_manager = process_manager or QemuProcessManager(
            config=config,
            image_manager=self.image_manager,
        )
        self._client_factory = client_factory
        max_vms = config.QEMU_MAX_CONCURRENT_VMS or config.GLOBAL_CONCURRENCY_LIMIT
        self._semaphore = threading.BoundedSemaphore(value=max_vms)

    def _create_client(
        self,
        storage: PreparedVmStorage,
        vm_cfg: QemuVmConfig,
    ) -> GuestAgentClient:
        if self._client_factory is not None:
            return self._client_factory(storage, vm_cfg)
        return GuestAgentClient(
            storage.socket_path,
            default_timeout_seconds=vm_cfg.agent_timeout_seconds,
            max_archive_bytes=self.config.MAX_ARCHIVE_BYTES,
        )

    def execute(
        self,
        request: ExecutionRequest | str,
        *,
        timeout_override: float | None = None,
        sandbox_id: str | None = None,
        policy: EffectiveSandboxPolicy | None = None,
    ) -> ExecutionResult:
        """Run untrusted code inside a fresh ephemeral ARM64 Linux QEMU VM.

        Follows the 14-step execution and persistence workflow:
        1. Validate policy and VM configuration.
        2. Acquire concurrency slot.
        3. Acquire exclusive sandbox workspace lock.
        4. Serialize persistent workspace archive.
        5. Create disposable per-execution VM overlay and private 0700 runtime dir.
        6. Boot ARM64 guest VM.
        7. Initialize guest execution agent over virtio-serial Unix socket.
        8. Inject workspace archive into guest /workspace tmpfs.
        9. Execute user code as unprivileged UID/GID 10001:10001.
        10. Collect bounded stdout, stderr, and exit code.
        11. Retrieve and securely import workspace archive on COMPLETED or FAILED.
        12. Request graceful guest shutdown.
        13. Deterministically terminate VM and remove overlay/socket/runtime dir.
        14. Release workspace lock and concurrency slot.
        """
        effective_policy = policy or EffectiveSandboxPolicy.from_settings(self.config)
        effective_policy.validate()
        vm_cfg = QemuVmConfig.from_settings_and_policy(self.config, effective_policy)

        if isinstance(request, str):
            code = request
            requested_timeout = timeout_override
        else:
            code = request.code
            requested_timeout = request.timeout_seconds or timeout_override

        effective_timeout = (
            min(requested_timeout, effective_policy.timeout_seconds)
            if requested_timeout is not None
            else effective_policy.timeout_seconds
        )

        acquired = self._semaphore.acquire(blocking=False)
        if not acquired:
            logger.warning("QEMU execution rejected: concurrency limit reached.")
            raise ConcurrencyLimitError(
                "Sandbox execution concurrency limit reached. Please retry shortly."
            )

        has_persistent_workspace = sandbox_id is not None
        execution_sandbox_id = sandbox_id or str(uuid.uuid4())
        storage: PreparedVmStorage | None = None
        vm_handle: QemuVmHandle | None = None
        client: GuestAgentClient | None = None

        start_time = time.monotonic()
        telemetry = get_current_telemetry()
        if telemetry is not None:
            telemetry.mark("start")
        exit_code: int | None = None
        stdout = ""
        stderr = ""
        stdout_truncated = False
        stderr_truncated = False
        status = ExecutionStatus.ERROR
        error_message: str | None = None

        lock_ctx = (
            self.workspace_manager.sandbox_lock(execution_sandbox_id, exclusive=True)
            if has_persistent_workspace
            else contextlib.nullcontext()
        )

        try:
            with lock_ctx:
                try:
                    archive_spool = None
                    try:
                        if has_persistent_workspace:
                            archive_spool = self.archive_serializer.serialize(
                                execution_sandbox_id,
                                include_root_entry=True,
                                acquire_lock=False,
                            )
                            archive_payload: object = archive_spool
                        else:
                            archive_payload = _build_empty_workspace_root_archive()

                        if telemetry is not None:
                            telemetry.mark("create_start")
                        storage = self.image_manager.prepare_execution_storage(
                            sandbox_id=execution_sandbox_id,
                            vm_cfg=vm_cfg,
                        )
                        vm_handle = self.process_manager.start_vm(
                            vm_cfg=vm_cfg,
                            storage=storage,
                        )
                        client = self._create_client(storage, vm_cfg)

                        # Boot & guest agent readiness + workspace tmpfs initialization
                        try:
                            client.wait_until_ready(
                                boot_timeout_seconds=vm_cfg.boot_timeout_seconds,
                                workspace_size_bytes=vm_cfg.workspace_tmpfs_size_bytes,
                                max_file_size_bytes=vm_cfg.max_file_size_bytes,
                                max_file_count=vm_cfg.max_file_count,
                                pids_limit=vm_cfg.pids_limit,
                                run_as_uid=vm_cfg.run_as_uid,
                                run_as_gid=vm_cfg.run_as_gid,
                                process_alive_check=vm_handle.is_alive,
                            )
                            if telemetry is not None:
                                telemetry.mark("env_ready")
                                telemetry.mark("inject_start")
                            client.inject_archive(
                                archive_payload,  # type: ignore[arg-type]
                                timeout_seconds=vm_cfg.agent_timeout_seconds,
                            )
                            if telemetry is not None:
                                telemetry.mark("inject_end")
                        except (QemuAgentTimeoutError, QemuProtocolError, OSError) as exc:
                            logger.error(
                                "Guest boot or initialization failed for sandbox %s: %s",
                                execution_sandbox_id,
                                exc,
                            )
                            status = ExecutionStatus.ERROR
                            exit_code = None
                            error_message = "Guest VM initialization or workspace injection failed"
                        else:
                            # Execute user Python code inside the guest
                            if telemetry is not None:
                                telemetry.mark("workload_start")
                            try:
                                outcome = client.execute_code(
                                    code,
                                    timeout_seconds=effective_timeout,
                                    max_stdout_bytes=effective_policy.max_stdout_bytes,
                                    max_stderr_bytes=effective_policy.max_stderr_bytes,
                                )
                                stdout = outcome.stdout
                                stderr = outcome.stderr
                                stdout_truncated = outcome.stdout_truncated
                                stderr_truncated = outcome.stderr_truncated

                                if outcome.timed_out:
                                    status = ExecutionStatus.TIMED_OUT
                                    exit_code = None
                                else:
                                    exit_code = outcome.exit_code
                                    status = (
                                        ExecutionStatus.COMPLETED
                                        if exit_code == 0
                                        else ExecutionStatus.FAILED
                                    )
                            except QemuAgentTimeoutError as exc:
                                logger.info(
                                    "QEMU guest execution timed out (%ss) for sandbox %s: %s",
                                    effective_timeout,
                                    execution_sandbox_id,
                                    exc,
                                )
                                status = ExecutionStatus.TIMED_OUT
                                exit_code = None
                            except (QemuProtocolError, OSError) as exc:
                                logger.error(
                                    "QEMU guest communication error for sandbox %s: %s",
                                    execution_sandbox_id,
                                    exc,
                                )
                                status = ExecutionStatus.ERROR
                                exit_code = None
                                error_message = (
                                    "Guest communication failure during sandbox execution"
                                )
                            finally:
                                if telemetry is not None:
                                    telemetry.mark("workload_end")
                                    if vm_handle is not None and vm_handle.process is not None:
                                        with contextlib.suppress(Exception):
                                            pid = vm_handle.process.pid
                                            res = subprocess.run(
                                                ["ps", "-o", "rss=", "-p", str(pid)],
                                                capture_output=True,
                                                text=True,
                                                timeout=0.5,
                                                check=False,
                                            )
                                            if res.stdout.strip():
                                                rss_kb = int(res.stdout.strip())
                                                telemetry.record_memory(
                                                    peak_bytes=rss_kb * 1024,
                                                    steady_bytes=rss_kb * 1024,
                                                )
                    finally:
                        if archive_spool is not None:
                            archive_spool.close()

                    # Synchronize workspace back ONLY on COMPLETED or FAILED
                    should_sync_back = (
                        has_persistent_workspace
                        and client is not None
                        and status in (ExecutionStatus.COMPLETED, ExecutionStatus.FAILED)
                    )
                    if should_sync_back and client is not None:
                        if telemetry is not None:
                            telemetry.mark("retrieve_start")
                        exported_spool = None
                        try:
                            exported_spool = client.export_archive(
                                max_bytes=self.config.MAX_ARCHIVE_BYTES,
                                timeout_seconds=vm_cfg.agent_timeout_seconds,
                            )
                            self.archive_importer.import_archive(
                                execution_sandbox_id,
                                exported_spool,
                                strip_root_prefix="workspace",
                                acquire_lock=False,
                            )
                        except FileQuotaExceededError as exc:
                            logger.warning(
                                "QEMU workspace archive quota exceeded for sandbox %s: %s",
                                execution_sandbox_id,
                                type(exc).__name__,
                            )
                            status = ExecutionStatus.ERROR
                            error_message = (
                                "Workspace synchronization failed: workspace output "
                                "exceeded configured resource or quota limits"
                            )
                        except PathTraversalError as exc:
                            logger.warning(
                                "QEMU workspace archive security violation for sandbox %s: %s",
                                execution_sandbox_id,
                                type(exc).__name__,
                            )
                            status = ExecutionStatus.ERROR
                            error_message = (
                                "Workspace synchronization failed: workspace output "
                                "violated filesystem security policy"
                            )
                        except WorkspaceRollbackError as exc:
                            logger.critical(
                                "QEMU workspace commit and rollback failed for sandbox %s: %s",
                                execution_sandbox_id,
                                type(exc).__name__,
                            )
                            status = ExecutionStatus.ERROR
                            error_message = (
                                "Workspace synchronization failed: commit and automatic "
                                "rollback failed; previous workspace backup preserved for recovery"
                            )
                        except WorkspaceCleanupError as exc:
                            logger.error(
                                "QEMU workspace commit failed for sandbox %s: %s",
                                execution_sandbox_id,
                                type(exc).__name__,
                            )
                            status = ExecutionStatus.ERROR
                            error_message = (
                                "Workspace synchronization failed: unable to commit "
                                "updated workspace state"
                            )
                        except (QemuEngineError, OSError) as exc:
                            logger.error(
                                "QEMU workspace archive retrieval failed for sandbox %s: %s",
                                execution_sandbox_id,
                                type(exc).__name__,
                            )
                            status = ExecutionStatus.ERROR
                            error_message = (
                                "Workspace synchronization failed: unable to retrieve "
                                "workspace archive from execution VM"
                            )
                        finally:
                            if exported_spool is not None:
                                exported_spool.close()
                            if telemetry is not None:
                                telemetry.mark("retrieve_end")

                    # Attempt graceful guest shutdown when the agent channel is healthy
                    if client is not None and status in (
                        ExecutionStatus.COMPLETED,
                        ExecutionStatus.FAILED,
                    ):
                        with contextlib.suppress(Exception):
                            client.shutdown(timeout_seconds=1.0)
                finally:
                    if client is not None:
                        client.close()
                    if telemetry is not None:
                        telemetry.mark("cleanup_start")
                    if vm_handle is not None:
                        cleaned = self.process_manager.cleanup_vm(
                            vm_handle,
                            expected_sandbox_id=execution_sandbox_id,
                        )
                        if telemetry is not None:
                            telemetry.mark("cleanup_end")
                            telemetry.record_cleanup_confirmed(cleaned)
                        if not cleaned:
                            raise QemuEngineError(
                                f"Verified VM cleanup failed for sandbox {execution_sandbox_id}"
                            )
                    elif storage is not None:
                        cleaned = self.image_manager.cleanup_storage(storage)
                        if telemetry is not None:
                            telemetry.mark("cleanup_end")
                            telemetry.record_cleanup_confirmed(cleaned)
                        if not cleaned:
                            raise QemuEngineError(
                                f"Verified VM storage cleanup failed for "
                                f"sandbox {execution_sandbox_id}"
                            )
        finally:
            self._semaphore.release()

        if telemetry is not None:
            telemetry.mark("end")

        duration_ms = max(0, int((time.monotonic() - start_time) * 1000))
        return ExecutionResult(
            sandbox_id=execution_sandbox_id,
            status=status,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            duration_ms=duration_ms,
            error_message=error_message,
        )

    def cleanup_execution_containers(self, sandbox_id: str) -> None:
        """Clean up only verified ephemeral execution VMs owned by the logical sandbox."""
        with self.workspace_manager.sandbox_lock(sandbox_id, exclusive=True):
            self.process_manager.cleanup_sandbox_vms(sandbox_id)

    def cleanup_sandbox(self, sandbox_id: str) -> None:
        """Clean up verified ephemeral VMs and persistent workspace for the logical sandbox."""
        with self.workspace_manager.sandbox_lock(sandbox_id, exclusive=True):
            self.process_manager.cleanup_sandbox_vms(sandbox_id)
            self.workspace_manager.delete_workspace(sandbox_id)

    def check_health(self) -> None:
        """Verify QEMU runtime capabilities, HVF support, and guest assets."""
        verify_qemu_runtime(self.config)
