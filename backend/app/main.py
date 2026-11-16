"""FastAPI application entry point for the Ephemeral Sandbox Platform."""

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.dependencies import get_sandbox_backend
from app.api.health import router as health_router
from app.api.v1.router import api_v1_router
from app.core.config import settings
from app.core.exceptions import (
    AgentCancelledError,
    AgentMaxIterationsError,
    AgentSecurityError,
    AgentTaskNotFoundError,
    AgentTimeoutError,
    ConcurrencyLimitError,
    DockerEngineError,
    ExecutionNotFoundError,
    LLMProviderError,
    QemuEngineError,
    SandboxFileNotFoundError,
    SandboxNotFoundError,
    SandboxPlatformError,
    SecurityPolicyViolationError,
    WorkspaceCleanupError,
)
from app.db.session import SessionLocal
from app.models.sandbox import InvalidStateTransitionError
from app.services.sandbox_lifecycle_service import SandboxLifecycleService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("ai_sandbox")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Reconcile persisted lifecycle state on startup and handle graceful shutdown."""
    from app.services.agent_orchestrator_service import AgentOrchestratorService

    AgentOrchestratorService._shutting_down = False
    db = SessionLocal()
    try:
        lifecycle_svc = SandboxLifecycleService(
            db=db,
            backend=get_sandbox_backend(),
        )
        lifecycle_svc.reconcile_stale_sandboxes()
        AgentOrchestratorService(
            db=db,
            service=lifecycle_svc,
            llm_provider=None,
        ).reconcile_interrupted_tasks()
    except Exception:
        # Startup recovery is best-effort; readiness remains responsible for
        # reporting unavailable dependencies without exposing their details.
        logger.exception("Startup lifecycle recovery could not complete")
    finally:
        db.close()

    yield

    # Graceful shutdown: stop new tasks, signal active orchestrator loops, await completion
    shutdown_db = SessionLocal()
    try:
        from app.services.agent_orchestrator_service import AgentOrchestratorService

        await AgentOrchestratorService.graceful_shutdown(db=shutdown_db, timeout_seconds=3.0)
    except Exception:
        logger.exception("Agent orchestrator graceful shutdown encountered error")
    finally:
        shutdown_db.close()


app = FastAPI(
    title="Cloud-Based Ephemeral Sandbox Platform for AI Agents",
    description=(
        "Secure, isolated, ephemeral execution environment platform for untrusted AI agent code."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ==========================================
# CORS Middleware
# ==========================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
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
    logger.warning(f"Concurrency limit reached on {request.url.path}: {exc}")
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
    """Handle Docker daemon communication or execution errors without leaking raw internals."""
    logger.error(f"DockerEngineError on request {request.url.path}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "error": "DockerEngineError",
            "message": "Sandbox container infrastructure is temporarily unavailable.",
            "details": {},
        },
    )


@app.exception_handler(QemuEngineError)
async def qemu_engine_handler(
    request: Request,
    exc: QemuEngineError,
) -> JSONResponse:
    """Handle QEMU virtualization infrastructure failures without leaking internals."""
    logger.error(f"QemuEngineError on request {request.url.path}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "error": "QemuEngineError",
            "message": "Sandbox virtualization infrastructure is temporarily unavailable.",
            "details": {},
        },
    )


@app.exception_handler(WorkspaceCleanupError)
async def workspace_cleanup_handler(
    request: Request,
    exc: WorkspaceCleanupError,
) -> JSONResponse:
    """Handle workspace cleanup failures as retryable 503 errors without leaking host paths."""
    logger.error(f"WorkspaceCleanupError on request {request.url.path}: {type(exc).__name__}")
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "error": "WorkspaceCleanupError",
            "message": "Sandbox workspace cleanup failed and remains retryable.",
            "details": {},
        },
    )


@app.exception_handler(SandboxNotFoundError)
async def sandbox_not_found_handler(
    request: Request,
    exc: SandboxNotFoundError,
) -> JSONResponse:
    """Handle non-existent sandbox session lookup."""
    logger.info(f"SandboxNotFoundError on {request.url.path}: {exc.message}")
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
    """Handle non-existent execution job lookup."""
    logger.info(f"ExecutionNotFoundError on {request.url.path}: {exc.message}")
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "error": "ExecutionNotFoundError",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(SandboxFileNotFoundError)
async def sandbox_file_not_found_handler(
    request: Request,
    exc: SandboxFileNotFoundError,
) -> JSONResponse:
    """Handle 404 for missing workspace files or directories without leaking host paths."""
    logger.info(f"SandboxFileNotFoundError: {exc.message}")
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "error": "SandboxFileNotFoundError",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(InvalidStateTransitionError)
async def invalid_transition_handler(
    request: Request,
    exc: InvalidStateTransitionError,
) -> JSONResponse:
    """Handle invalid lifecycle state transitions."""
    logger.warning(f"Invalid state transition on {request.url.path}: {exc.message}")
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
    """Handle overall agent loop timeout."""
    logger.warning(f"Agent timeout on {request.url.path}: {exc.message}")
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
    """Handle agent iteration ceiling exhaustion."""
    logger.warning(f"Agent max iterations reached on {request.url.path}: {exc.message}")
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
    """Handle upstream LLM communication or parsing failures."""
    logger.error(f"LLM provider error on {request.url.path}: {exc.message}")
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={
            "error": "LLMProviderError",
            "message": "AI model provider communication failed.",
            "details": exc.details,
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


@app.exception_handler(AgentSecurityError)
async def agent_security_handler(
    request: Request,
    exc: AgentSecurityError,
) -> JSONResponse:
    """Handle cross-sandbox or unauthorized agent tool execution attempt."""
    logger.warning("AgentSecurityError on %s: %s", request.url.path, exc.message)
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={
            "error": "AgentSecurityError",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(AgentTaskNotFoundError)
async def agent_task_not_found_handler(
    request: Request,
    exc: AgentTaskNotFoundError,
) -> JSONResponse:
    """Handle non-existent agent task lookup."""
    logger.info("AgentTaskNotFoundError on %s: %s", request.url.path, exc.message)
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "error": "AgentTaskNotFoundError",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(AgentCancelledError)
async def agent_cancelled_handler(
    request: Request,
    exc: AgentCancelledError,
) -> JSONResponse:
    """Handle cancelled agent task execution."""
    logger.info("AgentCancelledError on %s: %s", request.url.path, exc.message)
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": "AgentCancelledError",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(SandboxPlatformError)
async def generic_platform_handler(
    request: Request,
    exc: SandboxPlatformError,
) -> JSONResponse:
    """Handle unclassified platform exceptions safely."""
    logger.error(f"Platform error on {request.url.path}: {exc.message}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": type(exc).__name__,
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Normalize input validation errors without internal leaking."""
    logger.info(f"Validation failure on {request.url.path}: {exc}")
    errors: list[dict[str, Any]] = []
    for err in exc.errors():
        loc = " -> ".join(str(item) for item in err.get("loc", []))
        errors.append(
            {
                "field": loc,
                "message": err.get("msg", "Invalid value"),
                "issue": err.get("msg", "Invalid value"),
                "type": err.get("type", "value_error"),
            }
        )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "ValidationError",
            "message": "Request payload failed schema validation",
            "details": {
                "errors": errors,
                "validation_errors": errors,
            },
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Fallback handler to prevent raw stack trace leakage to API clients."""
    logger.exception(f"Unhandled exception on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "InternalServerError",
            "message": "An unexpected error occurred processing your request.",
            "details": {},
        },
    )


# ==========================================
# Router Registrations
# ==========================================
app.include_router(health_router)
app.include_router(api_v1_router)
