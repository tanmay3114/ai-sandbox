"""Health and readiness response schemas."""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Liveness probe response."""

    status: str = Field(default="ok", description="Process liveness status")
    service: str = Field(default="ai-sandbox-platform", description="Platform service name")


class ReadyResponse(BaseModel):
    """Readiness probe response validating underlying infrastructure dependencies."""

    status: str = Field(..., description="Readiness status ('ready' or 'not_ready')")
    docker: str = Field(..., description="Docker connectivity ('connected' or 'unavailable')")
