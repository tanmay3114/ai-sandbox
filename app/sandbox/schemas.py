"""Pydantic schemas and enums for sandbox requests and execution results."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

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


class FileInfo(BaseModel):
    """Metadata describing a file or directory inside a sandbox workspace."""

    path: str = Field(..., description="Workspace-relative POSIX path")
    size_bytes: int = Field(..., ge=0, description="Size in bytes")
    is_directory: bool = Field(..., description="True if entry is a directory")
    modified_at: datetime = Field(..., description="Last modification timestamp (UTC)")


class FileContent(BaseModel):
    """File content and encoding retrieved from a sandbox workspace."""

    path: str = Field(..., description="Workspace-relative POSIX path")
    content: str = Field(..., description="File content (plain text or base64)")
    encoding: Literal["utf-8", "base64"] = Field(
        default="utf-8", description="Content encoding ('utf-8' or 'base64')"
    )
    size_bytes: int = Field(..., ge=0, description="Size in bytes")


class WriteFileRequest(BaseModel):
    """Payload for creating or overwriting a file in the workspace."""

    path: str = Field(..., min_length=1, max_length=255, description="Workspace-relative path")
    content: str = Field(
        ...,
        max_length=70 * 1024 * 1024,
        description="File content (plain text or base64)",
    )
    encoding: str = Field(
        default="utf-8",
        description="Content encoding format ('utf-8' or 'base64')",
    )


class CreateDirectoryRequest(BaseModel):
    """Payload for creating a directory in the workspace."""

    path: str = Field(..., min_length=1, max_length=255, description="Workspace-relative path")


class CreateDirectoryResponse(BaseModel):
    """Structured result for directory creation in a sandbox workspace."""

    path: str = Field(..., description="Workspace-relative POSIX path")
    created: bool = Field(..., description="True if directory was newly created")


class DeleteFileResponse(BaseModel):
    """Structured result for file or empty directory deletion in a sandbox workspace."""

    path: str = Field(..., description="Workspace-relative POSIX path")
    deleted: bool = Field(..., description="True if entry was deleted")


class FileListResponse(BaseModel):
    """Directory listing result with aggregated summary metadata."""

    files: list[FileInfo] = Field(default_factory=list, description="List of workspace entries")
    total_count: int = Field(..., ge=0, description="Total entries in this listing")
    total_size_bytes: int = Field(..., ge=0, description="Total size in bytes across listed files")
