"""Standardized error response schemas."""

from typing import Any

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Consistent JSON response format for all API error conditions."""

    error: str = Field(..., description="Stable error type identifier")
    message: str = Field(..., description="Human-readable description of the error condition")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured sanitized details (never includes tracebacks or secrets)",
    )
