"""Unit and live-socket tests for the framed QEMU host-to-guest protocol and guest agent."""

from __future__ import annotations

import io
import json
import os
import socket
import struct
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path

import pytest

from app.core.exceptions import (
    FileQuotaExceededError,
    QemuAgentTimeoutError,
    QemuProtocolError,
)
from app.sandbox.qemu.guest_protocol import (
    FRAME_LEN_STRUCT,
    MAX_HEADER_BYTES,
    PROTOCOL_VERSION,
    GuestAgentClient,
    ProtocolRequest,
    ProtocolResponse,
    recv_exact_bounded,
)


@pytest.fixture(autouse=True)
def verify_no_container_leak():
    """Protocol unit tests do not interact with Docker containers."""
    yield


def _make_short_socket_path() -> tuple[Path, Path]:
    """Create a short 0700 directory in /tmp to respect macOS 104-byte AF_UNIX path limit."""
    base = Path(f"/tmp/aisbx-test-{os.getuid()}-{os.urandom(4).hex()}")
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(base, 0o700)
    return base, base / "agent.sock"


def test_protocol_request_framing_and_validation():
    req = ProtocolRequest(op="ping", request_id="req-123")
    framed = req.to_header_bytes(max_payload_bytes=0)
    (header_len,) = FRAME_LEN_STRUCT.unpack(framed[:4])
    decoded = json.loads(framed[4 : 4 + header_len].decode("utf-8"))
    assert decoded == {
        "version": PROTOCOL_VERSION,
        "request_id": "req-123",
        "op": "ping",
        "payload_length": 0,
        "params": {},
    }

    with pytest.raises(QemuProtocolError, match="Unsupported guest protocol version"):
        ProtocolRequest(op="ping", version=99).validate(max_payload_bytes=0)

    with pytest.raises(QemuProtocolError, match="Unsupported guest protocol operation"):
        ProtocolRequest(op="shell_exec").validate(max_payload_bytes=0)

    with pytest.raises(QemuProtocolError, match="exceeds limit"):
        ProtocolRequest(op="inject_archive", payload_length=1025).validate(max_payload_bytes=1024)


def test_protocol_response_validation_and_mismatch_rejection():
    raw = json.dumps(
        {
            "version": 1,
            "request_id": "req-1",
            "op": "ping",
            "status": "ok",
            "payload_length": 0,
            "result": {"arch": "aarch64"},
        }
    ).encode("utf-8")

    resp = ProtocolResponse.from_json_bytes(
        raw,
        expected_request_id="req-1",
        expected_op="ping",
        max_payload_bytes=0,
    )
    assert resp.result["arch"] == "aarch64"

    # Request ID mismatch
    with pytest.raises(QemuProtocolError, match="request_id mismatch"):
        ProtocolResponse.from_json_bytes(
            raw,
            expected_request_id="req-other",
            expected_op="ping",
            max_payload_bytes=0,
        )

    # Operation mismatch
    with pytest.raises(QemuProtocolError, match="operation mismatch"):
        ProtocolResponse.from_json_bytes(
            raw,
            expected_request_id="req-1",
            expected_op="init",
            max_payload_bytes=0,
        )

    # Oversized payload length in header
    oversized = json.dumps(
        {
            "version": 1,
            "request_id": "req-1",
            "op": "export_archive",
            "status": "ok",
            "payload_length": 999999,
            "result": {},
        }
    ).encode("utf-8")
    with pytest.raises(QemuProtocolError, match="exceeds limit"):
        ProtocolResponse.from_json_bytes(
            oversized,
            expected_request_id="req-1",
            expected_op="export_archive",
            max_payload_bytes=1024,
        )

    # Malformed JSON
    with pytest.raises(QemuProtocolError, match="Malformed JSON"):
        ProtocolResponse.from_json_bytes(b"{not-json")

    # Oversized header (> 64 KiB)
    with pytest.raises(QemuProtocolError, match="Invalid response header size"):
        ProtocolResponse.from_json_bytes(b"x" * (MAX_HEADER_BYTES + 1))


def test_partial_socket_reads_and_writes():
    s1, s2 = socket.socketpair()
    try:
        payload = b"0123456789abcdef" * 2048  # 32 KiB

        def _trickle_sender() -> None:
            # Send in tiny irregular chunks to exercise partial read assembly
            view = memoryview(payload)
            idx = 0
            while idx < len(view):
                s1.send(view[idx : idx + 137])
                idx += 137
            s1.close()

        t = threading.Thread(target=_trickle_sender, daemon=True)
        t.start()

        deadline = time.monotonic() + 5.0
        received = recv_exact_bounded(s2, len(payload), deadline)
        assert received == payload
        t.join(timeout=2.0)
    finally:
        s1.close()
        s2.close()


def test_socket_read_timeout_and_unexpected_eof():
    s1, s2 = socket.socketpair()
    try:
        with pytest.raises(QemuAgentTimeoutError):
            recv_exact_bounded(s2, 16, time.monotonic() + 0.05)

        s1.send(b"abc")
        s1.close()
        with pytest.raises(QemuProtocolError, match="Unexpected EOF"):
            recv_exact_bounded(s2, 10, time.monotonic() + 1.0)
    finally:
        s1.close()
        s2.close()


def test_client_rejects_oversized_header_frame_from_socket():
    s1, s2 = socket.socketpair()
    try:
        client = GuestAgentClient(Path("/tmp/unused.sock"))
        client._sock = s2

        # Send a frame length header claiming 1 MiB (> MAX_HEADER_BYTES)
        s1.sendall(struct.pack("!I", 1024 * 1024))
        with pytest.raises(QemuProtocolError, match="out of bounds"):
            client._read_response_header(
                s2,
                expected_request_id="req-1",
                expected_op="ping",
                max_payload_bytes=0,
                deadline=time.monotonic() + 2.0,
            )
    finally:
        s1.close()
        s2.close()


def test_live_guest_agent_subprocess_end_to_end_over_unix_socket(tmp_path: Path):
    """Verify real guest_agent.py process over a live Unix socket on macOS ARM64."""
    sock_dir, sock_path = _make_short_socket_path()
    guest_ws = tmp_path / "guest_workspace"
    guest_ws.mkdir()

    agent_script = Path(__file__).resolve().parents[2] / "guest" / "agent" / "guest_agent.py"
    proc = subprocess.Popen(
        [
            sys.executable,
            str(agent_script),
            "--workspace-dir",
            str(guest_ws),
            "--unix-socket",
            str(sock_path),
            "--no-drop-privileges",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        with GuestAgentClient(
            sock_path,
            default_timeout_seconds=5.0,
            max_archive_bytes=5 * 1024 * 1024,
        ) as client:
            init_res = client.wait_until_ready(
                boot_timeout_seconds=5.0,
                workspace_size_bytes=5 * 1024 * 1024,
                max_file_size_bytes=1 * 1024 * 1024,
                max_file_count=50,
                pids_limit=32,
                process_alive_check=lambda: proc.poll() is None,
            )
            assert init_res["agent_version"] == PROTOCOL_VERSION

            ping_res = client.ping()
            assert "python_version" in ping_res

            # 1. Inject initial workspace archive containing input.txt
            in_buf = io.BytesIO()
            with tarfile.open(fileobj=in_buf, mode="w", format=tarfile.PAX_FORMAT) as tf:
                data = b"hello from host workspace\n"
                info = tarfile.TarInfo("input.txt")
                info.size = len(data)
                info.mode = 0o600
                tf.addfile(info, io.BytesIO(data))
            inject_res = client.inject_archive(in_buf.getvalue())
            assert inject_res["files_injected"] == 1

            # 2. Execute Python code reading input.txt and writing output.txt + stdout/stderr
            outcome = client.execute_code(
                "import sys, pathlib\n"
                "text = pathlib.Path('input.txt').read_text()\n"
                "pathlib.Path('output.txt').write_text(text.upper())\n"
                "print('STDOUT_OK:' + text.strip())\n"
                "print('STDERR_WARN', file=sys.stderr)\n",
                timeout_seconds=3.0,
                max_stdout_bytes=1024,
                max_stderr_bytes=1024,
            )
            assert outcome.timed_out is False
            assert outcome.exit_code == 0
            assert outcome.stdout == "STDOUT_OK:hello from host workspace\n"
            assert outcome.stderr == "STDERR_WARN\n"
            assert outcome.stdout_truncated is False
            assert outcome.stderr_truncated is False

            # 3. Verify output truncation
            trunc_outcome = client.execute_code(
                "import sys\nsys.stdout.write('A' * 200)\nsys.stderr.write('B' * 200)\n",
                timeout_seconds=3.0,
                max_stdout_bytes=32,
                max_stderr_bytes=16,
            )
            assert trunc_outcome.exit_code == 0
            assert trunc_outcome.stdout == "A" * 32
            assert trunc_outcome.stderr == "B" * 16
            assert trunc_outcome.stdout_truncated is True
            assert trunc_outcome.stderr_truncated is True

            # 4. Verify non-zero exit code
            fail_outcome = client.execute_code(
                "import sys; sys.exit(42)",
                timeout_seconds=3.0,
                max_stdout_bytes=1024,
                max_stderr_bytes=1024,
            )
            assert fail_outcome.timed_out is False
            assert fail_outcome.exit_code == 42

            # 5. Verify execution timeout kills runaway process
            timeout_outcome = client.execute_code(
                "import time\nwhile True:\n    time.sleep(0.05)\n",
                timeout_seconds=0.3,
                max_stdout_bytes=1024,
                max_stderr_bytes=1024,
            )
            assert timeout_outcome.timed_out is True
            assert timeout_outcome.exit_code is None

            # 6. Export workspace archive and verify output.txt is present
            spool = client.export_archive()
            try:
                with tarfile.open(fileobj=spool, mode="r:*") as tf:
                    names = tf.getnames()
                    assert "workspace/input.txt" in names
                    assert "workspace/output.txt" in names
                    extracted = tf.extractfile("workspace/output.txt")
                    assert extracted is not None
                    assert extracted.read() == b"HELLO FROM HOST WORKSPACE\n"
            finally:
                spool.close()

            # 7. Graceful shutdown
            client.shutdown()

        proc.wait(timeout=3.0)
        assert proc.returncode == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2.0)
        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()
        if sock_path.exists():
            sock_path.unlink()
        if sock_dir.exists():
            sock_dir.rmdir()


def test_live_guest_agent_rejects_traversal_and_oversized_injection(tmp_path: Path):
    """Verify guest_agent.py rejects symlink/traversal archives and enforces quota bounds."""
    sock_dir, sock_path = _make_short_socket_path()
    guest_ws = tmp_path / "guest_workspace"
    guest_ws.mkdir()

    agent_script = Path(__file__).resolve().parents[2] / "guest" / "agent" / "guest_agent.py"
    proc = subprocess.Popen(
        [
            sys.executable,
            str(agent_script),
            "--workspace-dir",
            str(guest_ws),
            "--unix-socket",
            str(sock_path),
            "--no-drop-privileges",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        with GuestAgentClient(sock_path, default_timeout_seconds=5.0) as client:
            client.wait_until_ready(
                boot_timeout_seconds=5.0,
                workspace_size_bytes=2048,
                max_file_size_bytes=512,
                max_file_count=5,
                pids_limit=16,
            )

            # Traversal path in tar
            bad_buf = io.BytesIO()
            with tarfile.open(fileobj=bad_buf, mode="w", format=tarfile.PAX_FORMAT) as tf:
                info = tarfile.TarInfo("../escape.txt")
                info.size = 4
                tf.addfile(info, io.BytesIO(b"evil"))

            with pytest.raises(QemuProtocolError, match="SECURITY_VIOLATION"):
                client.inject_archive(bad_buf.getvalue())

            # Oversized file in tar (> 512 bytes)
            big_buf = io.BytesIO()
            with tarfile.open(fileobj=big_buf, mode="w", format=tarfile.PAX_FORMAT) as tf:
                info = tarfile.TarInfo("too_big.bin")
                info.size = 1024
                tf.addfile(info, io.BytesIO(b"x" * 1024))

            with pytest.raises(FileQuotaExceededError):
                client.inject_archive(big_buf.getvalue())

            client.shutdown()
        proc.wait(timeout=3.0)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2.0)
        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()
        if sock_path.exists():
            sock_path.unlink()
        if sock_dir.exists():
            sock_dir.rmdir()
