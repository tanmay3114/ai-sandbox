"""Validated QEMU VM configuration derived from SandboxSettings and EffectiveSandboxPolicy."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from app.core.config import SandboxSettings
from app.core.exceptions import InvalidRuntimeError, ResourceLimitError
from app.sandbox.policy import APPROVED_RUNTIME_USER, EffectiveSandboxPolicy

_SIZE_RE = re.compile(r"^\s*(\d+)\s*([kmgKMG]?[bB]?)\s*$")
_UNSAFE_ARG_CHARS = frozenset({",", "\n", "\r", "\x00"})
MIN_GUEST_OS_HEADROOM_BYTES = 64 * 1024 * 1024  # 64 MiB minimum headroom for kernel + Python


def parse_size_bytes(size_str: str | int) -> int:
    """Parse a human-readable size string (e.g. '256m', '64M', '1g') into exact bytes."""
    if isinstance(size_str, int):
        if size_str <= 0:
            raise ResourceLimitError(f"Size value must be positive, got {size_str}")
        return size_str

    match = _SIZE_RE.match(str(size_str))
    if not match:
        raise ResourceLimitError(f"Invalid size specification: '{size_str}'")

    amount = int(match.group(1))
    unit = match.group(2).lower().rstrip("b")
    multipliers = {
        "": 1,
        "k": 1024,
        "m": 1024 * 1024,
        "g": 1024 * 1024 * 1024,
    }
    if amount <= 0 or unit not in multipliers:
        raise ResourceLimitError(f"Invalid size specification: '{size_str}'")
    return amount * multipliers[unit]


def parse_size_mb(size_str: str | int) -> int:
    """Parse a size specification into whole MiB (minimum 1 MiB)."""
    total_bytes = parse_size_bytes(size_str)
    if total_bytes < 1024 * 1024 or total_bytes % (1024 * 1024) != 0:
        raise ResourceLimitError(
            f"Memory specification '{size_str}' must be an exact multiple of 1 MiB"
        )
    return total_bytes // (1024 * 1024)


def validate_safe_qemu_path(path: Path, label: str) -> Path:
    """Ensure a filesystem path cannot inject QEMU option delimiters or control chars."""
    raw = str(path)
    if not raw or any(ch in _UNSAFE_ARG_CHARS for ch in raw):
        raise InvalidRuntimeError(
            f"Unsafe characters detected in {label} path; commas and control chars are forbidden"
        )
    if ".." in path.parts:
        raise InvalidRuntimeError(f"Parent directory traversal forbidden in {label} path")
    return path.resolve()


@dataclass(frozen=True, slots=True)
class QemuVmConfig:
    """Immutable per-execution QEMU VM resource and isolation configuration."""

    qemu_binary: str
    qemu_img_binary: str
    guest_arch: str
    accelerator: str
    machine: str
    cpu_model: str
    memory_mb: int
    vcpus: int
    disk_size: str
    disk_size_bytes: int
    kernel_path: Path
    initrd_path: Path
    base_image_path: Path | None
    runtime_dir: Path
    boot_timeout_seconds: float
    agent_timeout_seconds: float
    execution_timeout_seconds: float
    pids_limit: int
    max_stdout_bytes: int
    max_stderr_bytes: int
    max_file_size_bytes: int
    max_workspace_size_bytes: int
    max_file_count: int
    workspace_tmpfs_size_bytes: int
    workspace_tmpfs_inodes: int
    tmpfs_size_bytes: int
    run_as_uid: int
    run_as_gid: int
    network_disabled: bool = True
    read_only_rootfs: bool = True
    host_mounts_allowed: bool = False

    @classmethod
    def from_settings_and_policy(
        cls,
        config: SandboxSettings,
        policy: EffectiveSandboxPolicy | None = None,
    ) -> QemuVmConfig:
        """Translate SandboxSettings and EffectiveSandboxPolicy into validated VM config."""
        effective_policy = policy or EffectiveSandboxPolicy.from_settings(config)
        effective_policy.validate()

        if effective_policy.run_as_user != APPROVED_RUNTIME_USER:
            raise ResourceLimitError(
                f"QEMU backend requires approved runtime user {APPROVED_RUNTIME_USER}"
            )
        if not (
            effective_policy.network_disabled
            and not effective_policy.privileged
            and effective_policy.drop_all_capabilities
            and effective_policy.no_new_privileges
            and effective_policy.read_only_rootfs
            and not effective_policy.host_mounts_allowed
            and not effective_policy.host_environment_allowed
        ):
            raise ResourceLimitError(
                "QEMU backend cannot weaken mandatory sandbox policy isolation controls"
            )

        memory_bytes = parse_size_bytes(effective_policy.memory_limit)
        memory_mb = parse_size_mb(effective_policy.memory_limit)
        tmpfs_size_bytes = parse_size_bytes(effective_policy.tmpfs_size)
        configured_ws_tmpfs_bytes = parse_size_bytes(config.WORKSPACE_TMPFS_SIZE)
        workspace_tmpfs_size_bytes = min(
            configured_ws_tmpfs_bytes,
            effective_policy.max_workspace_size_bytes,
        )

        if workspace_tmpfs_size_bytes + MIN_GUEST_OS_HEADROOM_BYTES > memory_bytes:
            raise ResourceLimitError(
                f"VM memory limit ({memory_mb} MiB) is insufficient for workspace limit "
                f"({workspace_tmpfs_size_bytes // (1024 * 1024)} MiB) plus guest OS headroom "
                f"({MIN_GUEST_OS_HEADROOM_BYTES // (1024 * 1024)} MiB)"
            )

        disk_size_bytes = parse_size_bytes(config.QEMU_DISK_SIZE)
        policy_cpus = max(1, math.ceil(effective_policy.nano_cpus / 1_000_000_000))
        vcpus = max(1, min(config.QEMU_VCPUS, policy_cpus))

        image_dir = validate_safe_qemu_path(config.QEMU_IMAGE_DIR, "QEMU_IMAGE_DIR")
        kernel_path = validate_safe_qemu_path(
            config.QEMU_KERNEL_PATH or (image_dir / "vmlinuz-virt"),
            "QEMU_KERNEL_PATH",
        )
        initrd_path = validate_safe_qemu_path(
            config.QEMU_INITRD_PATH or (image_dir / "initramfs-virt"),
            "QEMU_INITRD_PATH",
        )
        raw_base_image = config.QEMU_BASE_IMAGE_PATH or (image_dir / "rootfs.qcow2")
        base_image_path = validate_safe_qemu_path(raw_base_image, "QEMU_BASE_IMAGE_PATH")
        runtime_dir = validate_safe_qemu_path(config.QEMU_RUNTIME_DIR, "QEMU_RUNTIME_DIR")

        uid_str, gid_str = effective_policy.run_as_user.split(":", 1)
        max_file_size = min(
            effective_policy.max_file_size_bytes,
            effective_policy.max_workspace_size_bytes,
        )
        # Allow enough inodes for MAX_FILE_COUNT files plus nested directories (up to depth * count)
        workspace_inodes = max(64, config.MAX_FILE_COUNT + 64)

        return cls(
            qemu_binary=config.QEMU_BINARY.strip(),
            qemu_img_binary=config.QEMU_IMG_BINARY.strip(),
            guest_arch=config.QEMU_GUEST_ARCH,
            accelerator=config.QEMU_ACCELERATOR,
            machine=config.QEMU_MACHINE,
            cpu_model=config.QEMU_CPU.strip(),
            memory_mb=memory_mb,
            vcpus=vcpus,
            disk_size=config.QEMU_DISK_SIZE.strip(),
            disk_size_bytes=disk_size_bytes,
            kernel_path=kernel_path,
            initrd_path=initrd_path,
            base_image_path=base_image_path,
            runtime_dir=runtime_dir,
            boot_timeout_seconds=config.QEMU_BOOT_TIMEOUT_SECONDS,
            agent_timeout_seconds=config.QEMU_AGENT_TIMEOUT_SECONDS,
            execution_timeout_seconds=effective_policy.timeout_seconds,
            pids_limit=effective_policy.pids_limit,
            max_stdout_bytes=effective_policy.max_stdout_bytes,
            max_stderr_bytes=effective_policy.max_stderr_bytes,
            max_file_size_bytes=max_file_size,
            max_workspace_size_bytes=effective_policy.max_workspace_size_bytes,
            max_file_count=config.MAX_FILE_COUNT,
            workspace_tmpfs_size_bytes=workspace_tmpfs_size_bytes,
            workspace_tmpfs_inodes=workspace_inodes,
            tmpfs_size_bytes=tmpfs_size_bytes,
            run_as_uid=int(uid_str),
            run_as_gid=int(gid_str),
        )
