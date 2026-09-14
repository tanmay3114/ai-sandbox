"""Security Policy Engine enforcing defense-in-depth platform security invariants."""

import logging
from typing import Any

from app.core.config import SandboxSettings, settings
from app.core.exceptions import SecurityPolicyViolationError
from app.sandbox.schemas import ExecutionRequest
from app.security.policy import (
    EffectiveSandboxPolicy,
    RequestedPolicy,
    SecurityAuditRecord,
)

logger = logging.getLogger(__name__)


def _parse_memory_bytes(val: str) -> int:
    """Parse a memory limit string (e.g. '256m', '1g', '512k') into integer bytes."""
    clean = val.strip().lower()
    if clean.endswith("g"):
        return int(clean[:-1]) * 1024 * 1024 * 1024
    if clean.endswith("m"):
        return int(clean[:-1]) * 1024 * 1024
    if clean.endswith("k"):
        return int(clean[:-1]) * 1024
    if clean.endswith("b"):
        return int(clean[:-1])
    return int(clean)


class SecurityPolicyEngine:
    """Centralized security policy evaluation and enforcement engine.

    Guarantees:
    1. The AI agent and external callers are NOT trusted.
    2. Any attempt to request forbidden capabilities (privileged mode, networking,
       host mounts, Docker socket access, root user, capability additions, or arbitrary images)
       is strictly rejected with a SecurityPolicyViolationError.
    3. Resource requests (CPU, memory, timeout, PID count, output size) are validated
       and clamped to platform limits defined in SandboxSettings.
    4. Produces an immutable EffectiveSandboxPolicy used exclusively by the execution engine.
    5. Records a lightweight, sanitized audit log distinguishing requested vs. effective
       constraints.
    """

    def __init__(self, config: SandboxSettings = settings) -> None:
        self.config = config

    def get_default_policy(self, runtime: str = "python") -> EffectiveSandboxPolicy:
        """Construct the default trusted EffectiveSandboxPolicy from configuration."""
        approved_image = self.config.ALLOWED_RUNTIMES.get(runtime, self.config.BASE_IMAGE)
        return EffectiveSandboxPolicy(
            runtime=runtime,
            image=approved_image,
            timeout_seconds=self.config.TIMEOUT_SECONDS,
            memory_limit=self.config.MEMORY_LIMIT,
            memswap_limit=self.config.MEMSWAP_LIMIT,
            nano_cpus=self.config.nano_cpus,
            pids_limit=self.config.PIDS_LIMIT,
            max_stdout_bytes=self.config.MAX_STDOUT_BYTES,
            max_stderr_bytes=self.config.MAX_STDERR_BYTES,
            network_mode="none",
            privileged=False,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            user="10001:10001",
            read_only=True,
            tmpfs={"/tmp": f"size={self.config.TMPFS_SIZE},noexec,nosuid,nodev"},
            volumes={},
            environment={
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUNBUFFERED": "1",
            },
            project_label=self.config.PROJECT_LABEL,
            managed_by_label=self.config.MANAGED_BY_LABEL,
        )

    def evaluate(
        self,
        requested: RequestedPolicy | ExecutionRequest | dict[str, Any] | str | None = None,
        timeout_override: float | None = None,
        sandbox_id: str | None = None,
    ) -> tuple[EffectiveSandboxPolicy, SecurityAuditRecord]:
        """Evaluate and enforce platform security policy on an incoming execution request.

        Raises:
            SecurityPolicyViolationError: If requested parameters violate security invariants.

        Returns:
            tuple[EffectiveSandboxPolicy, SecurityAuditRecord]:
                The immutable effective policy and structured audit record.
        """
        target_id = sandbox_id or "unspecified"

        # 1. Normalize input to RequestedPolicy
        if requested is None or isinstance(requested, str):
            req_policy = RequestedPolicy(timeout_seconds=timeout_override)
        elif isinstance(requested, ExecutionRequest):
            req_policy = RequestedPolicy(
                timeout_seconds=requested.timeout_seconds or timeout_override
            )
        elif isinstance(requested, dict):
            req_policy = RequestedPolicy.model_validate(requested)
            if timeout_override is not None and req_policy.timeout_seconds is None:
                req_policy.timeout_seconds = timeout_override
        elif isinstance(requested, RequestedPolicy):
            req_policy = requested
            if timeout_override is not None and req_policy.timeout_seconds is None:
                req_policy.timeout_seconds = timeout_override
        else:
            req_policy = RequestedPolicy(timeout_seconds=timeout_override)

        # 2. Strict Security Invariant Verification (Hard Rejections)
        if req_policy.privileged is True:
            logger.warning(
                f"Security policy rejection for sandbox {target_id}: privileged mode requested"
            )
            raise SecurityPolicyViolationError(
                "Privileged container execution is strictly forbidden by platform policy.",
                details={"violation": "privileged_execution_forbidden"},
            )

        if req_policy.network_mode is not None and req_policy.network_mode.strip().lower() not in (
            "none",
            "",
        ):
            logger.warning(
                f"Security policy rejection for sandbox {target_id}: "
                f"network mode '{req_policy.network_mode}' requested"
            )
            raise SecurityPolicyViolationError(
                f"Network access mode '{req_policy.network_mode}' is strictly forbidden. "
                "Network mode must be 'none'.",
                details={
                    "violation": "network_access_forbidden",
                    "requested": req_policy.network_mode,
                },
            )

        if req_policy.volumes:
            logger.warning(
                f"Security policy rejection for sandbox {target_id}: volumes/mounts requested"
            )
            raise SecurityPolicyViolationError(
                "Host filesystem and volume mounts are strictly forbidden by platform policy.",
                details={"violation": "host_mounts_forbidden"},
            )

        if req_policy.cap_add:
            logger.warning(
                f"Security policy rejection for sandbox {target_id}: "
                f"cap_add requested: {req_policy.cap_add}"
            )
            raise SecurityPolicyViolationError(
                f"Adding Linux capabilities ({req_policy.cap_add}) is strictly forbidden.",
                details={
                    "violation": "capability_addition_forbidden",
                    "cap_add": req_policy.cap_add,
                },
            )

        if req_policy.user is not None and req_policy.user.strip() not in (
            "10001:10001",
            "10001",
        ):
            logger.warning(
                f"Security policy rejection for sandbox {target_id}: "
                f"user override requested: {req_policy.user}"
            )
            raise SecurityPolicyViolationError(
                f"User override '{req_policy.user}' is strictly forbidden. "
                "Execution must run as unprivileged UID 10001.",
                details={"violation": "user_override_forbidden", "requested_user": req_policy.user},
            )

        if req_policy.read_only is False:
            logger.warning(
                f"Security policy rejection for sandbox {target_id}: read_only=False requested"
            )
            raise SecurityPolicyViolationError(
                "Disabling read-only root filesystem is strictly forbidden.",
                details={"violation": "writable_root_forbidden"},
            )

        if req_policy.security_opt is not None and any(
            "no-new-privileges:false" in opt.lower().replace(" ", "")
            for opt in req_policy.security_opt
        ):
            logger.warning(
                f"Security policy rejection for sandbox {target_id}: "
                "disabling no-new-privileges requested"
            )
            raise SecurityPolicyViolationError(
                "Disabling no-new-privileges security option is strictly forbidden.",
                details={"violation": "no_new_privileges_disabled"},
            )

        if req_policy.image is not None and req_policy.image.strip() != self.config.BASE_IMAGE:
            logger.warning(
                f"Security policy rejection for sandbox {target_id}: "
                f"arbitrary image '{req_policy.image}' requested"
            )
            raise SecurityPolicyViolationError(
                f"Arbitrary image selection '{req_policy.image}' is forbidden. "
                f"Approved image: '{self.config.BASE_IMAGE}'.",
                details={
                    "violation": "arbitrary_image_forbidden",
                    "requested_image": req_policy.image,
                },
            )

        if req_policy.cap_drop is not None and "ALL" not in req_policy.cap_drop:
            logger.warning(
                f"Security policy rejection for sandbox {target_id}: cap_drop without ALL requested"
            )
            raise SecurityPolicyViolationError(
                "Weakening Linux capability dropping (must contain 'ALL') is strictly forbidden.",
                details={"violation": "cap_drop_weakened"},
            )

        effective_runtime = "python"
        if req_policy.runtime is not None:
            clean_runtime = req_policy.runtime.strip().lower()
            if clean_runtime not in self.config.ALLOWED_RUNTIMES:
                allowed_list = list(self.config.ALLOWED_RUNTIMES.keys())
                raise SecurityPolicyViolationError(
                    f"Unsupported runtime '{req_policy.runtime}'. "
                    f"Allowed runtimes: {allowed_list}.",
                    details={"violation": "unsupported_runtime", "runtime": req_policy.runtime},
                )
            effective_runtime = clean_runtime

        approved_image = self.config.ALLOWED_RUNTIMES[effective_runtime]

        # 3. Resource Bounds & Safe Clamping
        clamped_fields: list[str] = []

        # Timeout clamping: [0.5, platform TIMEOUT_SECONDS]
        effective_timeout = self.config.TIMEOUT_SECONDS
        if req_policy.timeout_seconds is not None:
            if req_policy.timeout_seconds > self.config.TIMEOUT_SECONDS:
                effective_timeout = self.config.TIMEOUT_SECONDS
                clamped_fields.append("timeout_seconds")
            elif req_policy.timeout_seconds < 0.5:
                effective_timeout = 0.5
                clamped_fields.append("timeout_seconds")
            else:
                effective_timeout = req_policy.timeout_seconds

        # Memory limit clamping: cannot exceed platform MEMORY_LIMIT
        effective_memory = self.config.MEMORY_LIMIT
        platform_mem_bytes = _parse_memory_bytes(self.config.MEMORY_LIMIT)
        if req_policy.memory_limit is not None:
            try:
                requested_mem_bytes = _parse_memory_bytes(req_policy.memory_limit)
                if requested_mem_bytes > platform_mem_bytes:
                    effective_memory = self.config.MEMORY_LIMIT
                    clamped_fields.append("memory_limit")
                else:
                    effective_memory = req_policy.memory_limit
            except Exception:
                effective_memory = self.config.MEMORY_LIMIT
                clamped_fields.append("memory_limit")

        # CPU limit clamping: [0.1, platform CPU_LIMIT]
        effective_cpu = self.config.CPU_LIMIT
        if req_policy.cpu_limit is not None:
            if req_policy.cpu_limit > self.config.CPU_LIMIT:
                effective_cpu = self.config.CPU_LIMIT
                clamped_fields.append("cpu_limit")
            elif req_policy.cpu_limit < 0.1:
                effective_cpu = 0.1
                clamped_fields.append("cpu_limit")
            else:
                effective_cpu = req_policy.cpu_limit
        nano_cpus = int(effective_cpu * 1_000_000_000)

        # PID limit clamping: [8, platform PIDS_LIMIT]
        effective_pids = self.config.PIDS_LIMIT
        if req_policy.pids_limit is not None:
            if req_policy.pids_limit > self.config.PIDS_LIMIT:
                effective_pids = self.config.PIDS_LIMIT
                clamped_fields.append("pids_limit")
            elif req_policy.pids_limit < 8:
                effective_pids = 8
                clamped_fields.append("pids_limit")
            else:
                effective_pids = req_policy.pids_limit

        # Output bounds: cannot exceed platform limits
        effective_stdout_bytes = self.config.MAX_STDOUT_BYTES
        if req_policy.max_stdout_bytes is not None:
            effective_stdout_bytes = min(
                req_policy.max_stdout_bytes, self.config.MAX_STDOUT_BYTES
            )
            if effective_stdout_bytes != req_policy.max_stdout_bytes:
                clamped_fields.append("max_stdout_bytes")

        effective_stderr_bytes = self.config.MAX_STDERR_BYTES
        if req_policy.max_stderr_bytes is not None:
            effective_stderr_bytes = min(
                req_policy.max_stderr_bytes, self.config.MAX_STDERR_BYTES
            )
            if effective_stderr_bytes != req_policy.max_stderr_bytes:
                clamped_fields.append("max_stderr_bytes")

        # 4. Construct Immutable Effective Policy
        effective_policy = EffectiveSandboxPolicy(
            runtime=effective_runtime,
            image=approved_image,
            timeout_seconds=effective_timeout,
            memory_limit=effective_memory,
            memswap_limit=effective_memory,  # memory == swap disables swap escape
            nano_cpus=nano_cpus,
            pids_limit=effective_pids,
            max_stdout_bytes=effective_stdout_bytes,
            max_stderr_bytes=effective_stderr_bytes,
            network_mode="none",
            privileged=False,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            user="10001:10001",
            read_only=True,
            tmpfs={"/tmp": f"size={self.config.TMPFS_SIZE},noexec,nosuid,nodev"},
            volumes={},
            environment={
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUNBUFFERED": "1",
            },
            project_label=self.config.PROJECT_LABEL,
            managed_by_label=self.config.MANAGED_BY_LABEL,
        )

        # 5. Generate Audit Record
        decision = "clamped" if clamped_fields else "allowed"
        audit = SecurityAuditRecord(
            sandbox_id=target_id,
            decision=decision,
            clamped_fields=clamped_fields,
            violations=[],
            requested_summary=req_policy.model_dump(exclude_none=True),
            effective_summary={
                "runtime": effective_policy.runtime,
                "timeout_seconds": effective_policy.timeout_seconds,
                "memory_limit": effective_policy.memory_limit,
                "nano_cpus": effective_policy.nano_cpus,
                "pids_limit": effective_policy.pids_limit,
                "network_mode": effective_policy.network_mode,
                "privileged": effective_policy.privileged,
                "read_only": effective_policy.read_only,
                "user": effective_policy.user,
            },
        )

        logger.info(
            f"Security policy decision={decision} for sandbox {target_id}: "
            f"clamped_fields={clamped_fields}"
        )

        return effective_policy, audit
