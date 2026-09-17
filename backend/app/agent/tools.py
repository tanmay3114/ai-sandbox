"""Thin adapter exposing sandbox capabilities as deterministic tools for AI agents."""

import logging
from typing import Any

from pydantic import ValidationError

from app.agent.schemas import (
    AgentToolError,
    CreateSandboxInput,
    DestroySandboxInput,
    ExecuteCodeInput,
    GetExecutionResultInput,
    GetSandboxInput,
)
from app.core.exceptions import SandboxPlatformError
from app.schemas.sandbox import (
    JobExecutionResponse,
    SandboxDetailResponse,
    SandboxResponse,
)
from app.services.sandbox_lifecycle_service import SandboxLifecycleService

logger = logging.getLogger(__name__)


def create_sandbox_tool(
    service: SandboxLifecycleService,
    input_data: CreateSandboxInput | dict[str, Any],
) -> SandboxResponse:
    """Tool function: instantiate a new persistent sandbox session with validated TTL."""
    payload = (
        input_data
        if isinstance(input_data, CreateSandboxInput)
        else CreateSandboxInput.model_validate(input_data)
    )
    sandbox = service.create_sandbox(
        runtime=payload.runtime,
        ttl_seconds=payload.ttl_seconds,
    )
    return SandboxResponse(
        sandbox_id=sandbox.id,
        status=sandbox.status,
        runtime=sandbox.runtime,
        created_at=sandbox.created_at,
        expires_at=sandbox.expires_at,
        destroyed_at=sandbox.destroyed_at,
    )


async def execute_code_tool(
    service: SandboxLifecycleService,
    input_data: ExecuteCodeInput | dict[str, Any],
) -> JobExecutionResponse:
    """Tool function: execute code in an active sandbox session and return outcome."""
    payload = (
        input_data
        if isinstance(input_data, ExecuteCodeInput)
        else ExecuteCodeInput.model_validate(input_data)
    )
    return await service.execute_code(
        sandbox_id=payload.sandbox_id,
        code=payload.code,
        timeout_seconds=payload.timeout_seconds,
    )


def get_execution_result_tool(
    service: SandboxLifecycleService,
    input_data: GetExecutionResultInput | dict[str, Any],
) -> JobExecutionResponse:
    """Tool function: look up historical execution result by ID."""
    payload = (
        input_data
        if isinstance(input_data, GetExecutionResultInput)
        else GetExecutionResultInput.model_validate(input_data)
    )
    return service.get_execution(
        sandbox_id=payload.sandbox_id,
        execution_id=payload.execution_id,
    )


def get_sandbox_tool(
    service: SandboxLifecycleService,
    input_data: GetSandboxInput | dict[str, Any],
) -> SandboxDetailResponse:
    """Tool function: retrieve sandbox metadata, status, and execution statistics."""
    payload = (
        input_data
        if isinstance(input_data, GetSandboxInput)
        else GetSandboxInput.model_validate(input_data)
    )
    sandbox = service.get_sandbox(payload.sandbox_id)
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


def destroy_sandbox_tool(
    service: SandboxLifecycleService,
    input_data: DestroySandboxInput | dict[str, Any],
) -> SandboxResponse:
    """Tool function: idempotently terminate and destroy a sandbox session."""
    payload = (
        input_data
        if isinstance(input_data, DestroySandboxInput)
        else DestroySandboxInput.model_validate(input_data)
    )
    sandbox = service.delete_sandbox(payload.sandbox_id)
    return SandboxResponse(
        sandbox_id=sandbox.id,
        status=sandbox.status,
        runtime=sandbox.runtime,
        created_at=sandbox.created_at,
        expires_at=sandbox.expires_at,
        destroyed_at=sandbox.destroyed_at,
    )


async def execute_agent_tool(
    tool_name: str,
    arguments: dict[str, Any],
    service: SandboxLifecycleService,
) -> SandboxResponse | SandboxDetailResponse | JobExecutionResponse | AgentToolError:
    """Generic dispatcher executing agent tool calls with deterministic error wrapping."""
    try:
        match tool_name:
            case "create_sandbox":
                return create_sandbox_tool(service, arguments)
            case "execute_code":
                return await execute_code_tool(service, arguments)
            case "get_execution_result":
                return get_execution_result_tool(service, arguments)
            case "get_sandbox":
                return get_sandbox_tool(service, arguments)
            case "destroy_sandbox":
                return destroy_sandbox_tool(service, arguments)
            case _:
                return AgentToolError(
                    error="InvalidToolName",
                    message=f"Tool '{tool_name}' is not recognized by this sandbox platform.",
                    details={
                        "allowed_tools": [
                            "create_sandbox",
                            "execute_code",
                            "get_execution_result",
                            "get_sandbox",
                            "destroy_sandbox",
                        ]
                    },
                )
    except ValidationError as err:
        return AgentToolError(
            error="ValidationError",
            message="Input arguments failed schema validation.",
            details={"errors": err.errors()},
        )
    except SandboxPlatformError as err:
        return AgentToolError(
            error=err.__class__.__name__,
            message=err.message,
            details=err.details,
        )
    except Exception as exc:
        logger.exception(f"Unexpected error executing agent tool '{tool_name}': {exc}")
        return AgentToolError(
            error="InternalToolError",
            message="An unexpected error occurred while executing the tool.",
            details={},
        )
