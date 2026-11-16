"""Immutable provider-neutral sandbox security policy."""

from dataclasses import dataclass

from app.core.config import SandboxSettings
from app.core.exceptions import ResourceLimitError

APPROVED_RUNTIME_USER = "10001:10001"


@dataclass(frozen=True, slots=True)
class EffectiveSandboxPolicy:
    """Validated mandatory controls every execution backend must enforce."""

    image: str
    memory_limit: str
    memswap_limit: str
    nano_cpus: int
    pids_limit: int
    timeout_seconds: float
    max_stdout_bytes: int
    max_stderr_bytes: int
    tmpfs_size: str
    max_file_size_bytes: int = 5 * 1024 * 1024
    max_workspace_size_bytes: int = 25 * 1024 * 1024
    network_disabled: bool = True
    privileged: bool = False
    drop_all_capabilities: bool = True
    no_new_privileges: bool = True
    run_as_user: str = APPROVED_RUNTIME_USER
    read_only_rootfs: bool = True
    host_mounts_allowed: bool = False
    host_environment_allowed: bool = False

    @classmethod
    def from_settings(cls, config: SandboxSettings) -> "EffectiveSandboxPolicy":
        """Build the only policy accepted by the current application configuration."""
        policy = cls(
            image=config.BASE_IMAGE,
            memory_limit=config.MEMORY_LIMIT,
            memswap_limit=config.MEMSWAP_LIMIT,
            nano_cpus=config.nano_cpus,
            pids_limit=config.PIDS_LIMIT,
            timeout_seconds=config.TIMEOUT_SECONDS,
            max_stdout_bytes=config.MAX_STDOUT_BYTES,
            max_stderr_bytes=config.MAX_STDERR_BYTES,
            tmpfs_size=config.TMPFS_SIZE,
            max_file_size_bytes=config.MAX_FILE_SIZE_BYTES,
            max_workspace_size_bytes=config.MAX_WORKSPACE_SIZE_BYTES,
        )
        policy.validate()
        return policy

    def validate(self) -> None:
        """Fail closed if a mandatory provider-neutral safety requirement is absent."""
        if "@sha256:" not in self.image:
            raise ResourceLimitError("Sandbox policy requires an immutable runtime image digest")
        if self.memory_limit != self.memswap_limit:
            raise ResourceLimitError("Sandbox policy requires memory and swap limits to match")
        if self.nano_cpus <= 0 or self.pids_limit <= 0 or self.timeout_seconds <= 0:
            raise ResourceLimitError("Sandbox policy resource limits must be positive")
        if self.max_stdout_bytes <= 0 or self.max_stderr_bytes <= 0:
            raise ResourceLimitError("Sandbox policy output limits must be positive")
        if self.max_file_size_bytes <= 0 or self.max_workspace_size_bytes <= 0:
            raise ResourceLimitError("Sandbox policy workspace storage limits must be positive")
        if self.run_as_user != APPROVED_RUNTIME_USER:
            raise ResourceLimitError(
                f"Sandbox policy requires approved non-root numeric user {APPROVED_RUNTIME_USER}"
            )
        if not all(
            (
                self.network_disabled,
                not self.privileged,
                self.drop_all_capabilities,
                self.no_new_privileges,
                self.read_only_rootfs,
                not self.host_mounts_allowed,
                not self.host_environment_allowed,
            )
        ):
            raise ResourceLimitError(
                "Sandbox policy omits one or more mandatory isolation controls"
            )
