"""Security policy models defining requested capabilities, effective policies, and audit records."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import CoreSchema, core_schema


class RequestedPolicy(BaseModel):
    """Execution parameters and capabilities requested by a caller.

    Captures both permissible tuning parameters and any attempt to request
    forbidden or security-sensitive capabilities for explicit policy evaluation.
    Rejects any unknown fields to prevent parameter injection attacks.
    """

    model_config = ConfigDict(extra="forbid")

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


class FrozenDict(dict):
    """Immutable dictionary subclass preventing in-place modification of security policies."""

    def __readonly__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("FrozenDict is immutable and cannot be modified")

    __setitem__ = __readonly__
    __delitem__ = __readonly__
    pop = __readonly__
    popitem = __readonly__
    clear = __readonly__
    update = __readonly__
    setdefault = __readonly__

    def __copy__(self) -> "FrozenDict":
        return self

    def __deepcopy__(self, memo: Any) -> "FrozenDict":
        return self

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: Any
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls,
            core_schema.dict_schema(),
        )


class EffectiveSandboxPolicy(BaseModel):
    """Trusted, deeply immutable, and normalized security policy.

    The execution engine and container builder accept ONLY this model.
    Guarantees both top-level immutability (frozen=True) and nested collection
    immutability (tuples for lists, FrozenDict for mappings).
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

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
    cap_drop: tuple[str, ...] = ("ALL",)
    security_opt: tuple[str, ...] = ("no-new-privileges:true",)
    user: str = "10001:10001"
    read_only: bool = True
    tmpfs: FrozenDict
    volumes: FrozenDict = Field(default_factory=FrozenDict)
    environment: FrozenDict

    # Platform tracking metadata
    project_label: str
    managed_by_label: str

    @field_validator("cap_drop", "security_opt", mode="before")
    @classmethod
    def _validate_tuple(cls, v: Any) -> tuple[str, ...]:
        if isinstance(v, list | tuple):
            return tuple(v)
        return (v,)

    @field_validator("tmpfs", "volumes", "environment", mode="before")
    @classmethod
    def _validate_frozen_dict(cls, v: Any) -> FrozenDict:
        if isinstance(v, FrozenDict):
            return v
        if isinstance(v, dict):
            return FrozenDict(v)
        return v


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
