"""Secure, provider-neutral sandbox workspace management.

Enforces descriptor-relative filesystem operations, strict O_NOFOLLOW
symlink rejection, two-tier cross-process locking via flock, bounded quotas,
atomic file writes with directory-entry durability, and authoritative
lifecycle cleanup.
"""

import base64
import contextlib
import errno
import fcntl
import logging
import os
import stat
import threading
import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import SandboxSettings, settings
from app.core.exceptions import (
    FileQuotaExceededError,
    InvalidFileEncodingError,
    PathTraversalError,
    SandboxFileNotFoundError,
    WorkspaceCleanupError,
    WorkspaceRollbackError,
)
from app.sandbox.schemas import FileContent, FileInfo, FileListResponse

logger = logging.getLogger(__name__)


def write_all_to_fd(fd: int, data: bytes | bytearray | memoryview) -> int:
    """Write the entire buffer to file descriptor `fd`, looping over short writes and EINTR.

    Raises OSError(errno.EIO) if `os.write` returns 0 bytes before the buffer is exhausted.
    """
    view = memoryview(data)
    total_len = len(view)
    total_written = 0
    while total_written < total_len:
        try:
            written = os.write(fd, view[total_written:])
        except InterruptedError:
            continue
        except OSError as exc:
            if exc.errno == errno.EINTR:
                continue
            raise
        if written <= 0:
            raise OSError(
                errno.EIO,
                f"Short write to file descriptor: os.write returned {written}",
            )
        total_written += written
    return total_written


def fsync_directory_fd(dir_fd: int) -> None:
    """Flush directory entries referenced by `dir_fd` to stable storage.

    Platform behavior:
    - Linux (ext4, xfs, btrfs, tmpfs): `fsync(2)` on an `O_RDONLY | O_DIRECTORY`
      descriptor flushes modified directory entries and journal metadata.
    - macOS ARM64 (APFS): `fsync(2)` on an `O_RDONLY | O_DIRECTORY` descriptor is
      supported by XNU/APFS and flushes directory catalog records to the container.
    - Specialized virtual/network filesystems that reject directory `fsync` with
      `EINVAL`, `EBADF`, or `ENOTSUP` are logged at debug level; real I/O failures
      (`EIO`, `ENOSPC`, `EROFS`, etc.) propagate as `OSError`.
    """
    while True:
        try:
            os.fsync(dir_fd)
            return
        except InterruptedError:
            continue
        except OSError as exc:
            if exc.errno == errno.EINTR:
                continue
            if exc.errno in (errno.EINVAL, errno.EBADF, errno.ENOTSUP, errno.EOPNOTSUPP):
                logger.debug("Directory fsync not supported by underlying filesystem: %s", exc)
                return
            raise


class WorkspaceManager:
    """Manages isolated disk workspaces for logical sandboxes without container runtime ties.

    Internal transaction artifacts are stored outside `<base_dir>/<sandbox_id>`:
    - Advisory lock anchors: `<base_dir>/.locks/<sandbox_id>.lock`
    - Atomic file-write temp files: `<base_dir>/.tmp/.tmp.<sandbox_id>.<uuid>`
    - Archive import staging trees: `<base_dir>/.staging.<sandbox_id>.<uuid>`
    - Atomic commit backup trees: `<base_dir>/.backup.<sandbox_id>.<uuid>`

    Because `_validate_sandbox_id` forbids leading dots, no sandbox ID can collide with
    these internal directories, and legitimate user files inside `<base_dir>/<sandbox_id>`
    whose names begin with `.tmp.`, `.staging.`, or `.backup.` are preserved intact.
    """

    def __init__(self, config: SandboxSettings = settings) -> None:
        self.config = config
        self.base_dir = Path(config.WORKSPACE_DIR).resolve()
        self.locks_dir = self.base_dir / ".locks"
        self.tmp_dir = self.base_dir / ".tmp"
        self._thread_local = threading.local()
        self._ensure_infrastructure_directories()

    def _ensure_infrastructure_directories(self) -> None:
        """Create base storage, locks, and temp directories with restricted owner-only access."""
        for directory in (self.base_dir, self.locks_dir, self.tmp_dir):
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            try:
                os.chmod(directory, 0o700)
            except OSError as exc:
                logger.warning("Could not set strict 0700 permissions on %s: %s", directory, exc)

    def _validate_sandbox_id(self, sandbox_id: str) -> str:
        """Validate sandbox_id to prevent escaping base_dir or colliding with dot-entries."""
        if (
            not sandbox_id
            or not sandbox_id.strip()
            or "\0" in sandbox_id
            or "/" in sandbox_id
            or "\\" in sandbox_id
            or sandbox_id in (".", "..")
            or sandbox_id.startswith(".")
            or len(sandbox_id) > 128
        ):
            raise PathTraversalError("Invalid sandbox identifier")
        return sandbox_id

    def get_workspace_path(self, sandbox_id: str) -> Path:
        """Return the canonical filesystem path for a sandbox workspace directory."""
        self._validate_sandbox_id(sandbox_id)
        return self.base_dir / sandbox_id

    def get_lock_path(self, sandbox_id: str) -> Path:
        """Return the filesystem path for a sandbox synchronization advisory lock."""
        self._validate_sandbox_id(sandbox_id)
        return self.locks_dir / f"{sandbox_id}.lock"

    def _get_held_locks(self) -> dict[str, bool]:
        held: dict[str, bool] | None = getattr(self._thread_local, "held_locks", None)
        if held is None:
            held = {}
            self._thread_local.held_locks = held
        return held

    def _is_exclusive_lock_held(self, sandbox_id: str) -> bool:
        return self._get_held_locks().get(sandbox_id) is True

    @contextlib.contextmanager
    def sandbox_lock(
        self,
        sandbox_id: str,
        exclusive: bool = True,
    ) -> Generator[None, None, None]:
        """Advisory file locking ensuring safe serialization across OS processes and threads.

        Lock-File Lifetime and Split-Brain Prevention Strategy:
        - Each sandbox has a dedicated 0-byte lock file at `.locks/<sandbox_id>.lock`.
        - Lock files are NEVER unlinked during `delete_workspace()` or normal lifecycle
          operations while another process or thread could be waiting on the open inode.
          Unlinking an active `flock` file causes subsequent openers with `O_CREAT` to
          allocate a new inode while existing waiters hold locks on the unlinked inode
          (split-brain locking).
        - As defense-in-depth against external maintenance unlinks, after `fcntl.flock()`
          returns, we verify that `fstat(lock_fd)` still matches `lstat(lock_file)`
          (`st_nlink >= 1`, `st_ino`, and `st_dev`). If the path was replaced or unlinked
          while waiting, the stale descriptor is closed and acquisition retries on the live
          directory entry.
        """
        lock_file = self.get_lock_path(sandbox_id)
        held = self._get_held_locks()

        if sandbox_id in held:
            current_is_exclusive = held[sandbox_id]
            if current_is_exclusive or not exclusive:
                yield
                return
            raise RuntimeError(
                f"Cannot upgrade shared sandbox_lock to exclusive in-place for sandbox {sandbox_id}"
            )

        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        lock_fd: int | None = None

        for _attempt in range(8):
            try:
                fd = os.open(
                    str(lock_file),
                    os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                )
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.EEXIST):
                    raise PathTraversalError("Lock file symlink rejected") from exc
                raise

            try:
                st = os.fstat(fd)
                if not stat.S_ISREG(st.st_mode):
                    raise PathTraversalError("Lock file is not a regular file")
                if st.st_uid != os.getuid():
                    raise PathTraversalError("Lock file ownership mismatch")
                if (st.st_mode & 0o077) != 0:
                    os.fchmod(fd, 0o600)
                    st = os.fstat(fd)
                    if (st.st_mode & 0o077) != 0:
                        raise PathTraversalError("Lock file permissions are insecure")

                fcntl.flock(fd, operation)

                # Verify that the locked descriptor still matches the live directory entry
                # to prevent lock-inode replacement / split-brain locking.
                post_fd_st = os.fstat(fd)
                try:
                    path_st = os.stat(str(lock_file), follow_symlinks=False)
                except FileNotFoundError:
                    path_st = None

                if (
                    post_fd_st.st_nlink < 1
                    or path_st is None
                    or post_fd_st.st_ino != path_st.st_ino
                    or post_fd_st.st_dev != path_st.st_dev
                ):
                    with contextlib.suppress(OSError):
                        fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)
                    continue

                lock_fd = fd
                break
            except Exception:
                os.close(fd)
                raise

        if lock_fd is None:
            raise WorkspaceCleanupError(
                f"Unable to acquire stable lock inode for sandbox {sandbox_id}"
            )

        try:
            held[sandbox_id] = exclusive
            try:
                yield
            finally:
                held.pop(sandbox_id, None)
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)

    def _open_base_dir(self) -> int:
        """Open and validate `self.base_dir` as a directory descriptor with O_NOFOLLOW."""
        try:
            base_fd = os.open(
                str(self.base_dir),
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                raise PathTraversalError(
                    "Workspace base root is a symlink or non-directory"
                ) from exc
            raise

        st = os.fstat(base_fd)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
            os.close(base_fd)
            raise PathTraversalError("Workspace base root validation failed")
        return base_fd

    def _fsync_base_dir(self) -> None:
        """Open `self.base_dir` safely and fsync its directory entries."""
        base_fd = self._open_base_dir()
        try:
            fsync_directory_fd(base_fd)
        finally:
            os.close(base_fd)

    def _open_tmp_dir(self) -> int:
        """Open and validate `<base_dir>/.tmp` as a directory descriptor for atomic file staging."""
        if not self.tmp_dir.exists() and not self.tmp_dir.is_symlink():
            self.tmp_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            with contextlib.suppress(OSError):
                os.chmod(self.tmp_dir, 0o700)

        try:
            tmp_dir_fd = os.open(
                str(self.tmp_dir),
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                raise PathTraversalError(
                    "Workspace temp root is a symlink or non-directory"
                ) from exc
            raise

        st = os.fstat(tmp_dir_fd)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
            os.close(tmp_dir_fd)
            raise PathTraversalError("Workspace temp root validation failed")
        if (st.st_mode & 0o077) != 0:
            try:
                os.fchmod(tmp_dir_fd, 0o700)
                st = os.fstat(tmp_dir_fd)
            except OSError:
                pass
            if (st.st_mode & 0o077) != 0:
                os.close(tmp_dir_fd)
                raise PathTraversalError("Workspace temp root permissions are insecure")

        return tmp_dir_fd

    def _needs_commit_recovery(self, sandbox_id: str) -> bool:
        """Return True if crash artifacts (`.backup.`, `.staging.`, `.tmp.`) exist."""
        self._validate_sandbox_id(sandbox_id)
        backup_prefix = f".backup.{sandbox_id}."
        staging_prefix = f".staging.{sandbox_id}."
        tmp_prefix = f".tmp.{sandbox_id}."

        try:
            with os.scandir(self.base_dir) as it:
                for entry in it:
                    if entry.name.startswith((backup_prefix, staging_prefix)):
                        return True
            if self.tmp_dir.exists() and not self.tmp_dir.is_symlink():
                with os.scandir(self.tmp_dir) as it:
                    for entry in it:
                        if entry.name.startswith(tmp_prefix):
                            return True
        except OSError:
            return True
        return False

    def _ensure_recovered(self, sandbox_id: str) -> None:
        """Ensure any interrupted commit or write artifacts are recovered under an exclusive lock.

        Read operations call this (or `_shared_lock_with_recovery`) before acquiring a shared lock
        so that recovery NEVER runs under a shared lock (`LOCK_SH`).
        """
        self._validate_sandbox_id(sandbox_id)
        held = self._get_held_locks()
        if sandbox_id in held:
            if held[sandbox_id] is True:
                self.recover_interrupted_commit(sandbox_id)
                return
            # Currently holding a shared lock; recovery is forbidden under LOCK_SH.
            if self._needs_commit_recovery(sandbox_id):
                raise RuntimeError(
                    f"Cannot execute commit recovery for {sandbox_id} while holding a shared lock"
                )
            return

        if self._needs_commit_recovery(sandbox_id):
            with self.sandbox_lock(sandbox_id, exclusive=True):
                self.recover_interrupted_commit(sandbox_id)

    @contextlib.contextmanager
    def _shared_lock_with_recovery(self, sandbox_id: str) -> Generator[None, None, None]:
        """Acquire a shared lock while guaranteeing recovery has completed under an exclusive lock.

        Prevents both:
        1. In-place shared-to-exclusive lock upgrade deadlocks (by releasing `LOCK_SH`
           before acquiring `LOCK_EX` whenever crash artifacts are detected).
        2. Observing an unrecovered crash state if a writer crashed in the window
           immediately before `LOCK_SH` was acquired (by re-checking `_needs_commit_recovery`
           after `LOCK_SH` is held, when no `LOCK_EX` writer can be in flight).
        """
        self._validate_sandbox_id(sandbox_id)
        held = self._get_held_locks()
        if sandbox_id in held:
            if held[sandbox_id] is True:
                self.recover_interrupted_commit(sandbox_id)
                yield
                return
            if self._needs_commit_recovery(sandbox_id):
                raise RuntimeError(
                    f"Cannot execute commit recovery for {sandbox_id} while holding a shared lock"
                )
            yield
            return

        for _attempt in range(8):
            if self._needs_commit_recovery(sandbox_id):
                with self.sandbox_lock(sandbox_id, exclusive=True):
                    self.recover_interrupted_commit(sandbox_id)

            with self.sandbox_lock(sandbox_id, exclusive=False):
                if not self._needs_commit_recovery(sandbox_id):
                    yield
                    return
                # A writer crashed immediately before LOCK_SH was acquired.
                # Exit the LOCK_SH block first (preventing lock-upgrade deadlock)
                # and loop to recover under LOCK_EX.

        raise WorkspaceCleanupError(
            f"Unable to establish recovered shared lock state for sandbox {sandbox_id}"
        )

    def recover_interrupted_commit(self, sandbox_id: str) -> None:
        """Recover from an interrupted atomic staging-directory swap or atomic write.

        MUST be called while holding the exclusive sandbox lock (`LOCK_EX`).
        Raises `RuntimeError` if called without an active exclusive lock for `sandbox_id`.
        Raises `WorkspaceCleanupError` if backup restoration or artifact cleanup fails.
        """
        self._validate_sandbox_id(sandbox_id)
        if not self._is_exclusive_lock_held(sandbox_id):
            raise RuntimeError(
                f"recover_interrupted_commit requires an exclusive sandbox_lock for {sandbox_id}"
            )

        ws_path = self.get_workspace_path(sandbox_id)
        backup_prefix = f".backup.{sandbox_id}."
        staging_prefix = f".staging.{sandbox_id}."
        tmp_prefix = f".tmp.{sandbox_id}."

        try:
            all_backup_entries = [
                p for p in self.base_dir.iterdir() if p.name.startswith(backup_prefix)
            ]
            valid_backup_dirs = sorted(
                [p for p in all_backup_entries if p.is_dir() and not p.is_symlink()],
                key=lambda p: p.lstat().st_mtime_ns,
                reverse=True,
            )
            non_dir_backups = [
                p for p in all_backup_entries if not (p.is_dir() and not p.is_symlink())
            ]

            restored_backup = False
            if not ws_path.exists() and not ws_path.is_symlink() and valid_backup_dirs:
                latest_backup = valid_backup_dirs.pop(0)
                os.rename(latest_backup, ws_path)
                restored_backup = True

            removed_any_base_entry = False
            base_fd = self._open_base_dir()
            try:
                for leftover in valid_backup_dirs + non_dir_backups:
                    self._remove_entry_at(base_fd, leftover.name)
                    removed_any_base_entry = True

                with os.scandir(base_fd) as it:
                    staging_names = [e.name for e in it if e.name.startswith(staging_prefix)]
                for name in staging_names:
                    self._remove_entry_at(base_fd, name)
                    removed_any_base_entry = True

                if restored_backup or removed_any_base_entry:
                    fsync_directory_fd(base_fd)
            finally:
                os.close(base_fd)

            if self.tmp_dir.exists() and not self.tmp_dir.is_symlink():
                tmp_dir_fd = self._open_tmp_dir()
                try:
                    removed_tmp = False
                    with os.scandir(tmp_dir_fd) as it:
                        tmp_names = [e.name for e in it if e.name.startswith(tmp_prefix)]
                    for name in tmp_names:
                        os.unlink(name, dir_fd=tmp_dir_fd)
                        removed_tmp = True
                    if removed_tmp:
                        fsync_directory_fd(tmp_dir_fd)
                finally:
                    os.close(tmp_dir_fd)

        except (OSError, PathTraversalError) as exc:
            logger.error(
                "Workspace recovery failed for sandbox %s: %s",
                sandbox_id,
                exc,
            )
            raise WorkspaceCleanupError(
                f"Failed to recover interrupted workspace state for sandbox {sandbox_id}"
            ) from exc

    def commit_staging_workspace(self, sandbox_id: str, staging_path: Path) -> None:
        """Atomically commit a validated staging directory as the active workspace.

        Requires the exclusive sandbox lock (`LOCK_EX`).
        1. Moves existing active workspace `ws_path` to `.backup.<sandbox_id>.<uuid>`
           and fsyncs `base_dir`.
        2. Moves `staging_path` into the now-unoccupied `ws_path` and fsyncs `base_dir`.
        3. If step 2 fails:
           - Removes `staging_path` (best-effort).
           - Attempts to restore `backup_path -> ws_path` and fsync `base_dir`.
           - If rollback ALSO fails, NEVER deletes `backup_path` (preserving the only
             valid workspace generation) and raises `WorkspaceRollbackError`.
        4. After `ws_path` is active and durable, removes `backup_path` and fsyncs `base_dir`.
        """
        self._validate_sandbox_id(sandbox_id)
        if not self._is_exclusive_lock_held(sandbox_id):
            raise RuntimeError(
                f"commit_staging_workspace requires an exclusive sandbox_lock for {sandbox_id}"
            )

        ws_path = self.get_workspace_path(sandbox_id)
        backup_path = self.base_dir / f".backup.{sandbox_id}.{uuid.uuid4().hex}"
        moved_existing = False

        if ws_path.exists() or ws_path.is_symlink():
            try:
                os.rename(ws_path, backup_path)
                moved_existing = True
                self._fsync_base_dir()
            except OSError as exc:
                if staging_path.exists() or staging_path.is_symlink():
                    with contextlib.suppress(OSError):
                        self._remove_directory_tree(staging_path)
                raise WorkspaceCleanupError(
                    f"Failed to prepare workspace backup for sandbox {sandbox_id}"
                ) from exc

        try:
            os.rename(staging_path, ws_path)
            self._fsync_base_dir()
        except Exception as commit_exc:
            if staging_path.exists() or staging_path.is_symlink():
                with contextlib.suppress(OSError):
                    self._remove_directory_tree(staging_path)

            if moved_existing:
                try:
                    os.rename(backup_path, ws_path)
                    self._fsync_base_dir()
                except OSError as rollback_exc:
                    logger.critical(
                        "Workspace commit and rollback both failed for sandbox %s; "
                        "preserving backup generation %s (commit_err=%s, rollback_err=%s)",
                        sandbox_id,
                        backup_path.name,
                        type(commit_exc).__name__,
                        type(rollback_exc).__name__,
                    )
                    raise WorkspaceRollbackError(
                        f"Workspace commit failed and automatic rollback could not complete "
                        f"for sandbox {sandbox_id}; previous backup preserved for recovery",
                        details={
                            "sandbox_id": sandbox_id,
                            "rollback_failed": True,
                            "backup_preserved": True,
                        },
                    ) from rollback_exc

            raise WorkspaceCleanupError(
                f"Failed to commit staged workspace for sandbox {sandbox_id}; "
                f"previous workspace generation preserved"
            ) from commit_exc

        if moved_existing and (backup_path.exists() or backup_path.is_symlink()):
            try:
                self._remove_directory_tree(backup_path)
                self._fsync_base_dir()
            except OSError as cleanup_exc:
                logger.error(
                    "Committed workspace for sandbox %s, failed to remove backup %s: %s",
                    sandbox_id,
                    backup_path.name,
                    cleanup_exc,
                )
                raise WorkspaceCleanupError(
                    f"Failed to clean up previous workspace backup for sandbox {sandbox_id}"
                ) from cleanup_exc

    def _open_workspace_root(
        self,
        sandbox_id: str,
        *,
        create_if_missing: bool = False,
    ) -> int:
        """Open and validate the workspace directory anchor as a directory descriptor.

        Does NOT implicitly perform destructive commit recovery. When `create_if_missing=False`
        (used by read-only operations under shared locks), never creates or chmods directories.
        """
        ws_path = self.get_workspace_path(sandbox_id)
        if not ws_path.exists() and not ws_path.is_symlink():
            if not create_if_missing:
                raise SandboxFileNotFoundError(
                    f"Workspace for sandbox '{sandbox_id}' does not exist"
                )
            if not self._is_exclusive_lock_held(sandbox_id):
                raise RuntimeError(
                    f"Creating workspace root for {sandbox_id} requires an exclusive sandbox_lock"
                )
            ws_path.mkdir(mode=0o700, parents=True, exist_ok=True)
            with contextlib.suppress(OSError):
                os.chmod(ws_path, 0o700)
            self._fsync_base_dir()

        try:
            root_fd = os.open(
                str(ws_path),
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
        except FileNotFoundError as exc:
            raise SandboxFileNotFoundError(
                f"Workspace for sandbox '{sandbox_id}' does not exist"
            ) from exc
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                raise PathTraversalError("Workspace root is a symlink or non-directory") from exc
            raise

        st = os.fstat(root_fd)
        if not stat.S_ISDIR(st.st_mode):
            os.close(root_fd)
            raise PathTraversalError("Workspace root is not a directory")
        if st.st_uid != os.getuid():
            os.close(root_fd)
            raise PathTraversalError("Workspace root ownership mismatch")
        if (st.st_mode & 0o077) != 0:
            if self._is_exclusive_lock_held(sandbox_id):
                try:
                    os.fchmod(root_fd, 0o700)
                    st = os.fstat(root_fd)
                except OSError:
                    pass
            if (st.st_mode & 0o077) != 0:
                os.close(root_fd)
                raise PathTraversalError("Workspace root permissions are insecure")

        return root_fd

    def parse_and_validate_path(self, relative_path: str) -> list[str]:
        """Validate untrusted path input and return normalized components."""
        if not relative_path or not relative_path.strip():
            raise PathTraversalError("File path cannot be empty or whitespace only")

        if "\0" in relative_path:
            raise PathTraversalError("Null bytes are prohibited in file paths")

        if "\\" in relative_path or ":" in relative_path:
            raise PathTraversalError("Path contains invalid separators or drive identifiers")

        if relative_path.startswith("/"):
            raise PathTraversalError(
                "Absolute paths are prohibited; path must be workspace-relative"
            )

        if len(relative_path) > self.config.MAX_PATH_LENGTH:
            raise PathTraversalError(
                f"Path length {len(relative_path)} exceeds limit {self.config.MAX_PATH_LENGTH}"
            )

        raw_parts = relative_path.split("/")
        components: list[str] = []
        for part in raw_parts:
            part = part.strip()
            if not part or part == ".":
                continue
            if part == "..":
                raise PathTraversalError("Parent directory traversal ('..') is prohibited")
            if len(part) > 255:
                raise PathTraversalError(f"Directory or file component exceeds 255 chars: '{part}'")
            components.append(part)

        if not components:
            raise PathTraversalError("Path resolved to empty workspace root")

        if len(components) > self.config.MAX_DIRECTORY_DEPTH:
            raise PathTraversalError(
                f"Directory depth {len(components)} exceeds limit {self.config.MAX_DIRECTORY_DEPTH}"
            )

        return components

    def _traverse_to_parent(
        self,
        root_fd: int,
        components: list[str],
        create_parents: bool = False,
    ) -> tuple[int, str]:
        """Stepwise descriptor-relative traversal using O_NOFOLLOW to reach parent directory."""
        if len(components) == 1:
            return os.dup(root_fd), components[0]

        parent_components = components[:-1]
        leaf_name = components[-1]
        current_fd = os.dup(root_fd)

        for comp in parent_components:
            try:
                next_fd = os.open(
                    comp,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=current_fd,
                )
            except FileNotFoundError as exc:
                if create_parents:
                    try:
                        os.mkdir(comp, mode=0o700, dir_fd=current_fd)
                        fsync_directory_fd(current_fd)
                        next_fd = os.open(
                            comp,
                            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=current_fd,
                        )
                    except OSError as sub_exc:
                        os.close(current_fd)
                        if sub_exc.errno in (errno.ELOOP, errno.EEXIST):
                            raise PathTraversalError(
                                f"Symlink or conflict encountered creating directory '{comp}'"
                            ) from sub_exc
                        raise
                else:
                    os.close(current_fd)
                    raise SandboxFileNotFoundError(
                        f"Directory component '{comp}' does not exist"
                    ) from exc
            except OSError as exc:
                os.close(current_fd)
                if exc.errno in (errno.ELOOP, errno.EEXIST, errno.ENOTDIR):
                    raise PathTraversalError(
                        f"Symlink or non-directory encountered at component '{comp}'"
                    ) from exc
                raise

            os.close(current_fd)
            current_fd = next_fd

        return current_fd, leaf_name

    def _calculate_workspace_stats(self, root_fd: int) -> tuple[int, int]:
        """Recursively compute total regular file bytes and file count within the workspace.

        Fails closed if any symlink, hard link, or special file is encountered, or if any
        directory or entry cannot be inspected accurately due to filesystem errors.
        """
        total_bytes = 0
        file_count = 0

        def _walk_fd(dir_fd: int, rel_prefix: str) -> None:
            nonlocal total_bytes, file_count
            try:
                with os.scandir(dir_fd) as it:
                    entries = list(it)
            except OSError as exc:
                raise WorkspaceCleanupError(
                    f"Unable to establish accurate workspace quota accounting at "
                    f"'{rel_prefix or '.'}': {exc}"
                ) from exc

            for entry in entries:
                entry_rel = f"{rel_prefix}/{entry.name}" if rel_prefix else entry.name
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                        raise PathTraversalError(
                            f"Symlink or invalid entry encountered during quota accounting: "
                            f"'{entry_rel}'"
                        ) from exc
                    raise WorkspaceCleanupError(
                        f"Unable to stat workspace entry '{entry_rel}' for quota accounting: {exc}"
                    ) from exc

                if stat.S_ISLNK(st.st_mode):
                    raise PathTraversalError(
                        f"Symlink rejected during workspace quota accounting: '{entry_rel}'"
                    )

                if stat.S_ISREG(st.st_mode):
                    if st.st_nlink > 1:
                        raise PathTraversalError(
                            f"Hard link rejected during workspace quota accounting: '{entry_rel}'"
                        )
                    total_bytes += st.st_size
                    file_count += 1
                elif stat.S_ISDIR(st.st_mode):
                    try:
                        sub_fd = os.open(
                            entry.name,
                            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=dir_fd,
                        )
                    except OSError as exc:
                        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                            raise PathTraversalError(
                                f"Symlink or non-directory at '{entry_rel}'"
                            ) from exc
                        raise WorkspaceCleanupError(
                            f"Unable to open directory '{entry_rel}' for quota accounting: {exc}"
                        ) from exc
                    try:
                        sub_st = os.fstat(sub_fd)
                        if (
                            not stat.S_ISDIR(sub_st.st_mode)
                            or sub_st.st_ino != st.st_ino
                            or sub_st.st_dev != st.st_dev
                        ):
                            raise PathTraversalError(
                                f"Directory identity changed during quota accounting "
                                f"at '{entry_rel}'"
                            )
                        _walk_fd(sub_fd, entry_rel)
                    finally:
                        os.close(sub_fd)
                else:
                    raise PathTraversalError(
                        f"Special file rejected during workspace quota accounting: '{entry_rel}'"
                    )

        _walk_fd(root_fd, "")
        return total_bytes, file_count

    def write_file(
        self,
        sandbox_id: str,
        path: str,
        content: str | bytes,
        encoding: str = "utf-8",
    ) -> FileInfo:
        """Write content to a workspace file atomically using descriptor-relative replace."""
        if encoding.lower() == "base64":
            if isinstance(content, str):
                try:
                    payload = base64.b64decode(content, validate=True)
                except Exception as exc:
                    raise InvalidFileEncodingError(f"Invalid base64 payload: {exc}") from exc
            else:
                payload = content
        elif encoding.lower() in ("utf-8", "utf8"):
            if isinstance(content, str):
                payload = content.encode("utf-8")
            else:
                payload = content
        else:
            raise InvalidFileEncodingError(
                f"Unsupported encoding '{encoding}'. Use 'utf-8' or 'base64'."
            )

        payload_size = len(payload)
        if payload_size > self.config.MAX_FILE_SIZE_BYTES:
            raise FileQuotaExceededError(
                f"File size {payload_size} bytes exceeds limit {self.config.MAX_FILE_SIZE_BYTES}"
            )

        components = self.parse_and_validate_path(path)
        normalized_rel_path = "/".join(components)

        with self.sandbox_lock(sandbox_id, exclusive=True):
            self.recover_interrupted_commit(sandbox_id)
            root_fd = self._open_workspace_root(sandbox_id, create_if_missing=True)
            parent_fd: int | None = None
            tmp_dir_fd: int | None = None
            try:
                current_bytes, current_files = self._calculate_workspace_stats(root_fd)

                parent_fd, leaf_name = self._traverse_to_parent(
                    root_fd, components, create_parents=True
                )
                existing_size = 0
                is_existing = False
                try:
                    existing_stat = os.stat(leaf_name, dir_fd=parent_fd, follow_symlinks=False)
                    if stat.S_ISDIR(existing_stat.st_mode):
                        raise PathTraversalError(
                            f"Cannot overwrite directory '{leaf_name}' with a file"
                        )
                    if not stat.S_ISREG(existing_stat.st_mode):
                        raise PathTraversalError(f"Target '{leaf_name}' is not a regular file")
                    existing_size = existing_stat.st_size
                    is_existing = True
                except FileNotFoundError:
                    pass

                net_size_increase = payload_size - existing_size
                if current_bytes + net_size_increase > self.config.MAX_WORKSPACE_SIZE_BYTES:
                    raise FileQuotaExceededError(
                        f"Workspace quota exceeded: required {current_bytes + net_size_increase} "
                        f"bytes exceeds limit {self.config.MAX_WORKSPACE_SIZE_BYTES}"
                    )

                if not is_existing and (current_files + 1 > self.config.MAX_FILE_COUNT):
                    raise FileQuotaExceededError(
                        f"File count limit exceeded: workspace already has {current_files} files "
                        f"(limit: {self.config.MAX_FILE_COUNT})"
                    )

                tmp_dir_fd = self._open_tmp_dir()
                tmp_name = f".tmp.{sandbox_id}.{uuid.uuid4().hex}"
                tmp_fd = os.open(
                    tmp_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                    dir_fd=tmp_dir_fd,
                )
                try:
                    write_all_to_fd(tmp_fd, payload)
                    os.fsync(tmp_fd)
                finally:
                    os.close(tmp_fd)

                try:
                    if os.name == "posix":
                        os.replace(
                            tmp_name,
                            leaf_name,
                            src_dir_fd=tmp_dir_fd,
                            dst_dir_fd=parent_fd,
                        )
                    else:
                        parent_path = self._resolve_dir_path_from_components(
                            sandbox_id, components[:-1]
                        )
                        os.replace(self.tmp_dir / tmp_name, parent_path / leaf_name)
                    fsync_directory_fd(parent_fd)
                except Exception:
                    with contextlib.suppress(OSError):
                        os.unlink(tmp_name, dir_fd=tmp_dir_fd)
                    raise

                final_stat = os.stat(leaf_name, dir_fd=parent_fd, follow_symlinks=False)
                modified_at = datetime.fromtimestamp(final_stat.st_mtime, tz=UTC)

                return FileInfo(
                    path=normalized_rel_path,
                    size_bytes=payload_size,
                    is_directory=False,
                    modified_at=modified_at,
                )

            finally:
                if tmp_dir_fd is not None:
                    os.close(tmp_dir_fd)
                if parent_fd is not None:
                    os.close(parent_fd)
                os.close(root_fd)

    def read_file(self, sandbox_id: str, path: str) -> FileContent:
        """Read content from a workspace file using descriptor-relative O_NOFOLLOW verification.

        Never performs directory creation, renames, or cleanup while holding a shared lock.
        """
        components = self.parse_and_validate_path(path)
        normalized_rel_path = "/".join(components)

        with self._shared_lock_with_recovery(sandbox_id):
            root_fd = self._open_workspace_root(sandbox_id, create_if_missing=False)
            parent_fd: int | None = None
            try:
                parent_fd, leaf_name = self._traverse_to_parent(
                    root_fd, components, create_parents=False
                )
                # Pre-open stat to reject special files (FIFOs, sockets, devices)
                # BEFORE os.open which would block on named pipes.
                try:
                    pre_st = os.stat(leaf_name, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError as exc:
                    raise SandboxFileNotFoundError(
                        f"File '{normalized_rel_path}' does not exist"
                    ) from exc
                except OSError as exc:
                    if exc.errno in (errno.ELOOP, errno.EEXIST):
                        raise PathTraversalError(
                            f"Symlink rejected at '{normalized_rel_path}'"
                        ) from exc
                    raise

                if stat.S_ISLNK(pre_st.st_mode):
                    raise PathTraversalError(f"Symlink rejected at '{normalized_rel_path}'")
                if stat.S_ISDIR(pre_st.st_mode):
                    raise PathTraversalError(
                        f"Target '{normalized_rel_path}' is a directory, not a file"
                    )
                if not stat.S_ISREG(pre_st.st_mode):
                    raise PathTraversalError(
                        f"Target '{normalized_rel_path}' is not a regular file"
                    )

                if pre_st.st_size > self.config.MAX_READ_RESPONSE_BYTES:
                    raise FileQuotaExceededError(
                        f"File size {pre_st.st_size} exceeds read limit "
                        f"{self.config.MAX_READ_RESPONSE_BYTES}"
                    )

                try:
                    file_fd = os.open(
                        leaf_name,
                        os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                        dir_fd=parent_fd,
                    )
                except OSError as exc:
                    if exc.errno in (errno.ELOOP, errno.EEXIST):
                        raise PathTraversalError(
                            f"Symlink rejected at '{normalized_rel_path}'"
                        ) from exc
                    raise

                try:
                    # Post-open fstat to guard against TOCTOU race
                    st = os.fstat(file_fd)
                    if not stat.S_ISREG(st.st_mode):
                        raise PathTraversalError(
                            f"Target '{normalized_rel_path}' is not a regular file"
                        )
                    if st.st_ino != pre_st.st_ino or st.st_dev != pre_st.st_dev:
                        raise PathTraversalError(
                            f"File identity changed during open at '{normalized_rel_path}'"
                        )
                    if st.st_size > self.config.MAX_READ_RESPONSE_BYTES:
                        raise FileQuotaExceededError(
                            f"File size {st.st_size} exceeds read limit "
                            f"{self.config.MAX_READ_RESPONSE_BYTES}"
                        )
                    data = os.read(file_fd, self.config.MAX_READ_RESPONSE_BYTES + 1)
                    if len(data) > self.config.MAX_READ_RESPONSE_BYTES:
                        raise FileQuotaExceededError(
                            f"File size exceeds read limit {self.config.MAX_READ_RESPONSE_BYTES}"
                        )
                finally:
                    os.close(file_fd)

            finally:
                if parent_fd is not None:
                    os.close(parent_fd)
                os.close(root_fd)

        try:
            text = data.decode("utf-8")
            return FileContent(
                path=normalized_rel_path,
                content=text,
                encoding="utf-8",
                size_bytes=len(data),
            )
        except UnicodeDecodeError:
            b64_content = base64.b64encode(data).decode("ascii")
            return FileContent(
                path=normalized_rel_path,
                content=b64_content,
                encoding="base64",
                size_bytes=len(data),
            )

    def list_files(self, sandbox_id: str, path: str = "") -> FileListResponse:
        """List files and directories within the workspace or a specified subpath.

        Never performs directory creation, renames, or cleanup while holding a shared lock.
        """
        components = self.parse_and_validate_path(path) if path and path.strip() else []
        prefix = "/".join(components)

        with self._shared_lock_with_recovery(sandbox_id):
            try:
                root_fd = self._open_workspace_root(sandbox_id, create_if_missing=False)
            except SandboxFileNotFoundError:
                if components:
                    raise SandboxFileNotFoundError(f"Directory '{prefix}' does not exist") from None
                return FileListResponse(files=[], total_count=0, total_size_bytes=0)

            try:
                if components:
                    target_fd, leaf_name = self._traverse_to_parent(
                        root_fd, components, create_parents=False
                    )
                    try:
                        dir_fd = os.open(
                            leaf_name,
                            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=target_fd,
                        )
                    except FileNotFoundError as exc:
                        raise SandboxFileNotFoundError(
                            f"Directory '{prefix}' does not exist"
                        ) from exc
                    except OSError as exc:
                        if exc.errno in (errno.ELOOP, errno.EEXIST, errno.ENOTDIR):
                            raise PathTraversalError(
                                f"Symlink or non-directory encountered at '{prefix}'"
                            ) from exc
                        raise
                    finally:
                        os.close(target_fd)
                else:
                    dir_fd = os.dup(root_fd)

                files: list[FileInfo] = []
                total_size = 0

                def _collect_entries(current_fd: int, current_rel_prefix: str) -> None:
                    nonlocal total_size
                    if len(files) >= self.config.MAX_FILE_LIST_ENTRIES:
                        return

                    try:
                        with os.scandir(current_fd) as it:
                            for entry in it:
                                if len(files) >= self.config.MAX_FILE_LIST_ENTRIES:
                                    break

                                try:
                                    st = entry.stat(follow_symlinks=False)
                                except OSError:
                                    continue

                                entry_rel_path = (
                                    f"{current_rel_prefix}/{entry.name}"
                                    if current_rel_prefix
                                    else entry.name
                                )
                                mod_time = datetime.fromtimestamp(st.st_mtime, tz=UTC)

                                if stat.S_ISDIR(st.st_mode):
                                    files.append(
                                        FileInfo(
                                            path=entry_rel_path,
                                            size_bytes=0,
                                            is_directory=True,
                                            modified_at=mod_time,
                                        )
                                    )
                                    try:
                                        sub_fd = os.open(
                                            entry.name,
                                            os.O_RDONLY
                                            | os.O_DIRECTORY
                                            | os.O_NOFOLLOW
                                            | os.O_CLOEXEC,
                                            dir_fd=current_fd,
                                        )
                                        try:
                                            _collect_entries(sub_fd, entry_rel_path)
                                        finally:
                                            os.close(sub_fd)
                                    except OSError:
                                        continue
                                elif stat.S_ISREG(st.st_mode):
                                    files.append(
                                        FileInfo(
                                            path=entry_rel_path,
                                            size_bytes=st.st_size,
                                            is_directory=False,
                                            modified_at=mod_time,
                                        )
                                    )
                                    total_size += st.st_size
                    except OSError:
                        pass

                try:
                    _collect_entries(dir_fd, prefix)
                finally:
                    os.close(dir_fd)

                files.sort(key=lambda x: x.path)
                return FileListResponse(
                    files=files,
                    total_count=len(files),
                    total_size_bytes=total_size,
                )

            finally:
                os.close(root_fd)

    def delete_file(self, sandbox_id: str, path: str) -> bool:
        """Delete a file or empty directory in the workspace using descriptor-relative unlink."""
        components = self.parse_and_validate_path(path)
        normalized_rel_path = "/".join(components)

        with self.sandbox_lock(sandbox_id, exclusive=True):
            self.recover_interrupted_commit(sandbox_id)
            try:
                root_fd = self._open_workspace_root(sandbox_id, create_if_missing=False)
            except SandboxFileNotFoundError as exc:
                raise SandboxFileNotFoundError(
                    f"Entry '{normalized_rel_path}' does not exist"
                ) from exc

            try:
                parent_fd, leaf_name = self._traverse_to_parent(
                    root_fd, components, create_parents=False
                )
                try:
                    st = os.stat(leaf_name, dir_fd=parent_fd, follow_symlinks=False)
                    if stat.S_ISDIR(st.st_mode):
                        try:
                            os.rmdir(leaf_name, dir_fd=parent_fd)
                        except OSError as exc:
                            if exc.errno in (errno.ENOTEMPTY, errno.EEXIST):
                                raise PathTraversalError(
                                    f"Directory '{normalized_rel_path}' is not empty"
                                ) from exc
                            raise
                    else:
                        os.unlink(leaf_name, dir_fd=parent_fd)
                    fsync_directory_fd(parent_fd)
                    return True
                except FileNotFoundError as exc:
                    raise SandboxFileNotFoundError(
                        f"Entry '{normalized_rel_path}' does not exist"
                    ) from exc
                except OSError as exc:
                    if exc.errno in (errno.ELOOP, errno.EEXIST):
                        raise PathTraversalError(
                            f"Symlink rejected at '{normalized_rel_path}'"
                        ) from exc
                    raise
                finally:
                    os.close(parent_fd)
            finally:
                os.close(root_fd)

    def create_directory(self, sandbox_id: str, path: str) -> bool:
        """Create a directory with parents using descriptor-relative mkdirat."""
        components = self.parse_and_validate_path(path)
        with self.sandbox_lock(sandbox_id, exclusive=True):
            self.recover_interrupted_commit(sandbox_id)
            root_fd = self._open_workspace_root(sandbox_id, create_if_missing=True)
            try:
                parent_fd, leaf_name = self._traverse_to_parent(
                    root_fd, components, create_parents=True
                )
                try:
                    try:
                        os.mkdir(leaf_name, mode=0o700, dir_fd=parent_fd)
                        fsync_directory_fd(parent_fd)
                    except FileExistsError as exc:
                        st = os.stat(leaf_name, dir_fd=parent_fd, follow_symlinks=False)
                        if not stat.S_ISDIR(st.st_mode):
                            raise PathTraversalError(
                                f"Path '{path}' exists and is not a directory"
                            ) from exc
                    return True
                finally:
                    os.close(parent_fd)
            finally:
                os.close(root_fd)

    def delete_workspace(self, sandbox_id: str) -> None:
        """Authoritatively remove the workspace directory and all staging/backup/temp state.

        Preserves `.locks/<sandbox_id>.lock` as a 0-byte inode anchor so concurrent or queued
        waiters on the advisory lock never experience lock-inode replacement (split-brain locking).
        Raises `WorkspaceCleanupError` if any workspace, staging, backup, or temp artifact
        cannot be removed.
        """
        with self.sandbox_lock(sandbox_id, exclusive=True):
            ws_path = self.get_workspace_path(sandbox_id)
            removed_base = False
            try:
                base_fd = self._open_base_dir()
                try:
                    try:
                        os.stat(sandbox_id, dir_fd=base_fd, follow_symlinks=False)
                        has_ws = True
                    except FileNotFoundError:
                        has_ws = False

                    if has_ws:
                        self._remove_entry_at(base_fd, sandbox_id)
                        removed_base = True

                    prefixes = (f".staging.{sandbox_id}.", f".backup.{sandbox_id}.")
                    with os.scandir(base_fd) as it:
                        artifact_names = [e.name for e in it if e.name.startswith(prefixes)]
                    for name in artifact_names:
                        self._remove_entry_at(base_fd, name)
                        removed_base = True

                    if removed_base:
                        fsync_directory_fd(base_fd)
                finally:
                    os.close(base_fd)

                if self.tmp_dir.exists() and not self.tmp_dir.is_symlink():
                    tmp_prefix = f".tmp.{sandbox_id}."
                    tmp_dir_fd = self._open_tmp_dir()
                    try:
                        removed_tmp = False
                        with os.scandir(tmp_dir_fd) as it:
                            tmp_names = [e.name for e in it if e.name.startswith(tmp_prefix)]
                        for name in tmp_names:
                            os.unlink(name, dir_fd=tmp_dir_fd)
                            removed_tmp = True
                        if removed_tmp:
                            fsync_directory_fd(tmp_dir_fd)
                    finally:
                        os.close(tmp_dir_fd)

            except (OSError, PathTraversalError) as exc:
                logger.error("Failed to authoritatively delete workspace %s: %s", ws_path, exc)
                raise WorkspaceCleanupError(
                    f"Failed to delete workspace directory for sandbox {sandbox_id}: {exc}"
                ) from exc

    def _remove_entry_at(self, parent_fd: int, name: str) -> None:
        """Descriptor-relative recursive removal that never follows symlinks or traverses paths."""
        if not name or "/" in name or "\0" in name or name in (".", ".."):
            raise PathTraversalError(f"Invalid entry name for removal: {name!r}")

        st = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISDIR(st.st_mode):
            os.unlink(name, dir_fd=parent_fd)
            return

        try:
            child_fd = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent_fd,
            )
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                raise PathTraversalError(
                    f"Directory entry '{name}' was replaced by a symlink or non-directory"
                ) from exc
            raise

        try:
            child_st = os.fstat(child_fd)
            if (
                not stat.S_ISDIR(child_st.st_mode)
                or child_st.st_ino != st.st_ino
                or child_st.st_dev != st.st_dev
            ):
                raise PathTraversalError(
                    f"Directory replacement race detected while removing '{name}'"
                )
            with os.scandir(child_fd) as it:
                child_names = [entry.name for entry in it]
            for child_name in child_names:
                self._remove_entry_at(child_fd, child_name)
        finally:
            os.close(child_fd)

        os.rmdir(name, dir_fd=parent_fd)

    def _remove_directory_tree(self, path: Path) -> None:
        """Stepwise descriptor-relative recursive removal without ignoring errors."""
        parent_fd = os.open(
            str(path.parent),
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        try:
            self._remove_entry_at(parent_fd, path.name)
        finally:
            os.close(parent_fd)

    def _resolve_dir_path_from_components(self, sandbox_id: str, components: list[str]) -> Path:
        """Helper to construct trusted Path object for components within sandbox root."""
        res = self.get_workspace_path(sandbox_id)
        for comp in components:
            res = res / comp
        return res
