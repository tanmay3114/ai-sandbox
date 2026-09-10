from collections.abc import Generator

import docker
import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import SandboxSettings
from app.db.session import SessionLocal
from app.models.execution_job import ExecutionJob
from app.models.sandbox import Sandbox
from app.sandbox.docker_client import list_sandbox_containers
from app.sandbox.engine import EphemeralSandboxEngine


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Isolated database session fixture with automatic post-test cleanup."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        try:
            session.execute(delete(ExecutionJob))
            session.execute(delete(Sandbox))
            session.commit()
        except Exception:
            session.rollback()
        session.close()


@pytest.fixture(scope="session")
def docker_client() -> docker.DockerClient:
    """Session Docker client."""
    client = docker.from_env()
    client.ping()
    return client


@pytest.fixture
def fast_settings() -> SandboxSettings:
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
    # Check for leaked containers with label project=ai-sandbox and sandbox_id
    leaked = list_sandbox_containers(docker_client, config=fast_settings, all_states=True)
    if leaked:
        cids = [c.id[:12] for c in leaked]
        # Force cleanup any leaked container from this project only
        for c in leaked:
            try:
                c.kill()
            except Exception:  # noqa: S110, BLE001
                pass
            try:
                c.remove(force=True)
            except Exception:  # noqa: S110, BLE001
                pass
        pytest.fail(f"Container leak detected! Leaked ai-sandbox containers: {cids}")
