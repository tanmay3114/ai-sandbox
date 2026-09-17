"""Integration tests for the Security Policy API endpoints."""

from fastapi.testclient import TestClient

from app.main import app


def test_get_security_policy():
    """GET /api/v1/security/policy returns authoritative platform policy."""
    client = TestClient(app)
    response = client.get("/api/v1/security/policy")
    assert response.status_code == 200
    data = response.json()

    assert data["engine"] == "SecurityPolicyEngine (Phase 5)"
    assert data["enforcement"] == "authoritative"

    # Verify invariants
    invariants = data["invariants"]
    assert invariants["network_mode"] == "none"
    assert invariants["read_only_rootfs"] is True
    assert invariants["user"] == "10001:10001"
    assert invariants["cap_drop"] == ["ALL"]
    assert invariants["security_opt"] == ["no-new-privileges:true"]
    assert invariants["allow_host_mounts"] is False
    assert invariants["allow_docker_socket"] is False
    assert invariants["allow_privileged"] is False
    assert invariants["allow_arbitrary_images"] is False

    # Verify resource limits
    limits = data["resource_limits"]
    assert limits["memory_limit"] == "256m"
    assert limits["cpu_limit"] == 0.5
    assert limits["pids_limit"] == 32
    assert limits["timeout_seconds"] == 5.0

    # Verify runtime
    runtime = data["runtime"]
    assert runtime["default_runtime"] == "python"
    assert "python" in runtime["allowed_runtimes"]


def test_evaluate_safe_policy_allowed():
    """POST /api/v1/security/evaluate with safe parameters returns allowed status."""
    client = TestClient(app)
    payload = {
        "runtime": "python",
        "timeout_seconds": 3.0,
        "memory_limit": "128m",
        "cpu_limit": 0.4,
        "pids_limit": 20,
    }
    response = client.post("/api/v1/security/evaluate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "allowed"
    assert data["audit"]["decision"] == "allowed"
    assert data["audit"]["clamped_fields"] == []
    assert data["effective"]["timeout_seconds"] == 3.0
    assert data["effective"]["memory_limit"] == "128m"


def test_evaluate_excessive_policy_clamped():
    """POST /api/v1/security/evaluate with excessive resources clamps to platform limits."""
    client = TestClient(app)
    payload = {
        "timeout_seconds": 60.0,
        "memory_limit": "1024m",
        "cpu_limit": 2.0,
        "pids_limit": 100,
    }
    response = client.post("/api/v1/security/evaluate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "clamped"
    assert data["audit"]["decision"] == "clamped"
    assert "timeout_seconds" in data["audit"]["clamped_fields"]
    assert "memory_limit" in data["audit"]["clamped_fields"]
    assert "cpu_limit" in data["audit"]["clamped_fields"]
    assert "pids_limit" in data["audit"]["clamped_fields"]
    # Effective values are bounded to platform limits
    assert data["effective"]["timeout_seconds"] == 5.0
    assert data["effective"]["memory_limit"] == "256m"


def test_evaluate_privileged_rejected():
    """POST /api/v1/security/evaluate with privileged=True raises HTTP 400."""
    client = TestClient(app)
    payload = {"privileged": True}
    response = client.post("/api/v1/security/evaluate", json=payload)
    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "SecurityPolicyViolationError"
    assert "privileged" in data["message"].lower()
    assert data["details"]["violation"] == "privileged_execution_forbidden"


def test_evaluate_network_mode_rejected():
    """POST /api/v1/security/evaluate with network_mode='bridge' raises HTTP 400."""
    client = TestClient(app)
    payload = {"network_mode": "bridge"}
    response = client.post("/api/v1/security/evaluate", json=payload)
    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "SecurityPolicyViolationError"
    assert "network" in data["message"].lower()
    assert data["details"]["violation"] == "network_access_forbidden"


def test_evaluate_host_mounts_rejected():
    """POST /api/v1/security/evaluate with volumes raises HTTP 400."""
    client = TestClient(app)
    payload = {"volumes": {"/etc": {"bind": "/host_etc"}}}
    response = client.post("/api/v1/security/evaluate", json=payload)
    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "SecurityPolicyViolationError"
    assert "mount" in data["message"].lower() or "volume" in data["message"].lower()
    assert data["details"]["violation"] == "host_mounts_forbidden"


def test_evaluate_arbitrary_image_rejected():
    """POST /api/v1/security/evaluate with arbitrary image raises HTTP 400."""
    client = TestClient(app)
    payload = {"image": "alpine:latest"}
    response = client.post("/api/v1/security/evaluate", json=payload)
    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "SecurityPolicyViolationError"
    assert "image" in data["message"].lower()
    assert data["details"]["violation"] == "arbitrary_image_forbidden"
