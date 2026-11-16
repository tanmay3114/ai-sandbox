"""AI Agent Integration module."""

from app.agent.agent import AgentRunResult, SandboxAgent
from app.agent.orchestrator import AgentExecutionContext, AgentOrchestrator, AgentTaskResult
from app.agent.prompts import DEFAULT_SYSTEM_PROMPT
from app.agent.schemas import (
    AGENT_TOOLS,
    AgentToolDefinition,
    AgentToolError,
    CreateDirectoryInput,
    CreateSandboxInput,
    DeleteFileInput,
    DestroySandboxInput,
    ExecuteCodeInput,
    GetExecutionResultInput,
    GetSandboxInput,
    ListFilesInput,
    ReadFileInput,
    WriteFileInput,
)
from app.agent.tool_registry import AgentToolRegistry
from app.agent.tools import (
    create_directory_tool,
    create_sandbox_tool,
    delete_file_tool,
    destroy_sandbox_tool,
    execute_agent_tool,
    execute_code_tool,
    get_execution_result_tool,
    get_sandbox_tool,
    list_files_tool,
    read_file_tool,
    write_file_tool,
)

__all__ = [
    "AGENT_TOOLS",
    "AgentRunResult",
    "AgentToolDefinition",
    "AgentToolError",
    "AgentExecutionContext",
    "AgentOrchestrator",
    "AgentTaskResult",
    "AgentToolRegistry",
    "CreateDirectoryInput",
    "CreateSandboxInput",
    "DeleteFileInput",
    "ExecuteCodeInput",
    "GetExecutionResultInput",
    "GetSandboxInput",
    "DestroySandboxInput",
    "ListFilesInput",
    "ReadFileInput",
    "WriteFileInput",
    "DEFAULT_SYSTEM_PROMPT",
    "SandboxAgent",
    "create_sandbox_tool",
    "execute_code_tool",
    "get_execution_result_tool",
    "get_sandbox_tool",
    "destroy_sandbox_tool",
    "write_file_tool",
    "read_file_tool",
    "list_files_tool",
    "create_directory_tool",
    "delete_file_tool",
    "execute_agent_tool",
]
