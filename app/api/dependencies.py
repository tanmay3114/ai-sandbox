"""FastAPI dependency injection providers."""

from functools import lru_cache

import docker
from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import SandboxSettings, settings
from app.db.session import get_db
from app.sandbox.docker_client import get_docker_client
from app.sandbox.engine import EphemeralSandboxEngine
from app.services.sandbox_lifecycle_service import SandboxLifecycleService
from app.services.sandbox_service import SandboxService


@lru_cache
def get_settings() -> SandboxSettings:
    """Return cached application settings."""
    return settings


@lru_cache
def get_docker_client_dependency() -> docker.DockerClient:
    """Return cached Docker client."""
    return get_docker_client()


@lru_cache
def get_sandbox_engine() -> EphemeralSandboxEngine:
    """Return shared EphemeralSandboxEngine instance with concurrency semaphore."""
    return EphemeralSandboxEngine(config=get_settings(), client=get_docker_client_dependency())


def get_sandbox_service() -> SandboxService:
    """Provide SandboxService instance."""
    return SandboxService(engine=get_sandbox_engine(), config=get_settings())


def get_sandbox_lifecycle_service(
    db: Session = Depends(get_db),
    engine: EphemeralSandboxEngine = Depends(get_sandbox_engine),
    config: SandboxSettings = Depends(get_settings),
) -> SandboxLifecycleService:
    """Provide SandboxLifecycleService instance backed by PostgreSQL session."""
    return SandboxLifecycleService(db=db, config=config, engine=engine)
