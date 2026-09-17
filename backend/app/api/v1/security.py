"""Security policy inspection and evaluation router for API v1."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_settings
from app.core.config import SandboxSettings
from app.schemas.errors import ErrorResponse
from app.schemas.security import (
    PlatformSecurityPolicyResponse,
    SecurityEvaluationResponse,
    SecurityInvariantsResponse,
    SecurityLimitsResponse,
    SecurityRuntimeResponse,
)
from app.security.engine import SecurityPolicyEngine
from app.security.policy import RequestedPolicy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/security", tags=["Security Policy"])


@router.get(
    "/policy",
    response_model=PlatformSecurityPolicyResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Authoritative Security Policy",
    description="""
Retrieve the authoritative security boundaries, non-negotiable container invariants,
resource quotas, and approved runtimes enforced by the backend SecurityPolicyEngine.
""",
)
async def get_platform_security_policy(
    config: SandboxSettings = Depends(get_settings),
) -> PlatformSecurityPolicyResponse:
    """Return the active platform security policy and boundaries."""
    engine = SecurityPolicyEngine(config=config)
    default_policy = engine.get_default_policy(runtime="python")

    return PlatformSecurityPolicyResponse(
        engine="SecurityPolicyEngine (Phase 5)",
        enforcement="authoritative",
        invariants=SecurityInvariantsResponse(
            network_mode=default_policy.network_mode,
            read_only_rootfs=default_policy.read_only,
            user=default_policy.user,
            cap_drop=list(default_policy.cap_drop),
            security_opt=list(default_policy.security_opt),
            allow_host_mounts=False,
            allow_docker_socket=False,
            allow_privileged=False,
            allow_arbitrary_images=False,
        ),
        resource_limits=SecurityLimitsResponse(
            memory_limit=config.MEMORY_LIMIT,
            cpu_limit=config.CPU_LIMIT,
            pids_limit=config.PIDS_LIMIT,
            timeout_seconds=config.TIMEOUT_SECONDS,
            max_stdout_bytes=config.MAX_STDOUT_BYTES,
            max_stderr_bytes=config.MAX_STDERR_BYTES,
            tmpfs_size=config.TMPFS_SIZE,
            global_concurrency_limit=config.GLOBAL_CONCURRENCY_LIMIT,
        ),
        runtime=SecurityRuntimeResponse(
            default_runtime="python",
            approved_image=config.BASE_IMAGE,
            allowed_runtimes=dict(config.ALLOWED_RUNTIMES),
        ),
    )


@router.post(
    "/evaluate",
    response_model=SecurityEvaluationResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {
            "model": SecurityEvaluationResponse,
            "description": "Policy evaluated (allowed or clamped)",
        },
        400: {
            "model": ErrorResponse,
            "description": "Security policy invariant violation (rejected)",
        },
        422: {"description": "Malformed policy request payload"},
    },
    summary="Simulate Security Policy Enforcement",
    description="""
Performs dry-run policy evaluation using the authoritative backend SecurityPolicyEngine.
Demonstrates the distinction between Requested Policy and Effective Sandbox Policy.
Attempting to request forbidden capabilities (privileged mode, networking, host mounts,
root execution) raises an immediate SecurityPolicyViolationError (HTTP 400).
""",
)
async def evaluate_security_policy(
    requested: RequestedPolicy,
    config: SandboxSettings = Depends(get_settings),
) -> SecurityEvaluationResponse:
    """Evaluate requested policy without executing code or creating containers."""
    engine = SecurityPolicyEngine(config=config)
    effective, audit = engine.evaluate(
        requested=requested,
        sandbox_id="dry-run-evaluation",
    )

    safe_effective: dict[str, Any] = {
        "runtime": effective.runtime,
        "image": effective.image,
        "timeout_seconds": effective.timeout_seconds,
        "memory_limit": effective.memory_limit,
        "nano_cpus": effective.nano_cpus,
        "pids_limit": effective.pids_limit,
        "max_stdout_bytes": effective.max_stdout_bytes,
        "max_stderr_bytes": effective.max_stderr_bytes,
        "network_mode": effective.network_mode,
        "privileged": effective.privileged,
        "read_only": effective.read_only,
        "user": effective.user,
        "cap_drop": list(effective.cap_drop),
        "security_opt": list(effective.security_opt),
    }

    return SecurityEvaluationResponse(
        status=audit.decision,
        audit=audit,
        effective=safe_effective,
    )
