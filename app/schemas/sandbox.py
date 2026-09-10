"""Pydantic schemas for sandbox lifecycle requests and responses."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from app.models.sandbox import SandboxStatus


class CreateSandboxRequest(BaseModel):
    """Payload to instantiate a new sandbox session with defined TTL."""

    runtime: str = Field(
        default="python",
        description="Target runtime identifier (e.g. 'python')",
    )
    ttl_seconds: int = Field(
        default=settings.DEFAULT_SANDBOX_TTL_SECONDS,
        ge=settings.MIN_SANDBOX_TTL_SECONDS,
        le=settings.MAX_SANDBOX_TTL_SECONDS,
        description="Lifespan of sandbox session in seconds before automatic expiration",
    )

    @field_validator("runtime")
    @classmethod
    def validate_runtime(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in settings.ALLOWED_RUNTIMES:
            allowed = list(settings.ALLOWED_RUNTIMES.keys())
            raise ValueError(f"Unsupported runtime '{v}'. Allowed: {allowed}")
        return clean


class SandboxResponse(BaseModel):
    """Summary of sandbox session lifecycle status."""

    sandbox_id: uuid.UUID = Field(..., description="Unique application UUID for the sandbox")
    status: SandboxStatus = Field(..., description="Current lifecycle state")
    runtime: str = Field(..., description="Configured runtime identifier")
    created_at: datetime = Field(..., description="UTC creation timestamp")
    expires_at: datetime = Field(..., description="UTC TTL expiration timestamp")
    destroyed_at: datetime | None = Field(None, description="Destruction timestamp if destroyed")


class SandboxDetailResponse(SandboxResponse):
    """Detailed sandbox information including resource allocation and execution count."""

    resource_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Hardware and security limits assigned to this sandbox",
    )
    executions_count: int = Field(default=0, description="Total execution jobs submitted")


class JobExecutionResponse(BaseModel):
    """Structured response for an execution job within a persistent sandbox session."""

    execution_id: uuid.UUID = Field(..., description="Unique identifier for execution job")
    sandbox_id: uuid.UUID = Field(..., description="Parent sandbox session UUID")
    status: str = Field(..., description="Status ('completed', 'failed', 'timed_out', 'error')")
    exit_code: int | None = Field(None, description="Process exit code")
    stdout: str = Field(default="", description="Captured standard output")
    stderr: str = Field(default="", description="Captured standard error")
    stdout_truncated: bool = Field(default=False, description="True if stdout was truncated")
    stderr_truncated: bool = Field(default=False, description="True if stderr was truncated")
    duration_ms: int = Field(..., ge=0, description="Execution duration in milliseconds")
    submitted_at: datetime = Field(..., description="UTC submission timestamp")
    started_at: datetime | None = Field(None, description="UTC start timestamp")
    completed_at: datetime | None = Field(None, description="UTC completion timestamp")
    error_message: str | None = Field(None, description="Diagnostic error message")
