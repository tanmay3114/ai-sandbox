"""Liveness and readiness health endpoints."""

import logging

import docker
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.api.dependencies import get_docker_client_dependency
from app.schemas.health import HealthResponse, ReadyResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health & Probes"])


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Liveness Probe",
    description="Returns 200 OK if the FastAPI web application process is running and responsive.",
)
async def health() -> HealthResponse:
    """Check application process liveness."""
    return HealthResponse(status="ok", service="ai-sandbox-platform")


@router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={
        200: {"model": ReadyResponse, "description": "Dependencies are operational"},
        503: {"model": ReadyResponse, "description": "Underlying dependencies are unavailable"},
    },
    summary="Readiness Probe",
    description=(
        "Validates that required runtime dependencies (e.g. Docker Engine) are reachable."
    ),
)
async def ready(
    docker_client: docker.DockerClient = Depends(get_docker_client_dependency),
) -> JSONResponse:
    """Check readiness by verifying Docker Engine connectivity."""
    try:
        docker_client.ping()
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "ready", "docker": "connected"},
        )
    except Exception as exc:
        logger.error(f"Readiness check failed: Docker Engine is unreachable: {exc}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "docker": "unavailable"},
        )
