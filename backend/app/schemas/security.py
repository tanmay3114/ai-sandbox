"""Pydantic schemas for platform security policy inspection and evaluation."""

from typing import Any

from pydantic import BaseModel, Field

from app.security.policy import SecurityAuditRecord


class SecurityInvariantsResponse(BaseModel):
    """Immutable, non-negotiable container sandbox security invariants."""

    network_mode: str = Field(..., description="Container network isolation mode ('none')")
    read_only_rootfs: bool = Field(..., description="Root filesystem read-only confinement flag")
    user: str = Field(..., description="Execution UID:GID (unprivileged non-root 10001:10001)")
    cap_drop: list[str] = Field(..., description="Linux capabilities dropped (['ALL'])")
    security_opt: list[str] = Field(
        ..., description="Security options (['no-new-privileges:true'])"
    )
    allow_host_mounts: bool = Field(..., description="Host filesystem and volume binds prohibited")
    allow_docker_socket: bool = Field(..., description="Docker socket access prohibited")
    allow_privileged: bool = Field(..., description="Privileged execution prohibited")
    allow_arbitrary_images: bool = Field(..., description="Arbitrary image execution prohibited")


class SecurityLimitsResponse(BaseModel):
    """Authoritative platform resource bounds and quotas."""

    memory_limit: str = Field(..., description="Maximum container memory limit (e.g. '256m')")
    cpu_limit: float = Field(..., description="Maximum CPU quota in cores (e.g. 0.5)")
    pids_limit: int = Field(..., description="Maximum process / PID limit (e.g. 32)")
    timeout_seconds: float = Field(..., description="Execution timeout in seconds (e.g. 5.0)")
    max_stdout_bytes: int = Field(..., description="Maximum stdout capture buffer in bytes")
    max_stderr_bytes: int = Field(..., description="Maximum stderr capture buffer in bytes")
    tmpfs_size: str = Field(..., description="Temporary isolated tmpfs size (e.g. '32m')")
    global_concurrency_limit: int = Field(..., description="Maximum concurrent sandbox executions")


class SecurityRuntimeResponse(BaseModel):
    """Approved runtime environments and container images."""

    default_runtime: str = Field(..., description="Default sandbox execution runtime ('python')")
    approved_image: str = Field(..., description="Whitelisted container image")
    allowed_runtimes: dict[str, str] = Field(
        ..., description="Mapping of supported runtimes to images"
    )


class PlatformSecurityPolicyResponse(BaseModel):
    """Authoritative platform security configuration and boundary overview."""

    engine: str = Field(
        default="SecurityPolicyEngine (Phase 5)", description="Security policy engine name"
    )
    enforcement: str = Field(default="authoritative", description="Policy enforcement status")
    invariants: SecurityInvariantsResponse = Field(
        ..., description="Non-negotiable security boundaries"
    )
    resource_limits: SecurityLimitsResponse = Field(..., description="Enforced resource bounds")
    runtime: SecurityRuntimeResponse = Field(..., description="Approved runtime specifications")


class SecurityEvaluationResponse(BaseModel):
    """Outcome of dry-run security policy evaluation against requested parameters."""

    status: str = Field(..., description="Decision outcome ('allowed' or 'clamped')")
    audit: SecurityAuditRecord = Field(..., description="Structured audit decision record")
    effective: dict[str, Any] = Field(..., description="Sanitized summary of effective policy")
