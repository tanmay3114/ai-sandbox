"""Service layer for orchestrating sandbox execution and managing async offloading."""

import logging

from starlette.concurrency import run_in_threadpool

from app.core.config import SandboxSettings, settings
from app.sandbox.engine import EphemeralSandboxEngine
from app.sandbox.schemas import ExecutionRequest, ExecutionResult

logger = logging.getLogger(__name__)


class SandboxService:
    """Service layer decoupling API routers from Docker sandbox implementation.

    Handles offloading blocking Docker SDK operations to a worker threadpool
    to ensure FastAPI's async event loop remains non-blocking.
    """

    def __init__(
        self,
        engine: EphemeralSandboxEngine | None = None,
        config: SandboxSettings = settings,
    ) -> None:
        self.config = config
        self.engine = engine or EphemeralSandboxEngine(config=self.config)

    async def execute_code(self, request: ExecutionRequest) -> ExecutionResult:
        """Execute untrusted code asynchronously via threadpool worker."""
        logger.info("Offloading sandbox execution to worker threadpool...")
        return await run_in_threadpool(self.engine.execute, request)
