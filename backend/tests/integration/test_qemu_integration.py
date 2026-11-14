"""Real ARM64 QEMU + HVF integration tests for QemuSandboxBackend.

Executes only when ``qemu-system-aarch64``, ``qemu-img``, macOS ARM64 HVF support,
and the built ARM64 Linux guest assets (``vmlinuz-virt``, ``initramfs-virt``) are
available on the host. When prerequisites are missing, skips with the exact
remediation commands required to unblock real VM verification.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import SandboxSettings, settings
from app.sandbox.qemu.runtime import detect_qemu_capabilities
from app.sandbox.qemu_backend import QemuSandboxBackend
from app.sandbox.schemas import ExecutionRequest, ExecutionStatus


def _require_real_qemu_runtime(config: SandboxSettings) -> None:
    caps = detect_qemu_capabilities(config)
    if not caps.is_ready:
        pytest.skip(
            "Real ARM64 QEMU runtime or guest image is not available on this host:\n"
            + caps.format_diagnostic()
        )


@pytest.fixture
def qemu_live_settings(fast_settings: SandboxSettings, tmp_path: Path) -> SandboxSettings:
    cfg = fast_settings.model_copy(
        update={
            "BACKEND": "qemu",
            "MEMORY_LIMIT": "256m",
            "MEMSWAP_LIMIT": "256m",
            "TIMEOUT_SECONDS": 5.0,
            "QEMU_IMAGE_DIR": settings.QEMU_IMAGE_DIR,
            "QEMU_RUNTIME_DIR": tmp_path / "qemu_runtime",
            "WORKSPACE_DIR": tmp_path / "workspaces",
        }
    )
    _require_real_qemu_runtime(cfg)
    return cfg


def test_real_qemu_arm64_end_to_end_suite(qemu_live_settings: SandboxSettings):
    """Run the 15 real ARM64 QEMU VM integration checks when QEMU + guest image are present."""
    caps = detect_qemu_capabilities(qemu_live_settings)
    assert caps.is_ready is True
    assert caps.is_arm64_host is True
    assert "hvf" in caps.supported_accelerators

    backend = QemuSandboxBackend(config=qemu_live_settings)
    backend.check_health()

    sandbox_id = "real-qemu-sbx-1"
    backend.write_file(sandbox_id, "host_seed.txt", "seeded_from_host\n")

    # 1-6: Boot ARM64 guest, agent readiness, execute Python, capture stdout/stderr, check UID 10001
    res1 = backend.execute(
        ExecutionRequest(
            code=(
                "import os, platform, pathlib, sys\n"
                "assert os.geteuid() == 10001 and os.getegid() == 10001\n"
                "assert platform.machine() in ('aarch64', 'arm64')\n"
                "seed = pathlib.Path('host_seed.txt').read_text().strip()\n"
                "pathlib.Path('vm1_out.txt').write_text(seed + ':vm1\\n')\n"
                "print(f'ARCH={platform.machine()} SEED={seed}')\n"
                "print('STDERR_CHECK', file=sys.stderr)\n"
            )
        ),
        sandbox_id=sandbox_id,
    )
    assert res1.status == ExecutionStatus.COMPLETED
    assert res1.exit_code == 0
    assert "SEED=seeded_from_host" in res1.stdout
    assert "STDERR_CHECK" in res1.stderr

    # 11-13: Archive retrieval & persistence across a second fresh VM execution
    assert backend.read_file(sandbox_id, "vm1_out.txt").content == "seeded_from_host:vm1\n"

    res2 = backend.execute(
        ExecutionRequest(
            code=(
                "import pathlib\n"
                "prev = pathlib.Path('vm1_out.txt').read_text().strip()\n"
                "pathlib.Path('vm2_out.txt').write_text(prev + ':vm2\\n')\n"
                "print(prev)\n"
            )
        ),
        sandbox_id=sandbox_id,
    )
    assert res2.status == ExecutionStatus.COMPLETED
    assert res2.stdout.strip() == "seeded_from_host:vm1"
    assert backend.read_file(sandbox_id, "vm2_out.txt").content == "seeded_from_host:vm1:vm2\n"

    # 7: Non-zero exit code preserved and valid workspace changes still imported
    res_fail = backend.execute(
        ExecutionRequest(
            code="import pathlib, sys; pathlib.Path('nonzero.txt').write_text('kept'); sys.exit(19)"
        ),
        sandbox_id=sandbox_id,
    )
    assert res_fail.status == ExecutionStatus.FAILED
    assert res_fail.exit_code == 19
    assert backend.read_file(sandbox_id, "nonzero.txt").content == "kept"

    # 8 & 14: Timeout termination preserves previous workspace without importing partial changes
    res_timeout = backend.execute(
        ExecutionRequest(
            code=(
                "import pathlib, time\n"
                "pathlib.Path('uncommitted_timeout.txt').write_text('discard_me')\n"
                "while True:\n"
                "    time.sleep(0.1)\n"
            ),
            timeout_seconds=0.8,
        ),
        sandbox_id=sandbox_id,
    )
    assert res_timeout.status == ExecutionStatus.TIMED_OUT
    assert res_timeout.exit_code is None
    listed = {f.path for f in backend.list_files(sandbox_id).files}
    assert "uncommitted_timeout.txt" not in listed
    assert backend.read_file(sandbox_id, "vm2_out.txt").content == "seeded_from_host:vm1:vm2\n"

    # 9: Verify no external network interfaces exist inside guest (-nic none)
    res_net = backend.execute(
        ExecutionRequest(
            code=(
                "import os\n"
                "ifaces = os.listdir('/sys/class/net')\n"
                "print('IFACES=' + ','.join(sorted(ifaces)))\n"
                "assert ifaces == ['lo'], f'Unexpected NICs: {ifaces}'\n"
            )
        ),
        sandbox_id=sandbox_id,
    )
    assert res_net.status == ExecutionStatus.COMPLETED
    assert "IFACES=lo" in res_net.stdout

    # 10: Verify guest workspace file size limit (RLIMIT_FSIZE) prevents runaway writes
    res_quota = backend.execute(
        ExecutionRequest(
            code=("with open('huge.bin', 'wb') as f:\n    f.write(b'x' * (10 * 1024 * 1024))\n")
        ),
        sandbox_id=sandbox_id,
    )
    assert res_quota.status == ExecutionStatus.FAILED
    assert res_quota.exit_code != 0

    # 15: Verify cleanup removes all temporary VM runtime directories and overlays
    if qemu_live_settings.QEMU_RUNTIME_DIR.exists():
        remaining_vms = list(qemu_live_settings.QEMU_RUNTIME_DIR.glob("vm-*"))
        assert remaining_vms == []

    backend.cleanup_sandbox(sandbox_id)
    assert not (qemu_live_settings.WORKSPACE_DIR / sandbox_id).exists()
