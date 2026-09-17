"""Security profile builder enforcing defense-in-depth container isolation."""

from typing import Any

import docker.types

from app.core.config import SandboxSettings, settings
from app.security.policy import EffectiveSandboxPolicy


def build_container_parameters(
    code: str,
    sandbox_id: str,
    config: SandboxSettings = settings,
    policy: EffectiveSandboxPolicy | None = None,
) -> dict[str, Any]:
    """Construct hardened Docker container parameters.

    Derives container parameters strictly from an immutable EffectiveSandboxPolicy.
    If no policy is provided, instantiates the default trusted platform policy.
    """
    if policy is None:
        from app.security.engine import SecurityPolicyEngine

        policy = SecurityPolicyEngine(config=config).get_default_policy()

    return {
        "image": policy.image,
        "command": ["python", "-c", code],
        "detach": True,
        # Compute & Memory bounds
        "mem_limit": policy.memory_limit,
        "memswap_limit": policy.memswap_limit,
        "nano_cpus": policy.nano_cpus,
        "pids_limit": policy.pids_limit,
        # Network confinement
        "network_mode": policy.network_mode,
        # Privilege confinement
        "privileged": policy.privileged,
        "cap_drop": list(policy.cap_drop),
        "security_opt": list(policy.security_opt),
        "user": policy.user,
        # Filesystem isolation
        "read_only": policy.read_only,
        "tmpfs": dict(policy.tmpfs),
        "volumes": dict(policy.volumes),  # Strictly empty - no host directory or docker.sock mounts
        # Sanitized container environment
        "environment": dict(policy.environment),
        # Logging bounds to protect Docker host disk space
        "log_config": docker.types.LogConfig(
            type=docker.types.LogConfig.types.JSON,
            config={"max-size": "10m"},
        ),
        # Platform tracking metadata
        "labels": {
            "project": policy.project_label,
            "managed-by": policy.managed_by_label,
            "sandbox_id": sandbox_id,
        },
    }
