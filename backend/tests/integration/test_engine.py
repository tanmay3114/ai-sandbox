"""Integration tests for EphemeralSandboxEngine executing in Docker."""

import concurrent.futures
import threading
import time

import pytest

from app.core.config import SandboxSettings
from app.core.exceptions import ConcurrencyLimitError
from app.sandbox.docker_client import cleanup_container_safely
from app.sandbox.engine import EphemeralSandboxEngine
from app.sandbox.schemas import ExecutionStatus


def test_normal_python_execution(engine: EphemeralSandboxEngine):
    """Test standard successful Python execution returning stdout and exit code 0."""
    result = engine.execute("print(2 + 2)")

    assert result.status == ExecutionStatus.COMPLETED
    assert result.exit_code == 0
    assert result.stdout.strip() == "4"
    assert result.stderr == ""
    assert not result.stdout_truncated
    assert not result.stderr_truncated
    assert result.duration_ms >= 0


def test_syntax_error(engine: EphemeralSandboxEngine):
    """Test that Python syntax errors are captured with non-zero exit code and stderr."""
    result = engine.execute("def invalid_syntax(:")

    assert result.status == ExecutionStatus.FAILED
    assert result.exit_code != 0
    assert "SyntaxError" in result.stderr
    assert not result.stderr_truncated


def test_runtime_exception(engine: EphemeralSandboxEngine):
    """Test unhandled Python runtime exception capture."""
    result = engine.execute("raise RuntimeError('Sandbox custom exception')")

    assert result.status == ExecutionStatus.FAILED
    assert result.exit_code != 0
    assert "RuntimeError: Sandbox custom exception" in result.stderr


def test_infinite_loop_timeout(engine: EphemeralSandboxEngine):
    """Test that a CPU-pegging infinite loop is forcefully killed and marked TIMED_OUT."""
    t0 = time.monotonic()
    result = engine.execute("while True: pass")
    duration = time.monotonic() - t0

    assert result.status == ExecutionStatus.TIMED_OUT
    assert result.exit_code is None
    # Verify execution finished reasonably close to the configured timeout (2.0s in test profile)
    assert 1.8 <= duration <= 4.0


def test_long_sleep_timeout(engine: EphemeralSandboxEngine):
    """Test that a sleeping process exceeding timeout is forcefully terminated."""
    t0 = time.monotonic()
    result = engine.execute("import time; time.sleep(10)")
    duration = time.monotonic() - t0

    assert result.status == ExecutionStatus.TIMED_OUT
    assert result.exit_code is None
    assert 1.8 <= duration <= 4.0


def test_output_limiting_and_truncation(engine: EphemeralSandboxEngine):
    """Test that massive stdout and stderr output are bounded without memory explosion."""
    # Test profile limits max stdout/stderr to 1024 bytes
    code = """
import sys
sys.stdout.write('A' * 500000)
sys.stderr.write('B' * 500000)
"""
    result = engine.execute(code)

    assert result.status in (ExecutionStatus.COMPLETED, ExecutionStatus.FAILED)
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True
    assert len(result.stdout.encode("utf-8")) <= 1024
    assert len(result.stderr.encode("utf-8")) <= 1024


def test_memory_limit_exhaustion(engine: EphemeralSandboxEngine):
    """Test that attempting to allocate excessive memory is constrained and fails safely."""
    # Test profile sets memory limit to 128m
    code = """
# Try allocating 400MB
chunks = []
for _ in range(400):
    chunks.append(b'x' * (1024 * 1024))
"""
    result = engine.execute(code)
    # The process should either raise MemoryError or be killed by OOM (exit code 137)
    assert result.status == ExecutionStatus.FAILED
    assert result.exit_code != 0


def test_pid_limit_fork_bomb(engine: EphemeralSandboxEngine):
    """Test that a fork bomb attempt is constrained by pids_limit=32."""
    code = """
import os
try:
    for _ in range(100):
        os.fork()
except OSError as e:
    # Fork bomb was successfully blocked by kernel pid limit
    print(f"FORK_BLOCKED: {e}")
"""
    result = engine.execute(code)
    # The script should be blocked from unbounded process table exhaustion
    assert "FORK_BLOCKED" in result.stdout or result.status == ExecutionStatus.FAILED


def test_concurrency_limit_rejection(docker_client):
    """Test that concurrent executions beyond the semaphore limit are rejected."""
    limit_settings = SandboxSettings(
        TIMEOUT_SECONDS=3.0,
        GLOBAL_CONCURRENCY_LIMIT=1,  # Capacity of 1
    )
    single_capacity_engine = EphemeralSandboxEngine(config=limit_settings, client=docker_client)

    barrier = threading.Barrier(2)

    def run_first():
        # Holds the single slot for 2 seconds
        barrier.wait()
        return single_capacity_engine.execute("import time; time.sleep(2)")

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(run_first)
        barrier.wait()
        # Give a small margin for f1 to acquire the semaphore
        time.sleep(0.3)

        # The second execution should immediately fail with ConcurrencyLimitError
        with pytest.raises(ConcurrencyLimitError):
            single_capacity_engine.execute("print('rejected')")

        res1 = f1.result()
        assert res1.status in (ExecutionStatus.COMPLETED, ExecutionStatus.TIMED_OUT)


def test_idempotent_cleanup():
    """Test that safe container cleanup is completely idempotent."""
    assert cleanup_container_safely(None) is True
