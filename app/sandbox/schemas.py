"""Pydantic schemas and enums for sandbox requests and execution results."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ExecutionStatus(StrEnum):
    """Lifecycle / termination status of a code execution task."""

    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    FAILED = "failed"
    ERROR = "error"


class ExecutionRequest(BaseModel):
    """Payload for submitting untrusted code to the sandbox."""

    code: str = Field(
        ...,
        min_length=1,
        max_length=1_000_000,
        description="Python code string to execute",
    )
    timeout_seconds: float | None = Field(
        default=None,
        ge=0.5,
        le=60.0,
        description="Optional execution timeout override, bounded by platform limits",
    )

    @field_validator("code")
    @classmethod
    def validate_code_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Execution code cannot be whitespace only")
        return v


class ExecutionResult(BaseModel):
    """Structured response detailing the execution outcome and security metadata."""

    sandbox_id: str = Field(
        ...,
        description="Unique application identifier for the ephemeral sandbox",
    )
    status: ExecutionStatus = Field(
        ...,
        description="Final execution status",
    )
    exit_code: int | None = Field(
        None,
        description="Process exit code (0 for success, None on timeout/error)",
    )
    stdout: str = Field(
        default="",
        description="Captured standard output (bounded)",
    )
    stderr: str = Field(
        default="",
        description="Captured standard error (bounded)",
    )
    stdout_truncated: bool = Field(
        default=False,
        description="True if stdout was truncated due to size limits",
    )
    stderr_truncated: bool = Field(
        default=False,
        description="True if stderr was truncated due to size limits",
    )
    duration_ms: int = Field(
        ...,
        ge=0,
        description="Total execution duration in milliseconds",
    )
    error_message: str | None = Field(
        None,
        description="Internal error description if status is ERROR",
    )
    audit: Any | None = Field(
        default=None,
        description="Lightweight security policy enforcement audit record",
    )
