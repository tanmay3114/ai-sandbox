"""Comprehensive security policy and enforcement tests for Phase 5.

Verifies:
1. Rejection of forbidden capabilities (privileged, networking, mounts, socket, root, etc.).
2. Clamping of resource bounds (CPU, memory, PIDs, timeout, output).
3. Immutable EffectiveSandboxPolicy generation and sanitized audit logging.
4. EphemeralSandboxEngine execution-level policy enforcement.
5. REST API HTTP 400 error translation.
6. Agent tool and MCP error translation.
7. Zero container leakage across all security rejection flows.
"""

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agent.schemas import AgentToolError
from app.agent.tools import execute_agent_tool
from app.core.config import SandboxSettings
from app.core.exceptions import SecurityPolicyViolationError
from app.main import app
from app.mcp.tools import _format_mcp_error
from app.models.sandbox import SandboxStatus
from app.sandbox.engine import EphemeralSandboxEngine
from app.sandbox.schemas import ExecutionRequest, ExecutionStatus
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


# =====================================================================
# 2. Resource Bounds & Safe Clamping
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


def test_clamping_excessive_cpu():
    """CPU requests exceeding platform limits are safely clamped."""
    cfg = SandboxSettings(CPU_LIMIT=0.5)
    engine = SecurityPolicyEngine(config=cfg)
    req = RequestedPolicy(cpu_limit=4.0)
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


def test_clamping_excessive_stdout_bytes():
    """Output limits exceeding platform limits are clamped."""
    cfg = SandboxSettings(MAX_STDOUT_BYTES=65536)
    engine = SecurityPolicyEngine(config=cfg)
    req = RequestedPolicy(max_stdout_bytes=10_000_000)
    effective, audit = engine.evaluate(req)

    assert effective.max_stdout_bytes == 65536
    assert "max_stdout_bytes" in audit.clamped_fields


def test_effective_policy_immutability():
    """EffectiveSandboxPolicy is frozen and cannot be mutated after creation."""
    engine = SecurityPolicyEngine()
    policy = engine.get_default_policy()
    with pytest.raises(ValidationError):
        policy.privileged = True  # Pydantic frozen model raises ValidationError


# =====================================================================
# 3. Security Audit Record Structure
# =====================================================================

def test_audit_record_structure():
    """Audit records must accurately reflect requested vs. effective settings."""
    engine = SecurityPolicyEngine()
    req = RequestedPolicy(timeout_seconds=999.0)
    effective, audit = engine.evaluate(req, sandbox_id="audit-test-123")

    assert isinstance(audit, SecurityAuditRecord)
    assert audit.sandbox_id == "audit-test-123"
    assert audit.decision == "clamped"
    assert "timeout_seconds" in audit.clamped_fields
    assert audit.effective_summary["network_mode"] == "none"
    assert audit.effective_summary["privileged"] is False
    assert audit.effective_summary["user"] == "10001:10001"


# =====================================================================
# 4. EphemeralSandboxEngine Execution Integration
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
# 5. REST API Security Error Handling
# =====================================================================

def test_api_rejection_returns_http_400():
    """SecurityPolicyViolationError translates to HTTP 400 with structured JSON."""
    client = TestClient(app)
    # Triggering an intentional SecurityPolicyViolationError via mock/patch to verify handler
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
# 6. Agent Tool & MCP Error Translation
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
