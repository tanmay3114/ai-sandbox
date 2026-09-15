"""Comprehensive security policy and enforcement tests for Phase 5.

Verifies:
1. Rejection of forbidden capabilities (privileged, networking, mounts, socket, root, etc.).
2. Rejection of unknown policy fields (extra='forbid').
3. Clamping of resource bounds (CPU, memory, PIDs, timeout, output) including NaN/Inf/malformed.
4. Deep immutability of EffectiveSandboxPolicy (top-level and nested collections).
5. Unconditional rejection happens BEFORE Docker container creation (zero container leaks).
6. Docker container parameters strictly enforce all platform security invariants.
7. REST API HTTP 400 error translation.
8. Agent tool and MCP error translation without leaking tracebacks.
9. Audit records are strictly sanitized (zero secrets, credentials, or paths).
"""

import math
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agent.schemas import AgentToolError
from app.agent.tools import execute_agent_tool
from app.core.config import SandboxSettings, settings
from app.core.exceptions import SecurityPolicyViolationError
from app.main import app
from app.mcp.tools import _format_mcp_error
from app.models.sandbox import SandboxStatus
from app.sandbox.engine import EphemeralSandboxEngine
from app.sandbox.schemas import ExecutionRequest, ExecutionStatus
from app.sandbox.security import build_container_parameters
from app.security.engine import SecurityPolicyEngine
from app.security.policy import RequestedPolicy, SecurityAuditRecord
from app.services.sandbox_lifecycle_service import SandboxLifecycleService

# =====================================================================
# 1. Security Invariants & Rejection of Forbidden Capabilities
# =====================================================================

def test_reject_privileged_execution():
    """Privileged container execution MUST be unconditionally rejected."""
    engine = SecurityPolicyEngine()
    req = RequestedPolicy(privileged=True)
    with pytest.raises(SecurityPolicyViolationError) as exc_info:
        engine.evaluate(req)
    assert "privileged" in exc_info.value.message.lower()
    assert exc_info.value.details.get("violation") == "privileged_execution_forbidden"


@pytest.mark.parametrize("bad_network", ["bridge", "host", "container:foo", "custom_net"])
def test_reject_network_mode_not_none(bad_network: str):
    """Any network mode other than 'none' MUST be unconditionally rejected."""
    engine = SecurityPolicyEngine()
    req = RequestedPolicy(network_mode=bad_network)
    with pytest.raises(SecurityPolicyViolationError) as exc_info:
        engine.evaluate(req)
    assert "network" in exc_info.value.message.lower()
    assert exc_info.value.details.get("violation") == "network_access_forbidden"


def test_reject_volume_and_host_mounts():
    """Host filesystem and volume mounts MUST be unconditionally rejected."""
    engine = SecurityPolicyEngine()
    req = RequestedPolicy(volumes={"/etc": {"bind": "/host_etc", "mode": "ro"}})
    with pytest.raises(SecurityPolicyViolationError) as exc_info:
        engine.evaluate(req)
    assert "mount" in exc_info.value.message.lower() or "volume" in exc_info.value.message.lower()
    assert exc_info.value.details.get("violation") == "host_mounts_forbidden"


def test_reject_docker_socket_mount():
    """Docker socket mount attempts MUST be unconditionally rejected."""
    engine = SecurityPolicyEngine()
    req = RequestedPolicy(volumes={"/var/run/docker.sock": {"bind": "/docker.sock", "mode": "rw"}})
    with pytest.raises(SecurityPolicyViolationError) as exc_info:
        engine.evaluate(req)
    assert exc_info.value.details.get("violation") == "host_mounts_forbidden"


@pytest.mark.parametrize("caps", [["SYS_ADMIN"], ["NET_ADMIN", "SYS_PTRACE"], ["ALL"]])
def test_reject_capability_additions(caps: list[str]):
    """Adding Linux capabilities MUST be unconditionally rejected."""
    engine = SecurityPolicyEngine()
    req = RequestedPolicy(cap_add=caps)
    with pytest.raises(SecurityPolicyViolationError) as exc_info:
        engine.evaluate(req)
    assert "capabilit" in exc_info.value.message.lower()
    assert exc_info.value.details.get("violation") == "capability_addition_forbidden"


@pytest.mark.parametrize("bad_user", ["root", "0", "0:0", "1000:1000", "daemon"])
def test_reject_root_or_arbitrary_user_override(bad_user: str):
    """Overriding execution user away from UID 10001 MUST be rejected."""
    engine = SecurityPolicyEngine()
    req = RequestedPolicy(user=bad_user)
    with pytest.raises(SecurityPolicyViolationError) as exc_info:
        engine.evaluate(req)
    assert "user" in exc_info.value.message.lower()
    assert exc_info.value.details.get("violation") == "user_override_forbidden"


def test_reject_writable_root_filesystem():
    """Disabling read-only root filesystem MUST be rejected."""
    engine = SecurityPolicyEngine()
    req = RequestedPolicy(read_only=False)
    with pytest.raises(SecurityPolicyViolationError) as exc_info:
        engine.evaluate(req)
    assert "read-only" in exc_info.value.message.lower()
    assert exc_info.value.details.get("violation") == "writable_root_forbidden"


def test_reject_disabling_no_new_privileges():
    """Disabling no-new-privileges security option MUST be rejected."""
    engine = SecurityPolicyEngine()
    req = RequestedPolicy(security_opt=["no-new-privileges:false"])
    with pytest.raises(SecurityPolicyViolationError) as exc_info:
        engine.evaluate(req)
    assert "no-new-privileges" in exc_info.value.message.lower()
    assert exc_info.value.details.get("violation") == "no_new_privileges_disabled"


@pytest.mark.parametrize("bad_image", ["ubuntu:latest", "alpine:3.18", "python:3.11", "busybox"])
def test_reject_arbitrary_docker_images(bad_image: str):
    """Arbitrary Docker image requests MUST be rejected."""
    engine = SecurityPolicyEngine()
    req = RequestedPolicy(image=bad_image)
    with pytest.raises(SecurityPolicyViolationError) as exc_info:
        engine.evaluate(req)
    assert "image" in exc_info.value.message.lower()
    assert exc_info.value.details.get("violation") == "arbitrary_image_forbidden"


def test_reject_weakening_cap_drop():
    """Weakening cap_drop away from 'ALL' MUST be rejected."""
    engine = SecurityPolicyEngine()
    req = RequestedPolicy(cap_drop=["SYS_PTRACE"])  # Missing "ALL"
    with pytest.raises(SecurityPolicyViolationError) as exc_info:
        engine.evaluate(req)
    assert "cap_drop" in exc_info.value.details.get("violation", "")


def test_reject_unsupported_runtime():
    """Requesting an unsupported runtime MUST be rejected."""
    engine = SecurityPolicyEngine()
    req = RequestedPolicy(runtime="ruby")
    with pytest.raises(SecurityPolicyViolationError) as exc_info:
        engine.evaluate(req)
    assert "runtime" in exc_info.value.message.lower()


def test_reject_unknown_policy_fields():
    """Unknown policy fields must be explicitly rejected (extra='forbid')."""
    # 1. Pydantic direct instantiation rejects extra fields
    with pytest.raises(ValidationError):
        RequestedPolicy.model_validate({"unknown_security_override": True})

    # 2. SecurityPolicyEngine.evaluate rejects dictionary with unknown fields
    engine = SecurityPolicyEngine()
    with pytest.raises(SecurityPolicyViolationError) as exc_info:
        engine.evaluate({"unknown_injected_field": "exploit"})
    assert exc_info.value.details.get("violation") == "invalid_policy_specification"


# =====================================================================
# 2. Resource Bounds & Safe Clamping (Including NaN / Inf / Malformed)
# =====================================================================

def test_clamping_excessive_timeout():
    """Timeouts exceeding platform limits are safely clamped."""
    cfg = SandboxSettings(TIMEOUT_SECONDS=5.0)
    engine = SecurityPolicyEngine(config=cfg)
    req = RequestedPolicy(timeout_seconds=300.0)
    effective, audit = engine.evaluate(req)

    assert effective.timeout_seconds == 5.0
    assert "timeout_seconds" in audit.clamped_fields
    assert audit.decision == "clamped"


def test_clamping_below_minimum_timeout():
    """Timeouts below the safe minimum (0.5s) are clamped upward."""
    cfg = SandboxSettings(TIMEOUT_SECONDS=10.0)
    engine = SecurityPolicyEngine(config=cfg)
    req = RequestedPolicy(timeout_seconds=0.01)
    effective, audit = engine.evaluate(req)

    assert effective.timeout_seconds == 0.5
    assert "timeout_seconds" in audit.clamped_fields


@pytest.mark.parametrize("bad_val", [float("nan"), float("inf"), float("-inf"), -5.0, 0.0])
def test_clamping_non_finite_or_negative_timeout(bad_val: float):
    """Non-finite or negative timeouts safely clamp to platform defaults."""
    cfg = SandboxSettings(TIMEOUT_SECONDS=5.0)
    engine = SecurityPolicyEngine(config=cfg)
    req = RequestedPolicy(timeout_seconds=bad_val)
    effective, audit = engine.evaluate(req)

    assert math.isfinite(effective.timeout_seconds)
    assert effective.timeout_seconds == 5.0
    assert "timeout_seconds" in audit.clamped_fields


def test_clamping_excessive_memory():
    """Memory requests exceeding platform limits are safely clamped."""
    cfg = SandboxSettings(MEMORY_LIMIT="256m")
    engine = SecurityPolicyEngine(config=cfg)
    req = RequestedPolicy(memory_limit="2g")
    effective, audit = engine.evaluate(req)

    assert effective.memory_limit == "256m"
    assert "memory_limit" in audit.clamped_fields
    assert audit.decision == "clamped"


def test_permissible_lower_memory():
    """Memory requests within platform limits are honored."""
    cfg = SandboxSettings(MEMORY_LIMIT="256m")
    engine = SecurityPolicyEngine(config=cfg)
    req = RequestedPolicy(memory_limit="128m")
    effective, audit = engine.evaluate(req)

    assert effective.memory_limit == "128m"
    assert "memory_limit" not in audit.clamped_fields


@pytest.mark.parametrize("malformed_mem", ["invalid_string", "-100m", "0m", "1k"])
def test_clamping_malformed_or_subminimal_memory(malformed_mem: str):
    """Malformed or dangerously small memory strings clamp to platform default."""
    cfg = SandboxSettings(MEMORY_LIMIT="256m")
    engine = SecurityPolicyEngine(config=cfg)
    req = RequestedPolicy(memory_limit=malformed_mem)
    effective, audit = engine.evaluate(req)

    assert effective.memory_limit == "256m"
    assert "memory_limit" in audit.clamped_fields


def test_clamping_excessive_cpu():
    """CPU requests exceeding platform limits are safely clamped."""
    cfg = SandboxSettings(CPU_LIMIT=0.5)
    engine = SecurityPolicyEngine(config=cfg)
    req = RequestedPolicy(cpu_limit=4.0)
    effective, audit = engine.evaluate(req)

    assert effective.nano_cpus == 500_000_000
    assert "cpu_limit" in audit.clamped_fields


def test_clamping_below_minimum_cpu():
    """CPU requests below 0.1 are clamped to 0.1."""
    cfg = SandboxSettings(CPU_LIMIT=0.5)
    engine = SecurityPolicyEngine(config=cfg)
    req = RequestedPolicy(cpu_limit=0.01)
    effective, audit = engine.evaluate(req)

    assert effective.nano_cpus == 100_000_000
    assert "cpu_limit" in audit.clamped_fields


@pytest.mark.parametrize("bad_val", [float("nan"), float("inf"), float("-inf"), -1.0, 0.0])
def test_clamping_non_finite_or_negative_cpu(bad_val: float):
    """Non-finite or non-positive CPU requests clamp safely and compute valid nano_cpus."""
    cfg = SandboxSettings(CPU_LIMIT=0.5)
    engine = SecurityPolicyEngine(config=cfg)
    req = RequestedPolicy(cpu_limit=bad_val)
    effective, audit = engine.evaluate(req)

    assert effective.nano_cpus == 500_000_000
    assert "cpu_limit" in audit.clamped_fields


def test_clamping_excessive_pids():
    """PID requests exceeding platform limits are safely clamped."""
    cfg = SandboxSettings(PIDS_LIMIT=32)
    engine = SecurityPolicyEngine(config=cfg)
    req = RequestedPolicy(pids_limit=1024)
    effective, audit = engine.evaluate(req)

    assert effective.pids_limit == 32
    assert "pids_limit" in audit.clamped_fields


def test_clamping_below_minimum_pids():
    """PID requests below minimum (8) are clamped to 8."""
    cfg = SandboxSettings(PIDS_LIMIT=32)
    engine = SecurityPolicyEngine(config=cfg)
    req = RequestedPolicy(pids_limit=2)
    effective, audit = engine.evaluate(req)

    assert effective.pids_limit == 8
    assert "pids_limit" in audit.clamped_fields


def test_clamping_excessive_stdout_bytes():
    """Output limits exceeding platform limits are clamped."""
    cfg = SandboxSettings(MAX_STDOUT_BYTES=65536)
    engine = SecurityPolicyEngine(config=cfg)
    req = RequestedPolicy(max_stdout_bytes=10_000_000)
    effective, audit = engine.evaluate(req)

    assert effective.max_stdout_bytes == 65536
    assert "max_stdout_bytes" in audit.clamped_fields


def test_clamping_excessive_stderr_bytes():
    """Stderr limits exceeding platform limits are clamped."""
    cfg = SandboxSettings(MAX_STDERR_BYTES=65536)
    engine = SecurityPolicyEngine(config=cfg)
    req = RequestedPolicy(max_stderr_bytes=10_000_000)
    effective, audit = engine.evaluate(req)

    assert effective.max_stderr_bytes == 65536
    assert "max_stderr_bytes" in audit.clamped_fields


# =====================================================================
# 3. Deep Immutability of EffectiveSandboxPolicy
# =====================================================================

def test_effective_policy_top_level_immutability():
    """EffectiveSandboxPolicy rejects attribute reassignment."""
    engine = SecurityPolicyEngine()
    policy = engine.get_default_policy()
    with pytest.raises(ValidationError):
        policy.privileged = True


def test_effective_policy_nested_immutability():
    """Nested policy collections (cap_drop, security_opt, tmpfs, volumes, environment)
    cannot be mutated in-place to weaken isolation.
    """
    engine = SecurityPolicyEngine()
    policy = engine.get_default_policy()

    # 1. cap_drop is an immutable tuple
    with pytest.raises(AttributeError):
        policy.cap_drop.append("SYS_ADMIN")  # type: ignore

    # 2. security_opt is an immutable tuple
    with pytest.raises(AttributeError):
        policy.security_opt.remove("no-new-privileges:true")  # type: ignore

    # 3. tmpfs is an immutable FrozenDict
    with pytest.raises(TypeError):
        policy.tmpfs["/tmp"] = "rw"

    # 4. volumes is an immutable FrozenDict
    with pytest.raises(TypeError):
        policy.volumes["/var/run/docker.sock"] = {"bind": "/sock"}

    # 5. environment is an immutable FrozenDict
    with pytest.raises(TypeError):
        policy.environment["MALICIOUS"] = "1"


# =====================================================================
# 4. Docker Container Parameters & Pre-Docker Rejection Verification
# =====================================================================

@pytest.mark.parametrize(
    "bad_policy",
    [
        RequestedPolicy(privileged=True),
        RequestedPolicy(network_mode="bridge"),
        RequestedPolicy(volumes={"/etc": {"bind": "/host_etc"}}),
        RequestedPolicy(image="ubuntu:latest"),
    ],
)
def test_policy_rejection_happens_before_docker(bad_policy: RequestedPolicy):
    """Unsafe policy requests MUST be rejected BEFORE invoking Docker containers.run."""
    mock_docker_client = MagicMock()
    mock_docker_client.containers.run = MagicMock()

    engine = EphemeralSandboxEngine(client=mock_docker_client)

    with pytest.raises(SecurityPolicyViolationError):
        engine.execute("print('attack')", requested_policy=bad_policy)

    # Verify Docker was NEVER called and no container was created
    mock_docker_client.containers.run.assert_not_called()


def test_docker_parameter_construction_preserves_security_invariants():
    """Container parameters passed to Docker MUST strictly reflect EffectiveSandboxPolicy."""
    engine = SecurityPolicyEngine()
    policy = engine.get_default_policy()
    params = build_container_parameters(
        code="print('verified')",
        sandbox_id="sec-param-test",
        config=settings,
        policy=policy,
    )

    # 1. Non-negotiable security flags
    assert params["network_mode"] == "none", "Docker network_mode must be 'none'"
    assert params["privileged"] is False, "Docker privileged mode must be False"
    assert "ALL" in params["cap_drop"], "ALL Linux capabilities must be dropped"
    assert "no-new-privileges:true" in params["security_opt"], "no-new-privileges must be enabled"
    assert params["user"] == "10001:10001", "Execution user must be non-root 10001:10001"
    assert params["read_only"] is True, "Root filesystem must be read-only"
    assert params["volumes"] == {}, "Volumes must be strictly empty"

    # 2. Restricted /tmp tmpfs
    assert "/tmp" in params["tmpfs"]
    assert "noexec" in params["tmpfs"]["/tmp"]
    assert "nosuid" in params["tmpfs"]["/tmp"]
    assert "nodev" in params["tmpfs"]["/tmp"]

    # 3. Resource limits
    assert params["mem_limit"] == settings.MEMORY_LIMIT
    assert params["nano_cpus"] == settings.nano_cpus
    assert params["pids_limit"] == settings.PIDS_LIMIT


# =====================================================================
# 5. Security Audit Record Sanitization
# =====================================================================

def test_audit_record_sanitized_zero_secrets_or_paths():
    """Audit records must contain strictly safe metadata and NO sensitive paths/secrets."""
    engine = SecurityPolicyEngine()
    req = RequestedPolicy(timeout_seconds=999.0, memory_limit="128m")
    effective, audit = engine.evaluate(req, sandbox_id="audit-sanitization-test")

    assert isinstance(audit, SecurityAuditRecord)
    assert audit.sandbox_id == "audit-sanitization-test"
    assert audit.decision == "clamped"
    assert "timeout_seconds" in audit.clamped_fields

    # Safe summary verification
    assert "timeout_seconds" in audit.requested_summary
    assert "memory_limit" in audit.requested_summary
    assert "volumes" not in audit.requested_summary
    assert "environment" not in audit.requested_summary

    # Effective summary verification
    assert audit.effective_summary["network_mode"] == "none"
    assert audit.effective_summary["privileged"] is False
    assert audit.effective_summary["user"] == "10001:10001"
    assert audit.effective_summary["read_only"] is True


# =====================================================================
# 6. EphemeralSandboxEngine Execution Integration
# =====================================================================

def test_engine_rejects_unsafe_requested_policy(engine: EphemeralSandboxEngine):
    """EphemeralSandboxEngine.execute must reject unsafe policies before container creation."""
    unsafe_policy = RequestedPolicy(privileged=True)
    with pytest.raises(SecurityPolicyViolationError):
        engine.execute("print('attack')", requested_policy=unsafe_policy)


def test_engine_executes_with_audit_record(engine: EphemeralSandboxEngine):
    """Successful executions must contain an audit record in the result."""
    result = engine.execute("print('secure run')")
    assert result.status == ExecutionStatus.COMPLETED
    assert result.audit is not None
    assert result.audit.decision == "allowed"
    assert result.audit.effective_summary["network_mode"] == "none"
    assert result.audit.effective_summary["privileged"] is False


def test_engine_execution_request_schema_enforcement(engine: EphemeralSandboxEngine):
    """ExecutionRequest payload is validated and subject to policy evaluation."""
    req = ExecutionRequest(code="print('schema test')", timeout_seconds=1.5)
    result = engine.execute(req)
    assert result.status == ExecutionStatus.COMPLETED
    assert result.audit is not None


# =====================================================================
# 7. REST API Security Error Handling
# =====================================================================

def test_api_rejection_returns_http_400():
    """SecurityPolicyViolationError translates to HTTP 400 with structured JSON."""
    client = TestClient(app)
    with patch(
        "app.sandbox.engine.SecurityPolicyEngine.evaluate",
        side_effect=SecurityPolicyViolationError(
            "Privileged container execution is strictly forbidden by platform policy.",
            details={"violation": "privileged_execution_forbidden"},
        ),
    ):
        resp = client.post("/api/v1/sandboxes/execute", json={"code": "print(1)"})
        assert resp.status_code == 400
        data = resp.json()
        assert data["error"] == "SecurityPolicyViolationError"
        assert "privileged" in data["message"].lower()
        assert data["details"]["violation"] == "privileged_execution_forbidden"


# =====================================================================
# 8. Agent Tool & MCP Error Translation
# =====================================================================

@pytest.mark.asyncio
async def test_agent_tool_error_translation(db_session):
    """Agent tool layer converts exceptions into structured AgentToolError
    without leaking tracebacks.
    """
    service = SandboxLifecycleService(db_session)
    sandbox = service.create_sandbox()

    # 1. Invalid tool name -> InvalidToolName
    res = await execute_agent_tool("malicious_tool", {}, service)
    assert isinstance(res, AgentToolError)
    assert res.error == "InvalidToolName"

    # 2. Non-existent sandbox UUID -> SandboxNotFoundError
    non_existent_id = str(uuid.uuid4())
    res = await execute_agent_tool(
        "execute_code",
        {"sandbox_id": non_existent_id, "code": "print(1)"},
        service,
    )
    assert isinstance(res, AgentToolError)
    assert res.error == "SandboxNotFoundError"

    # 3. SecurityPolicyViolationError during tool execution
    with patch.object(
        service.engine.policy_engine,
        "evaluate",
        side_effect=SecurityPolicyViolationError(
            "Privileged container execution is strictly forbidden.",
            details={"violation": "privileged_execution_forbidden"},
        ),
    ):
        res = await execute_agent_tool(
            "execute_code",
            {"sandbox_id": str(sandbox.id), "code": "print(1)"},
            service,
        )
        assert isinstance(res, AgentToolError)
        assert res.error == "SecurityPolicyViolationError"
        assert "privileged" in res.message.lower()
        assert res.details.get("violation") == "privileged_execution_forbidden"

    # Clean up sandbox
    service.delete_sandbox(sandbox.id)
    assert service.get_sandbox(sandbox.id).status == SandboxStatus.DESTROYED


def test_mcp_format_security_policy_violation():
    """MCP format helper cleanly formats SecurityPolicyViolationError for MCP protocol."""
    exc = SecurityPolicyViolationError(
        "Host filesystem and volume mounts are strictly forbidden by platform policy.",
        details={"violation": "host_mounts_forbidden"},
    )
    mcp_err = _format_mcp_error(exc)
    assert mcp_err["error"] == "SecurityPolicyViolationError"
    assert "mount" in mcp_err["message"].lower()
    assert mcp_err["details"]["violation"] == "host_mounts_forbidden"
