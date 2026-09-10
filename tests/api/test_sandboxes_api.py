"""Tests for Sandbox Execution API endpoints."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_sandbox_service
from app.core.exceptions import ConcurrencyLimitError, DockerEngineError
from app.main import app
from app.services.sandbox_service import SandboxService


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient fixture."""
    return TestClient(app)


def test_api_execute_success(client: TestClient):
    """Test successful Python code execution via POST /api/v1/sandboxes/execute."""
    payload = {"code": "print(2 + 2)"}
    response = client.post("/api/v1/sandboxes/execute", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["exit_code"] == 0
    assert data["stdout"].strip() == "4"
    assert data["stderr"] == ""
    assert data["stdout_truncated"] is False
    assert data["stderr_truncated"] is False
    assert "sandbox_id" in data
    assert data["duration_ms"] >= 0


def test_api_execute_syntax_error(client: TestClient):
    """Test syntax error execution via API."""
    payload = {"code": "def invalid_syntax(:"}
    response = client.post("/api/v1/sandboxes/execute", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["exit_code"] != 0
    assert "SyntaxError" in data["stderr"]


def test_api_execute_runtime_error(client: TestClient):
    """Test runtime division by zero via API."""
    payload = {"code": "print(1 / 0)"}
    response = client.post("/api/v1/sandboxes/execute", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["exit_code"] != 0
    assert "ZeroDivisionError" in data["stderr"]


def test_api_execute_timeout(client: TestClient):
    """Test infinite loop timeout via API with custom timeout override."""
    payload = {"code": "while True: pass", "timeout_seconds": 2.0}
    response = client.post("/api/v1/sandboxes/execute", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "timed_out"
    assert data["exit_code"] is None


def test_api_execute_excessive_output(client: TestClient):
    """Test excessive output truncation via API."""
    payload = {
        "code": "import sys\nsys.stdout.write('A' * 500000)\nsys.stderr.write('B' * 500000)",
        "timeout_seconds": 5.0,
    }
    response = client.post("/api/v1/sandboxes/execute", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["stdout_truncated"] is True
    assert data["stderr_truncated"] is True


def test_api_execute_invalid_payload_empty_code(client: TestClient):
    """Test validation rejection for empty code string."""
    response = client.post("/api/v1/sandboxes/execute", json={"code": ""})
    assert response.status_code == 422
    data = response.json()
    assert data["error"] == "ValidationError"
    assert "errors" in data["details"]


def test_api_execute_invalid_payload_blank_code(client: TestClient):
    """Test validation rejection for whitespace-only code string."""
    response = client.post("/api/v1/sandboxes/execute", json={"code": "   \n\t  "})
    assert response.status_code == 422
    data = response.json()
    assert data["error"] == "ValidationError"


def test_api_execute_invalid_timeout(client: TestClient):
    """Test validation rejection for timeout below minimum bound."""
    payload = {"code": "pass", "timeout_seconds": 0.1}
    response = client.post("/api/v1/sandboxes/execute", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["error"] == "ValidationError"


def test_api_execute_oversized_code(client: TestClient):
    """Test validation rejection for code payload exceeding 1MB limit."""
    oversized = "a = 1\n" * 200_000  # > 1MB
    response = client.post("/api/v1/sandboxes/execute", json={"code": oversized})
    assert response.status_code == 422
    data = response.json()
    assert data["error"] == "ValidationError"


def test_api_concurrency_rejection(client: TestClient):
    """Test that HTTP 429 is returned when concurrency limit is reached."""
    mock_service = MagicMock(spec=SandboxService)
    mock_service.execute_code.side_effect = ConcurrencyLimitError("Concurrency limit reached")

    app.dependency_overrides[get_sandbox_service] = lambda: mock_service
    try:
        response = client.post("/api/v1/sandboxes/execute", json={"code": "print('hi')"})
        assert response.status_code == 429
        data = response.json()
        assert data["error"] == "ConcurrencyLimitError"
        assert "Concurrency limit reached" in data["message"]
    finally:
        app.dependency_overrides.clear()


def test_api_docker_unavailable_error_mapping(client: TestClient):
    """Test that DockerEngineError maps to HTTP 503 without leaking stack traces."""
    mock_service = MagicMock(spec=SandboxService)
    mock_service.execute_code.side_effect = DockerEngineError("Docker daemon socket closed")

    app.dependency_overrides[get_sandbox_service] = lambda: mock_service
    try:
        response = client.post("/api/v1/sandboxes/execute", json={"code": "print('hi')"})
        assert response.status_code == 503
        data = response.json()
        assert data["error"] == "DockerEngineError"
        assert "temporarily unavailable" in data["message"]
        # Ensure no tracebacks leaked
        assert "Traceback" not in response.text
    finally:
        app.dependency_overrides.clear()
