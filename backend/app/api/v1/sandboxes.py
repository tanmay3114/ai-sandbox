"""Sandbox lifecycle and execution router for API v1."""

import logging
import uuid

from fastapi import APIRouter, Depends, status

from app.api.dependencies import (
    get_sandbox_lifecycle_service,
    get_sandbox_service,
)
from app.sandbox.schemas import ExecutionRequest, ExecutionResult
from app.schemas.errors import ErrorResponse
from app.schemas.sandbox import (
    CreateSandboxRequest,
    JobExecutionResponse,
    SandboxDetailResponse,
    SandboxResponse,
)
from app.services.sandbox_lifecycle_service import SandboxLifecycleService
from app.services.sandbox_service import SandboxService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sandboxes", tags=["Sandboxes"])


@router.post(
    "",
    response_model=SandboxResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"model": SandboxResponse, "description": "Sandbox session created"},
        400: {"model": ErrorResponse, "description": "Invalid runtime or TTL configuration"},
        422: {"description": "Validation error in request payload"},
    },
    summary="Create Persistent Sandbox Session",
    description="""
Instantiates a new isolated sandbox environment record with a validated TTL (Time-to-Live).
Returns the assigned sandbox ID and expiration metadata.
""",
)
async def create_sandbox(
    request: CreateSandboxRequest,
    service: SandboxLifecycleService = Depends(get_sandbox_lifecycle_service),
) -> SandboxResponse:
    """Create a new sandbox session with defined TTL."""
    sandbox = service.create_sandbox(
        runtime=request.runtime,
        ttl_seconds=request.ttl_seconds,
    )
    return SandboxResponse(
        sandbox_id=sandbox.id,
        status=sandbox.status,
        runtime=sandbox.runtime,
        created_at=sandbox.created_at,
        expires_at=sandbox.expires_at,
        destroyed_at=sandbox.destroyed_at,
    )


@router.get(
    "",
    response_model=list[SandboxDetailResponse],
    status_code=status.HTTP_200_OK,
    summary="List Sandbox Sessions",
    description="Retrieve all persistent sandbox sessions with status and execution counts.",
)
async def list_sandboxes(
    service: SandboxLifecycleService = Depends(get_sandbox_lifecycle_service),
) -> list[SandboxDetailResponse]:
    """List all persisted sandbox sessions."""
    sandboxes = service.list_sandboxes()
    return [
        SandboxDetailResponse(
            sandbox_id=s.id,
            status=s.status,
            runtime=s.runtime,
            created_at=s.created_at,
            expires_at=s.expires_at,
            destroyed_at=s.destroyed_at,
            resource_config=s.resource_config,
            executions_count=len(s.executions),
        )
        for s in sandboxes
    ]


@router.get(
    "/{sandbox_id}",
    response_model=SandboxDetailResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"model": SandboxDetailResponse, "description": "Sandbox lifecycle information"},
        404: {"model": ErrorResponse, "description": "Sandbox ID not found"},
    },
    summary="Get Sandbox Status",
    description="Retrieve persisted lifecycle state, resource limits, and execution statistics.",
)
async def get_sandbox(
    sandbox_id: uuid.UUID,
    service: SandboxLifecycleService = Depends(get_sandbox_lifecycle_service),
) -> SandboxDetailResponse:
    """Fetch status and metadata for a given sandbox."""
    sandbox = service.get_sandbox(sandbox_id)
    return SandboxDetailResponse(
        sandbox_id=sandbox.id,
        status=sandbox.status,
        runtime=sandbox.runtime,
        created_at=sandbox.created_at,
        expires_at=sandbox.expires_at,
        destroyed_at=sandbox.destroyed_at,
        resource_config=sandbox.resource_config,
        executions_count=len(sandbox.executions),
    )


@router.delete(
    "/{sandbox_id}",
    response_model=SandboxResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"model": SandboxResponse, "description": "Sandbox terminated and destroyed"},
        404: {"model": ErrorResponse, "description": "Sandbox ID not found"},
    },
    summary="Destroy Sandbox Session",
    description="Idempotently tears down and destroys the sandbox session and its containers.",
)
async def delete_sandbox(
    sandbox_id: uuid.UUID,
    service: SandboxLifecycleService = Depends(get_sandbox_lifecycle_service),
) -> SandboxResponse:
    """Terminate and destroy a sandbox session."""
    sandbox = service.delete_sandbox(sandbox_id)
    return SandboxResponse(
        sandbox_id=sandbox.id,
        status=sandbox.status,
        runtime=sandbox.runtime,
        created_at=sandbox.created_at,
        expires_at=sandbox.expires_at,
        destroyed_at=sandbox.destroyed_at,
    )


@router.post(
    "/{sandbox_id}/execute",
    response_model=JobExecutionResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"model": JobExecutionResponse, "description": "Execution completed"},
        400: {"model": ErrorResponse, "description": "Sandbox expired or destroyed"},
        404: {"model": ErrorResponse, "description": "Sandbox not found"},
        409: {"model": ErrorResponse, "description": "Sandbox is currently executing another task"},
        429: {"model": ErrorResponse, "description": "Global concurrency limit reached"},
        503: {"model": ErrorResponse, "description": "Docker execution backend unavailable"},
    },
    summary="Execute Code within Persistent Sandbox",
    description="Runs code in the designated sandbox session, recording full job history.",
)
async def execute_in_sandbox(
    sandbox_id: uuid.UUID,
    request: ExecutionRequest,
    service: SandboxLifecycleService = Depends(get_sandbox_lifecycle_service),
) -> JobExecutionResponse:
    """Run code in an existing sandbox session."""
    return await service.execute_code(
        sandbox_id=sandbox_id,
        code=request.code,
        timeout_seconds=request.timeout_seconds,
    )


@router.get(
    "/{sandbox_id}/executions/{execution_id}",
    response_model=JobExecutionResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"model": JobExecutionResponse, "description": "Execution details retrieved"},
        404: {"model": ErrorResponse, "description": "Sandbox or Execution ID not found"},
    },
    summary="Get Execution Job Result",
    description=(
        "Retrieve status, logs, exit code, and timestamps for an execution job within a sandbox."
    ),
)
async def get_execution_result(
    sandbox_id: uuid.UUID,
    execution_id: uuid.UUID,
    service: SandboxLifecycleService = Depends(get_sandbox_lifecycle_service),
) -> JobExecutionResponse:
    """Fetch results and metadata for a specific execution job."""
    return service.get_execution(sandbox_id=sandbox_id, execution_id=execution_id)


@router.get(
    "/{sandbox_id}/executions",
    response_model=list[JobExecutionResponse],
    status_code=status.HTTP_200_OK,
    responses={
        200: {"model": list[JobExecutionResponse], "description": "Execution history retrieved"},
        404: {"model": ErrorResponse, "description": "Sandbox ID not found"},
    },
    summary="List Sandbox Executions",
    description="Retrieve execution job history for a specific sandbox session.",
)
async def list_sandbox_executions(
    sandbox_id: uuid.UUID,
    service: SandboxLifecycleService = Depends(get_sandbox_lifecycle_service),
) -> list[JobExecutionResponse]:
    """List all execution records for a given sandbox session."""
    return service.list_executions(sandbox_id)



# ===================================================================
# Backward Compatibility Endpoint: POST /api/v1/sandboxes/execute
# ===================================================================

@router.post(
    "/execute",
    response_model=ExecutionResult,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"model": ExecutionResult, "description": "Execution finished"},
        400: {"model": ErrorResponse, "description": "Execution error"},
        422: {"description": "Validation error"},
        429: {"model": ErrorResponse, "description": "Concurrency limit reached"},
        503: {"model": ErrorResponse, "description": "Docker backend unavailable"},
    },
    summary="Execute Untrusted Code (Ephemeral One-Shot)",
    description="Ephemeral execution: creates a sandbox, runs code, records, and destroys.",
)
async def execute_ephemeral_code(
    request: ExecutionRequest,
    service: SandboxService = Depends(get_sandbox_service),
) -> ExecutionResult:
    """Single-shot ephemeral execution compatible with Phase 2 callers."""
    return await service.execute_code(request)
