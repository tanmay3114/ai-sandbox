"""Provider-neutral contract, persistence, concurrency, and failure tests for QemuSandboxBackend."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tarfile
import tempfile
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.core.config import SandboxSettings
from app.core.exceptions import (
    ConcurrencyLimitError,
    FileQuotaExceededError,
    QemuAgentTimeoutError,
    QemuEngineError,
    QemuProtocolError,
)
from app.models.sandbox import SandboxStatus
from app.sandbox.backend import SandboxBackend
from app.sandbox.docker_backend import DockerSandboxBackend
from app.sandbox.engine import EphemeralSandboxEngine
from app.sandbox.qemu.config import QemuVmConfig
from app.sandbox.qemu.guest_protocol import GuestExecutionOutcome
from app.sandbox.qemu.image_manager import PreparedVmStorage, QemuImageManager
from app.sandbox.qemu.process_manager import QemuProcessManager, QemuVmHandle
from app.sandbox.qemu.vm_manager import QemuVmManager
from app.sandbox.qemu_backend import QemuSandboxBackend
from app.sandbox.schemas import ExecutionRequest, ExecutionStatus
from app.services.sandbox_lifecycle_service import SandboxLifecycleService


@pytest.fixture(autouse=True)
def verify_no_container_leak():
    """Tests in this module use mocked Docker/QEMU hypervisors and local Unix sockets."""
    yield


def _build_workspace_tar_spool(
    files: dict[str, bytes],
    dirs: set[str] | None = None,
) -> tempfile.SpooledTemporaryFile[bytes]:
    """Create a SpooledTemporaryFile containing a PAX tar archive rooted at 'workspace/'."""
    spool: tempfile.SpooledTemporaryFile[bytes] = tempfile.SpooledTemporaryFile(
        max_size=1024 * 1024,
        mode="w+b",
    )
    with tarfile.open(fileobj=spool, mode="w", format=tarfile.PAX_FORMAT) as tf:
        root = tarfile.TarInfo("workspace")
        root.type = tarfile.DIRTYPE
        root.mode = 0o700
        root.uid = 10001
        root.gid = 10001
        tf.addfile(root)
        for d in sorted(dirs or ()):
            d_info = tarfile.TarInfo(f"workspace/{d}")
            d_info.type = tarfile.DIRTYPE
            d_info.mode = 0o700
            d_info.uid = 10001
            d_info.gid = 10001
            tf.addfile(d_info)
        for rel_path, content in files.items():
            info = tarfile.TarInfo(f"workspace/{rel_path}")
            info.type = tarfile.REGTYPE
            info.size = len(content)
            info.mode = 0o600
            info.uid = 10001
            info.gid = 10001
            tf.addfile(info, io.BytesIO(content))
    spool.seek(0)
    return spool


class _InMemoryGuestSim:
    """Deterministic guest agent client double that simulates an ephemeral VM's /workspace."""

    def __init__(
        self,
        *,
        exit_code: int = 0,
        timed_out: bool = False,
        stdout: str = "ok\n",
        stderr: str = "",
        output_files: dict[str, bytes] | None = None,
        fail_boot: Exception | None = None,
        fail_execute: Exception | None = None,
        fail_export: Exception | None = None,
        execution_event: threading.Event | None = None,
        release_event: threading.Event | None = None,
    ) -> None:
        self.exit_code = exit_code
        self.timed_out = timed_out
        self.stdout = stdout
        self.stderr = stderr
        self.output_files = dict(output_files or {})
        self.fail_boot = fail_boot
        self.fail_execute = fail_execute
        self.fail_export = fail_export
        self.execution_event = execution_event
        self.release_event = release_event
        self.injected_files: dict[str, bytes] = {}
        self.injected_dirs: set[str] = set()
        self.last_timeout: float | None = None
        self.shutdown_called = False
        self.closed = False

    def wait_until_ready(self, **kwargs: Any) -> dict[str, Any]:
        if self.fail_boot is not None:
            raise self.fail_boot
        return {"agent_version": 1}

    def inject_archive(self, archive_payload: Any, **kwargs: Any) -> dict[str, Any]:
        if hasattr(archive_payload, "seek"):
            archive_payload.seek(0)
            stream = archive_payload
        else:
            stream = io.BytesIO(archive_payload)
        with tarfile.open(fileobj=stream, mode="r:*") as tf:
            for member in tf:
                name = member.name.strip()
                while name.startswith("./"):
                    name = name[2:]
                if name in {"", ".", "/"}:
                    continue
                if member.isdir():
                    self.injected_dirs.add(name)
                elif member.isreg():
                    f = tf.extractfile(member)
                    if f is not None:
                        self.injected_files[name] = f.read()
        return {"files_injected": len(self.injected_files)}

    def execute_code(
        self,
        code: str,
        *,
        timeout_seconds: float,
        max_stdout_bytes: int,
        max_stderr_bytes: int,
    ) -> GuestExecutionOutcome:
        self.last_timeout = timeout_seconds
        if self.execution_event is not None:
            self.execution_event.set()
        if self.release_event is not None:
            self.release_event.wait(timeout=5.0)
        if self.fail_execute is not None:
            raise self.fail_execute

        raw_out = self.stdout.encode("utf-8")
        raw_err = self.stderr.encode("utf-8")
        out_trunc = len(raw_out) > max_stdout_bytes
        err_trunc = len(raw_err) > max_stderr_bytes
        return GuestExecutionOutcome(
            exit_code=None if self.timed_out else self.exit_code,
            timed_out=self.timed_out,
            stdout=raw_out[:max_stdout_bytes].decode("utf-8", errors="replace"),
            stderr=raw_err[:max_stderr_bytes].decode("utf-8", errors="replace"),
            stdout_truncated=out_trunc,
            stderr_truncated=err_trunc,
        )

    def export_archive(self, **kwargs: Any) -> tempfile.SpooledTemporaryFile[bytes]:
        if self.fail_export is not None:
            raise self.fail_export
        merged = dict(self.injected_files)
        merged.update(self.output_files)
        return _build_workspace_tar_spool(merged, dirs=self.injected_dirs)

    def shutdown(self, **kwargs: Any) -> None:
        self.shutdown_called = True

    def close(self) -> None:
        self.closed = True


def _make_qemu_backend_with_sim(
    fast_settings: SandboxSettings,
    tmp_path: Path,
    sim_factory: Any,
    *,
    cleanup_ok: bool = True,
) -> tuple[QemuSandboxBackend, MagicMock, MagicMock]:
    cfg = fast_settings.model_copy(
        update={
            "BACKEND": "qemu",
            "QEMU_IMAGE_DIR": tmp_path / "images",
            "QEMU_RUNTIME_DIR": tmp_path / "runtime",
        }
    )
    img_mgr = MagicMock(spec=QemuImageManager)
    proc_mgr = MagicMock(spec=QemuProcessManager)

    def _prepare_storage(
        *, sandbox_id: str, vm_cfg: QemuVmConfig, execution_id: str | None = None
    ) -> PreparedVmStorage:
        exec_id = execution_id or "exec12345678"
        rdir = cfg.QEMU_RUNTIME_DIR / f"vm-{exec_id}"
        rdir.mkdir(parents=True, exist_ok=True)
        return PreparedVmStorage(
            sandbox_id=sandbox_id,
            execution_id=exec_id,
            runtime_dir=rdir,
            socket_dir=rdir,
            socket_path=rdir / "a.sock",
            overlay_path=rdir / "overlay.qcow2",
            pidfile_path=rdir / "qemu.pid",
            console_log_path=rdir / "console.log",
            metadata_path=rdir / "vm_metadata.json",
        )

    def _start_vm(*, vm_cfg: QemuVmConfig, storage: PreparedVmStorage) -> QemuVmHandle:
        proc = MagicMock()
        proc.pid = 55111
        proc.poll.return_value = None
        return QemuVmHandle(
            sandbox_id=storage.sandbox_id,
            execution_id=storage.execution_id,
            project_label=cfg.PROJECT_LABEL,
            managed_by_label=cfg.MANAGED_BY_LABEL,
            vm_cfg=vm_cfg,
            storage=storage,
            argv=["qemu-system-aarch64"],
            process=proc,
        )

    img_mgr.prepare_execution_storage.side_effect = _prepare_storage
    proc_mgr.start_vm.side_effect = _start_vm
    proc_mgr.cleanup_vm.return_value = cleanup_ok

    vm_mgr = QemuVmManager(
        config=cfg,
        image_manager=img_mgr,
        process_manager=proc_mgr,
        client_factory=lambda storage, vm_cfg: sim_factory(),
    )
    backend = QemuSandboxBackend(config=cfg, vm_manager=vm_mgr)
    return backend, img_mgr, proc_mgr


@pytest.mark.parametrize("backend_kind", ["docker", "qemu"])
def test_provider_neutral_backend_contract_equivalence(
    backend_kind: str,
    fast_settings: SandboxSettings,
    tmp_path: Path,
):
    """Run the identical provider-neutral contract test suite against Docker and QEMU backends."""
    ws_dir = tmp_path / f"ws_{backend_kind}"
    cfg = fast_settings.model_copy(update={"WORKSPACE_DIR": ws_dir, "BACKEND": backend_kind})

    if backend_kind == "docker":
        client = MagicMock()
        container = MagicMock()
        container.id = "d" * 64
        container.attrs = {
            "Config": {
                "Labels": {
                    "project": cfg.PROJECT_LABEL,
                    "managed-by": cfg.MANAGED_BY_LABEL,
                    "sandbox_id": "sbx-contract",
                }
            }
        }
        container.wait.return_value = {"StatusCode": 0}
        container.logs.side_effect = lambda stdout=False, stderr=False, stream=True: (
            iter([b"hello contract\n"]) if stdout else iter([b""])
        )
        container.get_archive.side_effect = lambda path: (
            _build_workspace_tar_spool(
                {"seed.txt": b"initial\n", "produced.txt": b"from_execution\n"},
                dirs={"subdir"},
            ),
            {},
        )
        client.containers.create.return_value = container
        client.containers.list.return_value = []
        backend: SandboxBackend = DockerSandboxBackend(
            config=cfg,
            engine=EphemeralSandboxEngine(config=cfg, client=client),
        )
    else:
        backend, _, _ = _make_qemu_backend_with_sim(
            cfg,
            tmp_path,
            lambda: _InMemoryGuestSim(
                exit_code=0,
                stdout="hello contract\n",
                output_files={"produced.txt": b"from_execution\n"},
            ),
        )

    assert isinstance(backend, SandboxBackend)

    # 1. Workspace file operations contract
    backend.create_directory("sbx-contract", "subdir")
    info = backend.write_file("sbx-contract", "seed.txt", "initial\n")
    assert info.path == "seed.txt"
    assert backend.read_file("sbx-contract", "seed.txt").content == "initial\n"

    listing = backend.list_files("sbx-contract")
    assert {f.path for f in listing.files} == {"subdir", "seed.txt"}

    # 2. Execution and workspace persistence contract
    res = backend.execute(
        ExecutionRequest(code="print('hello contract')"), sandbox_id="sbx-contract"
    )
    assert res.status == ExecutionStatus.COMPLETED
    assert res.exit_code == 0
    assert res.stdout == "hello contract\n"
    assert backend.read_file("sbx-contract", "produced.txt").content == "from_execution\n"

    # 3. File deletion and sandbox cleanup contract
    assert backend.delete_file("sbx-contract", "subdir") is True
    backend.cleanup_sandbox("sbx-contract")
    assert not (ws_dir / "sbx-contract").exists()


def test_qemu_workspace_persistence_matrix_all_cases(
    fast_settings: SandboxSettings,
    tmp_path: Path,
):
    """Verify Stage 6 persistence matrix across COMPLETED, FAILED, TIMED_OUT, and failure modes."""
    sandbox_id = "sbx-matrix"

    # Case 1: Successful execution (COMPLETED) imports valid changes
    sims: list[_InMemoryGuestSim] = [
        _InMemoryGuestSim(
            exit_code=0,
            stdout="step1\n",
            output_files={"step1.txt": b"step1_data"},
        )
    ]
    backend, _, proc_mgr = _make_qemu_backend_with_sim(
        fast_settings,
        tmp_path,
        lambda: sims[-1],
    )
    backend.write_file(sandbox_id, "base.txt", "base_value")

    r1 = backend.execute(ExecutionRequest(code="print('step1')"), sandbox_id=sandbox_id)
    assert r1.status == ExecutionStatus.COMPLETED
    assert r1.exit_code == 0
    assert backend.read_file(sandbox_id, "base.txt").content == "base_value"
    assert backend.read_file(sandbox_id, "step1.txt").content == "step1_data"

    # Case 2: Non-zero exit code (FAILED) still imports valid changes and preserves exit code
    sims.append(
        _InMemoryGuestSim(
            exit_code=7,
            stderr="non-zero failure\n",
            output_files={"step2.txt": b"saved_before_exit"},
        )
    )
    r2 = backend.execute(ExecutionRequest(code="import sys; sys.exit(7)"), sandbox_id=sandbox_id)
    assert r2.status == ExecutionStatus.FAILED
    assert r2.exit_code == 7
    assert backend.read_file(sandbox_id, "step1.txt").content == "step1_data"
    assert backend.read_file(sandbox_id, "step2.txt").content == "saved_before_exit"

    # Case 3: Timeout (TIMED_OUT) preserves previous workspace without importing partial files
    sims.append(
        _InMemoryGuestSim(
            timed_out=True,
            output_files={"corrupt_timeout.txt": b"partial"},
        )
    )
    r3 = backend.execute(
        ExecutionRequest(code="while True: pass", timeout_seconds=0.5),
        sandbox_id=sandbox_id,
    )
    assert r3.status == ExecutionStatus.TIMED_OUT
    assert r3.exit_code is None
    assert sims[-1].last_timeout == 0.5
    files_after_timeout = {f.path for f in backend.list_files(sandbox_id).files}
    assert "corrupt_timeout.txt" not in files_after_timeout
    assert backend.read_file(sandbox_id, "step2.txt").content == "saved_before_exit"

    # Case 4: Guest boot failure preserves previous workspace
    sims.append(
        _InMemoryGuestSim(
            fail_boot=QemuAgentTimeoutError("guest kernel did not reach init"),
            output_files={"never.txt": b"x"},
        )
    )
    r4 = backend.execute(ExecutionRequest(code="print(1)"), sandbox_id=sandbox_id)
    assert r4.status == ExecutionStatus.ERROR
    assert r4.exit_code is None
    assert "initialization" in (r4.error_message or "").lower()
    assert backend.read_file(sandbox_id, "step2.txt").content == "saved_before_exit"

    # Case 5: Communication failure during execution preserves previous workspace
    sims.append(
        _InMemoryGuestSim(
            fail_execute=QemuProtocolError("Unexpected EOF from QEMU guest agent"),
            output_files={"never2.txt": b"x"},
        )
    )
    r5 = backend.execute(ExecutionRequest(code="print(1)"), sandbox_id=sandbox_id)
    assert r5.status == ExecutionStatus.ERROR
    assert "communication failure" in (r5.error_message or "").lower()
    assert backend.read_file(sandbox_id, "step2.txt").content == "saved_before_exit"

    # Case 6: Archive retrieval failure preserves previous workspace
    sims.append(
        _InMemoryGuestSim(
            exit_code=0,
            fail_export=QemuProtocolError("Truncated archive stream"),
        )
    )
    r6 = backend.execute(ExecutionRequest(code="print(1)"), sandbox_id=sandbox_id)
    assert r6.status == ExecutionStatus.ERROR
    assert "unable to retrieve workspace archive" in (r6.error_message or "").lower()
    assert backend.read_file(sandbox_id, "step2.txt").content == "saved_before_exit"

    # Case 7: Archive validation / quota failure preserves previous workspace
    sims.append(
        _InMemoryGuestSim(
            exit_code=0,
            fail_export=FileQuotaExceededError("Guest workspace quota exceeded"),
        )
    )
    r7 = backend.execute(ExecutionRequest(code="print(1)"), sandbox_id=sandbox_id)
    assert r7.status == ExecutionStatus.ERROR
    assert "exceeded configured resource or quota limits" in (r7.error_message or "").lower()
    assert backend.read_file(sandbox_id, "step2.txt").content == "saved_before_exit"

    # Every single execution path cleaned up its VM handle
    assert proc_mgr.cleanup_vm.call_count == 7


def test_qemu_concurrency_limits_and_same_sandbox_serialization(
    fast_settings: SandboxSettings,
    tmp_path: Path,
):
    """Verify concurrent execution limits and workspace lock serialization."""
    exec_started = threading.Event()
    release_exec = threading.Event()

    backend, _, _ = _make_qemu_backend_with_sim(
        fast_settings.model_copy(update={"GLOBAL_CONCURRENCY_LIMIT": 1}),
        tmp_path,
        lambda: _InMemoryGuestSim(
            exit_code=0,
            execution_event=exec_started,
            release_event=release_exec,
        ),
    )

    res_holder: list[Any] = []

    def _first_worker() -> None:
        res_holder.append(backend.execute(ExecutionRequest(code="print(1)"), sandbox_id="sbx-1"))

    t1 = threading.Thread(target=_first_worker)
    t1.start()
    assert exec_started.wait(timeout=3.0)

    # Second concurrent execution while slot 1 is busy must raise ConcurrencyLimitError immediately
    with pytest.raises(ConcurrencyLimitError):
        backend.execute(ExecutionRequest(code="print(2)"), sandbox_id="sbx-2")

    release_exec.set()
    t1.join(timeout=3.0)
    assert len(res_holder) == 1
    assert res_holder[0].status == ExecutionStatus.COMPLETED


def test_qemu_cleanup_failure_raises_qemu_engine_error_and_releases_slot(
    fast_settings: SandboxSettings,
    tmp_path: Path,
):
    """If VM termination or disk cleanup fails, QemuEngineError is raised and slot released."""
    backend, _, _ = _make_qemu_backend_with_sim(
        fast_settings.model_copy(update={"GLOBAL_CONCURRENCY_LIMIT": 1}),
        tmp_path,
        lambda: _InMemoryGuestSim(exit_code=0),
        cleanup_ok=False,
    )

    with pytest.raises(QemuEngineError, match="Verified VM cleanup failed"):
        backend.execute(ExecutionRequest(code="print('hi')"), sandbox_id="sbx-fail-clean")

    # Semaphore must have been released so a subsequent call does not hit ConcurrencyLimitError
    assert backend.vm_manager._semaphore._value == 1


@pytest.mark.asyncio
async def test_qemu_backend_with_lifecycle_service_and_stale_vm_reconciliation(
    db_session,
    fast_settings: SandboxSettings,
    tmp_path: Path,
):
    """Verify SandboxLifecycleService with QemuSandboxBackend and restart reconciliation."""
    sock_base = Path(f"/tmp/aisbx-lc-{os.getuid()}-{os.urandom(3).hex()}")
    sock_base.mkdir(parents=True, exist_ok=True, mode=0o700)
    agent_script = Path(__file__).resolve().parents[2] / "guest" / "agent" / "guest_agent.py"

    cfg = fast_settings.model_copy(
        update={
            "BACKEND": "qemu",
            "WORKSPACE_DIR": tmp_path / "workspaces",
            "QEMU_IMAGE_DIR": tmp_path / "images",
            "QEMU_RUNTIME_DIR": sock_base,
        }
    )

    # Wire QemuVmManager to spawn the real guest_agent.py over a local Unix socket per execution
    img_mgr = MagicMock(spec=QemuImageManager)
    proc_mgr = MagicMock(spec=QemuProcessManager)
    spawned_procs: list[subprocess.Popen[str]] = []

    def _prepare_storage(
        *, sandbox_id: str, vm_cfg: QemuVmConfig, execution_id: str | None = None
    ) -> PreparedVmStorage:
        exec_id = os.urandom(4).hex()
        rdir = sock_base / f"vm-{exec_id}"
        rdir.mkdir(parents=True, exist_ok=True, mode=0o700)
        (rdir / "guest_ws").mkdir(mode=0o700)
        return PreparedVmStorage(
            sandbox_id=sandbox_id,
            execution_id=exec_id,
            runtime_dir=rdir,
            socket_dir=rdir,
            socket_path=rdir / "a.sock",
            overlay_path=rdir / "overlay.qcow2",
            pidfile_path=rdir / "qemu.pid",
            console_log_path=rdir / "console.log",
            metadata_path=rdir / "vm_metadata.json",
        )

    def _start_vm(*, vm_cfg: QemuVmConfig, storage: PreparedVmStorage) -> QemuVmHandle:
        proc = subprocess.Popen(
            [
                sys.executable,
                str(agent_script),
                "--workspace-dir",
                str(storage.runtime_dir / "guest_ws"),
                "--unix-socket",
                str(storage.socket_path),
                "--no-drop-privileges",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        spawned_procs.append(proc)
        return QemuVmHandle(
            sandbox_id=storage.sandbox_id,
            execution_id=storage.execution_id,
            project_label=cfg.PROJECT_LABEL,
            managed_by_label=cfg.MANAGED_BY_LABEL,
            vm_cfg=vm_cfg,
            storage=storage,
            argv=["guest_agent.py"],
            process=proc,
        )

    def _cleanup_vm(handle: QemuVmHandle, expected_sandbox_id: str | None = None) -> bool:
        if handle.process.poll() is None:
            handle.process.kill()
            handle.process.wait(timeout=2.0)
        if handle.process.stdout:
            handle.process.stdout.close()
        if handle.process.stderr:
            handle.process.stderr.close()
        return QemuImageManager._remove_storage_dirs(
            handle.storage.runtime_dir, handle.storage.socket_dir
        )

    img_mgr.prepare_execution_storage.side_effect = _prepare_storage
    proc_mgr.start_vm.side_effect = _start_vm
    proc_mgr.cleanup_vm.side_effect = _cleanup_vm

    vm_mgr = QemuVmManager(config=cfg, image_manager=img_mgr, process_manager=proc_mgr)
    backend = QemuSandboxBackend(config=cfg, vm_manager=vm_mgr)
    service = SandboxLifecycleService(db=db_session, backend=backend, config=cfg)

    try:
        sandbox = service.create_sandbox(ttl_seconds=120)

        # Execution 1 in VM #1 creates a file in /workspace
        res1 = await service.execute_code(
            sandbox.id,
            "import pathlib; pathlib.Path('counter.txt').write_text('10'); print('vm1_done')",
        )
        assert res1.status == ExecutionStatus.COMPLETED
        assert res1.stdout == "vm1_done\n"

        # Execution 2 in fresh VM #2 reads the persisted file from VM #1 and updates it
        res2 = await service.execute_code(
            sandbox.id,
            "import pathlib\n"
            "val = int(pathlib.Path('counter.txt').read_text())\n"
            "pathlib.Path('counter.txt').write_text(str(val + 5))\n"
            "print(f'vm2_val={val + 5}')\n",
        )
        assert res2.status == ExecutionStatus.COMPLETED
        assert res2.stdout == "vm2_val=15\n"
        assert service.read_file(sandbox.id, "counter.txt").content == "15"

        # Verify both ephemeral VMs exited and their runtime directories were removed
        assert len(spawned_procs) == 2
        for p in spawned_procs:
            assert p.poll() is not None

        # Simulate interrupted execution state left behind before restart
        sandbox.status = SandboxStatus.EXECUTING
        db_session.commit()

        reconciled = service.reconcile_stale_sandboxes()
        assert reconciled >= 1
        db_session.refresh(sandbox)
        assert sandbox.status == SandboxStatus.RUNNING
        proc_mgr.cleanup_sandbox_vms.assert_called_with(str(sandbox.id))

        # Destroy sandbox and confirm workspace is removed
        service.delete_sandbox(sandbox.id)
        db_session.refresh(sandbox)
        assert sandbox.status == SandboxStatus.DESTROYED
        assert not (cfg.WORKSPACE_DIR / str(sandbox.id)).exists()
    finally:
        for p in spawned_procs:
            if p.poll() is None:
                p.kill()
                p.wait(timeout=1.0)
        QemuImageManager._remove_storage_dirs(sock_base, sock_base)
