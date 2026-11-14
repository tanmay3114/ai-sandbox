"""Provider-neutral boundary for ephemeral sandbox infrastructure."""

from typing import Protocol, runtime_checkable

from app.sandbox.schemas import (
    ExecutionRequest,
    ExecutionResult,
    FileContent,
    FileInfo,
    FileListResponse,
)


@runtime_checkable
class SandboxBackend(Protocol):
    """Execute and clean resources without exposing provider implementation details."""

    def execute(
        self,
        request: ExecutionRequest,
        *,
        sandbox_id: str | None = None,
    ) -> ExecutionResult:
        """Run one ephemeral execution associated with a logical sandbox."""

    def cleanup_sandbox(self, sandbox_id: str) -> None:
        """Idempotently remove verified ephemeral resources and workspace for a logical sandbox."""

    def check_health(self) -> None:
        """Raise a domain infrastructure error when the backend is unavailable."""

    def write_file(
        self,
        sandbox_id: str,
        path: str,
        content: str | bytes,
        encoding: str = "utf-8",
    ) -> FileInfo:
        """Write a file into the logical sandbox's persistent workspace."""

    def read_file(self, sandbox_id: str, path: str) -> FileContent:
        """Read a file from the logical sandbox's persistent workspace."""

    def list_files(self, sandbox_id: str, path: str = "") -> FileListResponse:
        """List files and directories in the logical sandbox's persistent workspace."""

    def delete_file(self, sandbox_id: str, path: str) -> bool:
        """Delete a file or empty directory in the logical sandbox's persistent workspace."""

    def create_directory(self, sandbox_id: str, path: str) -> bool:
        """Create a directory in the logical sandbox's persistent workspace."""
