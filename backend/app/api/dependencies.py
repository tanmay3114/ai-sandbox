"""FastAPI dependency injection providers."""

from functools import lru_cache

from fastapi import Depends
from sqlalchemy.orm import Session

from app.agent.agent import SandboxAgent
from app.agent.llm import LLMProvider, get_llm_provider
from app.core.config import SandboxSettings, settings
from app.db.session import get_db
from app.sandbox.backend import SandboxBackend
from app.sandbox.factory import create_sandbox_backend
from app.services.agent_orchestrator_service import AgentOrchestratorService
from app.services.sandbox_lifecycle_service import SandboxLifecycleService
from app.services.sandbox_service import SandboxService


@lru_cache
def get_settings() -> SandboxSettings:
    """Return cached application settings."""
    return settings


@lru_cache
def get_sandbox_backend() -> SandboxBackend:
    """Return the one process-shared backend and concurrency controller."""
    return create_sandbox_backend(config=get_settings())


def get_sandbox_service() -> SandboxService:
    """Provide SandboxService instance."""
    return SandboxService(backend=get_sandbox_backend())


def get_sandbox_lifecycle_service(
    db: Session = Depends(get_db),
    backend: SandboxBackend = Depends(get_sandbox_backend),
    config: SandboxSettings = Depends(get_settings),
) -> SandboxLifecycleService:
    """Provide SandboxLifecycleService instance backed by PostgreSQL session."""
    return SandboxLifecycleService(db=db, config=config, backend=backend)


def get_llm_provider_dependency(
    config: SandboxSettings = Depends(get_settings),
) -> LLMProvider:
    """Provide configured LLMProvider instance."""
    return get_llm_provider(config=config)


def get_sandbox_agent(
    llm: LLMProvider = Depends(get_llm_provider_dependency),
    service: SandboxLifecycleService = Depends(get_sandbox_lifecycle_service),
    config: SandboxSettings = Depends(get_settings),
) -> SandboxAgent:
    """Provide SandboxAgent instance configured with LLM provider and sandbox service."""
    return SandboxAgent(llm_provider=llm, service=service, config=config)


def get_agent_orchestrator_service(
    db: Session = Depends(get_db),
    service: SandboxLifecycleService = Depends(get_sandbox_lifecycle_service),
    llm: LLMProvider = Depends(get_llm_provider_dependency),
    config: SandboxSettings = Depends(get_settings),
) -> AgentOrchestratorService:
    """Provide AgentOrchestratorService instance backed by PostgreSQL and LLM provider."""
    return AgentOrchestratorService(
        db=db,
        service=service,
        llm_provider=llm,
        config=config,
    )
