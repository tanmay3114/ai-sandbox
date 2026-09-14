"""Security policy models defining requested capabilities, effective policies, and audit records."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RequestedPolicy(BaseModel):
    """Execution parameters and capabilities requested by a caller.

    Captures both permissible tuning parameters and any attempt to request
    forbidden or security-sensitive capabilities for explicit policy evaluation.
    """

    model_config = ConfigDict(extra="ignore")

    # Safe tunable parameters
    runtime: str | None = Field(
        default=None,
        description="Target execution runtime (e.g. 'python')",
    )
    timeout_seconds: float | None = Field(
        default=None,
        description="Requested timeout in seconds",
    )
    memory_limit: str | None = Field(
        default=None,
        description="Requested memory limit (e.g. '256m')",
    )
    cpu_limit: float | None = Field(
        default=None,
        description="Requested CPU limit (e.g. 0.5)",
    )
    pids_limit: int | None = Field(
        default=None,
        description="Requested process/PID limit",
    )
    max_stdout_bytes: int | None = Field(
        default=None,
        description="Requested stdout byte cap",
    )
    max_stderr_bytes: int | None = Field(
        default=None,
        description="Requested stderr byte cap",
    )

    # Security-sensitive parameters (captured strictly to detect and reject policy violations)
    image: str | None = Field(
        default=None,
        description="Requested container image",
    )
    privileged: bool | None = Field(
        default=None,
        description="Requested privileged execution flag",
    )
    network_mode: str | None = Field(
        default=None,
        description="Requested network mode",
    )
    cap_add: list[str] | None = Field(
        default=None,
        description="Requested Linux capabilities to add",
    )
    cap_drop: list[str] | None = Field(
        default=None,
        description="Requested Linux capabilities to drop",
    )
    security_opt: list[str] | None = Field(
        default=None,
        description="Requested security options",
    )
    user: str | None = Field(
        default=None,
        description="Requested execution UID/GID",
    )
    read_only: bool | None = Field(
        default=None,
        description="Requested root filesystem read-only flag",
    )
    volumes: dict[str, Any] | list[Any] | None = Field(
        default=None,
        description="Requested volume binds or host mounts",
    )


class EffectiveSandboxPolicy(BaseModel):
    """Trusted, immutable, and normalized security policy.

    The execution engine and container builder accept ONLY this model,
    ensuring that no external caller can weaken or bypass platform invariants.
    """

    model_config = ConfigDict(frozen=True)

    # Approved runtime & container image
    runtime: str
    image: str

    # Bounded resource constraints
    timeout_seconds: float
    memory_limit: str
    memswap_limit: str
    nano_cpus: int
    pids_limit: int
    max_stdout_bytes: int
    max_stderr_bytes: int

    # Non-negotiable security invariants
    network_mode: str = "none"
    privileged: bool = False
    cap_drop: list[str] = Field(default_factory=lambda: ["ALL"])
    security_opt: list[str] = Field(default_factory=lambda: ["no-new-privileges:true"])
    user: str = "10001:10001"
    read_only: bool = True
    tmpfs: dict[str, str]
    volumes: dict[str, Any] = Field(default_factory=dict)
    environment: dict[str, str]

    # Platform tracking metadata
    project_label: str
    managed_by_label: str


class SecurityAuditRecord(BaseModel):
    """Lightweight audit decision record.

    Distinguishes requested parameters from effective platform policy.
    Contains strictly sanitized metadata (zero secrets, credentials, or host paths).
    """

    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    sandbox_id: str
    decision: str  # "allowed", "clamped", "rejected"
    clamped_fields: list[str] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)
    requested_summary: dict[str, Any] = Field(default_factory=dict)
    effective_summary: dict[str, Any] = Field(default_factory=dict)
