"""QEMU ARM64 implementation of the provider-neutral SandboxBackend contract."""

from __future__ import annotations

from app.core.config import SandboxSettings, settings
from app.sandbox.policy import EffectiveSandboxPolicy
from app.sandbox.qemu.vm_manager import QemuVmManager
from app.sandbox.schemas import (
    ExecutionRequest,
    ExecutionResult,
    FileContent,
    FileInfo,
    FileListResponse,
)
from app.sandbox.workspace import WorkspaceManager


class QemuSandboxBackend:
    """Provider-neutral SandboxBackend adapter executing code in ephemeral ARM64 QEMU VMs."""

    def __init__(
        self,
        config: SandboxSettings = settings,
        vm_manager: QemuVmManager | None = None,
        workspace_manager: WorkspaceManager | None = None,
    ) -> None:
        self.config = config
        self.policy = EffectiveSandboxPolicy.from_settings(config)
        self.workspace_manager = workspace_manager or (
            vm_manager.workspace_manager
            if vm_manager is not None
            else WorkspaceManager(config=config)
        )
        self.vm_manager = vm_manager or QemuVmManager(
            config=config,
            workspace_manager=self.workspace_manager,
        )

    def execute(
        self,
        request: ExecutionRequest,
        *,
        sandbox_id: str | None = None,
    ) -> ExecutionResult:
        """Run one ephemeral VM execution associated with a logical sandbox."""
        return self.vm_manager.execute(request, sandbox_id=sandbox_id, policy=self.policy)

    def cleanup_execution_containers(self, sandbox_id: str) -> None:
        """Remove only verified ephemeral execution VMs owned by the logical sandbox."""
        self.vm_manager.cleanup_execution_containers(sandbox_id)

    def cleanup_sandbox(self, sandbox_id: str) -> None:
        """Remove verified QEMU VM resources and persistent workspace for the logical sandbox."""
        self.vm_manager.cleanup_sandbox(sandbox_id)

    def check_health(self) -> None:
        """Verify QEMU runtime, accelerator, and guest image readiness."""
        self.vm_manager.check_health()

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
