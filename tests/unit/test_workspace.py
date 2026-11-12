"""Unit and security tests for provider-neutral WorkspaceManager."""

import base64
import concurrent.futures
import errno
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.config import SandboxSettings
from app.core.exceptions import (
    FileQuotaExceededError,
    InvalidFileEncodingError,
    PathTraversalError,
    SandboxFileNotFoundError,
    WorkspaceCleanupError,
)
from app.sandbox.workspace import WorkspaceManager


@pytest.fixture(autouse=True)
def verify_no_container_leak():
    """Workspace unit tests do not interact with Docker."""
    yield


@pytest.fixture
def workspace_settings(tmp_path: Path) -> SandboxSettings:
    """Settings profile using a dedicated temporary workspace directory."""
    return SandboxSettings(
        WORKSPACE_DIR=tmp_path / "workspaces",
        MAX_FILE_SIZE_BYTES=1024,  # 1 KB for fast testing
        MAX_WORKSPACE_SIZE_BYTES=4096,  # 4 KB total quota
        MAX_FILE_COUNT=10,
        MAX_DIRECTORY_DEPTH=4,
        MAX_PATH_LENGTH=100,
        MAX_READ_RESPONSE_BYTES=2048,
        MAX_FILE_LIST_ENTRIES=50,
    )


@pytest.fixture
def manager(workspace_settings: SandboxSettings) -> WorkspaceManager:
    """WorkspaceManager instance bound to temporary test settings."""
    return WorkspaceManager(config=workspace_settings)


# ---------------------------------------------------------------------------
# Basic File Operations & Content
# ---------------------------------------------------------------------------


def test_write_and_read_utf8_file(manager: WorkspaceManager):
    sandbox_id = "test-ws-basic"
    info = manager.write_file(sandbox_id, "hello.txt", "Hello Sandbox!", encoding="utf-8")

    assert info.path == "hello.txt"
    assert info.size_bytes == 14
    assert info.is_directory is False
    assert info.modified_at is not None

    content = manager.read_file(sandbox_id, "hello.txt")
    assert content.path == "hello.txt"
    assert content.content == "Hello Sandbox!"
    assert content.encoding == "utf-8"
    assert content.size_bytes == 14


def test_write_and_read_base64_binary_file(manager: WorkspaceManager):
    sandbox_id = "test-ws-binary"
    raw_bytes = bytes([0x00, 0xFF, 0xFE, 0x42, 0x10])
    b64_str = base64.b64encode(raw_bytes).decode("ascii")

    info = manager.write_file(sandbox_id, "data.bin", b64_str, encoding="base64")
    assert info.size_bytes == 5

    content = manager.read_file(sandbox_id, "data.bin")
    assert content.encoding == "base64"
    assert base64.b64decode(content.content) == raw_bytes


def test_invalid_encoding_rejected(manager: WorkspaceManager):
    sandbox_id = "test-ws-invalid-enc"
    with pytest.raises(InvalidFileEncodingError):
        manager.write_file(sandbox_id, "file.txt", "abc", encoding="invalid_format")

    with pytest.raises(InvalidFileEncodingError):
        manager.write_file(sandbox_id, "file.bin", "not-valid-base64!", encoding="base64")


def test_overwrite_file_atomically(manager: WorkspaceManager):
    sandbox_id = "test-ws-overwrite"
    manager.write_file(sandbox_id, "state.txt", "Initial State")
    info1 = manager.read_file(sandbox_id, "state.txt")
    assert info1.content == "Initial State"

    manager.write_file(sandbox_id, "state.txt", "Updated State")
    info2 = manager.read_file(sandbox_id, "state.txt")
    assert info2.content == "Updated State"


def test_nested_directory_creation_and_traversal(manager: WorkspaceManager):
    sandbox_id = "test-ws-nested"
    info = manager.write_file(sandbox_id, "a/b/c/nested.txt", "Deep content")
    assert info.path == "a/b/c/nested.txt"

    content = manager.read_file(sandbox_id, "a/b/c/nested.txt")
    assert content.content == "Deep content"


def test_list_files_hierarchical(manager: WorkspaceManager):
    sandbox_id = "test-ws-list"
    manager.write_file(sandbox_id, "root.txt", "root")
    manager.write_file(sandbox_id, "docs/readme.txt", "readme")
    manager.write_file(sandbox_id, "docs/specs/spec.txt", "spec")

    res = manager.list_files(sandbox_id)
    assert res.total_count == 5  # root.txt, docs, docs/readme.txt, docs/specs, docs/specs/spec.txt
    paths = [f.path for f in res.files]
    assert "root.txt" in paths
    assert "docs" in paths
    assert "docs/readme.txt" in paths
    assert "docs/specs/spec.txt" in paths

    # Subdirectory listing
    res_sub = manager.list_files(sandbox_id, "docs")
    sub_paths = [f.path for f in res_sub.files]
    assert "docs/readme.txt" in sub_paths
    assert "docs/specs" in sub_paths
    assert "root.txt" not in sub_paths


def test_delete_file_and_empty_directory(manager: WorkspaceManager):
    sandbox_id = "test-ws-delete"
    manager.write_file(sandbox_id, "data/temp.txt", "temporary")

    assert manager.delete_file(sandbox_id, "data/temp.txt") is True
    with pytest.raises(SandboxFileNotFoundError):
        manager.read_file(sandbox_id, "data/temp.txt")

    # Empty directory deletion
    assert manager.delete_file(sandbox_id, "data") is True


def test_delete_non_empty_directory_rejected(manager: WorkspaceManager):
    sandbox_id = "test-ws-del-nonempty"
    manager.write_file(sandbox_id, "dir/file.txt", "content")

    with pytest.raises(PathTraversalError) as excinfo:
        manager.delete_file(sandbox_id, "dir")
    assert "not empty" in str(excinfo.value).lower()


def test_read_and_delete_missing_file_raises(manager: WorkspaceManager):
    sandbox_id = "test-ws-missing"
    with pytest.raises(SandboxFileNotFoundError):
        manager.read_file(sandbox_id, "nonexistent.txt")

    with pytest.raises(SandboxFileNotFoundError):
        manager.delete_file(sandbox_id, "nonexistent.txt")


def test_user_files_with_dot_tmp_staging_backup_prefixes_preserved(manager: WorkspaceManager):
    sandbox_id = "test-ws-dot-prefixes"
    manager.write_file(sandbox_id, ".tmp.config", "tmp-cfg")
    manager.write_file(sandbox_id, ".staging.env", "STAGE=1")
    manager.write_file(sandbox_id, ".backup.sql", "SELECT 1;")
    manager.write_file(sandbox_id, "nested/.tmp.inner", "inner-tmp")

    assert manager.read_file(sandbox_id, ".tmp.config").content == "tmp-cfg"
    assert manager.read_file(sandbox_id, ".staging.env").content == "STAGE=1"
    assert manager.read_file(sandbox_id, ".backup.sql").content == "SELECT 1;"
    assert manager.read_file(sandbox_id, "nested/.tmp.inner").content == "inner-tmp"

    listed_paths = {f.path for f in manager.list_files(sandbox_id).files}
    assert ".tmp.config" in listed_paths
    assert ".staging.env" in listed_paths
    assert ".backup.sql" in listed_paths
    assert "nested/.tmp.inner" in listed_paths


# ---------------------------------------------------------------------------
# Security & Path Traversal Rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_path",
    [
        "/etc/passwd",
        "/root/secret",
        "../escape.txt",
        "a/../../escape.txt",
        "subdir/../../../etc/shadow",
        "file\0null.txt",
        "C:windows/win.ini",
        "path\\with\\backslashes",
        "",
        "   ",
        "///",
    ],
)
def test_path_traversal_rejected(manager: WorkspaceManager, bad_path: str):
    sandbox_id = "test-ws-traversal"
    with pytest.raises(PathTraversalError):
        manager.write_file(sandbox_id, bad_path, "malicious")

    with pytest.raises(PathTraversalError):
        manager.read_file(sandbox_id, bad_path)


def test_max_directory_depth_rejected(manager: WorkspaceManager):
    sandbox_id = "test-ws-depth"
    # MAX_DIRECTORY_DEPTH is 4 in fixture
    too_deep = "1/2/3/4/5/file.txt"
    with pytest.raises(PathTraversalError) as excinfo:
        manager.write_file(sandbox_id, too_deep, "deep")
    assert "depth" in str(excinfo.value).lower()


def test_symlink_rejection_on_read(manager: WorkspaceManager):
    sandbox_id = "test-ws-symlink-read"
    ws_path = manager.get_workspace_path(sandbox_id)
    ws_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(ws_path, 0o700)

    # Malicious symlink created manually inside workspace pointing to /etc/hosts
    symlink_path = ws_path / "evil_symlink.txt"
    os.symlink("/etc/hosts", symlink_path)

    with pytest.raises(PathTraversalError) as excinfo:
        manager.read_file(sandbox_id, "evil_symlink.txt")
    assert "symlink" in str(excinfo.value).lower()


def test_intermediate_directory_symlink_rejection(manager: WorkspaceManager):
    sandbox_id = "test-ws-symlink-dir"
    ws_path = manager.get_workspace_path(sandbox_id)
    ws_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(ws_path, 0o700)

    # Symlink directory pointing to host /tmp
    symlink_dir = ws_path / "escape_dir"
    os.symlink(tempfile.gettempdir(), symlink_dir)

    with pytest.raises(PathTraversalError):
        manager.write_file(sandbox_id, "escape_dir/hacked.txt", "malicious write")

    with pytest.raises(PathTraversalError):
        manager.read_file(sandbox_id, "escape_dir/hacked.txt")


def test_special_file_rejection(manager: WorkspaceManager):
    sandbox_id = "test-ws-fifo"
    ws_path = manager.get_workspace_path(sandbox_id)
    ws_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(ws_path, 0o700)

    # Create a FIFO (named pipe) inside workspace
    fifo_path = ws_path / "test_pipe"
    try:
        os.mkfifo(str(fifo_path))
    except (AttributeError, OSError):
        pytest.skip("mkfifo not supported on this platform/filesystem")

    with pytest.raises(PathTraversalError) as excinfo:
        manager.read_file(sandbox_id, "test_pipe")
    assert "not a regular file" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# Quotas & Limits
# ---------------------------------------------------------------------------


def test_single_file_size_quota(manager: WorkspaceManager):
    sandbox_id = "test-ws-file-quota"
    # MAX_FILE_SIZE_BYTES is 1024
    oversized = "X" * 1025
    with pytest.raises(FileQuotaExceededError) as excinfo:
        manager.write_file(sandbox_id, "big.txt", oversized)
    assert "exceeds" in str(excinfo.value).lower()


def test_total_workspace_size_quota(manager: WorkspaceManager):
    sandbox_id = "test-ws-total-quota"
    # MAX_WORKSPACE_SIZE_BYTES is 4096 (4 KB)
    manager.write_file(sandbox_id, "f1.txt", "A" * 1000)
    manager.write_file(sandbox_id, "f2.txt", "B" * 1000)
    manager.write_file(sandbox_id, "f3.txt", "C" * 1000)
    manager.write_file(sandbox_id, "f4.txt", "D" * 1000)

    # 5th file exceeds 4096 bytes
    with pytest.raises(FileQuotaExceededError) as excinfo:
        manager.write_file(sandbox_id, "f5.txt", "E" * 500)
    assert "quota exceeded" in str(excinfo.value).lower()


def test_max_file_count_quota(manager: WorkspaceManager):
    sandbox_id = "test-ws-count-quota"
    # MAX_FILE_COUNT is 10
    for i in range(10):
        manager.write_file(sandbox_id, f"file_{i}.txt", f"data {i}")

    # 11th file exceeds count limit
    with pytest.raises(FileQuotaExceededError) as excinfo:
        manager.write_file(sandbox_id, "file_11.txt", "overflow")
    assert "file count" in str(excinfo.value).lower()


def test_read_oversized_file_rejected(manager: WorkspaceManager):
    sandbox_id = "test-ws-read-limit"
    # Artificially create a file on disk that exceeds MAX_READ_RESPONSE_BYTES
    ws_path = manager.get_workspace_path(sandbox_id)
    ws_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(ws_path, 0o700)
    large_file = ws_path / "huge.txt"
    large_file.write_bytes(b"Z" * (manager.config.MAX_READ_RESPONSE_BYTES + 10))

    with pytest.raises(FileQuotaExceededError) as excinfo:
        manager.read_file(sandbox_id, "huge.txt")
    assert "read limit" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# Lifecycle, Cleanup, Locking, Durability & Short-Write Handling
# ---------------------------------------------------------------------------


def test_authoritative_delete_workspace_preserves_lock_inode(manager: WorkspaceManager):
    sandbox_id = "test-ws-cleanup"
    manager.write_file(sandbox_id, "sub/file.txt", "data")
    ws_path = manager.get_workspace_path(sandbox_id)
    lock_path = manager.get_lock_path(sandbox_id)

    assert ws_path.exists() is True
    assert lock_path.exists() is True
    initial_lock_ino = lock_path.stat().st_ino

    manager.delete_workspace(sandbox_id)

    assert ws_path.exists() is False
    # Lock file is intentionally preserved as a 0-byte inode anchor to prevent split-brain
    assert lock_path.exists() is True
    assert lock_path.stat().st_ino == initial_lock_ino

    # Repeated deletion is idempotent
    manager.delete_workspace(sandbox_id)


def test_delete_workspace_failure_raises_workspace_cleanup_error(manager: WorkspaceManager):
    sandbox_id = "test-ws-cleanup-fail"
    manager.write_file(sandbox_id, "test.txt", "data")

    with patch("os.rmdir", side_effect=OSError("Disk hardware fault")):
        with pytest.raises(WorkspaceCleanupError) as excinfo:
            manager.delete_workspace(sandbox_id)
        assert "failed to delete workspace" in str(excinfo.value).lower()


def test_sandbox_advisory_locking_coherence(manager: WorkspaceManager):
    sandbox_id = "test-ws-flock"
    manager.write_file(sandbox_id, "data.txt", "shared")

    # Verify nested/re-entrant shared locks succeed
    with manager.sandbox_lock(sandbox_id, exclusive=False):
        content = manager.read_file(sandbox_id, "data.txt")
        assert content.content == "shared"


def test_recover_interrupted_commit_requires_exclusive_lock(manager: WorkspaceManager):
    sandbox_id = "test-ws-rec-lock"
    # Calling without any lock must fail
    with pytest.raises(RuntimeError, match="exclusive sandbox_lock"):
        manager.recover_interrupted_commit(sandbox_id)

    # Calling while holding only a shared lock must fail
    with manager.sandbox_lock(sandbox_id, exclusive=False):
        with pytest.raises(RuntimeError, match="exclusive sandbox_lock"):
            manager.recover_interrupted_commit(sandbox_id)


def test_read_and_list_never_mutate_or_create_dirs_under_shared_lock(manager: WorkspaceManager):
    sandbox_id = "test-ws-pure-read"
    ws_path = manager.get_workspace_path(sandbox_id)
    assert not ws_path.exists()

    # list_files on non-existent workspace returns empty list without creating ws_path
    listing = manager.list_files(sandbox_id)
    assert listing.total_count == 0
    assert not ws_path.exists()

    # read_file on non-existent workspace raises SandboxFileNotFoundError without creating ws_path
    with pytest.raises(SandboxFileNotFoundError):
        manager.read_file(sandbox_id, "missing.txt")
    assert not ws_path.exists()

    # If caller holds a shared lock and crash artifacts appear, _ensure_recovered refuses
    # to run recovery under LOCK_SH.
    manager.write_file(sandbox_id, "ok.txt", "safe")
    staging_artifact = manager.base_dir / f".staging.{sandbox_id}.deadbeef"
    staging_artifact.mkdir(mode=0o700)
    try:
        with manager.sandbox_lock(sandbox_id, exclusive=False):
            with pytest.raises(RuntimeError, match="shared lock"):
                manager.read_file(sandbox_id, "ok.txt")
    finally:
        # Outside shared lock, read_file recovers under exclusive lock, then reads under shared
        assert manager.read_file(sandbox_id, "ok.txt").content == "safe"
        assert not staging_artifact.exists()


def test_concurrent_readers_and_recovery(manager: WorkspaceManager):
    sandbox_id = "test-ws-concurrent-readers"
    manager.write_file(sandbox_id, "shared.txt", "consistent-payload")

    # Simulate an interrupted commit (Crash Point 2: ws_path moved to backup, staging left over)
    ws_path = manager.get_workspace_path(sandbox_id)
    backup_path = manager.base_dir / f".backup.{sandbox_id}.crash2"
    staging_path = manager.base_dir / f".staging.{sandbox_id}.crash2"
    os.rename(ws_path, backup_path)
    staging_path.mkdir(mode=0o700)

    def _reader_worker(_idx: int) -> str:
        res = manager.read_file(sandbox_id, "shared.txt")
        return res.content

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_reader_worker, range(16)))

    assert all(r == "consistent-payload" for r in results)
    assert ws_path.exists()
    assert not backup_path.exists()
    assert not staging_path.exists()


def test_lock_inode_reacquired_when_unlinked_during_acquisition(
    manager: WorkspaceManager,
    monkeypatch: pytest.MonkeyPatch,
):
    sandbox_id = "test-ws-inode-race"
    lock_path = manager.get_lock_path(sandbox_id)

    real_flock = os.sys.modules["fcntl"].flock
    unlinked_once = False

    def race_simulating_flock(fd: int, op: int) -> None:
        nonlocal unlinked_once
        real_flock(fd, op)
        # Simulate another process unlinking the lock file right as flock returns on attempt 1
        if not unlinked_once and op != os.sys.modules["fcntl"].LOCK_UN:
            unlinked_once = True
            lock_path.unlink(missing_ok=True)

    monkeypatch.setattr("fcntl.flock", race_simulating_flock)

    with manager.sandbox_lock(sandbox_id, exclusive=True):
        assert unlinked_once is True
        # sandbox_lock detected st_nlink == 0 / missing path and re-created & locked the live inode
        assert lock_path.exists() is True


def test_write_file_fsync_ordering(
    manager: WorkspaceManager,
    monkeypatch: pytest.MonkeyPatch,
):
    sandbox_id = "test-ws-fsync-order"
    events: list[str] = []

    real_write = os.write
    real_fsync = os.fsync
    real_replace = os.replace

    def spy_write(fd: int, data: bytes) -> int:
        events.append("write_tmp")
        return real_write(fd, data)

    def spy_fsync(fd: int) -> None:
        st = os.fstat(fd)
        if os.path.samestat(st, os.stat(manager.base_dir)):
            events.append("fsync_base_dir")
        elif os.stat(fd).st_mode & 0o040000:
            events.append("fsync_dir")
        else:
            events.append("fsync_file")
        real_fsync(fd)

    def spy_replace(src, dst, *args, **kwargs):
        events.append("replace_atomic")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "write", spy_write)
    monkeypatch.setattr(os, "fsync", spy_fsync)
    monkeypatch.setattr(os, "replace", spy_replace)

    manager.write_file(sandbox_id, "durable.txt", "durable content")

    # Verify ordering: write_tmp -> fsync_file -> replace_atomic -> fsync_dir
    write_idx = events.index("write_tmp")
    fsync_file_idx = events.index("fsync_file")
    replace_idx = events.index("replace_atomic")
    fsync_dir_after_replace = [
        i for i, e in enumerate(events) if e == "fsync_dir" and i > replace_idx
    ]

    assert write_idx < fsync_file_idx < replace_idx
    assert len(fsync_dir_after_replace) >= 1


def test_write_file_handles_partial_and_interrupted_writes(
    manager: WorkspaceManager,
    monkeypatch: pytest.MonkeyPatch,
):
    sandbox_id = "test-ws-short-write"
    payload = "0123456789abcdefghijklmnopqrstuvwxyz"
    real_write = os.write
    call_count = 0

    def partial_and_eintr_write(fd: int, data: bytes | memoryview) -> int:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise InterruptedError("Simulated signal interruption")
        if call_count == 4:
            raise OSError(errno.EINTR, "Simulated EINTR")
        # Write at most 4 bytes per syscall
        view = memoryview(data)
        return real_write(fd, view[:4])

    monkeypatch.setattr(os, "write", partial_and_eintr_write)
    manager.write_file(sandbox_id, "chunked.txt", payload)
    monkeypatch.undo()

    assert call_count > 8
    assert manager.read_file(sandbox_id, "chunked.txt").content == payload


def test_write_file_zero_byte_write_raises_eio(
    manager: WorkspaceManager,
    monkeypatch: pytest.MonkeyPatch,
):
    sandbox_id = "test-ws-zero-write"
    monkeypatch.setattr(os, "write", lambda _fd, _data: 0)

    with pytest.raises(OSError) as excinfo:
        manager.write_file(sandbox_id, "broken.txt", "data")
    assert excinfo.value.errno == errno.EIO


def test_workspace_permissions_are_owner_only(manager: WorkspaceManager):
    sandbox_id = "test-ws-perms"
    manager.write_file(sandbox_id, "secret.txt", "top-secret")
    ws_path = manager.get_workspace_path(sandbox_id)
    lock_path = manager.get_lock_path(sandbox_id)

    st = os.stat(ws_path)
    # Check permissions are strictly 0700 (owner only)
    assert (st.st_mode & 0o077) == 0

    lock_st = os.stat(lock_path)
    # Check lock file permissions are strictly 0600 (owner only)
    assert (lock_st.st_mode & 0o077) == 0


def test_symlinked_workspace_root_rejected(manager: WorkspaceManager):
    sandbox_id = "test-ws-root-symlink"
    ws_path = manager.get_workspace_path(sandbox_id)
    os.symlink(tempfile.gettempdir(), ws_path)

    with pytest.raises(PathTraversalError):
        manager.write_file(sandbox_id, "escape.txt", "blocked")


def test_symlinked_lock_file_rejected(manager: WorkspaceManager):
    sandbox_id = "test-ws-lock-symlink"
    lock_path = manager.get_lock_path(sandbox_id)
    os.symlink("/etc/hosts", lock_path)

    with pytest.raises(PathTraversalError):
        manager.write_file(sandbox_id, "file.txt", "blocked")


@pytest.mark.parametrize("bad_sandbox_id", ["", "  ", "../escape", "a/b", ".hidden", "id\0null"])
def test_invalid_sandbox_id_rejected(manager: WorkspaceManager, bad_sandbox_id: str):
    with pytest.raises(PathTraversalError):
        manager.write_file(bad_sandbox_id, "file.txt", "blocked")


def test_create_directory_and_conflict(manager: WorkspaceManager):
    sandbox_id = "test-ws-mkdir"
    assert manager.create_directory(sandbox_id, "src/pkg/sub") is True
    # Idempotent when directory already exists
    assert manager.create_directory(sandbox_id, "src/pkg/sub") is True

    manager.write_file(sandbox_id, "src/pkg/file.txt", "code")
    with pytest.raises(PathTraversalError):
        manager.create_directory(sandbox_id, "src/pkg/file.txt")


# ---------------------------------------------------------------------------
# Audit 2: Quota Accounting Fail-Closed Tests
# ---------------------------------------------------------------------------


def test_quota_accounting_fails_closed_on_symlinks_hardlinks_and_special_files(
    manager: WorkspaceManager,
):
    # 1. Symlink present inside workspace must fail closed during quota accounting on write_file
    sym_id = "test-quota-symlink"
    manager.write_file(sym_id, "existing.txt", "ok")
    ws_sym = manager.get_workspace_path(sym_id)
    os.symlink("/etc/hosts", ws_sym / "dangling_or_host_link")
    with pytest.raises(PathTraversalError, match="Symlink rejected during workspace quota"):
        manager.write_file(sym_id, "another.txt", "blocked")

    # 2. Hard link present inside workspace must fail closed during quota accounting
    hl_id = "test-quota-hardlink"
    manager.write_file(hl_id, "orig.txt", "ok")
    ws_hl = manager.get_workspace_path(hl_id)
    os.link(ws_hl / "orig.txt", ws_hl / "dup.txt")
    with pytest.raises(PathTraversalError, match="Hard link rejected during workspace quota"):
        manager.write_file(hl_id, "another.txt", "blocked")

    # 3. Special file (FIFO) present inside workspace must fail closed during quota accounting
    fifo_id = "test-quota-fifo"
    manager.write_file(fifo_id, "orig.txt", "ok")
    ws_fifo = manager.get_workspace_path(fifo_id)
    try:
        os.mkfifo(str(ws_fifo / "pipe_entry"))
    except (AttributeError, OSError):
        pytest.skip("mkfifo not supported on this platform/filesystem")
    with pytest.raises(PathTraversalError, match="Special file rejected during workspace quota"):
        manager.write_file(fifo_id, "another.txt", "blocked")


def test_quota_accounting_fails_closed_on_unreadable_entries_and_fs_errors(
    manager: WorkspaceManager,
    monkeypatch: pytest.MonkeyPatch,
):
    sandbox_id = "test-quota-fs-err"
    manager.write_file(sandbox_id, "sub/hidden_usage.txt", "A" * 900)
    sub_dir = manager.get_workspace_path(sandbox_id) / "sub"

    # 1. Unreadable subdirectory (mode 0000 when running as non-root) must fail closed
    if os.getuid() != 0:
        os.chmod(sub_dir, 0o000)
        try:
            with pytest.raises(WorkspaceCleanupError, match="quota accounting"):
                manager.write_file(sandbox_id, "new.txt", "B" * 500)
        finally:
            os.chmod(sub_dir, 0o700)

    # 2. Simulated scandir I/O error during _calculate_workspace_stats must fail closed
    ws_stat = os.stat(manager.get_workspace_path(sandbox_id))
    real_scandir = os.scandir

    def failing_scandir(path):
        if isinstance(path, int) and os.path.samestat(os.fstat(path), ws_stat):
            raise OSError(errno.EIO, "Simulated disk I/O failure during scandir")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", failing_scandir)
    with pytest.raises(WorkspaceCleanupError, match="quota accounting"):
        manager.write_file(sandbox_id, "new.txt", "B" * 100)
    monkeypatch.undo()


# ---------------------------------------------------------------------------
# Audit 3: Locking & Recovery Concurrency Interleaving Tests
# ---------------------------------------------------------------------------


def test_reader_detecting_crash_artifact_after_acquiring_shared_lock_releases_before_recovery(
    manager: WorkspaceManager,
    monkeypatch: pytest.MonkeyPatch,
):
    sandbox_id = "test-lock-recheck-interleaving"
    manager.write_file(sandbox_id, "doc.txt", "recovered-generation")

    ws_path = manager.get_workspace_path(sandbox_id)
    backup_path = manager.base_dir / f".backup.{sandbox_id}.interleaved"

    real_needs = manager._needs_commit_recovery
    call_idx = 0

    def simulated_interleaving_needs(sid: str) -> bool:
        nonlocal call_idx
        call_idx += 1
        # Call 1 (before acquiring LOCK_SH): return False as if writer hasn't crashed yet.
        # Right before Call 2 (inside LOCK_SH), simulate that a writer had moved ws_path -> backup
        # and crashed right before our LOCK_SH acquisition completed.
        if call_idx == 1:
            return False
        if call_idx == 2 and ws_path.exists():
            os.rename(ws_path, backup_path)
            return True
        return real_needs(sid)

    monkeypatch.setattr(manager, "_needs_commit_recovery", simulated_interleaving_needs)

    # Reader must release LOCK_SH, acquire LOCK_EX, recover backup_path -> ws_path,
    # re-acquire LOCK_SH, and return the valid file content without deadlock.
    content = manager.read_file(sandbox_id, "doc.txt")
    assert content.content == "recovered-generation"
    assert ws_path.exists()
    assert not backup_path.exists()
    assert call_idx >= 3


def test_concurrent_recovery_attempts_are_idempotent_and_ignore_symlink_backups(
    manager: WorkspaceManager,
    tmp_path: Path,
):
    sandbox_id = "test-concurrent-recovery-symlink-backup"
    manager.write_file(sandbox_id, "safe.txt", "authoritative-backup-data")

    ws_path = manager.get_workspace_path(sandbox_id)
    valid_backup = manager.base_dir / f".backup.{sandbox_id}.valid"
    os.rename(ws_path, valid_backup)

    # Plant a newer symlink with a .backup prefix pointing to an external directory;
    # recovery must never restore a symlink as the active workspace root.
    outside_dir = tmp_path / "external_trap"
    outside_dir.mkdir(mode=0o700)
    (outside_dir / "safe.txt").write_text("poisoned-external-data")
    symlink_backup = manager.base_dir / f".backup.{sandbox_id}.zz_symlink"
    os.symlink(outside_dir, symlink_backup)

    def _worker(idx: int) -> str:
        if idx % 3 == 0:
            manager.write_file(sandbox_id, f"extra_{idx}.txt", f"v{idx}")
        return manager.read_file(sandbox_id, "safe.txt").content

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(_worker, range(12)))

    assert all(r == "authoritative-backup-data" for r in results)
    assert ws_path.exists() and not ws_path.is_symlink()
    assert not valid_backup.exists()
    assert not symlink_backup.exists()
    # External directory and its contents must remain untouched
    assert (outside_dir / "safe.txt").read_text() == "poisoned-external-data"


# ---------------------------------------------------------------------------
# Audit 4: Descriptor-Relative Workspace Deletion Safety Tests
# ---------------------------------------------------------------------------


def test_delete_workspace_does_not_follow_symlinks_outside_sandbox(
    manager: WorkspaceManager,
    tmp_path: Path,
):
    sandbox_id = "test-safe-delete-symlinks"
    manager.write_file(sandbox_id, "nested/inside.txt", "sandbox-data")

    # External host target that must NEVER be deleted
    external_dir = tmp_path / "host_protected_dir"
    external_dir.mkdir(mode=0o700)
    canary_file = external_dir / "canary.txt"
    canary_file.write_text("must-survive-cleanup")

    ws_path = manager.get_workspace_path(sandbox_id)
    os.symlink(external_dir, ws_path / "nested" / "symlink_to_host_dir")
    os.symlink(canary_file, ws_path / "symlink_to_host_file")

    # Also plant symlinks inside staging and backup directories
    staging_dir = manager.base_dir / f".staging.{sandbox_id}.s1"
    staging_dir.mkdir(mode=0o700)
    os.symlink(external_dir, staging_dir / "staging_host_link")

    backup_dir = manager.base_dir / f".backup.{sandbox_id}.b1"
    backup_dir.mkdir(mode=0o700)
    os.symlink(canary_file, backup_dir / "backup_file_link")

    manager.delete_workspace(sandbox_id)

    assert not ws_path.exists()
    assert not staging_dir.exists()
    assert not backup_dir.exists()
    # External directory and canary file must be completely intact
    assert external_dir.exists()
    assert canary_file.exists()
    assert canary_file.read_text() == "must-survive-cleanup"


def test_delete_workspace_detects_directory_replacement_race_and_remains_retryable(
    manager: WorkspaceManager,
    monkeypatch: pytest.MonkeyPatch,
):
    sandbox_id = "test-delete-dir-race"
    manager.write_file(sandbox_id, "sub/file.txt", "content")
    ws_path = manager.get_workspace_path(sandbox_id)

    real_fstat = os.fstat
    tampered_once = False

    class _FakeStat:
        def __init__(self, orig: os.stat_result) -> None:
            self.st_mode = orig.st_mode
            self.st_ino = orig.st_ino + 999999
            self.st_dev = orig.st_dev
            self.st_uid = orig.st_uid
            self.st_size = orig.st_size
            self.st_mtime = orig.st_mtime
            self.st_mtime_ns = orig.st_mtime_ns
            self.st_nlink = orig.st_nlink

    sub_ino = (ws_path / "sub").stat().st_ino

    def race_simulating_fstat(fd: int):
        nonlocal tampered_once
        orig = real_fstat(fd)
        if not tampered_once and orig.st_ino == sub_ino:
            tampered_once = True
            return _FakeStat(orig)
        return orig

    monkeypatch.setattr(os, "fstat", race_simulating_fstat)

    # First attempt detects inode mismatch on 'sub' and raises WorkspaceCleanupError
    with pytest.raises(WorkspaceCleanupError, match="Directory replacement race"):
        manager.delete_workspace(sandbox_id)

    assert tampered_once is True
    assert ws_path.exists()

    # Retry succeeds cleanly once the race condition is gone
    manager.delete_workspace(sandbox_id)
    assert not ws_path.exists()
