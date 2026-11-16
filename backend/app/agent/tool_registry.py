"""Controlled Agent Tool Registry with strict sandbox authorization boundaries."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

from pydantic import ValidationError

from app.agent.schemas import (
    AgentToolDefinition,
    AgentToolError,
    CreateDirectoryInput,
    DeleteFileInput,
    ExecuteCodeInput,
    GetExecutionResultInput,
    GetSandboxInput,
    ListFilesInput,
    ReadFileInput,
    WriteFileInput,
)
from app.core.config import settings
from app.core.exceptions import AgentSecurityError, SandboxPlatformError
from app.services.sandbox_lifecycle_service import SandboxLifecycleService

logger = logging.getLogger(__name__)


class AgentToolRegistry:
    """Security-enforcing tool registry that binds all invocations to an authorized sandbox."""

    def __init__(
        self,
        service: SandboxLifecycleService,
        authorized_sandbox_id: uuid.UUID,
        max_output_bytes: int | None = None,
    ) -> None:
        self.service = service
        self.authorized_sandbox_id = authorized_sandbox_id
        self.max_output_bytes = max_output_bytes or settings.AGENT_MAX_TOOL_RESULT_BYTES
        self._tools: dict[str, AgentToolDefinition] = {}
        self._handlers: dict[
            str,
            Callable[[dict[str, Any]], Coroutine[Any, Any, Any] | Any],
        ] = {}

        self._register_default_tools()

    @property
    def tool_names(self) -> list[str]:
        """Return list of all registered tool names."""
        return list(self._tools.keys())

    def get_definitions(self) -> list[dict[str, Any]]:
        """Return provider-neutral JSON Schema definitions for registered tools."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }
            for t in self._tools.values()
        ]

    def _verify_and_inject_sandbox_id(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Enforce that arguments strictly target the authorized sandbox context."""
        cleaned = dict(arguments)
        passed_id = cleaned.get("sandbox_id")

        if passed_id is not None:
            passed_id_str = str(passed_id).strip()
            authorized_str = str(self.authorized_sandbox_id)
            if passed_id_str != authorized_str:
                logger.warning(
                    "Security violation: model requested sandbox_id=%s, but session is bound to %s",
                    passed_id_str,
                    authorized_str,
                )
                raise AgentSecurityError(
                    f"Access denied: cannot access sandbox '{passed_id_str}'. "
                    f"Tool calls are strictly restricted to authorized sandbox '{authorized_str}'.",
                    details={
                        "requested_sandbox_id": passed_id_str,
                        "authorized_sandbox_id": authorized_str,
                    },
                )
        # Ensure authorized sandbox_id is explicitly bound
        cleaned["sandbox_id"] = str(self.authorized_sandbox_id)
        return cleaned

    def _register_default_tools(self) -> None:
        """Register the 8 standard sandbox workspace, execution, and inspection tools."""

        # 1. get_sandbox
        self.register_tool(
            AgentToolDefinition(
                name="get_sandbox",
                description=(
                    "Check the lifecycle status, remaining TTL, resource limits, and execution "
                    "count of the current active sandbox session."
                ),
                parameters=GetSandboxInput.model_json_schema(),
            ),
            self._handle_get_sandbox,
        )

        # 2. list_files
        self.register_tool(
            AgentToolDefinition(
                name="list_files",
                description=(
                    "List files and directories inside the sandbox persistent workspace. "
                    "Returns relative paths, sizes in bytes, and timestamps."
                ),
                parameters=ListFilesInput.model_json_schema(),
            ),
            self._handle_list_files,
        )

        # 3. read_file
        self.register_tool(
            AgentToolDefinition(
                name="read_file",
                description=(
                    "Read content of a file from the sandbox persistent workspace. "
                    "Returns plain text (UTF-8) or base64."
                ),
                parameters=ReadFileInput.model_json_schema(),
            ),
            self._handle_read_file,
        )

        # 4. write_file
        self.register_tool(
            AgentToolDefinition(
                name="write_file",
                description=(
                    "Create or atomically overwrite a file inside the sandbox persistent workspace "
                    "using UTF-8 text or base64 content."
                ),
                parameters=WriteFileInput.model_json_schema(),
            ),
            self._handle_write_file,
        )

        # 5. create_directory
        self.register_tool(
            AgentToolDefinition(
                name="create_directory",
                description=(
                    "Create a directory (and any necessary parent directories) in the workspace."
                ),
                parameters=CreateDirectoryInput.model_json_schema(),
            ),
            self._handle_create_directory,
        )

        # 6. delete_file
        self.register_tool(
            AgentToolDefinition(
                name="delete_file",
                description=(
                    "Delete a file or empty directory inside the sandbox persistent workspace."
                ),
                parameters=DeleteFileInput.model_json_schema(),
            ),
            self._handle_delete_file,
        )

        # 7. execute_code
        self.register_tool(
            AgentToolDefinition(
                name="execute_code",
                description=(
                    "Execute Python code inside a fresh, hardened ephemeral container/microVM. "
                    "Returns execution status, process exit code, stdout, stderr, and duration."
                ),
                parameters=ExecuteCodeInput.model_json_schema(),
            ),
            self._handle_execute_code,
        )

        # 8. get_execution_result
        self.register_tool(
            AgentToolDefinition(
                name="get_execution_result",
                description=(
                    "Retrieve the detailed execution outcome, logs, and exit code for a "
                    "previously executed code job in this sandbox."
                ),
                parameters=GetExecutionResultInput.model_json_schema(),
            ),
            self._handle_get_execution_result,
        )

    def register_tool(
        self,
        definition: AgentToolDefinition,
        handler: Callable[[dict[str, Any]], Coroutine[Any, Any, Any] | Any],
    ) -> None:
        """Register a custom tool definition and handler."""
        self._tools[definition.name] = definition
        self._handlers[definition.name] = handler

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        """Validate, authorize, execute the requested tool, and return serialized JSON."""
        if tool_name not in self._handlers:
            err = AgentToolError(
                error="UnknownToolError",
                message=f"Tool '{tool_name}' is not recognized.",
                details={"available_tools": self.tool_names},
            )
            return err.model_dump_json()

        try:
            # 1. Enforce sandbox isolation boundary
            cleaned_args = self._verify_and_inject_sandbox_id(arguments)

            # 2. Dispatch handler
            handler = self._handlers[tool_name]
            result = handler(cleaned_args)
            if hasattr(result, "__await__"):
                result = await result

            # 3. Serialize output
            if hasattr(result, "model_dump_json"):
                dumped = result.model_dump_json()
                serialized = dumped if isinstance(dumped, str) else str(dumped)
            elif isinstance(result, (dict, list)):
                serialized = json.dumps(result, default=str)
            else:
                serialized = str(result)

            # 4. Truncate if output exceeds safety limits
            return self._truncate_output(serialized)

        except AgentSecurityError as sec_err:
            err = AgentToolError(
                error="AccessDeniedError",
                message=sec_err.message,
                details=sec_err.details,
            )
            return err.model_dump_json()
        except ValidationError as val_err:
            clean_errors = []
            for item in val_err.errors():
                clean_item = dict(item)
                if "ctx" in clean_item and isinstance(clean_item["ctx"], dict):
                    clean_item["ctx"] = {k: str(v) for k, v in clean_item["ctx"].items()}
                clean_errors.append(clean_item)
            err = AgentToolError(
                error="ValidationError",
                message="Input arguments failed schema validation.",
                details={"errors": clean_errors},
            )
            return err.model_dump_json()
        except SandboxPlatformError as plat_err:
            err = AgentToolError(
                error=plat_err.__class__.__name__,
                message=plat_err.message,
                details=plat_err.details,
            )
            return err.model_dump_json()
        except Exception as exc:
            logger.exception("Unexpected error executing tool '%s': %s", tool_name, exc)
            err = AgentToolError(
                error="InternalToolError",
                message="An unexpected error occurred while executing the tool.",
                details={},
            )
            return err.model_dump_json()

    def _truncate_output(self, text: str) -> str:
        """Truncate tool output if it exceeds maximum allowed result bytes."""
        text_bytes = len(text.encode("utf-8"))
        if text_bytes <= self.max_output_bytes:
            return text

        # Truncate text cleanly
        keep_chars = int(len(text) * (self.max_output_bytes / text_bytes) * 0.95)
        truncated_text = text[:keep_chars]
        warning = (
            f"\n\n[WARNING: Tool output truncated: original size {text_bytes} bytes "
            f"exceeded maximum allowed limit of {self.max_output_bytes} bytes.]"
        )
        return truncated_text + warning

    # Internal Handlers
    def _handle_get_sandbox(self, args: dict[str, Any]) -> Any:
        payload = GetSandboxInput.model_validate(args)
        sandbox = self.service.get_sandbox(payload.sandbox_id)
        return {
            "sandbox_id": str(sandbox.id),
            "status": str(sandbox.status),
            "runtime": sandbox.runtime,
            "created_at": sandbox.created_at.isoformat(),
            "expires_at": sandbox.expires_at.isoformat(),
            "destroyed_at": sandbox.destroyed_at.isoformat() if sandbox.destroyed_at else None,
            "resource_config": sandbox.resource_config,
            "executions_count": len(sandbox.executions),
        }

    def _handle_list_files(self, args: dict[str, Any]) -> Any:
        payload = ListFilesInput.model_validate(args)
        return self.service.list_files(sandbox_id=payload.sandbox_id, path=payload.path)

    def _handle_read_file(self, args: dict[str, Any]) -> Any:
        payload = ReadFileInput.model_validate(args)
        return self.service.read_file(sandbox_id=payload.sandbox_id, path=payload.path)

    def _handle_write_file(self, args: dict[str, Any]) -> Any:
        payload = WriteFileInput.model_validate(args)
        return self.service.write_file(
            sandbox_id=payload.sandbox_id,
            path=payload.path,
            content=payload.content,
            encoding=payload.encoding,
        )

    def _handle_create_directory(self, args: dict[str, Any]) -> Any:
        payload = CreateDirectoryInput.model_validate(args)
        created = self.service.create_directory(
            sandbox_id=payload.sandbox_id,
            path=payload.path,
        )
        return {"path": payload.path, "created": created}

    def _handle_delete_file(self, args: dict[str, Any]) -> Any:
        payload = DeleteFileInput.model_validate(args)
        deleted = self.service.delete_file(
            sandbox_id=payload.sandbox_id,
            path=payload.path,
        )
        return {"path": payload.path, "deleted": deleted}

    async def _handle_execute_code(self, args: dict[str, Any]) -> Any:
        payload = ExecuteCodeInput.model_validate(args)
        return await self.service.execute_code(
            sandbox_id=payload.sandbox_id,
            code=payload.code,
            timeout_seconds=payload.timeout_seconds,
        )

    def _handle_get_execution_result(self, args: dict[str, Any]) -> Any:
        payload = GetExecutionResultInput.model_validate(args)
        return self.service.get_execution(
            sandbox_id=payload.sandbox_id,
            execution_id=payload.execution_id,
        )
