"""QEMU process spawning, exact PID/metadata tracking, termination, and cleanup."""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import SandboxSettings, settings
from app.core.exceptions import QemuEngineError
from app.sandbox.qemu.config import QemuVmConfig, validate_safe_qemu_path
from app.sandbox.qemu.image_manager import PreparedVmStorage, QemuImageManager

logger = logging.getLogger(__name__)


@dataclass
class QemuVmHandle:
    """Active ephemeral QEMU VM instance tracked by the host backend."""

    sandbox_id: str
    execution_id: str
    project_label: str
    managed_by_label: str
    vm_cfg: QemuVmConfig
    storage: PreparedVmStorage
    argv: list[str]
    process: subprocess.Popen[str]

    @property
    def pid(self) -> int:
        return self.process.pid

    def is_alive(self) -> bool:
        return self.process.poll() is None


def build_qemu_command(
    vm_cfg: QemuVmConfig,
    storage: PreparedVmStorage,
) -> list[str]:
    """Construct a strict argument vector for booting an isolated ARM64 QEMU guest.

    Security controls enforced in the argument vector:
    - Hardware virtualization (-accel hvf on macOS ARM64) without silent fallback.
    - No network stack or NIC (-nic none).
    - No USB controller (usb=off), display (-display none), or default devices (-nodefaults).
    - No host filesystem mounts (no 9p / virtiofs).
    - Disposable per-execution qcow2 overlay (-drive ... format=qcow2).
    - Single narrow virtio-serial channel bound to a private 0700 Unix domain socket.
    """
    validate_safe_qemu_path(vm_cfg.kernel_path, "kernel_path")
    validate_safe_qemu_path(vm_cfg.initrd_path, "initrd_path")
    validate_safe_qemu_path(storage.overlay_path, "overlay_path")
    validate_safe_qemu_path(storage.socket_path, "socket_path")
    validate_safe_qemu_path(storage.console_log_path, "console_log_path")
    validate_safe_qemu_path(storage.pidfile_path, "pidfile_path")

    vm_name = f"aisbx-{storage.execution_id[:12]}"
    kernel_cmdline = "console=ttyAMA0 panic=-1 rdinit=/init"

    return [
        vm_cfg.qemu_binary,
        "-name",
        vm_name,
        "-machine",
        f"{vm_cfg.machine},usb=off",
        "-accel",
        vm_cfg.accelerator,
        "-cpu",
        vm_cfg.cpu_model,
        "-m",
        str(vm_cfg.memory_mb),
        "-smp",
        f"cpus={vm_cfg.vcpus}",
        "-nodefaults",
        "-no-user-config",
        "-nographic",
        "-display",
        "none",
        "-monitor",
        "none",
        "-nic",
        "none",
        "-no-reboot",
        "-kernel",
        str(vm_cfg.kernel_path),
        "-initrd",
        str(vm_cfg.initrd_path),
        "-append",
        kernel_cmdline,
        "-drive",
        f"file={storage.overlay_path},if=none,format=qcow2,id=drv0,cache=unsafe",
        "-device",
        "virtio-blk-pci,drive=drv0",
        "-chardev",
        f"socket,id=agent0,path={storage.socket_path},server=on,wait=off",
        "-device",
        "virtio-serial-pci",
        "-device",
        "virtserialport,chardev=agent0,name=org.aisandbox.agent",
        "-serial",
        f"file:{storage.console_log_path}",
        "-pidfile",
        str(storage.pidfile_path),
    ]


class QemuProcessManager:
    """Spawns, tracks, terminates, and reconciles project-owned QEMU VM processes."""

    def __init__(
        self,
        config: SandboxSettings = settings,
        image_manager: QemuImageManager | None = None,
    ) -> None:
        self.config = config
        self.image_manager = image_manager or QemuImageManager(config=config)
        self._active_handles: dict[str, QemuVmHandle] = {}

    def start_vm(
        self,
        *,
        vm_cfg: QemuVmConfig,
        storage: PreparedVmStorage,
    ) -> QemuVmHandle:
        """Spawn a new isolated QEMU VM subprocess and persist ownership metadata."""
        argv = build_qemu_command(vm_cfg, storage)
        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                # Never leave undrained pipes attached to a long-lived VM process;
                # guest console output is captured via -serial file: instead.
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
                close_fds=True,
            )
        except FileNotFoundError as exc:
            self.image_manager.cleanup_storage(storage)
            raise QemuEngineError(f"QEMU binary '{vm_cfg.qemu_binary}' not found on host") from exc
        except OSError as exc:
            self.image_manager.cleanup_storage(storage)
            raise QemuEngineError(f"Failed to start QEMU VM process: {exc}") from exc

        handle = QemuVmHandle(
            sandbox_id=storage.sandbox_id,
            execution_id=storage.execution_id,
            project_label=self.config.PROJECT_LABEL,
            managed_by_label=self.config.MANAGED_BY_LABEL,
            vm_cfg=vm_cfg,
            storage=storage,
            argv=argv,
            process=proc,
        )

        try:
            self._write_metadata(handle)
        except Exception as exc:
            self._terminate_popen(proc, grace_seconds=0.2)
            self.image_manager.cleanup_storage(storage)
            raise QemuEngineError(f"Failed to record VM process metadata: {exc}") from exc

        self._active_handles[storage.execution_id] = handle
        return handle

    def _write_metadata(self, handle: QemuVmHandle) -> None:
        metadata = {
            "project": handle.project_label,
            "managed_by": handle.managed_by_label,
            "sandbox_id": handle.sandbox_id,
            "execution_id": handle.execution_id,
            "pid": handle.pid,
            "runtime_dir": str(handle.storage.runtime_dir),
            "socket_dir": str(handle.storage.socket_dir),
            "socket_path": str(handle.storage.socket_path),
            "overlay_path": str(handle.storage.overlay_path),
            "created_at": time.time(),
        }
        raw = json.dumps(metadata, indent=2).encode("utf-8")
        fd = os.open(
            handle.storage.metadata_path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        try:
            os.write(fd, raw)
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _close_process_streams(proc: subprocess.Popen[Any]) -> None:
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass

    def _terminate_popen(
        self,
        proc: subprocess.Popen[Any],
        *,
        grace_seconds: float = 0.5,
    ) -> bool:
        """Deterministically terminate and reap a Popen process (SIGTERM then SIGKILL)."""
        try:
            if proc.poll() is None:
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass
                except Exception as exc:
                    logger.warning("Error sending SIGTERM to QEMU PID %s: %s", proc.pid, exc)
                    return False

                try:
                    proc.wait(timeout=grace_seconds)
                except subprocess.TimeoutExpired:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    except Exception as exc:
                        logger.error("Error sending SIGKILL to QEMU PID %s: %s", proc.pid, exc)
                        return False
                    try:
                        proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        return False
            else:
                proc.wait(timeout=0.5)
            return proc.poll() is not None
        except Exception as exc:
            logger.error("Failed to terminate/reap QEMU process %s: %s", proc.pid, exc)
            return False
        finally:
            self._close_process_streams(proc)

    def cleanup_vm(
        self,
        handle: QemuVmHandle | None,
        *,
        expected_sandbox_id: str | None = None,
    ) -> bool:
        """Verify ownership, terminate QEMU process, and remove temporary disks/sockets."""
        if handle is None:
            return True

        if (
            handle.project_label != self.config.PROJECT_LABEL
            or handle.managed_by_label != self.config.MANAGED_BY_LABEL
        ):
            logger.error(
                "Refusing to clean up QEMU VM %s: project/managed-by label mismatch",
                handle.execution_id,
            )
            return False

        if expected_sandbox_id is not None and handle.sandbox_id != expected_sandbox_id:
            logger.error(
                "Refusing to clean up QEMU VM %s: sandbox_id mismatch (%s != %s)",
                handle.execution_id,
                handle.sandbox_id,
                expected_sandbox_id,
            )
            return False

        terminated = self._terminate_popen(handle.process)
        if not terminated:
            return False

        storage_cleaned = self.image_manager.cleanup_storage(handle.storage)
        if storage_cleaned:
            self._active_handles.pop(handle.execution_id, None)
        return storage_cleaned

    @staticmethod
    def _verify_pid_matches_execution(pid: int, execution_id: str, runtime_dir: str) -> bool:
        """Confirm a live OS PID belongs to the exact recorded QEMU execution before signaling."""
        if pid <= 1:
            return False
        try:
            proc = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            if proc.returncode != 0:
                return False
            cmdline = proc.stdout.strip()
            return bool(cmdline) and (execution_id[:12] in cmdline or runtime_dir in cmdline)
        except Exception:
            return False

    def _terminate_recorded_pid(self, pid: int, execution_id: str, runtime_dir: str) -> bool:
        """Terminate a stale QEMU process by PID only after verifying its command identity."""
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False

        if not self._verify_pid_matches_execution(pid, execution_id, runtime_dir):
            # PID has been recycled by an unrelated process; do not signal it!
            return True

        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return True
        except OSError:
            return False

        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
                time.sleep(0.02)
            except ProcessLookupError:
                return True

        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return True
        except OSError:
            return False

        return True

    def cleanup_sandbox_vms(self, sandbox_id: str) -> None:
        """Clean up all project-owned ephemeral QEMU VMs and runtime dirs for a sandbox_id."""
        # 1. Clean active in-memory handles for this sandbox
        for exec_id, handle in list(self._active_handles.items()):
            if handle.sandbox_id == sandbox_id:
                if not self.cleanup_vm(handle, expected_sandbox_id=sandbox_id):
                    raise QemuEngineError(
                        f"Failed to clean up active QEMU VM {exec_id} for sandbox {sandbox_id}"
                    )

        # 2. Scan runtime directory for any orphaned on-disk VM directories for this sandbox
        runtime_base = self.config.QEMU_RUNTIME_DIR
        if not runtime_base.is_dir() or runtime_base.is_symlink():
            return

        for entry in list(runtime_base.iterdir()):
            if not entry.is_dir() or entry.is_symlink() or not entry.name.startswith("vm-"):
                continue
            meta_file = entry / "vm_metadata.json"
            if not meta_file.is_file() or meta_file.is_symlink():
                continue
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception as exc:
                raise QemuEngineError(
                    f"Unreadable VM metadata during cleanup for sandbox {sandbox_id}: {exc}"
                ) from exc

            if (
                meta.get("project") != self.config.PROJECT_LABEL
                or meta.get("managed_by") != self.config.MANAGED_BY_LABEL
            ):
                continue
            if meta.get("sandbox_id") != sandbox_id:
                continue

            pid = int(meta.get("pid", -1))
            exec_id = str(meta.get("execution_id", entry.name))
            socket_dir = Path(meta.get("socket_dir", str(entry)))

            if not self._terminate_recorded_pid(pid, exec_id, str(entry)):
                raise QemuEngineError(
                    f"Failed to terminate stale QEMU VM process {pid} for sandbox {sandbox_id}"
                )
            if not QemuImageManager._remove_storage_dirs(entry, socket_dir):
                raise QemuEngineError(
                    f"Failed to remove runtime directory '{entry}' for sandbox {sandbox_id}"
                )
