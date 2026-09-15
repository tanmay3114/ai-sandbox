"""FastAPI application entrypoint for the Ephemeral Sandbox Platform."""

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.health import router as health_router
from app.api.v1.router import api_v1_router
from app.core.exceptions import (
    AgentMaxIterationsError,
    AgentTimeoutError,
    ConcurrencyLimitError,
    DockerEngineError,
    ExecutionNotFoundError,
    LLMProviderError,
    SandboxNotFoundError,
    SandboxPlatformError,
    SecurityPolicyViolationError,
)
from app.db.session import SessionLocal
from app.models.sandbox import InvalidStateTransitionError
from app.services.sandbox_lifecycle_service import SandboxLifecycleService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("ai_sandbox")

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Reconcile persisted lifecycle state left by a prior process on startup."""
    db = SessionLocal()
    try:
        SandboxLifecycleService(db=db).reconcile_stale_sandboxes()
    except Exception:
        # Startup recovery is best-effort; readiness remains responsible for
        # reporting unavailable dependencies without exposing their details.
        logger.exception("Sandbox lifecycle recovery could not complete")
    finally:
        db.close()
    yield


app = FastAPI(
    title="Cloud-Based Ephemeral Sandbox Platform for AI Agents",
    description="""
Secure, isolated, ephemeral execution environment platform for untrusted AI agent code.

### Security Guarantees:
* **Privilege Confinement**: Non-root UID (10001), drop ALL capabilities, no-new-privileges.
* **Filesystem Confinement**: Read-only root filesystem, restricted non-exec /tmp tmpfs, 0 mounts.
* **Network Isolation**: Disabled network stack (network_mode=none), zero network connectivity.
* **Resource Bounds**: Strict memory (256MB), CPU quota (0.5 core), and PID limit (32).
* **Output Bounds**: Hard stream limits preventing host memory exhaustion.
* **Ephemeral Lifecycle**: One request = one container; timeout kill and guaranteed cleanup.
""",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ==========================================
# Centralized Exception Handlers
# ==========================================

@app.exception_handler(ConcurrencyLimitError)
async def concurrency_limit_handler(
    request: Request,
    exc: ConcurrencyLimitError,
) -> JSONResponse:
    """Handle platform execution capacity exhaustion."""
    logger.warning(f"Concurrency limit exceeded: {exc.message}")
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "error": "ConcurrencyLimitError",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(DockerEngineError)
async def docker_engine_handler(
    request: Request,
    exc: DockerEngineError,
) -> JSONResponse:
    """Handle Docker daemon communication failures without leaking internals."""
    logger.error(f"DockerEngineError on request {request.url.path}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "error": "DockerEngineError",
            "message": "Sandbox container infrastructure is temporarily unavailable.",
            "details": {},
        },
    )


@app.exception_handler(SandboxNotFoundError)
async def sandbox_not_found_handler(
    request: Request,
    exc: SandboxNotFoundError,
) -> JSONResponse:
    """Handle 404 for missing sandbox resources."""
    logger.info(f"SandboxNotFoundError: {exc.message}")
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "error": "SandboxNotFoundError",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(ExecutionNotFoundError)
async def execution_not_found_handler(
    request: Request,
    exc: ExecutionNotFoundError,
) -> JSONResponse:
    """Handle 404 for missing execution resources."""
    logger.info(f"ExecutionNotFoundError: {exc.message}")
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "error": "ExecutionNotFoundError",
            "message": exc.message,
            "details": exc.details,
        },
    )



@app.exception_handler(InvalidStateTransitionError)
async def invalid_transition_handler(
    request: Request,
    exc: InvalidStateTransitionError,
) -> JSONResponse:
    """Handle 409 conflict for illegal state transitions."""
    logger.warning(f"InvalidStateTransitionError: {exc.message}")
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": "InvalidStateTransitionError",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(AgentTimeoutError)
async def agent_timeout_handler(
    request: Request,
    exc: AgentTimeoutError,
) -> JSONResponse:
    """Handle agent deadline expiration."""
    logger.warning(f"Agent execution timed out: {exc.message}")
    return JSONResponse(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        content={
            "error": "AgentTimeoutError",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(AgentMaxIterationsError)
async def agent_max_iterations_handler(
    request: Request,
    exc: AgentMaxIterationsError,
) -> JSONResponse:
    """Handle agent loop iteration limit exhaustion."""
    logger.warning(f"Agent max iterations reached: {exc.message}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "AgentMaxIterationsError",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(LLMProviderError)
async def llm_provider_handler(
    request: Request,
    exc: LLMProviderError,
) -> JSONResponse:
    """Handle LLM provider communication failure without leaking secrets."""
    logger.error(f"LLMProviderError on {request.url.path}: {exc.message}")
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={
            "error": "LLMProviderError",
            "message": "AI model provider communication failed.",
            "details": {},
        },
    )


@app.exception_handler(SecurityPolicyViolationError)
async def security_policy_violation_handler(
    request: Request,
    exc: SecurityPolicyViolationError,
) -> JSONResponse:
    """Handle security policy violations with explicit HTTP 400."""
    logger.warning(f"Security policy violation on {request.url.path}: {exc.message}")
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "SecurityPolicyViolationError",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(SandboxPlatformError)
async def sandbox_platform_handler(
    request: Request,
    exc: SandboxPlatformError,
) -> JSONResponse:
    """Handle domain validation and configuration errors."""
    logger.info(f"SandboxPlatformError: {exc.message}")
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": exc.__class__.__name__,
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Format request validation errors consistently without internal paths."""
    sanitized_errors: list[dict[str, Any]] = []
    for err in exc.errors():
        sanitized_errors.append(
            {
                "field": ".".join(str(loc) for loc in err.get("loc", [])),
                "message": err.get("msg", "Invalid value"),
                "type": err.get("type", "value_error"),
            }
        )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "error": "ValidationError",
            "message": "Request payload failed validation schema.",
            "details": {"errors": sanitized_errors},
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Sanitize all uncaught exceptions to prevent leakage of secrets or tracebacks."""
    logger.exception(f"Unhandled internal server error on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "InternalServerError",
            "message": "An unexpected server error occurred.",
            "details": {},
        },
    )


# ==========================================
# Routers
# ==========================================
app.include_router(health_router)
app.include_router(api_v1_router)
