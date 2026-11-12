"""Provider-neutral workspace archive serialization and secure tar import.

Enforces descriptor-relative traversal, O_NOFOLLOW validation, strict entry-type
whitelisting (regular files and directories only), bounded streaming memory,
resource quotas, write-all guarantees, directory-entry fsync durability, and
atomic directory-generation staging commits.
"""

from __future__ import annotations

import contextlib
import errno
import io
import lzma
import os
import stat
import tarfile
import tempfile
import time
import uuid
import zlib
from collections.abc import Iterable, Iterator
from typing import IO

from app.core.exceptions import (
    FileQuotaExceededError,
    PathTraversalError,
    SandboxFileNotFoundError,
)
from app.sandbox.workspace import (
    WorkspaceManager,
    fsync_directory_fd,
    write_all_to_fd,
)

APPROVED_ARCHIVE_UID = 10001
APPROVED_ARCHIVE_GID = 10001
APPROVED_ARCHIVE_USER = "sandbox"
STREAM_CHUNK_SIZE = 64 * 1024  # 64 KB bounded streaming chunks
SPOOL_MAX_MEMORY_BYTES = 1024 * 1024  # 1 MB before spooling to temporary file


class _BoundedSpoolWriter:
    """File-like wrapper around SpooledTemporaryFile enforcing MAX_ARCHIVE_BYTES."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self.bytes_written = 0
        self._spool: tempfile.SpooledTemporaryFile[bytes] = tempfile.SpooledTemporaryFile(
            max_size=SPOOL_MAX_MEMORY_BYTES,
            mode="w+b",
        )

    def write(self, data: bytes | bytearray | memoryview) -> int:
        chunk_len = len(data)
        if self.bytes_written + chunk_len > self.max_bytes:
            raise FileQuotaExceededError(
                f"Serialized archive size exceeds limit of {self.max_bytes} bytes"
            )
        written = self._spool.write(data)
        self.bytes_written += chunk_len
        return written

    def tell(self) -> int:
        return self._spool.tell()

    def flush(self) -> None:
        self._spool.flush()

    def detach_spool(self) -> tempfile.SpooledTemporaryFile[bytes]:
        self._spool.flush()
        self._spool.seek(0)
        return self._spool

    def close(self) -> None:
        self._spool.close()


class _BoundedStreamReader(io.RawIOBase):
    """Readable stream adapter enforcing MAX_ARCHIVE_BYTES over bytes, IO, or chunk iterables."""

    def __init__(
        self,
        source: bytes | IO[bytes] | Iterable[bytes],
        max_bytes: int,
    ) -> None:
        super().__init__()
        self.max_bytes = max_bytes
        self.total_bytes_read = 0
        self._buffer = bytearray()
        self._eof = False

        if isinstance(source, (bytes, bytearray, memoryview)):
            self._file_source: IO[bytes] | None = io.BytesIO(bytes(source))
            self._iter_source: Iterator[bytes] | None = None
        elif hasattr(source, "read"):
            self._file_source = source  # type: ignore[assignment]
            self._iter_source = None
        else:
            self._file_source = None
            self._iter_source = iter(source)

    def readable(self) -> bool:
        return True

    def _fill_buffer(self, target_size: int) -> None:
        while len(self._buffer) < target_size and not self._eof:
            if self._file_source is not None:
                chunk = self._file_source.read(STREAM_CHUNK_SIZE)
                if not chunk:
                    self._eof = True
                    break
            else:
                assert self._iter_source is not None
                try:
                    chunk = next(self._iter_source)
                except StopIteration:
                    self._eof = True
                    break
                if not chunk:
                    continue

            self.total_bytes_read += len(chunk)
            if self.total_bytes_read > self.max_bytes:
                raise FileQuotaExceededError(
                    f"Archive stream exceeds maximum allowed size of {self.max_bytes} bytes"
                )
            self._buffer.extend(chunk)

    def readinto(self, b: bytearray | memoryview) -> int:  # type: ignore[override]
        target = len(b)
        if target == 0:
            return 0
        self._fill_buffer(target)
        n = min(target, len(self._buffer))
        if n == 0:
            return 0
        b[:n] = self._buffer[:n]
        del self._buffer[:n]
        return n


class WorkspaceArchiveSerializer:
    """Serializes a sandbox workspace into a normalized, bounded tar stream."""

    def __init__(self, workspace_manager: WorkspaceManager) -> None:
        self.workspace_manager = workspace_manager
        self.config = workspace_manager.config

    def serialize(
        self,
        sandbox_id: str,
        *,
        include_root_entry: bool = True,
        acquire_lock: bool = True,
    ) -> tempfile.SpooledTemporaryFile[bytes]:
        """Serialize verified regular files and directories into a bounded SpooledTemporaryFile.

        Never performs directory creation or destructive recovery while holding a shared lock.
        All user-owned files inside `<base_dir>/<sandbox_id>` (including files starting with
        `.tmp.`, `.staging.`, or `.backup.`) are serialized intact.
        """
        if acquire_lock:
            lock_ctx = self.workspace_manager._shared_lock_with_recovery(sandbox_id)
        else:
            self.workspace_manager._ensure_recovered(sandbox_id)
            lock_ctx = contextlib.nullcontext()

        with lock_ctx:
            writer = _BoundedSpoolWriter(max_bytes=self.config.MAX_ARCHIVE_BYTES)
            root_fd: int | None = None
            try:
                try:
                    root_fd = self.workspace_manager._open_workspace_root(
                        sandbox_id,
                        create_if_missing=False,
                    )
                except SandboxFileNotFoundError:
                    root_fd = None

                entry_count = 0
                file_count = 0
                total_decompressed_bytes = 0
                max_decompressed = min(
                    self.config.MAX_WORKSPACE_SIZE_BYTES,
                    self.config.MAX_DECOMPRESSED_BYTES,
                )

                with tarfile.open(
                    fileobj=writer,  # type: ignore[arg-type]
                    mode="w|",
                    format=tarfile.PAX_FORMAT,
                ) as tf:
                    if include_root_entry:
                        root_mtime = (
                            int(os.fstat(root_fd).st_mtime)
                            if root_fd is not None
                            else int(time.time())
                        )
                        root_info = tarfile.TarInfo("/")
                        root_info.type = tarfile.DIRTYPE
                        root_info.uid = APPROVED_ARCHIVE_UID
                        root_info.gid = APPROVED_ARCHIVE_GID
                        root_info.uname = APPROVED_ARCHIVE_USER
                        root_info.gname = APPROVED_ARCHIVE_USER
                        root_info.mode = 0o700
                        root_info.mtime = root_mtime
                        tf.addfile(root_info)

                    def _serialize_dir(dir_fd: int, rel_prefix: str) -> None:
                        nonlocal entry_count, file_count, total_decompressed_bytes

                        with os.scandir(dir_fd) as it:
                            entries = sorted(it, key=lambda e: e.name)

                        for entry in entries:
                            rel_path = f"{rel_prefix}/{entry.name}" if rel_prefix else entry.name
                            # Validate path depth, length, and characters
                            self.workspace_manager.parse_and_validate_path(rel_path)

                            try:
                                st = entry.stat(follow_symlinks=False)
                            except OSError as exc:
                                raise PathTraversalError(
                                    f"Failed to stat workspace entry '{rel_path}'"
                                ) from exc

                            if stat.S_ISLNK(st.st_mode):
                                raise PathTraversalError(
                                    f"Symlink rejected during workspace serialization: '{rel_path}'"
                                )

                            if stat.S_ISDIR(st.st_mode):
                                entry_count += 1
                                if entry_count > self.config.MAX_ARCHIVE_ENTRIES:
                                    raise FileQuotaExceededError(
                                        f"Workspace entry count exceeds archive limit "
                                        f"({self.config.MAX_ARCHIVE_ENTRIES})"
                                    )

                                try:
                                    sub_fd = os.open(
                                        entry.name,
                                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                        dir_fd=dir_fd,
                                    )
                                except OSError as exc:
                                    if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                                        raise PathTraversalError(
                                            f"Symlink or non-directory at '{rel_path}'"
                                        ) from exc
                                    raise
                                try:
                                    sub_st = os.fstat(sub_fd)
                                    if (
                                        not stat.S_ISDIR(sub_st.st_mode)
                                        or sub_st.st_ino != st.st_ino
                                        or sub_st.st_dev != st.st_dev
                                    ):
                                        raise PathTraversalError(
                                            f"Directory identity changed during serialization "
                                            f"at '{rel_path}'"
                                        )

                                    dir_info = tarfile.TarInfo(rel_path)
                                    dir_info.type = tarfile.DIRTYPE
                                    dir_info.uid = APPROVED_ARCHIVE_UID
                                    dir_info.gid = APPROVED_ARCHIVE_GID
                                    dir_info.uname = APPROVED_ARCHIVE_USER
                                    dir_info.gname = APPROVED_ARCHIVE_USER
                                    dir_info.mode = 0o700
                                    dir_info.mtime = int(sub_st.st_mtime)
                                    tf.addfile(dir_info)

                                    _serialize_dir(sub_fd, rel_path)
                                finally:
                                    os.close(sub_fd)

                            elif stat.S_ISREG(st.st_mode):
                                if st.st_nlink > 1:
                                    raise PathTraversalError(
                                        f"Hard link rejected during workspace serialization: "
                                        f"'{rel_path}'"
                                    )
                                entry_count += 1
                                if entry_count > self.config.MAX_ARCHIVE_ENTRIES:
                                    raise FileQuotaExceededError(
                                        f"Workspace entry count exceeds archive limit "
                                        f"({self.config.MAX_ARCHIVE_ENTRIES})"
                                    )
                                file_count += 1
                                if file_count > self.config.MAX_FILE_COUNT:
                                    raise FileQuotaExceededError(
                                        f"Workspace file count exceeds limit "
                                        f"({self.config.MAX_FILE_COUNT})"
                                    )
                                if st.st_size > self.config.MAX_FILE_SIZE_BYTES:
                                    raise FileQuotaExceededError(
                                        f"File '{rel_path}' size {st.st_size} exceeds limit "
                                        f"({self.config.MAX_FILE_SIZE_BYTES})"
                                    )
                                total_decompressed_bytes += st.st_size
                                if total_decompressed_bytes > max_decompressed:
                                    raise FileQuotaExceededError(
                                        f"Total serialized payload {total_decompressed_bytes} "
                                        f"exceeds limit ({max_decompressed})"
                                    )

                                try:
                                    file_fd = os.open(
                                        entry.name,
                                        os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                        dir_fd=dir_fd,
                                    )
                                except OSError as exc:
                                    if exc.errno in (errno.ELOOP, errno.EEXIST):
                                        raise PathTraversalError(
                                            f"Symlink rejected at '{rel_path}'"
                                        ) from exc
                                    raise

                                try:
                                    fst = os.fstat(file_fd)
                                    if not stat.S_ISREG(fst.st_mode) or fst.st_nlink > 1:
                                        raise PathTraversalError(
                                            f"Entry '{rel_path}' is not an unlinked regular file"
                                        )
                                    if fst.st_ino != st.st_ino or fst.st_dev != st.st_dev:
                                        raise PathTraversalError(
                                            f"File inode/device identity changed on '{rel_path}'"
                                        )
                                    if (
                                        fst.st_size != st.st_size
                                        or fst.st_mtime_ns != st.st_mtime_ns
                                    ):
                                        raise PathTraversalError(
                                            f"Concurrent file mutation detected on '{rel_path}'"
                                        )

                                    reg_info = tarfile.TarInfo(rel_path)
                                    reg_info.type = tarfile.REGTYPE
                                    reg_info.size = fst.st_size
                                    reg_info.uid = APPROVED_ARCHIVE_UID
                                    reg_info.gid = APPROVED_ARCHIVE_GID
                                    reg_info.uname = APPROVED_ARCHIVE_USER
                                    reg_info.gname = APPROVED_ARCHIVE_USER
                                    reg_info.mode = 0o600
                                    reg_info.mtime = int(fst.st_mtime)

                                    try:
                                        with os.fdopen(file_fd, "rb", closefd=False) as fobj:
                                            tf.addfile(reg_info, fileobj=fobj)
                                    except OSError as exc:
                                        raise PathTraversalError(
                                            f"Snapshot consistency failure while reading "
                                            f"'{rel_path}': {exc}"
                                        ) from exc

                                    trailing = os.read(file_fd, 1)
                                    post_st = os.fstat(file_fd)
                                    if (
                                        trailing
                                        or not stat.S_ISREG(post_st.st_mode)
                                        or post_st.st_nlink > 1
                                        or post_st.st_ino != fst.st_ino
                                        or post_st.st_dev != fst.st_dev
                                        or post_st.st_size != fst.st_size
                                        or post_st.st_mtime_ns != fst.st_mtime_ns
                                    ):
                                        raise PathTraversalError(
                                            f"Snapshot consistency violation: '{rel_path}' "
                                            f"modified during serialization"
                                        )
                                finally:
                                    os.close(file_fd)
                            else:
                                raise PathTraversalError(
                                    f"Special file rejected during workspace serialization: "
                                    f"'{rel_path}'"
                                )

                    if root_fd is not None:
                        _serialize_dir(root_fd, "")

                return writer.detach_spool()
            except Exception:
                writer.close()
                raise
            finally:
                if root_fd is not None:
                    os.close(root_fd)


class SecureTarImporter:
    """Validates and extracts untrusted tar streams without tarfile.extractall()."""

    def __init__(self, workspace_manager: WorkspaceManager) -> None:
        self.workspace_manager = workspace_manager
        self.config = workspace_manager.config

    @staticmethod
    def _validate_raw_member_name(raw_name: str) -> None:
        """Reject control characters, null bytes, drive prefixes, and parent traversal."""
        if not raw_name:
            raise PathTraversalError("Archive entry has empty name")
        for ch in raw_name:
            code = ord(ch)
            if code < 32 or code == 127:
                raise PathTraversalError("Archive entry contains control characters or null bytes")
        if "\\" in raw_name or ":" in raw_name:
            raise PathTraversalError(
                "Archive entry contains backslashes or drive letter separators"
            )
        parts = raw_name.split("/")
        if ".." in parts:
            raise PathTraversalError("Parent directory traversal ('..') in archive entry")

    @staticmethod
    def _validate_pax_headers(pax_headers: dict[str, str], *, is_global: bool = False) -> None:
        """Validate PAX extended or global header dictionaries."""
        if not pax_headers:
            return
        if "linkpath" in pax_headers:
            raise PathTraversalError("PAX linkpath header rejected in archive")
        if is_global and "path" in pax_headers:
            raise PathTraversalError("Global PAX path override rejected in archive")
        for pk, pv in pax_headers.items():
            if not isinstance(pk, str) or not isinstance(pv, str):
                raise PathTraversalError("Malformed PAX extended header key or value")
            if any(ord(c) < 32 or ord(c) == 127 for c in pk + pv):
                raise PathTraversalError("Control characters or null bytes in PAX extended headers")

    def import_archive(
        self,
        sandbox_id: str,
        archive_source: bytes | IO[bytes] | Iterable[bytes],
        *,
        strip_root_prefix: str | None = None,
        acquire_lock: bool = True,
    ) -> None:
        """Validate complete archive in a staging directory and atomically commit on success."""
        self.workspace_manager._validate_sandbox_id(sandbox_id)

        lock_ctx = (
            self.workspace_manager.sandbox_lock(sandbox_id, exclusive=True)
            if acquire_lock
            else contextlib.nullcontext()
        )

        with lock_ctx:
            self.workspace_manager.recover_interrupted_commit(sandbox_id)
            staging_path = (
                self.workspace_manager.base_dir / f".staging.{sandbox_id}.{uuid.uuid4().hex}"
            )
            staging_path.mkdir(mode=0o700, parents=False, exist_ok=False)
            with contextlib.suppress(OSError):
                os.chmod(staging_path, 0o700)

            staging_root_fd = os.open(
                str(staging_path),
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )

            try:
                self._extract_to_staging_fd(
                    staging_root_fd,
                    archive_source,
                    strip_root_prefix=strip_root_prefix,
                )
                fsync_directory_fd(staging_root_fd)
            except Exception:
                os.close(staging_root_fd)
                if staging_path.exists() or staging_path.is_symlink():
                    with contextlib.suppress(OSError):
                        self.workspace_manager._remove_directory_tree(staging_path)
                raise

            os.close(staging_root_fd)
            self.workspace_manager.commit_staging_workspace(sandbox_id, staging_path)

    def _extract_to_staging_fd(
        self,
        staging_root_fd: int,
        archive_source: bytes | IO[bytes] | Iterable[bytes],
        *,
        strip_root_prefix: str | None = None,
    ) -> None:
        reader = _BoundedStreamReader(
            archive_source,
            max_bytes=self.config.MAX_ARCHIVE_BYTES,
        )

        entry_count = 0
        file_count = 0
        total_decompressed_bytes = 0
        max_decompressed = min(
            self.config.MAX_DECOMPRESSED_BYTES,
            self.config.MAX_WORKSPACE_SIZE_BYTES,
        )

        seen_explicit_entries: set[str] = set()
        all_dirs: set[str] = set()
        all_files: set[str] = set()

        try:
            with tarfile.open(fileobj=reader, mode="r|*") as tf:
                if getattr(tf, "pax_headers", None):
                    self._validate_pax_headers(tf.pax_headers, is_global=True)

                for member in tf:
                    if getattr(tf, "pax_headers", None):
                        self._validate_pax_headers(tf.pax_headers, is_global=True)
                    if member.pax_headers:
                        self._validate_pax_headers(member.pax_headers, is_global=False)

                    # Validate effective entry type and link target after PAX/GNU metadata
                    if member.linkname:
                        raise PathTraversalError(
                            f"Archive entry with link target rejected: "
                            f"'{member.name}' -> '{member.linkname}'"
                        )
                    if member.issym():
                        raise PathTraversalError(
                            f"Symlink entry rejected in archive: '{member.name}'"
                        )
                    if member.islnk():
                        raise PathTraversalError(
                            f"Hard link entry rejected in archive: '{member.name}'"
                        )
                    if member.isfifo():
                        raise PathTraversalError(f"FIFO entry rejected in archive: '{member.name}'")
                    if member.ischr() or member.isblk():
                        raise PathTraversalError(
                            f"Device file entry rejected in archive: '{member.name}'"
                        )
                    if member.type not in (
                        tarfile.REGTYPE,
                        tarfile.AREGTYPE,
                        tarfile.DIRTYPE,
                    ):
                        raise PathTraversalError(
                            f"Unsupported archive entry type {member.type!r} for '{member.name}'"
                        )

                    raw_name = member.name

                    # Python tarfile strips trailing '/' on DIRTYPE, turning TarInfo("/") into ""
                    if strip_root_prefix and raw_name == "" and member.isdir():
                        continue

                    self._validate_raw_member_name(raw_name)

                    # Handle root directory entries when strip_root_prefix is active
                    if strip_root_prefix:
                        if raw_name in (
                            strip_root_prefix,
                            f"{strip_root_prefix}/",
                            "/",
                            ".",
                            "./",
                        ):
                            if not member.isdir():
                                raise PathTraversalError(
                                    f"Archive root entry '{raw_name}' is not a directory"
                                )
                            continue
                        if raw_name.startswith("/"):
                            raise PathTraversalError(
                                f"Absolute path rejected in archive: '{raw_name}'"
                            )
                        prefix_with_slash = f"{strip_root_prefix}/"
                        if raw_name.startswith(prefix_with_slash):
                            rel_name = raw_name[len(prefix_with_slash) :]
                        else:
                            rel_name = raw_name
                    else:
                        if raw_name in (".", "./") and member.isdir():
                            continue
                        if raw_name.startswith("/"):
                            raise PathTraversalError(
                                f"Absolute path rejected in archive: '{raw_name}'"
                            )
                        rel_name = raw_name

                    if member.isdir():
                        rel_name = rel_name.rstrip("/")
                        if not rel_name:
                            continue
                    else:
                        if rel_name.endswith("/"):
                            raise PathTraversalError(
                                f"Regular file archive entry cannot end with '/': '{raw_name}'"
                            )

                    if rel_name.startswith("/") or "//" in rel_name:
                        raise PathTraversalError(
                            f"Malformed or absolute path in archive: '{raw_name}'"
                        )

                    raw_segments = rel_name.split("/")
                    if any(seg in ("", ".", "..") for seg in raw_segments):
                        raise PathTraversalError(
                            f"Invalid relative path segments in archive: '{raw_name}'"
                        )

                    components = self.workspace_manager.parse_and_validate_path(rel_name)
                    norm_path = "/".join(components)

                    if norm_path in seen_explicit_entries:
                        raise PathTraversalError(f"Duplicate path in archive: '{norm_path}'")
                    seen_explicit_entries.add(norm_path)

                    for idx in range(1, len(components)):
                        ancestor = "/".join(components[:idx])
                        if ancestor in all_files:
                            raise PathTraversalError(
                                f"Conflicting file and directory path in archive at '{ancestor}'"
                            )
                        all_dirs.add(ancestor)

                    entry_count += 1
                    if entry_count > self.config.MAX_ARCHIVE_ENTRIES:
                        raise FileQuotaExceededError(
                            f"Archive entry count exceeds limit ({self.config.MAX_ARCHIVE_ENTRIES})"
                        )

                    if member.isdir():
                        if norm_path in all_files:
                            raise PathTraversalError(
                                f"Conflicting file and directory path in archive at '{norm_path}'"
                            )
                        all_dirs.add(norm_path)

                        parent_fd, leaf_name = self.workspace_manager._traverse_to_parent(
                            staging_root_fd,
                            components,
                            create_parents=True,
                        )
                        try:
                            try:
                                os.mkdir(leaf_name, mode=0o700, dir_fd=parent_fd)
                                fsync_directory_fd(parent_fd)
                            except FileExistsError as exc:
                                st = os.stat(leaf_name, dir_fd=parent_fd, follow_symlinks=False)
                                if not stat.S_ISDIR(st.st_mode):
                                    raise PathTraversalError(
                                        f"Path conflict at '{norm_path}'"
                                    ) from exc
                        finally:
                            os.close(parent_fd)

                    else:
                        if norm_path in all_dirs:
                            raise PathTraversalError(
                                f"Conflicting directory and file path in archive at '{norm_path}'"
                            )
                        all_files.add(norm_path)

                        file_count += 1
                        if file_count > self.config.MAX_FILE_COUNT:
                            raise FileQuotaExceededError(
                                f"Archive file count exceeds limit ({self.config.MAX_FILE_COUNT})"
                            )

                        if member.size < 0:
                            raise PathTraversalError(
                                f"Malformed negative size in archive for '{norm_path}'"
                            )
                        if member.size > self.config.MAX_FILE_SIZE_BYTES:
                            raise FileQuotaExceededError(
                                f"Archive member '{norm_path}' size {member.size} exceeds limit "
                                f"({self.config.MAX_FILE_SIZE_BYTES})"
                            )
                        if total_decompressed_bytes + member.size > max_decompressed:
                            projected = total_decompressed_bytes + member.size
                            raise FileQuotaExceededError(
                                f"Decompressed archive size {projected} "
                                f"exceeds limit ({max_decompressed})"
                            )

                        extracted_fobj = tf.extractfile(member)
                        if extracted_fobj is None:
                            raise PathTraversalError(
                                f"Unable to read payload for regular file entry '{norm_path}'"
                            )

                        parent_fd, leaf_name = self.workspace_manager._traverse_to_parent(
                            staging_root_fd,
                            components,
                            create_parents=True,
                        )
                        try:
                            file_fd = os.open(
                                leaf_name,
                                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                0o600,
                                dir_fd=parent_fd,
                            )
                            try:
                                member_bytes_written = 0
                                while True:
                                    chunk = extracted_fobj.read(STREAM_CHUNK_SIZE)
                                    if not chunk:
                                        break
                                    member_bytes_written += len(chunk)
                                    if member_bytes_written > self.config.MAX_FILE_SIZE_BYTES:
                                        raise FileQuotaExceededError(
                                            f"Archive member '{norm_path}' exceeds max file size "
                                            f"({self.config.MAX_FILE_SIZE_BYTES})"
                                        )
                                    total_decompressed_bytes += len(chunk)
                                    if total_decompressed_bytes > max_decompressed:
                                        raise FileQuotaExceededError(
                                            f"Decompressed archive size exceeds limit "
                                            f"({max_decompressed})"
                                        )
                                    write_all_to_fd(file_fd, chunk)

                                if member_bytes_written != member.size:
                                    raise PathTraversalError(
                                        f"Malformed archive payload size mismatch for '{norm_path}'"
                                    )
                                os.fsync(file_fd)
                            finally:
                                os.close(file_fd)
                            fsync_directory_fd(parent_fd)
                        finally:
                            os.close(parent_fd)

            # Drain any trailing bytes after the tar EOF marker so MAX_ARCHIVE_BYTES
            # is strictly enforced over the entire incoming stream.
            while reader.read(STREAM_CHUNK_SIZE):
                pass

        except (FileQuotaExceededError, PathTraversalError):
            raise
        except (tarfile.TarError, EOFError, zlib.error, lzma.LZMAError, OSError) as exc:
            raise PathTraversalError(f"Malformed or corrupted tar archive: {exc}") from exc
