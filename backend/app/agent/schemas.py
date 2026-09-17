"""Provider-neutral AI Agent tool schemas and function-calling definitions."""

import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings


class CreateSandboxInput(BaseModel):
    """Input schema for create_sandbox tool."""

    runtime: str = Field(
        default="python",
        description="Target execution runtime (e.g. 'python')",
    )
    ttl_seconds: int = Field(
        default=settings.DEFAULT_SANDBOX_TTL_SECONDS,
        ge=settings.MIN_SANDBOX_TTL_SECONDS,
        le=settings.MAX_SANDBOX_TTL_SECONDS,
        description="Lifespan of sandbox session in seconds before expiration",
    )

    @field_validator("runtime")
    @classmethod
    def validate_runtime(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in settings.ALLOWED_RUNTIMES:
            allowed = list(settings.ALLOWED_RUNTIMES.keys())
            raise ValueError(f"Unsupported runtime '{v}'. Allowed: {allowed}")
        return clean


class ExecuteCodeInput(BaseModel):
    """Input schema for execute_code tool."""

    sandbox_id: uuid.UUID = Field(
        ...,
        description="UUID of the active sandbox session",
    )
    code: str = Field(
        ...,
        min_length=1,
        max_length=1_000_000,
        description="Python code to execute inside the ephemeral container",
    )
    timeout_seconds: float | None = Field(
        default=None,
        ge=0.5,
        le=60.0,
        description="Optional execution timeout override in seconds (capped by platform limits)",
    )

    @field_validator("code")
    @classmethod
    def validate_code_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Execution code cannot be empty or whitespace only")
        return v


class GetExecutionResultInput(BaseModel):
    """Input schema for get_execution_result tool."""

    sandbox_id: uuid.UUID = Field(
        ...,
        description="UUID of the parent sandbox session",
    )
    execution_id: uuid.UUID = Field(
        ...,
        description="UUID of the execution job to inspect",
    )


class GetSandboxInput(BaseModel):
    """Input schema for get_sandbox tool."""

    sandbox_id: uuid.UUID = Field(
        ...,
        description="UUID of the sandbox session to query",
    )


class DestroySandboxInput(BaseModel):
    """Input schema for destroy_sandbox tool."""

    sandbox_id: uuid.UUID = Field(
        ...,
        description="UUID of the sandbox session to terminate and delete",
    )


class AgentToolError(BaseModel):
    """Structured, deterministic error representation returned to an AI agent."""

    error: str = Field(..., description="Stable machine-readable error type identifier")
    message: str = Field(..., description="Human- and agent-readable description of the error")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured context attributes for programmatic recovery",
    )


class AgentToolDefinition(BaseModel):
    """Provider-neutral tool declaration conforming to standard JSON Schema specifications."""

    name: str = Field(..., description="Unique name of the tool function")
    description: str = Field(
        ...,
        description="Clear instructions explaining when and how to call this tool",
    )
    parameters: dict[str, Any] = Field(
        ...,
        description="JSON Schema specification for input parameters",
    )


# Canonical provider-neutral tool catalog
AGENT_TOOLS: dict[str, AgentToolDefinition] = {
    "create_sandbox": AgentToolDefinition(
        name="create_sandbox",
        description=(
            "Create a new isolated sandbox execution session with a configured Time-To-Live (TTL). "
            "Returns sandbox_id and expiration metadata for subsequent executions."
        ),
        parameters=CreateSandboxInput.model_json_schema(),
    ),
    "execute_code": AgentToolDefinition(
        name="execute_code",
        description=(
            "Run untrusted Python code inside a fresh, hardened, ephemeral container within an "
            "active sandbox session. Returns execution status, process exit code, stdout, stderr, "
            "and duration in milliseconds."
        ),
        parameters=ExecuteCodeInput.model_json_schema(),
    ),
    "get_execution_result": AgentToolDefinition(
        name="get_execution_result",
        description=(
            "Retrieve the execution outcome, captured logs (stdout/stderr), exit code, "
            "and timestamps for a previously executed job within a sandbox session."
        ),
        parameters=GetExecutionResultInput.model_json_schema(),
    ),
    "get_sandbox": AgentToolDefinition(
        name="get_sandbox",
        description=(
            "Check the lifecycle status, remaining TTL, resource limits, and total execution count "
            "of a sandbox session."
        ),
        parameters=GetSandboxInput.model_json_schema(),
    ),
    "destroy_sandbox": AgentToolDefinition(
        name="destroy_sandbox",
        description=(
            "Idempotently terminate and tear down a sandbox session, freeing all associated "
            "resources and preventing further code execution."
        ),
        parameters=DestroySandboxInput.model_json_schema(),
    ),
}
