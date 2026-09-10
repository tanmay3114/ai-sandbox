"""Security profile builder enforcing defense-in-depth container isolation."""

from typing import Any

import docker.types

from app.core.config import SandboxSettings, settings


def build_container_parameters(
    code: str,
    sandbox_id: str,
    config: SandboxSettings = settings,
) -> dict[str, Any]:
    """Construct hardened Docker container parameters.

    Security controls:
    1. Privilege: non-root user (10001:10001), cap_drop ALL, no-new-privileges, unprivileged.
    2. Filesystem: read_only root filesystem, restricted tmpfs at /tmp, 0 host mounts.
    3. Network: network_mode='none' (completely isolated network stack).
    4. Compute: strict memory limit, memory+swap limit, nano_cpus, pids_limit.
    5. Environment: minimal sanitized env vars; zero host environment or secrets forwarded.
    6. Command: strict argument vector ["python", "-c", code] avoiding shell evaluation.
    7. Ownership: metadata labels for project-scoped lifecycle tracking.
    """
    return {
        "image": config.BASE_IMAGE,
        "command": ["python", "-c", code],
        "detach": True,
        # Compute & Memory bounds
        "mem_limit": config.MEMORY_LIMIT,
        "memswap_limit": config.MEMSWAP_LIMIT,
        "nano_cpus": config.nano_cpus,
        "pids_limit": config.PIDS_LIMIT,
        # Network confinement
        "network_mode": "none",
        # Privilege confinement
        "privileged": False,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "user": "10001:10001",
        # Filesystem isolation
        "read_only": True,
        "tmpfs": {
            "/tmp": f"size={config.TMPFS_SIZE},noexec,nosuid,nodev",
        },
        "volumes": {},  # Strictly empty - no host directory or docker.sock mounts
        # Sanitized container environment
        "environment": {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
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
