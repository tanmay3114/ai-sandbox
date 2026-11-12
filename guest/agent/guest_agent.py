#!/usr/bin/env python3
"""Minimal guest execution agent for the AI Sandbox ARM64 Linux QEMU backend.

Communicates with the host over a dedicated virtio-serial channel (or Unix domain
socket in local tests) using the framed length-prefixed JSON + binary protocol.
Executes untrusted Python code strictly as unprivileged UID/GID 10001:10001 inside
a bounded /workspace filesystem with independent stdout/stderr capture and timeouts.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import platform
import resource
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO

PROTOCOL_VERSION = 1
FRAME_LEN_STRUCT = struct.Struct("!I")
MAX_HEADER_BYTES = 64 * 1024
MAX_CODE_PAYLOAD_BYTES = 2 * 1024 * 1024
STREAM_CHUNK_SIZE = 64 * 1024

DEFAULT_VIRTIO_PORTS = (
    Path("/dev/virtio-ports/org.aisandbox.agent"),
    Path("/dev/vport0p1"),
    Path("/dev/vport1p1"),
)

ALLOWED_OPERATIONS = frozenset(
    {
        "ping",
        "init",
        "inject_archive",
        "execute",
        "export_archive",
        "shutdown",
    }
)


class GuestProtocolViolation(Exception):
    """Raised when a host request frame is malformed or violates bounds."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _ChannelStream:
    """Uniform binary read/write wrapper over a raw file descriptor or socket."""

    def __init__(self, fd: int | None = None, sock: socket.socket | None = None) -> None:
        if fd is None and sock is None:
            raise ValueError("Either fd or sock is required")
        self._fd = fd
        self._sock = sock
        if fd is not None:
            os.set_inheritable(fd, False)
        if sock is not None:
            os.set_inheritable(sock.fileno(), False)

    def read_exact(self, num_bytes: int) -> bytes:
        if num_bytes <= 0:
            return b""
        buf = bytearray()
        while len(buf) < num_bytes:
            to_read = min(STREAM_CHUNK_SIZE, num_bytes - len(buf))
            if self._sock is not None:
                chunk = self._sock.recv(to_read)
            else:
                assert self._fd is not None
                chunk = os.read(self._fd, to_read)
            if not chunk:
                raise EOFError(f"Channel EOF after {len(buf)} of {num_bytes} bytes")
            buf.extend(chunk)
        return bytes(buf)

    def write_all(self, data: bytes | memoryview) -> None:
        view = memoryview(data)
        total = len(view)
        sent = 0
        while sent < total:
            chunk = view[sent : sent + STREAM_CHUNK_SIZE]
            if self._sock is not None:
                n = self._sock.send(chunk)
            else:
                assert self._fd is not None
                n = os.write(self._fd, chunk)
            if n <= 0:
                raise BrokenPipeError("Channel closed during write")
            sent += n

    def close(self) -> None:
        if self._sock is not None:
            with contextlib.suppress(Exception):
                self._sock.close()
        if self._fd is not None:
            with contextlib.suppress(Exception):
                os.close(self._fd)


def _validate_relative_tar_path(raw_name: str, max_depth: int = 8, max_len: int = 255) -> str:
    """Validate and normalize a tar member path, rejecting traversal or absolute paths."""
    cleaned = raw_name.strip()
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    if not cleaned or cleaned in {".", "/"}:
        return ""
    if "\x00" in cleaned or cleaned.startswith("/") or "\\" in cleaned:
        raise GuestProtocolViolation("SECURITY_VIOLATION", f"Forbidden archive path: {raw_name}")
    if len(cleaned) > max_len:
        raise GuestProtocolViolation("QUOTA_EXCEEDED", "Archive path exceeds maximum length")
    parts = [p for p in cleaned.split("/") if p]
    if not parts or any(p in {".", ".."} for p in parts):
        raise GuestProtocolViolation("SECURITY_VIOLATION", f"Traversal component in: {raw_name}")
    if len(parts) > max_depth:
        raise GuestProtocolViolation("QUOTA_EXCEEDED", "Archive directory depth limit exceeded")
    return "/".join(parts)


def _read_stream_bounded(
    pipe: BinaryIO,
    max_bytes: int,
    out_chunks: list[bytes],
    truncated_flag: list[bool],
) -> None:
    """Read a subprocess pipe up to max_bytes and drain excess output to avoid deadlock."""
    collected = 0
    try:
        while True:
            chunk = pipe.read(4096)
            if not chunk:
                break
            if collected < max_bytes:
                remaining = max_bytes - collected
                if len(chunk) <= remaining:
                    out_chunks.append(chunk)
                    collected += len(chunk)
                else:
                    out_chunks.append(chunk[:remaining])
                    collected = max_bytes
                    truncated_flag[0] = True
            else:
                truncated_flag[0] = True
    except Exception:
        pass
    finally:
        with contextlib.suppress(Exception):
            pipe.close()


class GuestExecutionAgent:
    """Stateful guest execution agent handling a single VM session."""

    def __init__(
        self,
        workspace_dir: Path = Path("/workspace"),
        *,
        drop_privileges: bool | None = None,
    ) -> None:
        self.workspace_dir = workspace_dir.resolve()
        self.workspace_size_bytes = 25 * 1024 * 1024
        self.max_file_size_bytes = 5 * 1024 * 1024
        self.max_file_count = 250
        self.pids_limit = 32
        self.run_as_uid = 10001
        self.run_as_gid = 10001
        self.should_shutdown = False
        self._drop_privileges = (os.geteuid() == 0) if drop_privileges is None else drop_privileges

    def _prepare_workspace_filesystem(self) -> bool:
        """Mount or reset the bounded /workspace directory with strict permissions."""
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        mounted_tmpfs = False

        if os.geteuid() == 0 and platform.system().lower() == "linux":
            inodes = max(64, self.max_file_count + 64)
            mount_opts = (
                f"size={self.workspace_size_bytes},"
                f"nr_inodes={inodes},"
                f"mode=0700,"
                f"uid={self.run_as_uid},"
                f"gid={self.run_as_gid},"
                "nosuid,nodev"
            )
            subprocess.run(
                ["umount", "-f", str(self.workspace_dir)],
                capture_output=True,
                check=False,
            )
            proc = subprocess.run(
                ["mount", "-t", "tmpfs", "-o", mount_opts, "tmpfs", str(self.workspace_dir)],
                capture_output=True,
                text=True,
                check=False,
            )
            mounted_tmpfs = proc.returncode == 0

        if not mounted_tmpfs:
            # Clear any existing contents inside workspace_dir
            for entry in list(self.workspace_dir.iterdir()):
                if entry.is_symlink() or entry.is_file():
                    entry.unlink()
                elif entry.is_dir():
                    shutil.rmtree(entry)

        os.chmod(self.workspace_dir, 0o700)
        if self._drop_privileges:
            os.chown(self.workspace_dir, self.run_as_uid, self.run_as_gid)
        return mounted_tmpfs

    def handle_ping(self) -> dict[str, Any]:
        return {
            "agent_version": PROTOCOL_VERSION,
            "arch": platform.machine(),
            "python_version": platform.python_version(),
        }

    def handle_init(self, params: dict[str, Any]) -> dict[str, Any]:
        self.workspace_size_bytes = int(
            params.get("workspace_size_bytes", self.workspace_size_bytes)
        )
        self.max_file_size_bytes = int(params.get("max_file_size_bytes", self.max_file_size_bytes))
        self.max_file_count = int(params.get("max_file_count", self.max_file_count))
        self.pids_limit = int(params.get("pids_limit", self.pids_limit))
        self.run_as_uid = int(params.get("run_as_uid", self.run_as_uid))
        self.run_as_gid = int(params.get("run_as_gid", self.run_as_gid))

        if self.workspace_size_bytes <= 0 or self.max_file_size_bytes <= 0:
            raise GuestProtocolViolation("INVALID_PARAMS", "Workspace limits must be positive")
        if self.run_as_uid <= 0 or self.run_as_gid <= 0:
            raise GuestProtocolViolation(
                "SECURITY_VIOLATION",
                "Guest execution user must be non-root (UID/GID > 0)",
            )

        mounted = self._prepare_workspace_filesystem()
        return {
            "agent_version": PROTOCOL_VERSION,
            "arch": platform.machine(),
            "workspace_tmpfs_mounted": mounted,
            "run_as_uid": self.run_as_uid,
            "run_as_gid": self.run_as_gid,
        }

    def handle_inject_archive(self, payload: bytes) -> dict[str, Any]:
        """Extract verified regular files and directories from tar payload into /workspace."""
        if len(payload) > max(self.workspace_size_bytes * 2, 64 * 1024):
            raise GuestProtocolViolation("QUOTA_EXCEEDED", "Archive payload exceeds size limit")

        total_bytes = 0
        file_count = 0

        try:
            with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as tf:
                for member in tf:
                    rel_path = _validate_relative_tar_path(member.name)
                    if not rel_path:
                        continue

                    if member.issym() or member.islnk() or member.isfifo() or member.isdev():
                        raise GuestProtocolViolation(
                            "SECURITY_VIOLATION",
                            f"Forbidden archive entry type for '{rel_path}'",
                        )

                    target = (self.workspace_dir / rel_path).resolve()
                    if target != self.workspace_dir and self.workspace_dir not in target.parents:
                        raise GuestProtocolViolation(
                            "SECURITY_VIOLATION",
                            f"Path traversal detected for '{rel_path}'",
                        )

                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                        os.chmod(target, 0o700)
                        if self._drop_privileges:
                            os.chown(target, self.run_as_uid, self.run_as_gid)
                    elif member.isreg():
                        file_count += 1
                        if file_count > self.max_file_count:
                            raise GuestProtocolViolation(
                                "QUOTA_EXCEEDED",
                                f"Workspace file count exceeds {self.max_file_count}",
                            )
                        if member.size < 0 or member.size > self.max_file_size_bytes:
                            raise GuestProtocolViolation(
                                "QUOTA_EXCEEDED",
                                f"File '{rel_path}' exceeds max_file_size_bytes",
                            )
                        total_bytes += member.size
                        if total_bytes > self.workspace_size_bytes:
                            raise GuestProtocolViolation(
                                "QUOTA_EXCEEDED",
                                "Cumulative workspace size exceeds limit",
                            )

                        target.parent.mkdir(parents=True, exist_ok=True)
                        for parent in target.parents:
                            if (
                                parent == self.workspace_dir
                                or self.workspace_dir not in parent.parents
                            ):
                                break
                            os.chmod(parent, 0o700)
                            if self._drop_privileges:
                                os.chown(parent, self.run_as_uid, self.run_as_gid)

                        src = tf.extractfile(member)
                        if src is None:
                            raise GuestProtocolViolation(
                                "INVALID_ARCHIVE",
                                f"Missing file data for '{rel_path}'",
                            )
                        fd = os.open(
                            target,
                            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
                            0o600,
                        )
                        try:
                            written = 0
                            while True:
                                chunk = src.read(STREAM_CHUNK_SIZE)
                                if not chunk:
                                    break
                                written += len(chunk)
                                if written > self.max_file_size_bytes:
                                    raise GuestProtocolViolation(
                                        "QUOTA_EXCEEDED",
                                        f"File '{rel_path}' exceeded size limit while extracting",
                                    )
                                os.write(fd, chunk)
                            if self._drop_privileges:
                                os.fchown(fd, self.run_as_uid, self.run_as_gid)
                            os.fchmod(fd, 0o600)
                        finally:
                            os.close(fd)
                            src.close()
                    else:
                        raise GuestProtocolViolation(
                            "SECURITY_VIOLATION",
                            f"Unsupported tar entry type for '{rel_path}'",
                        )
        except GuestProtocolViolation:
            raise
        except tarfile.TarError as exc:
            raise GuestProtocolViolation("INVALID_ARCHIVE", f"Invalid tar archive: {exc}") from exc
        except OSError as exc:
            raise GuestProtocolViolation("QUOTA_EXCEEDED", f"Filesystem error: {exc}") from exc

        return {"files_injected": file_count, "bytes_injected": total_bytes}

    def handle_execute(
        self,
        code_bytes: bytes,
        params: dict[str, Any],
    ) -> tuple[dict[str, Any], bytes]:
        """Execute Python code in /workspace as unprivileged user with resource and time bounds."""
        try:
            code = code_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GuestProtocolViolation(
                "INVALID_CODE", f"Invalid UTF-8 code payload: {exc}"
            ) from exc

        timeout_seconds = float(params.get("timeout_seconds", 5.0))
        max_stdout_bytes = int(params.get("max_stdout_bytes", 65536))
        max_stderr_bytes = int(params.get("max_stderr_bytes", 65536))

        if timeout_seconds <= 0 or max_stdout_bytes <= 0 or max_stderr_bytes <= 0:
            raise GuestProtocolViolation("INVALID_PARAMS", "Execution bounds must be positive")

        fsize_limit = min(self.max_file_size_bytes, self.workspace_size_bytes)
        pids_limit = self.pids_limit
        uid = self.run_as_uid
        gid = self.run_as_gid
        drop_privs = self._drop_privileges

        def _preexec() -> None:
            os.setsid()
            os.umask(0o077)
            with contextlib.suppress(Exception):
                resource.setrlimit(resource.RLIMIT_FSIZE, (fsize_limit, fsize_limit))
            if drop_privs:
                try:
                    os.setgroups([])
                    os.setgid(gid)
                    os.setuid(uid)
                except Exception:
                    os._exit(126)
                if os.geteuid() != uid or os.getegid() != gid:
                    os._exit(126)
                with contextlib.suppress(Exception):
                    if hasattr(resource, "RLIMIT_NPROC"):
                        resource.setrlimit(resource.RLIMIT_NPROC, (pids_limit, pids_limit))

        env = {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            "HOME": str(self.workspace_dir),
            "PATH": "/usr/local/bin:/usr/bin:/bin",
        }

        proc = subprocess.Popen(
            [sys.executable, "-c", code],
            cwd=str(self.workspace_dir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            preexec_fn=_preexec,
            close_fds=True,
        )

        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        stdout_truncated = [False]
        stderr_truncated = [False]

        assert proc.stdout is not None
        assert proc.stderr is not None

        t_out = threading.Thread(
            target=_read_stream_bounded,
            args=(proc.stdout, max_stdout_bytes, stdout_chunks, stdout_truncated),
            daemon=True,
        )
        t_err = threading.Thread(
            target=_read_stream_bounded,
            args=(proc.stderr, max_stderr_bytes, stderr_chunks, stderr_truncated),
            daemon=True,
        )
        t_out.start()
        t_err.start()

        timed_out = False
        exit_code: int | None = None
        try:
            exit_code = proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = None
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, signal.SIGKILL)
            with contextlib.suppress(Exception):
                proc.kill()
            with contextlib.suppress(Exception):
                proc.wait(timeout=1.0)
        finally:
            # Always clean up any background child processes in the process group
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, signal.SIGKILL)

        t_out.join(timeout=1.0)
        t_err.join(timeout=1.0)

        stdout_bytes = b"".join(stdout_chunks)
        stderr_bytes = b"".join(stderr_chunks)
        payload = stdout_bytes + stderr_bytes

        result = {
            "exit_code": exit_code,
            "timed_out": timed_out,
            "stdout_length": len(stdout_bytes),
            "stderr_length": len(stderr_bytes),
            "stdout_truncated": stdout_truncated[0],
            "stderr_truncated": stderr_truncated[0],
        }
        return result, payload

    def handle_export_archive(self, params: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
        """Serialize /workspace into a validated PAX tar archive rooted at 'workspace/'."""
        max_archive_bytes = int(params.get("max_archive_bytes", self.workspace_size_bytes))
        buf = io.BytesIO()
        total_bytes = 0
        file_count = 0
        now_ts = int(time.time())

        with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tf:
            root_info = tarfile.TarInfo("workspace")
            root_info.type = tarfile.DIRTYPE
            root_info.uid = self.run_as_uid
            root_info.gid = self.run_as_gid
            root_info.uname = "sandbox"
            root_info.gname = "sandbox"
            root_info.mode = 0o700
            root_info.mtime = now_ts
            tf.addfile(root_info)

            for dirpath, dirnames, filenames in os.walk(self.workspace_dir, followlinks=False):
                dirnames.sort()
                filenames.sort()
                current_dir = Path(dirpath)

                for name in dirnames:
                    full_path = current_dir / name
                    st = os.lstat(full_path)
                    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
                        raise GuestProtocolViolation(
                            "SECURITY_VIOLATION",
                            f"Forbidden non-directory entry '{name}' in workspace",
                        )
                    rel = full_path.relative_to(self.workspace_dir).as_posix()
                    _validate_relative_tar_path(rel)
                    info = tarfile.TarInfo(f"workspace/{rel}")
                    info.type = tarfile.DIRTYPE
                    info.uid = self.run_as_uid
                    info.gid = self.run_as_gid
                    info.uname = "sandbox"
                    info.gname = "sandbox"
                    info.mode = 0o700
                    info.mtime = int(st.st_mtime)
                    tf.addfile(info)

                for name in filenames:
                    full_path = current_dir / name
                    st = os.lstat(full_path)
                    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                        raise GuestProtocolViolation(
                            "SECURITY_VIOLATION",
                            f"Forbidden non-regular file '{name}' in workspace",
                        )
                    if st.st_nlink > 1:
                        raise GuestProtocolViolation(
                            "SECURITY_VIOLATION",
                            f"Hardlinked file '{name}' is forbidden in workspace",
                        )
                    file_count += 1
                    if file_count > self.max_file_count:
                        raise GuestProtocolViolation(
                            "QUOTA_EXCEEDED",
                            f"Workspace file count ({file_count}) exceeds "
                            f"limit ({self.max_file_count})",
                        )
                    if st.st_size > self.max_file_size_bytes:
                        raise GuestProtocolViolation(
                            "QUOTA_EXCEEDED",
                            f"Workspace file '{name}' exceeds max_file_size_bytes",
                        )
                    total_bytes += st.st_size
                    if total_bytes > self.workspace_size_bytes:
                        raise GuestProtocolViolation(
                            "QUOTA_EXCEEDED",
                            "Cumulative workspace size exceeds max_workspace_size_bytes",
                        )

                    rel = full_path.relative_to(self.workspace_dir).as_posix()
                    _validate_relative_tar_path(rel)
                    info = tarfile.TarInfo(f"workspace/{rel}")
                    info.type = tarfile.REGTYPE
                    info.size = st.st_size
                    info.uid = self.run_as_uid
                    info.gid = self.run_as_gid
                    info.uname = "sandbox"
                    info.gname = "sandbox"
                    info.mode = 0o600
                    info.mtime = int(st.st_mtime)

                    with full_path.open("rb") as f_obj:
                        tf.addfile(info, fileobj=f_obj)

                    if buf.tell() > max_archive_bytes:
                        raise GuestProtocolViolation(
                            "QUOTA_EXCEEDED",
                            "Serialized workspace archive exceeds max_archive_bytes",
                        )

        archive_bytes = buf.getvalue()
        if len(archive_bytes) > max_archive_bytes:
            raise GuestProtocolViolation(
                "QUOTA_EXCEEDED",
                "Serialized workspace archive exceeds max_archive_bytes",
            )
        return {"files_exported": file_count, "bytes_exported": total_bytes}, archive_bytes

    def process_one_request(self, channel: _ChannelStream) -> bool:
        """Read one framed request from channel, execute it, and write the framed response."""
        raw_len = channel.read_exact(FRAME_LEN_STRUCT.size)
        (header_len,) = FRAME_LEN_STRUCT.unpack(raw_len)
        if header_len <= 0 or header_len > MAX_HEADER_BYTES:
            raise GuestProtocolViolation(
                "HEADER_TOO_LARGE",
                f"Header length {header_len} out of bounds",
            )

        raw_header = channel.read_exact(header_len)
        try:
            header = json.loads(raw_header.decode("utf-8"))
        except Exception as exc:
            raise GuestProtocolViolation("INVALID_JSON", f"Malformed header JSON: {exc}") from exc

        version = header.get("version")
        request_id = str(header.get("request_id", ""))
        op = str(header.get("op", ""))
        payload_length = int(header.get("payload_length", 0))
        params = header.get("params") or {}

        if version != PROTOCOL_VERSION or not request_id or op not in ALLOWED_OPERATIONS:
            self._send_response(
                channel,
                request_id=request_id or "invalid",
                op=op if op in ALLOWED_OPERATIONS else "ping",
                status="error",
                error={"code": "INVALID_REQUEST", "message": "Unsupported version or operation"},
            )
            return not self.should_shutdown

        max_payload = max(self.workspace_size_bytes * 2, MAX_CODE_PAYLOAD_BYTES)
        if payload_length < 0 or payload_length > max_payload:
            self._send_response(
                channel,
                request_id=request_id,
                op=op,
                status="error",
                error={"code": "QUOTA_EXCEEDED", "message": "Request payload_length exceeds limit"},
            )
            return False

        payload = channel.read_exact(payload_length) if payload_length > 0 else b""

        try:
            resp_payload = b""
            if op == "ping":
                result = self.handle_ping()
            elif op == "init":
                result = self.handle_init(params)
            elif op == "inject_archive":
                result = self.handle_inject_archive(payload)
            elif op == "execute":
                result, resp_payload = self.handle_execute(payload, params)
            elif op == "export_archive":
                result, resp_payload = self.handle_export_archive(params)
            elif op == "shutdown":
                self.should_shutdown = True
                result = {"shutting_down": True}
            else:
                raise GuestProtocolViolation("UNSUPPORTED_OP", f"Unsupported op '{op}'")

            self._send_response(
                channel,
                request_id=request_id,
                op=op,
                status="ok",
                result=result,
                payload=resp_payload,
            )
        except GuestProtocolViolation as exc:
            self._send_response(
                channel,
                request_id=request_id,
                op=op,
                status="error",
                error={"code": exc.code, "message": exc.message},
            )
        except Exception as exc:
            self._send_response(
                channel,
                request_id=request_id,
                op=op,
                status="error",
                error={"code": "INTERNAL_ERROR", "message": str(exc)},
            )

        return not self.should_shutdown

    @staticmethod
    def _send_response(
        channel: _ChannelStream,
        *,
        request_id: str,
        op: str,
        status: str,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        payload: bytes = b"",
    ) -> None:
        header_bytes = json.dumps(
            {
                "version": PROTOCOL_VERSION,
                "request_id": request_id,
                "op": op,
                "status": status,
                "payload_length": len(payload),
                "result": result or {},
                "error": error,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        channel.write_all(FRAME_LEN_STRUCT.pack(len(header_bytes)) + header_bytes)
        if payload:
            channel.write_all(payload)


def _open_virtio_channel() -> _ChannelStream:
    """Wait for and open the virtio-serial character device inside the Linux VM."""
    for _ in range(200):
        for candidate in DEFAULT_VIRTIO_PORTS:
            if candidate.exists():
                if os.geteuid() == 0:
                    with contextlib.suppress(OSError):
                        os.chown(candidate, 0, 0)
                        os.chmod(candidate, 0o600)
                fd = os.open(candidate, os.O_RDWR | getattr(os, "O_CLOEXEC", 0))
                return _ChannelStream(fd=fd)
        time.sleep(0.05)
    raise RuntimeError("Virtio-serial port for guest agent not found")


def serve_unix_socket(
    socket_path: Path,
    workspace_dir: Path,
    *,
    drop_privileges: bool = False,
) -> None:
    """Run the guest agent listening on a local Unix domain socket (used for host-side testing)."""
    if socket_path.exists():
        socket_path.unlink()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    os.set_inheritable(server.fileno(), False)
    server.bind(str(socket_path))
    os.chmod(socket_path, 0o600)
    server.listen(1)

    agent = GuestExecutionAgent(workspace_dir=workspace_dir, drop_privileges=drop_privileges)
    try:
        conn, _ = server.accept()
        channel = _ChannelStream(sock=conn)
        try:
            while agent.process_one_request(channel):
                pass
        except EOFError:
            pass
        finally:
            channel.close()
    finally:
        server.close()
        with contextlib.suppress(OSError):
            socket_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description="AI Sandbox QEMU Guest Execution Agent")
    parser.add_argument(
        "--workspace-dir",
        type=Path,
        default=Path("/workspace"),
        help="Path to guest workspace directory",
    )
    parser.add_argument(
        "--unix-socket",
        type=Path,
        default=None,
        help="Optional Unix domain socket path for local integration testing",
    )
    parser.add_argument(
        "--no-drop-privileges",
        action="store_true",
        help="Disable UID/GID privilege drop when running unprivileged local socket tests",
    )
    args = parser.parse_args()

    if args.unix_socket is not None:
        serve_unix_socket(
            args.unix_socket,
            args.workspace_dir,
            drop_privileges=not args.no_drop_privileges and os.geteuid() == 0,
        )
        return 0

    agent = GuestExecutionAgent(
        workspace_dir=args.workspace_dir,
        drop_privileges=not args.no_drop_privileges,
    )
    channel = _open_virtio_channel()
    try:
        while agent.process_one_request(channel):
            pass
    except EOFError:
        pass
    finally:
        channel.close()

    if os.geteuid() == 0 and platform.system().lower() == "linux":
        os.sync()
        subprocess.run(["/sbin/poweroff", "-f"], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
