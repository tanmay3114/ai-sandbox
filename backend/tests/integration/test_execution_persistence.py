"""Docker integration tests for workspace archive injection, cross-execution
persistence, synchronization semantics, and execution cleanup separation.
"""

from __future__ import annotations

import fcntl
import os

import docker

from app.core.config import SandboxSettings
from app.sandbox.docker_backend import DockerSandboxBackend
from app.sandbox.docker_client import list_sandbox_containers
from app.sandbox.engine import EphemeralSandboxEngine
from app.sandbox.schemas import ExecutionRequest, ExecutionStatus


def _assert_lock_is_free(backend: DockerSandboxBackend, sandbox_id: str) -> None:
    """Verify the per-sandbox advisory lock is not held by acquiring LOCK_EX | LOCK_NB."""
    lock_path = backend.workspace_manager.get_lock_path(sandbox_id)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def test_workspace_injected_before_execution_and_persists_across_containers(
    docker_client: docker.DockerClient,
    fast_settings: SandboxSettings,
):
    """Verify pre-seeded files are injected and container-written files persist across runs."""
    engine = EphemeralSandboxEngine(config=fast_settings, client=docker_client)
    backend = DockerSandboxBackend(config=fast_settings, engine=engine)
    sandbox_id = "persist-multi-exec"

    # 1. Seed initial file via backend before any container runs
    backend.write_file(sandbox_id, "seed.txt", "initial-seed")
    backend.create_directory(sandbox_id, "reports")

    # 2. First fresh execution container reads seed.txt and creates step1.txt + nested file
    code_1 = """
import os, socket
with open("seed.txt") as f:
    seed_val = f.read().strip()
with open("step1.txt", "w") as f:
    f.write(f"{seed_val}->step1")
with open("reports/summary.txt", "w") as f:
    f.write("report-v1")
print(f"HOST_1={socket.gethostname()}")
"""
    res_1 = backend.execute(ExecutionRequest(code=code_1), sandbox_id=sandbox_id)
    assert res_1.status == ExecutionStatus.COMPLETED
    assert res_1.exit_code == 0
    host_1 = res_1.stdout.strip()

    # Verify execution container was cleaned up, while persistent workspace remains
    assert list_sandbox_containers(docker_client, config=fast_settings, all_states=True) == []
    assert backend.read_file(sandbox_id, "step1.txt").content == "initial-seed->step1"
    assert backend.read_file(sandbox_id, "reports/summary.txt").content == "report-v1"
    _assert_lock_is_free(backend, sandbox_id)

    # 3. Second fresh execution container reads step1.txt and updates workspace
    code_2 = """
import socket
with open("step1.txt") as f:
    prev = f.read().strip()
with open("step2.txt", "w") as f:
    f.write(f"{prev}->step2")
print(f"HOST_2={socket.gethostname()}")
"""
    res_2 = backend.execute(ExecutionRequest(code=code_2), sandbox_id=sandbox_id)
    assert res_2.status == ExecutionStatus.COMPLETED
    assert res_2.exit_code == 0
    host_2 = res_2.stdout.strip()

    # Confirm the two executions ran in two distinct fresh containers
    assert host_1 != host_2
    assert backend.read_file(sandbox_id, "seed.txt").content == "initial-seed"
    assert backend.read_file(sandbox_id, "step1.txt").content == "initial-seed->step1"
    assert backend.read_file(sandbox_id, "step2.txt").content == "initial-seed->step1->step2"
    assert backend.read_file(sandbox_id, "reports/summary.txt").content == "report-v1"
    _assert_lock_is_free(backend, sandbox_id)


def test_non_zero_exit_preserves_valid_workspace_changes(
    docker_client: docker.DockerClient,
    fast_settings: SandboxSettings,
):
    """Verify valid files written before a non-zero exit are synchronized and preserved."""
    engine = EphemeralSandboxEngine(config=fast_settings, client=docker_client)
    backend = DockerSandboxBackend(config=fast_settings, engine=engine)
    sandbox_id = "persist-nonzero-exit"

    backend.write_file(sandbox_id, "existing.txt", "keep-me")

    code = """
import sys
with open("diagnostic.log", "w") as f:
    f.write("partial progress before error")
sys.stderr.write("fatal calculation error\\n")
sys.exit(3)
"""
    res = backend.execute(ExecutionRequest(code=code), sandbox_id=sandbox_id)

    assert res.status == ExecutionStatus.FAILED
    assert res.exit_code == 3
    assert "fatal calculation error" in res.stderr
    assert backend.read_file(sandbox_id, "existing.txt").content == "keep-me"
    assert (
        backend.read_file(sandbox_id, "diagnostic.log").content == "partial progress before error"
    )
    _assert_lock_is_free(backend, sandbox_id)


def test_timeout_preserves_previous_valid_workspace_without_partial_import(
    docker_client: docker.DockerClient,
    fast_settings: SandboxSettings,
):
    """Verify timed-out executions do not corrupt or overwrite the pre-execution workspace."""
    engine = EphemeralSandboxEngine(config=fast_settings, client=docker_client)
    backend = DockerSandboxBackend(config=fast_settings, engine=engine)
    sandbox_id = "persist-timeout"

    backend.write_file(sandbox_id, "stable.txt", "verified-baseline")

    code = """
import time
with open("stable.txt", "w") as f:
    f.write("uncommitted-corrupted-write")
with open("partial.txt", "w") as f:
    f.write("incomplete")
time.sleep(10)
"""
    res = backend.execute(
        ExecutionRequest(code=code, timeout_seconds=1.0),
        sandbox_id=sandbox_id,
    )

    assert res.status == ExecutionStatus.TIMED_OUT
    assert res.exit_code is None
    # Pre-execution workspace must be preserved intact
    assert backend.read_file(sandbox_id, "stable.txt").content == "verified-baseline"
    listed_paths = [f.path for f in backend.list_files(sandbox_id).files]
    assert "partial.txt" not in listed_paths
    _assert_lock_is_free(backend, sandbox_id)


def test_archive_import_failure_on_container_symlink_preserves_previous_workspace(
    docker_client: docker.DockerClient,
    fast_settings: SandboxSettings,
):
    """Verify creating a symlink inside /workspace fails post-run sync and rolls back cleanly."""
    engine = EphemeralSandboxEngine(config=fast_settings, client=docker_client)
    backend = DockerSandboxBackend(config=fast_settings, engine=engine)
    sandbox_id = "persist-symlink-reject"

    backend.write_file(sandbox_id, "clean.txt", "safe-before-run")

    code = """
import os
with open("clean.txt", "w") as f:
    f.write("tampered")
os.symlink("/etc/passwd", "escape_link.txt")
"""
    res = backend.execute(ExecutionRequest(code=code), sandbox_id=sandbox_id)

    assert res.status == ExecutionStatus.ERROR
    assert res.error_message is not None
    assert "security policy" in res.error_message
    # Previous valid workspace state is preserved untouched
    assert backend.read_file(sandbox_id, "clean.txt").content == "safe-before-run"
    listed_paths = [f.path for f in backend.list_files(sandbox_id).files]
    assert "escape_link.txt" not in listed_paths
    _assert_lock_is_free(backend, sandbox_id)


def test_execution_cleanup_never_deletes_workspace_data(
    docker_client: docker.DockerClient,
    fast_settings: SandboxSettings,
):
    """Prove execution cleanup preserves workspace while cleanup_sandbox deletes it."""
    engine = EphemeralSandboxEngine(config=fast_settings, client=docker_client)
    backend = DockerSandboxBackend(config=fast_settings, engine=engine)
    sandbox_id = "cleanup-separation-check"

    backend.write_file(sandbox_id, "important.txt", "persistent-workspace-data")
    res = backend.execute(
        ExecutionRequest(code="print(open('important.txt').read())"),
        sandbox_id=sandbox_id,
    )
    assert res.status == ExecutionStatus.COMPLETED
    assert res.stdout.strip() == "persistent-workspace-data"

    # Execution container cleanup must only remove containers, never persistent workspace data
    backend.cleanup_execution_containers(sandbox_id)
    assert list_sandbox_containers(docker_client, config=fast_settings, all_states=True) == []
    assert backend.read_file(sandbox_id, "important.txt").content == "persistent-workspace-data"
    _assert_lock_is_free(backend, sandbox_id)

    # Full sandbox lifecycle cleanup removes both containers/volumes and persistent workspace
    backend.cleanup_sandbox(sandbox_id)
    assert not (fast_settings.WORKSPACE_DIR / sandbox_id).exists()
    _assert_lock_is_free(backend, sandbox_id)


def test_execution_time_workspace_storage_limit_enforced_by_kernel(
    docker_client: docker.DockerClient,
    fast_settings: SandboxSettings,
    tmp_path,
):
    """Verify kernel RLIMIT_FSIZE blocks excessive writes to /workspace during execution."""
    bounded_settings = fast_settings.model_copy(
        update={
            "WORKSPACE_DIR": tmp_path / "bounded_ws",
            "MAX_FILE_SIZE_BYTES": 65536,  # 64 KB per-file kernel ulimit
            "MAX_WORKSPACE_SIZE_BYTES": 131072,  # 128 KB total workspace quota
            "MAX_DECOMPRESSED_BYTES": 131072,
        }
    )
    engine = EphemeralSandboxEngine(config=bounded_settings, client=docker_client)
    backend = DockerSandboxBackend(config=bounded_settings, engine=engine)
    sandbox_id = "exec-disk-quota-enforced"

    backend.write_file(sandbox_id, "baseline.txt", "safe-baseline")

    # 1. Process attempting to write a 256 KB file (> 64 KB RLIMIT_FSIZE) inside /workspace
    #    while ignoring SIGXFSZ immediately receives EFBIG (errno 27) from the Linux kernel
    #    at execution time and cannot grow the file past 65536 bytes.
    code_efbig = """
import errno, os, signal
signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
try:
    with open("/workspace/oversized.bin", "wb") as f:
        f.write(b"X" * (256 * 1024))
    print("UNBOUNDED_WRITE_SUCCEEDED")
except OSError as exc:
    actual_size = os.path.getsize("/workspace/oversized.bin")
    print(f"KERNEL_EFBIG={exc.errno == errno.EFBIG} SIZE={actual_size}")
"""
    res_efbig = backend.execute(ExecutionRequest(code=code_efbig), sandbox_id=sandbox_id)
    assert res_efbig.status == ExecutionStatus.COMPLETED
    assert "KERNEL_EFBIG=True SIZE=65536" in res_efbig.stdout
    assert "UNBOUNDED_WRITE_SUCCEEDED" not in res_efbig.stdout
    _assert_lock_is_free(backend, sandbox_id)

    # 2. Multi-file write where each file is <= 64 KB (50 KB x 3 = 150 KB) but cumulative
    #    workspace output exceeds MAX_WORKSPACE_SIZE_BYTES (128 KB) fails synchronization,
    #    preserves the previous valid workspace, and cleans up the container + volume.
    code_multi = """
for i in range(3):
    with open(f"/workspace/chunk_{i}.bin", "wb") as f:
        f.write(b"Y" * (50 * 1024))
"""
    res_multi = backend.execute(ExecutionRequest(code=code_multi), sandbox_id=sandbox_id)
    assert res_multi.status == ExecutionStatus.ERROR
    assert res_multi.error_message is not None
    assert "quota limits" in res_multi.error_message
    assert backend.read_file(sandbox_id, "baseline.txt").content == "safe-baseline"
    listed = {f.path for f in backend.list_files(sandbox_id).files}
    assert "chunk_0.bin" not in listed
    assert list_sandbox_containers(docker_client, config=bounded_settings, all_states=True) == []
    _assert_lock_is_free(backend, sandbox_id)
