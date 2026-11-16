import os
from collections.abc import Generator
from pathlib import Path

import docker
import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import SandboxSettings, settings
from app.db.session import SessionLocal
from app.models.agent_task import AgentTask
from app.models.execution_job import ExecutionJob
from app.models.sandbox import Sandbox
from app.sandbox.docker_client import list_sandbox_containers
from app.sandbox.engine import EphemeralSandboxEngine


def pytest_sessionstart(session: pytest.Session) -> None:
    """Strict pre-flight safety barrier: abort immediately if not in isolated test environment."""
    env = getattr(settings, "ENVIRONMENT", "")
    db_url = getattr(settings, "DATABASE_URL", "")
    proj_label = getattr(settings, "PROJECT_LABEL", "")
    managed_by = getattr(settings, "MANAGED_BY_LABEL", "")
    compose_proj = os.environ.get("COMPOSE_PROJECT_NAME", "")

    errors = []
    if env != "test":
        errors.append(f"SANDBOX_ENVIRONMENT must be 'test', got '{env}'")
    if "ai_sandbox_test" not in db_url:
        errors.append(f"DATABASE_URL must target 'ai_sandbox_test', got '{db_url}'")
    if "ai_sandbox_db" in db_url:
        errors.append("DATABASE_URL points to normal development database 'ai_sandbox_db'!")
    if proj_label != "ai-sandbox-test":
        errors.append(f"PROJECT_LABEL must be 'ai-sandbox-test', got '{proj_label}'")
    if proj_label == "ai-sandbox":
        errors.append("PROJECT_LABEL matches the normal development project label 'ai-sandbox'!")
    if managed_by != "ai-sandbox-platform-test":
        errors.append(f"MANAGED_BY_LABEL must be 'ai-sandbox-platform-test', got '{managed_by}'")
    if compose_proj != "ai-sandbox-test":
        errors.append(f"COMPOSE_PROJECT_NAME must be 'ai-sandbox-test', got '{compose_proj}'")

    if errors:
        msg = (
            "\n" + "=" * 78 + "\n"
            "CRITICAL SAFETY BARRIER PREVENTED TEST EXECUTION!\n"
            "The test suite was invoked without the isolated test environment active.\n"
            "To prevent mutating or deleting development resources, pytest aborted.\n\n"
            "Safety Violations:\n  * " + "\n  * ".join(errors) + "\n\n"
            "Resolution:\n"
            "  Run tests using scripts/run_isolated_tests.sh or source .env.test.\n" + "=" * 78
        )
        raise pytest.UsageError(msg)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Isolated database session fixture with automatic post-test cleanup."""
    if "ai_sandbox_test" not in settings.DATABASE_URL or "ai_sandbox_db" in settings.DATABASE_URL:
        pytest.fail(
            f"CRITICAL SAFETY VIOLATION: db_session connected to '{settings.DATABASE_URL}', "
            "which is NOT the disposable test database 'ai_sandbox_test'!"
        )

    session = SessionLocal()
    from app.services.agent_orchestrator_service import AgentOrchestratorService

    AgentOrchestratorService._shutting_down = False
    try:
        yield session
    finally:
        AgentOrchestratorService._shutting_down = False
        session.rollback()
        try:
            session.execute(delete(AgentTask))
            session.execute(delete(ExecutionJob))
            session.execute(delete(Sandbox))
            session.commit()
        except Exception:
            session.rollback()
        session.close()


@pytest.fixture(scope="session")
def docker_client() -> docker.DockerClient | None:
    """Session Docker client or None if Docker daemon is not available."""
    try:
        client = docker.from_env()
        client.ping()
        return client
    except Exception:
        return None


@pytest.fixture
def fast_settings(tmp_path: Path) -> SandboxSettings:
    """Fast settings profile for test execution."""
    return SandboxSettings(
        TIMEOUT_SECONDS=2.0,
        MEMORY_LIMIT="128m",
        MEMSWAP_LIMIT="128m",
        CPU_LIMIT=0.5,
        MAX_STDOUT_BYTES=1024,
        MAX_STDERR_BYTES=1024,
        PIDS_LIMIT=32,
        GLOBAL_CONCURRENCY_LIMIT=2,
        PROJECT_LABEL="ai-sandbox-test",
        MANAGED_BY_LABEL="ai-sandbox-platform-test",
        WORKSPACE_DIR=tmp_path / "workspaces",
    )


@pytest.fixture
def engine(
    fast_settings: SandboxSettings,
    docker_client: docker.DockerClient,
) -> EphemeralSandboxEngine:
    """EphemeralSandboxEngine instance configured with test settings."""
    return EphemeralSandboxEngine(config=fast_settings, client=docker_client)


@pytest.fixture(autouse=True)
def verify_no_container_leak(
    docker_client: docker.DockerClient,
    fast_settings: SandboxSettings,
):
    """Autouse fixture ensuring no orphaned sandbox containers remain after every test."""
    yield
    if fast_settings.PROJECT_LABEL != "ai-sandbox-test":
        pytest.fail(
            f"CRITICAL SAFETY VIOLATION: fast_settings.PROJECT_LABEL is "
            f"'{fast_settings.PROJECT_LABEL}' (expected 'ai-sandbox-test'). "
            "Refusing to perform container leak cleanup."
        )

    if docker_client is None:
        return
    # Check for leaked containers with label project=ai-sandbox-test and sandbox_id
    leaked = list_sandbox_containers(docker_client, config=fast_settings, all_states=True)
    if leaked:
        cids = [c.id[:12] for c in leaked]
        # Force cleanup any leaked container from THIS TEST PROJECT ONLY
        for c in leaked:
            try:
                c.reload()
                labels = c.attrs.get("Config", {}).get("Labels", {})
                if (
                    labels.get("project") != "ai-sandbox-test"
                    or labels.get("managed-by") != "ai-sandbox-platform-test"
                ):
                    pytest.fail(
                        f"CRITICAL SAFETY VIOLATION: Container {c.id[:12]} does not match "
                        "strict test labels. Refusing to remove!"
                    )
            except Exception:
                pass
            try:
                c.kill()
            except Exception:  # noqa: S110, BLE001
                pass
            try:
                c.remove(v=True, force=True)
            except Exception:  # noqa: S110, BLE001
                pass
        pytest.fail(f"Container leak detected! Leaked ai-sandbox-test containers: {cids}")
