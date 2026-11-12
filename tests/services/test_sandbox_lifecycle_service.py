"""Tests for SandboxLifecycleService."""

import asyncio
import threading
import uuid
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.core.config import SandboxSettings
from app.core.exceptions import (
    DockerEngineError,
    ExecutionNotFoundError,
    SandboxDestroyedError,
    SandboxExpiredError,
    SandboxNotFoundError,
    WorkspaceCleanupError,
)
from app.models.execution_job import JobStatus
from app.models.sandbox import SandboxStatus, utc_now
from app.repositories.execution_repository import ExecutionRepository
from app.sandbox.docker_backend import DockerSandboxBackend
from app.sandbox.docker_client import list_sandbox_containers
from app.sandbox.engine import EphemeralSandboxEngine
from app.sandbox.schemas import ExecutionRequest, ExecutionResult, ExecutionStatus
from app.sandbox.workspace import WorkspaceManager
from app.services.sandbox_lifecycle_service import SandboxLifecycleService


def test_service_create_and_get(db_session: Session, engine: EphemeralSandboxEngine):
    """Test creating and retrieving a sandbox session."""
    service = SandboxLifecycleService(db=db_session, backend=engine)
    sandbox = service.create_sandbox(runtime="python", ttl_seconds=180)

    assert sandbox.id is not None
    assert sandbox.status == SandboxStatus.RUNNING
    assert sandbox.ttl_seconds == 180

    fetched = service.get_sandbox(sandbox.id)
    assert fetched.id == sandbox.id
    assert fetched.status == SandboxStatus.RUNNING


def test_service_delete_idempotent(db_session: Session, engine: EphemeralSandboxEngine):
    """Test destroying a sandbox and repeated idempotent destruction."""
    service = SandboxLifecycleService(db=db_session, backend=engine)
    sandbox = service.create_sandbox(runtime="python", ttl_seconds=180)

    deleted = service.delete_sandbox(sandbox.id)
    assert deleted.status == SandboxStatus.DESTROYED
    assert deleted.destroyed_at is not None

    # Repeated delete must be idempotent
    repeated = service.delete_sandbox(sandbox.id)
    assert repeated.status == SandboxStatus.DESTROYED


def test_service_not_found(db_session: Session, engine: EphemeralSandboxEngine):
    """Test that querying an unknown UUID raises SandboxNotFoundError."""
    service = SandboxLifecycleService(db=db_session, backend=engine)
    random_id = uuid.uuid4()

    with pytest.raises(SandboxNotFoundError):
        service.get_sandbox(random_id)

    with pytest.raises(SandboxNotFoundError):
        service.delete_sandbox(random_id)


@pytest.mark.asyncio
async def test_service_execute_code_success(db_session: Session, engine: EphemeralSandboxEngine):
    """Test executing code within an active persistent sandbox."""
    service = SandboxLifecycleService(db=db_session, backend=engine)
    sandbox = service.create_sandbox(runtime="python", ttl_seconds=180)

    result = await service.execute_code(
        sandbox_id=sandbox.id,
        code="print('Lifecycle Execution Success')",
    )

    assert result.sandbox_id == sandbox.id
    assert result.status == "completed"
    assert result.exit_code == 0
    assert "Lifecycle Execution Success" in result.stdout
    assert result.submitted_at is not None
    assert result.completed_at is not None

    # Verify sandbox is back to RUNNING state
    db_session.refresh(sandbox)
    assert sandbox.status == SandboxStatus.RUNNING
    assert len(sandbox.executions) == 1


@pytest.mark.asyncio
async def test_service_execute_on_destroyed_sandbox_fails(
    db_session: Session,
    engine: EphemeralSandboxEngine,
):
    """Test that executing code on a destroyed sandbox raises SandboxDestroyedError."""
    service = SandboxLifecycleService(db=db_session, backend=engine)
    sandbox = service.create_sandbox(runtime="python", ttl_seconds=180)
    service.delete_sandbox(sandbox.id)

    with pytest.raises(SandboxDestroyedError):
        await service.execute_code(sandbox_id=sandbox.id, code="print('fail')")


@pytest.mark.asyncio
async def test_service_execute_on_expired_sandbox_fails(
    db_session: Session,
    engine: EphemeralSandboxEngine,
):
    """Test that executing code on an expired sandbox raises SandboxExpiredError."""
    service = SandboxLifecycleService(db=db_session, backend=engine)
    sandbox = service.create_sandbox(runtime="python", ttl_seconds=10)

    # Force expiration
    sandbox.expires_at = utc_now() - timedelta(seconds=20)
    db_session.commit()

    with pytest.raises(SandboxExpiredError):
        await service.execute_code(sandbox_id=sandbox.id, code="print('fail')")


def test_service_cleanup_expired_sandboxes(db_session: Session, engine: EphemeralSandboxEngine):
    """Test that cleanup_expired_sandboxes sweeps all expired active sandboxes."""
    service = SandboxLifecycleService(db=db_session, backend=engine)
    now = utc_now()

    # Create active sandbox
    s_active = service.create_sandbox(runtime="python", ttl_seconds=300)

    # Create expired sandbox
    s_expired = service.create_sandbox(runtime="python", ttl_seconds=10)
    s_expired.expires_at = now - timedelta(seconds=30)
    db_session.commit()

    cleaned = service.cleanup_expired_sandboxes()
    assert cleaned == 1

    db_session.refresh(s_expired)
    assert s_expired.status == SandboxStatus.EXPIRED

    db_session.refresh(s_active)
    assert s_active.status == SandboxStatus.RUNNING


def test_service_cleanup_reports_partial_failures(db_session: Session, fast_settings):
    class PartiallyFailingBackend:
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("not used")

        def cleanup_sandbox(self, _sandbox_id: str) -> None:
            self.calls += 1
            if self.calls == 1:
                raise DockerEngineError("temporary cleanup failure")

        def check_health(self) -> None:
            return None

    service = SandboxLifecycleService(
        db=db_session, backend=PartiallyFailingBackend(), config=fast_settings
    )
    now = utc_now()
    first = service.create_sandbox(ttl_seconds=10)
    second = service.create_sandbox(ttl_seconds=10)
    first.expires_at = now - timedelta(seconds=2)
    second.expires_at = now - timedelta(seconds=1)
    db_session.commit()

    assert service.cleanup_expired_sandboxes() == 1
    assert service.last_cleanup_report.attempted == 2
    assert service.last_cleanup_report.succeeded == 1
    assert service.last_cleanup_report.failed == 1


def test_service_get_expired_sandbox_preserves_expired_state(
    db_session: Session, engine: EphemeralSandboxEngine
):
    """A TTL-expired sandbox remains visible as expired instead of silently destroyed."""
    service = SandboxLifecycleService(db=db_session, backend=engine)
    sandbox = service.create_sandbox(runtime="python", ttl_seconds=10)
    sandbox.expires_at = utc_now() - timedelta(seconds=1)
    db_session.commit()

    fetched = service.get_sandbox(sandbox.id)

    assert fetched.status == SandboxStatus.EXPIRED


@pytest.mark.asyncio
async def test_service_persists_engine_failure_as_failed_job(db_session: Session):
    """An infrastructure error finalizes the job instead of leaving it running."""

    class FailingBackend:
        def execute(self, *_args: object, **_kwargs: object) -> None:
            raise DockerEngineError("unavailable")

        def cleanup_sandbox(self, _sandbox_id: str) -> None:
            return None

        def check_health(self) -> None:
            return None

    service = SandboxLifecycleService(db=db_session, backend=FailingBackend())
    sandbox = service.create_sandbox(runtime="python", ttl_seconds=180)

    with pytest.raises(DockerEngineError):
        await service.execute_code(sandbox.id, "print('never runs')")

    jobs = ExecutionRepository(db_session).list_by_sandbox(sandbox.id)
    assert len(jobs) == 1
    assert jobs[0].status == "failed"
    assert jobs[0].completed_at is not None
    assert jobs[0].error_message == "Execution infrastructure failure"


@pytest.mark.asyncio
async def test_service_get_execution_success(db_session: Session, engine: EphemeralSandboxEngine):
    """Test retrieving a historical execution record by sandbox_id and execution_id."""
    service = SandboxLifecycleService(db=db_session, backend=engine)
    sandbox = service.create_sandbox(runtime="python", ttl_seconds=180)

    exec_res = await service.execute_code(sandbox.id, "print('history check')")

    fetched_exec = service.get_execution(sandbox.id, exec_res.execution_id)
    assert fetched_exec.execution_id == exec_res.execution_id
    assert fetched_exec.sandbox_id == sandbox.id
    assert fetched_exec.status == "completed"
    assert "history check" in fetched_exec.stdout
    assert fetched_exec.exit_code == 0
    assert fetched_exec.completed_at is not None


def test_service_get_execution_not_found(db_session: Session, engine: EphemeralSandboxEngine):
    """Test retrieving a non-existent execution ID raises ExecutionNotFoundError."""
    service = SandboxLifecycleService(db=db_session, backend=engine)
    sandbox = service.create_sandbox(runtime="python", ttl_seconds=180)
    random_exec_id = uuid.uuid4()

    with pytest.raises(ExecutionNotFoundError):
        service.get_execution(sandbox.id, random_exec_id)


@pytest.mark.asyncio
async def test_service_get_execution_mismatch_sandbox(
    db_session: Session, engine: EphemeralSandboxEngine
):
    """Test retrieving an execution belonging to another sandbox raises ExecutionNotFoundError."""
    service = SandboxLifecycleService(db=db_session, backend=engine)
    sandbox1 = service.create_sandbox(runtime="python", ttl_seconds=180)
    sandbox2 = service.create_sandbox(runtime="python", ttl_seconds=180)

    exec1 = await service.execute_code(sandbox1.id, "print('sandbox 1')")

    with pytest.raises(ExecutionNotFoundError):
        service.get_execution(sandbox2.id, exec1.execution_id)


# =====================================================================
# Phase 2, Step 3 — Persistent Workspace Lifecycle Integration Tests
# =====================================================================


@pytest.mark.asyncio
async def test_step3_1_successful_destruction_removes_workspace_and_execution_resources(
    db_session: Session,
    engine: EphemeralSandboxEngine,
    fast_settings: SandboxSettings,
):
    """Scenario 1: Successful destruction removes workspace, metadata, and containers."""
    backend = DockerSandboxBackend(config=fast_settings, engine=engine)
    service = SandboxLifecycleService(db=db_session, backend=backend, config=fast_settings)
    sandbox = service.create_sandbox(runtime="python", ttl_seconds=180)
    sid = str(sandbox.id)

    # Write initial workspace files and run code that produces output files
    service.write_file(sandbox.id, "input.txt", "hello-step3")
    service.create_directory(sandbox.id, "sub")
    service.write_file(sandbox.id, "sub/nested.txt", "nested-data")

    exec_res = await service.execute_code(
        sandbox.id,
        "with open('generated.txt', 'w') as f: f.write(open('input.txt').read() + '-done')\n",
    )
    assert exec_res.status == "completed"
    assert service.read_file(sandbox.id, "generated.txt").content == "hello-step3-done"
    assert (fast_settings.WORKSPACE_DIR / sid).exists()

    # Destroy the sandbox
    destroyed = service.delete_sandbox(sandbox.id)
    assert destroyed.status == SandboxStatus.DESTROYED
    assert destroyed.destroyed_at is not None

    # Persistent workspace directory, staging dirs, and lock metadata must be gone
    assert not (fast_settings.WORKSPACE_DIR / sid).exists()
    assert list(fast_settings.WORKSPACE_DIR.glob(f"*{sid}*")) == []
    assert list_sandbox_containers(engine.client, config=fast_settings, all_states=True) == []

    # Post-destruction file and execution calls must fail and never recreate workspace
    with pytest.raises(SandboxDestroyedError):
        service.write_file(sandbox.id, "revive.txt", "nope")
    with pytest.raises(SandboxDestroyedError):
        service.read_file(sandbox.id, "input.txt")
    with pytest.raises(SandboxDestroyedError):
        service.list_files(sandbox.id)
    with pytest.raises(SandboxDestroyedError):
        await service.execute_code(sandbox.id, "print('should not run')")
    assert not (fast_settings.WORKSPACE_DIR / sid).exists()


@pytest.mark.asyncio
async def test_step3_2_container_cleanup_failure_prevents_destroyed_status(
    db_session: Session,
    fast_settings: SandboxSettings,
    tmp_path,
):
    """Scenario 2 & 12: Container cleanup failure leaves sandbox DESTROYING and retryable."""
    ws_settings = fast_settings.model_copy(update={"WORKSPACE_DIR": tmp_path / "ws_s2"})
    ws_mgr = WorkspaceManager(config=ws_settings)
    mock_client = MagicMock()
    engine = EphemeralSandboxEngine(
        config=ws_settings, client=mock_client, workspace_manager=ws_mgr
    )
    backend = DockerSandboxBackend(config=ws_settings, engine=engine, workspace_manager=ws_mgr)
    service = SandboxLifecycleService(db=db_session, backend=backend, config=ws_settings)

    sandbox = service.create_sandbox(runtime="python", ttl_seconds=180)
    sid = str(sandbox.id)
    service.write_file(sandbox.id, "keep_until_clean.txt", "data")

    # Simulate an owned container whose removal fails on first attempt
    failing_container = MagicMock()
    failing_container.id = "c" * 64
    failing_container.attrs = {
        "Config": {
            "Labels": {
                "project": ws_settings.PROJECT_LABEL,
                "managed-by": ws_settings.MANAGED_BY_LABEL,
                "sandbox_id": sid,
            }
        }
    }
    failing_container.reload.side_effect = RuntimeError("Docker daemon socket error")
    mock_client.containers.list.return_value = [failing_container]

    with pytest.raises(DockerEngineError):
        service.delete_sandbox(sandbox.id)

    db_session.refresh(sandbox)
    assert sandbox.status == SandboxStatus.DESTROYING
    assert sandbox.destroyed_at is None
    # Workspace was not yet removed because container cleanup failed first
    assert (ws_settings.WORKSPACE_DIR / sid).exists()

    # New executions and workspace writes must be blocked while in DESTROYING state
    with pytest.raises(SandboxDestroyedError):
        await service.execute_code(sandbox.id, "print('blocked')")
    with pytest.raises(SandboxDestroyedError):
        service.write_file(sandbox.id, "new.txt", "blocked")

    # Now fix container removal and retry delete_sandbox -> succeeds and reaches DESTROYED
    failing_container.reload.side_effect = None
    destroyed = service.delete_sandbox(sandbox.id)
    assert destroyed.status == SandboxStatus.DESTROYED
    assert destroyed.destroyed_at is not None
    assert not (ws_settings.WORKSPACE_DIR / sid).exists()


def test_step3_3_workspace_deletion_failure_prevents_destroyed_status_and_retries(
    db_session: Session,
    fast_settings: SandboxSettings,
    tmp_path,
    monkeypatch,
):
    """Scenario 3 & 12: Workspace deletion failure prevents DESTROYED and stays retryable."""
    ws_settings = fast_settings.model_copy(update={"WORKSPACE_DIR": tmp_path / "ws_s3"})
    ws_mgr = WorkspaceManager(config=ws_settings)
    mock_client = MagicMock()
    mock_client.containers.list.return_value = []
    engine = EphemeralSandboxEngine(
        config=ws_settings, client=mock_client, workspace_manager=ws_mgr
    )
    backend = DockerSandboxBackend(config=ws_settings, engine=engine, workspace_manager=ws_mgr)
    service = SandboxLifecycleService(db=db_session, backend=backend, config=ws_settings)

    sandbox = service.create_sandbox(runtime="python", ttl_seconds=180)
    sid = str(sandbox.id)
    service.write_file(sandbox.id, "artifact.txt", "important")

    orig_delete = ws_mgr.delete_workspace
    fail_once = {"should_fail": True}

    def flaky_delete_workspace(target_id: str) -> None:
        if fail_once["should_fail"]:
            fail_once["should_fail"] = False
            raise WorkspaceCleanupError("Simulated transient filesystem unlink error")
        orig_delete(target_id)

    monkeypatch.setattr(ws_mgr, "delete_workspace", flaky_delete_workspace)

    with pytest.raises(WorkspaceCleanupError):
        service.delete_sandbox(sandbox.id)

    db_session.refresh(sandbox)
    assert sandbox.status == SandboxStatus.DESTROYING
    assert sandbox.destroyed_at is None
    assert (ws_settings.WORKSPACE_DIR / sid).exists()

    # Retry succeeds and marks sandbox DESTROYED
    destroyed = service.delete_sandbox(sandbox.id)
    assert destroyed.status == SandboxStatus.DESTROYED
    assert destroyed.destroyed_at is not None
    assert not (ws_settings.WORKSPACE_DIR / sid).exists()


def test_step3_4_database_update_failure_remains_recoverable(
    db_session: Session,
    fast_settings: SandboxSettings,
    tmp_path,
    monkeypatch,
):
    """Scenario 4: DB failure when recording DESTROYED rolls back cleanly and recovers."""
    ws_settings = fast_settings.model_copy(update={"WORKSPACE_DIR": tmp_path / "ws_s4"})
    ws_mgr = WorkspaceManager(config=ws_settings)
    mock_client = MagicMock()
    mock_client.containers.list.return_value = []
    engine = EphemeralSandboxEngine(
        config=ws_settings, client=mock_client, workspace_manager=ws_mgr
    )
    backend = DockerSandboxBackend(config=ws_settings, engine=engine, workspace_manager=ws_mgr)
    service = SandboxLifecycleService(db=db_session, backend=backend, config=ws_settings)

    sandbox = service.create_sandbox(runtime="python", ttl_seconds=180)
    sid = str(sandbox.id)
    service.write_file(sandbox.id, "db_fail.txt", "payload")

    orig_commit = db_session.commit
    commit_state = {"fail_destroyed": True}

    def flaky_commit() -> None:
        if sandbox.status == SandboxStatus.DESTROYED and commit_state["fail_destroyed"]:
            commit_state["fail_destroyed"] = False
            raise RuntimeError("Simulated PostgreSQL commit failure on DESTROYED")
        orig_commit()

    monkeypatch.setattr(db_session, "commit", flaky_commit)

    with pytest.raises(RuntimeError, match="Simulated PostgreSQL commit failure"):
        service.delete_sandbox(sandbox.id)

    # Session rolled back cleanly; status remains DESTROYING
    db_session.refresh(sandbox)
    assert sandbox.status == SandboxStatus.DESTROYING
    assert sandbox.destroyed_at is None

    # Subsequent retry (or startup reconciliation) cleanly transitions to DESTROYED
    recovered = service.delete_sandbox(sandbox.id)
    assert recovered.status == SandboxStatus.DESTROYED
    assert recovered.destroyed_at is not None
    assert not (ws_settings.WORKSPACE_DIR / sid).exists()


def test_step3_5_repeated_destruction_is_idempotent_and_never_recreates_workspace(
    db_session: Session,
    fast_settings: SandboxSettings,
    tmp_path,
):
    """Scenario 5: Repeated delete_sandbox calls are idempotent and never recreate the workspace."""
    ws_settings = fast_settings.model_copy(update={"WORKSPACE_DIR": tmp_path / "ws_s5"})
    ws_mgr = WorkspaceManager(config=ws_settings)
    mock_client = MagicMock()
    mock_client.containers.list.return_value = []
    engine = EphemeralSandboxEngine(
        config=ws_settings, client=mock_client, workspace_manager=ws_mgr
    )
    backend = DockerSandboxBackend(config=ws_settings, engine=engine, workspace_manager=ws_mgr)
    service = SandboxLifecycleService(db=db_session, backend=backend, config=ws_settings)

    sandbox = service.create_sandbox(runtime="python", ttl_seconds=180)
    sid = str(sandbox.id)
    service.write_file(sandbox.id, "once.txt", "once")

    first = service.delete_sandbox(sandbox.id)
    first_destroyed_at = first.destroyed_at
    assert first.status == SandboxStatus.DESTROYED
    assert not (ws_settings.WORKSPACE_DIR / sid).exists()

    for _ in range(3):
        again = service.delete_sandbox(sandbox.id)
        assert again.status == SandboxStatus.DESTROYED
        assert again.destroyed_at == first_destroyed_at
        assert not (ws_settings.WORKSPACE_DIR / sid).exists()
        assert list(ws_settings.WORKSPACE_DIR.glob(f"*{sid}*")) == []


def test_step3_6_concurrent_destruction_requests_are_safe(
    db_session: Session,
    fast_settings: SandboxSettings,
    tmp_path,
):
    """Scenario 6: Concurrent destruction requests synchronize safely without errors."""
    ws_settings = fast_settings.model_copy(update={"WORKSPACE_DIR": tmp_path / "ws_s6"})
    ws_mgr = WorkspaceManager(config=ws_settings)
    mock_client = MagicMock()
    mock_client.containers.list.return_value = []
    engine = EphemeralSandboxEngine(
        config=ws_settings, client=mock_client, workspace_manager=ws_mgr
    )
    backend = DockerSandboxBackend(config=ws_settings, engine=engine, workspace_manager=ws_mgr)
    service = SandboxLifecycleService(db=db_session, backend=backend, config=ws_settings)

    sandbox = service.create_sandbox(runtime="python", ttl_seconds=180)
    sid = str(sandbox.id)
    service.write_file(sandbox.id, "shared.txt", "concurrent-delete")

    barrier = threading.Barrier(4)
    results: list[SandboxStatus] = []
    errors: list[BaseException] = []
    results_lock = threading.Lock()

    def worker() -> None:
        try:
            barrier.wait(timeout=5.0)
            res = service.delete_sandbox(sandbox.id)
            with results_lock:
                results.append(res.status)
        except BaseException as exc:
            with results_lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    assert errors == []
    assert results == [SandboxStatus.DESTROYED] * 4
    assert not (ws_settings.WORKSPACE_DIR / sid).exists()
    assert ws_mgr._is_exclusive_lock_held(sid) is False


@pytest.mark.asyncio
async def test_step3_7a_execution_versus_destruction_race_in_flight_execution(
    db_session: Session,
    fast_settings: SandboxSettings,
    tmp_path,
):
    """Scenario 7a: Destruction waits for in-flight execution holding lock, then deletes."""
    ws_settings = fast_settings.model_copy(update={"WORKSPACE_DIR": tmp_path / "ws_s7a"})
    ws_mgr = WorkspaceManager(config=ws_settings)

    exec_entered_lock = threading.Event()
    allow_exec_exit = threading.Event()
    cleanup_ran_after_exec = threading.Event()
    events_order: list[str] = []

    class CoordinatedBackend:
        def __init__(self) -> None:
            self.workspace_manager = ws_mgr

        def execute(
            self,
            request: ExecutionRequest,
            *,
            sandbox_id: str | None = None,
        ) -> ExecutionResult:
            assert sandbox_id is not None
            with self.workspace_manager.sandbox_lock(sandbox_id, exclusive=True):
                # Write a file during execution to verify destruction removes it afterward
                self.workspace_manager.write_file(sandbox_id, "during_exec.txt", "written-in-exec")
                events_order.append("exec_holding_lock")
                exec_entered_lock.set()
                assert allow_exec_exit.wait(timeout=5.0), "Timed out waiting for allow_exec_exit"
                events_order.append("exec_releasing_lock")
                return ExecutionResult(
                    sandbox_id=sandbox_id,
                    status=ExecutionStatus.COMPLETED,
                    exit_code=0,
                    stdout="done\n",
                    stderr="",
                    duration_ms=5,
                )

        def cleanup_sandbox(self, sandbox_id: str) -> None:
            with self.workspace_manager.sandbox_lock(sandbox_id, exclusive=True):
                events_order.append("cleanup_acquired_lock")
                self.workspace_manager.delete_workspace(sandbox_id)
                cleanup_ran_after_exec.set()

        def check_health(self) -> None:
            return None

    backend = CoordinatedBackend()
    service = SandboxLifecycleService(db=db_session, backend=backend, config=ws_settings)
    sandbox = service.create_sandbox(runtime="python", ttl_seconds=180)
    sid = str(sandbox.id)
    ws_mgr.write_file(sid, "initial.txt", "before-race")

    # Launch execute_code asynchronously
    exec_task = asyncio.create_task(service.execute_code(sandbox.id, "print('in flight')"))

    # Wait until the worker thread holds the exclusive sandbox lock
    await asyncio.to_thread(exec_entered_lock.wait, 5.0)
    assert exec_entered_lock.is_set()

    # Start delete_sandbox on a background thread; it must transition DB to DESTROYING
    # and then block on sandbox_lock until execution finishes.
    delete_done = threading.Event()
    delete_errors: list[BaseException] = []

    def run_delete() -> None:
        try:
            service.delete_sandbox(sandbox.id)
        except BaseException as exc:
            delete_errors.append(exc)
        finally:
            delete_done.set()

    delete_thread = threading.Thread(target=run_delete)
    delete_thread.start()

    # Wait deterministically until sandbox status is DESTROYING in DB
    for _ in range(100):
        with service._db_lock:
            current = service.sandbox_repo.get_by_id(sandbox.id)
            assert current is not None
            db_session.refresh(current)
            if current.status == SandboxStatus.DESTROYING:
                break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("Sandbox did not transition to DESTROYING while waiting on execution lock")

    # Cleanup must STILL be blocked waiting on sandbox_lock
    assert not cleanup_ran_after_exec.is_set()

    # Any new execution attempt while DESTROYING must immediately fail with SandboxDestroyedError
    with pytest.raises(SandboxDestroyedError):
        await service.execute_code(sandbox.id, "print('rejected while destroying')")

    # Now allow the in-flight execution to finish and release sandbox_lock
    allow_exec_exit.set()
    exec_result = await exec_task
    await asyncio.to_thread(delete_thread.join, 5.0)

    assert delete_errors == []
    assert delete_done.is_set()
    assert exec_result.status == "completed"

    # Ordering proof: execution held and released lock before cleanup acquired lock
    assert events_order == [
        "exec_holding_lock",
        "exec_releasing_lock",
        "cleanup_acquired_lock",
    ]

    # Final state must be DESTROYED (never overwritten back to RUNNING by execute_code's finally)
    # and the workspace must be completely removed.
    db_session.refresh(sandbox)
    assert sandbox.status == SandboxStatus.DESTROYED
    assert sandbox.destroyed_at is not None
    assert not (ws_settings.WORKSPACE_DIR / sid).exists()


@pytest.mark.asyncio
async def test_step3_7b_destruction_before_worker_acquires_lock_aborts_execution(
    db_session: Session,
    fast_settings: SandboxSettings,
    tmp_path,
    monkeypatch,
):
    """Scenario 7b: Destruction before worker lock aborts execution without recreating workspace."""
    ws_settings = fast_settings.model_copy(update={"WORKSPACE_DIR": tmp_path / "ws_s7b"})
    ws_mgr = WorkspaceManager(config=ws_settings)
    mock_client = MagicMock()
    mock_client.containers.list.return_value = []
    engine = EphemeralSandboxEngine(
        config=ws_settings, client=mock_client, workspace_manager=ws_mgr
    )
    backend = DockerSandboxBackend(config=ws_settings, engine=engine, workspace_manager=ws_mgr)
    service = SandboxLifecycleService(db=db_session, backend=backend, config=ws_settings)

    sandbox = service.create_sandbox(runtime="python", ttl_seconds=180)
    sid = str(sandbox.id)
    service.write_file(sandbox.id, "pre_race.txt", "initial")

    orig_mark_started = service.execution_repo.mark_started

    def destroy_before_threadpool(job):
        res = orig_mark_started(job)
        # Simulate concurrent delete_sandbox completing right before _execute_in_backend runs
        service.delete_sandbox(sandbox.id)
        return res

    monkeypatch.setattr(service.execution_repo, "mark_started", destroy_before_threadpool)

    with pytest.raises(SandboxDestroyedError):
        await service.execute_code(sandbox.id, "open('zombie.txt', 'w').write('bad')")

    # Container creation must never have been invoked and workspace must not be recreated
    mock_client.containers.create.assert_not_called()
    assert not (ws_settings.WORKSPACE_DIR / sid).exists()

    db_session.refresh(sandbox)
    assert sandbox.status == SandboxStatus.DESTROYED

    jobs = ExecutionRepository(db_session).list_by_sandbox(sandbox.id)
    assert len(jobs) == 1
    assert jobs[0].status == JobStatus.FAILED


@pytest.mark.asyncio
async def test_step3_8_expired_sandbox_cleanup_removes_workspace_and_blocks_execution(
    db_session: Session,
    fast_settings: SandboxSettings,
    tmp_path,
    monkeypatch,
):
    """Scenario 8: Expired cleanup deletes workspace, blocks execution, and retries on failure."""
    ws_settings = fast_settings.model_copy(update={"WORKSPACE_DIR": tmp_path / "ws_s8"})
    ws_mgr = WorkspaceManager(config=ws_settings)
    mock_client = MagicMock()
    mock_client.containers.list.return_value = []
    engine = EphemeralSandboxEngine(
        config=ws_settings, client=mock_client, workspace_manager=ws_mgr
    )
    backend = DockerSandboxBackend(config=ws_settings, engine=engine, workspace_manager=ws_mgr)
    service = SandboxLifecycleService(db=db_session, backend=backend, config=ws_settings)

    sandbox = service.create_sandbox(runtime="python", ttl_seconds=10)
    sid = str(sandbox.id)
    service.write_file(sandbox.id, "ttl_file.txt", "ephemeral-data")
    assert (ws_settings.WORKSPACE_DIR / sid).exists()

    # Force TTL expiration
    sandbox.expires_at = utc_now() - timedelta(seconds=15)
    db_session.commit()

    # Simulate transient workspace cleanup failure on first expiration sweep
    orig_delete = ws_mgr.delete_workspace
    fail_once = {"fail": True}

    def flaky_delete(target_id: str) -> None:
        if fail_once["fail"]:
            fail_once["fail"] = False
            raise WorkspaceCleanupError("Simulated transient expiry cleanup error")
        orig_delete(target_id)

    monkeypatch.setattr(ws_mgr, "delete_workspace", flaky_delete)

    cleaned_first = service.cleanup_expired_sandboxes()
    assert cleaned_first == 0
    assert service.last_cleanup_report.attempted == 1
    assert service.last_cleanup_report.failed == 1

    # Sandbox is marked EXPIRED in DB and cannot execute code or write files while pending
    db_session.refresh(sandbox)
    assert sandbox.status == SandboxStatus.EXPIRED
    with pytest.raises(SandboxExpiredError):
        await service.execute_code(sandbox.id, "print('blocked while expired')")
    with pytest.raises(SandboxExpiredError):
        service.write_file(sandbox.id, "more.txt", "blocked")

    # Second sweep retries the EXPIRED sandbox and deletes its persistent workspace
    cleaned_second = service.cleanup_expired_sandboxes()
    assert cleaned_second == 1
    assert service.last_cleanup_report.succeeded == 1
    assert not (ws_settings.WORKSPACE_DIR / sid).exists()


def test_step3_9_reconcile_stale_sandboxes_after_partial_cleanup_and_interrupted_execution(
    db_session: Session,
    fast_settings: SandboxSettings,
    tmp_path,
):
    """Scenario 9: Reconciliation completes DESTROYING/EXPIRED cleanup and recovers EXECUTING."""
    ws_settings = fast_settings.model_copy(update={"WORKSPACE_DIR": tmp_path / "ws_s9"})
    ws_mgr = WorkspaceManager(config=ws_settings)
    mock_client = MagicMock()
    mock_client.containers.list.return_value = []
    engine = EphemeralSandboxEngine(
        config=ws_settings, client=mock_client, workspace_manager=ws_mgr
    )
    backend = DockerSandboxBackend(config=ws_settings, engine=engine, workspace_manager=ws_mgr)
    service = SandboxLifecycleService(db=db_session, backend=backend, config=ws_settings)

    past = utc_now() - timedelta(seconds=60)

    # 1. Sandbox interrupted in DESTROYING with leftover workspace and RUNNING job
    s_destroying = service.create_sandbox(runtime="python", ttl_seconds=300)
    sid_destroying = str(s_destroying.id)
    service.write_file(s_destroying.id, "leftover.txt", "must-be-deleted")
    job_destroying = service.execution_repo.create(s_destroying.id, "print(1)", 5.0)
    service.execution_repo.mark_started(job_destroying)
    s_destroying.status = SandboxStatus.DESTROYING
    s_destroying.updated_at = past
    db_session.commit()

    # 2. Sandbox expired with leftover workspace
    s_expired = service.create_sandbox(runtime="python", ttl_seconds=10)
    sid_expired = str(s_expired.id)
    service.write_file(s_expired.id, "expired.txt", "must-be-deleted")
    s_expired.expires_at = past
    db_session.commit()

    # 3. Non-expired sandbox interrupted in EXECUTING with interrupted atomic workspace commit
    s_executing = service.create_sandbox(runtime="python", ttl_seconds=300)
    sid_executing = str(s_executing.id)
    service.write_file(s_executing.id, "active_work.txt", "preserve-me")
    job_executing = service.execution_repo.create(s_executing.id, "print(2)", 5.0)
    service.execution_repo.mark_started(job_executing)
    s_executing.status = SandboxStatus.EXECUTING
    s_executing.updated_at = past
    db_session.commit()

    # Simulate an interrupted atomic commit on s_executing (active moved to backup)
    active_dir = ws_settings.WORKSPACE_DIR / sid_executing
    backup_dir = ws_settings.WORKSPACE_DIR / f".backup.{sid_executing}.crash9"
    active_dir.rename(backup_dir)

    reconciled = service.reconcile_stale_sandboxes()
    assert reconciled == 3
    assert service.last_reconciliation_report.attempted == 3
    assert service.last_reconciliation_report.succeeded == 3
    assert service.last_reconciliation_report.failed == 0

    # Verify 1: s_destroying is now DESTROYED and its workspace is deleted
    db_session.refresh(s_destroying)
    db_session.refresh(job_destroying)
    assert s_destroying.status == SandboxStatus.DESTROYED
    assert job_destroying.status == JobStatus.FAILED
    assert not (ws_settings.WORKSPACE_DIR / sid_destroying).exists()

    # Verify 2: s_expired is EXPIRED and its workspace is deleted
    db_session.refresh(s_expired)
    assert s_expired.status == SandboxStatus.EXPIRED
    assert not (ws_settings.WORKSPACE_DIR / sid_expired).exists()

    # Verify 3: s_executing is back to RUNNING, job is FAILED, and workspace recovered intact!
    db_session.refresh(s_executing)
    db_session.refresh(job_executing)
    assert s_executing.status == SandboxStatus.RUNNING
    assert job_executing.status == JobStatus.FAILED
    assert (ws_settings.WORKSPACE_DIR / sid_executing).exists()
    assert service.read_file(s_executing.id, "active_work.txt").content == "preserve-me"


@pytest.mark.asyncio
async def test_step3_10_no_cross_sandbox_workspace_or_container_deletion(
    db_session: Session,
    engine: EphemeralSandboxEngine,
    fast_settings: SandboxSettings,
):
    """Scenario 10: Destroying Sandbox A never deletes Sandbox B's workspace or containers."""
    backend = DockerSandboxBackend(config=fast_settings, engine=engine)
    service = SandboxLifecycleService(db=db_session, backend=backend, config=fast_settings)

    sandbox_a = service.create_sandbox(runtime="python", ttl_seconds=180)
    sandbox_b = service.create_sandbox(runtime="python", ttl_seconds=180)

    service.write_file(sandbox_a.id, "owner.txt", "sandbox-a-secret")
    service.write_file(sandbox_b.id, "owner.txt", "sandbox-b-secret")

    service.delete_sandbox(sandbox_a.id)

    assert not (fast_settings.WORKSPACE_DIR / str(sandbox_a.id)).exists()
    assert (fast_settings.WORKSPACE_DIR / str(sandbox_b.id)).exists()
    assert service.read_file(sandbox_b.id, "owner.txt").content == "sandbox-b-secret"

    res_b = await service.execute_code(sandbox_b.id, "print(open('owner.txt').read())")
    assert res_b.status == "completed"
    assert res_b.stdout.strip() == "sandbox-b-secret"

    service.delete_sandbox(sandbox_b.id)
    assert not (fast_settings.WORKSPACE_DIR / str(sandbox_b.id)).exists()


@pytest.mark.asyncio
async def test_step3_11_anonymous_execution_volumes_are_removed_on_destruction(
    db_session: Session,
    engine: EphemeralSandboxEngine,
    fast_settings: SandboxSettings,
):
    """Scenario 11: Anonymous /workspace volumes are removed by execution and lifecycle cleanup."""
    from app.sandbox.policy import EffectiveSandboxPolicy
    from app.sandbox.security import build_container_parameters

    backend = DockerSandboxBackend(config=fast_settings, engine=engine)
    service = SandboxLifecycleService(db=db_session, backend=backend, config=fast_settings)
    sandbox = service.create_sandbox(runtime="python", ttl_seconds=180)
    sid = str(sandbox.id)

    volumes_before = {v.name for v in engine.client.volumes.list()}

    # 1. Execute code that writes to /workspace and verify no anonymous volume leaks
    service.write_file(sandbox.id, "seed.txt", "seed-data")
    res = await service.execute_code(
        sandbox.id,
        "open('/workspace/out.txt', 'w').write('volume-check')",
    )
    assert res.status == "completed"
    volumes_after_exec = {v.name for v in engine.client.volumes.list()}
    assert volumes_after_exec - volumes_before == set()

    # 2. Create an orphaned execution container with an anonymous /workspace volume
    #    belonging to this sandbox, then destroy the sandbox and verify the container,
    #    its anonymous volume, and the persistent host workspace are all removed.
    policy = EffectiveSandboxPolicy.from_settings(fast_settings)
    params = build_container_parameters("import time; time.sleep(30)", sid, fast_settings, policy)
    orphan = engine.client.containers.create(**params)
    orphan.reload()
    mounts = orphan.attrs.get("Mounts", [])
    anon_vol_names = {m["Name"] for m in mounts if m.get("Type") == "volume" and "Name" in m}
    assert len(anon_vol_names) == 1

    destroyed = service.delete_sandbox(sandbox.id)
    assert destroyed.status == SandboxStatus.DESTROYED

    volumes_after_destroy = {v.name for v in engine.client.volumes.list()}
    assert anon_vol_names.isdisjoint(volumes_after_destroy)
    assert volumes_after_destroy - volumes_before == set()
    assert not (fast_settings.WORKSPACE_DIR / sid).exists()
