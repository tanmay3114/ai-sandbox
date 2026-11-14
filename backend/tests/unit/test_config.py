"""Unit tests for configuration validation and properties."""

# pyrefly: ignore [missing-import]
import pytest
from pydantic import ValidationError

from app.core.config import SandboxSettings


@pytest.fixture(autouse=True)
def verify_no_container_leak():
    """Config unit tests do not interact with Docker."""
    yield


def test_default_settings(monkeypatch):
    monkeypatch.delenv("SANDBOX_PROJECT_LABEL", raising=False)
    monkeypatch.delenv("SANDBOX_MANAGED_BY_LABEL", raising=False)
    monkeypatch.delenv("SANDBOX_ENVIRONMENT", raising=False)
    settings = SandboxSettings()
    assert settings.MEMORY_LIMIT == "256m"
    assert settings.CPU_LIMIT == 0.5
    assert settings.nano_cpus == 500_000_000
    assert settings.TIMEOUT_SECONDS == 5.0
    assert settings.MAX_STDOUT_BYTES == 65536
    assert settings.PIDS_LIMIT == 32
    assert settings.GLOBAL_CONCURRENCY_LIMIT == 4
    assert settings.PROJECT_LABEL == "ai-sandbox"


def test_reject_floating_latest_image():
    with pytest.raises(ValidationError) as excinfo:
        SandboxSettings(BASE_IMAGE="python:latest")
    assert "immutable image digest" in str(excinfo.value)


def test_reject_invalid_cpu_limit():
    with pytest.raises(ValidationError):
        SandboxSettings(CPU_LIMIT=0.0)

    with pytest.raises(ValidationError):
        SandboxSettings(CPU_LIMIT=10.0)


def test_reject_invalid_timeout():
    with pytest.raises(ValidationError):
        SandboxSettings(TIMEOUT_SECONDS=0.1)

    with pytest.raises(ValidationError):
        SandboxSettings(TIMEOUT_SECONDS=120.0)


def test_accept_qemu_and_reject_unimplemented_backend():
    s = SandboxSettings(BACKEND="qemu")
    assert s.BACKEND == "qemu"

    with pytest.raises(ValidationError) as excinfo:
        SandboxSettings(BACKEND="firecracker")
    assert "Only 'docker' and 'qemu' are implemented" in str(excinfo.value)


def test_custom_valid_settings():
    s = SandboxSettings(
        CPU_LIMIT=1.5,
        TIMEOUT_SECONDS=10.0,
        MAX_STDOUT_BYTES=131072,
        PIDS_LIMIT=64,
        BASE_IMAGE="python@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea",
    )
    assert s.nano_cpus == 1_500_000_000
    assert s.TIMEOUT_SECONDS == 10.0
    assert s.MAX_STDOUT_BYTES == 131072
    assert s.PIDS_LIMIT == 64


def test_production_requires_an_api_key(monkeypatch):
    monkeypatch.delenv("SANDBOX_API_KEY", raising=False)
    with pytest.raises(ValidationError) as excinfo:
        SandboxSettings(ENVIRONMENT="production")
    assert "SANDBOX_API_KEY is required" in str(excinfo.value)


def test_staging_api_key_enables_api_authentication():
    s = SandboxSettings(ENVIRONMENT="staging", API_KEY="test-secret")
    assert s.api_auth_required is True


def test_reject_unpinned_allowed_runtime_image():
    with pytest.raises(ValidationError) as excinfo:
        SandboxSettings(ALLOWED_RUNTIMES={"python": "python:3.12-slim"})
    assert "allowed python runtime" in str(excinfo.value)
