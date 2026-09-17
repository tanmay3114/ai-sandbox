"""Integration tests for Sandbox Lifecycle API endpoints."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient fixture."""
    return TestClient(app)


def test_api_create_sandbox(client: TestClient):
    """Test POST /api/v1/sandboxes creates a new persistent sandbox session."""
    payload = {"runtime": "python", "ttl_seconds": 180}
    response = client.post("/api/v1/sandboxes", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert "sandbox_id" in data
    assert data["status"] == "running"
    assert data["runtime"] == "python"
    assert "created_at" in data
    assert "expires_at" in data
    assert data["destroyed_at"] is None


def test_api_create_sandbox_invalid_runtime(client: TestClient):
    """Test validation failure on unsupported runtime."""
    payload = {"runtime": "unsupported_ruby", "ttl_seconds": 180}
    response = client.post("/api/v1/sandboxes", json=payload)
    assert response.status_code == 422


def test_api_create_sandbox_invalid_ttl(client: TestClient):
    """Test validation failure on out-of-bounds TTL."""
    payload = {"runtime": "python", "ttl_seconds": 1}
    response = client.post("/api/v1/sandboxes", json=payload)
    assert response.status_code == 422


def test_api_get_sandbox(client: TestClient):
    """Test GET /api/v1/sandboxes/{sandbox_id}."""
    create_resp = client.post("/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 180})
    sandbox_id = create_resp.json()["sandbox_id"]

    get_resp = client.get(f"/api/v1/sandboxes/{sandbox_id}")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["sandbox_id"] == sandbox_id
    assert data["status"] == "running"
    assert "resource_config" in data
    assert data["executions_count"] == 0


def test_api_get_sandbox_not_found(client: TestClient):
    """Test GET on unknown sandbox ID returns 404."""
    random_id = uuid.uuid4()
    response = client.get(f"/api/v1/sandboxes/{random_id}")
    assert response.status_code == 404
    data = response.json()
    assert data["error"] == "SandboxNotFoundError"


def test_api_delete_sandbox_idempotent(client: TestClient):
    """Test DELETE /api/v1/sandboxes/{sandbox_id} terminates and destroys session."""
    create_resp = client.post("/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 180})
    sandbox_id = create_resp.json()["sandbox_id"]

    del_resp1 = client.delete(f"/api/v1/sandboxes/{sandbox_id}")
    assert del_resp1.status_code == 200
    assert del_resp1.json()["status"] == "destroyed"

    # Repeated deletion should be idempotent and return 200
    del_resp2 = client.delete(f"/api/v1/sandboxes/{sandbox_id}")
    assert del_resp2.status_code == 200
    assert del_resp2.json()["status"] == "destroyed"


def test_api_execute_in_sandbox(client: TestClient):
    """Test POST /api/v1/sandboxes/{sandbox_id}/execute runs code and records history."""
    create_resp = client.post("/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 180})
    sandbox_id = create_resp.json()["sandbox_id"]

    exec_payload = {"code": "print(10 * 10)"}
    exec_resp = client.post(f"/api/v1/sandboxes/{sandbox_id}/execute", json=exec_payload)

    assert exec_resp.status_code == 200
    data = exec_resp.json()
    assert data["sandbox_id"] == sandbox_id
    assert data["status"] == "completed"
    assert data["exit_code"] == 0
    assert data["stdout"].strip() == "100"
    assert "execution_id" in data
    assert data["submitted_at"] is not None
    assert data["completed_at"] is not None

    # Check that execution count incremented in get_sandbox
    get_resp = client.get(f"/api/v1/sandboxes/{sandbox_id}")
    assert get_resp.json()["executions_count"] == 1


def test_api_execute_on_destroyed_sandbox_fails(client: TestClient):
    """Test executing code on a destroyed sandbox returns 400."""
    create_resp = client.post("/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 180})
    sandbox_id = create_resp.json()["sandbox_id"]

    client.delete(f"/api/v1/sandboxes/{sandbox_id}")

    exec_resp = client.post(
        f"/api/v1/sandboxes/{sandbox_id}/execute",
        json={"code": "print('fail')"},
    )
    assert exec_resp.status_code == 400
    data = exec_resp.json()
    assert data["error"] == "SandboxDestroyedError"


def test_api_execute_on_unknown_sandbox_returns_404(client: TestClient):
    """Test executing on a non-existent sandbox returns 404."""
    random_id = uuid.uuid4()
    response = client.post(f"/api/v1/sandboxes/{random_id}/execute", json={"code": "print('fail')"})
    assert response.status_code == 404
    assert response.json()["error"] == "SandboxNotFoundError"


def test_api_get_execution_result_success(client: TestClient):
    """Test GET /api/v1/sandboxes/{sandbox_id}/executions/{execution_id}."""
    create_resp = client.post("/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 180})
    sandbox_id = create_resp.json()["sandbox_id"]

    exec_resp = client.post(
        f"/api/v1/sandboxes/{sandbox_id}/execute",
        json={"code": "print('API job lookup')"},
    )
    assert exec_resp.status_code == 200
    execution_id = exec_resp.json()["execution_id"]

    get_exec_resp = client.get(f"/api/v1/sandboxes/{sandbox_id}/executions/{execution_id}")
    assert get_exec_resp.status_code == 200
    data = get_exec_resp.json()
    assert data["execution_id"] == execution_id
    assert data["sandbox_id"] == sandbox_id
    assert data["status"] == "completed"
    assert "API job lookup" in data["stdout"]
    assert data["exit_code"] == 0


def test_api_get_execution_result_not_found(client: TestClient):
    """Test GET on unknown execution ID returns 404 ExecutionNotFoundError."""
    create_resp = client.post("/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 180})
    sandbox_id = create_resp.json()["sandbox_id"]
    random_exec_id = uuid.uuid4()

    response = client.get(f"/api/v1/sandboxes/{sandbox_id}/executions/{random_exec_id}")
    assert response.status_code == 404
    assert response.json()["error"] == "ExecutionNotFoundError"


def test_api_get_execution_result_mismatched_sandbox(client: TestClient):
    """Test GET execution under a different sandbox ID returns 404 ExecutionNotFoundError."""
    s1_resp = client.post("/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 180})
    sandbox1_id = s1_resp.json()["sandbox_id"]
    s2_resp = client.post("/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 180})
    sandbox2_id = s2_resp.json()["sandbox_id"]

    exec_resp = client.post(
        f"/api/v1/sandboxes/{sandbox1_id}/execute",
        json={"code": "print('s1')"},
    )
    execution_id = exec_resp.json()["execution_id"]

    # Attempt fetching sandbox 1's execution under sandbox 2
    response = client.get(f"/api/v1/sandboxes/{sandbox2_id}/executions/{execution_id}")
    assert response.status_code == 404
    assert response.json()["error"] == "ExecutionNotFoundError"


def test_api_list_sandboxes(client: TestClient):
    """Test GET /api/v1/sandboxes retrieves list of all sandboxes with details."""
    s1_resp = client.post("/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 180})
    s1_id = s1_resp.json()["sandbox_id"]
    s2_resp = client.post("/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 300})
    s2_id = s2_resp.json()["sandbox_id"]

    list_resp = client.get("/api/v1/sandboxes")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert isinstance(items, list)
    ids = [item["sandbox_id"] for item in items]
    assert s1_id in ids
    assert s2_id in ids

    # Validate structure
    target = next(item for item in items if item["sandbox_id"] == s1_id)
    assert target["runtime"] == "python"
    assert target["status"] == "running"
    assert "executions_count" in target
    assert "resource_config" in target
    assert "expires_at" in target


def test_api_list_sandbox_executions(client: TestClient):
    """Test GET /api/v1/sandboxes/{sandbox_id}/executions returns execution list."""
    create_resp = client.post("/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 180})
    sandbox_id = create_resp.json()["sandbox_id"]

    # Initial list is empty
    empty_resp = client.get(f"/api/v1/sandboxes/{sandbox_id}/executions")
    assert empty_resp.status_code == 200
    assert empty_resp.json() == []

    # Execute code
    exec_resp = client.post(
        f"/api/v1/sandboxes/{sandbox_id}/execute",
        json={"code": "print('hello list executions')"},
    )
    assert exec_resp.status_code == 200
    exec_id = exec_resp.json()["execution_id"]

    # Now list contains the execution
    list_resp = client.get(f"/api/v1/sandboxes/{sandbox_id}/executions")
    assert list_resp.status_code == 200
    executions = list_resp.json()
    assert len(executions) == 1
    assert executions[0]["execution_id"] == exec_id
    assert executions[0]["sandbox_id"] == sandbox_id
    assert executions[0]["status"] == "completed"
    assert "hello list executions" in executions[0]["stdout"]


def test_api_list_sandbox_executions_not_found(client: TestClient):
    """Test GET /api/v1/sandboxes/{unknown}/executions returns 404."""
    random_id = uuid.uuid4()
    response = client.get(f"/api/v1/sandboxes/{random_id}/executions")
    assert response.status_code == 404
    assert response.json()["error"] == "SandboxNotFoundError"

