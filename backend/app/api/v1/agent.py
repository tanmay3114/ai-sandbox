"""AI Agent execution router for API v1."""

import logging

from fastapi import APIRouter, Depends, status

from app.agent.agent import SandboxAgent
from app.api.dependencies import get_sandbox_agent
from app.schemas.agent import AgentRunRequest, AgentRunResponse
from app.schemas.errors import ErrorResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["Agent"])


@router.post(
    "/run",
    response_model=AgentRunResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {
            "model": AgentRunResponse,
            "description": "Agent run completed successfully",
        },
        400: {
            "model": ErrorResponse,
            "description": "Agent domain or execution error",
        },
        422: {
            "description": "Validation error in request payload",
        },
        500: {
            "model": ErrorResponse,
            "description": "Agent loop reached maximum iterations or internal error",
        },
        502: {
            "model": ErrorResponse,
            "description": "Underlying LLM provider failure",
        },
        504: {
            "model": ErrorResponse,
            "description": "Agent execution timed out",
        },
    },
    summary="Execute Model-Driven Agent Task",
    description="""
Executes an autonomous, model-driven reasoning and tool-calling loop.
The agent interprets natural-language instructions, decides which sandbox tools to call,
validates arguments, runs untrusted code in hardened containers, and returns a final explanation.
""",
)
async def run_agent(
    request: AgentRunRequest,
    agent: SandboxAgent = Depends(get_sandbox_agent),
) -> AgentRunResponse:
    """Execute autonomous agent against the sandbox platform."""
    logger.info(f"Received agent run request: prompt='{request.prompt[:80]}...'")

    result = await agent.run(prompt=request.prompt)

    executed_tools: list[str] = [
        msg.name for msg in result.messages if msg.role == "tool" and msg.name
    ]

    return AgentRunResponse(
        response=result.response,
        tools_used=result.tool_calls_count > 0,
        iterations=result.iterations,
        tool_calls_count=result.tool_calls_count,
        executed_tools=executed_tools,
    )
