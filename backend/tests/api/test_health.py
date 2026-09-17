"""Tests for health and readiness probes."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_docker_client_dependency
from app.main import app


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient fixture."""
    return TestClient(app)


def test_health_liveness(client: TestClient):
    """Test that GET /health returns 200 OK and service metadata."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "ai-sandbox-platform"


def test_ready_success(client: TestClient):
    """Test that GET /ready returns 200 when Docker engine is reachable."""
    response = client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["docker"] == "connected"


def test_ready_docker_unavailable(client: TestClient):
    """Test that GET /ready returns 503 when Docker engine fails connectivity ping."""
    mock_docker = MagicMock()
    mock_docker.ping.side_effect = Exception("Connection refused to docker daemon")

    app.dependency_overrides[get_docker_client_dependency] = lambda: mock_docker
    try:
        response = client.get("/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "not_ready"
        assert data["docker"] == "unavailable"
    finally:
        app.dependency_overrides.clear()
