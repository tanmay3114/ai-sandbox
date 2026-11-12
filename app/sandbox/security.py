"""Security profile builder enforcing defense-in-depth container isolation."""

from typing import Any

import docker.types

from app.core.config import SandboxSettings, settings
from app.sandbox.policy import EffectiveSandboxPolicy


def build_container_parameters(
    code: str,
    sandbox_id: str,
    config: SandboxSettings = settings,
    policy: EffectiveSandboxPolicy | None = None,
) -> dict[str, Any]:
    """Translate a validated provider-neutral policy into Docker controls.

    Security controls:
    1. Privilege: non-root user (10001:10001), cap_drop ALL, no-new-privileges, unprivileged.
    2. Filesystem: read_only root filesystem, restricted tmpfs at /tmp, 0 host mounts.
    3. Network: network_mode='none' (completely isolated network stack).
    4. Compute: strict memory limit, memory+swap limit, nano_cpus, pids_limit.
    5. Environment: minimal sanitized env vars; zero host environment or secrets forwarded.
    6. Command: strict argument vector ["python", "-c", code] avoiding shell evaluation.
    7. Ownership: metadata labels for project-scoped lifecycle tracking.
    """
    effective_policy = policy or EffectiveSandboxPolicy.from_settings(config)
    effective_policy.validate()

    if not (
        effective_policy.network_disabled
        and not effective_policy.privileged
        and effective_policy.drop_all_capabilities
        and effective_policy.no_new_privileges
        and effective_policy.read_only_rootfs
        and not effective_policy.host_mounts_allowed
        and not effective_policy.host_environment_allowed
    ):
        raise ValueError("Docker backend cannot weaken mandatory sandbox policy controls")

    fsize_limit = min(
        effective_policy.max_file_size_bytes,
        effective_policy.max_workspace_size_bytes,
    )

    return {
        "image": effective_policy.image,
        "command": ["python", "-c", code],
        "detach": True,
        "working_dir": "/workspace",
        # Compute & Memory bounds
        "mem_limit": effective_policy.memory_limit,
        "memswap_limit": effective_policy.memswap_limit,
        "nano_cpus": effective_policy.nano_cpus,
        "pids_limit": effective_policy.pids_limit,
        # Kernel-enforced execution-time file size ceiling (RLIMIT_FSIZE)
        "ulimits": [
            docker.types.Ulimit(
                name="fsize",
                soft=fsize_limit,
                hard=fsize_limit,
            ),
        ],
        # Network confinement
        "network_mode": "none",
        # Privilege confinement
        "privileged": effective_policy.privileged,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "user": effective_policy.run_as_user,
        # Filesystem isolation
        "read_only": effective_policy.read_only_rootfs,
        "tmpfs": {
            "/tmp": f"size={effective_policy.tmpfs_size},noexec,nosuid,nodev",
        },
        "mounts": [
            docker.types.Mount(
                target="/workspace",
                source=None,
                type="volume",
                no_copy=True,
            ),
        ],
        "volumes": {},  # Strictly empty - no host directory or docker.sock mounts
        # Sanitized container environment
        "environment": {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            "HOME": "/workspace",
        },
        # Logging bounds to protect Docker host disk space
        "log_config": docker.types.LogConfig(
            type=docker.types.LogConfig.types.JSON,
            config={"max-size": "10m"},
        ),
        # Platform tracking metadata
        "labels": {
            "project": config.PROJECT_LABEL,
            "managed-by": config.MANAGED_BY_LABEL,
            "sandbox_id": sandbox_id,
        },
    }
