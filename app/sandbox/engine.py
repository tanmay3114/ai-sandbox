"""Ephemeral Sandbox Execution Engine.

Implements single-request ephemeral container execution with hardened isolation,
bounded output streaming, strict timeout enforcement, and deterministic cleanup.
"""

import logging
import threading
import time
import uuid
from collections.abc import Generator

import docker
import requests.exceptions
from docker.errors import APIError, DockerException, NotFound
from docker.models.containers import Container

from app.core.config import SandboxSettings, settings
from app.core.exceptions import (
    ConcurrencyLimitError,
    DockerEngineError,
)
from app.sandbox.docker_client import cleanup_container_safely, get_docker_client
from app.sandbox.schemas import ExecutionRequest, ExecutionResult, ExecutionStatus
from app.sandbox.security import build_container_parameters

logger = logging.getLogger(__name__)


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
    ) -> None:
        self.config = config
        self._client = client
        # In-process concurrency control
        self._semaphore = threading.BoundedSemaphore(
            value=self.config.GLOBAL_CONCURRENCY_LIMIT
        )

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
        # Normalize request input
        if isinstance(request, str):
            code = request
            requested_timeout = timeout_override
        else:
            code = request.code
            requested_timeout = request.timeout_seconds or timeout_override

        effective_timeout = (
            min(requested_timeout, self.config.TIMEOUT_SECONDS)
            if requested_timeout is not None
            else self.config.TIMEOUT_SECONDS
        )

        # 1. Enforce Concurrency Limit
        acquired = self._semaphore.acquire(blocking=False)
        if not acquired:
            logger.warning("Sandbox execution rejected: global concurrency limit reached.")
            raise ConcurrencyLimitError(
                "Sandbox execution concurrency limit reached. Please retry shortly."
            )

        execution_sandbox_id = sandbox_id or str(uuid.uuid4())
        container: Container | None = None
        start_time = time.monotonic()
        exit_code: int | None = None
        stdout = ""
        stderr = ""
        stdout_truncated = False
        stderr_truncated = False
        status = ExecutionStatus.ERROR
        error_message: str | None = None

        try:
            # 2. Build security configuration & create container
            container_params = build_container_parameters(
                code=code,
                sandbox_id=execution_sandbox_id,
                config=self.config,
            )

            try:
                container = self.client.containers.run(**container_params)
            except DockerException as exc:
                logger.error(f"Failed to create sandbox container: {exc}")
                raise DockerEngineError(f"Container creation failed: {exc}") from exc

            # 3. Wait for execution with timeout
            try:
                wait_result = container.wait(timeout=effective_timeout)
                if isinstance(wait_result, dict):
                    exit_code = wait_result.get("StatusCode")
                elif isinstance(wait_result, int):
                    exit_code = wait_result
                else:
                    exit_code = 0

                status = (
                    ExecutionStatus.COMPLETED
                    if exit_code == 0
                    else ExecutionStatus.FAILED
                )

            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                APIError,
            ) as exc:
                # Docker SDK wait timeout or underlying socket timeout
                status = ExecutionStatus.TIMED_OUT
                exit_code = None
                logger.info(
                    "Execution timed out "
                    f"({effective_timeout}s) for sandbox {execution_sandbox_id}: {exc}"
                )

                # 4. Immediately kill running container
                try:
                    container.kill()
                except (NotFound, APIError):
                    pass

            except Exception as exc:
                # Any other unexpected exception during wait
                if "timeout" in type(exc).__name__.lower():
                    status = ExecutionStatus.TIMED_OUT
                    exit_code = None
                    try:
                        container.kill()
                    except Exception:
                        pass
                else:
                    logger.error(f"Unexpected exception waiting for container: {exc}")
                    status = ExecutionStatus.ERROR
                    error_message = "Unexpected runtime error during execution wait"

            # 5. Collect bounded stdout & stderr streams
            try:
                stdout_gen = container.logs(
                    stdout=True,
                    stderr=False,
                    stream=True,
                )
                stdout, stdout_truncated = _read_bounded_stream(
                    stdout_gen,
                    self.config.MAX_STDOUT_BYTES,
                )

                stderr_gen = container.logs(
                    stdout=False,
                    stderr=True,
                    stream=True,
                )
                stderr, stderr_truncated = _read_bounded_stream(
                    stderr_gen,
                    self.config.MAX_STDERR_BYTES,
                )
            except Exception as exc:
                logger.warning(
                    f"Failed to extract container logs for {execution_sandbox_id}: {exc}"
                )

        finally:
            # 6. Guaranteed deterministic cleanup of the container
            try:
                cleanup_container_safely(container, sandbox_id=execution_sandbox_id)
            finally:
                # Release concurrency slot
                self._semaphore.release()

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
