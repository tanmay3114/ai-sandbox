"""MCP tool adapter registering sandbox capabilities with the Model Context Protocol."""

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field, ValidationError

from app.agent.schemas import (
    AGENT_TOOLS,
    AgentToolError,
    CreateSandboxInput,
    DestroySandboxInput,
    ExecuteCodeInput,
    GetExecutionResultInput,
    GetSandboxInput,
)
from app.agent.tools import (
    create_sandbox_tool,
    destroy_sandbox_tool,
    execute_code_tool,
    get_execution_result_tool,
    get_sandbox_tool,
)
from app.core.config import settings
from app.core.exceptions import SandboxPlatformError
from app.services.sandbox_lifecycle_service import SandboxLifecycleService

logger = logging.getLogger(__name__)


def _format_mcp_error(exc: Exception) -> dict[str, Any]:
    """Format validation or domain exceptions into structured agent tool errors."""
    if isinstance(exc, ValidationError):
        clean_errors = []
        for item in exc.errors():
            clean_item = dict(item)
            if "ctx" in clean_item and isinstance(clean_item["ctx"], dict):
                clean_item["ctx"] = {k: str(v) for k, v in clean_item["ctx"].items()}
            clean_errors.append(clean_item)
        return AgentToolError(
            error="ValidationError",
            message="Input arguments failed schema validation.",
            details={"errors": clean_errors},
        ).model_dump(mode="json")
    if isinstance(exc, SandboxPlatformError):
        return AgentToolError(
            error=exc.__class__.__name__,
            message=exc.message,
            details=exc.details,
        ).model_dump(mode="json")
    logger.exception(f"Unexpected error in MCP tool: {exc}")
    return AgentToolError(
        error="InternalToolError",
        message="An unexpected error occurred while executing the tool.",
        details={},
    ).model_dump(mode="json")


def register_mcp_tools(
    server: MCPServer,
    service_factory: Callable[[], AbstractContextManager[SandboxLifecycleService]],
) -> None:
    """Register sandbox management and execution tools on the MCP server instance."""

    @server.tool(
        name="create_sandbox",
        description=AGENT_TOOLS["create_sandbox"].description,
    )
    def create_sandbox(
        runtime: Annotated[
            str,
            Field(
                default="python",
                description="Target execution runtime (e.g. 'python')",
            ),
        ] = "python",
        ttl_seconds: Annotated[
            int,
            Field(
                default=settings.DEFAULT_SANDBOX_TTL_SECONDS,
                ge=settings.MIN_SANDBOX_TTL_SECONDS,
                le=settings.MAX_SANDBOX_TTL_SECONDS,
                description="Lifespan of sandbox session in seconds before expiration",
            ),
        ] = settings.DEFAULT_SANDBOX_TTL_SECONDS,
    ) -> dict[str, Any]:
        """Create a new isolated sandbox execution session with a configured TTL."""
        try:
            payload = CreateSandboxInput(runtime=runtime, ttl_seconds=ttl_seconds)
            with service_factory() as service:
                result = create_sandbox_tool(service, payload)
                return result.model_dump(mode="json")
        except Exception as exc:
            return _format_mcp_error(exc)

    @server.tool(
        name="execute_code",
        description=AGENT_TOOLS["execute_code"].description,
    )
    async def execute_code(
        sandbox_id: Annotated[
            str,
            Field(
                description="UUID of the active sandbox session",
            ),
        ],
        code: Annotated[
            str,
            Field(
                min_length=1,
                max_length=1_000_000,
                description="Python code to execute inside the ephemeral container",
            ),
        ],
        timeout_seconds: Annotated[
            float | None,
            Field(
                default=None,
                ge=0.5,
                le=60.0,
                description=(
                    "Optional execution timeout override in seconds (capped by platform limits)"
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Run untrusted Python code inside a fresh, hardened ephemeral container."""
        try:
            payload = ExecuteCodeInput(
                sandbox_id=sandbox_id,
                code=code,
                timeout_seconds=timeout_seconds,
            )
            with service_factory() as service:
                result = await execute_code_tool(service, payload)
                return result.model_dump(mode="json")
        except Exception as exc:
            return _format_mcp_error(exc)

    @server.tool(
        name="get_execution_result",
        description=AGENT_TOOLS["get_execution_result"].description,
    )
    def get_execution_result(
        sandbox_id: Annotated[
            str,
            Field(
                description="UUID of the parent sandbox session",
            ),
        ],
        execution_id: Annotated[
            str,
            Field(
                description="UUID of the execution job to inspect",
            ),
        ],
    ) -> dict[str, Any]:
        """Retrieve historical execution outcome, logs, and timestamps by ID."""
        try:
            payload = GetExecutionResultInput(
                sandbox_id=sandbox_id,
                execution_id=execution_id,
            )
            with service_factory() as service:
                result = get_execution_result_tool(service, payload)
                return result.model_dump(mode="json")
        except Exception as exc:
            return _format_mcp_error(exc)

    @server.tool(
        name="get_sandbox",
        description=AGENT_TOOLS["get_sandbox"].description,
    )
    def get_sandbox(
        sandbox_id: Annotated[
            str,
            Field(
                description="UUID of the sandbox session to query",
            ),
        ],
    ) -> dict[str, Any]:
        """Check the lifecycle status, remaining TTL, and execution count of a sandbox."""
        try:
            payload = GetSandboxInput(sandbox_id=sandbox_id)
            with service_factory() as service:
                result = get_sandbox_tool(service, payload)
                return result.model_dump(mode="json")
        except Exception as exc:
            return _format_mcp_error(exc)

    @server.tool(
        name="destroy_sandbox",
        description=AGENT_TOOLS["destroy_sandbox"].description,
    )
    def destroy_sandbox(
        sandbox_id: Annotated[
            str,
            Field(
                description="UUID of the sandbox session to terminate and delete",
            ),
        ],
    ) -> dict[str, Any]:
        """Idempotently terminate and tear down a sandbox session."""
        try:
            payload = DestroySandboxInput(sandbox_id=sandbox_id)
            with service_factory() as service:
                result = destroy_sandbox_tool(service, payload)
                return result.model_dump(mode="json")
        except Exception as exc:
            return _format_mcp_error(exc)
