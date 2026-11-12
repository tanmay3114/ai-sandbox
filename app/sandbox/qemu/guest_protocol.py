"""Framed host-to-guest communication protocol over a private Unix domain socket."""

from __future__ import annotations

import io
import json
import socket
import struct
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

from app.core.exceptions import (
    FileQuotaExceededError,
    QemuAgentTimeoutError,
    QemuProtocolError,
)
from app.sandbox.archive import STREAM_CHUNK_SIZE, _BoundedSpoolWriter

PROTOCOL_VERSION = 1
FRAME_LEN_STRUCT = struct.Struct("!I")
MAX_HEADER_BYTES = 64 * 1024  # 64 KiB hard cap on JSON control headers
MAX_CODE_PAYLOAD_BYTES = 2 * 1024 * 1024  # 2 MiB hard cap on UTF-8 Python source code

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


@dataclass(frozen=True, slots=True)
class ProtocolRequest:
    """Validated host-to-guest request header."""

    op: str
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    version: int = PROTOCOL_VERSION
    payload_length: int = 0
    params: dict[str, Any] = field(default_factory=dict)

    def validate(self, max_payload_bytes: int) -> None:
        if self.version != PROTOCOL_VERSION:
            raise QemuProtocolError(
                f"Unsupported guest protocol version {self.version} (expected {PROTOCOL_VERSION})"
            )
        if (
            not self.request_id
            or not isinstance(self.request_id, str)
            or len(self.request_id) > 128
        ):
            raise QemuProtocolError("Invalid protocol request_id")
        if self.op not in ALLOWED_OPERATIONS:
            raise QemuProtocolError(f"Unsupported guest protocol operation '{self.op}'")
        if not isinstance(self.payload_length, int) or isinstance(self.payload_length, bool):
            raise QemuProtocolError("Protocol payload_length must be an integer")
        if self.payload_length < 0 or self.payload_length > max_payload_bytes:
            raise QemuProtocolError(
                f"Protocol payload_length {self.payload_length} exceeds limit of "
                f"{max_payload_bytes} bytes"
            )
        if not isinstance(self.params, dict):
            raise QemuProtocolError("Protocol params must be a JSON object")

    def to_header_bytes(self, max_payload_bytes: int) -> bytes:
        self.validate(max_payload_bytes=max_payload_bytes)
        body = json.dumps(
            {
                "version": self.version,
                "request_id": self.request_id,
                "op": self.op,
                "payload_length": self.payload_length,
                "params": self.params,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        if len(body) > MAX_HEADER_BYTES:
            raise QemuProtocolError(
                f"Serialized request header ({len(body)} bytes) exceeds "
                f"MAX_HEADER_BYTES ({MAX_HEADER_BYTES})"
            )
        return FRAME_LEN_STRUCT.pack(len(body)) + body


@dataclass(frozen=True, slots=True)
class ProtocolResponse:
    """Validated guest-to-host response header."""

    request_id: str
    op: str
    status: str
    version: int = PROTOCOL_VERSION
    payload_length: int = 0
    result: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None

    def validate(
        self,
        *,
        expected_request_id: str | None = None,
        expected_op: str | None = None,
        max_payload_bytes: int = 0,
    ) -> None:
        if self.version != PROTOCOL_VERSION:
            raise QemuProtocolError(
                f"Guest response version mismatch: got {self.version}, expected {PROTOCOL_VERSION}"
            )
        if not self.request_id or not isinstance(self.request_id, str):
            raise QemuProtocolError("Guest response is missing a valid request_id")
        if expected_request_id is not None and self.request_id != expected_request_id:
            raise QemuProtocolError(
                f"Guest response request_id mismatch: got '{self.request_id}', "
                f"expected '{expected_request_id}'"
            )
        if self.op not in ALLOWED_OPERATIONS:
            raise QemuProtocolError(f"Guest response contains invalid operation '{self.op}'")
        if expected_op is not None and self.op != expected_op:
            raise QemuProtocolError(
                f"Guest response operation mismatch: got '{self.op}', expected '{expected_op}'"
            )
        if self.status not in {"ok", "error"}:
            raise QemuProtocolError(f"Invalid guest response status '{self.status}'")
        if not isinstance(self.payload_length, int) or isinstance(self.payload_length, bool):
            raise QemuProtocolError("Guest response payload_length must be an integer")
        if self.payload_length < 0 or self.payload_length > max_payload_bytes:
            raise QemuProtocolError(
                f"Guest response payload_length {self.payload_length} exceeds limit of "
                f"{max_payload_bytes} bytes"
            )
        if not isinstance(self.result, dict):
            raise QemuProtocolError("Guest response result must be a JSON object")
        if self.error is not None and not isinstance(self.error, dict):
            raise QemuProtocolError("Guest response error field must be a JSON object or null")

    @classmethod
    def from_json_bytes(
        cls,
        raw: bytes,
        *,
        expected_request_id: str | None = None,
        expected_op: str | None = None,
        max_payload_bytes: int = 0,
    ) -> ProtocolResponse:
        if len(raw) == 0 or len(raw) > MAX_HEADER_BYTES:
            raise QemuProtocolError(
                f"Invalid response header size {len(raw)} (max {MAX_HEADER_BYTES})"
            )
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise QemuProtocolError(f"Malformed JSON in guest response header: {exc}") from exc
        if not isinstance(data, dict):
            raise QemuProtocolError("Guest response header must decode to a JSON object")

        resp = cls(
            version=data.get("version", -1),
            request_id=data.get("request_id", ""),
            op=data.get("op", ""),
            status=data.get("status", ""),
            payload_length=data.get("payload_length", -1),
            result=data.get("result") if data.get("result") is not None else {},
            error=data.get("error"),
        )
        resp.validate(
            expected_request_id=expected_request_id,
            expected_op=expected_op,
            max_payload_bytes=max_payload_bytes,
        )
        return resp


@dataclass(frozen=True, slots=True)
class GuestExecutionOutcome:
    """Result returned by the guest agent for a code execution request."""

    exit_code: int | None
    timed_out: bool
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool


def _remaining_timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise QemuAgentTimeoutError("Timed out communicating with QEMU guest agent")
    return remaining


def recv_exact_bounded(sock: socket.socket, num_bytes: int, deadline: float) -> bytes:
    """Read exactly num_bytes from sock before deadline, handling partial reads."""
    if num_bytes < 0:
        raise QemuProtocolError(f"Cannot read negative byte count: {num_bytes}")
    if num_bytes == 0:
        return b""

    buf = bytearray()
    while len(buf) < num_bytes:
        sock.settimeout(_remaining_timeout(deadline))
        to_read = min(STREAM_CHUNK_SIZE, num_bytes - len(buf))
        try:
            chunk = sock.recv(to_read)
        except TimeoutError as exc:
            raise QemuAgentTimeoutError(
                "Timed out waiting for bytes from QEMU guest agent"
            ) from exc
        except OSError as exc:
            raise QemuProtocolError(f"Socket read error from QEMU guest agent: {exc}") from exc
        if not chunk:
            raise QemuProtocolError(
                f"Unexpected EOF from QEMU guest agent (read {len(buf)} of {num_bytes} bytes)"
            )
        buf.extend(chunk)
    return bytes(buf)


def recv_stream_to_spool(
    sock: socket.socket,
    num_bytes: int,
    max_bytes: int,
    deadline: float,
) -> tempfile.SpooledTemporaryFile[bytes]:
    """Stream exactly num_bytes from sock into a bounded spooled temporary file."""
    if num_bytes < 0 or num_bytes > max_bytes:
        raise FileQuotaExceededError(
            f"Guest archive payload ({num_bytes} bytes) exceeds maximum allowed ({max_bytes} bytes)"
        )
    writer = _BoundedSpoolWriter(max_bytes=max_bytes)
    remaining = num_bytes
    try:
        while remaining > 0:
            sock.settimeout(_remaining_timeout(deadline))
            to_read = min(STREAM_CHUNK_SIZE, remaining)
            try:
                chunk = sock.recv(to_read)
            except TimeoutError as exc:
                raise QemuAgentTimeoutError(
                    "Timed out streaming workspace archive from QEMU guest agent"
                ) from exc
            except OSError as exc:
                raise QemuProtocolError(
                    f"Socket error streaming archive from QEMU guest agent: {exc}"
                ) from exc
            if not chunk:
                raise QemuProtocolError(
                    f"Truncated archive stream from QEMU guest agent "
                    f"({num_bytes - remaining} of {num_bytes} bytes received)"
                )
            writer.write(chunk)
            remaining -= len(chunk)
        return writer.detach_spool()
    except Exception:
        writer.close()
        raise


def send_all_bounded(sock: socket.socket, data: bytes | memoryview, deadline: float) -> None:
    """Write all bytes in data to sock before deadline, handling partial writes."""
    view = memoryview(data)
    total_sent = 0
    total_len = len(view)
    while total_sent < total_len:
        sock.settimeout(_remaining_timeout(deadline))
        try:
            sent = sock.send(view[total_sent : total_sent + STREAM_CHUNK_SIZE])
        except TimeoutError as exc:
            raise QemuAgentTimeoutError("Timed out sending bytes to QEMU guest agent") from exc
        except OSError as exc:
            raise QemuProtocolError(f"Socket write error to QEMU guest agent: {exc}") from exc
        if sent <= 0:
            raise QemuProtocolError("Socket connection closed while sending to QEMU guest agent")
        total_sent += sent


def send_stream_bounded(
    sock: socket.socket,
    stream: IO[bytes],
    expected_length: int,
    deadline: float,
) -> None:
    """Stream exactly expected_length bytes from a file-like object to sock in 64 KB chunks."""
    stream.seek(0)
    remaining = expected_length
    while remaining > 0:
        chunk = stream.read(min(STREAM_CHUNK_SIZE, remaining))
        if not chunk:
            raise QemuProtocolError(
                f"Archive stream ended early (remaining {remaining} of {expected_length} bytes)"
            )
        send_all_bounded(sock, chunk, deadline)
        remaining -= len(chunk)


def _measure_payload(
    payload: bytes | IO[bytes] | None, max_bytes: int
) -> tuple[int, IO[bytes] | None]:
    """Return exact byte length and optional stream handle for a request payload."""
    if payload is None:
        return 0, None
    if isinstance(payload, (bytes, bytearray, memoryview)):
        raw = bytes(payload)
        if len(raw) > max_bytes:
            raise FileQuotaExceededError(
                f"Payload size {len(raw)} exceeds maximum allowed {max_bytes} bytes"
            )
        return len(raw), io.BytesIO(raw)
    if hasattr(payload, "seek") and hasattr(payload, "tell"):
        payload.seek(0, io.SEEK_END)
        size = int(payload.tell())
        payload.seek(0)
        if size > max_bytes:
            raise FileQuotaExceededError(
                f"Payload size {size} exceeds maximum allowed {max_bytes} bytes"
            )
        return size, payload
    raise QemuProtocolError("Unsupported payload object type for guest protocol")


class GuestAgentClient:
    """Host-side client for communicating with the QEMU guest agent over a Unix domain socket."""

    def __init__(
        self,
        socket_path: Path,
        *,
        default_timeout_seconds: float = 5.0,
        max_archive_bytes: int = 25 * 1024 * 1024,
    ) -> None:
        self.socket_path = socket_path
        self.default_timeout_seconds = default_timeout_seconds
        self.max_archive_bytes = max_archive_bytes
        self._sock: socket.socket | None = None

    def connect(self, timeout_seconds: float | None = None) -> None:
        """Connect to the per-execution Unix domain socket."""
        timeout = timeout_seconds if timeout_seconds is not None else self.default_timeout_seconds
        deadline = time.monotonic() + timeout
        last_err: Exception | None = None

        while time.monotonic() < deadline:
            if self.socket_path.exists():
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    sock.settimeout(min(0.5, _remaining_timeout(deadline)))
                    sock.connect(str(self.socket_path))
                    self._sock = sock
                    return
                except Exception as exc:
                    last_err = exc
                    sock.close()
            time.sleep(0.02)

        raise QemuAgentTimeoutError(
            f"Timed out connecting to guest agent socket '{self.socket_path.name}': {last_err}"
        )

    def close(self) -> None:
        """Close the client socket idempotently."""
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            finally:
                self._sock = None

    def __enter__(self) -> GuestAgentClient:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def _require_socket(self) -> socket.socket:
        if self._sock is None:
            raise QemuProtocolError("GuestAgentClient is not connected")
        return self._sock

    def _read_response_header(
        self,
        sock: socket.socket,
        *,
        expected_request_id: str,
        expected_op: str,
        max_payload_bytes: int,
        deadline: float,
    ) -> ProtocolResponse:
        raw_len = recv_exact_bounded(sock, FRAME_LEN_STRUCT.size, deadline)
        (header_len,) = FRAME_LEN_STRUCT.unpack(raw_len)
        if header_len <= 0 or header_len > MAX_HEADER_BYTES:
            raise QemuProtocolError(
                f"Guest response header length {header_len} is out of bounds "
                f"(1..{MAX_HEADER_BYTES})"
            )
        raw_header = recv_exact_bounded(sock, header_len, deadline)
        resp = ProtocolResponse.from_json_bytes(
            raw_header,
            expected_request_id=expected_request_id,
            expected_op=expected_op,
            max_payload_bytes=max_payload_bytes,
        )
        if resp.status == "error":
            err_info = resp.error or {}
            err_code = err_info.get("code", "GUEST_ERROR")
            err_msg = err_info.get("message", "Guest agent reported an error")
            if err_code == "QUOTA_EXCEEDED":
                raise FileQuotaExceededError(f"Guest workspace quota exceeded: {err_msg}")
            raise QemuProtocolError(f"Guest agent error [{err_code}]: {err_msg}")
        return resp

    def wait_until_ready(
        self,
        *,
        boot_timeout_seconds: float,
        workspace_size_bytes: int,
        max_file_size_bytes: int,
        max_file_count: int,
        pids_limit: int,
        run_as_uid: int = 10001,
        run_as_gid: int = 10001,
        process_alive_check: Any | None = None,
    ) -> dict[str, Any]:
        """Connect to the guest agent and complete 'init' within boot_timeout_seconds."""
        deadline = time.monotonic() + boot_timeout_seconds
        last_exc: Exception | None = None

        while time.monotonic() < deadline:
            if process_alive_check is not None and not process_alive_check():
                raise QemuProtocolError("QEMU VM process exited before guest agent became ready")
            try:
                if self._sock is None:
                    self.connect(timeout_seconds=min(0.25, _remaining_timeout(deadline)))
                remaining = _remaining_timeout(deadline)
                return self.initialize_guest(
                    workspace_size_bytes=workspace_size_bytes,
                    max_file_size_bytes=max_file_size_bytes,
                    max_file_count=max_file_count,
                    pids_limit=pids_limit,
                    run_as_uid=run_as_uid,
                    run_as_gid=run_as_gid,
                    timeout_seconds=min(1.0, remaining),
                )
            except (QemuAgentTimeoutError, QemuProtocolError, OSError) as exc:
                last_exc = exc
                # Note: When QEMU owns the server socket via -chardev socket,server=on,
                # the host connects immediately while the guest kernel is still booting.
                # Only close and reconnect if the socket itself broke.
                if isinstance(exc, (QemuProtocolError, OSError)) and "Unexpected EOF" in str(exc):
                    self.close()
                time.sleep(0.03)

        raise QemuAgentTimeoutError(
            f"Guest agent did not become ready within {boot_timeout_seconds}s: {last_exc}"
        )

    def ping(self, timeout_seconds: float | None = None) -> dict[str, Any]:
        """Send a lightweight 'ping' request and return guest status telemetry."""
        timeout = timeout_seconds if timeout_seconds is not None else self.default_timeout_seconds
        deadline = time.monotonic() + timeout
        sock = self._require_socket()
        req = ProtocolRequest(op="ping")
        send_all_bounded(sock, req.to_header_bytes(max_payload_bytes=0), deadline)
        resp = self._read_response_header(
            sock,
            expected_request_id=req.request_id,
            expected_op="ping",
            max_payload_bytes=0,
            deadline=deadline,
        )
        return resp.result

    def initialize_guest(
        self,
        *,
        workspace_size_bytes: int,
        max_file_size_bytes: int,
        max_file_count: int,
        pids_limit: int,
        run_as_uid: int = 10001,
        run_as_gid: int = 10001,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Send 'init' to configure the guest's bounded /workspace tmpfs and execution limits."""
        timeout = timeout_seconds if timeout_seconds is not None else self.default_timeout_seconds
        deadline = time.monotonic() + timeout
        sock = self._require_socket()
        req = ProtocolRequest(
            op="init",
            params={
                "workspace_size_bytes": workspace_size_bytes,
                "max_file_size_bytes": max_file_size_bytes,
                "max_file_count": max_file_count,
                "pids_limit": pids_limit,
                "run_as_uid": run_as_uid,
                "run_as_gid": run_as_gid,
            },
        )
        send_all_bounded(sock, req.to_header_bytes(max_payload_bytes=0), deadline)
        resp = self._read_response_header(
            sock,
            expected_request_id=req.request_id,
            expected_op="init",
            max_payload_bytes=0,
            deadline=deadline,
        )
        return resp.result

    def inject_archive(
        self,
        archive_payload: bytes | IO[bytes],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Stream a serialized workspace tar archive into the guest's /workspace."""
        timeout = timeout_seconds if timeout_seconds is not None else self.default_timeout_seconds
        deadline = time.monotonic() + timeout
        sock = self._require_socket()

        payload_len, stream = _measure_payload(archive_payload, max_bytes=self.max_archive_bytes)
        req = ProtocolRequest(
            op="inject_archive",
            payload_length=payload_len,
        )
        send_all_bounded(
            sock,
            req.to_header_bytes(max_payload_bytes=self.max_archive_bytes),
            deadline,
        )
        if stream is not None and payload_len > 0:
            send_stream_bounded(sock, stream, payload_len, deadline)

        resp = self._read_response_header(
            sock,
            expected_request_id=req.request_id,
            expected_op="inject_archive",
            max_payload_bytes=0,
            deadline=deadline,
        )
        return resp.result

    def execute_code(
        self,
        code: str,
        *,
        timeout_seconds: float,
        max_stdout_bytes: int,
        max_stderr_bytes: int,
    ) -> GuestExecutionOutcome:
        """Execute untrusted Python code in the guest as UID/GID 10001 and return bounded output."""
        if not isinstance(code, str) or not code.strip():
            raise QemuProtocolError("Execution code must be a non-empty string")
        code_bytes = code.encode("utf-8")
        if len(code_bytes) > MAX_CODE_PAYLOAD_BYTES:
            raise QemuProtocolError(
                f"Execution code size ({len(code_bytes)} bytes) exceeds limit "
                f"({MAX_CODE_PAYLOAD_BYTES} bytes)"
            )

        # Allow host-side RPC margin beyond the guest-enforced execution timeout
        rpc_deadline = time.monotonic() + timeout_seconds + self.default_timeout_seconds
        sock = self._require_socket()
        req = ProtocolRequest(
            op="execute",
            payload_length=len(code_bytes),
            params={
                "timeout_seconds": timeout_seconds,
                "max_stdout_bytes": max_stdout_bytes,
                "max_stderr_bytes": max_stderr_bytes,
            },
        )
        send_all_bounded(
            sock,
            req.to_header_bytes(max_payload_bytes=MAX_CODE_PAYLOAD_BYTES),
            rpc_deadline,
        )
        send_all_bounded(sock, code_bytes, rpc_deadline)

        max_combined_output = max_stdout_bytes + max_stderr_bytes
        resp = self._read_response_header(
            sock,
            expected_request_id=req.request_id,
            expected_op="execute",
            max_payload_bytes=max_combined_output,
            deadline=rpc_deadline,
        )

        stdout_len = int(resp.result.get("stdout_length", 0))
        stderr_len = int(resp.result.get("stderr_length", 0))
        if (
            stdout_len < 0
            or stderr_len < 0
            or stdout_len > max_stdout_bytes
            or stderr_len > max_stderr_bytes
            or stdout_len + stderr_len != resp.payload_length
        ):
            raise QemuProtocolError(
                f"Invalid stdout/stderr lengths in guest execute response "
                f"(stdout={stdout_len}, stderr={stderr_len}, payload={resp.payload_length})"
            )

        raw_output = recv_exact_bounded(sock, resp.payload_length, rpc_deadline)
        stdout_bytes = raw_output[:stdout_len]
        stderr_bytes = raw_output[stdout_len : stdout_len + stderr_len]

        timed_out = bool(resp.result.get("timed_out", False))
        raw_exit_code = resp.result.get("exit_code")
        exit_code = None if timed_out or raw_exit_code is None else int(raw_exit_code)

        return GuestExecutionOutcome(
            exit_code=exit_code,
            timed_out=timed_out,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            stdout_truncated=bool(resp.result.get("stdout_truncated", False)),
            stderr_truncated=bool(resp.result.get("stderr_truncated", False)),
        )

    def export_archive(
        self,
        *,
        max_bytes: int | None = None,
        timeout_seconds: float | None = None,
    ) -> tempfile.SpooledTemporaryFile[bytes]:
        """Request workspace tar export from the guest and stream into a bounded spool."""
        effective_max = max_bytes if max_bytes is not None else self.max_archive_bytes
        timeout = timeout_seconds if timeout_seconds is not None else self.default_timeout_seconds
        deadline = time.monotonic() + timeout
        sock = self._require_socket()

        req = ProtocolRequest(
            op="export_archive",
            params={"max_archive_bytes": effective_max},
        )
        send_all_bounded(sock, req.to_header_bytes(max_payload_bytes=0), deadline)

        resp = self._read_response_header(
            sock,
            expected_request_id=req.request_id,
            expected_op="export_archive",
            max_payload_bytes=effective_max,
            deadline=deadline,
        )
        return recv_stream_to_spool(
            sock,
            num_bytes=resp.payload_length,
            max_bytes=effective_max,
            deadline=deadline,
        )

    def shutdown(self, timeout_seconds: float = 2.0) -> None:
        """Request graceful guest shutdown."""
        deadline = time.monotonic() + timeout_seconds
        sock = self._require_socket()
        req = ProtocolRequest(op="shutdown")
        send_all_bounded(sock, req.to_header_bytes(max_payload_bytes=0), deadline)
        self._read_response_header(
            sock,
            expected_request_id=req.request_id,
            expected_op="shutdown",
            max_payload_bytes=0,
            deadline=deadline,
        )
