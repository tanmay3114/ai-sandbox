"""QEMU runtime capability detection and platform verification for macOS ARM64 / Linux ARM64."""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import SandboxSettings, settings
from app.core.exceptions import QemuEngineError
from app.sandbox.qemu.config import QemuVmConfig

REQUIRED_DEVICE_FAMILIES: tuple[tuple[str, ...], ...] = (
    ("virtio-serial-device", "virtio-serial-pci"),
    ("virtserialport",),
    ("virtio-blk-device", "virtio-blk-pci"),
)


@dataclass(frozen=True, slots=True)
class QemuRuntimeCapabilities:
    """Structured diagnostic snapshot of host QEMU and ARM64 virtualization support."""

    host_os: str
    host_arch: str
    is_arm64_host: bool
    hvf_supported_by_kernel: bool
    qemu_binary_path: str | None
    qemu_img_binary_path: str | None
    qemu_version: str | None
    supported_accelerators: tuple[str, ...] = ()
    supported_machines: tuple[str, ...] = ()
    supported_devices: tuple[str, ...] = ()
    kernel_exists: bool = False
    initrd_exists: bool = False
    base_image_exists: bool = False
    missing_prerequisites: tuple[str, ...] = field(default_factory=tuple)
    remediation_commands: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_ready(self) -> bool:
        """Return True only when all required QEMU binaries, devices, and guest assets exist."""
        return len(self.missing_prerequisites) == 0

    def format_diagnostic(self) -> str:
        """Produce a human-readable diagnostic summary suitable for logs and startup checks."""
        status = "READY" if self.is_ready else "NOT_READY"
        qemu_bin_str = self.qemu_binary_path or "MISSING"
        qemu_ver_str = self.qemu_version or "n/a"
        lines = [
            f"QEMU Runtime Capability Check: {status}",
            f"  Host OS / Arch: {self.host_os} / {self.host_arch} (arm64={self.is_arm64_host})",
            f"  Apple HVF Kernel Support: {self.hvf_supported_by_kernel}",
            f"  qemu-system-aarch64: {qemu_bin_str} ({qemu_ver_str})",
            f"  qemu-img: {self.qemu_img_binary_path or 'MISSING'}",
            f"  Supported Accelerators: {', '.join(self.supported_accelerators) or 'none'}",
            f"  Guest Kernel Present: {self.kernel_exists}",
            f"  Guest Initramfs Present: {self.initrd_exists}",
        ]
        if self.missing_prerequisites:
            lines.append("  Missing Prerequisites:")
            for item in self.missing_prerequisites:
                lines.append(f"    - {item}")
        if self.remediation_commands:
            lines.append("  One-Time Remediation Commands:")
            for cmd in self.remediation_commands:
                lines.append(f"    $ {cmd}")
        return "\n".join(lines)


def _check_macos_hvf_support() -> bool:
    """Check whether macOS Hypervisor.framework is enabled on the current host."""
    if platform.system().lower() != "darwin":
        return False
    try:
        proc = subprocess.run(
            ["sysctl", "-n", "kern.hv_support"],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
        return proc.returncode == 0 and proc.stdout.strip() == "1"
    except Exception:
        return False


def _run_probe(argv: list[str]) -> str | None:
    """Execute a read-only QEMU capability probe command with a short timeout."""
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
        if proc.returncode != 0:
            return None
        return proc.stdout
    except Exception:
        return None


def _resolve_executable(binary: str) -> str | None:
    """Resolve an executable name or explicit path."""
    candidate = Path(binary)
    if candidate.is_absolute():
        if candidate.is_file() and shutil.which(str(candidate)) is not None:
            return str(candidate)
        return None
    return shutil.which(binary)


def detect_qemu_capabilities(config: SandboxSettings = settings) -> QemuRuntimeCapabilities:
    """Inspect the host platform and QEMU installation without modifying system state."""
    vm_cfg = QemuVmConfig.from_settings_and_policy(config)
    host_os = platform.system().lower()
    host_arch = platform.machine().lower()
    is_arm64 = host_arch in {"arm64", "aarch64"}
    hvf_kernel = _check_macos_hvf_support()

    missing: list[str] = []
    remediation: list[str] = []

    if not is_arm64 and vm_cfg.accelerator in {"hvf", "kvm"}:
        missing.append(
            f"Host architecture '{host_arch}' cannot run ARM64 hardware-accelerated "
            f"({vm_cfg.accelerator}) guests; Apple Silicon / ARM64 host is required."
        )

    if vm_cfg.accelerator == "hvf":
        if host_os != "darwin":
            missing.append(
                f"Configured accelerator 'hvf' requires macOS (Darwin), found '{host_os}'."
            )
        elif not hvf_kernel:
            missing.append("macOS Hypervisor.framework (kern.hv_support=1) is not available.")

    qemu_bin = _resolve_executable(vm_cfg.qemu_binary)
    qemu_img_bin = _resolve_executable(vm_cfg.qemu_img_binary)

    if qemu_bin is None:
        missing.append(f"QEMU binary '{vm_cfg.qemu_binary}' not found on PATH.")
    if qemu_img_bin is None:
        missing.append(f"QEMU image utility '{vm_cfg.qemu_img_binary}' not found on PATH.")
    if qemu_bin is None or qemu_img_bin is None:
        remediation.append("brew install qemu")

    qemu_version: str | None = None
    accelerators: list[str] = []
    machines: list[str] = []
    devices: list[str] = []

    if qemu_bin is not None:
        ver_out = _run_probe([qemu_bin, "--version"])
        if ver_out:
            qemu_version = ver_out.splitlines()[0].strip()
        else:
            missing.append(f"Failed to execute '{qemu_bin} --version'.")

        accel_out = _run_probe([qemu_bin, "-accel", "help"])
        if accel_out:
            for line in accel_out.splitlines():
                token = line.strip().lower()
                if token and not token.startswith("accelerators") and " " not in token:
                    accelerators.append(token)
            if vm_cfg.accelerator not in accelerators:
                missing.append(
                    f"Required QEMU accelerator '{vm_cfg.accelerator}' is not supported by "
                    f"'{qemu_bin}' (available: {accelerators or ['none']}). Refusing to fall back "
                    "to slow or unapproved emulation."
                )
        else:
            missing.append(f"Unable to query accelerators via '{qemu_bin} -accel help'.")

        machine_out = _run_probe([qemu_bin, "-machine", "help"])
        if machine_out:
            for line in machine_out.splitlines():
                parts = line.strip().split()
                if parts and not line.lower().startswith("supported machines"):
                    machines.append(parts[0])
            if not any(m == vm_cfg.machine or m.startswith(f"{vm_cfg.machine}-") for m in machines):
                missing.append(
                    f"Required ARM64 machine '{vm_cfg.machine}' is not supported by '{qemu_bin}'."
                )
        else:
            missing.append(f"Unable to query machines via '{qemu_bin} -machine help'.")

        device_out = _run_probe([qemu_bin, "-device", "help"])
        if device_out:
            for line in device_out.splitlines():
                if line.startswith('name "'):
                    name_part = line.split('"', 2)[1]
                    devices.append(name_part)
            for family in REQUIRED_DEVICE_FAMILIES:
                if not any(dev in devices for dev in family):
                    missing.append(
                        f"Required QEMU device model family {family} is not supported "
                        f"by '{qemu_bin}'."
                    )
        else:
            missing.append(f"Unable to query device models via '{qemu_bin} -device help'.")

    kernel_exists = vm_cfg.kernel_path.is_file() and not vm_cfg.kernel_path.is_symlink()
    initrd_exists = vm_cfg.initrd_path.is_file() and not vm_cfg.initrd_path.is_symlink()
    base_image_exists = (
        vm_cfg.base_image_path is not None
        and vm_cfg.base_image_path.is_file()
        and not vm_cfg.base_image_path.is_symlink()
    )

    if not kernel_exists:
        missing.append(f"ARM64 guest kernel not found at '{vm_cfg.kernel_path}'.")
    if not initrd_exists:
        missing.append(f"ARM64 guest initramfs not found at '{vm_cfg.initrd_path}'.")
    if not kernel_exists or not initrd_exists:
        remediation.append("./guest/scripts/build_guest_image.sh")

    return QemuRuntimeCapabilities(
        host_os=host_os,
        host_arch=host_arch,
        is_arm64_host=is_arm64,
        hvf_supported_by_kernel=hvf_kernel,
        qemu_binary_path=qemu_bin,
        qemu_img_binary_path=qemu_img_bin,
        qemu_version=qemu_version,
        supported_accelerators=tuple(accelerators),
        supported_machines=tuple(machines),
        supported_devices=tuple(devices),
        kernel_exists=kernel_exists,
        initrd_exists=initrd_exists,
        base_image_exists=base_image_exists,
        missing_prerequisites=tuple(missing),
        remediation_commands=tuple(remediation),
    )


def verify_qemu_runtime(config: SandboxSettings = settings) -> QemuRuntimeCapabilities:
    """Verify QEMU runtime readiness or raise QemuEngineError with actionable diagnostics."""
    caps = detect_qemu_capabilities(config)
    if not caps.is_ready:
        raise QemuEngineError(
            "QEMU execution backend is not ready: " + "; ".join(caps.missing_prerequisites),
            details={
                "missing_prerequisites": list(caps.missing_prerequisites),
                "remediation_commands": list(caps.remediation_commands),
                "host_os": caps.host_os,
                "host_arch": caps.host_arch,
                "hvf_supported": caps.hvf_supported_by_kernel,
            },
        )
    return caps
