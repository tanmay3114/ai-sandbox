"""Unit tests for QEMU backend config, capability detection, image/process managers, and factory."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import SandboxSettings
from app.core.exceptions import (
    InvalidRuntimeError,
    QemuEngineError,
    ResourceLimitError,
)
from app.sandbox.backend import SandboxBackend
from app.sandbox.docker_backend import DockerSandboxBackend
from app.sandbox.factory import create_sandbox_backend
from app.sandbox.policy import EffectiveSandboxPolicy
from app.sandbox.qemu.config import (
    QemuVmConfig,
    parse_size_bytes,
    parse_size_mb,
    validate_safe_qemu_path,
)
from app.sandbox.qemu.image_manager import PreparedVmStorage, QemuImageManager
from app.sandbox.qemu.process_manager import QemuProcessManager, build_qemu_command
from app.sandbox.qemu.runtime import detect_qemu_capabilities, verify_qemu_runtime
from app.sandbox.qemu_backend import QemuSandboxBackend


@pytest.fixture(autouse=True)
def verify_no_container_leak():
    """Unit tests in this module do not create Docker containers."""
    yield


def _create_dummy_guest_assets(image_dir: Path) -> tuple[Path, Path, Path]:
    image_dir.mkdir(parents=True, exist_ok=True)
    kernel = image_dir / "vmlinuz-virt"
    initrd = image_dir / "initramfs-virt"
    base_img = image_dir / "rootfs.qcow2"
    kernel.write_bytes(b"ARM64_LINUX_KERNEL_IMAGE")
    initrd.write_bytes(b"ARM64_INITRAMFS_CPIO_GZ")
    base_img.write_bytes(b"QCOW2_BASE_IMAGE")
    os.chmod(kernel, 0o644)
    os.chmod(initrd, 0o644)
    os.chmod(base_img, 0o644)
    return kernel, initrd, base_img


def test_backend_factory_selects_docker_or_qemu_and_rejects_invalid(fast_settings: SandboxSettings):
    docker_cfg = fast_settings.model_copy(update={"BACKEND": "docker"})
    qemu_cfg = fast_settings.model_copy(update={"BACKEND": "qemu"})

    docker_backend = create_sandbox_backend(docker_cfg)
    assert isinstance(docker_backend, DockerSandboxBackend)
    assert isinstance(docker_backend, SandboxBackend)

    qemu_backend = create_sandbox_backend(qemu_cfg)
    assert isinstance(qemu_backend, QemuSandboxBackend)
    assert isinstance(qemu_backend, SandboxBackend)

    # Bypass Pydantic validator via model_construct to prove factory fails closed
    bad_cfg = fast_settings.model_copy(update={"BACKEND": "firecracker"})
    with pytest.raises(InvalidRuntimeError, match="Unsupported sandbox backend"):
        create_sandbox_backend(bad_cfg)


def test_qemu_command_construction_enforces_isolation_and_hvf(
    fast_settings: SandboxSettings,
    tmp_path: Path,
):
    image_dir = tmp_path / "images"
    runtime_dir = tmp_path / "runtime"
    _create_dummy_guest_assets(image_dir)

    cfg = fast_settings.model_copy(
        update={
            "BACKEND": "qemu",
            "QEMU_IMAGE_DIR": image_dir,
            "QEMU_RUNTIME_DIR": runtime_dir,
            "QEMU_ACCELERATOR": "hvf",
            "QEMU_MACHINE": "virt",
            "QEMU_CPU": "host",
        }
    )
    vm_cfg = QemuVmConfig.from_settings_and_policy(cfg)
    exec_dir = runtime_dir / "vm-123456789abc"
    storage = PreparedVmStorage(
        sandbox_id="sbx-1",
        execution_id="123456789abc",
        runtime_dir=exec_dir,
        socket_dir=exec_dir,
        socket_path=exec_dir / "a.sock",
        overlay_path=exec_dir / "overlay.qcow2",
        pidfile_path=exec_dir / "qemu.pid",
        console_log_path=exec_dir / "console.log",
        metadata_path=exec_dir / "vm_metadata.json",
    )

    argv = build_qemu_command(vm_cfg, storage)

    assert argv[0] == "qemu-system-aarch64"
    assert "-accel" in argv and argv[argv.index("-accel") + 1] == "hvf"
    assert "-machine" in argv and argv[argv.index("-machine") + 1] == "virt,usb=off"
    assert "-cpu" in argv and argv[argv.index("-cpu") + 1] == "host"
    assert "-m" in argv and argv[argv.index("-m") + 1] == "128"
    assert "-nic" in argv and argv[argv.index("-nic") + 1] == "none"
    assert "-monitor" in argv and argv[argv.index("-monitor") + 1] == "none"
    assert "-nodefaults" in argv
    assert "-no-user-config" in argv
    assert "-nographic" in argv
    assert "-no-reboot" in argv
    assert "virtio-serial-pci" in argv
    assert any("virtserialport,chardev=agent0,name=org.aisandbox.agent" in a for a in argv)
    assert any(f"file={storage.overlay_path},if=none,format=qcow2" in a for a in argv)

    # Confirm no host filesystem sharing (9p / virtiofs) or networking is present
    joined = " ".join(argv)
    assert "9p" not in joined
    assert "virtiofs" not in joined
    assert "fsdev" not in joined
    assert "netdev" not in joined


def test_qemu_path_validation_rejects_option_injection(tmp_path: Path):
    with pytest.raises(InvalidRuntimeError, match="Unsafe characters"):
        validate_safe_qemu_path(tmp_path / "bad,option=evil.qcow2", "overlay")

    with pytest.raises(InvalidRuntimeError, match="Unsafe characters"):
        validate_safe_qemu_path(tmp_path / "bad\nline.qcow2", "overlay")

    with pytest.raises(InvalidRuntimeError, match="traversal forbidden"):
        validate_safe_qemu_path(Path("/tmp/aisbx/../escape"), "overlay")


def test_qemu_vm_config_validates_memory_headroom_and_policy(fast_settings: SandboxSettings):
    assert parse_size_bytes("256m") == 256 * 1024 * 1024
    assert parse_size_mb("128M") == 128

    # Memory limit too small for 25 MiB workspace + 64 MiB guest OS headroom
    tiny_mem_cfg = fast_settings.model_copy(
        update={
            "MEMORY_LIMIT": "64m",
            "MEMSWAP_LIMIT": "64m",
        }
    )
    with pytest.raises(ResourceLimitError, match="insufficient for workspace limit"):
        QemuVmConfig.from_settings_and_policy(tiny_mem_cfg)

    # Weakened policy rejected before VM creation
    policy = replace(EffectiveSandboxPolicy.from_settings(fast_settings), network_disabled=False)
    with pytest.raises(ResourceLimitError):
        QemuVmConfig.from_settings_and_policy(fast_settings, policy)


def test_runtime_capability_detection_handles_present_and_missing_qemu(
    fast_settings: SandboxSettings,
    tmp_path: Path,
):
    image_dir = tmp_path / "images"
    _create_dummy_guest_assets(image_dir)
    cfg = fast_settings.model_copy(
        update={
            "BACKEND": "qemu",
            "QEMU_IMAGE_DIR": image_dir,
            "QEMU_ACCELERATOR": "hvf",
        }
    )

    # 1. Simulate missing QEMU binary
    with patch("app.sandbox.qemu.runtime._resolve_executable", return_value=None):
        caps = detect_qemu_capabilities(cfg)
        assert caps.is_ready is False
        assert any("not found on PATH" in m for m in caps.missing_prerequisites)
        assert "brew install qemu" in caps.remediation_commands
        with pytest.raises(QemuEngineError, match="not ready"):
            verify_qemu_runtime(cfg)

    # 2. Simulate QEMU binary present but missing HVF accelerator support
    def _mock_probe_no_hvf(argv: list[str]) -> str:
        if "--version" in argv:
            return "QEMU emulator version 9.2.0\n"
        if "-accel" in argv:
            return "Accelerators supported in QEMU binary:\ntcg\n"
        if "-machine" in argv:
            return (
                "Supported machines are:\n"
                "virt-9.2 QEMU 9.2 ARM Virtual Machine\n"
                "virt ARM Virtual Machine\n"
            )
        if "-device" in argv:
            return (
                'name "virtio-serial-device", bus virtio-bus\n'
                'name "virtserialport", bus virtio-serial-bus\n'
                'name "virtio-blk-device", bus virtio-bus\n'
            )
        return ""

    with (
        patch(
            "app.sandbox.qemu.runtime._resolve_executable", return_value="/opt/homebrew/bin/qemu"
        ),
        patch("app.sandbox.qemu.runtime._check_macos_hvf_support", return_value=True),
        patch("app.sandbox.qemu.runtime._run_probe", side_effect=_mock_probe_no_hvf),
    ):
        caps = detect_qemu_capabilities(cfg)
        assert caps.is_ready is False
        assert any(
            "Required QEMU accelerator 'hvf' is not supported" in m
            for m in caps.missing_prerequisites
        )

    # 3. Simulate full macOS ARM64 + HVF + virt + virtio device support
    def _mock_probe_ok(argv: list[str]) -> str:
        if "--version" in argv:
            return "QEMU emulator version 9.2.0\n"
        if "-accel" in argv:
            return "Accelerators supported in QEMU binary:\nhvf\ntcg\n"
        if "-machine" in argv:
            return "Supported machines are:\nvirt ARM Virtual Machine\n"
        if "-device" in argv:
            return (
                'name "virtio-serial-device", bus virtio-bus\n'
                'name "virtserialport", bus virtio-serial-bus\n'
                'name "virtio-blk-device", bus virtio-bus\n'
            )
        return ""

    with (
        patch(
            "app.sandbox.qemu.runtime._resolve_executable", return_value="/opt/homebrew/bin/qemu"
        ),
        patch("app.sandbox.qemu.runtime._check_macos_hvf_support", return_value=True),
        patch("app.sandbox.qemu.runtime._run_probe", side_effect=_mock_probe_ok),
    ):
        caps = verify_qemu_runtime(cfg)
        assert caps.is_ready is True
        assert "hvf" in caps.supported_accelerators
        assert "READY" in caps.format_diagnostic()


def test_image_manager_verifies_checksums_permissions_and_creates_overlay(
    fast_settings: SandboxSettings,
    tmp_path: Path,
):
    image_dir = tmp_path / "images"
    runtime_dir = tmp_path / "runtime"
    kernel, initrd, base_img = _create_dummy_guest_assets(image_dir)

    manifest = {
        "sha256": {
            "vmlinuz-virt": hashlib.sha256(kernel.read_bytes()).hexdigest(),
            "initramfs-virt": hashlib.sha256(initrd.read_bytes()).hexdigest(),
            "rootfs.qcow2": hashlib.sha256(base_img.read_bytes()).hexdigest(),
        }
    }
    (image_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    cfg = fast_settings.model_copy(
        update={
            "BACKEND": "qemu",
            "QEMU_IMAGE_DIR": image_dir,
            "QEMU_RUNTIME_DIR": runtime_dir,
        }
    )
    vm_cfg = QemuVmConfig.from_settings_and_policy(cfg)
    img_mgr = QemuImageManager(config=cfg)

    def _fake_qemu_img(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        overlay_file = Path(argv[-2])
        overlay_file.write_bytes(b"QCOW2_OVERLAY")
        return subprocess.CompletedProcess(argv, 0, stdout="Formatting...", stderr="")

    with patch("app.sandbox.qemu.image_manager.subprocess.run", side_effect=_fake_qemu_img):
        storage = img_mgr.prepare_execution_storage(sandbox_id="sbx-1", vm_cfg=vm_cfg)
        assert storage.runtime_dir.is_dir()
        assert (storage.runtime_dir.stat().st_mode & 0o777) == 0o700
        assert (storage.socket_dir.stat().st_mode & 0o777) == 0o700
        assert len(str(storage.socket_path).encode("utf-8")) <= 96
        assert storage.overlay_path.is_file()
        assert (storage.overlay_path.stat().st_mode & 0o777) == 0o600

        assert img_mgr.cleanup_storage(storage) is True
        assert not storage.runtime_dir.exists()
        assert not storage.socket_dir.exists()

    # Checksum mismatch must fail closed
    kernel.write_bytes(b"TAMPERED_KERNEL")
    with pytest.raises(QemuEngineError, match="SHA-256 checksum mismatch"):
        img_mgr.verify_guest_assets(vm_cfg)


def test_image_manager_rejects_symlink_and_world_writable_assets(
    fast_settings: SandboxSettings,
    tmp_path: Path,
):
    image_dir = tmp_path / "images"
    kernel, initrd, _ = _create_dummy_guest_assets(image_dir)
    cfg = fast_settings.model_copy(
        update={
            "BACKEND": "qemu",
            "QEMU_IMAGE_DIR": image_dir,
        }
    )
    vm_cfg = QemuVmConfig.from_settings_and_policy(cfg)
    img_mgr = QemuImageManager(config=cfg)

    # World-writable kernel rejected
    os.chmod(kernel, 0o666)
    with pytest.raises(QemuEngineError, match="world-writable"):
        img_mgr.verify_guest_assets(vm_cfg)
    os.chmod(kernel, 0o644)

    # Symlink initramfs rejected
    initrd.unlink()
    initrd.symlink_to(kernel)
    with pytest.raises(QemuEngineError, match="symbolic link"):
        img_mgr.verify_guest_assets(vm_cfg)


def test_process_manager_lifecycle_ownership_and_kill_escalation(
    fast_settings: SandboxSettings,
    tmp_path: Path,
):
    runtime_dir = tmp_path / "runtime"
    image_dir = tmp_path / "images"
    _create_dummy_guest_assets(image_dir)
    cfg = fast_settings.model_copy(
        update={
            "BACKEND": "qemu",
            "QEMU_IMAGE_DIR": image_dir,
            "QEMU_RUNTIME_DIR": runtime_dir,
        }
    )
    vm_cfg = QemuVmConfig.from_settings_and_policy(cfg)
    img_mgr = QemuImageManager(config=cfg)
    proc_mgr = QemuProcessManager(config=cfg, image_manager=img_mgr)

    exec_dir = runtime_dir / "vm-exec12345678"
    exec_dir.mkdir(parents=True)
    storage = PreparedVmStorage(
        sandbox_id="sbx-owned",
        execution_id="exec12345678",
        runtime_dir=exec_dir,
        socket_dir=exec_dir,
        socket_path=exec_dir / "a.sock",
        overlay_path=exec_dir / "overlay.qcow2",
        pidfile_path=exec_dir / "qemu.pid",
        console_log_path=exec_dir / "console.log",
        metadata_path=exec_dir / "vm_metadata.json",
    )

    mock_popen = MagicMock()
    mock_popen.pid = 44556
    # First poll() returns None (running), wait(timeout=0.5) times out so kill() is called
    mock_popen.poll.side_effect = [None, -9]
    mock_popen.wait.side_effect = [subprocess.TimeoutExpired("qemu", 0.5), -9]
    mock_popen.stdout = MagicMock()
    mock_popen.stderr = MagicMock()

    with patch("app.sandbox.qemu.process_manager.subprocess.Popen", return_value=mock_popen):
        handle = proc_mgr.start_vm(vm_cfg=vm_cfg, storage=storage)
        assert storage.metadata_path.is_file()

        # Refuses cleanup if sandbox_id does not match
        assert proc_mgr.cleanup_vm(handle, expected_sandbox_id="different-sandbox") is False
        mock_popen.terminate.assert_not_called()

        # Matching sandbox_id escalates SIGTERM -> SIGKILL and removes runtime dir
        assert proc_mgr.cleanup_vm(handle, expected_sandbox_id="sbx-owned") is True
        mock_popen.terminate.assert_called_once()
        mock_popen.kill.assert_called_once()
        assert not exec_dir.exists()
