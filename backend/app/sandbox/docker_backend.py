"""Docker implementation of the provider-neutral sandbox backend."""

from app.core.config import SandboxSettings, settings
from app.sandbox.engine import EphemeralSandboxEngine
from app.sandbox.policy import EffectiveSandboxPolicy
from app.sandbox.schemas import (
    ExecutionRequest,
    ExecutionResult,
    FileContent,
    FileInfo,
    FileListResponse,
)
from app.sandbox.workspace import WorkspaceManager


class DockerSandboxBackend:
    """Thin adapter retaining the proven Docker execution engine implementation."""

    def __init__(
        self,
        config: SandboxSettings = settings,
        engine: EphemeralSandboxEngine | None = None,
        workspace_manager: WorkspaceManager | None = None,
    ) -> None:
        self.config = config
        self.policy = EffectiveSandboxPolicy.from_settings(config)
        self.workspace_manager = workspace_manager or (
            engine.workspace_manager if engine is not None else WorkspaceManager(config=config)
        )
        self.engine = engine or EphemeralSandboxEngine(
            config=config,
            workspace_manager=self.workspace_manager,
        )

    def execute(
        self,
        request: ExecutionRequest,
        *,
        sandbox_id: str | None = None,
    ) -> ExecutionResult:
        """Run the validated policy through the existing synchronous Docker engine."""
        return self.engine.execute(request, sandbox_id=sandbox_id, policy=self.policy)

    def cleanup_execution_containers(self, sandbox_id: str) -> None:
        """Remove only verified ephemeral execution containers owned by the logical sandbox."""
        self.engine.cleanup_execution_containers(sandbox_id)

    def cleanup_sandbox(self, sandbox_id: str) -> None:
        """Remove verified Docker resources and persistent workspace for the logical sandbox."""
        self.engine.cleanup_sandbox(sandbox_id)

    def check_health(self) -> None:
        """Verify Docker availability without leaking Docker details to callers."""
        self.engine.check_health()

    def write_file(
        self,
        sandbox_id: str,
        path: str,
        content: str | bytes,
        encoding: str = "utf-8",
    ) -> FileInfo:
        """Write a file into the logical sandbox's persistent workspace."""
        return self.workspace_manager.write_file(sandbox_id, path, content, encoding=encoding)

    def read_file(self, sandbox_id: str, path: str) -> FileContent:
        """Read a file from the logical sandbox's persistent workspace."""
        return self.workspace_manager.read_file(sandbox_id, path)

    def list_files(self, sandbox_id: str, path: str = "") -> FileListResponse:
        """List files and directories in the logical sandbox's persistent workspace."""
        return self.workspace_manager.list_files(sandbox_id, path=path)

    def delete_file(self, sandbox_id: str, path: str) -> bool:
        """Delete a file or empty directory in the logical sandbox's persistent workspace."""
        return self.workspace_manager.delete_file(sandbox_id, path)

    def create_directory(self, sandbox_id: str, path: str) -> bool:
        """Create a directory in the logical sandbox's persistent workspace."""
        return self.workspace_manager.create_directory(sandbox_id, path)
