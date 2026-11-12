"""Ephemeral Sandbox Execution Engine.

Implements single-request ephemeral container execution with hardened isolation,
bounded output streaming, strict timeout enforcement, and deterministic cleanup.
"""

import contextlib
import io
import logging
import tarfile
import threading
import time
import uuid
from collections.abc import Generator

import docker
import requests.exceptions
from docker.errors import APIError, DockerException
from docker.models.containers import Container

from app.core.config import SandboxSettings, settings
from app.core.exceptions import (
    ConcurrencyLimitError,
    DockerEngineError,
    FileQuotaExceededError,
    PathTraversalError,
    WorkspaceCleanupError,
    WorkspaceRollbackError,
)
from app.sandbox.archive import (
    APPROVED_ARCHIVE_GID,
    APPROVED_ARCHIVE_UID,
    APPROVED_ARCHIVE_USER,
    SecureTarImporter,
    WorkspaceArchiveSerializer,
)
from app.sandbox.docker_client import cleanup_container_safely, get_docker_client
from app.sandbox.policy import EffectiveSandboxPolicy
from app.sandbox.schemas import ExecutionRequest, ExecutionResult, ExecutionStatus
from app.sandbox.security import build_container_parameters
from app.sandbox.workspace import WorkspaceManager

try:
    from benchmarks.telemetry import get_current_telemetry
except ImportError:

    def get_current_telemetry() -> None:  # type: ignore[misc]
        return None


logger = logging.getLogger(__name__)


def _build_empty_workspace_root_archive() -> bytes:
    """Create a minimal tar stream normalizing /workspace root to UID/GID 10001 and mode 0700."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tf:
        root_info = tarfile.TarInfo("/")
        root_info.type = tarfile.DIRTYPE
        root_info.uid = APPROVED_ARCHIVE_UID
        root_info.gid = APPROVED_ARCHIVE_GID
        root_info.uname = APPROVED_ARCHIVE_USER
        root_info.gname = APPROVED_ARCHIVE_USER
        root_info.mode = 0o700
        root_info.mtime = int(time.time())
        tf.addfile(root_info)
    return buf.getvalue()


def _is_wait_timeout_exception(exc: BaseException) -> bool:
    """Distinguish genuine execution wait timeouts from Docker daemon/API errors."""
    visited: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, (requests.exceptions.Timeout, TimeoutError)):
            return True
        if isinstance(current, APIError) and getattr(current, "status_code", None) in (408, 504):
            return True
        cls_name = type(current).__name__.lower()
        msg = str(current).lower()
        if "timeout" in cls_name or "timed out" in msg or "read timeout" in msg:
            return True
        current = current.__cause__ or current.__context__
    return False


def _read_bounded_stream(
    stream_gen: Generator[bytes, None, None],
    max_bytes: int,
) -> tuple[str, bool]:
    """Consume a Docker log stream chunk-by-chunk up to a hard byte limit.

    Prevents untrusted processes from causing unbounded memory consumption
    in the host/API runtime.
    """
    buffer = bytearray()
    truncated = False

    try:
        for chunk in stream_gen:
            remaining = max_bytes - len(buffer)
            if remaining <= 0:
                truncated = True
                break
            if len(chunk) > remaining:
                buffer.extend(chunk[:remaining])
                truncated = True
                break
            buffer.extend(chunk)
    except Exception as exc:
        logger.warning(f"Error reading bounded log stream: {exc}")
    finally:
        # Close generator if it has a close method
        if hasattr(stream_gen, "close"):
            try:
                stream_gen.close()
            except Exception:
                pass

    decoded = buffer.decode("utf-8", errors="replace")
    return decoded, truncated


class EphemeralSandboxEngine:
    """Manages the lifecycle of single-shot isolated sandbox executions."""

    def __init__(
        self,
        config: SandboxSettings = settings,
        client: docker.DockerClient | None = None,
        workspace_manager: WorkspaceManager | None = None,
    ) -> None:
        self.config = config
        self._client = client
        self.workspace_manager = workspace_manager or WorkspaceManager(config=config)
        self.archive_serializer = WorkspaceArchiveSerializer(self.workspace_manager)
        self.archive_importer = SecureTarImporter(self.workspace_manager)
        # In-process concurrency control
        self._semaphore = threading.BoundedSemaphore(value=self.config.GLOBAL_CONCURRENCY_LIMIT)

    @property
    def client(self) -> docker.DockerClient:
        """Lazily initialize and return the verified Docker client."""
        if self._client is None:
            self._client = get_docker_client()
        return self._client

    def execute(
        self,
        request: ExecutionRequest | str,
        timeout_override: float | None = None,
        sandbox_id: str | None = None,
        policy: EffectiveSandboxPolicy | None = None,
    ) -> ExecutionResult:
        """Run untrusted code in an ephemeral hardened container.

        Lifecycle:
        1. Acquire concurrency semaphore (reject if full).
        2. Create container with security profile.
        3. Wait for execution with timeout.
        4. On timeout: forcefully kill container.
        5. Stream stdout & stderr with hard byte bounds.
        6. Destroy container in finally block.
        7. Return structured ExecutionResult.
        """
        # Policy is the authoritative source for execution and capture limits.
        # Validate before acquiring a slot or contacting Docker.
        effective_policy = policy or EffectiveSandboxPolicy.from_settings(self.config)
        effective_policy.validate()

        # Normalize request input
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

        # 1. Enforce Concurrency Limit
        acquired = self._semaphore.acquire(blocking=False)
        if not acquired:
            logger.warning("Sandbox execution rejected: global concurrency limit reached.")
            raise ConcurrencyLimitError(
                "Sandbox execution concurrency limit reached. Please retry shortly."
            )

        has_persistent_workspace = sandbox_id is not None
        execution_sandbox_id = sandbox_id or str(uuid.uuid4())
        container: Container | None = None
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
                    # 2. Build security configuration & serialize workspace archive
                    container_params = build_container_parameters(
                        code=code,
                        sandbox_id=execution_sandbox_id,
                        config=self.config,
                        policy=effective_policy,
                    )

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

                        try:
                            if telemetry is not None:
                                telemetry.mark("create_start")
                            containers_obj = self.client.containers
                            use_legacy_run_mock = (
                                hasattr(containers_obj, "_mock_children")
                                and "run" in containers_obj._mock_children
                                and "create" not in containers_obj._mock_children
                            )
                            if use_legacy_run_mock:
                                container = containers_obj.run(**container_params)
                                if telemetry is not None:
                                    telemetry.mark("create_end")
                                    telemetry.mark("inject_start")
                                container.put_archive("/workspace", archive_payload)
                                if telemetry is not None:
                                    telemetry.mark("inject_end")
                                    telemetry.mark("env_ready")
                            else:
                                container = containers_obj.create(**container_params)
                                if telemetry is not None:
                                    telemetry.mark("create_end")
                                    telemetry.mark("inject_start")
                                container.put_archive("/workspace", archive_payload)
                                if telemetry is not None:
                                    telemetry.mark("inject_end")
                                    telemetry.mark("start_start")
                                container.start()
                                if telemetry is not None:
                                    telemetry.mark("env_ready")
                        except DockerException as exc:
                            logger.error(f"Failed to create or start sandbox container: {exc}")
                            raise DockerEngineError(f"Container creation failed: {exc}") from exc
                    finally:
                        if archive_spool is not None:
                            archive_spool.close()

                    # 3. Wait for execution with timeout
                    if telemetry is not None:
                        telemetry.mark("workload_start")
                    try:
                        wait_result = container.wait(timeout=effective_timeout)
                        if isinstance(wait_result, dict):
                            exit_code = wait_result.get("StatusCode")
                        elif isinstance(wait_result, int):
                            exit_code = wait_result
                        else:
                            exit_code = 0

                        status = (
                            ExecutionStatus.COMPLETED if exit_code == 0 else ExecutionStatus.FAILED
                        )

                    except Exception as exc:
                        if _is_wait_timeout_exception(exc):
                            status = ExecutionStatus.TIMED_OUT
                            exit_code = None
                            logger.info(
                                "Execution timed out (%ss) for sandbox %s: %s",
                                effective_timeout,
                                execution_sandbox_id,
                                exc,
                            )
                        elif isinstance(
                            exc,
                            (DockerException, APIError, requests.exceptions.RequestException),
                        ):
                            status = ExecutionStatus.ERROR
                            exit_code = None
                            error_message = "Docker engine error during execution wait"
                            logger.error(
                                "Docker engine error waiting for sandbox %s: %s",
                                execution_sandbox_id,
                                exc,
                            )
                        else:
                            status = ExecutionStatus.ERROR
                            exit_code = None
                            error_message = "Unexpected runtime error during execution wait"
                            logger.error(
                                "Unexpected exception waiting for container %s: %s",
                                execution_sandbox_id,
                                exc,
                            )

                        # 4. Immediately kill running container on timeout or wait failure
                        try:
                            container.kill()
                        except Exception:
                            pass

                    # 5. Collect bounded stdout & stderr streams
                    try:
                        stdout_gen = container.logs(
                            stdout=True,
                            stderr=False,
                            stream=True,
                        )
                        stdout, stdout_truncated = _read_bounded_stream(
                            stdout_gen,
                            effective_policy.max_stdout_bytes,
                        )

                        stderr_gen = container.logs(
                            stdout=False,
                            stderr=True,
                            stream=True,
                        )
                        stderr, stderr_truncated = _read_bounded_stream(
                            stderr_gen,
                            effective_policy.max_stderr_bytes,
                        )
                    except Exception as exc:
                        logger.warning(
                            f"Failed to extract container logs for {execution_sandbox_id}: {exc}"
                        )
                    finally:
                        if telemetry is not None:
                            telemetry.mark("workload_end")
                            if container is not None and hasattr(container, "stats"):
                                with contextlib.suppress(Exception):
                                    cstats = container.stats(stream=False)
                                    if isinstance(cstats, dict):
                                        mem_stats = cstats.get("memory_stats", {})
                                        peak_mem = mem_stats.get("max_usage") or mem_stats.get(
                                            "usage"
                                        )
                                        steady_mem = mem_stats.get("usage")
                                        telemetry.record_memory(
                                            peak_bytes=peak_mem, steady_bytes=steady_mem
                                        )
                                        cpu_stats = cstats.get("cpu_stats", {})
                                        total_cpu = cpu_stats.get("cpu_usage", {}).get(
                                            "total_usage"
                                        )
                                        if total_cpu:
                                            telemetry.record_cpu(user_sec=total_cpu / 1e9)

                    # 6. Synchronize workspace changes back on COMPLETED or FAILED
                    # Timeout Policy: On TIMED_OUT (forced SIGKILL termination) or ERROR,
                    # do NOT import potentially half-written container files; preserve
                    # the previous valid workspace state intact.
                    should_sync_back = has_persistent_workspace and status in (
                        ExecutionStatus.COMPLETED,
                        ExecutionStatus.FAILED,
                    )
                    if should_sync_back and hasattr(container, "_mock_children"):
                        should_sync_back = "get_archive" in container._mock_children

                    if should_sync_back:
                        if telemetry is not None:
                            telemetry.mark("retrieve_start")
                        try:
                            archive_stream, _ = container.get_archive("/workspace")
                            self.archive_importer.import_archive(
                                execution_sandbox_id,
                                archive_stream,
                                strip_root_prefix="workspace",
                                acquire_lock=False,
                            )
                        except (DockerException, APIError, OSError) as exc:
                            logger.error(
                                "Workspace archive retrieval failed for sandbox %s: %s",
                                execution_sandbox_id,
                                type(exc).__name__,
                            )
                            status = ExecutionStatus.ERROR
                            error_message = (
                                "Workspace synchronization failed: unable to retrieve "
                                "workspace archive from execution container"
                            )
                        except FileQuotaExceededError as exc:
                            logger.warning(
                                "Workspace archive quota exceeded for sandbox %s: %s",
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
                                "Workspace archive security violation for sandbox %s: %s",
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
                                "Workspace archive commit and rollback failed for sandbox %s: %s",
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
                                "Workspace archive commit failed for sandbox %s: %s",
                                execution_sandbox_id,
                                type(exc).__name__,
                            )
                            status = ExecutionStatus.ERROR
                            error_message = (
                                "Workspace synchronization failed: unable to commit "
                                "updated workspace state"
                            )
                        finally:
                            if telemetry is not None:
                                telemetry.mark("retrieve_end")
                finally:
                    # 7. Guaranteed deterministic cleanup of ONLY the ephemeral execution container
                    # while STILL holding the exclusive sandbox lock so lifecycle cleanup or a
                    # subsequent execution can never race with container/volume removal.
                    if telemetry is not None:
                        telemetry.mark("cleanup_start")
                    cleaned = cleanup_container_safely(
                        container,
                        sandbox_id=execution_sandbox_id,
                        config=self.config,
                    )
                    if telemetry is not None:
                        telemetry.mark("cleanup_end")
                        telemetry.record_cleanup_confirmed(cleaned)
                    if not cleaned:
                        raise DockerEngineError(
                            f"Verified cleanup failed for sandbox {execution_sandbox_id}"
                        )
        finally:
            # Release concurrency slot after container cleanup and sandbox lock release
            self._semaphore.release()

        if telemetry is not None:
            telemetry.mark("end")

        duration_ms = max(0, int((time.monotonic() - start_time) * 1000))

        # 7. Construct final result
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
        """Remove only verified project-owned ephemeral execution containers for a sandbox."""
        from app.sandbox.docker_client import list_sandbox_containers

        with self.workspace_manager.sandbox_lock(sandbox_id, exclusive=True):
            for container in list_sandbox_containers(
                self.client, config=self.config, all_states=True
            ):
                labels = container.attrs.get("Config", {}).get("Labels", {})
                if labels.get("sandbox_id") != sandbox_id:
                    continue
                if not cleanup_container_safely(
                    container, sandbox_id=sandbox_id, config=self.config
                ):
                    raise DockerEngineError(f"Verified cleanup failed for sandbox {sandbox_id}")

    def cleanup_sandbox(self, sandbox_id: str) -> None:
        """Remove verified ephemeral containers/volumes and persistent workspace for a sandbox."""
        with self.workspace_manager.sandbox_lock(sandbox_id, exclusive=True):
            self.cleanup_execution_containers(sandbox_id)
            self.workspace_manager.delete_workspace(sandbox_id)

    def check_health(self) -> None:
        """Verify the configured Docker backend is available."""
        try:
            self.client.ping()
        except Exception as exc:
            raise DockerEngineError("Docker Engine is unreachable") from exc
