"""Tests for production HTTP API admission control."""

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_settings
from app.core.config import SandboxSettings
from app.main import app


@pytest.fixture
def production_client() -> TestClient:
    config = SandboxSettings(ENVIRONMENT="production", API_KEY="test-api-key")
    app.dependency_overrides[get_settings] = lambda: config
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_production_api_rejects_missing_key(production_client: TestClient):
    response = production_client.post("/api/v1/sandboxes/execute", json={"code": "print(1)"})
    assert response.status_code == 401
    assert response.json()["detail"] == "A valid X-API-Key is required."


def test_production_api_rejects_incorrect_key(production_client: TestClient):
    response = production_client.post(
        "/api/v1/sandboxes/execute",
        json={"code": "print(1)"},
        headers={"X-API-Key": "incorrect"},
    )
    assert response.status_code == 401


def test_production_api_accepts_valid_key(production_client: TestClient):
    response = production_client.post(
        "/api/v1/sandboxes/execute",
        json={"code": ""},
        headers={"X-API-Key": "test-api-key"},
    )
    assert response.status_code == 422


def test_health_endpoint_remains_unauthenticated(production_client: TestClient):
    response = production_client.get("/health")
    assert response.status_code == 200


def test_production_workspace_endpoints_enforce_api_key(production_client: TestClient):
    """Verify all workspace API endpoints reject missing and invalid X-API-Key headers."""
    fake_id = "00000000-0000-0000-0000-000000000001"
    endpoints = [
        ("POST", f"/api/v1/sandboxes/{fake_id}/files", {"path": "a.txt", "content": "x"}),
        ("GET", f"/api/v1/sandboxes/{fake_id}/files", None),
        ("GET", f"/api/v1/sandboxes/{fake_id}/files/a.txt", None),
        ("POST", f"/api/v1/sandboxes/{fake_id}/directories", {"path": "dir"}),
        ("DELETE", f"/api/v1/sandboxes/{fake_id}/files/a.txt", None),
    ]
    for method, url, payload in endpoints:
        resp_missing = production_client.request(method, url, json=payload)
        assert resp_missing.status_code == 401
        assert resp_missing.json()["detail"] == "A valid X-API-Key is required."

        resp_invalid = production_client.request(
            method,
            url,
            json=payload,
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp_invalid.status_code == 401
